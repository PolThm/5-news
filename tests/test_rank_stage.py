"""Tests for the rank stage: the product's central, AI-free judgment.

No library heuristics here (unlike Story 2.1's HDBSCAN detour) — ranking is a
plain Python sort on integer counts, so determinism is straightforward to get
right and to verify.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.stages import read_jsonl
from pipeline.stages.rank import run_rank


def _cluster(cluster_id: str, sources: int, countries: int) -> dict:
    return {
        "cluster_id": cluster_id,
        "member_titles": [f"title-{cluster_id}"],
        "independent_source_count": sources,
        "country_count": countries,
    }


def _write(tmp_path: Path, clusters: list[dict]) -> Path:
    path = tmp_path / "clusters.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in clusters) + "\n", encoding="utf-8")
    return path


# --- Qualifying floor ---------------------------------------------------------


def test_a_cluster_with_one_source_does_not_qualify(tmp_path: Path) -> None:
    input_path = _write(tmp_path, [_cluster("a", sources=1, countries=1)])
    written = run_rank(input_path, cycle_id="c1", data_root=tmp_path / "data")

    ranked = list(read_jsonl(written.output_path))
    assert ranked == []


def test_two_sources_but_one_country_does_not_qualify(tmp_path: Path) -> None:
    """Both floors are independent and both must hold — a Cluster can clear
    the source-count floor easily while still failing the country floor."""
    input_path = _write(tmp_path, [_cluster("a", sources=5, countries=1)])
    written = run_rank(input_path, cycle_id="c1", data_root=tmp_path / "data")

    ranked = list(read_jsonl(written.output_path))
    assert ranked == []


def test_two_sources_across_two_countries_qualifies(tmp_path: Path) -> None:
    input_path = _write(tmp_path, [_cluster("a", sources=2, countries=2)])
    written = run_rank(input_path, cycle_id="c1", data_root=tmp_path / "data")

    ranked = list(read_jsonl(written.output_path))
    assert len(ranked) == 1
    assert ranked[0]["cluster_id"] == "a"


# --- Ordering ------------------------------------------------------------------


def test_independent_source_count_leads_over_country_count() -> None:
    """FR-6's explicit, non-obvious choice: source count leads, country count
    only breaks ties. A 5-source/2-country Cluster outranks a 3-source/
    4-country one, even though the latter has wider geographic spread."""
    import pipeline.stages.rank as rank_module

    clusters = [
        _cluster("wide-spread", sources=3, countries=4),
        _cluster("more-sources", sources=5, countries=2),
    ]
    ranked = rank_module.rank_clusters(clusters)

    assert [c["cluster_id"] for c in ranked] == ["more-sources", "wide-spread"]


def test_country_count_breaks_ties_on_equal_source_count() -> None:
    import pipeline.stages.rank as rank_module

    clusters = [
        _cluster("fewer-countries", sources=3, countries=2),
        _cluster("more-countries", sources=3, countries=3),
    ]
    ranked = rank_module.rank_clusters(clusters)

    assert [c["cluster_id"] for c in ranked] == ["more-countries", "fewer-countries"]


def test_identical_counts_break_the_tie_on_cluster_id_ascending() -> None:
    import pipeline.stages.rank as rank_module

    clusters = [
        _cluster("zebra", sources=3, countries=2),
        _cluster("alpha", sources=3, countries=2),
    ]
    ranked = rank_module.rank_clusters(clusters)

    assert [c["cluster_id"] for c in ranked] == ["alpha", "zebra"]


def test_ordering_does_not_depend_on_input_order() -> None:
    import pipeline.stages.rank as rank_module

    forward = [
        _cluster("a", sources=5, countries=2),
        _cluster("b", sources=3, countries=2),
    ]
    reversed_input = list(reversed(forward))

    assert rank_module.rank_clusters(forward) == rank_module.rank_clusters(reversed_input)


# --- Selection cap and Discarded Volume ---------------------------------------


def test_more_than_five_qualifying_selects_only_the_top_five(tmp_path: Path) -> None:
    clusters = [_cluster(f"c{i}", sources=10 - i, countries=2) for i in range(7)]
    input_path = _write(tmp_path, clusters)
    written = run_rank(input_path, cycle_id="c1", data_root=tmp_path / "data")

    ranked = list(read_jsonl(written.output_path))
    assert len(ranked) == 5
    assert [c["cluster_id"] for c in ranked] == ["c0", "c1", "c2", "c3", "c4"]

    metadata = json.loads(written.metadata_path.read_text())
    assert metadata["clusters_in"] == 7
    assert metadata["clusters_qualifying"] == 7
    assert metadata["clusters_selected"] == 5
    assert metadata["clusters_discarded"] == 2


def test_fewer_than_five_qualifying_is_never_padded(tmp_path: Path) -> None:
    clusters = [_cluster(f"c{i}", sources=5, countries=2) for i in range(3)]
    input_path = _write(tmp_path, clusters)
    written = run_rank(input_path, cycle_id="c1", data_root=tmp_path / "data")

    ranked = list(read_jsonl(written.output_path))
    assert len(ranked) == 3

    metadata = json.loads(written.metadata_path.read_text())
    assert metadata["clusters_selected"] == 3
    assert metadata["clusters_discarded"] == 0


def test_zero_qualifying_selects_nothing_but_completes(tmp_path: Path) -> None:
    clusters = [_cluster("a", sources=1, countries=1)]
    input_path = _write(tmp_path, clusters)
    written = run_rank(input_path, cycle_id="c1", data_root=tmp_path / "data")

    ranked = list(read_jsonl(written.output_path))
    assert ranked == []

    metadata = json.loads(written.metadata_path.read_text())
    assert metadata["clusters_in"] == 1
    assert metadata["clusters_qualifying"] == 0
    assert metadata["clusters_selected"] == 0
    assert metadata["clusters_discarded"] == 1


def test_selected_clusters_carry_a_1_indexed_rank(tmp_path: Path) -> None:
    clusters = [
        _cluster("first", sources=10, countries=2),
        _cluster("second", sources=5, countries=2),
    ]
    input_path = _write(tmp_path, clusters)
    written = run_rank(input_path, cycle_id="c1", data_root=tmp_path / "data")

    ranked = list(read_jsonl(written.output_path))
    assert ranked[0]["rank"] == 1
    assert ranked[1]["rank"] == 2


def test_non_qualifying_and_unranked_qualifying_both_count_as_discarded(tmp_path: Path) -> None:
    """Discarded Volume, as this stage defines it, is clusters considered
    minus clusters selected — both a Cluster that never qualified and a
    Cluster that qualified but ranked 6th belong in that count."""
    clusters = [
        _cluster("unqualified", sources=1, countries=1),
        *[_cluster(f"q{i}", sources=10 - i, countries=2) for i in range(6)],
    ]
    input_path = _write(tmp_path, clusters)
    written = run_rank(input_path, cycle_id="c1", data_root=tmp_path / "data")

    metadata = json.loads(written.metadata_path.read_text())
    assert metadata["clusters_in"] == 7
    assert metadata["clusters_qualifying"] == 6
    assert metadata["clusters_selected"] == 5
    assert metadata["clusters_discarded"] == 2  # 1 unqualified + 1 unranked-6th


# --- Determinism ---------------------------------------------------------------


def test_rank_is_byte_identical_across_reruns(tmp_path: Path) -> None:
    clusters = [
        _cluster("a", sources=5, countries=2),
        _cluster("b", sources=3, countries=3),
        _cluster("c", sources=1, countries=1),
    ]
    input_path = _write(tmp_path, clusters)

    out1 = run_rank(input_path, cycle_id="c1", data_root=tmp_path / "d1")
    out2 = run_rank(input_path, cycle_id="c1", data_root=tmp_path / "d2")

    assert out1.output_path.read_bytes() == out2.output_path.read_bytes()


def test_rerunning_into_the_same_output_path_is_still_byte_identical(tmp_path: Path) -> None:
    """The more realistic production scenario: a cycle re-run overwrites its
    own previous output at the same path, rather than writing to a fresh
    directory. write_atomically's temp-file-then-rename must not interact
    badly with its own prior output."""
    clusters = [
        _cluster("a", sources=5, countries=2),
        _cluster("b", sources=3, countries=3),
    ]
    input_path = _write(tmp_path, clusters)
    data_root = tmp_path / "data"

    first = run_rank(input_path, cycle_id="c1", data_root=data_root)
    first_bytes = first.output_path.read_bytes()
    second = run_rank(input_path, cycle_id="c1", data_root=data_root)

    assert second.output_path == first.output_path
    assert second.output_path.read_bytes() == first_bytes


def test_empty_input(tmp_path: Path) -> None:
    input_path = _write(tmp_path, [])
    written = run_rank(input_path, cycle_id="c1", data_root=tmp_path / "data")

    ranked = list(read_jsonl(written.output_path))
    assert ranked == []

    metadata = json.loads(written.metadata_path.read_text())
    assert metadata["clusters_in"] == 0
    assert metadata["clusters_selected"] == 0


# --- Zone-scoped ranking with Continent fallback (Story 2.5) -----------------


def _zone_cluster(cluster_id: str, sources: int, countries: list[str]) -> dict:
    return {
        "cluster_id": cluster_id,
        "member_titles": [f"title-{cluster_id}"],
        "independent_source_count": sources,
        "country_count": len(countries),
        "countries": sorted(countries),
        # Arbitrary but deterministic and always a member of `countries` --
        # these Story 2.5 tests predate the anti-concentration cap (Story
        # 2.6) and don't care which one is "origin", only that the field
        # exists so the cap's lookup doesn't KeyError.
        "origin_country": sorted(countries)[0],
    }


def test_a_well_served_country_needs_no_fallback() -> None:
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import rank_for_zone

    clusters = [
        _zone_cluster("a", sources=3, countries=["france", "germany"]),
        _zone_cluster("b", sources=2, countries=["france", "japan"]),
    ]
    zone = zone_by_slug("france")

    result = rank_for_zone(clusters, zone)

    assert result.requested_zone == zone
    assert result.served_zone == zone
    assert result.substituted is False
    assert len(result.ranked_clusters) == 2


def test_a_thin_country_falls_back_to_its_continent() -> None:
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import rank_for_zone

    clusters = [
        # Only 1 Cluster relevant to France -- below the fallback floor.
        _zone_cluster("fr1", sources=3, countries=["france", "germany"]),
        # Not relevant to France, but relevant to Europe (france's continent).
        _zone_cluster("uk1", sources=2, countries=["united-kingdom", "germany"]),
        _zone_cluster("de1", sources=2, countries=["germany", "japan"]),
    ]
    zone = zone_by_slug("france")

    result = rank_for_zone(clusters, zone)

    assert result.requested_zone == zone
    assert result.served_zone == zone_by_slug("europe")
    assert result.substituted is True
    # All 3 clusters are relevant to Europe (each involves a European country).
    assert len(result.ranked_clusters) == 3


def test_a_continent_zone_never_falls_back_further() -> None:
    """A Continent has nowhere further to fall back to -- even a thin
    Continent must not attempt to substitute World, which the current
    scope of this story does not define a relevance rule for."""
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import rank_for_zone

    clusters = [_zone_cluster("a", sources=2, countries=["france", "germany"])]
    zone = zone_by_slug("europe")

    result = rank_for_zone(clusters, zone)

    assert result.served_zone == zone
    assert result.substituted is False


def test_relevance_is_derived_from_the_countries_list_not_a_new_signal() -> None:
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import _is_relevant_to

    france = zone_by_slug("france")
    europe = zone_by_slug("europe")
    japan = zone_by_slug("japan")
    asia = zone_by_slug("asia")

    cluster = _zone_cluster("a", sources=2, countries=["france", "germany"])

    assert _is_relevant_to(cluster, france) is True
    assert _is_relevant_to(cluster, europe) is True  # france's continent
    assert _is_relevant_to(cluster, japan) is False
    assert _is_relevant_to(cluster, asia) is False


def test_a_cluster_relevant_to_zero_of_the_target_countries_is_excluded() -> None:
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import rank_for_zone

    clusters = [
        _zone_cluster("relevant", sources=2, countries=["france", "germany"]),
        _zone_cluster("irrelevant", sources=5, countries=["japan", "china"]),
    ]
    zone = zone_by_slug("france")

    result = rank_for_zone(clusters, zone)

    ids = [c["cluster_id"] for c in result.ranked_clusters]
    assert "irrelevant" not in ids


def test_world_zone_is_relevant_to_every_cluster() -> None:
    """World has no country/continent filtering at all (PRD FR-16 area) --
    verified explicitly since _is_relevant_to's Continent-branch logic
    would otherwise wrongly find zero matches for World (no country's
    `continent` field ever equals "world")."""
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import _is_relevant_to

    world = zone_by_slug("world")
    cluster = _zone_cluster("a", sources=2, countries=["japan", "brazil"])

    assert _is_relevant_to(cluster, world) is True


def test_world_zone_never_falls_back(monkeypatch) -> None:
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import rank_for_zone

    clusters = [_zone_cluster("a", sources=1, countries=["france"])]  # not even qualifying
    world = zone_by_slug("world")

    result = rank_for_zone(clusters, world)

    assert result.served_zone == world
    assert result.substituted is False


def test_a_continent_with_too_few_qualifying_clusters_still_serves_itself() -> None:
    """A Continent has nowhere further to fall back to (World is not a
    fallback target per this story's scope) -- even a Continent below the
    MIN_QUALIFYING_FOR_ZONE floor must still serve its own thin result
    rather than crash or recurse further."""
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import rank_for_zone

    clusters = [_zone_cluster("only-one", sources=2, countries=["france", "germany"])]
    europe = zone_by_slug("europe")

    result = rank_for_zone(clusters, europe)

    assert result.served_zone == europe
    assert result.substituted is False
    assert len(result.ranked_clusters) == 1


def test_a_cluster_spanning_two_continents_is_relevant_to_both() -> None:
    """A Cluster covering countries in two different continents counts as
    relevant to each independently -- the relevance rule is per-continent
    membership, not exclusive assignment to one continent."""
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import _is_relevant_to

    cluster = _zone_cluster("a", sources=2, countries=["france", "japan"])

    assert _is_relevant_to(cluster, zone_by_slug("europe")) is True
    assert _is_relevant_to(cluster, zone_by_slug("asia")) is True
    assert _is_relevant_to(cluster, zone_by_slug("north-america")) is False


def test_fallback_still_respects_the_five_item_cap() -> None:
    """The MAX_SELECTED_CLUSTERS cap applies at the zone that ends up
    actually serving the request, not the originally requested one --
    verified with a Continent fallback yielding more than 5 candidates."""
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import rank_for_zone

    clusters = [
        # Below the zone floor alone (only 1 qualifying-relevant cluster
        # touches france), so this forces a fallback to europe.
        _zone_cluster("fr-thin", sources=2, countries=["france", "germany"]),
        # 6 candidates NOT touching france directly, spread across the other
        # 2 configured European countries (at most 2 per country, so the
        # per-country cap never triggers) -- only relevant once serving_zone
        # widens to europe, exercising the plain 5-item cap post-fallback.
        *[
            _origin_cluster(
                f"eu{i}",
                sources=10 - i,
                origin=["germany", "united-kingdom"][i % 2],
                countries=["germany", "united-kingdom"],
            )
            for i in range(6)
        ],
    ]
    zone = zone_by_slug("france")

    result = rank_for_zone(clusters, zone)

    assert result.served_zone == zone_by_slug("europe")
    assert len(result.ranked_clusters) == 5


def test_real_cluster_output_is_consumable_by_rank_for_zone(tmp_path) -> None:
    """Integration check: the countries field pipeline.stages.cluster.py
    actually writes to disk round-trips correctly through
    read_jsonl -> rank_for_zone, not just through hand-built test dicts."""
    import json

    from pipeline.adapters.cohere_embed import EmbeddingResult
    from pipeline.config import zone_by_slug
    from pipeline.stages import read_jsonl
    from pipeline.stages.cluster import run_cluster
    from pipeline.stages.rank import rank_for_zone

    groups = [
        {
            "title": "Ceasefire agreed",
            "url": "https://a.com/x",
            "published_at": "2026-08-11T06:00:00+00:00",
            "source": "a.com",
            "source_country": "france",
            "language": "en",
            "collected_by": "gdelt",
            "normalized_title": "ceasefire agreed",
            "independent_source_count": 1,
            "country_count": 1,
            "sources": ["a.com"],
            "countries": ["france"],
            "article_count": 1,
        },
        {
            "title": "Truce declared",
            "url": "https://b.com/x",
            "published_at": "2026-08-11T06:05:00+00:00",
            "source": "b.com",
            "source_country": "germany",
            "language": "en",
            "collected_by": "gdelt",
            "normalized_title": "truce declared",
            "independent_source_count": 1,
            "country_count": 1,
            "sources": ["b.com"],
            "countries": ["germany"],
            "article_count": 1,
        },
    ]
    input_path = tmp_path / "groups.jsonl"
    input_path.write_text("\n".join(json.dumps(g) for g in groups) + "\n", encoding="utf-8")

    def embed(titles: list[str]) -> EmbeddingResult:
        # Close enough to merge into one cross-language-style Cluster.
        vectors = {"Ceasefire agreed": [1.0, 0.0], "Truce declared": [0.99, 0.02]}
        return EmbeddingResult(vectors=[vectors[t] for t in titles])

    written = run_cluster(input_path, cycle_id="c1", data_root=tmp_path / "data", embed=embed)
    clusters_on_disk = list(read_jsonl(written.output_path))

    result = rank_for_zone(clusters_on_disk, zone_by_slug("france"))

    # The merged cluster spans france+germany (country_count=2, qualifies)
    # and is relevant to france, but it is the only qualifying-relevant
    # cluster for france -- below MIN_QUALIFYING_FOR_ZONE (2), so this
    # correctly falls back to europe rather than serving france directly.
    assert result.served_zone == zone_by_slug("europe")
    assert result.substituted is True
    assert len(result.ranked_clusters) == 1
    assert result.ranked_clusters[0]["country_count"] == 2


# --- Anti-concentration cap (Story 2.6) --------------------------------------


def _origin_cluster(cluster_id: str, sources: int, origin: str, countries: list[str]) -> dict:
    return {
        "cluster_id": cluster_id,
        "member_titles": [f"title-{cluster_id}"],
        "independent_source_count": sources,
        "country_count": len(countries),
        "countries": sorted(countries),
        "origin_country": origin,
    }


def test_apply_anti_concentration_cap_keeps_at_most_two_per_country() -> None:
    from pipeline.stages.rank import apply_anti_concentration_cap

    ranked = [
        _origin_cluster("fr1", sources=10, origin="france", countries=["france", "germany"]),
        _origin_cluster("fr2", sources=9, origin="france", countries=["france", "germany"]),
        _origin_cluster("fr3", sources=8, origin="france", countries=["france", "germany"]),
        _origin_cluster("de1", sources=7, origin="germany", countries=["germany", "france"]),
    ]

    capped = apply_anti_concentration_cap(ranked)

    ids = [c["cluster_id"] for c in capped]
    assert ids == ["fr1", "fr2", "de1"], "the 3rd-ranked French cluster is dropped, not fr1/fr2"


def test_anti_concentration_cap_preserves_relative_order() -> None:
    from pipeline.stages.rank import apply_anti_concentration_cap

    ranked = [
        _origin_cluster("a", sources=10, origin="japan", countries=["japan"]),
        _origin_cluster("b", sources=9, origin="france", countries=["france"]),
        _origin_cluster("c", sources=8, origin="japan", countries=["japan"]),
        _origin_cluster("d", sources=7, origin="brazil", countries=["brazil"]),
    ]

    capped = apply_anti_concentration_cap(ranked)

    assert [c["cluster_id"] for c in capped] == ["a", "b", "c", "d"]


def test_cap_only_removes_never_pads(monkeypatch=None) -> None:
    from pipeline.stages.rank import apply_anti_concentration_cap

    ranked = [
        _origin_cluster("fr1", sources=10, origin="france", countries=["france"]),
        _origin_cluster("fr2", sources=9, origin="france", countries=["france"]),
        _origin_cluster("fr3", sources=8, origin="france", countries=["france"]),
    ]

    capped = apply_anti_concentration_cap(ranked)

    assert len(capped) == 2, "the excess is dropped, never backfilled with padding"


def test_continent_briefing_applies_the_cap_with_backfill() -> None:
    """AC1, end to end: an over-represented country's excess Cluster is
    dropped and a lower-ranked Cluster from another country fills the freed
    slot -- capping must happen before the top-5 slice, not after."""
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import rank_for_zone

    clusters = [
        _origin_cluster(f"fr{i}", sources=10 - i, origin="france", countries=["france", "spain"])
        for i in range(3)
    ] + [_origin_cluster("de1", sources=2, origin="germany", countries=["germany", "italy"])]

    result = rank_for_zone(clusters, zone_by_slug("europe"))

    ids = [c["cluster_id"] for c in result.ranked_clusters]
    assert "fr2" not in ids, "3rd-ranked France cluster excluded by the cap"
    assert "de1" in ids, "de1 backfills the slot the cap freed"
    assert len(ids) == 3


def test_cap_before_slice_backfills_from_beyond_the_top_five() -> None:
    """The real regression this ordering exists to prevent: with 5 ranked
    slots and MORE than 5 total candidates, capping AFTER the slice would
    never see the 6th-ranked cluster at all -- it would just be sliced away
    before the cap ever ran, leaving a 4-item Briefing when a 5th,
    lower-ranked-but-eligible cluster exists and should fill the freed slot.
    An adversarial review found the prior version of this test used only 4
    total candidates, so slicing before or after capping produced identical
    output -- it never actually exercised this ordering."""
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import rank_for_zone

    clusters = [
        # Ranks 1-4: France, an over-represented country that will hit the
        # cap after only 2 survive.
        *[
            _origin_cluster(
                f"fr{i}", sources=20 - i, origin="france", countries=["france", "spain"]
            )
            for i in range(4)
        ],
        # Rank 5: Germany.
        _origin_cluster("de1", sources=15, origin="germany", countries=["germany", "italy"]),
        # Rank 6: United Kingdom -- ranked below the top-5 slice, but must
        # backfill into the slot freed by capping fr2/fr3, since capping
        # runs before the slice. If the code sliced to 5 first and capped
        # after, this cluster would never be reachable at all. Uses a real
        # configured European country (only france/germany/united-kingdom
        # exist in ZONES) so it is genuinely relevant to europe, not
        # excluded by the relevance filter before the cap question even
        # arises.
        _origin_cluster(
            "uk1", sources=14, origin="united-kingdom", countries=["united-kingdom", "germany"]
        ),
    ]

    result = rank_for_zone(clusters, zone_by_slug("europe"))

    ids = [c["cluster_id"] for c in result.ranked_clusters]
    assert ids == ["fr0", "fr1", "de1", "uk1"], (
        "fr2/fr3 capped away; uk1 (rank 6) backfills a freed slot only "
        "reachable if the cap ran before the top-5 slice"
    )
    assert len(ids) <= 5


def test_world_zone_is_not_subject_to_the_cap() -> None:
    """AC2: the cap does not apply to World, per FR-17's explicit exemption."""
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import rank_for_zone

    clusters = [
        _origin_cluster(f"fr{i}", sources=10 - i, origin="france", countries=["france", "spain"])
        for i in range(4)
    ]

    result = rank_for_zone(clusters, zone_by_slug("world"))

    ids = [c["cluster_id"] for c in result.ranked_clusters]
    assert ids == ["fr0", "fr1", "fr2", "fr3"], "no cap applied -- all 4 France clusters included"


def test_country_zone_is_not_subject_to_the_cap() -> None:
    """The cap is stated as being about Continent Briefings; a Country
    Zone's own Briefing was never in its scope either."""
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import rank_for_zone

    clusters = [
        _origin_cluster(f"fr{i}", sources=10 - i, origin="france", countries=["france", "spain"])
        for i in range(4)
    ]

    result = rank_for_zone(clusters, zone_by_slug("france"))

    ids = [c["cluster_id"] for c in result.ranked_clusters]
    assert len(ids) == 4, "a Country Zone Briefing is not subject to the anti-concentration cap"


# --- Cross-day linking (Story 2.7, FR-18) -------------------------------------


def _today_cluster(cluster_id: str, sources: int, countries: list[str]) -> dict:
    return {
        "cluster_id": cluster_id,
        "member_titles": [f"title for {cluster_id}"],
        "independent_source_count": sources,
        "country_count": len(countries),
        "countries": sorted(countries),
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


def test_three_day_event_links_into_one_with_a_unioned_source_count() -> None:
    """AC1: an Event covered on three consecutive days appears once, with a
    Consensus Score aggregating all three days' Independent Sources -- not
    a naive sum, a union (matching cluster.py's own coverage_for_cluster
    arithmetic one level up)."""
    from pipeline.stages.rank import link_across_days

    today = [_today_cluster("today1", sources=2, countries=["france", "germany"])]
    history = [
        _history_entry("day1", "2026-08-09T06-00-00Z", sources=2, countries=["france", "spain"]),
        _history_entry("day2", "2026-08-10T06-00-00Z", sources=2, countries=["germany", "italy"]),
    ]
    embeddings = {
        "today1": [1.0, 0.0],
        "day1": [0.99, 0.02],
        "day2": [0.98, 0.03],
    }

    linked = link_across_days(today, history, embedding_by_id=embeddings)

    assert len(linked) == 1
    # Union of countries across all three days: france, germany (today) +
    # spain (day1) + italy (day2) -- but source count unions by Independent
    # Source identity, not naive summation; the test data has no shared
    # Source across days, so union count == 2+2+2 here is the union of three
    # *distinct* per-day dispatch sets, which is the correct arithmetic for
    # three genuinely different days' worth of reporting on the same Event.
    assert linked[0]["independent_source_count"] >= today[0]["independent_source_count"]
    assert set(linked[0]["countries"]) >= {"france", "germany", "spain", "italy"}


def test_month_window_links_across_more_than_two_days() -> None:
    """AC2: a month Briefing must not contain two items describing the same
    Event, exercised here with more than two linked days."""
    from pipeline.stages.rank import link_across_days

    today = [_today_cluster("today1", sources=2, countries=["france", "germany"])]
    history = [
        _history_entry("d1", "2026-08-01T06-00-00Z", sources=2, countries=["france", "japan"]),
        _history_entry("d2", "2026-08-05T06-00-00Z", sources=2, countries=["germany", "brazil"]),
        _history_entry("d3", "2026-08-09T06-00-00Z", sources=2, countries=["france", "china"]),
    ]
    embeddings = {
        "today1": [1.0, 0.0, 0.0],
        "d1": [0.99, 0.02, 0.0],
        "d2": [0.98, 0.03, 0.0],
        "d3": [0.97, 0.04, 0.0],
    }

    linked = link_across_days(today, history, embedding_by_id=embeddings)

    assert len(linked) == 1, "all four days' Clusters describe one Event and must merge into one"


def test_unrelated_history_entries_do_not_link() -> None:
    """The central risk this mechanism must avoid: an unrelated historical
    Cluster must not merge into today's just because it's in the window."""
    from pipeline.stages.rank import link_across_days

    today = [_today_cluster("today1", sources=2, countries=["france", "germany"])]
    history = [
        _history_entry(
            "unrelated", "2026-08-10T06-00-00Z", sources=3, countries=["japan", "china"]
        ),
    ]
    embeddings = {"today1": [1.0, 0.0], "unrelated": [0.0, 1.0]}

    linked = link_across_days(today, history, embedding_by_id=embeddings)

    assert len(linked) == 2, "an unrelated historical Cluster must remain separate"


def test_transitive_chaining_does_not_fold_a_non_clique_triple_together() -> None:
    """The same clique discipline this epic has now needed three times
    (Stories 2.1, 2.3, 2.4) — verified again for this mechanism's own,
    independent call site into clique_partition."""
    from pipeline.stages.rank import link_across_days

    today = [_today_cluster("today1", sources=2, countries=["france", "germany"])]
    history = [
        _history_entry("mid", "2026-08-10T06-00-00Z", sources=2, countries=["spain", "italy"]),
        _history_entry("far", "2026-08-09T06-00-00Z", sources=2, countries=["japan", "china"]),
    ]
    # today1-mid close, mid-far close, today1-far NOT close -- a non-clique
    # chain across three "days" (today plus two history entries).
    embeddings = {
        "today1": [1.0, 0.0, 0.0],
        "mid": [0.97, 0.24, 0.0],
        "far": [0.0, 0.0, 1.0],
    }

    linked = link_across_days(today, history, embedding_by_id=embeddings)

    assert not any({"today1", "mid", "far"} <= set(item["_linked_ids"]) for item in linked), (
        "all three must never fold into one group via transitive chaining"
    )


def test_no_history_within_window_leaves_todays_clusters_unchanged() -> None:
    from pipeline.stages.rank import link_across_days

    today = [_today_cluster("today1", sources=2, countries=["france", "germany"])]

    linked = link_across_days(today, [], embedding_by_id={"today1": [1.0, 0.0]})

    assert len(linked) == 1
    assert linked[0]["cluster_id"] == "today1"


def test_history_only_clique_still_carries_member_titles() -> None:
    """An adversarial review found that a clique with zero "today" members
    (a completely ordinary case -- an ongoing Event goes uncovered for a day
    within a week/month window) produced a merged record missing
    member_titles entirely, since history entries never carry that field."""
    from pipeline.stages.rank import link_across_days

    history = [
        _history_entry("d1", "2026-08-09T06-00-00Z", sources=2, countries=["france", "spain"]),
        _history_entry("d2", "2026-08-10T06-00-00Z", sources=2, countries=["germany", "italy"]),
    ]
    embeddings = {"d1": [1.0, 0.0], "d2": [0.99, 0.02]}

    linked = link_across_days([], history, embedding_by_id=embeddings)

    assert len(linked) == 1
    assert "member_titles" in linked[0]
    assert linked[0]["member_titles"] == []


def test_mismatched_embedding_dimensions_degrade_to_no_merge() -> None:
    """A vendor model upgrade between when a history row was embedded and
    today's embedding call could leave mismatched vector dimensions in
    embedding_by_id -- this must degrade (treat as unrelated), not crash,
    matching every other embedding boundary in this pipeline."""
    from pipeline.stages.rank import link_across_days

    today = [_today_cluster("today1", sources=2, countries=["france", "germany"])]
    history = [
        _history_entry("old", "2026-08-10T06-00-00Z", sources=2, countries=["spain", "italy"]),
    ]
    embeddings = {"today1": [1.0, 0.0, 0.0], "old": [1.0, 0.0]}  # different dimensionality

    linked = link_across_days(today, history, embedding_by_id=embeddings)

    assert len(linked) == 2, "mismatched dimensions must not crash or falsely merge"
