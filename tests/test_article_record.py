"""The on-disk shape of a collected Article.

Every adapter writes this shape, whatever its upstream looks like — that is
what makes the vendor response shape stay inside pipeline/adapters/ (AD-13).
Field names come from the PRD Glossary; a synonym here would leak through
every downstream stage and into the published Briefing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pipeline.domain import ArticleRecord


def test_carries_every_field_the_story_requires() -> None:
    """AC: title, publication timestamp, Source, Source country, and language."""
    record = ArticleRecord(
        title="Ceasefire agreed",
        url="https://example.com/a",
        published_at=datetime(2026, 8, 11, 6, 30, tzinfo=UTC),
        source="Reuters",
        source_country="united-kingdom",
        language="en",
        collected_by="gdelt",
    )
    assert record.title == "Ceasefire agreed"
    assert record.source_country == "united-kingdom"
    assert record.collected_by == "gdelt"


def test_round_trips_through_json() -> None:
    """Records are written as JSON Lines and read back by the next stage."""
    original = ArticleRecord(
        title="Markets rally",
        url="https://example.com/b",
        published_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
        source="AFP",
        source_country="france",
        language="fr",
        collected_by="rss",
    )
    restored = ArticleRecord.from_dict(original.to_dict())
    assert restored == original


def test_timestamp_is_iso8601_with_offset() -> None:
    """Spine convention: UTC everywhere inside the pipeline, ISO-8601 with an
    explicit offset in stored data. Never a naive local timestamp."""
    record = ArticleRecord(
        title="x",
        url="https://example.com/c",
        published_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
        source="S",
        source_country="japan",
        language="ja",
        collected_by="gdelt",
    )
    assert record.to_dict()["published_at"] == "2026-08-11T12:00:00+00:00"


def test_rejects_a_naive_timestamp() -> None:
    """A naive datetime would silently be read as local time somewhere
    downstream, shifting an Article into the wrong Period."""
    with pytest.raises(ValueError, match="timezone-aware"):
        ArticleRecord(
            title="x",
            url="https://example.com/d",
            published_at=datetime(2026, 8, 11, 12, 0),  # no tzinfo
            source="S",
            source_country="france",
            language="fr",
            collected_by="gdelt",
        )


def test_keys_are_glossary_terms() -> None:
    """No synonyms. `source`, not `outlet`/`publisher`/`feed`."""
    record = ArticleRecord(
        title="x",
        url="https://example.com/e",
        published_at=datetime(2026, 8, 11, tzinfo=UTC),
        source="S",
        source_country="germany",
        language="de",
        collected_by="rss",
    )
    assert set(record.to_dict()) == {
        "title",
        "url",
        "published_at",
        "source",
        "source_country",
        "language",
        "collected_by",
    }


def test_wire_agency_defaults_to_none() -> None:
    """GDELT exposes no attribution field at all (Story 2.3 scope reality
    check) — every GDELT-collected record has wire_agency=None unconditionally,
    and this must be the default so no existing call site needs to change."""
    record = ArticleRecord(
        title="x",
        url="https://example.com/f",
        published_at=datetime(2026, 8, 11, tzinfo=UTC),
        source="S",
        source_country="japan",
        language="ja",
        collected_by="gdelt",
    )
    assert record.wire_agency is None


def test_wire_agency_is_omitted_from_the_dict_when_absent() -> None:
    """Common-case bytes stay unchanged from before this field existed —
    diffs during the inspection window stay readable (AC4)."""
    record = ArticleRecord(
        title="x",
        url="https://example.com/g",
        published_at=datetime(2026, 8, 11, tzinfo=UTC),
        source="S",
        source_country="japan",
        language="ja",
        collected_by="gdelt",
    )
    assert "wire_agency" not in record.to_dict()


def test_wire_agency_round_trips_when_present() -> None:
    original = ArticleRecord(
        title="Wire dispatch",
        url="https://example.com/h",
        published_at=datetime(2026, 8, 11, tzinfo=UTC),
        source="outlet.com",
        source_country="france",
        language="en",
        collected_by="rss",
        wire_agency="AFP",
    )
    restored = ArticleRecord.from_dict(original.to_dict())
    assert restored == original
    assert restored.wire_agency == "AFP"
