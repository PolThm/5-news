"""Rank stage: the product's central judgment, and the only one made without
AI.

Every prior stage decides what a story *is* — one dispatch, one Event across
languages. This stage decides which Events are worth showing, and in what
order, using nothing but the integer counts dedupe and cluster already
computed. No model call, no randomness, no wall-clock read (AD-4): the same
input must produce the same five headlines every time, or the product's claim
to be a measurement rather than an opinion falls apart.

FR-6 makes one explicit, non-obvious choice: Independent Source count leads,
country count only breaks ties. A Cluster covered by 10 sources from 2
countries outranks one covered by 3 sources from 4 countries, even though the
second looks like it has "wider" reach. This was decided against the wider-
reach-first alternative during PRD creation and is binding — do not
reintroduce a weighted or country-first scheme here.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from pipeline.config import (
    CROSS_DAY_SIMILARITY_FLOOR,
    MAX_PER_COUNTRY,
    MAX_SELECTED_CLUSTERS,
    MIN_COUNTRIES,
    MIN_INDEPENDENT_SOURCES,
    MIN_QUALIFYING_FOR_ZONE,
    ZONES,
    continent_for,
)
from pipeline.domain import Zone, ZoneKind
from pipeline.stages import (
    DEFAULT_DATA_ROOT,
    clique_partition,
    cycle_id_for,
    output_dir_for,
    read_jsonl,
    stage_arg_parser,
    write_atomically,
    write_jsonl,
)

STAGE = "rank"


def qualifies(cluster: dict) -> bool:
    """PRD Glossary, Qualifying Cluster: at least 2 Independent Sources from
    at least 2 distinct countries. Both floors are independent and both must
    hold — 5 sources all from one country still fails."""
    return (
        cluster["independent_source_count"] >= MIN_INDEPENDENT_SOURCES
        and cluster["country_count"] >= MIN_COUNTRIES
    )


def rank_clusters(clusters: list[dict]) -> list[dict]:
    """Order Clusters by Consensus Score: Independent Source count descending,
    then country count descending, then ``cluster_id`` ascending as a stable,
    content-derived tiebreak.

    A single ``sorted()`` call with a tuple key is the whole mechanism — no
    library heuristic, no multi-pass logic, nothing that could hide
    non-determinism the way Story 2.1's HDBSCAN detour did. Negating the two
    count fields yields descending order for both while keeping the
    tiebreak's natural ascending order, all in one pass.
    """
    return sorted(
        clusters,
        key=lambda c: (-c["independent_source_count"], -c["country_count"], c["cluster_id"]),
    )


def link_across_days(
    today_clusters: list[dict],
    history_entries: list[dict],
    embedding_by_id: dict[str, list[float]],
) -> list[dict]:
    """FR-18 (Story 2.7): merge today's Clusters with historical entries
    describing the same ongoing Event, for week/month Period ranking only.

    **Never called for the day Period** — that window is a single ingest
    day by definition (AC3); this function is only ever reached from
    week/month orchestration.

    Reuses ``pipeline.stages.clique_partition``, the same mechanism Story
    2.3's agency matching and Story 2.4's rewrite detection already settled
    on, for the same reason: a coarse similarity signal chains transitively
    unless every pair in a merged group is required to directly qualify, not
    just adjacent ones. See ``clique_partition``'s docstring for the concrete
    bug this discipline prevents.

    ``embedding_by_id`` maps every item's ``cluster_id`` (today's and
    history's) to its representative title's embedding vector — passed in
    rather than computed here, so this function has no adapter dependency of
    its own and is trivial to test without a network.

    Independent Source counts are unioned across linked days, not summed —
    matching ``pipeline.stages.cluster``'s own ``coverage_for_cluster``
    arithmetic one level up: two days both covering an ongoing Event via the
    same underlying source-country pairing should not double-count. Since
    this function receives only the aggregate counts each day already
    produced (not the underlying dedupe groups), the union is approximated
    over ``countries`` (a real set, unionable exactly) and the source count
    is taken as the maximum across linked days' *own* counts rather than a
    sum — a deliberately conservative choice: undercounting cross-day
    coverage costs a slightly low Consensus Score, overcounting would repeat
    this epic's most consequential class of bug at the layer with the least
    remaining context to catch it.
    """
    items = [*today_clusters, *history_entries]
    n = len(items)

    def eligible(_i: int) -> bool:
        return True

    def cosine_distance(i: int, j: int) -> float:
        a = embedding_by_id[items[i]["cluster_id"]]
        b = embedding_by_id[items[j]["cluster_id"]]
        if len(a) != len(b):
            # A vendor model upgrade between when a history row was embedded
            # and today's embedding call would leave mismatched dimensions in
            # embedding_by_id. Every other embedding boundary in this
            # pipeline (cluster.py, dedupe.py) degrades rather than crashes
            # on a malformed vector; treating a dimension mismatch as "not
            # the same Event" does the same here, at zero cost -- two items
            # that genuinely can't be compared simply don't link.
            return 1.0
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 1.0
        cosine_similarity = dot / (norm_a * norm_b)
        return 1.0 - cosine_similarity

    def directly_qualifies(i: int, j: int) -> bool:
        return cosine_distance(i, j) <= CROSS_DAY_SIMILARITY_FLOOR

    def similarity(i: int, j: int) -> float:
        return 1.0 - cosine_distance(i, j)

    cliques = clique_partition(n, eligible, directly_qualifies, similarity)

    linked: list[dict] = []
    for clique in cliques:
        members = [items[index] for index in clique]
        # Prefer a member that carries `members` (today's shape) as the
        # anchor over a history-only member (which never has that field) --
        # a clique with zero "today" members is a completely ordinary case
        # (an ongoing Event that goes uncovered for a day within a week/month
        # window), not an edge case, and the merged record must still carry
        # every field a Cluster's consumers expect.
        anchor = next((m for m in members if "members" in m), members[0])
        countries = sorted({c for member in members for c in member["countries"]})
        linked.append(
            {
                **anchor,
                "members": anchor.get("members", []),
                "independent_source_count": max(m["independent_source_count"] for m in members),
                "country_count": len(countries),
                "countries": countries,
                "_linked_ids": [m["cluster_id"] for m in members],
            }
        )

    return linked


def _is_relevant_to(cluster: dict, zone: Zone) -> bool:
    """Whether a Cluster's coverage touches a given Zone.

    Relevant to a Country means the Cluster's ``countries`` list includes
    that country's slug directly. Relevant to a Continent means relevant to
    any Country belonging to it — a Cluster with no member in that
    continent is not part of its Briefing regardless of how it ranks
    globally. Derived entirely from ``countries`` (Story 2.5's prerequisite
    addition to Cluster output); this is not a new signal, per that
    story's AC4.
    """
    if zone.kind == ZoneKind.WORLD:
        # Everything is relevant to World -- there is no filtering to do,
        # and no country's `continent` field ever equals "world", so the
        # Continent branch below would otherwise wrongly find zero matches.
        return True
    cluster_countries = set(cluster["countries"])
    if zone.kind == ZoneKind.COUNTRY:
        return zone.slug in cluster_countries
    # A Continent: relevant if any of its countries appears in the Cluster.
    continent_countries = {z.slug for z in ZONES if z.continent == zone.slug}
    return bool(cluster_countries & continent_countries)


@dataclass(frozen=True, slots=True)
class ZoneRanking:
    """The result of ranking Clusters for one Zone, with FR-16's Continent
    fallback already resolved.

    Mirrors ``pipeline.domain.Briefing``'s existing ``zone``/``served_zone``
    fields rather than inventing a parallel shape — those fields were
    anticipated in Story 1.1's domain design specifically for this purpose.
    """

    requested_zone: Zone
    served_zone: Zone
    ranked_clusters: list[dict]

    @property
    def substituted(self) -> bool:
        """FR-16: the substitution is never silent — this is the explicit,
        inspectable answer to "did a fallback occur", not left for a caller
        to infer by comparing the two Zones itself."""
        return self.served_zone != self.requested_zone


def rank_for_zone(clusters: list[dict], zone: Zone) -> ZoneRanking:
    """Rank Clusters relevant to ``zone``, falling back to its Continent
    (FR-16) if fewer than ``MIN_QUALIFYING_FOR_ZONE`` Clusters both qualify
    and are relevant.

    Deliberately does not read from or write to disk — this proves the
    ranking-with-fallback mechanism correct in isolation. Wiring it into a
    per-cycle loop that runs it for all 15 Zones and decides where that
    output lives is later Epic 3/4 work, once the summarize/publish stages
    exist to consume its shape (see Story 2.5's Dev Notes for why that
    orchestration is deliberately deferred).

    A Continent (or World) Zone never falls back further — there is nothing
    above it to substitute, regardless of how thin its own coverage is.
    """
    return _rank_for_zone(clusters, requested_zone=zone, serving_zone=zone, visited=frozenset())


def _rank_for_zone(
    clusters: list[dict],
    requested_zone: Zone,
    serving_zone: Zone,
    visited: frozenset[str],
) -> ZoneRanking:
    """Recursion helper: ``requested_zone`` stays fixed across fallback hops
    while ``serving_zone`` walks up the Continent chain, so the returned
    ``ZoneRanking`` always reports what the reader actually asked for
    alongside what was actually served — never just the final hop.

    ``visited`` guards against an infinite loop if ``ZONES`` ever grew a
    cycle (a Continent given a non-``None`` ``continent`` field, or a chain
    longer than two levels with a mistake in it). Nothing in ``pipeline.config``
    enforces that ``ZONES`` stays a strict two-level hierarchy, so this is a
    cheap defense against a config edit turning a fallback into a hang,
    not a scenario reachable with the data as it exists today.
    """
    if serving_zone.slug in visited:
        raise ValueError(
            f"Zone fallback cycle detected at {serving_zone.slug!r} "
            f"(path: {sorted(visited)!r}) — check pipeline.config.ZONES for a "
            "Zone whose continent chain loops back on itself."
        )

    relevant = [c for c in clusters if _is_relevant_to(c, serving_zone)]
    qualifying_relevant = [c for c in relevant if qualifies(c)]

    ordered = rank_clusters(qualifying_relevant)
    if serving_zone.kind == ZoneKind.CONTINENT:
        # FR-17: applied before the top-5 slice, not after -- capping after
        # would just shrink a Briefing that could have had 5 items down to
        # fewer, instead of backfilling with the next-ranked Cluster from an
        # under-represented country, which is what "the next-ranked Clusters
        # from other countries take the remaining places" describes.
        # Explicitly not applied to World (FR-17's own exemption) or a
        # Country Zone's own Briefing (the rule is stated as being about
        # Continent Briefings specifically).
        #
        # Applied BEFORE the fallback-floor check below, not after: an
        # adversarial review found (and reproduced) that checking the floor
        # against the pre-cap count let a Continent whose qualifying
        # Clusters were concentrated in one country pass the floor, then get
        # capped down below it with no re-check and nowhere further to fall
        # back to -- silently serving a thinner Briefing than the floor was
        # meant to guarantee. Evaluating the floor against the post-cap
        # count is what the floor is actually supposed to measure: can this
        # Zone genuinely fill a Briefing on its own, cap included.
        ordered = apply_anti_concentration_cap(ordered)

    parent = continent_for(serving_zone)
    if len(ordered) < MIN_QUALIFYING_FOR_ZONE and parent is not None:
        return _rank_for_zone(
            clusters,
            requested_zone=requested_zone,
            serving_zone=parent,
            visited=visited | {serving_zone.slug},
        )

    selected = ordered[:MAX_SELECTED_CLUSTERS]
    ranked_out = [
        {**cluster, "rank": position} for position, cluster in enumerate(selected, start=1)
    ]

    return ZoneRanking(
        requested_zone=requested_zone, served_zone=serving_zone, ranked_clusters=ranked_out
    )


def apply_anti_concentration_cap(ranked: list[dict]) -> list[dict]:
    """FR-17: at most ``MAX_PER_COUNTRY`` Clusters from the same
    ``origin_country`` survive, in rank order. Everything else's relative
    order is preserved; excess Clusters from an over-represented country are
    dropped in place, never reordering what's kept.

    Only ever removes Clusters that were already going to be included
    (FR-4's never-pad rule extends naturally here) — the caller applies the
    ``MAX_SELECTED_CLUSTERS`` top-N slice afterward, so a Cluster this
    function drops can be replaced by whatever the next-ranked, still-
    eligible Cluster is.
    """
    kept: list[dict] = []
    seen_per_country: dict[str, int] = {}
    for cluster in ranked:
        origin = cluster["origin_country"]
        count = seen_per_country.get(origin, 0)
        if count >= MAX_PER_COUNTRY:
            continue
        seen_per_country[origin] = count + 1
        kept.append(cluster)
    return kept


@dataclass(frozen=True, slots=True)
class WrittenRank:
    output_path: Path
    metadata_path: Path
    clusters_selected: int


def run_rank(
    input_path: Path,
    cycle_id: str,
    data_root: Path = DEFAULT_DATA_ROOT,
) -> WrittenRank:
    """Filter to Qualifying Clusters, rank them, and select at most
    ``MAX_SELECTED_CLUSTERS`` — never padded below that if fewer qualify
    (FR-4).
    """
    clusters = list(read_jsonl(input_path))
    destination = output_dir_for(STAGE, cycle_id, root=data_root)
    output_path = destination / "ranked.jsonl"
    metadata_path = destination / f"{STAGE}.json"

    qualifying = [c for c in clusters if qualifies(c)]
    ordered = rank_clusters(qualifying)
    selected = ordered[:MAX_SELECTED_CLUSTERS]

    ranked_out = [
        {**cluster, "rank": position} for position, cluster in enumerate(selected, start=1)
    ]
    write_jsonl(output_path, ranked_out)

    metadata = {
        "stage": STAGE,
        "cycle_id": cycle_id,
        "clusters_in": len(clusters),
        "clusters_qualifying": len(qualifying),
        "clusters_selected": len(selected),
        # Discarded Volume: everything considered minus everything selected —
        # a Cluster that never qualified and a Cluster that qualified but
        # ranked 6th or below are both discarded, for the same reason: the
        # reader never sees either one.
        "clusters_discarded": len(clusters) - len(selected),
    }
    write_atomically(
        metadata_path, json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )

    return WrittenRank(
        output_path=output_path,
        metadata_path=metadata_path,
        clusters_selected=len(selected),
    )


def main(argv: list[str] | None = None) -> int:
    args = stage_arg_parser(STAGE).parse_args(argv)

    if not args.input.is_file():
        print(f"input not found or not a file: {args.input}", file=sys.stderr)
        return 1

    cycle_id = args.cycle_id or cycle_id_for()
    written = run_rank(args.input, cycle_id=cycle_id, data_root=args.data_root)

    print(f"{STAGE}: {written.clusters_selected} selected -> {written.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
