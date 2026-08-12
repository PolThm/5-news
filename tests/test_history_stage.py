"""Tests for the history stage: the small persisted record that makes
Story 2.7's cross-day linking possible at all.

No live Cohere call anywhere here — the injected `embed` keeps every test
network-free, matching every other adapter-boundary test in this pipeline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pipeline.adapters.cohere_embed import EmbeddingResult
from pipeline.stages import read_jsonl
from pipeline.stages.history import append_history, read_history


def _ranked_cluster(cluster_id: str, sources: int, countries: list[str], rank: int) -> dict:
    return {
        "cluster_id": cluster_id,
        "members": [{"title": f"title for {cluster_id}", "url": "https://example.com/x"}],
        "independent_source_count": sources,
        "country_count": len(countries),
        "countries": sorted(countries),
        "origin_country": countries[0],
        "rank": rank,
    }


def _fake_embed(vector_by_title: dict[str, list[float]]):
    def embed(titles: list[str]) -> EmbeddingResult:
        return EmbeddingResult(vectors=[vector_by_title[t] for t in titles])

    return embed


def test_append_writes_one_record_per_selected_cluster(tmp_path: Path) -> None:
    selected = [
        _ranked_cluster("a", sources=3, countries=["france", "germany"], rank=1),
        _ranked_cluster("b", sources=2, countries=["japan", "china"], rank=2),
    ]
    embed = _fake_embed(
        {"title for a": [1.0, 0.0], "title for b": [0.0, 1.0]},
    )

    append_history(
        selected,
        cycle_id="2026-08-11T06-00-00Z",
        history_root=tmp_path,
        embed=embed,
    )

    records = list(read_jsonl(tmp_path / "clusters.jsonl"))
    assert len(records) == 2
    assert {r["cluster_id"] for r in records} == {"a", "b"}
    assert records[0]["cycle_id"] == "2026-08-11T06-00-00Z"
    assert records[0]["embedding"] in ([1.0, 0.0], [0.0, 1.0])


def test_history_accumulates_across_cycles(tmp_path: Path) -> None:
    embed = _fake_embed({"title for a": [1.0, 0.0]})
    append_history(
        [_ranked_cluster("a", sources=2, countries=["france", "spain"], rank=1)],
        cycle_id="2026-08-10T06-00-00Z",
        history_root=tmp_path,
        embed=embed,
    )
    append_history(
        [_ranked_cluster("a", sources=2, countries=["france", "spain"], rank=1)],
        cycle_id="2026-08-11T06-00-00Z",
        history_root=tmp_path,
        embed=embed,
    )

    records = list(read_jsonl(tmp_path / "clusters.jsonl"))
    assert len(records) == 2
    assert {r["cycle_id"] for r in records} == {"2026-08-10T06-00-00Z", "2026-08-11T06-00-00Z"}


def test_retention_prunes_entries_older_than_the_window(tmp_path: Path) -> None:
    history_path = tmp_path / "clusters.jsonl"
    old_record = {
        "cycle_id": "2026-07-01T06-00-00Z",  # 40+ days before the new cycle
        "cluster_id": "old",
        "embedding": [1.0, 0.0],
        "independent_source_count": 2,
        "country_count": 2,
        "countries": ["france", "spain"],
        "origin_country": "france",
    }
    history_path.write_text(json.dumps(old_record, sort_keys=True) + "\n", encoding="utf-8")

    embed = _fake_embed({"title for new": [0.0, 1.0]})
    append_history(
        [
            {
                "cluster_id": "new",
                "members": [{"title": "title for new", "url": "https://example.com/new"}],
                "independent_source_count": 2,
                "country_count": 2,
                "countries": ["china", "japan"],
                "origin_country": "japan",
                "rank": 1,
            }
        ],
        cycle_id="2026-08-11T06-00-00Z",
        history_root=tmp_path,
        embed=embed,
    )

    records = list(read_jsonl(history_path))
    assert len(records) == 1
    assert records[0]["cluster_id"] == "new"


def test_read_history_filters_to_the_requested_window(tmp_path: Path) -> None:
    records = [
        {"cycle_id": "2026-08-01T06-00-00Z", "cluster_id": "a"},
        {"cycle_id": "2026-08-09T06-00-00Z", "cluster_id": "b"},
        {"cycle_id": "2026-08-11T06-00-00Z", "cluster_id": "c"},
    ]
    history_path = tmp_path / "clusters.jsonl"
    history_path.write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n", encoding="utf-8"
    )

    within_week = read_history(
        history_root=tmp_path,
        reference_date=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
        window_days=7,
    )

    assert {r["cluster_id"] for r in within_week} == {"b", "c"}


def test_append_with_no_selected_clusters_writes_nothing_new(tmp_path: Path) -> None:
    embed = _fake_embed({})
    append_history([], cycle_id="2026-08-11T06-00-00Z", history_root=tmp_path, embed=embed)

    history_path = tmp_path / "clusters.jsonl"
    records = list(read_jsonl(history_path)) if history_path.exists() else []
    assert records == []


def test_append_with_an_empty_members_list_does_not_crash(tmp_path: Path) -> None:
    """A clique formed entirely from historical entries (rank.py's
    link_across_days) legitimately produces `"members": []` -- its own
    comment calls this "a completely ordinary case," not an edge case. This
    stage must degrade that Cluster, not raise IndexError, once cross-day
    linking is wired into a real cycle."""
    embed = _fake_embed({"title for normal": [1.0, 0.0]})
    append_history(
        [
            {
                "cluster_id": "history-only",
                "members": [],
                "independent_source_count": 2,
                "country_count": 2,
                "countries": ["france", "germany"],
                "origin_country": "france",
                "rank": 1,
            },
            _ranked_cluster("normal", sources=2, countries=["japan", "china"], rank=2),
        ],
        cycle_id="2026-08-11T06-00-00Z",
        history_root=tmp_path,
        embed=embed,
    )

    history_path = tmp_path / "clusters.jsonl"
    records = list(read_jsonl(history_path))
    # The empty-members Cluster is skipped (nothing to embed for it); the
    # normal Cluster is still recorded -- one Cluster's degenerate shape
    # must not cost every other Cluster its history entry.
    assert {r["cluster_id"] for r in records} == {"normal"}


def test_a_malformed_cycle_id_in_history_is_skipped_not_crashed(tmp_path: Path) -> None:
    """An adversarial review found cycle_date had no error handling --
    data/history/clusters.jsonl is a long-lived, hand-editable, committed
    file with no schema enforcement, so a single malformed row must not
    crash every future read."""
    history_path = tmp_path / "clusters.jsonl"
    records = [
        {"cycle_id": "not-a-valid-cycle-id", "cluster_id": "bad"},
        {"cycle_id": "2026-08-11T06-00-00Z", "cluster_id": "good"},
    ]
    history_path.write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n", encoding="utf-8"
    )

    result = read_history(
        history_root=tmp_path,
        reference_date=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
        window_days=7,
    )

    assert {r["cluster_id"] for r in result} == {"good"}


def test_append_with_a_malformed_cycle_id_skips_retention_but_still_appends(
    tmp_path: Path,
) -> None:
    """A malformed --cycle-id (a free-form CLI argument) must not crash the
    cycle; retention pruning is skipped rather than guessing a cutoff."""
    embed = _fake_embed({"title for a": [1.0, 0.0]})

    append_history(
        [_ranked_cluster("a", sources=2, countries=["france", "spain"], rank=1)],
        cycle_id="not-a-valid-cycle-id",
        history_root=tmp_path,
        embed=embed,
    )

    records = list(read_jsonl(tmp_path / "clusters.jsonl"))
    assert len(records) == 1
    assert records[0]["cluster_id"] == "a"
