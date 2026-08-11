"""Configuration is data, not code (AC 3).

These tests pin the values that URLs, published file paths, and the
135-Briefing matrix all depend on. Changing a slug here breaks the site's
routing, so the tests exist to make such a change deliberate.
"""

from pipeline.config import OUTPUT_LANGUAGES, PERIODS, ZONES, briefing_combinations
from pipeline.domain import ZoneKind


def test_fifteen_zones() -> None:
    assert len(ZONES) == 15


def test_zone_slugs_are_exact() -> None:
    """Slugs appear in URLs and published paths. They are not free to change."""
    assert [z.slug for z in ZONES] == [
        "world",
        "europe",
        "north-america",
        "south-america",
        "asia",
        "africa",
        "oceania",
        "france",
        "united-kingdom",
        "germany",
        "united-states",
        "japan",
        "china",
        "india",
        "brazil",
    ]


def test_zone_kinds() -> None:
    kinds = [z.kind for z in ZONES]
    assert kinds.count(ZoneKind.WORLD) == 1
    assert kinds.count(ZoneKind.CONTINENT) == 6
    assert kinds.count(ZoneKind.COUNTRY) == 8


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
    assert [p.value for p in PERIODS] == ["day", "week", "month"]


def test_output_languages() -> None:
    assert [lang.value for lang in OUTPUT_LANGUAGES] == ["fr", "en", "es"]


def test_matrix_is_135() -> None:
    """15 Zones x 3 Periods x 3 Output Languages (FR-15)."""
    combos = list(briefing_combinations())
    assert len(combos) == 135
    assert len(set(combos)) == 135, "combinations must be unique"


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
