"""GDELT DOC 2.0 adapter.

Verified against the live API on 2026-08-10/11. Three facts drive this design:

1. **There is no pagination.** `maxrecords` caps at 250 and stops. The only way
   past it is splitting the query by time, and a slice returning exactly 250 is
   *truncated*, not complete — it must be bisected.
2. **Query-level errors come back as HTTP 200 with a plain-text body.** Trusting
   the status code means silently ingesting an error message as if it were news.
3. **Country codes are FIPS 10-4, not ISO 3166.** `CH` is China in FIPS and
   Switzerland in ISO. Reusing an ISO table would mis-attribute every article.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pipeline.adapters.gdelt import (
    FIPS_BY_ZONE,
    GdeltClient,
    is_saturated,
    parse_articles,
    parse_seendate,
    split_window,
)

# --- Response parsing --------------------------------------------------------


def test_parses_the_live_response_shape() -> None:
    """Field names captured from a real API response, not guessed."""
    payload = {
        "articles": [
            {
                "url": "https://www.bfmtv.com/x.html",
                "url_mobile": "",
                "title": "Incendies, canicules",
                "seendate": "20260810T114500Z",
                "socialimage": "https://images.bfmtv.com/y.jpg",
                "domain": "bfmtv.com",
                "language": "French",
                "sourcecountry": "France",
            }
        ]
    }

    records = parse_articles(payload)

    assert len(records) == 1
    assert records[0].title == "Incendies, canicules"
    assert records[0].source == "bfmtv.com"
    assert records[0].collected_by == "gdelt"


def test_maps_full_names_back_to_slugs() -> None:
    """GDELT queries take codes but responses return full English names —
    an asymmetry that would otherwise leak 'France' where the pipeline
    expects the 'france' Zone slug."""
    payload = {
        "articles": [
            {
                "url": "https://example.com/a",
                "title": "x",
                "seendate": "20260810T114500Z",
                "domain": "example.com",
                "language": "French",
                "sourcecountry": "France",
            }
        ]
    }

    record = parse_articles(payload)[0]

    assert record.source_country == "france"
    assert record.language == "fr"


def test_unknown_country_is_preserved_not_dropped() -> None:
    """An Article from a country outside the 15 Zones is still real coverage —
    it counts toward World. Dropping it would understate Consensus Score."""
    payload = {
        "articles": [
            {
                "url": "https://example.com/a",
                "title": "x",
                "seendate": "20260810T114500Z",
                "domain": "example.com",
                "language": "Icelandic",
                "sourcecountry": "Iceland",
            }
        ]
    }

    record = parse_articles(payload)[0]

    assert record.source_country == "iceland"


def test_empty_result_is_not_an_error() -> None:
    assert parse_articles({"articles": []}) == []


def test_missing_articles_key_is_not_an_error() -> None:
    """GDELT sometimes returns an empty body for a zero-match query."""
    assert parse_articles({}) == []


def test_skips_an_article_missing_required_fields() -> None:
    """One malformed row must not cost the whole batch."""
    payload = {
        "articles": [
            {
                "url": "https://example.com/good",
                "title": "keep me",
                "seendate": "20260810T114500Z",
                "domain": "example.com",
                "language": "English",
                "sourcecountry": "United States",
            },
            {"url": "https://example.com/bad"},  # no title, no seendate
        ]
    }

    records = parse_articles(payload)

    assert len(records) == 1
    assert records[0].title == "keep me"


# --- seendate ----------------------------------------------------------------


def test_seendate_uses_the_response_format_not_the_query_format() -> None:
    """Queries take YYYYMMDDHHMMSS; responses return YYYYMMDDTHHMMSSZ.
    Confusing the two is a silent parse failure."""
    parsed = parse_seendate("20260810T114500Z")
    assert parsed == datetime(2026, 8, 10, 11, 45, 0, tzinfo=UTC)
    assert parsed.tzinfo is not None


def test_malformed_seendate_raises() -> None:
    with pytest.raises(ValueError):
        parse_seendate("2026-08-10 11:45")


# --- The 250 ceiling ---------------------------------------------------------


def test_exactly_250_means_truncated() -> None:
    """The single most important constraint: 250 is a saturation signal, never
    a complete result."""
    assert is_saturated(250) is True


def test_fewer_than_250_is_complete() -> None:
    assert is_saturated(249) is False
    assert is_saturated(0) is False


def test_window_bisects_for_recursive_narrowing() -> None:
    start = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    end = datetime(2026, 8, 12, 0, 0, tzinfo=UTC)

    first, second = split_window(start, end)

    assert first == (start, datetime(2026, 8, 11, 12, 0, tzinfo=UTC))
    assert second == (datetime(2026, 8, 11, 12, 0, tzinfo=UTC), end)


def test_window_too_narrow_to_split_returns_none() -> None:
    """Below a minute there is nothing left to bisect — accept truncation and
    record it rather than recursing forever."""
    start = datetime(2026, 8, 11, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 8, 11, 0, 0, 30, tzinfo=UTC)

    assert split_window(start, end) is None


# --- FIPS codes --------------------------------------------------------------


def test_fips_codes_are_not_iso() -> None:
    """The trap: CH is China in FIPS, Switzerland in ISO. UK not GB, GM not DE,
    JA not JP."""
    assert FIPS_BY_ZONE["china"] == "CH"
    assert FIPS_BY_ZONE["united-kingdom"] == "UK"
    assert FIPS_BY_ZONE["germany"] == "GM"
    assert FIPS_BY_ZONE["japan"] == "JA"
    assert FIPS_BY_ZONE["france"] == "FR"
    assert FIPS_BY_ZONE["united-states"] == "US"
    assert FIPS_BY_ZONE["india"] == "IN"
    assert FIPS_BY_ZONE["brazil"] == "BR"


def test_every_country_zone_has_a_fips_code() -> None:
    from pipeline.config import ZONES
    from pipeline.domain import ZoneKind

    for zone in ZONES:
        if zone.kind is ZoneKind.COUNTRY:
            assert zone.slug in FIPS_BY_ZONE, f"no FIPS code for {zone.slug}"


# --- Error handling ----------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int, body: str, content_type: str = "application/json") -> None:
        self.status_code = status
        self.text = body
        self.headers = {"Content-Type": content_type}


def test_http_200_with_a_text_error_body_is_a_failure_not_data() -> None:
    """GDELT returns 200 + plain text for query errors. Trusting the status
    would ingest 'A maximum of 250 records can be returned.' as an article."""
    client = GdeltClient(
        fetch=lambda url: FakeResponse(
            200, "A maximum of 250 records can be returned.", "text/html"
        )
    )

    result = client.fetch_window(
        query="sourcelang:eng",
        start=datetime(2026, 8, 11, tzinfo=UTC),
        end=datetime(2026, 8, 12, tzinfo=UTC),
    )

    assert result.articles == []
    assert result.failures
    assert "maximum of 250" in result.failures[0].detail


def test_429_is_reported_as_a_failure_without_raising() -> None:
    """AD-10: an adapter reports, it does not raise past its boundary."""
    client = GdeltClient(
        fetch=lambda url: FakeResponse(429, "Please limit requests to one every 5 seconds"),
        max_retries=0,
    )

    result = client.fetch_window(
        query="sourcelang:eng",
        start=datetime(2026, 8, 11, tzinfo=UTC),
        end=datetime(2026, 8, 12, tzinfo=UTC),
    )

    assert result.articles == []
    assert result.failures
    assert "429" in result.failures[0].detail


def test_a_network_exception_becomes_a_failure_record() -> None:
    def explode(url: str) -> FakeResponse:
        raise ConnectionError("dns failure")

    client = GdeltClient(fetch=explode, max_retries=0)

    result = client.fetch_window(
        query="sourcelang:eng",
        start=datetime(2026, 8, 11, tzinfo=UTC),
        end=datetime(2026, 8, 12, tzinfo=UTC),
    )

    assert result.articles == []
    assert result.failures
    assert "dns failure" in result.failures[0].detail


def test_successful_fetch_returns_records() -> None:
    body = (
        '{"articles": [{"url": "https://example.com/a", "title": "t", '
        '"seendate": "20260810T114500Z", "domain": "example.com", '
        '"language": "English", "sourcecountry": "United States"}]}'
    )
    client = GdeltClient(fetch=lambda url: FakeResponse(200, body))

    result = client.fetch_window(
        query="sourcelang:eng",
        start=datetime(2026, 8, 11, tzinfo=UTC),
        end=datetime(2026, 8, 12, tzinfo=UTC),
    )

    assert len(result.articles) == 1
    assert result.failures == []


def test_query_datetime_format_has_no_separators() -> None:
    """Query format is YYYYMMDDHHMMSS — 14 digits, no T, no Z. The response
    format differs, which is exactly why this is pinned."""
    from pipeline.adapters.gdelt import format_query_datetime

    assert format_query_datetime(datetime(2026, 8, 11, 6, 30, 15, tzinfo=UTC)) == "20260811063015"


def test_saturated_window_is_bisected_automatically() -> None:
    """A window returning 250 is split and re-fetched, so coverage is not
    silently capped at 250 for a busy day."""
    calls: list[str] = []

    def fetch(url: str) -> FakeResponse:
        calls.append(url)
        # First call saturates; each half then returns one distinct article.
        if len(calls) == 1:
            count, prefix = 250, "sat"
        else:
            count, prefix = 1, f"half{len(calls)}"
        articles = ",".join(
            f'{{"url": "https://example.com/{prefix}-{i}", "title": "t{i}", '
            f'"seendate": "20260810T114500Z", "domain": "example.com", '
            f'"language": "English", "sourcecountry": "United States"}}'
            for i in range(count)
        )
        return FakeResponse(200, f'{{"articles": [{articles}]}}')

    client = GdeltClient(fetch=fetch)

    result = client.collect(
        query="sourcelang:eng",
        start=datetime(2026, 8, 11, 0, 0, tzinfo=UTC),
        end=datetime(2026, 8, 12, 0, 0, tzinfo=UTC),
    )

    assert len(calls) == 3, "expected one saturated call plus two halves"
    assert len(result.articles) == 2


def test_collect_deduplicates_by_url_across_slices() -> None:
    """Bisected windows can overlap at their boundary and repeat an article."""

    def fetch(url: str) -> FakeResponse:
        body = (
            '{"articles": [{"url": "https://example.com/same", "title": "t", '
            '"seendate": "20260810T114500Z", "domain": "example.com", '
            '"language": "English", "sourcecountry": "United States"}]}'
        )
        return FakeResponse(200, body)

    client = GdeltClient(fetch=fetch)

    result = client.collect(
        query="sourcelang:eng",
        start=datetime(2026, 8, 11, tzinfo=UTC),
        end=datetime(2026, 8, 12, tzinfo=UTC),
    )

    assert len(result.articles) == 1
