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
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pipeline.adapters import CollectionResult, Failure
from pipeline.stages import DEFAULT_DATA_ROOT, cycle_id_for
from pipeline.stages.collect import write_collection
from pipeline.stages.dedupe import run_dedupe


@dataclass(frozen=True, slots=True)
class CycleResult:
    """What one cycle produced, and where it landed."""

    cycle_id: str
    articles_collected: int
    groups_after_dedupe: int
    collect_path: Path
    dedupe_path: Path
    cycle_path: Path
    failures: tuple[Failure, ...]
    completed: bool = True

    @property
    def degraded(self) -> bool:
        return bool(self.failures)


def run_cycle(
    collect: Callable[[], CollectionResult],
    cycle_id: str | None = None,
    data_root: Path = DEFAULT_DATA_ROOT,
) -> CycleResult:
    """Run collect, then dedupe, then write the cycle record.

    ``collect`` is injected so a cycle can be exercised without a network —
    the scheduled entrypoint passes the real adapters.

    Each cycle writes into its own ``<cycle-id>`` directory and never touches a
    previous one: a failed cycle leaves yesterday's committed output exactly as
    it was (AD-7).
    """
    started_at = datetime.now(UTC)
    cycle_id = cycle_id or cycle_id_for(started_at)

    try:
        collection = collect()
    except Exception as exc:  # noqa: BLE001 - last line of defense; a crash must leave a record
        collection = CollectionResult(
            articles=[],
            failures=[Failure("cycle", f"collection raised: {exc}")],
        )

    written = write_collection(collection, cycle_id=cycle_id, data_root=data_root)
    deduped = run_dedupe(written.articles_path, cycle_id=cycle_id, data_root=data_root)

    # Cross-phase state lives beside the cycle, not under a stage: a later run
    # reads this to resume (AD-11, and Story 3.4's two-phase batch depends on
    # exactly this path).
    cycle_path = data_root / "intermediate" / cycle_id / "cycle.json"
    cycle_path.parent.mkdir(parents=True, exist_ok=True)
    cycle_path.write_text(
        json.dumps(
            {
                "cycle_id": cycle_id,
                "started_at": started_at.isoformat(),
                "phase": "collected",
                "articles_collected": written.article_count,
                "groups_after_dedupe": deduped.groups_out,
                "degraded": bool(collection.failures),
                "failures": [f.to_dict() for f in collection.failures],
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
        articles_collected=written.article_count,
        groups_after_dedupe=deduped.groups_out,
        collect_path=written.articles_path,
        dedupe_path=deduped.output_path,
        cycle_path=cycle_path,
        failures=tuple(collection.failures),
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
        f"-> {result.groups_after_dedupe} groups"
    )
    # A degraded cycle still succeeded. Only a cycle that could not run at all
    # is a failure, and that path raises before reaching here.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
