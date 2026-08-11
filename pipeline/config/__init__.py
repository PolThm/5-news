"""Configuration as data. Read by every stage.

Adding a Zone is an edit to this file and nothing else — no stage contains a
hardcoded zone list. The slugs here appear in URLs (FR-2, FR-3) and in
published file paths (``data/briefings/<lang>/<zone>/<period>.json``), so
changing one is a breaking change to the site's routing.
"""

from __future__ import annotations

from collections.abc import Iterator

from pipeline.domain import OutputLanguage, Period, Zone, ZoneKind

# --- Stage names -------------------------------------------------------------

# The pipeline's six stages, in execution order. Also a reserved namespace:
# data/intermediate/ holds both <stage>/<cycle-id>/ and <cycle-id>/cycle.json
# as siblings, so a cycle identifier must never equal a stage name.
STAGE_NAMES: tuple[str, ...] = (
    "collect",
    "dedupe",
    "cluster",
    "rank",
    "summarize",
    "publish",
)

# --- Zones -------------------------------------------------------------------

# 15 Zones: World, 6 Continents, 8 Countries (FR-3).
#
# The `continent` field on a country is not decoration: FR-16 (Story 2.5)
# serves a country's containing continent when the country has too few
# Qualifying Clusters. Without the parent link there is nothing to fall back to.
ZONES: tuple[Zone, ...] = (
    Zone("world", ZoneKind.WORLD),
    Zone("europe", ZoneKind.CONTINENT),
    Zone("north-america", ZoneKind.CONTINENT),
    Zone("south-america", ZoneKind.CONTINENT),
    Zone("asia", ZoneKind.CONTINENT),
    Zone("africa", ZoneKind.CONTINENT),
    Zone("oceania", ZoneKind.CONTINENT),
    Zone("france", ZoneKind.COUNTRY, continent="europe"),
    Zone("united-kingdom", ZoneKind.COUNTRY, continent="europe"),
    Zone("germany", ZoneKind.COUNTRY, continent="europe"),
    Zone("united-states", ZoneKind.COUNTRY, continent="north-america"),
    Zone("japan", ZoneKind.COUNTRY, continent="asia"),
    Zone("china", ZoneKind.COUNTRY, continent="asia"),
    Zone("india", ZoneKind.COUNTRY, continent="asia"),
    Zone("brazil", ZoneKind.COUNTRY, continent="south-america"),
)

PERIODS: tuple[Period, ...] = (Period.DAY, Period.WEEK, Period.MONTH)

OUTPUT_LANGUAGES: tuple[OutputLanguage, ...] = (
    OutputLanguage.FR,
    OutputLanguage.EN,
    OutputLanguage.ES,
)

# Ranking thresholds (the Qualifying Cluster floor, item-count bounds, the
# anti-concentration cap) belong to Story 2.2/2.6, which own the rules that
# read them. Story 1.1 is scaffolding only — adding them here ahead of the
# stage that uses them was scope creep past "types only, no behavior" and was
# removed in code review.


# --- Derived -----------------------------------------------------------------


def zone_by_slug(slug: str) -> Zone:
    """Look up a Zone. Raises KeyError rather than returning None, because a
    caller asking for an unknown slug has a bug, not a missing value."""
    for zone in ZONES:
        if zone.slug == slug:
            return zone
    raise KeyError(f"unknown zone slug: {slug!r}")


def continent_for(zone: Zone) -> Zone | None:
    """The Zone this one falls back to when it has too few Qualifying Clusters
    (FR-16). Only countries have one."""
    if zone.continent is None:
        return None
    return zone_by_slug(zone.continent)


def briefing_combinations() -> Iterator[tuple[OutputLanguage, Zone, Period]]:
    """Every Briefing the pipeline generates per cycle: 15 x 3 x 3 = 135.

    Yielded in the order a Briefing is addressed — language, zone, period —
    matching the published path ``<lang>/<zone>/<period>.json``.
    """
    for language in OUTPUT_LANGUAGES:
        for zone in ZONES:
            for period in PERIODS:
                yield (language, zone, period)


__all__ = [
    "OUTPUT_LANGUAGES",
    "PERIODS",
    "STAGE_NAMES",
    "ZONES",
    "briefing_combinations",
    "continent_for",
    "zone_by_slug",
]
