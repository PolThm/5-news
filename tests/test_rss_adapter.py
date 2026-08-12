"""RSS adapter.

Story 1.3: coverage must not depend on a single upstream whose limits the
project does not control. RSS feeds from major outlets sit alongside GDELT,
producing the same ArticleRecord shape so nothing downstream can tell which
adapter an Article came from except by reading ``collected_by``.

One unreachable or malformed feed degrades coverage; it never fails the
collection (AD-10, NFR-3).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pipeline.adapters.rss import (
    FEEDS,
    RssClient,
    parse_feed,
    parse_rfc2822,
)

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Le Monde</title>
    <item>
      <title>Un accord de cessez-le-feu</title>
      <link>https://www.lemonde.fr/a.html</link>
      <pubDate>Mon, 11 Aug 2026 06:30:00 +0000</pubDate>
    </item>
    <item>
      <title>Les marches rebondissent</title>
      <link>https://www.lemonde.fr/b.html</link>
      <pubDate>Mon, 11 Aug 2026 09:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example</title>
  <entry>
    <title>An atom entry</title>
    <link href="https://example.com/atom-1"/>
    <updated>2026-08-11T06:30:00Z</updated>
  </entry>
</feed>
"""

# RSS 1.0 / RDF, the shape confirmed live on dw.com's actual feed. Every
# element -- item, title, link -- is namespaced under rss/1.0, and there is
# no pubDate at all; dc:date is the only date signal. Before Story 2.7's
# post-completion inspection caught this against a real cycle (0 records
# parsed from a genuinely live feed), every item here silently vanished.
SAMPLE_RDF = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel rdf:about="https://example.com/feed">
    <title>Example RDF Feed</title>
  </channel>
  <item rdf:about="https://example.com/rdf-1">
    <title>An RDF item</title>
    <link>https://example.com/rdf-1</link>
    <dc:date>2026-08-12T08:57:00Z</dc:date>
  </item>
</rdf:RDF>
"""


# --- Parsing -----------------------------------------------------------------


def test_parses_rss_items_into_article_records() -> None:
    records = parse_feed(SAMPLE_RSS, source="lemonde.fr", source_country="france", language="fr")

    assert len(records) == 2
    assert records[0].title == "Un accord de cessez-le-feu"
    assert records[0].url == "https://www.lemonde.fr/a.html"
    assert records[0].source_country == "france"
    assert records[0].collected_by == "rss"


def test_parses_atom_entries_too() -> None:
    """Major outlets publish both formats; supporting only RSS would silently
    drop whichever feeds happen to be Atom."""
    records = parse_feed(
        SAMPLE_ATOM, source="example.com", source_country="united-states", language="en"
    )

    assert len(records) == 1
    assert records[0].title == "An atom entry"
    assert records[0].url == "https://example.com/atom-1"


def test_produces_the_same_shape_as_gdelt() -> None:
    """AC: RSS Articles are written in the same shape as GDELT Articles."""
    from pipeline.adapters.gdelt import parse_articles as parse_gdelt

    gdelt_record = parse_gdelt(
        {
            "articles": [
                {
                    "url": "https://example.com/g",
                    "title": "t",
                    "seendate": "20260810T114500Z",
                    "domain": "example.com",
                    "language": "French",
                    "sourcecountry": "France",
                }
            ]
        }
    )[0]
    rss_record = parse_feed(
        SAMPLE_RSS, source="lemonde.fr", source_country="france", language="fr"
    )[0]

    assert set(gdelt_record.to_dict()) == set(rss_record.to_dict())


def test_records_which_adapter_produced_it() -> None:
    """AC: each Article records which adapter produced it — so a human reading
    the output can tell GDELT's coverage from RSS's."""
    record = parse_feed(SAMPLE_RSS, source="lemonde.fr", source_country="france", language="fr")[0]
    assert record.collected_by == "rss"


def test_skips_an_item_missing_a_title_or_link() -> None:
    feed = """<rss version="2.0"><channel>
      <item><title>Good</title><link>https://example.com/ok</link>
        <pubDate>Mon, 11 Aug 2026 06:30:00 +0000</pubDate></item>
      <item><title>No link</title></item>
    </channel></rss>"""

    records = parse_feed(feed, source="s", source_country="france", language="fr")

    assert len(records) == 1
    assert records[0].title == "Good"


def test_item_without_a_date_is_skipped() -> None:
    """Period assignment depends on the timestamp; an Article without one
    cannot be placed in a Briefing window."""
    feed = """<rss version="2.0"><channel>
      <item><title>Undated</title><link>https://example.com/x</link></item>
    </channel></rss>"""

    assert parse_feed(feed, source="s", source_country="france", language="fr") == []


def test_malformed_xml_yields_no_records_rather_than_raising() -> None:
    records = parse_feed("<rss><channel><item>", source="s", source_country="france", language="fr")
    assert records == []


# --- Dates -------------------------------------------------------------------


def test_parses_rfc2822_dates() -> None:
    parsed = parse_rfc2822("Mon, 11 Aug 2026 06:30:00 +0000")
    assert parsed == datetime(2026, 8, 11, 6, 30, tzinfo=UTC)


def test_converts_a_non_utc_offset_to_utc() -> None:
    """Spine convention: UTC everywhere inside the pipeline."""
    parsed = parse_rfc2822("Mon, 11 Aug 2026 08:30:00 +0200")
    assert parsed == datetime(2026, 8, 11, 6, 30, tzinfo=UTC)


def test_rejects_an_unparseable_date() -> None:
    with pytest.raises(ValueError):
        parse_rfc2822("sometime last tuesday")


# --- Feed configuration ------------------------------------------------------


def test_feeds_declare_country_and_language() -> None:
    """RSS gives no source metadata of its own, so the country and language a
    feed represents must be configured rather than inferred."""
    assert FEEDS
    for feed in FEEDS:
        assert feed.url.startswith("https://")
        assert feed.source
        assert feed.source_country
        assert feed.language


def test_feed_countries_are_zone_slugs() -> None:
    """A feed attributed to a country outside the Zone list would be invisible
    to every Country Briefing."""
    from pipeline.config import ZONES

    known = {z.slug for z in ZONES}
    for feed in FEEDS:
        assert feed.source_country in known, f"{feed.source} -> {feed.source_country}"


# --- Client resilience -------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status_code = status
        self.text = body
        self.headers: dict[str, str] = {}


def test_one_unreachable_feed_does_not_lose_the_others() -> None:
    """AC: the other feeds' Articles are still written, and the failure is
    recorded."""

    def fetch(url: str) -> FakeResponse:
        if "broken" in url:
            raise ConnectionError("host unreachable")
        return FakeResponse(200, SAMPLE_RSS)

    client = RssClient(fetch=fetch)
    result = client.collect(
        [
            _feed("https://broken.example.com/rss", "broken.example.com"),
            _feed("https://ok.example.com/rss", "ok.example.com"),
        ]
    )

    assert len(result.articles) == 2, "the working feed's articles survived"
    assert len(result.failures) == 1
    assert "host unreachable" in result.failures[0].detail


def test_a_malformed_feed_is_recorded_not_raised() -> None:
    def fetch(url: str) -> FakeResponse:
        return FakeResponse(200, "<html>not a feed</html>")

    client = RssClient(fetch=fetch)
    result = client.collect([_feed("https://x.example.com/rss", "x.example.com")])

    assert result.articles == []
    assert result.failures
    assert "no items" in result.failures[0].detail


def test_http_error_is_recorded() -> None:
    client = RssClient(fetch=lambda url: FakeResponse(404, "Not Found"))
    result = client.collect([_feed("https://x.example.com/rss", "x.example.com")])

    assert result.articles == []
    assert "404" in result.failures[0].detail


def test_all_feeds_failing_still_returns_a_result() -> None:
    """AD-10: an adapter reports, it never raises past its boundary."""

    def fetch(url: str) -> FakeResponse:
        raise TimeoutError("slow")

    client = RssClient(fetch=fetch)
    result = client.collect(
        [_feed("https://a.example.com/rss", "a"), _feed("https://b.example.com/rss", "b")]
    )

    assert result.empty is True
    assert len(result.failures) == 2


def _feed(url: str, source: str):
    from pipeline.adapters.rss import Feed

    return Feed(url=url, source=source, source_country="france", language="fr")


# --- Wire-service attribution (Story 2.3) -------------------------------------


SAMPLE_RSS_WITH_ATTRIBUTION = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Example</title>
    <item>
      <title>Wire dispatch republished</title>
      <link>https://example.com/wire.html</link>
      <pubDate>Mon, 11 Aug 2026 06:30:00 +0000</pubDate>
      <dc:creator>Agence France-Presse</dc:creator>
    </item>
    <item>
      <title>Original reporting</title>
      <link>https://example.com/original.html</link>
      <pubDate>Mon, 11 Aug 2026 07:00:00 +0000</pubDate>
      <dc:creator>Brittney Melton</dc:creator>
    </item>
    <item>
      <title>No attribution at all</title>
      <link>https://example.com/none.html</link>
      <pubDate>Mon, 11 Aug 2026 08:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""


def test_recognized_wire_service_creator_sets_wire_agency() -> None:
    records = parse_feed(
        SAMPLE_RSS_WITH_ATTRIBUTION, source="example.com", source_country="france", language="en"
    )
    by_title = {r.title: r for r in records}

    assert by_title["Wire dispatch republished"].wire_agency == "AFP"


def test_human_byline_in_dc_creator_does_not_resolve_to_an_agency() -> None:
    """dc:creator is overloaded: the same element holds a human byline for
    original reporting. An unrecognized name must resolve to None, not be
    guessed at."""
    records = parse_feed(
        SAMPLE_RSS_WITH_ATTRIBUTION, source="example.com", source_country="france", language="en"
    )
    by_title = {r.title: r for r in records}

    assert by_title["Original reporting"].wire_agency is None


def test_missing_dc_creator_leaves_wire_agency_none() -> None:
    """This is the normal case for the large majority of articles, and for
    entire feeds like BBC's — not an error."""
    records = parse_feed(
        SAMPLE_RSS_WITH_ATTRIBUTION, source="example.com", source_country="france", language="en"
    )
    by_title = {r.title: r for r in records}

    assert by_title["No attribution at all"].wire_agency is None


def test_wire_service_name_lookup_matches_known_variants() -> None:
    from pipeline.adapters.rss import resolve_wire_agency

    assert resolve_wire_agency("AP") == "AP"
    assert resolve_wire_agency("Associated Press") == "AP"
    assert resolve_wire_agency("The Associated Press") == "AP"
    assert resolve_wire_agency("Reuters") == "Reuters"
    assert resolve_wire_agency("AFP") == "AFP"
    assert resolve_wire_agency("Agence France-Presse") == "AFP"
    assert resolve_wire_agency("agence france-presse") == "AFP"  # case-insensitive


def test_wire_service_name_lookup_rejects_unrecognized_and_none() -> None:
    from pipeline.adapters.rss import resolve_wire_agency

    assert resolve_wire_agency("Brittney Melton") is None
    assert resolve_wire_agency(None) is None
    assert resolve_wire_agency("") is None


def test_resolve_wire_agency_tolerates_extra_internal_whitespace() -> None:
    """XML formatting can introduce a double space or non-breaking space
    around dc:creator's text content — this must not cost a match."""
    from pipeline.adapters.rss import resolve_wire_agency

    assert resolve_wire_agency("Agence  France-Presse") == "AFP"  # double space
    assert resolve_wire_agency("  Reuters  ") == "Reuters"  # leading/trailing


def test_resolve_wire_agency_matches_common_decorated_bylines() -> None:
    """Real-world dc:creator conventions often decorate the bare agency name
    ('Reuters Staff', 'By AFP') rather than using it alone — an adversarial
    review found the exact-match table as first written missed these common
    forms entirely."""
    from pipeline.adapters.rss import resolve_wire_agency

    assert resolve_wire_agency("By Reuters Staff") == "Reuters"
    assert resolve_wire_agency("Reuters Editorial") == "Reuters"
    assert resolve_wire_agency("AP News") == "AP"
    assert resolve_wire_agency("By AFP") == "AFP"


# --- RSS 1.0 / RDF support (post-Epic-2 real-cycle finding) -------------------


def test_parses_rdf_items_with_dc_date_fallback() -> None:
    """Confirmed against a real, live dw.com fetch: RSS 1.0/RDF has no
    pubDate and uses dc:date instead, under a fully namespaced <item>."""
    records = parse_feed(SAMPLE_RDF, source="dw.com", source_country="germany", language="en")

    assert len(records) == 1
    assert records[0].title == "An RDF item"
    assert records[0].url == "https://example.com/rdf-1"
    assert records[0].published_at.isoformat() == "2026-08-12T08:57:00+00:00"


def test_rdf_and_rss20_feeds_do_not_interfere_with_each_other() -> None:
    """The two <item> tag spellings (unprefixed vs RDF_NS-prefixed) are
    scanned unconditionally in the same pass -- confirm an ordinary RSS 2.0
    feed still parses correctly and isn't double-counted."""
    records = parse_feed(SAMPLE_RSS, source="lemonde.fr", source_country="france", language="fr")
    assert len(records) == 2
