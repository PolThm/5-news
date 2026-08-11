"""Glossary types. The leaf of the dependency graph — imports nothing.

Every name here comes from the PRD Glossary and is binding across the codebase:
in type names, file names, and JSON keys. Using a synonym anywhere — Story,
Item, NewsItem, Topic where the Glossary says Cluster — is a defect.

Types only. No behavior beyond trivial derived properties, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

# --- Scalars and enums -------------------------------------------------------


class ZoneKind(StrEnum):
    """A Zone is exactly one of these."""

    WORLD = "world"
    CONTINENT = "continent"
    COUNTRY = "country"


class Period(StrEnum):
    """A time window for a Briefing."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class OutputLanguage(StrEnum):
    """The language a Briefing is generated in. v1 supports three."""

    FR = "fr"
    EN = "en"
    ES = "es"


# --- Sources and Articles ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Source:
    """A news outlet that publishes Articles."""

    name: str
    country: str
    language: str


@dataclass(frozen=True, slots=True)
class Article:
    """A single news item published by one Source."""

    title: str
    url: str
    published_at: datetime
    source: Source
    language: str


@dataclass(frozen=True, slots=True)
class IndependentSource:
    """A Source whose Article is not a republication of another Source's
    dispatch, as determined by Syndication Detection.

    Only Independent Sources count toward the Consensus Score.
    """

    source: Source
    article: Article


@dataclass(frozen=True, slots=True)
class WireCopy:
    """An Article republished from a news agency dispatch (AP, Reuters, AFP)
    rather than independently reported.

    Excluded from Independent Source counts. ``agency`` is the attributed
    agency where the Source exposes it; ``collapsed_into`` names the Article
    this one was folded into.
    """

    article: Article
    agency: str | None
    collapsed_into: str


class SyndicationDetection:
    """The pipeline stage that identifies Wire Copy and collapses
    republications so they count once.

    Implemented in Story 1.4 (near-duplicate title collapse), Story 2.3 (wire
    attribution metadata), and Story 2.4 (rewrite detection). This is the
    Glossary anchor; the behavior lives in ``pipeline.stages.dedupe``.
    """


# --- Events and Clusters -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Event:
    """A real-world occurrence that multiple Articles describe.

    Distinct from Cluster: a Cluster is the *set of Articles* grouped as
    describing one Event. Story 2.7 (FR-18) turns on recognizing the same
    Event across ingest days, which is why it needs a name of its own.
    """

    identity: str


@dataclass(frozen=True, slots=True)
class ConsensusScore:
    """The ranking measure of a Cluster: how many Independent Sources covered
    its Event, and across how many distinct countries.

    Both numbers are displayed to the reader (FR-7). Their combination into a
    single order is FR-6: Independent Source volume leads, country count
    breaks ties.
    """

    independent_sources: int
    countries: int


@dataclass(frozen=True, slots=True)
class Cluster:
    """The set of Articles grouped as describing the same Event.

    One Cluster represents one Event.
    """

    event: Event
    articles: tuple[Article, ...]
    independent_sources: tuple[IndependentSource, ...] = ()
    wire_copy: tuple[WireCopy, ...] = ()

    @property
    def consensus_score(self) -> ConsensusScore:
        countries = {s.source.country for s in self.independent_sources}
        return ConsensusScore(
            independent_sources=len(self.independent_sources),
            countries=len(countries),
        )


@dataclass(frozen=True, slots=True)
class QualifyingCluster:
    """A Cluster that has met the Qualifying Cluster floor.

    Clusters below the floor are never displayed and never counted toward item
    totals — they belong to Discarded Volume instead.

    This type carries no validation of its own: it is a marker applied by
    whichever stage owns the floor check (``pipeline.stages.rank``, Story 2.2),
    which is also the only place threshold constants may be read from
    ``pipeline.config`` — ``domain`` is the leaf of the dependency graph and
    may not import ``config``. Do not construct one directly except from that
    stage's qualification check.
    """

    cluster: Cluster

    @property
    def consensus_score(self) -> ConsensusScore:
        return self.cluster.consensus_score


# --- Zones and Briefings -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Zone:
    """A geographic scope for a Briefing: World, a Continent, or a Country.

    ``continent`` is set only for countries, and is what FR-16 falls back to
    when a Country has too few Qualifying Clusters (Story 2.5).
    """

    slug: str
    kind: ZoneKind
    continent: str | None = None


@dataclass(frozen=True, slots=True)
class Summary:
    """The AI-generated text for one Cluster within a Briefing, written in the
    Output Language.

    A trailer, not a substitute: it exists to make the reader want the
    original (FR-14).
    """

    text: str
    language: OutputLanguage


@dataclass(frozen=True, slots=True)
class DiscardedVolume:
    """Articles ingested for a Briefing minus those in its published Clusters.

    Displayed as the ratio that makes the filtering visible (FR-8).
    """

    ingested: int
    kept: int

    @property
    def discarded(self) -> int:
        return self.ingested - self.kept


@dataclass(frozen=True, slots=True)
class Briefing:
    """The ordered list of 2 to 5 Clusters for one Zone x Period x Output
    Language combination, with their Summaries.

    The unit that is precomputed, cached, and served. ``served_zone`` differs
    from ``zone`` when FR-16's Continent fallback applied, and the difference
    is never silent — the page states it.
    """

    zone: Zone
    period: Period
    language: OutputLanguage
    clusters: tuple[QualifyingCluster, ...] = ()
    summaries: dict[str, Summary] = field(default_factory=dict)
    discarded_volume: DiscardedVolume | None = None
    generated_at: datetime | None = None
    served_zone: Zone | None = None


__all__ = [
    "Article",
    "Briefing",
    "Cluster",
    "ConsensusScore",
    "DiscardedVolume",
    "Event",
    "IndependentSource",
    "OutputLanguage",
    "Period",
    "QualifyingCluster",
    "Source",
    "Summary",
    "SyndicationDetection",
    "WireCopy",
    "Zone",
    "ZoneKind",
]
