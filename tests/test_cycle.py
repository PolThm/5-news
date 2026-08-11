"""Running a full cycle: collect, then dedupe, then record what happened.

Story 1.5 turns the pipeline from something you invoke into something that
accumulates. The Build Order's inspection window depends on days of real output
piling up without anyone starting them.

A failed cycle must leave the previous cycle's committed output untouched
(AD-7): the next run is independent of the last one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pipeline.adapters import CollectionResult, Failure
from pipeline.domain import ArticleRecord
from pipeline.stages.cycle import CycleResult, run_cycle


def _record(title: str, source: str, country: str = "france") -> ArticleRecord:
    return ArticleRecord(
        title=title,
        url=f"https://{source}/{abs(hash(title + source))}",
        published_at=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
        source=source,
        source_country=country,
        language="fr",
        collected_by="gdelt",
    )


def _collection(*records: ArticleRecord, failures: list[Failure] | None = None) -> CollectionResult:
    return CollectionResult(articles=[r.to_dict() for r in records], failures=failures or [])


def test_runs_collect_then_dedupe(tmp_path: Path) -> None:
    """AC: collect and dedupe run for World / day."""
    collection = _collection(
        _record("Ceasefire agreed", "reuters.com", "united-kingdom"),
        _record("Ceasefire agreed", "lemonde.fr", "france"),
        _record("Markets rally", "ft.com", "united-kingdom"),
    )

    result = run_cycle(
        collect=lambda: collection,
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
    )

    assert result.articles_collected == 3
    assert result.groups_after_dedupe == 2
    assert result.collect_path.exists()
    assert result.dedupe_path.exists()


def test_writes_a_cycle_record(tmp_path: Path) -> None:
    """The cycle record is what a human reads weeks later to judge whether a
    thin day was a quiet news day or a broken upstream."""
    result = run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
    )

    record = json.loads(result.cycle_path.read_text())
    assert record["cycle_id"] == "2026-08-11T00-00-00Z"
    assert record["articles_collected"] == 1
    assert record["groups_after_dedupe"] == 1
    assert record["failures"] == []
    assert "started_at" in record


def test_cycle_record_names_upstream_failures(tmp_path: Path) -> None:
    """A degraded cycle is not a failed cycle, but the degradation must be
    visible — otherwise thin coverage looks like a quiet day (AD-10)."""
    result = run_cycle(
        collect=lambda: _collection(
            _record("A", "a.com"),
            failures=[Failure("gdelt", "429 after 3 of 7 windows")],
        ),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
    )

    record = json.loads(result.cycle_path.read_text())
    assert record["failures"] == [{"adapter": "gdelt", "detail": "429 after 3 of 7 windows"}]
    assert record["degraded"] is True


def test_a_clean_cycle_is_not_marked_degraded(tmp_path: Path) -> None:
    result = run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
    )

    assert json.loads(result.cycle_path.read_text())["degraded"] is False


def test_cycle_state_lands_where_a_later_run_can_resume_it(tmp_path: Path) -> None:
    """Spine convention: cross-phase state at
    data/intermediate/<cycle-id>/cycle.json, committed so a later scheduled run
    can pick it up (AD-11, and Story 3.4 depends on this path)."""
    result = run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
    )

    assert result.cycle_path == tmp_path / "intermediate" / "2026-08-11T00-00-00Z" / "cycle.json"


def test_a_totally_failed_collection_still_completes_the_cycle(tmp_path: Path) -> None:
    """Every upstream down is a fact about the day, recorded — not a crash."""
    result = run_cycle(
        collect=lambda: CollectionResult(
            articles=[],
            failures=[Failure("gdelt", "unreachable"), Failure("rss", "all feeds down")],
        ),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
    )

    assert result.articles_collected == 0
    record = json.loads(result.cycle_path.read_text())
    assert record["degraded"] is True
    assert len(record["failures"]) == 2


def test_a_new_cycle_does_not_touch_a_previous_one(tmp_path: Path) -> None:
    """AC: a cycle runs independently of a failed one, leaving previously
    committed output untouched."""
    first = run_cycle(
        collect=lambda: _collection(_record("Yesterday", "a.com")),
        cycle_id="2026-08-10T00-00-00Z",
        data_root=tmp_path,
    )
    yesterday = first.dedupe_path.read_text()

    run_cycle(
        collect=lambda: CollectionResult(articles=[], failures=[Failure("gdelt", "down")]),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
    )

    assert first.dedupe_path.read_text() == yesterday, "yesterday's output survived"


def test_each_cycle_gets_its_own_directory(tmp_path: Path) -> None:
    first = run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-10T00-00-00Z",
        data_root=tmp_path,
    )
    second = run_cycle(
        collect=lambda: _collection(_record("B", "b.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
    )

    assert first.cycle_path != second.cycle_path
    assert first.dedupe_path != second.dedupe_path


def test_collect_raising_is_contained(tmp_path: Path) -> None:
    """Adapters should never raise past their boundary, but the cycle is the
    last line of defense: an unexpected crash must still leave a record saying
    what happened rather than a silent gap."""

    def explode() -> CollectionResult:
        raise RuntimeError("adapter bug")

    result = run_cycle(
        collect=explode,
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
    )

    assert result.articles_collected == 0
    record = json.loads(result.cycle_path.read_text())
    assert record["degraded"] is True
    assert any("adapter bug" in f["detail"] for f in record["failures"])


def test_result_reports_success_for_a_degraded_but_completed_cycle(tmp_path: Path) -> None:
    """Exit status is about whether the cycle ran, not whether coverage was
    perfect — a scheduled job that reports failure on a thin day would train
    the author to ignore it."""
    result = run_cycle(
        collect=lambda: _collection(
            _record("A", "a.com"), failures=[Failure("rss", "one feed 404")]
        ),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
    )

    assert isinstance(result, CycleResult)
    assert result.completed is True


def test_dedupe_crashing_still_leaves_a_cycle_record(tmp_path: Path) -> None:
    """cycle.json is the ONLY tracked file and it is written last. A crash in
    dedupe that skipped it would leave nothing in git at all — the exact silent
    gap this function exists to prevent.

    Reachable in practice: a truncated articles.jsonl from a timed-out earlier
    run makes read_jsonl raise on the partial final line.
    """
    bad = tmp_path / "intermediate" / "collect" / "2026-08-11T00-00-00Z"
    bad.mkdir(parents=True)
    (bad / "articles.jsonl").write_text('{"title": "truncated"')  # no closing brace

    def collect_returning_unwritable() -> CollectionResult:
        # Force dedupe to read the malformed file already on disk by writing
        # nothing new over it.
        return CollectionResult(articles=[], failures=[])

    result = run_cycle(
        collect=collect_returning_unwritable,
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
    )

    assert result.cycle_path.exists(), "a cycle record must survive any crash"
    record = json.loads(result.cycle_path.read_text())
    assert record["cycle_id"] == "2026-08-11T00-00-00Z"


def test_completed_is_false_when_a_stage_crashes(tmp_path: Path) -> None:
    """`completed` distinguishes "ran and found little" from "could not run".
    Without it the field is a constant and the distinction is unrepresentable.
    """
    import pipeline.stages.cycle as cycle_module

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("disk full")

    original = cycle_module.run_dedupe
    cycle_module.run_dedupe = explode  # type: ignore[assignment]
    try:
        result = run_cycle(
            collect=lambda: _collection(_record("A", "a.com")),
            cycle_id="2026-08-11T00-00-00Z",
            data_root=tmp_path,
        )
    finally:
        cycle_module.run_dedupe = original  # type: ignore[assignment]

    assert result.completed is False
    record = json.loads(result.cycle_path.read_text())
    assert record["completed"] is False
    assert any("disk full" in f["detail"] for f in record["failures"])
