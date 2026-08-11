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
