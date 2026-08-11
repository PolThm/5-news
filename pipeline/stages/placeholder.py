"""A stage that does nothing but prove the contract runs.

It exists to demonstrate that a stage can be invoked alone from the command
line against a saved input and write JSON Lines output — the property AD-3
requires and the Build Order's inspection window depends on.

This is not a real stage and must not grow into one. Story 1.2 adds `collect`
as a sibling module following the same shape; delete this file once a real
stage has replaced its demonstration value.
"""

from __future__ import annotations

import sys

from pipeline.stages import (
    cycle_id_for,
    output_dir_for,
    read_jsonl,
    stage_arg_parser,
    write_jsonl,
)

STAGE = "placeholder"


def main(argv: list[str] | None = None) -> int:
    args = stage_arg_parser(STAGE).parse_args(argv)

    if not args.input.exists():
        print(f"input not found: {args.input}", file=sys.stderr)
        return 1

    cycle_id = args.cycle_id or cycle_id_for()
    destination = output_dir_for(STAGE, cycle_id, root=args.data_root) / "output.jsonl"

    written = write_jsonl(destination, read_jsonl(args.input))

    print(f"{STAGE}: {written} records -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
