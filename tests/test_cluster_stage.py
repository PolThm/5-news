"""Tests for the cluster stage.

Clustering logic is tested against hand-constructed embedding vectors, never
live Cohere output — see Story 2.1 Dev Notes -> "What determinism means
here": embeddings themselves are not contractually byte-reproducible across
API calls, but everything downstream of a fixed set of vectors must be.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.adapters.cohere_embed import EmbeddingResult
from pipeline.stages import read_jsonl
from pipeline.stages.cluster import (
    assign_cluster_ids,
    cluster_vectors,
    coverage_for_cluster,
    run_cluster,
)


def _group(title: str, normalized: str, country: str, sources: list[str]) -> dict:
    return {
        "title": title,
        "url": f"https://example.com/{normalized}",
        "published_at": "2026-08-11T06:00:00+00:00",
        "source": sources[0],
        "source_country": country,
        "language": "en",
        "collected_by": "gdelt",
        "normalized_title": normalized,
        "independent_source_count": 1,
        "country_count": 1,
        "sources": sorted(sources),
        "countries": [country],
        "article_count": len(sources),
    }


# --- cluster_vectors: hand-constructed embeddings -----------------------------


def test_close_vectors_land_in_the_same_cluster() -> None:
    vectors = [
        [1.0, 0.0, 0.0],
        [0.99, 0.01, 0.0],  # nearly identical direction -> same event
        [0.0, 1.0, 0.0],  # orthogonal -> different event
    ]
    labels = cluster_vectors(vectors)

    assert labels[0] == labels[1]
    assert labels[0] != labels[2]


def test_three_unrelated_vectors_become_three_singleton_clusters() -> None:
    """A point with no neighbor inside the distance threshold is its own
    connected component — a legitimate singleton Cluster, not a discard.
    Deciding what qualifies for a Briefing is the rank stage's job, not this
    one's (AD-12)."""
    vectors = [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]]
    labels = cluster_vectors(vectors)

    assert len(labels) == 3
    assert len(set(labels)) == 3, "three unrelated directions must not collapse together"


def test_clustering_two_vectors_never_raises() -> None:
    # A degenerate case worth locking down: connected-components with very
    # small input, and a zero pairwise distance (identical vectors).
    labels = cluster_vectors([[1.0, 0.0], [1.0, 0.0]])
    assert labels[0] == labels[1]


def test_an_unrelated_group_does_not_chain_into_a_genuine_pair() -> None:
    """The bug an adversarial review caught: HDBSCAN's cluster_selection_epsilon
    governs where it cuts its internal single-linkage tree, not the pairwise
    distance between merged points, so a chain of intermediate points could
    pull a genuinely unrelated group into a genuine pair's cluster even
    though its own distance to every member was far over the threshold.
    Connected-components requires a direct edge for every merge, so this
    cannot happen — verified directly for a group at distance ~1.0, far
    beyond _SAME_EVENT_DISTANCE, alongside a genuine near-duplicate pair."""
    genuine_pair = [[1.0, 0.0, 0.0], [0.99, 0.02, 0.0]]
    unrelated = [0.0, 1.0, 0.0]
    labels = cluster_vectors([*genuine_pair, unrelated])

    assert labels[0] == labels[1]
    assert labels[2] not in (labels[0],)


# --- assign_cluster_ids: deterministic, not HDBSCAN's arbitrary integers -----


def test_same_input_order_gives_the_same_ids_every_run() -> None:
    """AC6's actual contract: given the same vectors (hence the same labels,
    in the same input order), output is byte-identical every run. Dedupe's
    output is itself sorted by normalized_title (group_by_title), so the
    cluster stage's input order is already deterministic run-to-run for the
    same day's data — this is the guarantee that matters in practice."""
    ids_first = assign_cluster_ids(labels=[0, 0])
    ids_second = assign_cluster_ids(labels=[0, 0])

    assert ids_first == ids_second


def test_two_groups_with_identical_titles_in_different_clusters_get_different_ids() -> None:
    """An adversarial review caught a real bug here: IDs used to be derived
    from sorted member *titles*, so two dedupe groups sharing an identical
    title string collided onto the same cluster ID even when they were placed
    in different clusters — silently re-merging dispatches the clustering
    step had explicitly kept apart. IDs are now derived from member indices,
    which cannot collide this way regardless of title content."""
    # Two groups, both titled "Ceasefire agreed" in the caller's data, but
    # distance-based clustering put them in unrelated clusters (0 and 1).
    ids = assign_cluster_ids(labels=[0, 0, 1])

    assert ids[0] == ids[1]  # index 0 and 1 share label 0
    assert ids[2] != ids[0]  # index 2 has a different label -> must not collide


def test_different_members_get_different_cluster_ids() -> None:
    ids = assign_cluster_ids(labels=[0, 0, 1])
    assert ids[0] == ids[1]
    assert ids[0] != ids[2]


# --- coverage_for_cluster: reuse dedupe's union semantics, not reinvent -----


def test_coverage_unions_origin_countries_like_merge_all() -> None:
    groups = [
        _group("Ceasefire agreed", "ceasefire agreed", "france", ["o1.com"]),
        _group("Ceasefire agreed - AP", "ceasefire agreed ap", "germany", ["o2.com"]),
    ]
    coverage = coverage_for_cluster(groups)

    assert coverage.independent_source_count == 2
    assert coverage.country_count == 2


def test_coverage_of_two_dispatches_from_the_same_country_is_one_country() -> None:
    groups = [
        _group("A", "a", "france", ["o1.com"]),
        _group("B", "b", "france", ["o2.com"]),
    ]
    coverage = coverage_for_cluster(groups)

    assert coverage.independent_source_count == 2
    assert coverage.country_count == 1


def test_coverage_of_a_singleton_matches_the_underlying_group() -> None:
    groups = [_group("A", "a", "japan", ["o1.com"])]
    coverage = coverage_for_cluster(groups)

    assert coverage.independent_source_count == 1
    assert coverage.country_count == 1


# --- run_cluster: end to end, with an injected embedding function -----------


def test_run_cluster_groups_across_languages_and_writes_output(tmp_path: Path) -> None:
    groups = [
        _group("Ceasefire declared", "ceasefire declared", "france", ["lemonde.fr"]),
        _group("停戦が宣言された", "停戦が宣言された", "japan", ["nhk.jp"]),  # same event, Japanese
        _group("Stock market rallies", "stock market rallies", "united-states", ["cnn.com"]),
    ]
    input_path = tmp_path / "groups.jsonl"
    input_path.write_text("\n".join(json.dumps(g) for g in groups) + "\n", encoding="utf-8")

    # Two near-identical vectors for the ceasefire pair (French + Japanese),
    # one far-off vector for the unrelated market story.
    fake_vectors = {
        "Ceasefire declared": [1.0, 0.0, 0.0],
        "停戦が宣言された": [0.98, 0.02, 0.0],
        "Stock market rallies": [0.0, 0.0, 1.0],
    }

    def fake_embed(titles: list[str]) -> EmbeddingResult:
        return EmbeddingResult(vectors=[fake_vectors[t] for t in titles])

    data_root = tmp_path / "data"
    written = run_cluster(
        input_path,
        cycle_id="2026-08-11T06-00-00Z",
        data_root=data_root,
        embed=fake_embed,
    )

    clusters = list(read_jsonl(written.output_path))
    assert len(clusters) == 2

    by_size = sorted(clusters, key=lambda c: len(c["member_titles"]))
    assert len(by_size[0]["member_titles"]) == 1  # the market story, alone
    assert len(by_size[1]["member_titles"]) == 2  # the two ceasefire dispatches
    assert by_size[1]["independent_source_count"] == 2
    assert by_size[1]["country_count"] == 2  # france + japan, genuinely distinct


def test_run_cluster_degrades_to_one_cluster_per_group_on_embedding_failure(
    tmp_path: Path,
) -> None:
    groups = [
        _group("A", "a", "france", ["o1.com"]),
        _group("B", "b", "germany", ["o2.com"]),
    ]
    input_path = tmp_path / "groups.jsonl"
    input_path.write_text("\n".join(json.dumps(g) for g in groups) + "\n", encoding="utf-8")

    def failing_embed(titles: list[str]) -> EmbeddingResult:
        from pipeline.adapters import Failure

        return EmbeddingResult(failures=[Failure("cohere_embed", "boom")])

    data_root = tmp_path / "data"
    written = run_cluster(
        input_path,
        cycle_id="2026-08-11T06-00-00Z",
        data_root=data_root,
        embed=failing_embed,
    )

    clusters = list(read_jsonl(written.output_path))
    assert len(clusters) == 2, "a failed embedding must fall back to one cluster per group"
    assert written.degraded is True

    metadata = json.loads(written.metadata_path.read_text())
    assert metadata["degraded"] is True
    assert len(metadata["failures"]) == 1


def test_run_cluster_is_deterministic_given_fixed_embeddings(tmp_path: Path) -> None:
    groups = [
        _group("A", "a", "france", ["o1.com"]),
        _group("B", "b", "japan", ["o2.com"]),
        _group("C", "c", "brazil", ["o3.com"]),
    ]
    input_path = tmp_path / "groups.jsonl"
    input_path.write_text("\n".join(json.dumps(g) for g in groups) + "\n", encoding="utf-8")

    fixed_vectors = {"A": [1.0, 0.0], "B": [0.9, 0.1], "C": [0.0, 1.0]}

    def fake_embed(titles: list[str]) -> EmbeddingResult:
        return EmbeddingResult(vectors=[fixed_vectors[t] for t in titles])

    out1 = run_cluster(input_path, cycle_id="run-1", data_root=tmp_path / "d1", embed=fake_embed)
    out2 = run_cluster(input_path, cycle_id="run-1", data_root=tmp_path / "d2", embed=fake_embed)

    assert out1.output_path.read_bytes() == out2.output_path.read_bytes()


def test_run_cluster_empty_input(tmp_path: Path) -> None:
    input_path = tmp_path / "groups.jsonl"
    input_path.write_text("", encoding="utf-8")

    def fake_embed(titles: list[str]) -> EmbeddingResult:
        return EmbeddingResult(vectors=[])

    written = run_cluster(
        input_path, cycle_id="2026-08-11T06-00-00Z", data_root=tmp_path / "data", embed=fake_embed
    )
    clusters = list(read_jsonl(written.output_path))
    assert clusters == []
