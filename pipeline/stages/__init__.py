"""The stage contract.

Every stage reads its input from disk and writes its output to disk, and is
invocable alone against a saved input:

    python -m pipeline.stages.<name> --input <path> [--cycle-id <id>]

Stages never hand data to each other in memory or through a shared mutable
object. This is what makes the Build Order's inspection window possible — the
author must be able to run collect and dedupe for days and look at the output
before anything downstream exists (AD-3).

Output lands at ``data/intermediate/<stage>/<cycle-id>/`` as JSON Lines, one
record per line. These files are read by a human during the inspection window,
so they are written with sorted keys and a trailing newline: stable bytes make
diffs between cycles readable.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DATA_ROOT = Path("data")


def cycle_id_for(instant: datetime | None = None) -> str:
    """A cycle identifier derived from a UTC instant.

    The format is deliberately digit-first and colon-free. Digit-first because
    ``data/intermediate/`` holds both ``<stage>/<cycle-id>/`` and
    ``<cycle-id>/cycle.json`` as siblings — a cycle id that collided with a
    stage name would corrupt both trees, and no stage name starts with a
    digit. Colon-free because colons are not path-safe everywhere.
    """
    moment = instant or datetime.now(UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


def output_dir_for(stage: str, cycle_id: str, root: Path = DEFAULT_DATA_ROOT) -> Path:
    """Where a stage writes: ``<root>/intermediate/<stage>/<cycle-id>/``."""
    return root / "intermediate" / stage / cycle_id


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Read JSON Lines, skipping blank lines."""
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    """Write JSON Lines with stable bytes, returning the record count.

    Sorted keys and a trailing newline are not cosmetic: intermediate output is
    inspected by hand and diffed between cycles during the Build Order's
    inspection window. Unstable ordering would make every diff unreadable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False))
            handle.write("\n")
            count += 1
    return count


def stage_arg_parser(stage: str) -> argparse.ArgumentParser:
    """The command-line surface every stage shares.

    Flag names are fixed here so later stages inherit them rather than each
    inventing its own.
    """
    parser = argparse.ArgumentParser(prog=f"pipeline.stages.{stage}")
    parser.add_argument("--input", required=True, type=Path, help="path to this stage's input")
    parser.add_argument(
        "--cycle-id",
        default=None,
        help="cycle identifier; defaults to a UTC timestamp derived at invocation",
    )
    parser.add_argument(
        "--data-root",
        default=DEFAULT_DATA_ROOT,
        type=Path,
        help="root of the data directory (default: ./data)",
    )
    return parser


__all__ = [
    "DEFAULT_DATA_ROOT",
    "cycle_id_for",
    "output_dir_for",
    "read_jsonl",
    "stage_arg_parser",
    "write_jsonl",
]
