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


def test_ignores_prose_in_comments_mentioning_pipeline(sandbox: Path) -> None:
    """Regression guard for the false-positive this check's own comment
    stripping exists to avoid (Story 4.6): a comment that merely *mentions*
    "pipeline/" while explaining the architectural boundary itself (this
    codebase's own comments do this extensively) must never be flagged as
    a real code reference."""
    probe = sandbox / "site" / "src" / "_probe.ts"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(
        "// This file must never import from pipeline/ -- see AD-2.\n"
        "/**\n"
        " * pipeline/domain's own documented range for this field.\n"
        " */\n"
        "const clean = 1;\n"
    )

    result = run_check(sandbox)
    assert result.returncode == 0, result.stdout + result.stderr


def test_catches_a_violation_on_a_line_starting_with_a_multiplication_operator(
    sandbox: Path,
) -> None:
    """Story 4.6's adversarial review caught a real gap in an earlier
    version of this check's comment-exclusion fix: a whole-line exclusion
    keyed on the line's leading character (`//` or `*`) cannot distinguish
    a JSDoc continuation line from an unrelated continuation line that
    happens to start with a multiplication operator. The current
    comment-STRIPPING approach (not line-exclusion) must still catch this."""
    probe = sandbox / "site" / "src" / "_probe.ts"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(
        "const weight = getBase()\n"
        '  * fetchWeight("pipeline/rating-secret.json");\n'
    )

    result = run_check(sandbox)
    assert result.returncode != 0
    assert "references pipeline/ by path" in result.stdout


def test_catches_a_violation_that_trails_a_same_line_comment(sandbox: Path) -> None:
    """A real violation must still be caught even when a comment follows it
    on the same line -- only the comment portion should be stripped, not
    the whole line."""
    probe = sandbox / "site" / "src" / "_probe.ts"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text('import x from "../pipeline/secret"; // trailing comment\n')

    result = run_check(sandbox)
    assert result.returncode != 0
    assert "references pipeline/ by path" in result.stdout


def test_catches_site_referencing_an_ai_provider(sandbox: Path) -> None:
    """Violation mode 4 (Story 3.6, AD-1): site/ must never call an AI,
    embedding, or ingestion provider -- its only input is the static JSON
    the pipeline already wrote under data/briefings/."""
    probe = sandbox / "site" / "src" / "_probe.ts"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("const key = process.env.ANTHROPIC_API_KEY;\n")

    result = run_check(sandbox)
    assert result.returncode != 0
    assert "AI/embedding/ingestion provider" in result.stdout


@pytest.mark.parametrize(
    "snippet",
    [
        "import Anthropic from '@anthropic-ai/sdk';",
        "const client = new Cohere.Client();",
        "// fetched via cohere-embed-v3",
        "const url = 'https://api.gdelt.org/api/v2/doc/doc';",
        "const key = process.env.NEWSAPI_KEY;",
    ],
)
def test_catches_every_provider_name_in_the_alternation(sandbox: Path, snippet: str) -> None:
    """Each token in the check's regex alternation (anthropic, cohere,
    gdelt, newsapi) is exercised individually -- a narrower pattern here
    (e.g. one requiring an exact identifier like ANTHROPIC_API_KEY) would
    have silently let a hyphenated or differently-cased real-world
    reference like "cohere-embed-v3" through untested."""
    probe = sandbox / "site" / "src" / "_probe.ts"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(snippet + "\n")

    result = run_check(sandbox)
    assert result.returncode != 0, f"expected a violation for: {snippet!r}"
    assert "AI/embedding/ingestion provider" in result.stdout


def test_a_clean_site_with_only_briefings_json_references_passes(sandbox: Path) -> None:
    """Regression guard: reading data/briefings/ (the pipeline's real,
    intended output) must never trip the AI-provider tripwire."""
    probe = sandbox / "site" / "src" / "_probe.ts"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text('const path = "../../data/briefings/fr/world/day.json";\n')

    result = run_check(sandbox)
    assert result.returncode == 0, result.stdout + result.stderr
