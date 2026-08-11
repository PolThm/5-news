"""Proof that scripts/check-boundary.sh actually catches what it claims to.

AC 4 requires this be proven, not asserted: "The check must actually fail on
a deliberately introduced violation — prove it." The Dev Agent Record for
Story 1.1 originally carried this proof only as a hand-typed transcript in
Completion Notes, with no committed artifact — flagged in code review as
unverifiable from the diff alone. This test is the fix.

Each violation is planted in a throwaway copy of the tree, never in the real
pipeline/site directories, so a failing assertion here never leaves a stray
file behind in the working repository.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check-boundary.sh"


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A throwaway copy of pipeline/, site/, and the script itself.

    Copying rather than running in place means a planted violation can never
    leak into the real tree, even if an assertion fails mid-test.
    """
    for name in ("pipeline", "site", "scripts"):
        src = REPO_ROOT / name
        if src.exists():
            shutil.copytree(src, tmp_path / name, ignore=shutil.ignore_patterns("node_modules"))
    return tmp_path


def run_check(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(cwd / "scripts" / "check-boundary.sh")],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_clean_tree_passes(sandbox: Path) -> None:
    result = run_check(sandbox)
    assert result.returncode == 0, result.stdout + result.stderr


def test_catches_python_reading_site_by_path(sandbox: Path) -> None:
    """Violation mode 1: pipeline/ reads site/ files by path."""
    probe = sandbox / "pipeline" / "stages" / "_probe.py"
    probe.write_text('from pathlib import Path\nBAD = Path("site/src/pages")\n')

    result = run_check(sandbox)
    assert result.returncode != 0
    assert "references site/ by path" in result.stdout


def test_catches_site_importing_across_the_boundary(sandbox: Path) -> None:
    """Violation mode 2: site/ imports across ../../pipeline."""
    probe = sandbox / "site" / "src" / "_probe.ts"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("import { thing } from '../../pipeline/domain';\n")

    result = run_check(sandbox)
    assert result.returncode != 0
    assert "imports across the pipeline boundary" in result.stdout


def test_catches_site_referencing_pipeline_by_path(sandbox: Path) -> None:
    """Violation mode 3: site/ references pipeline/ in a string literal."""
    probe = sandbox / "site" / "src" / "_probe.ts"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text('const p = "pipeline/config/zones.json";\n')

    result = run_check(sandbox)
    assert result.returncode != 0
    assert "references pipeline/ by path" in result.stdout


def test_does_not_flag_stdlib_site_module(sandbox: Path) -> None:
    """Regression guard for the false-positive this check deliberately avoids:
    `site` is a Python standard library module. A naive `import site` rule
    would fire on legitimate code."""
    probe = sandbox / "pipeline" / "stages" / "_probe.py"
    probe.write_text("import site\n")

    result = run_check(sandbox)
    assert result.returncode == 0, result.stdout + result.stderr
