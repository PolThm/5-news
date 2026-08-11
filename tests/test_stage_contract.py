"""Every stage reads a path and writes a path, and runs alone (AC 5, AD-3).

This is what makes the Build Order's inspection window possible: the author
must be able to run collect and dedupe for days and look at the output before
anything downstream exists.
"""

import json
import subprocess
import sys
from pathlib import Path

from pipeline.stages import cycle_id_for, output_dir_for


def test_cycle_id_cannot_collide_with_a_stage_name() -> None:
    """data/intermediate/ holds <stage>/<cycle-id>/ and <cycle-id>/cycle.json
    as siblings. A cycle id equal to a stage name would corrupt both."""
    from pipeline.config import STAGE_NAMES

    cid = cycle_id_for()
    assert cid not in STAGE_NAMES
    assert cid[0].isdigit(), "cycle id must start with a digit, by construction"


def test_cycle_id_is_utc_and_path_safe() -> None:
    cid = cycle_id_for()
    assert cid.endswith("Z")
    assert ":" not in cid, "colons are not path-safe on every filesystem"
    assert "/" not in cid


def test_output_dir_shape() -> None:
    d = output_dir_for("collect", "2026-08-11T00-00-00Z", root=Path("/tmp/x"))
    assert d == Path("/tmp/x/intermediate/collect/2026-08-11T00-00-00Z")


def test_placeholder_stage_runs_alone(tmp_path: Path) -> None:
    """Invoke the stage from the command line with an input path, with no
    other stage involved, and confirm it writes JSON Lines output."""
    src = tmp_path / "in.jsonl"
    src.write_text('{"title": "one"}\n{"title": "two"}\n')

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pipeline.stages.placeholder",
            "--input",
            str(src),
            "--cycle-id",
            "2026-08-11T00-00-00Z",
            "--data-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    out = tmp_path / "intermediate" / "placeholder" / "2026-08-11T00-00-00Z" / "output.jsonl"
    assert out.exists(), f"stage wrote nothing to {out}"

    lines = out.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["title"] == "one"


def test_stage_output_is_stable_across_runs(tmp_path: Path) -> None:
    """Committed intermediate files must diff readably during the inspection
    window: stable key ordering, trailing newline, no embedded raw newlines."""
    src = tmp_path / "in.jsonl"
    src.write_text('{"b": 2, "a": 1}\n')

    def run() -> str:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pipeline.stages.placeholder",
                "--input",
                str(src),
                "--cycle-id",
                "2026-08-11T00-00-00Z",
                "--data-root",
                str(tmp_path),
            ],
            capture_output=True,
            check=True,
        )
        return (
            tmp_path / "intermediate" / "placeholder" / "2026-08-11T00-00-00Z" / "output.jsonl"
        ).read_text()

    first = run()
    assert first == run(), "re-running on identical input must be byte-identical"
    assert first.endswith("\n"), "trailing newline at EOF"
    assert first.startswith('{"a": 1'), "keys must be sorted for readable diffs"
