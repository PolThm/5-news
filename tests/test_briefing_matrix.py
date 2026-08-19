"""Tests for the briefing_matrix mechanism: per-Period Cluster pools and the
4-Zone ranking loop that produces them, plus the deduplicated Cluster union
summarize is submitted against.

Story 3.5 wires ``rank.py``'s ``rank_for_zone``/``link_across_days`` — both
already unit-tested in isolation — into a real per-cycle loop for the first
time. This module's own tests stay one level up from those: given a set of
qualifying Clusters (or history entries), does the loop visit every Zone,
does day/week diverge correctly, and does the union dedupe correctly.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pipeline.config import PERIODS, ZONES
from pipeline.domain import Period
from pipeline.stages.briefing_matrix import build_period_pools, dedupe_union, rank_all_zones


def _cluster(cluster_id: str, sources: int, countries: list[str]) -> dict:
    """A Cluster shaped the way `pipeline.stages.cluster` really writes one.

    One member per Independent Source, because that is what the count means --
    `coverage_for_cluster` sets it to `len(groups)` and `members` is those same
    groups. A fixture with a single member and a count of three would let a
    test pass while asserting something the real output cannot satisfy (see
    test_every_pooled_cluster_can_substantiate_its_own_consensus_score).
    """
    return {
        "cluster_id": cluster_id,
        "members": [
            {
                "title": f"title {i} for {cluster_id}",
                "url": f"https://example.com/{cluster_id}/{i}",
                "source": f"outlet{i}.example",
                "source_country": countries[i % len(countries)],
                "language": "en",
            }
            for i in range(sources)
        ],
        "independent_source_count": sources,
        "country_count": len(countries),
        "countries": sorted(countries),
        "mentioned_countries": sorted(countries),
        "origin_country": countries[0],
    }


def _history_entry(cluster_id: str, cycle_id: str, sources: int, countries: list[str]) -> dict:
    return {
        "cycle_id": cycle_id,
        "cluster_id": cluster_id,
        "independent_source_count": sources,
        "country_count": len(countries),
        "countries": sorted(countries),
        "origin_country": countries[0],
    }


# --- build_period_pools --------------------------------------------------


def test_day_pool_is_todays_clusters_unchanged() -> None:
    today = [_cluster("a", sources=2, countries=["france", "germany"])]

    pools = build_period_pools(
        today_clusters=today,
        history_entries=[],
        embedding_by_id={"a": [1.0, 0.0]},
    )

    assert pools[Period.DAY] == today


def test_day_pool_is_unaffected_by_history_entries() -> None:
    """rank.py's own docstring: link_across_days is 'never called for the
    day Period' -- proven here by observing the day pool is exactly
    today's Clusters even when history entries close enough to link exist."""
    today = [_cluster("a", sources=2, countries=["france", "germany"])]
    history = [
        _history_entry("h1", "2026-08-11T06-00-00Z", sources=2, countries=["france", "germany"])
    ]

    pools = build_period_pools(
        today_clusters=today,
        history_entries=history,
        embedding_by_id={"a": [1.0, 0.0], "h1": [1.0, 0.0]},
    )

    assert pools[Period.DAY] == today


def test_week_pool_links_recent_history_but_not_entries_past_its_window() -> None:
    today = [_cluster("today1", sources=2, countries=["france", "germany"])]
    history = [
        _history_entry("recent", "2026-08-10T06-00-00Z", sources=2, countries=["france", "spain"]),
        _history_entry("old", "2026-07-01T06-00-00Z", sources=2, countries=["france", "spain"]),
    ]
    embeddings = {
        "today1": [1.0, 0.0],
        "recent": [0.99, 0.02],
        "old": [0.99, 0.02],
    }

    pools = build_period_pools(
        today_clusters=today,
        history_entries=history,
        embedding_by_id=embeddings,
        reference_date=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
    )

    week_ids = {cid for c in pools[Period.WEEK] for cid in c.get("_linked_ids", [c["cluster_id"]])}
    assert "recent" in week_ids
    assert "old" not in week_ids


def test_both_periods_are_always_present() -> None:
    pools = build_period_pools(today_clusters=[], history_entries=[], embedding_by_id={})

    assert set(pools.keys()) == set(PERIODS)


def test_a_cluster_missing_from_embedding_by_id_degrades_to_unlinked_not_a_crash() -> None:
    """An upstream embedding failure (Cohere outage) leaves cluster.py's own
    output degraded but present -- such a Cluster has no entry in
    embedding_by_id at all. link_across_days requires every today_cluster it
    receives to have one; passing it through unlinked (present in every
    Period's pool, just never merged with history) must not crash the whole
    ranking matrix over one degraded Cluster (AD-10)."""
    today = [
        _cluster("embeddable", sources=2, countries=["france", "germany"]),
        _cluster("no-embedding", sources=2, countries=["japan", "china"]),
    ]

    pools = build_period_pools(
        today_clusters=today,
        history_entries=[],
        embedding_by_id={"embeddable": [1.0, 0.0]},  # "no-embedding" absent on purpose
    )

    for period in PERIODS:
        ids = {cid for c in pools[period] for cid in c.get("_linked_ids", [c["cluster_id"]])}
        assert "no-embedding" in ids
        assert "embeddable" in ids


# --- rank_all_zones --------------------------------------------------------


def test_rank_all_zones_produces_one_ranking_per_zone() -> None:
    clusters = [_cluster("a", sources=3, countries=["france", "germany"])]

    rankings = rank_all_zones(clusters)

    assert len(rankings) == len(ZONES)
    assert {r.requested_zone.slug for r in rankings} == {z.slug for z in ZONES}


def test_rank_all_zones_world_includes_every_qualifying_cluster() -> None:
    clusters = [
        _cluster("a", sources=3, countries=["france", "germany"]),
        _cluster("b", sources=2, countries=["japan", "china"]),
    ]

    rankings = rank_all_zones(clusters)
    world = next(r for r in rankings if r.requested_zone.slug == "world")

    assert {c["cluster_id"] for c in world.ranked_clusters} == {"a", "b"}


# --- dedupe_union -----------------------------------------------------------


def test_dedupe_union_collapses_a_cluster_selected_into_multiple_zones() -> None:
    clusters = [_cluster("shared", sources=3, countries=["france", "germany"])]
    rankings = rank_all_zones(clusters)

    union = dedupe_union(rankings)

    ids = [c["cluster_id"] for c in union]
    assert ids.count("shared") == 1, "a Cluster selected by more than one Zone must appear once"


def test_dedupe_union_covers_every_distinct_cluster_id_across_all_zones() -> None:
    clusters = [
        _cluster("fr-only", sources=2, countries=["france", "germany"]),
        _cluster("jp-only", sources=2, countries=["japan", "china"]),
    ]
    rankings = rank_all_zones(clusters)

    union = dedupe_union(rankings)

    assert {c["cluster_id"] for c in union} == {"fr-only", "jp-only"}


def test_dedupe_union_of_no_rankings_is_empty() -> None:
    assert dedupe_union([]) == []


def test_dedupe_union_keeps_the_first_seen_occurrence_across_periods() -> None:
    """Documents a known, deliberately accepted approximation: a Cluster
    that differs in shape between an unlinked (day) occurrence and a
    linked (week, via link_across_days) occurrence is deduplicated
    by first-seen order, not by any Period-aware merge -- see
    dedupe_union's own docstring for why this trade-off was accepted."""
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import ZoneRanking

    day_occurrence = {"cluster_id": "x", "independent_source_count": 2}
    week_occurrence = {"cluster_id": "x", "independent_source_count": 5, "_linked_ids": ["x", "y"]}

    day_ranking = ZoneRanking(
        requested_zone=zone_by_slug("world"),
        served_zone=zone_by_slug("world"),
        ranked_clusters=[day_occurrence],
    )
    week_ranking = ZoneRanking(
        requested_zone=zone_by_slug("world"),
        served_zone=zone_by_slug("world"),
        ranked_clusters=[week_occurrence],
    )

    union_day_first = dedupe_union([day_ranking, week_ranking])
    assert union_day_first == [day_occurrence]

    union_week_first = dedupe_union([week_ranking, day_ranking])
    assert union_week_first == [week_occurrence]


def test_every_pooled_cluster_can_substantiate_its_own_consensus_score() -> None:
    """AC3's hard guarantee, enforced where the numbers are produced.

    The chip shows `independent_source_count` and the disclosure lists
    `members`; the product's whole claim is that the reader can open the second
    to check the first. There is an e2e test named for this guarantee, but it
    builds against committed fixtures, so it cannot see what a real cycle
    produces -- and a real cycle produced "7 sources · 3 countries" above a
    one-line source list on 2026-08-19, because cross-day linking aggregated
    counts from history entries whose Articles nothing stores.

    Asserted over both pools, on the merged output rather than on the inputs,
    so any future aggregation that reintroduces an unshowable number fails
    here rather than in production.
    """
    today = [
        _cluster("a", sources=2, countries=["france", "spain"]),
        _cluster("b", sources=3, countries=["germany", "it", "france"]),
    ]
    history = [
        _history_entry("a", "2026-08-10T06-00-00Z", sources=9, countries=["nl", "be", "pl"]),
        _history_entry("far", "2026-08-10T06-00-00Z", sources=7, countries=["up"]),
    ]
    embeddings = {
        "a": [1.0, 0.0],
        "b": [0.0, 1.0],
        "far": [0.7, 0.7],
    }

    pools = build_period_pools(
        today_clusters=today,
        history_entries=history,
        embedding_by_id=embeddings,
        reference_date=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
    )

    for period, pool in pools.items():
        for cluster in pool:
            listed = len(cluster["members"])
            claimed = cluster["independent_source_count"]
            assert listed == claimed, (
                f"{period} pool: cluster {cluster['cluster_id']} claims {claimed} "
                f"Independent Sources but can only list {listed}"
            )
            assert cluster["country_count"] == len(cluster["countries"])
