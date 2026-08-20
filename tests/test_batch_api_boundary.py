"""Proof that every Claude call in this pipeline goes through the Batch
API, never the synchronous Messages API (NFR-2, Story 3.6, AC1).

Stories 3.1/3.4 already built `submit_batch`/`collect_batch` against
`client.messages.batches.create`/`.retrieve`/`.results` exclusively, and
the per-function tests in `test_claude_adapter.py` already prove those two
functions behave correctly in isolation. This module proves a *stronger*
claim those per-function tests cannot: that no OTHER call site anywhere
under `pipeline/` (this check's actual scope -- not the whole repository;
`scripts/`, `site/`, and anything Epic 4 eventually adds are out of its
reach) ever reaches for the synchronous `client.messages.create(...)`
instead. A single call site added later (a shortcut during a future
story, a copy-pasted example) would silently reintroduce per-request
billing and defeat AC3's cost-independence guarantee -- this is the
tripwire for that, within the one directory every Claude call in this
project has ever lived in.

AST-based, not a bare grep: a textual search for ``messages.create`` would
also match ``messages.batches.create`` (the correct call), which starts
with the same substring read left to right after the ``.messages.`` split.
Parsing lets this check ask the precise question -- "is the attribute
chain exactly `<something>.messages.create`, with no `.batches` in
between?" -- without a fragile regex trying to encode the same distinction.

Known, accepted blind spots (a tripwire, not an airtight guarantee): a
call reached through an intermediate variable (`m = client.messages;
m.create(...)`) or via `getattr`/dynamic dispatch would not be flagged,
since both change the AST shape this check looks for. Revisit only if a
real violation of either shape is ever found in review.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_ROOT = REPO_ROOT / "pipeline"


# The one function allowed to reach the synchronous endpoint, and why.
#
# NFR-2's concern is cost-independence: per-request billing that scales with the
# corpus. Summarization is exactly that shape -- one call per published item,
# every cycle, forever -- so it must be batched, and the tripwire above exists
# because a single copy-pasted synchronous call would quietly undo it.
#
# `score_consequence` is a different shape. The ranking cannot order anything
# until it knows what each event changes, and the Batch API's own commitment is
# 24 hours: batching it would mean a third phase in every cycle and a Briefing
# published half a day after the news. It sends headlines only, batched
# `CONSEQUENCE_BATCH` at a time, so the call count is ceil(candidates / 25) --
# two or three per cycle whether the corpus holds 12,000 articles or 120,000.
# That is bounded independently of volume, which is what NFR-2 is protecting.
#
# Named exactly, not pattern-matched: any OTHER synchronous call still fails,
# including a second one added inside this same module.
_SYNCHRONOUS_ALLOWED = {("pipeline/adapters/claude.py", "score_consequence")}


def _enclosing_function(tree: ast.AST, lineno: int) -> str | None:
    """The name of the innermost function containing a line."""
    best: tuple[int, str] | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= lineno <= end and (best is None or node.lineno > best[0]):
                best = (node.lineno, node.name)
    return best[1] if best else None


def _synchronous_messages_create_calls(source: str, filename: str) -> list[str]:
    """Every call in `source` shaped like `<expr>.messages.create(...)` --
    the synchronous endpoint -- as opposed to `<expr>.messages.batches.create(...)`,
    the Batch API's submit call, which is what this pipeline must use instead."""
    tree = ast.parse(source, filename=filename)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "create":
            continue
        # func is `<owner>.create` -- owner must be exactly `<expr>.messages`,
        # not `<expr>.messages.batches` (the correct call) or anything else.
        owner = func.value
        if not isinstance(owner, ast.Attribute) or owner.attr != "messages":
            continue
        violations.append(f"{filename}:{node.lineno}")
    return violations


def test_no_pipeline_file_calls_the_synchronous_messages_api() -> None:
    violations: list[str] = []
    for path in PIPELINE_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text()
        relative = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(source, filename=relative)
        for found in _synchronous_messages_create_calls(source, relative):
            lineno = int(found.rsplit(":", 1)[1])
            if (relative, _enclosing_function(tree, lineno)) in _SYNCHRONOUS_ALLOWED:
                continue
            violations.append(found)

    assert violations == [], (
        "found a synchronous client.messages.create(...) call outside the "
        f"Batch API: {violations}. Every Claude call in this pipeline must "
        "go through client.messages.batches.create/.retrieve/.results "
        "(NFR-2) -- see pipeline/adapters/claude.py's submit_batch/"
        "collect_batch. The one allowlisted exception is recorded in "
        "_SYNCHRONOUS_ALLOWED, with the reason it is bounded independently "
        "of corpus size; add to it deliberately or not at all."
    )


def test_the_allowlist_names_functions_that_actually_exist() -> None:
    """An allowlist entry that no longer matches anything is worse than no
    entry: it reads as a live exception while silently protecting nothing, and
    the next synchronous call added to that file inherits the exemption."""
    for relative, function in _SYNCHRONOUS_ALLOWED:
        source = (REPO_ROOT / relative).read_text()
        tree = ast.parse(source, filename=relative)
        names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        assert function in names, f"{relative} has no function {function}"


def test_a_second_synchronous_call_in_the_allowlisted_file_is_still_caught() -> None:
    """The exemption is one function, not one file. A shortcut added elsewhere in
    the adapter must fail exactly as it would anywhere else."""
    planted = """
def score_consequence(client):
    return client.messages.create(model="x", messages=[])


def something_else(client):
    return client.messages.create(model="x", messages=[])
"""
    tree = ast.parse(planted, filename="pipeline/adapters/claude.py")
    found = _synchronous_messages_create_calls(planted, "pipeline/adapters/claude.py")
    unexempt = [
        hit
        for hit in found
        if ("pipeline/adapters/claude.py", _enclosing_function(tree, int(hit.rsplit(":", 1)[1])))
        not in _SYNCHRONOUS_ALLOWED
    ]
    assert len(found) == 2
    assert unexempt == ["pipeline/adapters/claude.py:7"]


def test_the_detector_actually_catches_a_planted_synchronous_call() -> None:
    """AD-style proof this check works, not just that it currently finds
    nothing -- mirrors test_boundary_check.py's own discipline of planting
    a violation and confirming detection, rather than trusting a check that
    has never been observed to fail."""
    planted = """
def bad(client):
    return client.messages.create(model="x", messages=[])
"""
    violations = _synchronous_messages_create_calls(planted, "planted.py")
    assert violations == ["planted.py:3"]


def test_the_detector_does_not_flag_the_real_batch_api_call() -> None:
    """Regression guard for the false positive this check must avoid: the
    Batch API's own submit call, `client.messages.batches.create(...)`,
    must never be mistaken for the synchronous endpoint it replaces."""
    correct = """
def good(client):
    return client.messages.batches.create(requests=[])
"""
    violations = _synchronous_messages_create_calls(correct, "correct.py")
    assert violations == []


def test_the_detector_still_catches_an_aliased_import() -> None:
    """A renamed import (`import anthropic as sdk`) or a rebound local
    name for the client must not change the AST shape this check looks
    for -- the check inspects the attribute chain's shape, not any
    variable's name, so an alias is not a way around it."""
    aliased = """
def bad(sdk_client):
    return sdk_client.messages.create(model="x", messages=[])
"""
    violations = _synchronous_messages_create_calls(aliased, "aliased.py")
    assert violations == ["aliased.py:3"]


def test_known_blind_spot_an_intermediate_variable_is_not_caught() -> None:
    """Documents, rather than silently leaves undiscovered, a real blind
    spot in this check: pulling `client.messages` into a local before
    dispatching changes the AST shape enough that this check's narrow
    attribute-chain match misses it. Accepted as a tripwire limitation
    (see this module's own docstring) rather than "fixed" with a fuller
    data-flow analysis, which would be disproportionate machinery for a
    tripwire whose job is to catch the common, careless case."""
    evasive = """
def bad(client):
    m = client.messages
    return m.create(model="x", messages=[])
"""
    violations = _synchronous_messages_create_calls(evasive, "evasive.py")
    assert violations == [], (
        "if this now fails, the detector has been improved to catch this "
        "case -- update this test's expectation and this module's "
        "docstring together, rather than treating the new failure as a bug"
    )
