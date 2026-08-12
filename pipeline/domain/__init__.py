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
class ArticleRecord:
    """An Article as it lives on disk, one per JSON Line.

    Flat rather than nested so the intermediate files stay greppable and
    diffable by hand during the Build Order's inspection window. Every adapter
    produces this shape whatever its upstream returns, which is what keeps the
    vendor response shape inside ``pipeline.adapters`` (AD-13).

    ``collected_by`` names the adapter, so a human reading the output can tell
    GDELT's coverage from RSS's without running anything.
    """

    title: str
    url: str
    published_at: datetime
    source: str
    source_country: str
    language: str
    collected_by: str
    # The Article's recognized wire-service attribution, if any (Story 2.3,
    # FR-10 layer 2). None is the default and by far the common case — GDELT
    # exposes no such field at all, and most RSS feeds either don't populate
    # it or attribute to a human byline rather than an agency. Absence is not
    # a failure; it means dedupe treats the Article as independent.
    wire_agency: str | None = None

    def __post_init__(self) -> None:
        if self.published_at.tzinfo is None:
            raise ValueError(
                "published_at must be timezone-aware; a naive timestamp would be "
                "read as local time downstream and could shift an Article into "
                "the wrong Period"
            )

    def to_dict(self) -> dict[str, str]:
        data = {
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at.isoformat(),
            "source": self.source,
            "source_country": self.source_country,
            "language": self.language,
            "collected_by": self.collected_by,
        }
        # Omitted rather than written as a literal null when absent, so the
        # common case's on-disk bytes are unchanged from before this field
        # existed — the inspection window's diffs stay readable (AC4).
        if self.wire_agency is not None:
            data["wire_agency"] = self.wire_agency
        return data

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> ArticleRecord:
        return cls(
            title=data["title"],
            url=data["url"],
            published_at=datetime.fromisoformat(data["published_at"]),
            source=data["source"],
            source_country=data["source_country"],
            language=data["language"],
            collected_by=data["collected_by"],
            wire_agency=data.get("wire_agency"),
        )


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


# --- The on-disk shape of a published Briefing --------------------------


_BRIEFING_RECORD_SCHEMA_VERSION = 1


def _zone_from_dict(data: dict[str, str | None]) -> Zone:
    return Zone(slug=data["slug"], kind=ZoneKind(data["kind"]), continent=data["continent"])


@dataclass(frozen=True, slots=True)
class BriefingRecord:
    """A published Briefing exactly as it lives on disk, one JSON file per
    (Output Language, Zone, Period) combination at
    ``data/briefings/<lang>/<zone>/<period>.json`` (architecture spine,
    Consistency Conventions).

    Deliberately distinct from ``Briefing``: this pipeline's stages
    (dedupe, cluster, rank, summarize) have never materialized
    ``QualifyingCluster``/``Cluster``/``Event``/``Article`` — every stage
    operates on plain dicts end to end. ``clusters`` here is that same dict
    shape (whatever ``summarize``'s collected output already carries:
    ``cluster_id``, ``members``, ``summary``, ``outbound_url``, ``rank``,
    etc.), not a forced conversion into the richer domain objects
    ``Briefing`` names — building that conversion layer would be new
    complexity with no real consumer anywhere in the codebase.

    ``schema_version`` exists because the architecture spine requires this
    shape to be versioned: "A schema change is a version bump, never a
    silent field edit." ``publish`` (Story 3.5) and the site (Epic 4) both
    read against this one definition, so neither can drift from the other.
    """

    zone: Zone
    period: Period
    language: OutputLanguage
    clusters: tuple[dict, ...]
    generated_at: datetime
    served_zone: Zone | None = None
    # FR-8 (Discarded Volume: "how many Articles were ingested and how many
    # were kept") is explicitly Epic 4's display responsibility, not Epic
    # 3's -- these fields exist so the shape is ready for whichever future
    # story computes real per-Zone-per-Period ingested/kept counts. Story
    # 3.5's `publish.assemble_briefings` does not populate them (no stage
    # yet computes a per-Zone-per-Period ingested/kept count to pass
    # through); they default to 0, which must not be read as "nothing was
    # filtered" until a future story wires real values through.
    discarded_ingested: int = 0
    discarded_kept: int = 0

    def __post_init__(self) -> None:
        if self.served_zone is None:
            # FR-16's fallback is the exception, not the rule — every
            # ordinary Briefing's served_zone equals what was requested,
            # and requiring every caller to repeat the Zone twice for the
            # common case would be pure ceremony.
            object.__setattr__(self, "served_zone", self.zone)

    def to_dict(self) -> dict:
        return {
            "schema_version": _BRIEFING_RECORD_SCHEMA_VERSION,
            "zone": self.zone.slug,
            "zone_kind": self.zone.kind.value,
            "zone_continent": self.zone.continent,
            "served_zone": self.served_zone.slug,
            "served_zone_kind": self.served_zone.kind.value,
            "served_zone_continent": self.served_zone.continent,
            "period": self.period.value,
            "language": self.language.value,
            "clusters": list(self.clusters),
            "discarded_ingested": self.discarded_ingested,
            "discarded_kept": self.discarded_kept,
            "generated_at": self.generated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> BriefingRecord:
        return cls(
            zone=_zone_from_dict(
                {
                    "slug": data["zone"],
                    "kind": data["zone_kind"],
                    "continent": data["zone_continent"],
                }
            ),
            served_zone=_zone_from_dict(
                {
                    "slug": data["served_zone"],
                    "kind": data["served_zone_kind"],
                    "continent": data["served_zone_continent"],
                }
            ),
            period=Period(data["period"]),
            language=OutputLanguage(data["language"]),
            clusters=tuple(data["clusters"]),
            discarded_ingested=data.get("discarded_ingested", 0),
            discarded_kept=data.get("discarded_kept", 0),
            generated_at=datetime.fromisoformat(data["generated_at"]),
        )


__all__ = [
    "Article",
    "ArticleRecord",
    "Briefing",
    "BriefingRecord",
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
