"""Collect stage: gather Articles from every configured adapter.

The first stage of the pipeline and the one the Build Order says to stand up
first, run for days, and look at before building anything downstream. Its
output is deliberately raw — no judgment about importance has been applied yet.

Runs each adapter, merges what they returned, and writes two files:

    data/intermediate/collect/<cycle-id>/articles.jsonl
    data/intermediate/collect/<cycle-id>/collect.json

The second is the cycle record: how many Articles arrived and what failed to
arrive. A cycle where one upstream was rate-limited is not a failed cycle, but
it is a cycle whose coverage was thinner than usual, and a human inspecting the
output weeks later needs to be able to see that (AD-10, NFR-3).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.adapters import CollectionResult
from pipeline.stages import (
    DEFAULT_DATA_ROOT,
    cycle_id_for,
    output_dir_for,
    stage_arg_parser,
    write_atomically,
    write_jsonl,
)

STAGE = "collect"


@dataclass(frozen=True, slots=True)
class WrittenCollection:
    """Where a collection landed on disk."""

    articles_path: Path
    metadata_path: Path
    article_count: int


def write_collection(
    result: CollectionResult,
    cycle_id: str,
    data_root: Path = DEFAULT_DATA_ROOT,
) -> WrittenCollection:
    """Write a collection's Articles and its cycle record.

    Both files are written even when nothing was collected: an empty
    ``articles.jsonl`` next to a metadata file naming the failure says "the
    upstream was down", where a missing file says only "something went wrong,
    possibly with this code".
    """
    destination = output_dir_for(STAGE, cycle_id, root=data_root)
    articles_path = destination / "articles.jsonl"
    metadata_path = destination / f"{STAGE}.json"

    count = write_jsonl(articles_path, result.articles)

    metadata = {
        "stage": STAGE,
        "cycle_id": cycle_id,
        "article_count": count,
        "failures": [failure.to_dict() for failure in result.failures],
    }
    write_atomically(
        metadata_path, json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )

    return WrittenCollection(
        articles_path=articles_path,
        metadata_path=metadata_path,
        article_count=count,
    )


def collect_all() -> CollectionResult:
    """Run collection and return what it produced.

    One adapter, as of Story 6.2. There used to be two — GDELT's DOC 2.0 API
    plus eleven RSS feeds (Story 1.3) — on the reasoning that coverage should
    not depend on a single upstream. In practice the API was throttled in all
    eight recorded cycles and RSS carried the product alone, which is the
    opposite of the intended arrangement: a fallback doing all the work while
    the primary contributed nothing.

    Moving to GDELT's raw files removes the throttle that caused it (static
    files, no rate limit) and lifts the corpus from ~365 articles across 11
    outlets to ~26,000 across thousands. Losing the second adapter is a real
    tradeoff, taken deliberately: if the files become unreachable, this cycle
    publishes nothing and the previous Briefing set stays in place (AD-7),
    rather than degrading to partial coverage.

    Still deduplicates on URL: the same article appears in more than one
    15-minute slot, and in both the English and translingual files.
    """
    from pipeline.adapters.gdelt import collect_world_day

    merged = CollectionResult.merge([collect_world_day()])

    seen: set[str] = set()
    deduplicated: list[dict[str, Any]] = []
    for article in merged.articles:
        url = article.get("url", "")
        if url and url not in seen:
            seen.add(url)
            deduplicated.append(article)

    return CollectionResult(articles=deduplicated, failures=merged.failures)


def main(argv: list[str] | None = None) -> int:
    parser = stage_arg_parser(STAGE)
    # collect has no upstream stage to read from, so --input is optional here
    # and names a zone/period selection instead. Story 1.2 collects World/day;
    # widening to the full matrix is Story 1.5's scheduling concern.
    for action in parser._actions:  # noqa: SLF001 - argparse exposes no public API for this
        if action.dest == "input":
            action.required = False
    args = parser.parse_args(argv)

    cycle_id = args.cycle_id or cycle_id_for()
    result = collect_all()
    written = write_collection(result, cycle_id=cycle_id, data_root=args.data_root)

    for failure in result.failures:
        print(f"{STAGE}: degraded — {failure.adapter}: {failure.detail}", file=sys.stderr)

    print(f"{STAGE}: {written.article_count} articles -> {written.articles_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
