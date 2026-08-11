"""Rank stage: the product's central judgment, and the only one made without
AI.

Every prior stage decides what a story *is* — one dispatch, one Event across
languages. This stage decides which Events are worth showing, and in what
order, using nothing but the integer counts dedupe and cluster already
computed. No model call, no randomness, no wall-clock read (AD-4): the same
input must produce the same five headlines every time, or the product's claim
to be a measurement rather than an opinion falls apart.

FR-6 makes one explicit, non-obvious choice: Independent Source count leads,
country count only breaks ties. A Cluster covered by 10 sources from 2
countries outranks one covered by 3 sources from 4 countries, even though the
second looks like it has "wider" reach. This was decided against the wider-
reach-first alternative during PRD creation and is binding — do not
reintroduce a weighted or country-first scheme here.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from pipeline.config import MAX_SELECTED_CLUSTERS, MIN_COUNTRIES, MIN_INDEPENDENT_SOURCES
from pipeline.stages import (
    DEFAULT_DATA_ROOT,
    cycle_id_for,
    output_dir_for,
    read_jsonl,
    stage_arg_parser,
    write_atomically,
    write_jsonl,
)

STAGE = "rank"


def qualifies(cluster: dict) -> bool:
    """PRD Glossary, Qualifying Cluster: at least 2 Independent Sources from
    at least 2 distinct countries. Both floors are independent and both must
    hold — 5 sources all from one country still fails."""
    return (
        cluster["independent_source_count"] >= MIN_INDEPENDENT_SOURCES
        and cluster["country_count"] >= MIN_COUNTRIES
    )


def rank_clusters(clusters: list[dict]) -> list[dict]:
    """Order Clusters by Consensus Score: Independent Source count descending,
    then country count descending, then ``cluster_id`` ascending as a stable,
    content-derived tiebreak.

    A single ``sorted()`` call with a tuple key is the whole mechanism — no
    library heuristic, no multi-pass logic, nothing that could hide
    non-determinism the way Story 2.1's HDBSCAN detour did. Negating the two
    count fields yields descending order for both while keeping the
    tiebreak's natural ascending order, all in one pass.
    """
    return sorted(
        clusters,
        key=lambda c: (-c["independent_source_count"], -c["country_count"], c["cluster_id"]),
    )


@dataclass(frozen=True, slots=True)
class WrittenRank:
    output_path: Path
    metadata_path: Path
    clusters_selected: int


def run_rank(
    input_path: Path,
    cycle_id: str,
    data_root: Path = DEFAULT_DATA_ROOT,
) -> WrittenRank:
    """Filter to Qualifying Clusters, rank them, and select at most
    ``MAX_SELECTED_CLUSTERS`` — never padded below that if fewer qualify
    (FR-4).
    """
    clusters = list(read_jsonl(input_path))
    destination = output_dir_for(STAGE, cycle_id, root=data_root)
    output_path = destination / "ranked.jsonl"
    metadata_path = destination / f"{STAGE}.json"

    qualifying = [c for c in clusters if qualifies(c)]
    ordered = rank_clusters(qualifying)
    selected = ordered[:MAX_SELECTED_CLUSTERS]

    ranked_out = [
        {**cluster, "rank": position} for position, cluster in enumerate(selected, start=1)
    ]
    write_jsonl(output_path, ranked_out)

    metadata = {
        "stage": STAGE,
        "cycle_id": cycle_id,
        "clusters_in": len(clusters),
        "clusters_qualifying": len(qualifying),
        "clusters_selected": len(selected),
        # Discarded Volume: everything considered minus everything selected —
        # a Cluster that never qualified and a Cluster that qualified but
        # ranked 6th or below are both discarded, for the same reason: the
        # reader never sees either one.
        "clusters_discarded": len(clusters) - len(selected),
    }
    write_atomically(
        metadata_path, json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )

    return WrittenRank(
        output_path=output_path,
        metadata_path=metadata_path,
        clusters_selected=len(selected),
    )


def main(argv: list[str] | None = None) -> int:
    args = stage_arg_parser(STAGE).parse_args(argv)

    if not args.input.is_file():
        print(f"input not found or not a file: {args.input}", file=sys.stderr)
        return 1

    cycle_id = args.cycle_id or cycle_id_for()
    written = run_rank(args.input, cycle_id=cycle_id, data_root=args.data_root)

    print(f"{STAGE}: {written.clusters_selected} selected -> {written.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
