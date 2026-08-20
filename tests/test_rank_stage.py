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
        "members": [{"title": f"title-{cluster_id}", "url": f"https://example.com/{cluster_id}"}],
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


def _zone_cluster(
    cluster_id: str, sources: int, countries: list[str], about: list[str] | None = None
) -> dict:
    """A Cluster as `rank` sees it.

    `countries` is where the reporting outlets sit (the Consensus Score's
    evidence); `about` is what the Event is about (what places a Cluster in a
    Zone, since 2026-08-19). They default to the same value here because most
    of these tests predate the distinction and only care that placement works
    at all -- the tests that exercise the difference pass `about` explicitly.
    """
    located = sorted(countries if about is None else about)
    return {
        "cluster_id": cluster_id,
        "members": [{"title": f"title-{cluster_id}", "url": f"https://example.com/{cluster_id}"}],
        "independent_source_count": sources,
        "country_count": len(countries),
        "countries": sorted(countries),
        "mentioned_countries": located,
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
    spain = zone_by_slug("spain")

    cluster = _zone_cluster("a", sources=2, countries=["france", "germany"])

    assert _is_relevant_to(cluster, france) is True
    assert _is_relevant_to(cluster, europe) is True  # france's continent
    # Germany is in the corpus as a source country but is not a Zone, so it
    # contributes nothing to Zone relevance; Spain is a Zone the Cluster does
    # not touch.
    assert _is_relevant_to(cluster, spain) is False


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


def test_relevance_is_membership_not_exclusive_assignment() -> None:
    """A Cluster is relevant to every Zone it touches, independently -- being
    relevant to one Country does not assign it away from that Country's
    Continent, nor from World.

    This used to be proven with a Cluster spanning two Continents (france +
    japan -> europe and asia). The 2026-08-19 scope cut leaves one Continent,
    so the same rule is now shown across the levels of the hierarchy instead:
    a Cluster in France is relevant to France, to Europe, and to World at
    once, and not to the sibling Country it never touches."""
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import _is_relevant_to

    cluster = _zone_cluster("a", sources=2, countries=["france", "germany"])

    assert _is_relevant_to(cluster, zone_by_slug("france")) is True
    assert _is_relevant_to(cluster, zone_by_slug("europe")) is True
    assert _is_relevant_to(cluster, zone_by_slug("world")) is True
    assert _is_relevant_to(cluster, zone_by_slug("spain")) is False


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
            "mentioned_countries": ["france"],
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
        "members": [{"title": f"title-{cluster_id}", "url": f"https://example.com/{cluster_id}"}],
        "independent_source_count": sources,
        "country_count": len(countries),
        "countries": sorted(countries),
        # These cap tests are about concentration, not placement, so the Event
        # is about the same countries that report it -- enough for the Zone
        # filter to let them through and reach the cap under test.
        "mentioned_countries": sorted(countries),
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
    # Asserted as a SET, not a sequence: what this test is about is which
    # candidates survive capping, and the order among them is the scorer's
    # business (and changes with the weights, which are versioned). Pinning the
    # sequence here made this test fail on a weight change that did not affect
    # the backfill it exists to prove.
    assert set(ids) == {"fr0", "fr1", "de1", "uk1"}, (
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
        "members": [{"title": f"title for {cluster_id}", "url": "https://example.com/x"}],
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


def test_a_three_day_event_appears_once_with_a_score_it_can_substantiate() -> None:
    """AC1: an Event covered on three consecutive days appears once, not three
    times. Its Consensus Score stays the one it can show.

    This test previously asserted the opposite -- that the score aggregated
    across the linked days -- and that aggregate shipped: published week
    Briefings on 2026-08-19 read "7 sources · 3 countries" above a source list
    containing one line. A history entry stores coverage counts but not the
    Articles behind them, so a cross-day total is unlistable by construction.
    AC3's hard guarantee is that the list holds exactly as many entries as the
    chip claims, and the number is shown to the reader as proof -- an
    uninspectable proof is worse than a smaller honest one.

    So linking still collapses the days into one item, which is the job only
    it can do, and leaves the arithmetic alone.
    """
    from pipeline.stages.rank import link_across_days

    today = [_today_cluster("today1", sources=2, countries=["france", "germany"])]
    history = [
        _history_entry("day1", "2026-08-09T06-00-00Z", sources=5, countries=["france", "spain"]),
        _history_entry("day2", "2026-08-10T06-00-00Z", sources=9, countries=["germany", "italy"]),
    ]
    embeddings = {"today1": [1.0, 0.0], "day1": [0.99, 0.02], "day2": [0.98, 0.03]}

    linked = link_across_days(today, history, embedding_by_id=embeddings)

    # One item for the whole Event, not one per day.
    assert len(linked) == 1
    assert set(linked[0]["_linked_ids"]) == {"today1", "day1", "day2"}

    # And a score matching what the source list can actually show.
    assert linked[0]["independent_source_count"] == 2
    assert linked[0]["country_count"] == 2
    assert set(linked[0]["countries"]) == {"france", "germany"}
    assert len(linked[0]["members"]) == len(today[0]["members"])


def test_linked_ids_never_repeat_the_same_cluster() -> None:
    """An Event selected on several cycles has one history row per cycle, all
    carrying the same cluster_id, so the raw list held that id up to four
    times in real output."""
    from pipeline.stages.rank import link_across_days

    today = [_today_cluster("t", sources=2, countries=["france"])]
    history = [
        _history_entry("same", f"2026-08-1{d}T06-00-00Z", sources=2, countries=["france"])
        for d in range(1, 5)
    ]
    embeddings = {"t": [1.0, 0.0], "same": [0.999, 0.01]}

    linked = link_across_days(today, history, embedding_by_id=embeddings)

    ids = linked[0]["_linked_ids"]
    assert len(ids) == len(set(ids)), f"duplicate ids in {ids}"


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

    # Asserted on the linkage, not on a count: the unrelated history entry
    # carries no Articles, so it is dropped rather than emitted as an item of
    # its own (see test_a_clique_with_no_articles_is_dropped_not_published).
    # What matters here is that it was not absorbed into today's Cluster.
    assert len(linked) == 1
    assert linked[0]["_linked_ids"] == ["today1"], "an unrelated entry must not merge in"


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


def test_a_clique_with_no_articles_is_dropped_not_published() -> None:
    """A clique formed only from history entries must not become a Briefing
    item.

    This test used to assert the opposite -- that such a clique was emitted
    with `"members": []` -- on the reasoning that an ongoing Event uncovered
    for a day is ordinary and the record should still carry every field a
    Cluster's consumers expect. That was wrong, and it shipped: a history
    entry stores only an embedding and its coverage counts, never titles or
    URLs, so the Cluster reached summarize with nothing to read and Claude's
    honest "no articles were provided" answer was published as a headline to
    six real week Briefings on 2026-08-19. One claimed 7 independent sources
    across 3 countries, because history preserves the counts while discarding
    the evidence behind them -- so the entry cleared the 2-source floor while
    being impossible to write or to link.

    A history entry enriches a Cluster it links to. It cannot be one alone.
    """
    from pipeline.stages.rank import link_across_days

    history = [
        _history_entry("d1", "2026-08-09T06-00-00Z", sources=7, countries=["france", "spain"]),
        _history_entry("d2", "2026-08-10T06-00-00Z", sources=2, countries=["germany", "italy"]),
    ]
    embeddings = {"d1": [1.0, 0.0], "d2": [0.99, 0.02]}

    assert link_across_days([], history, embedding_by_id=embeddings) == []


def test_a_history_entry_that_links_to_today_collapses_into_it() -> None:
    """Dropping article-less cliques must not cost history its actual purpose:
    an entry that does link to one of today's Clusters still folds into it, so
    the Event appears once rather than once per day it was covered."""
    from pipeline.stages.rank import link_across_days

    today = [_zone_cluster("t1", sources=2, countries=["france"])]
    history = [
        _history_entry("d1", "2026-08-10T06-00-00Z", sources=5, countries=["spain", "germany"]),
    ]
    embeddings = {"t1": [1.0, 0.0], "d1": [0.999, 0.01]}

    linked = link_across_days(today, history, embedding_by_id=embeddings)

    assert len(linked) == 1
    assert linked[0]["members"], "the surviving anchor must be today's, with its Articles"
    assert set(linked[0]["_linked_ids"]) == {"t1", "d1"}
    # The history entry's own counts are NOT absorbed: they describe Articles
    # nothing can list, and the chip must not claim what it cannot show.
    assert linked[0]["independent_source_count"] == 2
    assert set(linked[0]["countries"]) == {"france"}


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

    # Two items that cannot be compared must not merge. The article-less
    # history entry is then dropped on its own account, so today's Cluster is
    # what survives -- unmerged, which is the property under test.
    assert len(linked) == 1
    assert linked[0]["_linked_ids"] == ["today1"], "mismatched dimensions must not merge"


# --- Placement is about the Event, not about the newsroom --------------------


def test_a_zone_is_decided_by_what_happened_not_by_who_reported_it() -> None:
    """The fix for the published week Briefings of 2026-08-19.

    France's carried a cyclist hit by a bus in Stockholm, an American
    actress's death, and a SpaceX lunar crater -- each a French outlet writing
    about somewhere else, admitted because placement read `countries` (where
    the outlets sit) instead of what the Event was about.
    """
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import _is_relevant_to

    # French newsrooms, Swedish story: not France's Briefing, but still
    # Europe's, because Sweden is in Europe.
    stockholm = _zone_cluster("s", sources=3, countries=["france"], about=["sw"])
    assert _is_relevant_to(stockholm, zone_by_slug("france")) is False
    assert _is_relevant_to(stockholm, zone_by_slug("europe")) is True
    assert _is_relevant_to(stockholm, zone_by_slug("world")) is True

    # French newsrooms, American story: neither France's nor Europe's.
    spacex = _zone_cluster("x", sources=3, countries=["france"], about=["united-states"])
    assert _is_relevant_to(spacex, zone_by_slug("france")) is False
    assert _is_relevant_to(spacex, zone_by_slug("europe")) is False
    assert _is_relevant_to(spacex, zone_by_slug("world")) is True

    # The inverse, which the old rule lost entirely: an American outlet
    # covering a French story belongs in France's Briefing.
    from_abroad = _zone_cluster("f", sources=3, countries=["united-states"], about=["france"])
    assert _is_relevant_to(from_abroad, zone_by_slug("france")) is True
    assert _is_relevant_to(from_abroad, zone_by_slug("europe")) is True


def test_an_unplaceable_cluster_reaches_world_only() -> None:
    """~20% of GKG rows name no location. Absent evidence is not evidence of
    absence, but it is not evidence of presence either -- such a Cluster can
    corroborate a Consensus Score anywhere and be placed nowhere."""
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import _is_relevant_to

    nowhere = _zone_cluster("n", sources=4, countries=["france", "spain"], about=[])

    assert _is_relevant_to(nowhere, zone_by_slug("world")) is True
    assert _is_relevant_to(nowhere, zone_by_slug("europe")) is False
    assert _is_relevant_to(nowhere, zone_by_slug("france")) is False


def test_a_cluster_written_before_this_field_existed_does_not_crash_rank() -> None:
    """Clusters on disk from earlier cycles have no `mentioned_countries`, and
    a cycle resuming across the change must degrade rather than KeyError --
    the same discipline every other schema addition here follows."""
    from pipeline.config import zone_by_slug
    from pipeline.stages.rank import _is_relevant_to

    legacy = {
        "cluster_id": "old",
        "members": [{"title": "t", "url": "https://a.com/x"}],
        "independent_source_count": 3,
        "country_count": 1,
        "countries": ["france"],
        "origin_country": "france",
    }

    assert _is_relevant_to(legacy, zone_by_slug("world")) is True
    assert _is_relevant_to(legacy, zone_by_slug("france")) is False


# --- Editorial judgment as a route to publication ----------------------------


def test_an_editorial_item_qualifies_without_corroboration() -> None:
    """The measurement that forced this: of 105 chronicle events, 16 had any
    coverage at all in a 10,000-article corpus, and the consensus floor alone
    admitted 4 items -- keeping syndicated road accidents while dropping wars,
    elections and diplomacy, because accidents get rerun and diplomacy gets
    reported once.

    A human editor deciding an event belongs in the record of a day is a
    stronger claim about importance than any count of reruns, so it stands on
    its own.
    """
    from pipeline.stages.rank import qualifies

    uncorroborated = {
        "cluster_id": "e1",
        "independent_source_count": 0,
        "country_count": 0,
        "agenda_category": "Armed conflicts and attacks",
    }
    assert qualifies(uncorroborated) is True


def test_a_cluster_with_no_editorial_backing_still_faces_the_consensus_floor() -> None:
    """The original gate is not removed, only bypassed for items an editor
    vouched for. An item nobody vouched for -- no editor, no second source --
    must still be kept out."""
    from pipeline.stages.rank import qualifies

    def cluster(sources: int, countries: int) -> dict:
        return {
            "cluster_id": "c",
            "independent_source_count": sources,
            "country_count": countries,
        }

    assert qualifies(cluster(1, 1)) is False
    assert qualifies(cluster(5, 1)) is False, "5 sources all in one country still fails"
    assert qualifies(cluster(2, 2)) is True


def test_todays_editorial_items_outrank_a_widely_syndicated_older_one() -> None:
    """Consensus Score alone put the day upside down once the agenda supplied
    candidates: an uncorroborated event scores zero, so today's war sorted below
    a week-old road accident that happened to be rerun everywhere."""
    from pipeline.stages.rank import rank_clusters

    ordered = rank_clusters(
        [
            {
                "cluster_id": "old-but-syndicated",
                "independent_source_count": 9,
                "country_count": 4,
                "agenda_day": "2026-08-13",
            },
            {
                "cluster_id": "today-uncorroborated",
                "independent_source_count": 0,
                "country_count": 0,
                "agenda_day": "2026-08-19",
            },
        ]
    )

    assert [c["cluster_id"] for c in ordered] == ["today-uncorroborated", "old-but-syndicated"]


def test_within_one_day_the_consensus_score_still_orders() -> None:
    """Recency decides between days, not within one -- a better-corroborated
    event from today still leads."""
    from pipeline.stages.rank import rank_clusters

    ordered = rank_clusters(
        [
            {
                "cluster_id": "thin",
                "independent_source_count": 0,
                "country_count": 0,
                "agenda_day": "2026-08-19",
            },
            {
                "cluster_id": "well-covered",
                "independent_source_count": 3,
                "country_count": 2,
                "agenda_day": "2026-08-19",
            },
        ]
    )

    assert [c["cluster_id"] for c in ordered] == ["well-covered", "thin"]


def test_items_with_no_editorial_day_sort_last_and_by_score_alone() -> None:
    """The fallback path -- Clusters ranked directly when the agenda is
    unavailable -- must be ordered exactly as it was before this change."""
    from pipeline.stages.rank import rank_clusters

    ordered = rank_clusters(
        [
            {"cluster_id": "b", "independent_source_count": 2, "country_count": 2},
            {"cluster_id": "a", "independent_source_count": 7, "country_count": 3},
            {
                "cluster_id": "dated",
                "independent_source_count": 0,
                "country_count": 0,
                "agenda_day": "2026-08-19",
            },
        ]
    )

    assert [c["cluster_id"] for c in ordered] == ["dated", "a", "b"]


# --- Editorial diversity -----------------------------------------------------


def test_a_briefing_is_not_five_variations_on_one_kind_of_news() -> None:
    """Measured on the real 2026-08-19 output: the World Briefing was four of
    five items under "Disasters and accidents", so a reader got a run of fatal
    accidents rather than a picture of the day."""
    from pipeline.stages.rank import apply_category_cap

    ranked = [
        {"cluster_id": f"d{i}", "agenda_category": "Disasters and accidents"} for i in range(4)
    ] + [
        {"cluster_id": "h", "agenda_category": "Health and environment"},
        {"cluster_id": "a", "agenda_category": "Armed conflicts and attacks"},
    ]

    kept = apply_category_cap(ranked)

    assert [c["cluster_id"] for c in kept] == ["d0", "d1", "h", "a"]
    assert len([c for c in kept if c["agenda_category"] == "Disasters and accidents"]) == 2


def test_the_cap_preserves_rank_order_and_drops_in_place() -> None:
    """Excess items are removed, never reordered: the caller slices the top N
    afterwards, so a dropped item is replaced by the next eligible one rather
    than shuffling what was already chosen."""
    from pipeline.stages.rank import apply_category_cap

    ranked = [
        {"cluster_id": "1", "agenda_category": "A"},
        {"cluster_id": "2", "agenda_category": "B"},
        {"cluster_id": "3", "agenda_category": "A"},
        {"cluster_id": "4", "agenda_category": "A"},
        {"cluster_id": "5", "agenda_category": "B"},
    ]

    assert [c["cluster_id"] for c in apply_category_cap(ranked)] == ["1", "2", "3", "5"]


def test_items_with_no_category_are_never_capped_together() -> None:
    """The fallback path -- Clusters ranked directly when the agenda is
    unavailable -- carries no category. Treating "absent" as a shared bucket
    would cap that whole path down to two items and silently gut it."""
    from pipeline.stages.rank import apply_category_cap

    legacy = [{"cluster_id": str(i), "origin_country": "france"} for i in range(5)]

    assert len(apply_category_cap(legacy)) == 5


def test_the_country_cap_still_behaves_exactly_as_before() -> None:
    """Both caps now share one helper; this pins the per-country behaviour that
    predates it so the refactor cannot have changed FR-17."""
    from pipeline.stages.rank import apply_anti_concentration_cap

    ranked = [
        {"cluster_id": "a", "origin_country": "france"},
        {"cluster_id": "b", "origin_country": "france"},
        {"cluster_id": "c", "origin_country": "france"},
        {"cluster_id": "d", "origin_country": "spain"},
    ]

    assert [c["cluster_id"] for c in apply_anti_concentration_cap(ranked)] == ["a", "b", "d"]


# --- Source reliability ------------------------------------------------------


def _member(source: str, country: str = "france") -> dict:
    return {
        "title": f"headline from {source}",
        "url": f"https://{source}/x",
        "source": source,
        "source_country": country,
        "language": "en",
    }


def test_newsrooms_outrank_republishers_at_equal_source_count() -> None:
    """The inflation this pipeline exists to remove, in its last hiding place.

    On 2026-08-20 the World Briefing scored bignewsnetwork.com equal to
    lemonde.fr, so three aggregators reprinting one dispatch outranked two
    newsrooms reporting independently -- three confirmations that are really one
    story seen three times.
    """
    from pipeline.stages.rank import rank_clusters

    ordered = rank_clusters(
        [
            {
                "cluster_id": "republished",
                "members": [
                    _member("bignewsnetwork.com"),
                    _member("iheart.com"),
                    _member("zazoom.it"),
                ],
                "independent_source_count": 3,
                "country_count": 3,
                "agenda_day": "2026-08-20",
            },
            {
                "cluster_id": "reported",
                "members": [_member("lemonde.fr"), _member("theguardian.com")],
                "independent_source_count": 2,
                "country_count": 2,
                "agenda_day": "2026-08-20",
            },
        ]
    )

    assert [c["cluster_id"] for c in ordered] == ["reported", "republished"]


def test_broader_coverage_still_wins_among_equally_trusted_sources() -> None:
    """Reliability reorders, it does not replace the count: two newsrooms still
    beat one."""
    from pipeline.stages.rank import rank_clusters

    ordered = rank_clusters(
        [
            {
                "cluster_id": "one-newsroom",
                "members": [_member("lemonde.fr")],
                "independent_source_count": 1,
                "country_count": 1,
                "agenda_day": "2026-08-20",
            },
            {
                "cluster_id": "two-newsrooms",
                "members": [_member("lemonde.fr"), _member("elpais.com", "spain")],
                "independent_source_count": 2,
                "country_count": 2,
                "agenda_day": "2026-08-20",
            },
        ]
    )

    assert [c["cluster_id"] for c in ordered] == ["two-newsrooms", "one-newsroom"]


def test_recency_still_leads_over_reliability() -> None:
    """Ordering stays hierarchical: today's news first, then how well sourced it
    is. A well-sourced item from last week must not displace today."""
    from pipeline.stages.rank import rank_clusters

    ordered = rank_clusters(
        [
            {
                "cluster_id": "old-and-well-sourced",
                "members": [_member("lemonde.fr"), _member("theguardian.com")],
                "independent_source_count": 2,
                "country_count": 2,
                "agenda_day": "2026-08-14",
            },
            {
                "cluster_id": "today-thin",
                "members": [],
                "independent_source_count": 0,
                "country_count": 0,
                "agenda_day": "2026-08-20",
            },
        ]
    )

    assert [c["cluster_id"] for c in ordered] == ["today-thin", "old-and-well-sourced"]


def test_the_reference_tier_is_derived_from_the_feed_list() -> None:
    """Adding a feed must not leave its outlet scored as an unknown. The RSS
    adapter's feed list is the single place a curated newsroom is declared, so
    the tier reads from it rather than restating it."""
    from pipeline.adapters.rss import FEEDS
    from pipeline.config import TIER_ORDINARY, TIER_REFERENCE, source_trust_tier

    for feed in FEEDS:
        assert source_trust_tier(feed.source) == TIER_REFERENCE, feed.source

    assert source_trust_tier("some-local-paper.example") == TIER_ORDINARY


# --- Explainable scoring -----------------------------------------------------


def _scored(**over) -> dict:
    base = {
        "cluster_id": "c",
        "members": [_member("lemonde.fr")],
        "independent_source_count": 1,
        "country_count": 1,
        "mentioned_countries": ["france"],
        "agenda_day": "2026-08-20",
        "_linked_ids": ["c"],
    }
    return {**base, **over}


def test_a_score_reports_every_component_that_produced_it() -> None:
    """§5.3 asks for a score an operator can explain -- "une équipe doit pouvoir
    expliquer pourquoi un sujet est n°2". A bare number cannot be argued with,
    so the components and the weights version travel with it."""
    from pipeline.config import SCORE_WEIGHTS, SCORE_WEIGHTS_VERSION, zone_by_slug
    from pipeline.domain import Period
    from pipeline.stages.rank import score_item

    score = score_item(_scored(), zone_by_slug("france"), Period.DAY, "2026-08-20")

    assert set(score["components"]) == set(SCORE_WEIGHTS["day"])
    assert score["weights_version"] == SCORE_WEIGHTS_VERSION
    assert 0.0 <= score["total"] <= 1.0


def test_freshness_decays_rather_than_falling_off_a_cliff() -> None:
    """A hard window would make the ordering jump at midnight, and an event from
    yesterday is not worthless."""
    from pipeline.config import zone_by_slug
    from pipeline.domain import Period
    from pipeline.stages.rank import score_item

    def freshness(day: str) -> float:
        item = _scored(agenda_day=day)
        return score_item(item, zone_by_slug("france"), Period.DAY, "2026-08-20")["components"][
            "freshness"
        ]

    assert freshness("2026-08-20") == 1.0
    assert 0.4 < freshness("2026-08-18") < 0.6, "two days ~= half"
    assert freshness("2026-08-14") < freshness("2026-08-18")
    # Undated items sit mid-scale: neither promoted nor buried on a dimension
    # nothing measured for them.
    assert (
        score_item(_scored(agenda_day=None), zone_by_slug("france"), Period.DAY, "2026-08-20")[
            "components"
        ]["freshness"]
        == 0.5
    )


def test_the_two_period_profiles_trade_freshness_against_coverage_differently() -> None:
    """The spec varies freshness by Period (§7.2): "très forte" daily, "modérée"
    weekly. That is only meaningful if it can change an ordering, so this pins a
    case that actually flips.

    Both items are inside the daily window -- since the day pool is now bounded
    to one day, a five-day-old item cannot appear there at all. The difference is
    a day of age against far wider coverage: a daily review leads with today, a
    weekly one with the better-covered event.

    2 outlets against 12 is the spread the real corpus shows (its published
    items run 0 to 12). A one-outlet gap no longer flips anything, which is the
    saturating curve behaving as intended -- the eleventh outlet moves the score
    much less than the third.

    Source counts differ while `members` are held identical, so the only factors
    in play are freshness and prominence; mixing in reliability would test three
    things at once and prove none.
    """
    from pipeline.config import zone_by_slug
    from pipeline.domain import Period
    from pipeline.stages.rank import rank_by_score

    members = [_member("lemonde.fr"), _member("elpais.com", "spain")]
    today_slightly_thinner = _scored(
        cluster_id="today", agenda_day="2026-08-20", independent_source_count=2, members=members
    )
    yesterday_better_covered = _scored(
        cluster_id="yesterday",
        agenda_day="2026-08-19",
        independent_source_count=12,
        members=members,
    )
    pool = [today_slightly_thinner, yesterday_better_covered]

    daily = rank_by_score(pool, zone_by_slug("france"), Period.DAY, "2026-08-20")
    weekly = rank_by_score(pool, zone_by_slug("france"), Period.WEEK, "2026-08-20")

    assert daily[0]["cluster_id"] == "today"
    assert weekly[0]["cluster_id"] == "yesterday"


def test_geographic_relevance_prefers_the_country_over_its_continent() -> None:
    """A European decision genuinely concerns France, just less than a French
    one does -- so it earns partial credit rather than none or full."""
    from pipeline.config import zone_by_slug
    from pipeline.domain import Period
    from pipeline.stages.rank import score_item

    def relevance(about: list[str], zone: str) -> float:
        return score_item(
            _scored(mentioned_countries=about), zone_by_slug(zone), Period.DAY, "2026-08-20"
        )["components"]["geographic_relevance"]

    assert relevance(["france"], "france") == 1.0
    assert relevance(["germany"], "france") == 0.5, "European, not French"
    assert relevance(["japan"], "france") == 0.0
    # World takes everything: ranking it by how narrowly local a story is would
    # invert what a World Briefing is for.
    assert relevance(["japan"], "world") == 1.0


def test_a_story_told_across_several_days_scores_less_novel() -> None:
    """The spec asks for "a significant development, rather than repetition of
    an old subject"; cross-day linking is where that is observable."""
    from pipeline.config import zone_by_slug
    from pipeline.domain import Period
    from pipeline.stages.rank import score_item

    def novelty(linked: list[str]) -> float:
        return score_item(
            _scored(_linked_ids=linked), zone_by_slug("france"), Period.DAY, "2026-08-20"
        )["components"]["novelty"]

    assert novelty(["c"]) == 1.0
    assert novelty(["c", "d"]) == 0.5
    assert novelty(["c", "d", "e", "f"]) == 0.25


def test_ordering_stays_deterministic_when_scores_tie() -> None:
    """Two items scoring identically must not swap between runs -- the cross-day
    tests and a resumed cycle both depend on a stable order."""
    from pipeline.config import zone_by_slug
    from pipeline.domain import Period
    from pipeline.stages.rank import rank_by_score

    items = [_scored(cluster_id="zzz"), _scored(cluster_id="aaa")]
    ordered = rank_by_score(items, zone_by_slug("france"), Period.DAY, "2026-08-20")

    assert [c["cluster_id"] for c in ordered] == ["aaa", "zzz"]
    assert ordered[0]["score"]["total"] == ordered[1]["score"]["total"]


def test_the_score_reads_how_many_reference_newsrooms_led_with_the_item() -> None:
    """The signal the score was missing when subjects first shipped, and the
    reason that Briefing was wrong: six factors, none of them the count of
    reference newsrooms -- the entire reason the subject stage exists -- so
    selection still ran on raw wire volume. Measured on 2026-08-20 it published
    "sonia bellina" (5 newsrooms, 8 sources) and dropped Hind Rajab (14).
    """
    from pipeline.config import zone_by_slug
    from pipeline.domain import Period
    from pipeline.stages.rank import rank_by_score

    members = [_member("lemonde.fr"), _member("elpais.com", "spain")]
    well_led = _scored(
        cluster_id="led",
        reference_newsroom_count=14,
        independent_source_count=21,
        members=members,
    )
    merely_loud = _scored(
        cluster_id="loud",
        reference_newsroom_count=5,
        independent_source_count=189,
        members=members,
    )

    ranked = rank_by_score([merely_loud, well_led], zone_by_slug("world"), Period.DAY, "2026-08-20")

    assert ranked[0]["cluster_id"] == "led", "judgment outranks volume"
    assert (
        ranked[0]["score"]["components"]["editorial_weight"]
        > (ranked[1]["score"]["components"]["editorial_weight"])
    )


def test_an_item_with_no_newsroom_count_is_not_credited_with_judgment() -> None:
    """A chronicle event or a bare Cluster carries no newsroom count. It scores
    zero on that factor rather than the undated-field default of 0.5: nothing
    measured editorial judgment for it, and 0.5 would invent some."""
    from pipeline.stages.rank import _editorial_weight

    assert _editorial_weight({}) == 0.0
    assert _editorial_weight({"reference_newsroom_count": 0}) == 0.0


def test_a_container_subject_is_demoted_below_a_focused_one() -> None:
    """Coherence is what tells a story from a container. A subject named after a
    country collects everything that country appears in, and the summarizer then
    welds unrelated events together -- a real Briefing said "Evergrande's founder
    jailed for life and a hotel fire kills nine in India" because both sat under
    "china". Measured, the size-normalized tightness separates them: Hind Rajab
    0.59 and Ceuta 0.79 against "Espana" 0.93 and "Europa" 0.89.
    """
    from pipeline.config import zone_by_slug
    from pipeline.domain import Period
    from pipeline.stages.rank import rank_by_score

    members = [_member("lemonde.fr"), _member("elpais.com", "spain")]
    common = {"reference_newsroom_count": 11, "independent_source_count": 40, "members": members}
    focused = _scored(cluster_id="focused", coherence=0.40, **common)
    container = _scored(cluster_id="container", coherence=0.07, **common)

    ranked = rank_by_score([container, focused], zone_by_slug("world"), Period.DAY, "2026-08-20")

    assert ranked[0]["cluster_id"] == "focused"


def test_an_item_with_no_coherence_measure_sits_in_the_middle() -> None:
    """Absent for every item that did not come from the subject stage. 0.5 --
    neither promoted nor buried on a dimension nothing measured, the same
    convention `_freshness` uses for an undated item."""
    from pipeline.stages.rank import _coherence

    assert _coherence({}) == 0.5
    assert _coherence({"coherence": None}) == 0.5
    assert _coherence({"coherence": 0.4}) == 0.4


def test_every_profile_weighs_exactly_the_factors_the_score_computes() -> None:
    """A weight table and a component dict that drift apart fail in one of two
    ways, and one of them is silent.

    Removing a weight raises `KeyError` at scoring time -- which is how this
    test came to exist: dropping `novelty` from the profiles while `score_item`
    still computed it broke 29 tests at once. Adding a component with no weight
    is worse: the factor is computed, never read, and nothing complains.
    """
    from pipeline.config import SCORE_WEIGHTS, zone_by_slug
    from pipeline.domain import Period
    from pipeline.stages.rank import score_item

    computed = set(
        score_item(_scored(), zone_by_slug("world"), Period.DAY, "2026-08-20")["components"]
    )

    for period, weights in SCORE_WEIGHTS.items():
        assert set(weights) == computed, (
            f"the {period} profile weighs {sorted(set(weights) - computed)} which nothing "
            f"computes, and ignores {sorted(computed - set(weights))} which it does"
        )
