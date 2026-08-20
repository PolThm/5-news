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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.neighbors import radius_neighbors_graph

from pipeline.config import (
    CROSS_DAY_SIMILARITY_FLOOR,
    MAX_PER_CATEGORY,
    MAX_PER_COUNTRY,
    MAX_SELECTED_CLUSTERS,
    MIN_COUNTRIES,
    MIN_INDEPENDENT_SOURCES,
    MIN_QUALIFYING_FOR_ZONE,
    continent_for,
    countries_in_continent,
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
    """Whether an item may be published.

    Two independent routes, because there are two independent kinds of evidence
    that a story matters.

    **Editorial judgment.** An item carrying `agenda_category` came from the
    editorial chronicle: a human editor decided the event belonged in the
    record of a day, and filed it under a category. That is a stronger claim
    about importance than any count of reruns, so it qualifies on its own. It
    was measured: of 105 chronicle events, only 16 had any coverage at all in a
    10,000-article corpus, and the consensus floor alone admitted 4 items --
    dropping wars, elections and diplomacy while keeping road accidents,
    because accidents get syndicated and diplomacy gets reported once.

    **Corroborated consensus.** Otherwise the original floor stands (PRD
    Glossary, Qualifying Cluster): at least 2 Independent Sources from at least
    2 distinct countries, both independent and both required -- 5 sources all
    from one country still fails. This is what keeps an item that nothing
    vouched for out of a Briefing when no editor vouched for it either.

    The Consensus Score is unaffected either way: it still reports exactly what
    the item's own source list can show, which for an uncorroborated editorial
    item is zero, and the reader is sent to the source the chronicle cited.
    """
    if cluster.get("agenda_category"):
        return True
    return (
        cluster["independent_source_count"] >= MIN_INDEPENDENT_SOURCES
        and cluster["country_count"] >= MIN_COUNTRIES
    )


def rank_clusters(clusters: list[dict]) -> list[dict]:
    """Order items: most recent editorial day first, then Consensus Score.

    Recency leads because Consensus Score alone put the day the wrong way up
    once the editorial agenda started supplying candidates. An uncorroborated
    event has a score of zero, so sorting on score first buried today's war and
    diplomacy under a week-old road accident that happened to be syndicated --
    the same blindness that made the score a bad gate, showing up again as a
    bad order.

    Recency, deliberately, and not a ranking of the chronicle's categories.
    Deciding that "Armed conflicts and attacks" outranks "Politics and
    elections" would be this pipeline inventing an editorial hierarchy nobody
    asked it to hold; what day something happened is a fact. Items with no
    editorial day (Clusters ranked directly, when the agenda is unavailable)
    sort together and fall back to score alone, so that path is unchanged.

    Still a single ``sorted()`` call with a tuple key — no library heuristic,
    no multi-pass logic, nothing that could hide non-determinism the way Story
    2.1's HDBSCAN detour did. Negating the count fields yields descending order
    while keeping the tiebreak's natural ascending order, in one pass.
    """
    return sorted(
        clusters,
        key=lambda c: (
            # Descending by day: "" (no agenda day) sorts last under reverse
            # string comparison, which is why the whole tuple is negated-by-
            # convention rather than reversed wholesale.
            _descending_day(c.get("agenda_day") or ""),
            -c["independent_source_count"],
            -c["country_count"],
            c["cluster_id"],
        ),
    )


def _descending_day(day: str) -> str:
    """A sort key that puts later ISO dates first and undated items last.

    Inverting each digit turns ascending string order into descending date
    order without needing a separate reverse pass, and an empty day inverts to
    an empty string, which sorts *before* everything -- so it is replaced with a
    high sentinel to keep undated items at the end.
    """
    if not day:
        return "~"  # sorts after digits and hyphens in ASCII
    return "".join(chr(ord("9") - (ord(ch) - ord("0"))) if ch.isdigit() else ch for ch in day)


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

    # Vectors are grouped by width before any comparison. A vendor model
    # upgrade between when a history row was embedded and today's embedding
    # call would leave mismatched dimensions in embedding_by_id; every other
    # embedding boundary in this pipeline (cluster.py, dedupe.py) degrades
    # rather than crashes on a malformed vector, so two items that genuinely
    # cannot be compared simply never link -- which falls out of grouping by
    # width and only ever searching within a group.
    raw = [embedding_by_id[item["cluster_id"]] for item in items]
    indices_by_width: dict[int, list[int]] = {}
    for index, vector in enumerate(raw):
        indices_by_width.setdefault(len(vector), []).append(index)

    # The in-radius pairs, resolved by vectorized neighbor search per width
    # group rather than a cosine per pair.
    #
    # This used to compute each pair's cosine in interpreted Python --
    # `sum(x * y for x, y in zip(a, b))` plus two norms, so ~3x1024 float
    # operations per pair -- from a clique_partition call with
    # `eligible=lambda _i: True` and no candidate narrowing, i.e. across all
    # O(n^2) pairs, once for the week Period and again for the month. At the
    # retired RSS corpus's Cluster counts that was unnoticeable. At Story
    # 6.2's ~6,700-9,400 Clusters it is ~22 million pairs per Period and it
    # ran the cycle past its 30-minute job timeout with nothing published.
    #
    # sklearn's radius search is inclusive (`<= radius`), matching the
    # comparison it replaces, and `mode="connectivity"` keeps a genuinely
    # identical pair (distance exactly 0) inside its own neighbor set
    # instead of losing it to a structural zero.
    neighbors_of: list[set[int]] = [set() for _ in range(n)]
    for width, group_indices in indices_by_width.items():
        if width == 0 or len(group_indices) < 2:
            continue
        block = np.asarray([raw[index] for index in group_indices], dtype=float)
        norms = np.linalg.norm(block, axis=1)
        # A zero vector has no direction to compare, so it never links --
        # the same verdict the previous per-pair guard reached.
        usable = norms > 0
        if usable.sum() < 2:
            continue
        usable_indices = [index for index, ok in zip(group_indices, usable, strict=True) if ok]
        adjacency = (
            radius_neighbors_graph(
                block[usable],
                radius=CROSS_DAY_SIMILARITY_FLOOR,
                metric="cosine",
                mode="connectivity",
                include_self=False,
            )
            .tolil()
            .rows
        )
        for position, row in enumerate(adjacency):
            origin = usable_indices[position]
            neighbors_of[origin].update(usable_indices[neighbor] for neighbor in row)

    unit_by_index: dict[int, Any] = {}
    for width, group_indices in indices_by_width.items():
        if width == 0:
            continue
        for index in group_indices:
            vector = np.asarray(raw[index], dtype=float)
            norm = np.linalg.norm(vector)
            if norm > 0:
                unit_by_index[index] = vector / norm

    def directly_qualifies(i: int, j: int) -> bool:
        return j in neighbors_of[i]

    def similarity(i: int, j: int) -> float:
        # Cosine similarity on unit vectors is their dot product. Only ever
        # asked about pairs already known to be in radius, so both sides are
        # present in `unit_by_index`.
        return float(unit_by_index[i] @ unit_by_index[j])

    cliques = clique_partition(
        n, eligible, directly_qualifies, similarity, candidates_of=lambda i: neighbors_of[i]
    )

    linked: list[dict] = []
    for clique in cliques:
        members = [items[index] for index in clique]
        # A clique with no "today" member carries no Articles at all, and is
        # dropped rather than emitted.
        #
        # An earlier version anchored such a clique on a history entry and
        # emitted it with `"members": []`, reasoning that an ongoing Event
        # uncovered for a day is ordinary and the record should still carry
        # every field a Cluster's consumers expect. Carrying the fields is not
        # enough: a history entry stores only an embedding and its coverage
        # counts (see `pipeline.stages.history`), never titles or URLs. So the
        # Cluster reached summarize with nothing to read, Claude correctly
        # answered that no articles had been provided, and that answer shipped
        # as a headline -- "Aucun article disponible pour cet événement" was
        # published to six real week Briefings on 2026-08-19, one of them
        # claiming 7 independent sources across 3 countries. The Consensus
        # counts survive in history while the evidence for them does not, so
        # such an entry clears the 2-source floor while being unpublishable.
        #
        # A history entry's job is to enrich a Cluster it links to -- unioning
        # countries, carrying the max source count across days. It cannot be
        # one on its own, and the product's own promise ("lire l'article
        # original") is unkeepable without an Article behind it.
        anchor = next((m for m in members if m.get("members")), None)
        if anchor is None:
            continue
        # Coverage stays the anchor's -- today's Cluster -- rather than being
        # aggregated across the linked days.
        #
        # It used to take the max source count and the union of countries over
        # every linked item. Those numbers were unshowable: a history entry
        # stores counts but not the Articles behind them (see
        # `pipeline.stages.history`), so the Consensus chip announced a total
        # it could not list. Published week Briefings on 2026-08-19 read "7
        # sources · 3 countries" above a source list with one line in it --
        # and the suite has a test named for AC3's hard guarantee, that the
        # list holds exactly as many entries as the chip claims. It passes,
        # because it runs against fixtures rather than a real cycle.
        #
        # The whole product rests on that number being checkable: it is shown
        # to the reader as proof, and a proof that cannot be inspected is
        # worse than a smaller honest one. So cross-day linking keeps the job
        # only it can do -- collapsing one ongoing Event into a single item
        # instead of one per day it was covered -- and stops inflating a score
        # it cannot substantiate.
        linked.append(
            {
                **anchor,
                "members": anchor.get("members", []),
                # `sorted(set(...))`: an Event selected on several cycles has
                # one history row per cycle, all under the same cluster_id, so
                # this listed the same id up to four times.
                "_linked_ids": sorted({m["cluster_id"] for m in members}),
            }
        )

    return linked


def _is_relevant_to(cluster: dict, zone: Zone) -> bool:
    """Whether a Cluster belongs in a given Zone's Briefing.

    Decided on what the Event is *about* (``mentioned_countries``, from the
    places the Articles name), not on where the reporting outlets sit
    (``countries``, which stays the Consensus Score's evidence).

    Those two were the same field until 2026-08-19, and conflating them made
    "France Briefing" mean "what French newsrooms wrote about" rather than
    "what happened in France". The published week Briefing for France carried
    a cyclist hit by a bus in Stockholm, an American actress's death, and a
    SpaceX lunar crater -- every one of them a French outlet writing about
    somewhere else. The inverse was lost too: an American outlet covering a
    British debate never reached the United Kingdom.

    A Cluster whose Articles named no location at all is relevant only to
    World. That is ~20% of GKG rows, and it is the honest reading -- there is
    no evidence placing it anywhere. It still counts toward the Consensus
    Score of the Cluster it corroborates; it just cannot put it on a map.
    """
    if zone.kind == ZoneKind.WORLD:
        # Everything is relevant to World -- there is no filtering to do,
        # and no country's `continent` field ever equals "world", so the
        # Continent branch below would otherwise wrongly find zero matches.
        return True
    # `.get`, not `[...]`: Clusters written before this field existed, and
    # history-derived records, legitimately lack it. Absent means unplaceable,
    # which the World branch above has already allowed for.
    about = set(cluster.get("mentioned_countries") or ())
    if not about:
        return False
    if zone.kind == ZoneKind.COUNTRY:
        return zone.slug in about
    # A Continent: relevant if the Event is about any country in it.
    #
    # From the geography table, NOT from `{z.slug for z in ZONES if
    # z.continent == zone.slug}` as this once did. That derivation made a
    # continental Briefing mean "the Country Zones defined under this
    # continent" -- so Europe already excluded Italy and the Netherlands, and
    # the 2026-08-19 scope cut would have reduced it to France and Spain. A
    # country does not need a Zone of its own to have happened in Europe.
    return bool(about & countries_in_continent(zone.slug))


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

    # Every Zone, and before the fallback floor for the same reason the
    # per-country cap is: a floor measured on the pre-cap count would let a Zone
    # pass, then be capped below it with nowhere left to fall back to.
    ordered = apply_category_cap(ordered)

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


def _apply_cap(ranked: list[dict], key: Callable[[dict], str | None], limit: int) -> list[dict]:
    """Keep at most ``limit`` items sharing a ``key``, in rank order.

    Relative order of what survives is preserved, and excess items are dropped
    in place rather than reordering anything -- the caller applies the top-N
    slice afterwards, so a dropped item is replaced by the next eligible one.

    An item whose key is None is never capped: absent information must not be
    treated as a shared bucket, or every item missing a category would compete
    against every other one for the same two slots.
    """
    kept: list[dict] = []
    seen: dict[str, int] = {}
    for item in ranked:
        bucket = key(item)
        if bucket is None:
            kept.append(item)
            continue
        count = seen.get(bucket, 0)
        if count >= limit:
            continue
        seen[bucket] = count + 1
        kept.append(item)
    return kept


def apply_category_cap(ranked: list[dict]) -> list[dict]:
    """At most ``MAX_PER_CATEGORY`` items from one editorial category.

    Applied to every Zone, unlike the per-country cap, because the monotony it
    fixes was measured everywhere: on 2026-08-19 the World Briefing was four
    items out of five under "Disasters and accidents", and Spain's carried two
    separate earthquakes in Granada.

    The category is the chronicle's own taxonomy, so this needs no topic model.
    Items with no category -- Clusters ranked directly when the agenda is
    unavailable -- pass through untouched, leaving that fallback path exactly as
    it was.
    """
    return _apply_cap(ranked, lambda c: c.get("agenda_category") or None, MAX_PER_CATEGORY)


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
    return _apply_cap(ranked, lambda c: c["origin_country"], MAX_PER_COUNTRY)


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
