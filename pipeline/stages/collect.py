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

from pipeline.adapters import CollectionResult, Failure
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

    Two adapters, for two different jobs.

    `rss` reads the feeds serious newsrooms publish themselves -- ~1,100
    articles from Le Monde, Le Figaro, Libération, El País, the Guardian, the
    BBC, Der Spiegel, Repubblica, ANSA and others. This is the editorial
    substance. It was deleted in Story 6.2 and its absence was the single
    biggest reason the published Briefings read like an aggregator: measured
    2026-08-19, a GDELT-only cycle of 10,331 articles contained ZERO articles
    from Le Monde, Le Figaro, Libération, Reuters, AP, the NYT, the FT, El
    Mundo, Corriere or FAZ, while iheart.com alone supplied 298.

    `gdelt` supplies breadth -- ~10,000 articles across thousands of outlets in
    every language. On its own it is a long tail of local radio stations and
    portals; alongside a curated set it is what corroborates an event across
    countries, which is what the Consensus Score is for.

    Both are needed and neither is sufficient. Losing either degrades the cycle
    rather than failing it (AD-10): if the feeds are unreachable the corpus is
    broad but shallow, if GDELT is unreachable it is serious but narrow, and
    only losing both leaves nothing to publish (AD-7).

    Deduplicates on URL: the same article appears in more than one GKG slot, in
    both the English and translingual files, and in more than one feed of the
    same outlet (a front page and a section front overlap by design).
    """
    from pipeline.adapters.gdelt import collect_world_day
    from pipeline.adapters.rss import RssClient

    results = []
    for label, collect in (("rss", lambda: RssClient().collect()), ("gdelt", collect_world_day)):
        try:
            results.append(collect())
        except Exception as exc:  # noqa: BLE001 - adapter boundary (AD-10)
            results.append(CollectionResult(articles=[], failures=[Failure(label, str(exc))]))

    merged = CollectionResult.merge(results)

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
