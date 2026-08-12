"""Summarize stage: the AI stage, and the only one that calls a model.

AD-6's exact boundary: input is a Briefing that is already ordered and
counted (whatever `run_rank` produced). Output is Summary text keyed to
Cluster identity. This stage may not add, remove, reorder, or renumber
anything -- every field on a ranked Cluster dict besides the new `summary`
key is owned by an earlier stage and is copied through unchanged, never
recomputed (AD-12).

One language per call (this story's explicit scope). Story 3.2 calls this
three times per cycle, once per Output Language. Output is written under a
language-scoped subdirectory so those three calls never overwrite each
other's output.

A summarize failure for one Cluster degrades that item to its title; it
never fails the whole Briefing (AD-6, mirroring AD-10's "one failure
degrades, never aborts" pattern already used throughout this pipeline).
AD-6's own text also names an "outbound link" as part of a degraded item --
attaching one is explicitly Story 3.3's job, not this story's (each
member's `url` is available for it to use); this stage's degrade path adds
only the title field, per this story's own AC3.
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


def _earliest_member_title(cluster: dict) -> str:
    """The representative title for a degraded Cluster: earliest-published,
    then URL as a stable tiebreak -- the *exact* convention `dedupe.py`'s
    `ArticleGroup.representative` and `cluster.py`'s `coverage_for_cluster`
    already use one layer down (both tiebreak on `url`, never `title` --
    titles are not guaranteed unique the way URLs are). `members` is sorted
    by title, not publish order (Story 3.1, Task 0), so this must be
    recomputed here rather than assumed from list position.
    """
    members = cluster.get("members", [])
    if not members:
        return cluster["cluster_id"]
    representative = min(
        members,
        key=lambda m: (m.get("published_at", ""), m["url"]),
    )
    return representative["title"]


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
    summarized_out: list[dict] = []
    for cluster in clusters:
        cluster_id = cluster["cluster_id"]
        summary = result.summaries.get(cluster_id)
        if summary is None:
            summary = _earliest_member_title(cluster)
            degraded_cluster_ids.append(cluster_id)
        summarized_out.append({**cluster, "summary": summary})

    write_jsonl(output_path, summarized_out)

    metadata = {
        "stage": STAGE,
        "cycle_id": cycle_id,
        "language": language.value,
        "clusters_in": len(clusters),
        "clusters_summarized": len(summarized_out) - len(degraded_cluster_ids),
        "clusters_degraded": len(degraded_cluster_ids),
        "degraded_cluster_ids": sorted(degraded_cluster_ids),
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
