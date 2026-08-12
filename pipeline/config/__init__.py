"""Configuration as data. Read by every stage.

Adding a Zone is an edit to this file and nothing else — no stage contains a
hardcoded zone list. The slugs here appear in URLs (FR-2, FR-3) and in
published file paths (``data/briefings/<lang>/<zone>/<period>.json``), so
changing one is a breaking change to the site's routing.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

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

# --- Ranking thresholds -------------------------------------------------------
#
# Removed from this file during Story 1.1's code review as premature — no
# rank stage existed yet to consume them. Story 2.2 is that consumer; the
# anti-concentration cap (Story 2.6) and Continent fallback (Story 2.5) will
# read these same constants rather than each defining their own copy (AD-12:
# one owner per value).

# PRD Glossary, "Qualifying Cluster": at least 2 Independent Sources from at
# least 2 distinct countries. Both floors are `>=` and both must hold — a
# Cluster with 5 sources all from one country does not qualify.
MIN_INDEPENDENT_SOURCES: Final[int] = 2
MIN_COUNTRIES: Final[int] = 2

# FR-4: at most 5 Qualifying Clusters appear in any Briefing; the rest count
# toward Discarded Volume. Never padded below this if fewer qualify.
MAX_SELECTED_CLUSTERS: Final[int] = 5

# FR-16: "a Country Zone yielding fewer than 2 Qualifying Clusters serves its
# Continent's Briefing." A distinct concept from MIN_INDEPENDENT_SOURCES/
# MIN_COUNTRIES above — those gate whether one Cluster qualifies at all;
# this gates whether a Zone has enough qualifying Clusters to serve on its
# own. Named separately even though the value happens to match, because a
# future change to one must not accidentally change the other (AD-12
# applied to config values, not just stage-owned fields).
MIN_QUALIFYING_FOR_ZONE: Final[int] = 2

# FR-17: "A Continent Briefing contains at most 2 items from the same
# country" -- so "Africa" does not silently mean "Nigeria." Applied against
# a Cluster's origin_country (Story 2.6: the country of its earliest
# reported member), not its full countries set -- a Cluster's origin is
# always exactly one country, which is what a per-country cap needs.
# Explicitly not applied to World (FR-17's own stated exemption) or to a
# Country Zone's own Briefing (the rule is stated as being about Continent
# Briefings specifically).
MAX_PER_COUNTRY: Final[int] = 2

# If this ever failed, a Zone could never avoid falling back even after
# selecting a full Briefing — MIN_QUALIFYING_FOR_ZONE is checked against the
# pre-selection count in pipeline.stages.rank._rank_for_zone, so raising it
# above MAX_SELECTED_CLUSTERS would silently make every Zone fall back
# regardless of how much real coverage it has. Caught here, at import time,
# rather than as a confusing runtime symptom in rank.py.
assert MIN_QUALIFYING_FOR_ZONE <= MAX_SELECTED_CLUSTERS, (
    "MIN_QUALIFYING_FOR_ZONE must not exceed MAX_SELECTED_CLUSTERS"
)

# --- Syndication Detection, layer 3 (Story 2.4) -------------------------------
#
# REASONED, NOT MEASURED. The Build Order (PRD §10) calls for calibrating
# this threshold against real cycle output inspected after layers 1-2 ship —
# no such output existed when this story was built, so this value is a
# starting hypothesis, not a validated constant. Revisit against real
# data/intermediate/dedupe/ output at the first opportunity; a threshold that
# turns out to merge (or miss) more than expected is the foreseen cost of
# this deliberate deviation, not evidence of a bug in the code that reads it.
#
# Deliberately stricter than pipeline/stages/cluster.py's
# _SAME_EVENT_DISTANCE = 0.4. That constant answers "same real-world Event"
# — a looser question where two Independent Sources covering the same
# happening is the *desired*, counted outcome. This constant answers "same
# dispatch, merely reworded" — reusing the looser value here would silently
# collapse genuine independent reporting, which is the one error direction
# this whole pipeline exists to avoid. 0.25 (cosine similarity ~= 0.97 via
# the same d^2 = 2 - 2c relationship documented in cluster.py) is chosen to
# require near-paraphrase closeness, not merely topical relatedness.
REWRITE_SIMILARITY_FLOOR: Final[float] = 0.25

# --- Cross-day Cluster continuity, FR-18 (Story 2.7) --------------------------
#
# REASONED, NOT MEASURED — the same deliberate deviation Story 2.4 made for
# REWRITE_SIMILARITY_FLOOR, made here for the analogous reason: the
# architecture spine explicitly defers "Cluster identity across cycles" to be
# informed by an inspection window that has not happened yet. Revisit against
# real data/history/ output at the first opportunity.
#
# Positioned between the pipeline's two other embedding-distance floors, not
# copied from either: cluster.py's _SAME_EVENT_DISTANCE (0.4) links same-day
# coverage, where wording drift is minimal because every Article was written
# within hours of the same news cycle. REWRITE_SIMILARITY_FLOOR (0.25) links
# same-day *dispatches*, an even narrower claim. This constant links an
# *ongoing* Event's coverage one or more days apart, where the story has had
# time to develop and be reworded more than same-day coverage would be, but
# still describes the same Event, not merely a related one -- looser than
# REWRITE_SIMILARITY_FLOOR's "same dispatch" claim, but not as loose as
# _SAME_EVENT_DISTANCE's same-day tolerance, since more days apart means more
# opportunity for two genuinely different follow-on Events to drift into
# each other's neighborhood by coincidence.
CROSS_DAY_SIMILARITY_FLOOR: Final[float] = 0.35


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
    "CROSS_DAY_SIMILARITY_FLOOR",
    "MAX_PER_COUNTRY",
    "MAX_SELECTED_CLUSTERS",
    "MIN_COUNTRIES",
    "MIN_INDEPENDENT_SOURCES",
    "MIN_QUALIFYING_FOR_ZONE",
    "REWRITE_SIMILARITY_FLOOR",
    "OUTPUT_LANGUAGES",
    "PERIODS",
    "STAGE_NAMES",
    "ZONES",
    "briefing_combinations",
    "continent_for",
    "zone_by_slug",
]
