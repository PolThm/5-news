"""The on-disk JSON shape of a published Briefing.

Mirrors ArticleRecord's own reasoning (test_article_record.py): every stage
that writes a Briefing does so through this shape, whatever the in-memory
representation looks like, so the site (Epic 4) reads against one versioned
definition living in pipeline/domain/ rather than an ad-hoc dict shape
invented in pipeline/stages/publish.py.

Deliberately built on plain dicts for its Cluster entries, not
QualifyingCluster/Cluster/Event/Article -- the pipeline has never
materialized those richer domain objects anywhere (dedupe/cluster/rank/
summarize all operate on dicts end to end), and forcing a conversion layer
here would be new complexity with no real consumer.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pipeline.domain import BriefingRecord, OutputLanguage, Period, Zone, ZoneKind


def _cluster(cluster_id: str) -> dict:
    return {
        "cluster_id": cluster_id,
        "members": [{"title": f"title {cluster_id}", "url": f"https://example.com/{cluster_id}"}],
        "independent_source_count": 2,
        "country_count": 2,
        "countries": ["france", "germany"],
        "origin_country": "france",
        "rank": 1,
        "summary": "Un resume.",
        "outbound_url": f"https://example.com/{cluster_id}",
        "outbound_source": "example.com",
    }


def test_carries_the_addressing_triple_and_generation_timestamp() -> None:
    record = BriefingRecord(
        zone=Zone("france", ZoneKind.COUNTRY, continent="europe"),
        period=Period.DAY,
        language=OutputLanguage.FR,
        clusters=(_cluster("a"),),
        generated_at=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
    )

    assert record.zone.slug == "france"
    assert record.period == Period.DAY
    assert record.language == OutputLanguage.FR
    assert record.generated_at == datetime(2026, 8, 11, 6, 0, tzinfo=UTC)


def test_served_zone_defaults_to_the_requested_zone() -> None:
    """FR-16's fallback is never silent -- but the common case (no fallback)
    should not force every caller to repeat the Zone twice."""
    zone = Zone("japan", ZoneKind.COUNTRY, continent="asia")
    record = BriefingRecord(
        zone=zone,
        period=Period.DAY,
        language=OutputLanguage.EN,
        clusters=(),
        generated_at=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
    )

    assert record.served_zone == zone


def test_round_trips_through_json() -> None:
    original = BriefingRecord(
        zone=Zone("france", ZoneKind.COUNTRY, continent="europe"),
        served_zone=Zone("europe", ZoneKind.CONTINENT),
        period=Period.WEEK,
        language=OutputLanguage.ES,
        clusters=(_cluster("a"), _cluster("b")),
        discarded_ingested=100,
        discarded_kept=2,
        generated_at=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
    )

    restored = BriefingRecord.from_dict(original.to_dict())

    assert restored == original


def test_schema_version_is_present_and_stable() -> None:
    """A schema change is a version bump, never a silent field edit
    (architecture spine, Consistency Conventions) -- pinned here so a future
    change to the shape is a deliberate, visible diff to this test."""
    record = BriefingRecord(
        zone=Zone("world", ZoneKind.WORLD),
        period=Period.DAY,
        language=OutputLanguage.FR,
        clusters=(),
        generated_at=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
    )

    assert record.to_dict()["schema_version"] == 1


def test_a_fallback_records_both_the_requested_and_served_zone() -> None:
    requested = Zone("brazil", ZoneKind.COUNTRY, continent="south-america")
    served = Zone("south-america", ZoneKind.CONTINENT)
    record = BriefingRecord(
        zone=requested,
        served_zone=served,
        period=Period.DAY,
        language=OutputLanguage.FR,
        clusters=(),
        generated_at=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
    )

    data = record.to_dict()
    assert data["zone"] == "brazil"
    assert data["served_zone"] == "south-america"
    restored = BriefingRecord.from_dict(data)
    assert restored.zone.slug == "brazil"
    assert restored.served_zone.slug == "south-america"
