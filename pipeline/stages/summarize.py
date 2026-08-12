"""Summarize stage: the AI stage, and the only one that calls a model.

AD-6's exact boundary: input is a Briefing that is already ordered and
counted (whatever `run_rank` produced). Output is Summary text keyed to
Cluster identity, plus (Story 3.3) an `outbound_url`/`outbound_source` pair
this stage now also owns. This stage may not add, remove, reorder, or
renumber anything -- every field on a ranked Cluster dict besides these is
owned by an earlier stage and is copied through unchanged, never recomputed
(AD-12).

One language per call (Story 3.2's explicit scope). Story 3.2's own
orchestration calls this three times per cycle, once per Output Language.
Output is written under a language-scoped subdirectory so those three calls
never overwrite each other's output.

A summarize failure for one Cluster degrades that item's `summary` to its
title; it never fails the whole Briefing (AD-6, mirroring AD-10's "one
failure degrades, never aborts" pattern already used throughout this
pipeline). `outbound_url`/`outbound_source` are unaffected by a degrade --
they are attached from the same representative member regardless of
whether summarization succeeded, so a reader always has a genuine Article
to click through to. A representative with no usable `url`/`source` (a
malformed member, or an empty string) degrades both fields to `None`
rather than crashing or rendering a broken link.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pipeline.adapters.claude import SummarizeResult, summarize_clusters
from pipeline.domain import OutputLanguage
from pipeline.stages import (
    DEFAULT_DATA_ROOT,
    cycle_id_for,
    read_jsonl,
    stage_arg_parser,
    write_atomically,
    write_jsonl,
)

STAGE = "summarize"

# summarize_clusters's real signature also takes optional `client` and
# `poll_interval_seconds` for injection; this alias only describes the
# two-argument shape every call site here actually uses.
SummarizeFn = Callable[[list[dict], OutputLanguage], SummarizeResult]


def _representative_member(cluster: dict) -> dict | None:
    """The Article this Cluster is represented by wherever a single member
    must stand in for the whole Cluster: earliest-published, then URL as a
    stable tiebreak -- the *exact* convention `dedupe.py`'s
    `ArticleGroup.representative` and `cluster.py`'s `coverage_for_cluster`
    already use one layer down (both tiebreak on `url`, never `title` --
    titles are not guaranteed unique the way URLs are). `members` is sorted
    by title, not publish order (Story 3.1, Task 0), so this must be
    recomputed here rather than assumed from list position.

    `None` for a Cluster with no members -- the `link_across_days`
    history-only-clique case (Story 3.1, Task 0) legitimately produces one;
    there is nothing to be representative of.
    """
    members = cluster.get("members", [])
    if not members:
        return None
    return min(members, key=lambda m: (m.get("published_at", ""), m["url"]))


def _degrade_title(cluster: dict, representative: dict | None) -> str:
    """The representative title for a degraded Cluster -- see
    `_representative_member` for the selection convention. Takes the
    already-selected representative for the same reason
    `_select_outbound_link` does: one `_representative_member` call per
    Cluster, shared between both derivations."""
    if representative is None:
        return cluster["cluster_id"]
    return representative["title"]


def _select_outbound_link(representative: dict | None) -> tuple[str | None, str | None]:
    """The `(outbound_url, outbound_source)` every Briefing item carries
    (Story 3.3, FR-14) -- from the same representative member
    `_earliest_member_title` selects for the degrade path, applied here for
    every Cluster regardless of whether summarization succeeded or
    degraded, so a reader always has a genuine Article to click through to.

    Takes the already-selected representative (rather than the Cluster
    itself) so a caller that also needs `_earliest_member_title`'s degrade
    text for the same Cluster doesn't pay for `_representative_member`'s
    `min()` scan twice.

    Degrades to `(None, None)` for: a Cluster with no members (matching
    `_representative_member`'s own `None`); a representative missing
    `source` (a malformed upstream member must not crash the whole
    summarize call, per AD-10 -- it degrades only this Cluster's link); and
    a representative whose `url` or `source` is present but an empty
    string, which would otherwise render as a broken, empty href on the
    display side rather than being caught here.
    """
    if representative is None:
        return None, None
    url = representative.get("url") or None
    source = representative.get("source") or None
    return url, source


@dataclass(frozen=True, slots=True)
class WrittenSummarize:
    output_path: Path
    metadata_path: Path
    clusters_summarized: int
    degraded: bool


def run_summarize(
    clusters: list[dict],
    language: OutputLanguage,
    cycle_id: str,
    data_root: Path = DEFAULT_DATA_ROOT,
    summarize_fn: SummarizeFn = summarize_clusters,
) -> WrittenSummarize:
    """Attach a `summary` field to each ranked Cluster, in `language`.

    `clusters` is `run_rank`'s output exactly as written -- not re-sorted,
    re-filtered, or re-sliced. `summarize_fn` is injected so this stage is
    tested without a network, matching every other adapter-boundary test in
    this pipeline. `language` is typed on `OutputLanguage` for static
    analysis and self-documentation -- since it's a `StrEnum`, this is not
    a runtime guard (see `summarize_clusters`'s docstring); the actual
    enforcement is `claude.py`'s `_LANGUAGE_NAMES` lookup raising on an
    unsupported value.
    """
    # Explicit .value rather than relying on OutputLanguage's StrEnum-ness
    # to stringify itself implicitly: the path segment and metadata field
    # below are records, not prompt instructions, and every other stage's
    # metadata already uses lowercase slugs for this kind of field. Only
    # claude.py's prompt text needed the human-readable name ("French").
    destination = data_root / "intermediate" / STAGE / cycle_id / language.value
    output_path = destination / "summarized.jsonl"
    metadata_path = destination / f"{STAGE}.json"

    result: SummarizeResult = summarize_fn(clusters, language) if clusters else SummarizeResult()

    degraded_cluster_ids: list[str] = []
    unlinked_cluster_ids: list[str] = []
    summarized_out: list[dict] = []
    for cluster in clusters:
        cluster_id = cluster["cluster_id"]
        # One _representative_member call per Cluster, shared between the
        # degrade-text and outbound-link derivations below.
        representative = _representative_member(cluster)

        summary = result.summaries.get(cluster_id)
        if summary is None:
            summary = _degrade_title(cluster, representative)
            degraded_cluster_ids.append(cluster_id)

        # outbound_url/outbound_source (Story 3.3, FR-14) are attached
        # regardless of whether summarization degraded -- a reader always
        # needs somewhere to click through to, independent of whether the
        # AI text is real or a fallback title.
        outbound_url, outbound_source = _select_outbound_link(representative)
        if outbound_url is None:
            unlinked_cluster_ids.append(cluster_id)

        summarized_out.append(
            {
                **cluster,
                "summary": summary,
                "outbound_url": outbound_url,
                "outbound_source": outbound_source,
            }
        )

    write_jsonl(output_path, summarized_out)

    metadata = {
        "stage": STAGE,
        "cycle_id": cycle_id,
        "language": language.value,
        "clusters_in": len(clusters),
        "clusters_summarized": len(summarized_out) - len(degraded_cluster_ids),
        "clusters_degraded": len(degraded_cluster_ids),
        "degraded_cluster_ids": sorted(degraded_cluster_ids),
        # A Cluster with no outbound link is a reader-facing shortfall in
        # its own right (Story 3.3) -- tracked here the same way
        # degraded_cluster_ids tracks a summary-text shortfall, per this
        # file's AD-6/AD-10 philosophy of stating every visible degrade
        # rather than letting it pass silently.
        "clusters_without_outbound_link": len(unlinked_cluster_ids),
        "clusters_without_outbound_link_ids": sorted(unlinked_cluster_ids),
        "failures": [f.to_dict() for f in result.failures],
    }
    write_atomically(
        metadata_path, json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )

    return WrittenSummarize(
        output_path=output_path,
        metadata_path=metadata_path,
        clusters_summarized=len(summarized_out),
        degraded=bool(degraded_cluster_ids),
    )


def main(argv: list[str] | None = None) -> int:
    parser = stage_arg_parser(STAGE)
    parser.add_argument(
        "--language", required=True, choices=[lang.value for lang in OutputLanguage]
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"input not found or not a file: {args.input}", file=sys.stderr)
        return 1

    cycle_id = args.cycle_id or cycle_id_for(datetime.now())
    clusters = list(read_jsonl(args.input))
    written = run_summarize(
        clusters,
        language=OutputLanguage(args.language),
        cycle_id=cycle_id,
        data_root=args.data_root,
    )

    print(f"{STAGE}: {written.clusters_summarized} summarized -> {written.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
