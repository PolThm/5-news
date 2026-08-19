"""One cycle: collect, dedupe, cluster, rank per Zone x Period, summarize per
Output Language, and publish -- the whole pipeline, orchestrated.

Story 1.5 turns the pipeline from something you invoke into something that
accumulates. The Build Order's inspection window — days of real output to judge
the filter against before any interface exists — only happens if cycles run
without anyone starting them.

The cycle record is the point. A day with 40 articles could be a quiet news day
or a throttled upstream, and weeks later nobody remembers which. Recording the
failures alongside the counts is what makes thin coverage interpretable instead
of merely suspicious.

A cycle always completes. Upstream failures degrade it (AD-10); an unexpected
crash is caught and recorded rather than left as a silent gap. Exit status
reports whether the cycle *ran*, not whether coverage was perfect — a scheduled
job that goes red on a thin day trains its owner to ignore it.

Story 3.4 added AD-11's two-phase split on top of collect-through-history: a
fresh cycle (no pending batch recorded in `cycle.json`) runs every guarded
step below exactly as before, then submits a summarize batch and returns
without waiting. A later invocation of the *same* `cycle_id` finds the
pending batch ID in `cycle.json` and skips straight to checking it -- collect
through history never re-runs. Checking is a single call, never a poll loop:
if the batch is not done, this run records that it checked and exits; the
next invocation checks again. Neither phase holds a process open waiting on
the Batch API (AD-11's own words).

Story 3.5 replaces the flat, single-Zone rank call and single-language
summarize call with the real 15 Zone x 3 Period matrix
(`pipeline.stages.briefing_matrix`) and submits exactly 3 summarize batches
per cycle (one per Output Language, shared across every Zone x Period via a
deduplicated Cluster union -- Story 3.5's fan-out decision). A cycle is not
ready to publish until every language's batch has collected; `_resume_cycle`
checks whichever languages are still pending and leaves already-resolved
ones untouched. Once all three have collected, this same resumed invocation
assembles and publishes the 135-Briefing set atomically (AD-7).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pipeline.adapters import CollectionResult, Failure
from pipeline.adapters.cohere_embed import EmbeddingResult, embed_titles
from pipeline.config import OUTPUT_LANGUAGES, zone_by_slug
from pipeline.domain import OutputLanguage, Period
from pipeline.stages import (
    DEFAULT_DATA_ROOT,
    cycle_id_for,
    output_dir_for,
    read_jsonl,
    trace,
    write_atomically,
    write_jsonl,
)
from pipeline.stages.briefing_matrix import build_period_pools, dedupe_union, rank_all_zones
from pipeline.stages.cluster import EmbedFn, run_cluster
from pipeline.stages.collect import write_collection
from pipeline.stages.dedupe import run_dedupe
from pipeline.stages.history import append_history, read_history
from pipeline.stages.publish import WrittenPublish, assemble_briefings, publish_briefings
from pipeline.stages.rank import ZoneRanking
from pipeline.stages.summarize import (
    WrittenSubmission,
    WrittenSummarize,
    collect_summarize,
    submit_summarize,
)

_HISTORY_RETENTION_DAYS = 30

# Below this many dedupe groups, a 1:1 group-to-Cluster ratio is the correct
# outcome rather than a symptom -- two unrelated articles SHOULD stay apart --
# so the merged-nothing diagnostic below only fires on a real corpus.
_MERGE_DIAGNOSTIC_FLOOR = 50





@dataclass(frozen=True, slots=True)
class CycleResult:
    """What one cycle produced, and where it landed."""

    cycle_id: str
    articles_collected: int
    groups_after_dedupe: int
    clusters_after_grouping: int
    clusters_selected: int
    collect_path: Path
    # None means the stage never ran or crashed before writing — distinct from
    # a Path, which always means the file actually exists. An adversarial
    # review of Story 2.2 found these previously defaulted to the *expected*
    # output path even on a crash, so a caller checking e.g. `rank_path.exists()`
    # after a failed cycle would get a false negative rather than an explicit
    # "this was never written."
    dedupe_path: Path | None
    cluster_path: Path | None
    rank_path: Path | None
    cycle_path: Path
    failures: tuple[Failure, ...]
    completed: bool = True
    # Story 3.4's two-phase summarize status, distinct from `completed` --
    # a cycle can complete every guarded step below and still be pending on
    # one or more languages' batches. Story 3.5 adds the terminal
    # "published" phase once every language has collected. `None` means
    # this run didn't reach the summarize phase at all (a crash upstream).
    summarize_phase: str | None = None
    # Story 3.5: set once this cycle's Briefing set has actually been
    # written to data/briefings/ -- distinct from summarize_phase, which
    # only tracks the summarize batches' own state.
    published: bool = False
    briefings_path: Path | None = None


# "abandoned" is terminal for the same reason "collected" is: there is no
# useful work a later invocation could do. A cycle reaches it when the
# Clusters its batches were submitted for are gone for good (see the
# ranked.jsonl branch in _resume_cycle) -- without this, find_resumable_cycle_id
# would return that dead cycle on every run and the pipeline would retry it
# forever, never collecting again.
_TERMINAL_PHASES = frozenset(
    {
        None,
        "collected",
        # No useful work a later invocation could do:
        #
        # "abandoned" -- the Clusters this cycle's batches were submitted for
        #   are gone for good (see the ranked.jsonl branch in _resume_cycle).
        # "summarize_submit_failed" -- submission never produced a batch id,
        #   so summarize_batches is empty and there is nothing to poll. A real
        #   cycle sat in this phase (2026-08-14T06-53-46Z, zero Clusters
        #   selected so nothing was submitted) and, without this entry, was
        #   returned by find_resumable_cycle_id on every run -- blocking every
        #   future cycle from collecting at all.
        #
        # A fresh cycle_id starts over from collect instead, per AD-7.
        "abandoned",
        "summarize_submit_failed",
    }
)


def _should_resume(cycle_path: Path) -> bool:
    """Whether this `cycle_id` has unfinished work from a previous
    invocation to resume -- `False` if `cycle.json` doesn't exist yet, or
    exists but never reached the summarize phase (a crash upstream, so
    `phase` is still `"collected"`), or has already published (nothing left
    to resume).

    Deliberately keyed on `published`, not on whether `summarize_batches`
    is empty: every language's batch can have collected while publish
    itself still failed (a crash during staging) -- that cycle must still
    resume on the next invocation, straight to retrying publish, not fall
    through to a fresh cycle that re-submits batches for data already
    collected and sitting on disk.

    Reading, not holding this in memory across invocations, is the whole
    point of AD-11: the *file* is the durable state a separate process
    invocation resumes from, not anything this function remembers.
    """
    if not cycle_path.is_file():
        return False
    try:
        record = json.loads(cycle_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if record.get("phase") in _TERMINAL_PHASES:
        return False
    return not record.get("published", False)


def find_resumable_cycle_id(data_root: Path = DEFAULT_DATA_ROOT) -> str | None:
    """The most recent cycle_id with unfinished summarize/publish work, or
    ``None`` when there is nothing to resume.

    AD-11's two-phase cycle only completes if a *later* invocation picks up
    the batches an earlier one submitted. Nothing did: the scheduled workflow
    runs `python -m pipeline.stages.cycle` with no `--cycle-id`, so every run
    minted a fresh id, `_should_resume` was asked about a path that had just
    been created, and the pending cycle was silently abandoned along with the
    batches it had already paid for. Phase two existed and was tested, but
    was unreachable in production.

    Newest-first because cycle ids are digit-first UTC timestamps and sort
    lexicographically: if several cycles are somehow pending, the freshest is
    the one whose batches are least likely to have expired (the Batch API
    keeps results 29 days).
    """
    intermediate = data_root / "intermediate"
    if not intermediate.is_dir():
        return None
    for candidate in sorted((p for p in intermediate.iterdir() if p.is_dir()), reverse=True):
        if _should_resume(candidate / "cycle.json"):
            return candidate.name
    return None


def memoize_embeddings(embed: EmbedFn) -> EmbedFn:
    """Wrap an ``EmbedFn`` so a title is only ever sent once per cycle.

    A cycle embeds three times: dedupe layer 3 over its groups' titles,
    cluster over the groups dedupe returned, and `_embed_for_linking` over
    the Clusters cluster returned. Each set is a near-subset of the one
    before -- the stages only ever merge, never invent titles -- so the same
    strings were being paid for and waited on three times. Measured on the
    2026-08-19 cycle: 103 + 98 + 97 batches, ~380s of a 396s run, i.e. the
    overwhelming majority of the cycle spent re-deriving vectors it already
    had.

    Wrapping here rather than inside ``embed_titles`` keeps the cache's
    lifetime exactly one cycle: a module-level cache would persist across a
    resumed invocation and quietly serve vectors from a different corpus,
    and ``embed_titles`` itself has no notion of a cycle to scope to. Every
    stage already takes ``embed`` by injection, so nothing downstream
    changes.

    Three properties the callers depend on and this preserves:

    - Positional alignment. Vectors come back in the order of ``titles``,
      duplicates included, because every stage zips them against its own
      input by index.
    - All-or-nothing failure. A failed or short response is returned
      untouched, never partially cached, so a stage still sees the failure
      it would have seen and degrades the same way (AD-10).
    - Nothing cached unverified. Only a response whose length matches the
      request is stored, so a truncated one cannot poison later lookups.
    """
    cache: dict[str, list[float]] = {}

    def embed_with_cache(titles: list[str]) -> EmbeddingResult:
        # dict.fromkeys dedupes while preserving first-seen order, which also
        # collapses repeats *within* one call -- two dedupe groups can share a
        # representative title.
        missing = [title for title in dict.fromkeys(titles) if title not in cache]
        if missing:
            result = embed(missing)
            if result.failures or len(result.vectors) != len(missing):
                return result
            cache.update(zip(missing, result.vectors, strict=True))
        return EmbeddingResult(vectors=[cache[title] for title in titles])

    return embed_with_cache


def run_cycle(
    collect: Callable[[], CollectionResult],
    cycle_id: str | None = None,
    data_root: Path = DEFAULT_DATA_ROOT,
    embed: EmbedFn = embed_titles,
    submit_summarize_fn: Callable[..., WrittenSubmission] = submit_summarize,
    collect_summarize_fn: Callable[..., WrittenSummarize | None] = collect_summarize,
) -> CycleResult:
    """Run collect, then dedupe, then cluster, then the 15 Zone x 3 Period
    ranking matrix, then history, then submit (or, on a resumed invocation,
    check) a summarize batch per Output Language, then, once every
    language has collected, assemble and publish the 135-Briefing set.

    ``collect`` and ``embed`` are both injected so a cycle can be exercised
    without a network — the scheduled entrypoint passes the real adapters.

    Each cycle writes into its own ``<cycle-id>`` directory and never touches a
    previous one: a failed cycle leaves yesterday's committed output exactly as
    it was (AD-7).
    """
    started_at = datetime.now(UTC)
    cycle_id = cycle_id or cycle_id_for(started_at)
    cycle_path = data_root / "intermediate" / cycle_id / "cycle.json"

    # Resume case: this cycle_id has unfinished summarize/publish work from
    # a previous invocation. Skip collect through history entirely -- they
    # already ran -- and go straight to checking whichever languages are
    # still pending, or straight to retrying publish if every language has
    # already collected (AD-11: "does not re-run collect/dedupe/cluster/
    # rank", read literally).
    if _should_resume(cycle_path):
        return _resume_cycle(cycle_path, collect_summarize_fn=collect_summarize_fn)

    failures: list[Failure] = []
    completed = True

    try:
        collection = collect()
    except Exception as exc:  # noqa: BLE001 - last line of defense; a crash must leave a record
        collection = CollectionResult(articles=[])
        failures.append(Failure("cycle", f"collection raised: {exc}"))

    failures.extend(collection.failures)

    articles_path = output_dir_for("collect", cycle_id, root=data_root) / "articles.jsonl"
    dedupe_path: Path | None = None
    cluster_path: Path | None = None
    rank_path: Path | None = None
    articles_collected = 0
    groups_after_dedupe = 0
    clusters_after_grouping = 0
    clusters_selected = 0
    clusters: list[dict] = []

    embed = memoize_embeddings(embed)

    # Every step below is guarded, because cycle.json is the only tracked file
    # and it is written last. A crash anywhere in here without a record leaves
    # nothing in git at all — the silent gap this whole function exists to
    # prevent. A malformed line from a truncated earlier run is enough to
    # trigger it: read_jsonl raises, and so does ArticleRecord.from_dict.
    try:
        trace(f"collected {len(collection.articles)} articles; writing")
        written = write_collection(collection, cycle_id=cycle_id, data_root=data_root)
        articles_path = written.articles_path
        articles_collected = written.article_count
    except Exception as exc:  # noqa: BLE001
        failures.append(Failure("cycle", f"writing collection raised: {exc}"))
        completed = False

    if completed:
        try:
            trace(f"dedupe starting on {articles_collected} articles")
            deduped = run_dedupe(articles_path, cycle_id=cycle_id, data_root=data_root, embed=embed)
            dedupe_path = deduped.output_path
            groups_after_dedupe = deduped.groups_out
        except Exception as exc:  # noqa: BLE001
            failures.append(Failure("cycle", f"dedupe raised: {exc}"))
            completed = False

    if completed:
        try:
            trace(f"dedupe done -> {groups_after_dedupe} groups; cluster starting")
            clustered = run_cluster(
                dedupe_path, cycle_id=cycle_id, data_root=data_root, embed=embed
            )
            cluster_path = clustered.output_path
            clusters_after_grouping = clustered.clusters_out
            trace(
                f"cluster done -> {clusters_after_grouping} clusters, "
                f"degraded={clustered.degraded}"
            )
            clusters = list(read_jsonl(cluster_path))
            if clustered.degraded:
                detail = "clustering degraded: embedding failed, no cross-language merge"
                failures.append(Failure("cycle", detail))
            # Diagnostic: one Cluster per dedupe group means nothing merged
            # across sources, so no Cluster can reach the 2-Independent-Source
            # floor and the cycle selects zero -- publishing nothing while
            # still reporting success. Distinct from `degraded` above, which
            # only fires when embedding itself errored: a working embedding
            # call that merges nothing produces the same barren outcome and
            # was previously invisible.
            #
            # Gated on a real corpus: at small volumes a 1:1 ratio is the
            # correct outcome (two unrelated articles SHOULD stay apart), so
            # flagging it there would be a false positive on every small
            # cycle and every test fixture. The threshold is about having
            # enough articles that some overlap is expected, not a tuned
            # value.
            if (
                groups_after_dedupe >= _MERGE_DIAGNOSTIC_FLOOR
                and clusters_after_grouping == groups_after_dedupe
            ):
                failures.append(
                    Failure(
                        "cycle",
                        f"clustering merged nothing: {groups_after_dedupe} dedupe groups "
                        f"produced {clusters_after_grouping} Clusters (1:1). No Cluster can "
                        f"reach the 2-Independent-Source floor, so this cycle selects zero.",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            failures.append(Failure("cycle", f"clustering raised: {exc}"))
            completed = False

    zone_rankings: dict[Period, list[ZoneRanking]] = {}
    union: list[dict] = []
    if completed:
        try:
            history_entries = read_history(
                data_root / "history",
                reference_date=started_at,
                window_days=_HISTORY_RETENTION_DAYS,
            )
            trace(f"linking: embedding {len(clusters)} clusters + {len(history_entries)} history")
            embedding_by_id = _embed_for_linking(clusters, history_entries, embed)
            trace("linking: building period pools (cross-day linking runs here)")
            pools = build_period_pools(
                today_clusters=clusters,
                history_entries=history_entries,
                embedding_by_id=embedding_by_id,
                reference_date=started_at,
            )
            sizes = {period: len(pool) for period, pool in pools.items()}
            trace(f"linking: pools ready ({sizes}); ranking zones")
            for period, pool in pools.items():
                zone_rankings[period] = rank_all_zones(pool)
                trace(f"ranking: {period} done")
            union = dedupe_union([r for rankings in zone_rankings.values() for r in rankings])
            clusters_selected = len(union)
            trace(f"ranking: done -> {clusters_selected} selected")
            rank_path = output_dir_for("rank", cycle_id, root=data_root) / "ranked.jsonl"
            write_jsonl(rank_path, union)
            _write_zone_rankings(
                output_dir_for("rank", cycle_id, root=data_root) / "zone_rankings.json",
                zone_rankings,
            )
        except Exception as exc:  # noqa: BLE001
            # Unlike cluster's embedding call, ranking has no external
            # dependency of its own once `clusters` is in hand -- an
            # exception here is a real bug, not a degraded-but-expected
            # outcome. Still guarded, for the same reason every stage
            # before it is: cycle.json must survive a crash regardless of
            # where it originates.
            failures.append(Failure("cycle", f"ranking raised: {exc}"))
            completed = False

    if completed:
        try:
            append_history(
                union,
                cycle_id=cycle_id,
                history_root=data_root / "history",
                embed=embed,
            )
        except Exception as exc:  # noqa: BLE001
            # Same reasoning as ranking: no external dependency of its own
            # once `union` is in hand (the embed call inside append_history
            # degrades gracefully on its own, per its docstring) — an
            # exception escaping here is a real bug. Still guarded:
            # cycle.json must survive a crash regardless of where it
            # originates.
            failures.append(Failure("cycle", f"writing history raised: {exc}"))
            completed = False

    # Only a completed cycle has a ranked Cluster union to submit. A crash
    # upstream means there is nothing to summarize yet -- record the crash
    # and stop. This cycle_id itself is never revisited: the next scheduled
    # run gets a fresh cycle_id and starts over from collect (AD-7's
    # "leaves the previous Briefing set in place"), it does not resume this
    # one's already-collected data.
    summarize_phase: str | None = None
    summarize_batches: dict[str, dict] = {}
    if completed:
        any_failed = False
        for language in OUTPUT_LANGUAGES:
            submission = submit_summarize_fn(
                union, language=language, cycle_id=cycle_id, data_root=data_root
            )
            if submission.batch_id is not None:
                summarize_batches[language.value] = {
                    "batch_id": submission.batch_id,
                    "ranked_path": str(rank_path),
                }
            else:
                any_failed = True
                failures.append(
                    Failure(
                        "cycle",
                        f"summarize submission failed for {language.value}; see summarize.json",
                    )
                )
        summarize_phase = "summarize_submit_failed" if any_failed else "summarize_submitted"

    # Cross-phase state lives beside the cycle, not under a stage: a later run
    # reads this to resume (AD-11, and Story 3.4's two-phase batch depends on
    # exactly this path).
    cycle_path.parent.mkdir(parents=True, exist_ok=True)
    cycle_path.write_text(
        json.dumps(
            {
                "cycle_id": cycle_id,
                "started_at": started_at.isoformat(),
                "phase": summarize_phase or "collected",
                "articles_collected": articles_collected,
                "groups_after_dedupe": groups_after_dedupe,
                "clusters_after_grouping": clusters_after_grouping,
                "clusters_selected": clusters_selected,
                "completed": completed,
                "degraded": bool(failures),
                "failures": [f.to_dict() for f in failures],
                "summarize_batches": summarize_batches,
                "published": False,
                "briefings_path": None,
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return CycleResult(
        cycle_id=cycle_id,
        articles_collected=articles_collected,
        groups_after_dedupe=groups_after_dedupe,
        clusters_after_grouping=clusters_after_grouping,
        clusters_selected=clusters_selected,
        collect_path=articles_path,
        dedupe_path=dedupe_path,
        cluster_path=cluster_path,
        rank_path=rank_path,
        cycle_path=cycle_path,
        failures=tuple(failures),
        completed=completed,
        summarize_phase=summarize_phase,
    )


def _embed_for_linking(
    clusters: list[dict], history_entries: list[dict], embed: EmbedFn
) -> dict[str, list[float]]:
    """Every id `link_across_days` might need to compare: today's Clusters
    need a fresh embed call (their representative title); history entries
    already carry their own stored embedding (Story 2.7) -- no re-embedding
    of historical entries needed."""
    embedding_by_id: dict[str, list[float]] = {}
    embeddable = [c for c in clusters if c.get("members")]
    if embeddable:
        titles = [c["members"][0]["title"] for c in embeddable]
        result: EmbeddingResult = embed(titles)
        if not result.failures and len(result.vectors) == len(embeddable):
            for cluster, vector in zip(embeddable, result.vectors, strict=True):
                embedding_by_id[cluster["cluster_id"]] = list(vector)
    for entry in history_entries:
        if "embedding" in entry:
            embedding_by_id[entry["cluster_id"]] = entry["embedding"]
    return embedding_by_id


def _write_zone_rankings(path: Path, zone_rankings: dict[Period, list[ZoneRanking]]) -> None:
    data = {
        period.value: [
            {
                "requested_zone": r.requested_zone.slug,
                "served_zone": r.served_zone.slug,
                "ranked_clusters": r.ranked_clusters,
            }
            for r in rankings
        ]
        for period, rankings in zone_rankings.items()
    }
    write_atomically(path, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _read_zone_rankings(path: Path) -> dict[Period, list[ZoneRanking]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        Period(period_value): [
            ZoneRanking(
                requested_zone=zone_by_slug(r["requested_zone"]),
                served_zone=zone_by_slug(r["served_zone"]),
                ranked_clusters=r["ranked_clusters"],
            )
            for r in rankings
        ]
        for period_value, rankings in data.items()
    }


def _resume_cycle(
    cycle_path: Path,
    collect_summarize_fn: Callable[..., WrittenSummarize | None],
) -> CycleResult:
    """The second-invocation half of AD-11's two-phase cycle: collect
    through history already ran (recorded in this same `cycle.json`) --
    only check whichever languages' batches are still pending, and never
    re-derive anything the first invocation already wrote.

    Once every language has collected, this same invocation assembles and
    publishes the 135-Briefing set (Story 3.5) -- publishing is the
    terminal phase; nothing resumes after it for this `cycle_id`.

    Guarded the same way every stage in ``run_cycle`` is: a crash checking
    a batch (a network blip, a malformed ``ranked.jsonl`` left by a
    truncated earlier write) must degrade this run, not raise past it and
    leave ``cycle.json`` stuck mid-resume with no record of what happened
    (AD-10).
    """
    record = json.loads(cycle_path.read_text(encoding="utf-8"))
    cycle_id = record["cycle_id"]
    data_root = cycle_path.parent.parent.parent
    failures = [Failure(f["adapter"], f["detail"]) for f in record.get("failures", [])]

    summaries_by_language: dict[OutputLanguage, dict[str, dict]] = {}
    remaining_batches = dict(record.get("summarize_batches", {}))
    # Set when a batch's Clusters are gone for good -- see the ranked.jsonl
    # branch below. Terminal: the cycle is abandoned rather than retried.
    unrecoverable = False
    # The one shared union path every language was submitted against
    # (Story 3.5's fan-out decision) -- deliberately not re-derived from
    # whichever batch_info happens to be last-iterated below, since a
    # resume call with remaining_batches already empty (retrying publish
    # only) never enters that loop at all and still needs this for
    # CycleResult.rank_path.
    ranked_path = output_dir_for("rank", cycle_id, root=data_root) / "ranked.jsonl"

    for language_value, batch_info in list(remaining_batches.items()):
        language = OutputLanguage(language_value)
        batch_ranked_path = Path(batch_info["ranked_path"])
        if not batch_ranked_path.is_file():
            # Falling through with clusters=[] would call collect_summarize
            # with nothing to attach the returned text to: the batch would be
            # marked collected, its entry deleted, and the generated text
            # discarded -- silently, for work already paid for.
            #
            # But refusing forever is worse. ranked.jsonl is written by the
            # submitting run and only survives because it is committed; if it
            # is genuinely gone (a cycle submitted before that .gitignore fix,
            # or a run that never pushed), no future run can reconstruct it,
            # and holding the cycle open would make find_resumable_cycle_id
            # return it on every invocation -- the pipeline would retry a dead
            # cycle forever and never collect again.
            #
            # So: abandon it, loudly and terminally. `phase` becomes
            # "abandoned", which _should_resume treats as not-resumable, and
            # the next run starts a fresh cycle (AD-7: a failed cycle leaves
            # the previous Briefing set in place).
            failures.append(
                Failure(
                    "cycle",
                    f"{language_value}: ranked.jsonl missing at {batch_ranked_path} — the "
                    "Clusters this batch was submitted for cannot be recovered, so its "
                    "generated text is unusable; abandoning this cycle",
                )
            )
            unrecoverable = True
            continue
        try:
            clusters = list(read_jsonl(batch_ranked_path))
            collected = collect_summarize_fn(
                batch_info["batch_id"],
                clusters,
                language=language,
                cycle_id=cycle_id,
                data_root=data_root,
            )
        except Exception as exc:  # noqa: BLE001 - adapter boundary, must not raise past it
            failures.append(
                Failure("cycle", f"checking {language_value} summarize batch raised: {exc}")
            )
            record["last_checked_at"] = datetime.now(UTC).isoformat()
            continue

        if collected is None:
            # Still pending -- leave this language's entry in
            # remaining_batches untouched, so the *next* invocation resumes
            # the same wait rather than starting a new batch (AD-11's exact
            # words). Record that a check happened, for observability.
            record["last_checked_at"] = datetime.now(UTC).isoformat()
            continue

        failures.extend(collected.failures)
        summaries_by_language[language] = _summaries_from_output(collected.output_path)
        del remaining_batches[language_value]

    record["summarize_batches"] = remaining_batches
    record["degraded"] = bool(failures)
    record["failures"] = [f.to_dict() for f in failures]

    if unrecoverable:
        # Terminal, and deliberately not "published": nothing was published.
        # _should_resume treats any phase outside the pending set as
        # not-resumable, so the next run starts a fresh cycle instead of
        # retrying this one forever.
        record["phase"] = "abandoned"
        write_atomically(cycle_path, json.dumps(record, indent=2, sort_keys=True) + "\n")
        return CycleResult(
            cycle_id=cycle_id,
            articles_collected=record.get("articles_collected", 0),
            groups_after_dedupe=record.get("groups_after_dedupe", 0),
            clusters_after_grouping=record.get("clusters_after_grouping", 0),
            clusters_selected=record.get("clusters_selected", 0),
            collect_path=output_dir_for("collect", cycle_id, root=data_root) / "articles.jsonl",
            dedupe_path=None,
            cluster_path=None,
            rank_path=ranked_path if ranked_path.is_file() else None,
            cycle_path=cycle_path,
            failures=tuple(failures),
            completed=True,
            summarize_phase="abandoned",
            published=False,
        )

    published = False
    briefings_path: Path | None = None
    if not remaining_batches:
        # Every language has collected -- assemble and publish. A language
        # collected on an earlier invocation left no trace of its own
        # summaries here, so re-read every already-resolved language's
        # summarized.jsonl too, not just the ones just collected this call.
        for language in OUTPUT_LANGUAGES:
            if language not in summaries_by_language:
                output_path = (
                    data_root
                    / "intermediate"
                    / "summarize"
                    / cycle_id
                    / language.value
                    / "summarized.jsonl"
                )
                if output_path.is_file():
                    summaries_by_language[language] = _summaries_from_output(output_path)

        zone_rankings_path = output_dir_for("rank", cycle_id, root=data_root) / "zone_rankings.json"
        try:
            zone_rankings = _read_zone_rankings(zone_rankings_path)
            briefings = assemble_briefings(
                zone_rankings,
                summaries_by_language,
                generated_at=datetime.fromisoformat(record["started_at"]),
            )
            written: WrittenPublish = publish_briefings(briefings, data_root=data_root)
            published = True
            briefings_path = written.briefings_path
            record["phase"] = "published"
        except KeyError as exc:
            # A Zone or Period this cycle ranked no longer exists in
            # `pipeline.config`. Publish can never succeed for it, however many
            # times it is retried: the ranked output on disk was computed under
            # the old configuration and nothing re-derives it.
            #
            # This is why the distinction from `publish_failed` below matters.
            # `publish_failed` is deliberately resumable, so a transient
            # failure (a full disk, a crash mid-staging) gets retried. A
            # scope change is not transient, and leaving such a cycle
            # resumable blocks every future cycle from collecting at all --
            # the exact trap `_TERMINAL_PHASES` already records for
            # `summarize_submit_failed`. Observed for real on 2026-08-19,
            # when narrowing to 4 Zones left an in-flight cycle holding
            # `north-america` rankings.
            #
            # Abandoning loses this cycle's Briefings and its already-paid
            # summarize batches. That is the cheaper side of the trade: the
            # previous Briefing set stays in place (AD-7) and the next cycle
            # starts clean under the current config.
            failures.append(
                Failure("cycle", f"publish impossible under the current config: {exc}")
            )
            record["degraded"] = True
            record["failures"] = [f.to_dict() for f in failures]
            record["phase"] = "abandoned"
        except Exception as exc:  # noqa: BLE001 - adapter boundary, must not raise past it
            failures.append(Failure("cycle", f"publish raised: {exc}"))
            record["degraded"] = True
            record["failures"] = [f.to_dict() for f in failures]
            record["phase"] = "publish_failed"
    phase = record["phase"]

    record["published"] = published
    record["briefings_path"] = str(briefings_path) if briefings_path else None

    cycle_path.write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return CycleResult(
        cycle_id=cycle_id,
        articles_collected=record.get("articles_collected", 0),
        groups_after_dedupe=record.get("groups_after_dedupe", 0),
        clusters_after_grouping=record.get("clusters_after_grouping", 0),
        clusters_selected=record.get("clusters_selected", 0),
        collect_path=output_dir_for("collect", cycle_id, root=data_root) / "articles.jsonl",
        dedupe_path=None,
        cluster_path=None,
        rank_path=ranked_path if ranked_path.is_file() else None,
        cycle_path=cycle_path,
        failures=tuple(failures),
        completed=record.get("completed", True),
        summarize_phase=phase,
        published=published,
        briefings_path=briefings_path,
    )


def _summaries_from_output(output_path: Path) -> dict[str, dict]:
    """The Cluster-to-summarized-fields map `assemble_briefings` needs,
    rebuilt from an already-collected `summarized.jsonl` -- every collected
    Cluster already carries `summary`, `outbound_url`, `outbound_source`
    (Stories 3.1-3.3; FR-14). The whole dict is kept, not just `summary`,
    so `assemble_briefings` can attach the outbound link too -- dropping it
    here would silently defeat FR-14 for every published Briefing."""
    return {c["cluster_id"]: c for c in read_jsonl(output_path) if "summary" in c}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="pipeline.stages.cycle")
    parser.add_argument("--cycle-id", default=None)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT, type=Path)
    parser.add_argument(
        "--resume-only",
        action="store_true",
        help=(
            "Finish a cycle whose batches are pending, and do nothing at all if "
            "none is. For catch-up runs that must never start a fresh cycle."
        ),
    )
    args = parser.parse_args(argv)

    from pipeline.stages.collect import collect_all

    # Phase two before phase one: if a previous invocation submitted batches
    # and never got to publish, finish that cycle rather than starting a new
    # one whose batches would queue behind it. An explicit --cycle-id always
    # wins, so a human can still target one deliberately.
    cycle_id = args.cycle_id
    if cycle_id is None:
        resumable = find_resumable_cycle_id(args.data_root)
        if resumable is not None:
            print(f"cycle: resuming {resumable} (batches pending from an earlier run)")
            cycle_id = resumable

    # `--resume-only` exists so a catch-up trigger can be added for free.
    #
    # summarize is a two-phase batch (AD-11): the run that submits can never
    # publish, so something has to come back later. But a plain extra trigger
    # is not free -- a run with nothing to resume starts a whole new cycle
    # from collect, paying for another round of embeddings and summaries. That
    # is why there is exactly one scheduled follow-up rather than several, and
    # why a slow batch (the API guarantees 24h, not the ~30min observed) pushed
    # publication to the next day.
    #
    # With this flag a catch-up run is a no-op when there is nothing pending,
    # so more of them can be scheduled to close that window at zero cost.
    if args.resume_only and cycle_id is None:
        print("cycle: nothing pending to resume; --resume-only means no new cycle")
        return 0

    result = run_cycle(collect=collect_all, cycle_id=cycle_id, data_root=args.data_root)

    for failure in result.failures:
        print(f"cycle: degraded — {failure.adapter}: {failure.detail}", file=sys.stderr)

    print(
        f"cycle {result.cycle_id}: {result.articles_collected} articles "
        f"-> {result.groups_after_dedupe} groups -> {result.clusters_after_grouping} clusters "
        f"-> {result.clusters_selected} selected -> {result.summarize_phase}"
    )
    # A degraded cycle still succeeded. Only a cycle that could not run at all
    # is a failure, and that path raises before reaching here.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
