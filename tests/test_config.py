"""Configuration is data, not code (AC 3).

These tests pin the values that URLs, published file paths, and the
24-Briefing matrix all depend on. Changing a slug here breaks the site's
routing, so the tests exist to make such a change deliberate.
"""

from pipeline.config import (
    OUTPUT_LANGUAGES,
    PERIODS,
    ZONES,
    briefing_combinations,
    countries_in_continent,
)
from pipeline.domain import ZoneKind


def test_four_zones() -> None:
    """Narrowed from 15 on 2026-08-19 (World, 6 Continents, 8 Countries).

    Two of those Continents -- Africa and Oceania -- never had a single
    Country defined beneath them, so the Zone-word cycle could pass through
    them but never descend. Covering four Zones well was the brief's own
    guidance; fifteen was the PRD's addition.
    """
    assert len(ZONES) == 4


def test_zone_slugs_are_exact() -> None:
    """Slugs appear in URLs and published paths. They are not free to change."""
    assert [z.slug for z in ZONES] == [
        "world",
        "europe",
        "france",
        "spain",
    ]


def test_zone_kinds() -> None:
    kinds = [z.kind for z in ZONES]
    assert kinds.count(ZoneKind.WORLD) == 1
    assert kinds.count(ZoneKind.CONTINENT) == 1
    assert kinds.count(ZoneKind.COUNTRY) == 2


def test_every_country_has_a_continent() -> None:
    """FR-16 (Story 2.5) serves a country's continent when the country is too
    thin. Without the parent link there is nothing to fall back to."""
    continents = {z.slug for z in ZONES if z.kind is ZoneKind.CONTINENT}
    for zone in ZONES:
        if zone.kind is ZoneKind.COUNTRY:
            assert zone.continent is not None, f"{zone.slug} has no continent"
            assert zone.continent in continents, f"{zone.slug} -> unknown {zone.continent}"


def test_non_countries_have_no_continent() -> None:
    for zone in ZONES:
        if zone.kind is not ZoneKind.COUNTRY:
            assert zone.continent is None


def test_periods() -> None:
    assert [p.value for p in PERIODS] == ["day", "week"]


def test_output_languages() -> None:
    assert [lang.value for lang in OUTPUT_LANGUAGES] == ["fr", "en", "es"]


def test_matrix_is_24() -> None:
    """4 Zones x 2 Periods x 3 Output Languages (FR-15, narrowed 2026-08-19)."""
    combos = list(briefing_combinations())
    assert len(combos) == 24
    assert len(set(combos)) == 24, "combinations must be unique"


def test_matrix_ordering_is_lang_zone_period() -> None:
    """A Briefing is addressed by the triple in this order (spine conventions)."""
    first = next(iter(briefing_combinations()))
    lang, zone, period = first
    assert lang in OUTPUT_LANGUAGES
    assert zone in ZONES
    assert period in PERIODS


def test_no_zone_slug_collides_with_a_stage_name() -> None:
    """data/intermediate/ holds both <stage>/<cycle-id>/ and <cycle-id>/cycle.json.
    A collision between the two namespaces would corrupt both trees."""
    from pipeline.config import STAGE_NAMES

    assert not ({z.slug for z in ZONES} & set(STAGE_NAMES))


def test_a_continent_is_geography_not_the_zones_defined_under_it() -> None:
    """The Europe Briefing must mean Europe, not "the Country Zones we happen
    to route to inside Europe".

    Relevance was once derived from ZONES itself, which made a continental
    Briefing a union of its Country Zones: with 15 Zones, Europe already
    excluded Italy and the Netherlands, and narrowing to 4 Zones on 2026-08-19
    would have reduced it to France plus Spain -- a continental Briefing that
    duplicated its own two countries. A country needs no Zone of its own to
    have happened in Europe.
    """
    europe = countries_in_continent("europe")

    # Countries that are Zones, and countries that are not, both count.
    for slug in ("france", "spain", "germany", "united-kingdom"):
        assert slug in europe, f"{slug} should count toward Europe"

    # Non-Zone countries arrive as lowercased FIPS codes, not names -- see
    # gdelt.zone_slug_for_fips. Both forms must resolve or the continent
    # silently loses whichever half it fails to match.
    for code in ("it", "be", "nl", "pl", "up"):
        assert code in europe, f"FIPS {code} should count toward Europe"

    # And it stays a continent, not a catch-all.
    for slug in ("japan", "china", "brazil", "us", "cn"):
        assert slug not in europe, f"{slug} must not count toward Europe"


def test_transcontinental_countries_are_decided_by_newsroom_not_landmass() -> None:
    """Russia and Turkey are out; Ukraine and Cyprus are in.

    The table is matched against `source_country` -- where an Article's outlet
    is based, not where the event happened -- so including Russia would have
    added Russian outlets on Russian domestic subjects rather than adding
    coverage of the war in Ukraine. That war reaches Europe's Briefing through
    Ukraine and through every European outlet covering it, neither of which
    depends on Russia being listed. Cyprus is the mirror image: Asian by
    geography, European by press.
    """
    europe = countries_in_continent("europe")

    assert "up" in europe, "Ukraine (FIPS UP) must count toward Europe"
    assert "cy" in europe, "Cyprus must count toward Europe"
    assert "rs" not in europe, "Russia must not count toward Europe"
    assert "tu" not in europe, "Turkey must not count toward Europe"


def test_only_routable_continents_have_a_geography_table() -> None:
    """Continents that are no longer Zones resolve to nothing rather than
    guessing, so a stale caller gets an empty set instead of a wrong one."""
    assert countries_in_continent("asia") == frozenset()
    assert countries_in_continent("not-a-continent") == frozenset()
