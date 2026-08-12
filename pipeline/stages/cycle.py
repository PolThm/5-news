"""One cycle: collect, dedupe, and record what happened.

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

Story 3.4 adds AD-11's two-phase split on top of collect-through-history: a
fresh cycle (no pending batch recorded in `cycle.json`) runs every guarded
step below exactly as before, then submits a summarize batch and returns
without waiting. A later invocation of the *same* `cycle_id` finds the
pending batch ID in `cycle.json` and skips straight to checking it -- collect
through history never re-runs. Checking is a single call, never a poll loop:
if the batch is not done, this run records that it checked and exits; the
next invocation checks again. Neither phase holds a process open waiting on
the Batch API (AD-11's own words).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pipeline.adapters import CollectionResult, Failure
from pipeline.adapters.cohere_embed import embed_titles
from pipeline.domain import OutputLanguage
from pipeline.stages import DEFAULT_DATA_ROOT, cycle_id_for, output_dir_for, read_jsonl
from pipeline.stages.cluster import EmbedFn, run_cluster
from pipeline.stages.collect import write_collection
from pipeline.stages.dedupe import run_dedupe
from pipeline.stages.history import append_history
from pipeline.stages.rank import run_rank
from pipeline.stages.summarize import (
    WrittenSubmission,
    WrittenSummarize,
    collect_summarize,
    submit_summarize,
)


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
    # a cycle can complete every guarded step below and still be
    # "summarize_pending" (batch submitted, not yet checked) or
    # "summarize_collected" (batch ended, results written). `None` means
    # this run didn't reach the summarize phase at all (a crash upstream).
    summarize_phase: str | None = None

    @property
    def degraded(self) -> bool:
        return bool(self.failures)


def _read_pending_batch(cycle_path: Path) -> dict | None:
    """The pending-batch section of a previous run's `cycle.json`, if this
    `cycle_id` already submitted one -- `None` if `cycle.json` doesn't exist
    yet, or exists but records no pending batch (a fresh cycle, or one that
    crashed before reaching the summarize phase).

    Reading, not holding this in memory across invocations, is the whole
    point of AD-11: the *file* is the durable state a separate process
    invocation resumes from, not anything this function remembers.
    """
    if not cycle_path.is_file():
        return None
    try:
        record = json.loads(cycle_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    pending = record.get("summarize_batch")
    if not pending or not pending.get("batch_id"):
        return None
    return pending


def run_cycle(
    collect: Callable[[], CollectionResult],
    cycle_id: str | None = None,
    data_root: Path = DEFAULT_DATA_ROOT,
    embed: EmbedFn = embed_titles,
    language: OutputLanguage = OutputLanguage.FR,
    submit_summarize_fn: Callable[..., WrittenSubmission] = submit_summarize,
    collect_summarize_fn: Callable[..., WrittenSummarize | None] = collect_summarize,
) -> CycleResult:
    """Run collect, then dedupe, then cluster, then rank, then history, then
    submit (or, on a resumed invocation, check) a summarize batch.

    ``collect`` and ``embed`` are both injected so a cycle can be exercised
    without a network — the scheduled entrypoint passes the real adapters.

    Each cycle writes into its own ``<cycle-id>`` directory and never touches a
    previous one: a failed cycle leaves yesterday's committed output exactly as
    it was (AD-7).
    """
    started_at = datetime.now(UTC)
    cycle_id = cycle_id or cycle_id_for(started_at)
    cycle_path = data_root / "intermediate" / cycle_id / "cycle.json"

    # Resume case: this cycle_id already submitted a batch on a previous
    # invocation. Skip collect through history entirely -- they already ran
    # -- and go straight to checking the batch (AD-11: "does not re-run
    # collect/dedupe/cluster/rank", read literally).
    pending = _read_pending_batch(cycle_path)
    if pending is not None:
        return _resume_cycle(cycle_path, pending, collect_summarize_fn=collect_summarize_fn)

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

    # Every step below is guarded, because cycle.json is the only tracked file
    # and it is written last. A crash anywhere in here without a record leaves
    # nothing in git at all — the silent gap this whole function exists to
    # prevent. A malformed line from a truncated earlier run is enough to
    # trigger it: read_jsonl raises, and so does ArticleRecord.from_dict.
    try:
        written = write_collection(collection, cycle_id=cycle_id, data_root=data_root)
        articles_path = written.articles_path
        articles_collected = written.article_count
    except Exception as exc:  # noqa: BLE001
        failures.append(Failure("cycle", f"writing collection raised: {exc}"))
        completed = False

    if completed:
        try:
            deduped = run_dedupe(articles_path, cycle_id=cycle_id, data_root=data_root, embed=embed)
            dedupe_path = deduped.output_path
            groups_after_dedupe = deduped.groups_out
        except Exception as exc:  # noqa: BLE001
            failures.append(Failure("cycle", f"dedupe raised: {exc}"))
            completed = False

    if completed:
        try:
            clustered = run_cluster(
                dedupe_path, cycle_id=cycle_id, data_root=data_root, embed=embed
            )
            cluster_path = clustered.output_path
            clusters_after_grouping = clustered.clusters_out
            if clustered.degraded:
                detail = "clustering degraded: embedding failed, no cross-language merge"
                failures.append(Failure("cycle", detail))
        except Exception as exc:  # noqa: BLE001
            failures.append(Failure("cycle", f"clustering raised: {exc}"))
            completed = False

    if completed:
        try:
            ranked = run_rank(cluster_path, cycle_id=cycle_id, data_root=data_root)
            rank_path = ranked.output_path
            clusters_selected = ranked.clusters_selected
        except Exception as exc:  # noqa: BLE001
            # Unlike cluster's embedding call, rank has no external dependency
            # — every input is already on disk and validated. An exception
            # here is a real bug, not a degraded-but-expected outcome. Still
            # guarded, for the same reason every stage before it is: cycle.json
            # must survive a crash regardless of where it originates.
            failures.append(Failure("cycle", f"ranking raised: {exc}"))
            completed = False

    if completed:
        try:
            selected = list(read_jsonl(rank_path)) if rank_path else []
            append_history(
                selected,
                cycle_id=cycle_id,
                history_root=data_root / "history",
                embed=embed,
            )
        except Exception as exc:  # noqa: BLE001
            # Same reasoning as rank: no external dependency of its own once
            # `selected` is in hand (the embed call inside append_history
            # degrades gracefully on its own, per its docstring) — an
            # exception escaping here is a real bug. Still guarded: cycle.json
            # must survive a crash regardless of where it originates.
            failures.append(Failure("cycle", f"writing history raised: {exc}"))
            completed = False

    # Only a completed cycle has ranked Clusters to submit. A crash upstream
    # means there is nothing to summarize yet -- record the crash and stop.
    # This cycle_id itself is never revisited: the next scheduled run gets a
    # fresh cycle_id and starts over from collect (AD-7's "leaves the
    # previous Briefing set in place"), it does not resume this one's
    # already-collected data.
    summarize_phase: str | None = None
    summarize_batch: dict | None = None
    if completed:
        submission = submit_summarize_fn(
            selected, language=language, cycle_id=cycle_id, data_root=data_root
        )
        if submission.batch_id is not None:
            summarize_phase = "summarize_submitted"
            summarize_batch = {
                "batch_id": submission.batch_id,
                "language": language.value,
                "ranked_path": str(rank_path),
            }
        else:
            # Submission itself failed (e.g. no API key) -- degrade, same as
            # every other adapter-boundary failure in this function, rather
            # than treating it as a reason to mark the whole cycle failed.
            failures.append(Failure("cycle", "summarize submission failed; see summarize.json"))
            summarize_phase = "summarize_submit_failed"

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
                "summarize_batch": summarize_batch,
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


def _resume_cycle(
    cycle_path: Path,
    pending: dict,
    collect_summarize_fn: Callable[..., WrittenSummarize | None],
) -> CycleResult:
    """The second-invocation half of AD-11's two-phase cycle: collect
    through history already ran (recorded in this same `cycle.json`) --
    only check the pending batch, once, and never re-derive anything the
    first invocation already wrote.

    Guarded the same way every stage in ``run_cycle`` is: a crash checking
    the batch (a network blip, a malformed ``ranked.jsonl`` left by a
    truncated earlier write) must degrade this run, not raise past it and
    leave ``cycle.json`` stuck mid-resume with no record of what happened
    (AD-10).
    """
    record = json.loads(cycle_path.read_text(encoding="utf-8"))
    cycle_id = record["cycle_id"]
    data_root = cycle_path.parent.parent.parent
    language = OutputLanguage(pending["language"])
    ranked_path = Path(pending["ranked_path"])

    failures = [Failure(f["adapter"], f["detail"]) for f in record.get("failures", [])]
    try:
        clusters = list(read_jsonl(ranked_path)) if ranked_path.is_file() else []
        collected = collect_summarize_fn(
            pending["batch_id"],
            clusters,
            language=language,
            cycle_id=cycle_id,
            data_root=data_root,
        )
    except Exception as exc:  # noqa: BLE001 - adapter boundary, must not raise past it
        failures.append(Failure("cycle", f"checking summarize batch raised: {exc}"))
        record["last_checked_at"] = datetime.now(UTC).isoformat()
        record["degraded"] = True
        record["failures"] = [f.to_dict() for f in failures]
        phase = record["phase"]
        collected = None
    else:
        if collected is None:
            # Still pending -- record that a check happened, but do not touch
            # the pending batch ID itself, so the *next* invocation resumes
            # the same wait rather than starting a new batch (AD-11's exact
            # words).
            record["last_checked_at"] = datetime.now(UTC).isoformat()
            phase = record["phase"]
        else:
            failures.extend(collected.failures)
            record["phase"] = "summarize_collected"
            record["summarize_batch"] = None  # resolved -- nothing left to resume
            record["degraded"] = bool(failures)
            record["failures"] = [f.to_dict() for f in failures]
            phase = "summarize_collected"

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
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="pipeline.stages.cycle")
    parser.add_argument("--cycle-id", default=None)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT, type=Path)
    args = parser.parse_args(argv)

    from pipeline.stages.collect import collect_all

    result = run_cycle(collect=collect_all, cycle_id=args.cycle_id, data_root=args.data_root)

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
