"""Shared test setup.


Exists for one reason: `run_cycle` now consults the editorial agenda, which
reaches Wikipedia over the network. Left alone, every cycle test would make
seven HTTP requests -- the suite went from 9s to 78s the moment the stage was
wired in -- and would fail or pass depending on what volunteers had written
that morning. Tests must not depend on today's news.

The default here neutralizes the agenda, so the cycle tests keep asserting
exactly what they were written to assert: the collect -> dedupe -> cluster ->
rank -> summarize -> publish path, with the Clusters themselves as candidates.
Tests that mean to exercise the agenda pass their own `fetch` or `agenda_fn`
explicitly, which is visible at the call site rather than ambient.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_network_agenda(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the agenda stage see an empty chronicle instead of calling out.

    Patched on `pipeline.stages.agenda`, the name the stage resolves at call
    time -- not on the adapter's `_default_fetch`, which is bound as a default
    argument when the module is imported and so cannot be replaced afterwards.
    That distinction cost a confused run: patching the adapter left the suite
    still making seven real requests per cycle test.

    The adapter's own tests import `collect_agenda` from
    `pipeline.adapters.editorial_agenda` and inject their own `fetch`, so they
    are unaffected by this.
    """
    import pipeline.stages.agenda as agenda_stage

    monkeypatch.setattr(agenda_stage, "collect_agenda", lambda **_kwargs: ([], []))


@pytest.fixture
def working_agenda(monkeypatch: pytest.MonkeyPatch):
    """Give the agenda stage one real-shaped event, for tests asserting on a
    cycle that is NOT degraded.

    A cycle whose agenda is unavailable IS degraded -- it falls back to ranking
    Clusters by syndication, which is the selection this stage exists to
    replace, and a reader deserves to have that recorded. So "clean cycle"
    tests have to supply an agenda rather than assume one.
    """

    def install(text: str = "A Russian missile strike kills ten civilians in Kharkiv Oblast"):
        import pipeline.stages.agenda as agenda_stage
        from pipeline.adapters.editorial_agenda import EditorialEvent

        event = EditorialEvent(
            text=text,
            category="Armed conflicts and attacks",
            day="2026-08-11",
            sources=("https://apnews.com/x",),
            countries=("up",),
        )
        monkeypatch.setattr(agenda_stage, "collect_agenda", lambda **_kwargs: ([event], []))

    return install


@pytest.fixture
def empty_agenda():
    """An `agenda_fn` for `run_cycle` that writes no items.

    For tests that assert on the pre-agenda pipeline shape and should not pay
    for the stage at all.
    """
    from pipeline.stages.agenda import WrittenAgenda

    def agenda_fn(_cluster_path: Path, cycle_id: str, data_root: Path, **_kwargs) -> WrittenAgenda:
        destination = data_root / "intermediate" / "agenda" / cycle_id
        destination.mkdir(parents=True, exist_ok=True)
        items = destination / "items.jsonl"
        items.write_text("", encoding="utf-8")
        return WrittenAgenda(
            output_path=items,
            metadata_path=destination / "agenda.json",
            items_out=0,
            corroborated=0,
            degraded=False,
        )

    return agenda_fn


@pytest.fixture(autouse=True)
def _no_consequence_scoring(monkeypatch):
    """Every cycle test scores consequence unless it says otherwise, and the real
    scorer is a network call. Stubbed to "nothing judged", which the rank stage
    treats neutrally -- so a test that does not care about the ordering is
    unaffected, and one that does must supply its own verdicts.

    Patched on the module attribute, which works only because `run_cycle`
    resolves `consequence_fn or score_consequence` in its body. As a default
    argument it would be bound at import and this fixture would do nothing --
    the exact trap the agenda's `_default_fetch` fell into.
    """
    monkeypatch.setattr(
        "pipeline.stages.cycle.score_consequence", lambda events, **kwargs: ({}, [])
    )
