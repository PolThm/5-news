"""Tests for the GDELT raw-file adapter.

No real network call anywhere here — the client takes an injectable ``fetch``,
exactly like every other adapter-boundary test in this pipeline, so these tests
never touch data.gdeltproject.org.

The two fixtures under ``tests/fixtures/`` are real trimmed slices of live GKG
files captured 2026-08-18: the same 27-column shape, the same ``Extras``
payload, the same entity encoding. Parsing tests run against real bytes rather
than a hand-written approximation of the format, because every surprise in
Story 6.2 came from the format not matching its documentation.

Story 6.2 replaced the DOC 2.0 search API with these files. The API tests that
used to live here (bisection, saturation, 429 backoff) went with it — that
machinery existed only to work around a throttle these files do not have.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pipeline.adapters.gdelt import (
    DOMAIN_COUNTRY_URL,
    FIPS_BY_ZONE,
    SLOTS_PER_COLLECTION,
    ZONE_BY_FIPS,
    GdeltClient,
    country_for_domain,
    focus_countries,
    parse_domain_country,
    parse_gkg,
    parse_gkg_date,
    slot_timestamps,
    zone_slug_for_fips,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _zipped(text: str, inner_name: str = "slot.csv") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(inner_name, text)
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


# --- Slot selection ----------------------------------------------------------


def test_slots_are_spaced_across_the_day_and_land_on_real_boundaries() -> None:
    """Only :00/:15/:30/:45 timestamps exist, and the most recent boundary is
    skipped because a slot is published a few minutes after its timestamp."""
    now = datetime(2026, 8, 18, 9, 7, 33, tzinfo=UTC)

    slots = slot_timestamps(now)

    assert len(slots) == SLOTS_PER_COLLECTION
    # 09:07 floors to 09:00, minus one slot -> 08:45.
    assert slots[0] == "20260818084500"
    assert slots[1] == "20260818004500"  # SLOT_SPACING_HOURS earlier
    for slot in slots:
        assert len(slot) == 14
        assert slot[-2:] == "00"  # seconds
        assert int(slot[-4:-2]) % 15 == 0  # minutes land on a real boundary


def test_slots_span_a_full_day_without_repeating() -> None:
    slots = slot_timestamps(datetime(2026, 8, 18, 12, 0, tzinfo=UTC))

    assert len(set(slots)) == len(slots)
    # The sampled slots reach back into the previous day rather than
    # clustering in the last few hours, so no timezone is over-represented.
    assert slots[0].startswith("20260818")
    assert slots[-1].startswith("20260817")


# --- Domain -> country lookup -------------------------------------------------


def test_the_lookup_is_parsed_from_three_tab_separated_columns() -> None:
    table = parse_domain_country(
        "bbc.co.uk\tUK\tUnited Kingdom\nlemonde.fr\tFR\tFrance\n\nbad-line\n"
    )

    assert table == {"bbc.co.uk": "UK", "lemonde.fr": "FR"}


def test_a_subdomain_resolves_through_its_registrable_parent() -> None:
    """GDELT records the registrable domain while the GKG sometimes reports a
    subdomain: g1.globo.com is absent from the table, globo.com is present.
    Without the suffix fallback that article loses its country."""
    table = {"globo.com": "BR"}

    assert country_for_domain("g1.globo.com", table) == "BR"
    assert country_for_domain("globo.com", table) == "BR"
    assert country_for_domain("unknown-outlet.example", table) is None
    assert country_for_domain("", table) is None


def test_zone_slugs_come_from_fips_and_the_two_tables_cannot_drift() -> None:
    assert {code: zone for zone, code in FIPS_BY_ZONE.items()} == ZONE_BY_FIPS
    assert zone_slug_for_fips("UK") == "united-kingdom"
    assert zone_slug_for_fips("BR") == "brazil"


def test_a_country_outside_the_eight_zones_keeps_its_own_identity() -> None:
    """The Consensus Score counts *distinct* countries. Collapsing every
    non-Zone country into one bucket would make an Event covered by Italian,
    Korean and Greek outlets report as one country instead of three --
    understating the number the product asks readers to trust."""
    assert zone_slug_for_fips("IT") == "it"
    assert zone_slug_for_fips("AS") == "as"
    assert zone_slug_for_fips("IT") != zone_slug_for_fips("AS")

    # Only a genuinely unresolved domain is "unknown".
    assert zone_slug_for_fips(None) == "unknown"
    assert zone_slug_for_fips("") == "unknown"


# --- Parsing ------------------------------------------------------------------


def test_parses_a_real_english_slice() -> None:
    records = parse_gkg(_fixture("gkg_english_sample.csv"), {})

    assert records
    for record in records:
        assert record.title.strip()
        assert record.url.startswith("http")
        assert record.language == "en"  # no TranslationInfo means English
        assert record.collected_by == "gdelt"
        assert record.published_at.tzinfo is not None


def test_parses_a_real_translingual_slice_keeping_the_source_language() -> None:
    """Every French and Spanish article comes from the translingual file.
    Fetching only the English one would rebuild the exact language defect
    reported on 2026-08-13, where Spanish pages carried French text."""
    records = parse_gkg(_fixture("gkg_translingual_sample.csv"), {})

    languages = {record.language for record in records}
    assert "fr" in languages
    assert "es" in languages


def test_the_title_comes_from_extras_and_entities_are_decoded() -> None:
    """The GKG has no title column -- the title is inside Extras, and its
    numeric HTML entities would otherwise reach the page verbatim."""
    row = _row(extras="<PAGE_TITLE>Canicule&#xA0;: l&#39;astuce confirm&#xE9;e</PAGE_TITLE>")

    records = parse_gkg(row, {})

    assert len(records) == 1
    assert records[0].title == "Canicule\xa0: l'astuce confirmée"


def test_a_row_without_a_usable_title_is_skipped_not_placeholdered() -> None:
    """An Article with no title cannot be deduped, clustered, or summarized,
    and a placeholder would end up rendered on the page."""
    assert parse_gkg(_row(extras=""), {}) == []
    assert parse_gkg(_row(extras="<PAGE_LINKS>https://x.test</PAGE_LINKS>"), {}) == []
    assert parse_gkg(_row(extras="<PAGE_TITLE>   </PAGE_TITLE>"), {}) == []


def test_a_short_row_is_skipped_rather_than_failing_the_file() -> None:
    """One malformed row must not cost a whole slot's coverage."""
    good = _row(extras="<PAGE_TITLE>Real headline</PAGE_TITLE>")

    records = parse_gkg("too\tfew\tcolumns\n" + good, {})

    assert len(records) == 1


def test_source_country_uses_the_lookup() -> None:
    row = _row(source="bbc.co.uk", extras="<PAGE_TITLE>Headline</PAGE_TITLE>")

    records = parse_gkg(row, {"bbc.co.uk": "UK"})

    assert records[0].source_country == "united-kingdom"


def test_an_unresolved_domain_still_yields_an_article() -> None:
    """It is real coverage and still counts toward Independent Sources; it
    simply cannot contribute to country diversity."""
    row = _row(source="nowhere.test", extras="<PAGE_TITLE>Headline</PAGE_TITLE>")

    records = parse_gkg(row, {})

    assert len(records) == 1
    assert records[0].source_country == "unknown"


def test_the_slot_date_is_parsed_as_utc() -> None:
    assert parse_gkg_date("20260818093000") == datetime(2026, 8, 18, 9, 30, tzinfo=UTC)


def test_a_row_with_an_unparseable_date_is_skipped() -> None:
    row = _row(date="not-a-date", extras="<PAGE_TITLE>Headline</PAGE_TITLE>")

    assert parse_gkg(row, {}) == []


# --- Fetching and degradation --------------------------------------------------


def test_a_missing_slot_degrades_that_slot_only() -> None:
    """A slot published later than expected 404s. Every other slot must still
    contribute (AD-10)."""
    body = _zipped(_fixture("gkg_english_sample.csv"))
    calls: list[str] = []

    def fetch(url: str) -> FakeResponse:
        calls.append(url)
        if DOMAIN_COUNTRY_URL in url:
            return FakeResponse(200, b"bbc.co.uk\tUK\tUnited Kingdom\n")
        if url.endswith("translation.gkg.csv.zip"):
            return FakeResponse(404)
        return FakeResponse(200, body)

    result = GdeltClient(fetch=fetch).collect(now=datetime(2026, 8, 18, 9, 0, tzinfo=UTC))

    assert result.articles
    assert all("HTTP 404" in f.detail for f in result.failures)
    assert len(result.failures) == SLOTS_PER_COLLECTION  # one per translingual file


def test_a_corrupt_archive_degrades_that_file_only() -> None:
    def fetch(url: str) -> FakeResponse:
        if DOMAIN_COUNTRY_URL in url:
            return FakeResponse(200, b"bbc.co.uk\tUK\tUnited Kingdom\n")
        if url.endswith("translation.gkg.csv.zip"):
            return FakeResponse(200, b"not a zip at all")
        return FakeResponse(200, _zipped(_fixture("gkg_english_sample.csv")))

    result = GdeltClient(fetch=fetch).collect(now=datetime(2026, 8, 18, 9, 0, tzinfo=UTC))

    assert result.articles
    assert any("could not read archive" in f.detail for f in result.failures)


def test_a_raised_connection_error_degrades_rather_than_propagating() -> None:
    def fetch(url: str) -> FakeResponse:
        raise ConnectionError("boom")

    result = GdeltClient(fetch=fetch).collect(now=datetime(2026, 8, 18, 9, 0, tzinfo=UTC))

    assert result.articles == []
    assert any("request failed" in f.detail for f in result.failures)
    assert any("no slot yielded any Article" in f.detail for f in result.failures)


def test_a_failed_country_lookup_degrades_coverage_not_the_cycle() -> None:
    """Without the lookup every Article lands in "unknown": Zone Briefings
    thin out and country diversity stops counting. That is a recorded
    shortfall, not a crashed cycle."""

    def fetch(url: str) -> FakeResponse:
        if DOMAIN_COUNTRY_URL in url:
            return FakeResponse(503)
        return FakeResponse(200, _zipped(_fixture("gkg_english_sample.csv")))

    result = GdeltClient(fetch=fetch).collect(now=datetime(2026, 8, 18, 9, 0, tzinfo=UTC))

    assert result.articles
    assert all(a["source_country"] == "unknown" for a in result.articles)
    assert any("domain-country lookup" in f.detail for f in result.failures)


def test_articles_are_deduplicated_across_slots_and_files() -> None:
    """The same article appears in more than one 15-minute slot, and in both
    the English and translingual files."""
    body = _zipped(_fixture("gkg_english_sample.csv"))

    def fetch(url: str) -> FakeResponse:
        if DOMAIN_COUNTRY_URL in url:
            return FakeResponse(200, b"")
        return FakeResponse(200, body)

    result = GdeltClient(fetch=fetch).collect(now=datetime(2026, 8, 18, 9, 0, tzinfo=UTC))

    urls = [a["url"] for a in result.articles]
    assert len(urls) == len(set(urls))
    # Every slot returned the same file, so the union is one file's worth.
    assert len(urls) == len(parse_gkg(_fixture("gkg_english_sample.csv"), {}))


def test_collection_stops_at_the_deadline() -> None:
    """Story 6.1's bound survives the channel change: a cycle killed by the
    job timeout loses everything it has already done, including batches it
    has already paid for."""
    from pipeline.adapters import gdelt

    clock = {"now": 0.0}

    def fetch(url: str) -> FakeResponse:
        clock["now"] += 400.0  # each fetch burns most of the budget
        return FakeResponse(200, _zipped(_fixture("gkg_english_sample.csv")))

    original = gdelt.time.monotonic
    gdelt.time.monotonic = lambda: clock["now"]
    try:
        result = GdeltClient(fetch=fetch).collect(now=datetime(2026, 8, 18, 9, 0, tzinfo=UTC))
    finally:
        gdelt.time.monotonic = original

    assert any("deadline" in f.detail for f in result.failures)
    # Partial coverage that lands beats complete coverage that gets killed.
    assert result.articles


def test_both_files_are_requested_for_every_slot() -> None:
    requested: list[str] = []

    def fetch(url: str) -> FakeResponse:
        requested.append(url)
        if DOMAIN_COUNTRY_URL in url:
            return FakeResponse(200, b"")
        return FakeResponse(200, _zipped(_fixture("gkg_english_sample.csv")))

    GdeltClient(fetch=fetch).collect(now=datetime(2026, 8, 18, 9, 0, tzinfo=UTC))

    slot_urls = [u for u in requested if DOMAIN_COUNTRY_URL not in u]
    assert len(slot_urls) == SLOTS_PER_COLLECTION * 2
    assert sum(1 for u in slot_urls if u.endswith("translation.gkg.csv.zip")) == (
        SLOTS_PER_COLLECTION
    )


# --- helpers ------------------------------------------------------------------


def _row(
    *,
    date: str = "20260818093000",
    source: str = "example.test",
    url: str = "https://example.test/article",
    translation_info: str = "",
    extras: str = "<PAGE_TITLE>Headline</PAGE_TITLE>",
    locations: str = "",
) -> str:
    """One GKG row with only the columns this adapter reads populated."""
    columns = [""] * 27
    columns[1] = date
    columns[3] = source
    columns[4] = url
    columns[10] = locations
    columns[25] = translation_info
    columns[26] = extras
    return "\t".join(columns) + "\n"


def test_the_helper_row_matches_the_real_column_count() -> None:
    """Guards the hand-built rows above against a format change: if the real
    files gain or lose a column, these tests should fail loudly rather than
    silently testing a shape that no longer exists."""
    real = _fixture("gkg_english_sample.csv").splitlines()[0]

    assert len(real.split("\t")) == len(_row().rstrip("\n").split("\t"))


@pytest.mark.parametrize(
    ("srclc", "expected"),
    [("fra", "fr"), ("spa", "es"), ("zho", "zh"), ("xyz", "xyz")],
)
def test_language_codes_map_to_two_letters_with_an_honest_fallback(
    srclc: str, expected: str
) -> None:
    row = _row(translation_info=f"srclc:{srclc};", extras="<PAGE_TITLE>T</PAGE_TITLE>")

    assert parse_gkg(row, {})[0].language == expected


# --- What an article is about, not where its outlet sits ---------------------


def test_the_dominant_country_is_always_kept() -> None:
    """An article with any usable location must remain placeable: the
    thresholds trim the tail, they never empty the result."""
    assert focus_countries("1#India#IN#IN#20#77#1") == ("india",)


def test_an_incidental_single_mention_is_dropped() -> None:
    """The 2026-08-19 bug: a suspended Australian tennis player reached the
    Europe Briefing on one passing mention each of the UK and Ukraine. With
    three mentions across three countries the share test alone clears them
    all, so a country must also be named more than once to count."""
    locations = (
        "1#Australia#AS#AS#-25#135#1;1#Australia#AS#AS#-25#135#2;"
        "1#UK#UK#UK#54#-4#3;1#Ukraine#UP#UP#49#32#4"
    )
    assert focus_countries(locations) == ("as",)


def test_a_genuinely_bi_national_story_keeps_both() -> None:
    """Trimming the tail must not collapse every article to one country -- a
    story really about two places keeps both."""
    locations = (
        "1#UK#UK#UK#54#-4#1;1#UK#UK#UK#54#-4#2;1#France#FR#FR#46#2#3;1#France#FR#FR#46#2#4"
    )
    assert set(focus_countries(locations)) == {"united-kingdom", "france"}


def test_countries_come_back_as_zone_slugs_most_mentioned_first() -> None:
    """Same vocabulary as `source_country`, so rank can compare them directly,
    and ordered so the first entry is the article's own subject."""
    locations = (
        "1#Spain#SP#SP#40#-4#1;1#Spain#SP#SP#40#-4#2;1#Spain#SP#SP#40#-4#3;"
        "1#Italy#IT#IT#42#12#4;1#Italy#IT#IT#42#12#5"
    )
    assert focus_countries(locations) == ("spain", "it")


def test_an_absent_or_unparseable_location_field_yields_nothing() -> None:
    """~20% of GKG rows carry no usable location. That is the honest answer,
    not a failure -- such an Article corroborates a Cluster without placing
    it (see pipeline.stages.rank._is_relevant_to)."""
    assert focus_countries("") == ()
    assert focus_countries("no-hashes-at-all") == ()
    assert focus_countries("1#Somewhere##ADM#0#0#0") == ()


def test_a_parsed_row_carries_what_it_is_about() -> None:
    """End to end through parse_gkg, not just the helper: the field has to
    survive onto the ArticleRecord for rank to ever see it."""
    row = _row(
        source="lemonde.fr",
        extras="<PAGE_TITLE>Un titre</PAGE_TITLE>",
        locations="1#Spain#SP#SP#40#-4#1;1#Spain#SP#SP#40#-4#2",
    )
    records = parse_gkg(row, {"lemonde.fr": "FR"})

    assert len(records) == 1
    assert records[0].source_country == "france", "where the outlet sits"
    assert records[0].mentioned_countries == ("spain",), "what the article is about"
