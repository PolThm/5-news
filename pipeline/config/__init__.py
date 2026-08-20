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

# 4 Zones: World, 1 Continent, 2 Countries (FR-3, narrowed 2026-08-19).
#
# Down from 15 (World, 6 Continents, 8 Countries). The original set was the
# PRD's own invention rather than anything the brief asked for -- the brief's
# guidance was that 5-10 countries covered *well* beats the whole world
# covered badly, which is what this restores. Africa and Oceania never had a
# single Country defined under them, so two of the six Continents could never
# be reached by the Zone-word cycle's country hops at all.
#
# The `continent` field on a country is not decoration: FR-16 (Story 2.5)
# serves a country's containing continent when the country has too few
# Qualifying Clusters. Without the parent link there is nothing to fall back
# to -- both Countries here point at Europe, so the fallback stays exercised.
#
# Note this is the set of *routable* Zones, not the set of countries the
# pipeline can recognize as an Article's origin. Those are different concerns
# and live apart: see `pipeline.adapters.gdelt.FIPS_BY_ZONE`, which still
# names every country it can resolve so a Consensus Score can say "Germany"
# rather than "gm".
ZONES: tuple[Zone, ...] = (
    Zone("world", ZoneKind.WORLD),
    Zone("europe", ZoneKind.CONTINENT),
    Zone("france", ZoneKind.COUNTRY, continent="europe"),
    Zone("spain", ZoneKind.COUNTRY, continent="europe"),
)

# Narrowed from (day, week, month) on 2026-08-19. Month is gone: it was the
# hardest window to fill honestly -- a 30-day pool needs 30 days of cycles
# before it means anything -- and it cost a third of every publish.
PERIODS: tuple[Period, ...] = (Period.DAY, Period.WEEK)

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

# At most this many items from one editorial category in a Briefing, so a Top 5
# is not five variations on one kind of news.
#
# The need was measured, not assumed: a real Briefing on 2026-08-19 gave Spain
# two separate items about earthquakes in Granada, and World four items out of
# five filed under "Disasters and accidents". The chronicle's own taxonomy
# ("Armed conflicts and attacks", "Politics and elections", "Disasters and
# accidents") is the category, so this needs no topic model of its own.
#
# Deliberately NOT solved by deduplicating similar events, which was tried and
# rejected on evidence: two updates of one story (both Granada earthquakes) sit
# at cosine distance 0.315, while two genuinely distinct events of the same kind
# (wildfires in Zamora and in Ourense) sit at 0.155 -- closer. Semantic
# similarity cannot tell "same story" from "same kind of story", so merging on
# it would fuse unrelated events, which is a worse failure than showing two
# related ones. Capping the category caps the symptom without ever claiming two
# events are one.
#
# 2 rather than 1 because a genuinely heavy news day can legitimately be mostly
# one category -- a war week is mostly conflict -- and the cap must trim
# monotony, not rewrite the day.
MAX_PER_CATEGORY: Final[int] = 2

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
    """Every Briefing the pipeline generates per cycle: 4 x 2 x 3 = 24.

    Yielded in the order a Briefing is addressed — language, zone, period —
    matching the published path ``<lang>/<zone>/<period>.json``.
    """
    for language in OUTPUT_LANGUAGES:
        for zone in ZONES:
            for period in PERIODS:
                yield (language, zone, period)


# --- Geography ---------------------------------------------------------------

# Which FIPS 10-4 country codes count as Europe, for deciding whether a Cluster
# belongs in the Europe Briefing.
#
# This exists because relevance used to be derived from ZONES itself
# (`{z.slug for z in ZONES if z.continent == "europe"}`), which quietly made
# the Europe Briefing mean "the Country Zones defined under Europe" rather than
# "Europe". With 15 Zones that was France, the United Kingdom and Germany --
# Italy, Belgium and the Netherlands were already excluded. Narrowing to 4
# Zones on 2026-08-19 would have cut it to France and Spain, turning a
# continental Briefing into a duplicate of its two countries, which is what
# made the pre-existing flaw worth fixing rather than inheriting.
#
# Navigability and geography are now separate concerns: ZONES says where a
# reader can go, this says where a story happened. A country needs no Zone of
# its own to count toward its continent.
#
# Codes verified against GDELT's own published domain-to-country table (the
# same file the adapter resolves sources with) rather than written from
# memory, because FIPS is full of traps: Czechia is EZ, Denmark DA, Ireland
# EI, Latvia LG, Lithuania LH, Portugal PO, Serbia RI, Slovakia LO, Spain SP,
# Sweden SW, Switzerland SZ, Ukraine UP, Belarus BO.
#
# Russia and Turkey are deliberately EXCLUDED, and the reasoning matters
# because it is easy to get backwards. This table is matched against
# `source_country`, which is where an Article's *outlet* is based -- not where
# the event happened. Including Russia would not add coverage of the war in
# Ukraine; it would add Russian outlets writing about Russian domestic
# politics, which is not what a reader opening a Europe Briefing is asking
# for. The war stays in Europe's Briefing regardless, through Ukraine (UP,
# below) and through every French, German and British outlet covering it.
#
# Both countries straddle the continental boundary, so neither is a clear-cut
# exclusion on geography alone -- the deciding question was which set of
# newsrooms belongs in this Briefing, not which landmass they sit on.
#
# Cyprus is kept for the mirror-image reason: geographically Asian, but an EU
# member whose press is European by any editorial measure.
_EUROPE_FIPS: frozenset[str] = frozenset(
    {
        "AL",  # Albania
        "AN",  # Andorra
        "AU",  # Austria
        "BE",  # Belgium
        "BK",  # Bosnia-Herzegovina
        "BO",  # Belarus
        "BU",  # Bulgaria
        "CY",  # Cyprus
        "DA",  # Denmark
        "EI",  # Ireland
        "EN",  # Estonia
        "EZ",  # Czech Republic
        "FI",  # Finland
        "FO",  # Faroe Islands
        "FR",  # France
        "GI",  # Gibraltar
        "GK",  # Guernsey
        "GM",  # Germany
        "GR",  # Greece
        "HR",  # Croatia
        "HU",  # Hungary
        "IC",  # Iceland
        "IM",  # Isle of Man
        "IT",  # Italy
        "JE",  # Jersey
        "KV",  # Kosovo
        "LG",  # Latvia
        "LH",  # Lithuania
        "LO",  # Slovak Republic
        "LS",  # Liechtenstein
        "LU",  # Luxembourg
        "MD",  # Moldova
        "MJ",  # Montenegro
        "MK",  # Macedonia
        "MN",  # Monaco
        "MT",  # Malta
        "NL",  # Netherlands
        "NO",  # Norway
        "PL",  # Poland
        "PO",  # Portugal
        "RI",  # Serbia
        "RO",  # Romania
        "SI",  # Slovenia
        "SM",  # San Marino
        "SP",  # Spain
        "SV",  # Svalbard
        "SW",  # Sweden
        "SZ",  # Switzerland
        "UK",  # United Kingdom
        "UP",  # Ukraine
        "VT",  # Vatican City
    }
)


# English country names -> FIPS, for reading a country out of prose written in
# English (the editorial agenda's chronicle entries name their countries in
# wikilinks: "United Arab Emirates", "Ukraine", "Sudan").
#
# Built from the same code/name pairs as _EUROPE_FIPS above so the two cannot
# drift, plus the countries the GDELT adapter can already name. Aliases cover
# the forms the chronicle actually uses -- "UK" and "Britain" for the United
# Kingdom, "Czechia" alongside "Czech Republic" -- because a name this table
# misses silently costs that event its Zone.
_FIPS_BY_ENGLISH_NAME: dict[str, str] = {
    "albania": "AL",
    "andorra": "AN",
    "austria": "AU",
    "belgium": "BE",
    "bosnia-herzegovina": "BK",
    "belarus": "BO",
    "bulgaria": "BU",
    "cyprus": "CY",
    "denmark": "DA",
    "ireland": "EI",
    "estonia": "EN",
    "czech republic": "EZ",
    "finland": "FI",
    "faroe islands": "FO",
    "france": "FR",
    "gibraltar": "GI",
    "guernsey": "GK",
    "germany": "GM",
    "greece": "GR",
    "croatia": "HR",
    "hungary": "HU",
    "iceland": "IC",
    "isle of man": "IM",
    "italy": "IT",
    "jersey": "JE",
    "kosovo": "KV",
    "latvia": "LG",
    "lithuania": "LH",
    "slovak republic": "LO",
    "liechtenstein": "LS",
    "luxembourg": "LU",
    "moldova": "MD",
    "montenegro": "MJ",
    "macedonia": "MK",
    "monaco": "MN",
    "malta": "MT",
    "netherlands": "NL",
    "norway": "NO",
    "poland": "PL",
    "portugal": "PO",
    "serbia": "RI",
    "romania": "RO",
    "slovenia": "SI",
    "san marino": "SM",
    "spain": "SP",
    "svalbard": "SV",
    "sweden": "SW",
    "switzerland": "SZ",
    "united kingdom": "UK",
    "ukraine": "UP",
    "vatican city": "VT",
    # Nationality adjectives, which is how prose usually names a country:
    # "a Russian missile strike", "the Spanish government". Irregular enough to
    # be worth listing rather than deriving, and cheap: each one is a country
    # an event would otherwise lose. Restricted to the countries that can
    # actually change a Zone decision (Europe, plus the named GDELT set) --
    # everything else lands in World either way, so listing it buys nothing.
    "french": "FR",
    "spanish": "SP",
    "german": "GM",
    "british": "UK",
    "english": "UK",
    "scottish": "UK",
    "welsh": "UK",
    "italian": "IT",
    "ukrainian": "UP",
    "polish": "PL",
    "dutch": "NL",
    "belgian": "BE",
    "portuguese": "PO",
    "greek": "GR",
    "swedish": "SW",
    "norwegian": "NO",
    "danish": "DA",
    "finnish": "FI",
    "swiss": "SZ",
    "austrian": "AU",
    "irish": "EI",
    "romanian": "RO",
    "hungarian": "HU",
    "bulgarian": "BU",
    "croatian": "HR",
    "serbian": "RI",
    "albanian": "AL",
    "czech": "EZ",
    "slovak": "LO",
    "slovenian": "SI",
    "lithuanian": "LH",
    "latvian": "LG",
    "estonian": "EN",
    "icelandic": "IC",
    "cypriot": "CY",
    "maltese": "MT",
    "moldovan": "MD",
    "belarusian": "BO",
    # Aliases and short forms seen in chronicle prose.
    "uk": "UK",
    "britain": "UK",
    "great britain": "UK",
    "england": "UK",
    "scotland": "UK",
    "wales": "UK",
    "northern ireland": "UK",
    "czechia": "EZ",
    "slovakia": "LO",
    "holland": "NL",
    "the netherlands": "NL",
    "vatican": "VT",
    "holy see": "VT",
    "north macedonia": "MK",
    "bosnia and herzegovina": "BK",
    "united states": "US",
    "usa": "US",
    "america": "US",
    "japan": "JA",
    "china": "CH",
    "india": "IN",
    "brazil": "BR",
}


def country_slugs_in_english_text(text: str) -> list[str]:
    """Every recognized country named anywhere in English prose, longest first.

    Complements reading wikilinks: a chronicle entry often names a country only
    inside a larger linked title -- "Israel Defense Forces", "Prime Minister of
    the United Kingdom" -- so the link target resolves to nothing while the
    country is plainly there in the sentence.

    Matched longest-name-first on word boundaries, because a shorter name can
    sit inside a longer one ("Guinea" within "Papua New Guinea", "Ireland"
    within "Northern Ireland") and the longer match is the right one. Once a
    span is consumed it is not reconsidered.
    """
    haystack = text.casefold()
    found: list[str] = []
    consumed: list[tuple[int, int]] = []
    for name in sorted(_FIPS_BY_ENGLISH_NAME, key=len, reverse=True):
        start = 0
        while True:
            at = haystack.find(name, start)
            if at < 0:
                break
            start = at + 1
            end = at + len(name)
            # Word boundaries, so "chinatown" is not China and "malia" not Mali.
            before_ok = at == 0 or not (haystack[at - 1].isalnum() or haystack[at - 1] == "-")
            after_ok = end == len(haystack) or not (haystack[end].isalnum() or haystack[end] == "-")
            if not (before_ok and after_ok):
                continue
            if any(cs <= at and end <= ce for cs, ce in consumed):
                continue
            consumed.append((at, end))
            slug = country_slug_for_english_name(name)
            if slug is not None and slug not in found:
                found.append(slug)
    return found


def country_slug_for_english_name(name: str) -> str | None:
    """The `source_country`-style slug for an English country name, or None.

    None means "this is not a country name I recognize", which is the common
    case: the agenda's wikilinks are mostly people, organisations and places
    ("Andy Burnham", "Ministry of defence", "Kharkiv Oblast"). Callers filter on
    it rather than treating the miss as an error.
    """
    fips = _FIPS_BY_ENGLISH_NAME.get(name.strip().casefold())
    if fips is None:
        return None
    from pipeline.adapters.gdelt import zone_slug_for_fips

    return zone_slug_for_fips(fips)


def countries_in_continent(continent_slug: str) -> frozenset[str]:
    """Every ``source_country`` value that counts as part a continent.

    Matches both forms an Article's ``source_country`` can take (see
    ``pipeline.adapters.gdelt.zone_slug_for_fips``): a named slug when the
    adapter recognizes the country ("germany"), or the lowercased FIPS code
    when it does not ("it", "be"). Both are produced by the same cycle and
    both appear in a Cluster's ``countries``, so both must resolve here or the
    continent silently loses whichever half it does not match.
    """
    if continent_slug != "europe":
        return frozenset()
    from pipeline.adapters.gdelt import ZONE_BY_FIPS

    named = {ZONE_BY_FIPS[code] for code in _EUROPE_FIPS if code in ZONE_BY_FIPS}
    raw = {code.lower() for code in _EUROPE_FIPS}
    return frozenset(named | raw)


# --- Source reliability ------------------------------------------------------

# Domains that republish other newsrooms' work rather than reporting. They are
# not fraudulent and not excluded -- they genuinely carry the story -- but three
# aggregators agreeing is one newsroom's reporting seen three times, and the
# Consensus Score exists to measure the opposite.
#
# Named from real published output: the 2026-08-20 World Briefing counted
# bignewsnetwork.com alongside lemonde.fr and theguardian.com at equal weight.
# Deliberately a short, evidenced list rather than a heuristic -- "looks like an
# aggregator" is not something a domain name reveals.
_REPUBLISHER_DOMAINS: frozenset[str] = frozenset(
    {
        "bignewsnetwork.com",
        "zazoom.it",
        "iheart.com",
        "drimble.nl",
        "menafn.com",
        "newsbreak.com",
        "msn.com",
        "news.yahoo.com",
        "flipboard.com",
        "smartnews.com",
    }
)

TIER_REFERENCE = 3
TIER_ORDINARY = 2
TIER_REPUBLISHER = 1


def source_trust_tier(domain: str) -> int:
    """How much one outlet's coverage is worth as corroboration.

    Three tiers, kept coarse on purpose. A finer scale would be a ranking of
    newsrooms this project has no basis to publish, whereas these three
    distinctions rest on facts about the source's role: it is a newsroom we
    deliberately subscribe to, it is some other outlet, or it republishes.

    The reference tier is DERIVED from the RSS adapter's own feed list rather
    than restated here, so adding a feed cannot silently leave its outlet
    scored as an unknown. That list is the one place a curated newsroom is
    declared.
    """
    normalized = domain.strip().lower()
    if normalized in _REPUBLISHER_DOMAINS:
        return TIER_REPUBLISHER

    from pipeline.adapters.rss import FEEDS

    if normalized in {feed.source for feed in FEEDS}:
        return TIER_REFERENCE
    return TIER_ORDINARY


# --- Ranking weights ---------------------------------------------------------

# How much each factor counts, per Period. Versioned, because changing a weight
# changes what a reader sees and a Briefing must be explainable after the fact:
# the version is written onto every scored item alongside its components.
SCORE_WEIGHTS_VERSION = "2026-08-20.1"

# The spec's §7.1 opens with `0.28 x impact` -- people and territory affected,
# severity, economic or legal effect -- and it is deliberately ABSENT here.
#
# Impact at that weight needs structured data this pipeline does not ingest:
# casualty counts, sums of money, populations under an order. The available
# substitute would be the chronicle's category, i.e. deciding that armed
# conflict outranks elections, which is an editorial hierarchy this project has
# no basis to publish and has already declined to invent once (see
# `rank_clusters`). A named gap beats a fabricated proxy: a weight labelled
# "impact" that actually measures "category we guessed matters" would be worse
# than not scoring impact at all, because it would look justified.
#
# So the spec's remaining six weights are renormalised to sum to 1, keeping
# their relative proportions, and impact stays on the deferred list.
#
# Freshness is the one factor the spec itself varies by Period ("très forte" for
# daily, "modérée" for weekly, §7.2), so the two profiles differ there and the
# rest is rebalanced around it. A weekly review is a record of the week, where
# an event's corroboration matters more than which day it landed on.
SCORE_WEIGHTS: Final[dict[str, dict[str, float]]] = {
    "day": {
        "freshness": 0.30,
        "prominence": 0.18,
        "corroboration": 0.18,
        "geographic_relevance": 0.12,
        "source_reliability": 0.12,
        "novelty": 0.10,
    },
    "week": {
        "freshness": 0.10,
        "prominence": 0.24,
        "corroboration": 0.24,
        "geographic_relevance": 0.16,
        "source_reliability": 0.16,
        "novelty": 0.10,
    },
}

# Weights that do not sum to 1 make a score incomparable between Periods, which
# is exactly the bug a reader would never see and an operator could never
# explain. Caught at import rather than as a puzzling ordering later.
for _period, _weights in SCORE_WEIGHTS.items():
    _total = sum(_weights.values())
    assert abs(_total - 1.0) < 1e-9, f"{_period} weights sum to {_total}, not 1"

__all__ = [
    "CROSS_DAY_SIMILARITY_FLOOR",
    "SCORE_WEIGHTS",
    "SCORE_WEIGHTS_VERSION",
    "MAX_PER_CATEGORY",
    "MAX_PER_COUNTRY",
    "MAX_SELECTED_CLUSTERS",
    "MIN_COUNTRIES",
    "MIN_INDEPENDENT_SOURCES",
    "MIN_QUALIFYING_FOR_ZONE",
    "REWRITE_SIMILARITY_FLOOR",
    "OUTPUT_LANGUAGES",
    "TIER_ORDINARY",
    "TIER_REFERENCE",
    "TIER_REPUBLISHER",
    "countries_in_continent",
    "source_trust_tier",
    "country_slug_for_english_name",
    "country_slugs_in_english_text",
    "PERIODS",
    "STAGE_NAMES",
    "ZONES",
    "briefing_combinations",
    "continent_for",
    "zone_by_slug",
]
