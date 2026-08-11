"""The collect stage writes what it retrieved, plus what it could not.

Stories 1.2 and 1.3 share this stage: GDELT and RSS are two adapters feeding
one output. The stage's job is to run them, merge their results, write the
Articles as JSON Lines, and record any failure into the cycle metadata without
aborting (AD-10, NFR-3).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pipeline.adapters import CollectionResult, Failure
from pipeline.domain import ArticleRecord
from pipeline.stages.collect import write_collection


def _record(title: str, source: str = "S", country: str = "france") -> ArticleRecord:
    return ArticleRecord(
        title=title,
        url=f"https://example.com/{title.replace(' ', '-')}",
        published_at=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
        source=source,
        source_country=country,
        language="fr",
        collected_by="gdelt",
    )


def test_writes_one_json_line_per_article(tmp_path: Path) -> None:
    result = CollectionResult(
        articles=[_record("one").to_dict(), _record("two").to_dict()],
        failures=[],
    )

    written = write_collection(result, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path)

    lines = written.articles_path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["title"] == "one"


def test_article_records_carry_the_glossary_fields(tmp_path: Path) -> None:
    """AC: title, publication timestamp, Source, Source country, language."""
    result = CollectionResult(articles=[_record("x").to_dict()], failures=[])

    written = write_collection(result, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path)

    record = json.loads(written.articles_path.read_text().splitlines()[0])
    assert set(record) >= {"title", "published_at", "source", "source_country", "language"}


def test_failures_are_recorded_and_the_stage_still_succeeds(tmp_path: Path) -> None:
    """AC: writes the Articles it did retrieve plus a failure record naming
    what failed, and exits successfully."""
    result = CollectionResult(
        articles=[_record("survived").to_dict()],
        failures=[Failure(adapter="gdelt", detail="429 after 3 of 7 pages")],
    )

    written = write_collection(result, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path)

    assert written.articles_path.read_text().strip()
    meta = json.loads(written.metadata_path.read_text())
    assert meta["failures"] == [{"adapter": "gdelt", "detail": "429 after 3 of 7 pages"}]
    assert meta["article_count"] == 1


def test_clean_run_records_no_failures(tmp_path: Path) -> None:
    result = CollectionResult(articles=[_record("x").to_dict()], failures=[])

    written = write_collection(result, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path)

    meta = json.loads(written.metadata_path.read_text())
    assert meta["failures"] == []


def test_output_lands_under_the_stage_and_cycle(tmp_path: Path) -> None:
    """Spine convention: data/intermediate/<stage>/<cycle-id>/."""
    result = CollectionResult(articles=[_record("x").to_dict()], failures=[])

    written = write_collection(result, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path)

    assert written.articles_path.parent == (
        tmp_path / "intermediate" / "collect" / "2026-08-11T00-00-00Z"
    )


def test_rerun_on_identical_input_is_byte_identical(tmp_path: Path) -> None:
    """Committed intermediate files must diff readably between cycles."""
    result = CollectionResult(
        articles=[_record("b").to_dict(), _record("a").to_dict()], failures=[]
    )

    first = write_collection(result, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path)
    content = first.articles_path.read_text()
    second = write_collection(result, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path)

    assert second.articles_path.read_text() == content


def test_empty_collection_still_writes_metadata(tmp_path: Path) -> None:
    """A total upstream failure is a fact about the cycle worth recording —
    the next run reads this to know the gap was real, not a missing file."""
    result = CollectionResult(
        articles=[], failures=[Failure(adapter="gdelt", detail="unreachable")]
    )

    written = write_collection(result, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path)

    assert written.articles_path.exists()
    assert written.articles_path.read_text() == ""
    meta = json.loads(written.metadata_path.read_text())
    assert meta["article_count"] == 0
    assert meta["failures"]
