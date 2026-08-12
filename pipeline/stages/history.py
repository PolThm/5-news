"""History stage: the small persisted record that makes Story 2.7's
cross-day Cluster linking possible at all.

Nothing else in this pipeline survives a cycle. Every stage's output under
``data/intermediate/<stage>/<cycle-id>/`` is gitignored except ``cycle.json``
(Story 1.1) — a GitHub Actions run is a fresh, ephemeral runner, so yesterday's
``clusters.jsonl`` does not exist when today's cycle starts unless it was
explicitly committed. This stage is that explicit commit: one line per
selected Cluster per day, in ``data/history/clusters.jsonl``, tracked in git
like ``cycle.json`` is.

Deliberately small. Only what a future day's linking decision needs: the
representative title's embedding (for similarity), and the same Coverage
fields ``cluster.py`` already produces (for aggregating the Consensus Score
across linked days). Not the full Cluster record — no member titles, no
article lists. A 30-day retention window is enough for a month Period; this
is not an archive.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pipeline.adapters.cohere_embed import EmbeddingResult, embed_titles
from pipeline.stages import DEFAULT_DATA_ROOT, read_jsonl, write_jsonl

RETENTION_DAYS = 30

EmbedFn = Callable[[list[str]], EmbeddingResult]


def _history_path(history_root: Path) -> Path:
    return history_root / "clusters.jsonl"


def _cycle_date(cycle_id: str) -> datetime | None:
    """A cycle id is a UTC timestamp (``pipeline.stages.cycle_id_for``'s
    format); parsing it back is how history entries are dated without a
    separate stored field to keep in sync.

    Returns ``None`` on anything that doesn't parse rather than raising.
    ``data/history/clusters.jsonl`` is a long-lived, hand-editable, committed
    file with no schema enforcement past this module — a single malformed or
    hand-corrupted row must not crash every future read of the file. Callers
    treat ``None`` as "cannot date this row," which for both retention and
    windowing means "do not keep/include it": an undatable row is no better
    than a stale one for either purpose.
    """
    try:
        return datetime.strptime(cycle_id, "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def read_history(
    history_root: Path,
    reference_date: datetime,
    window_days: int,
) -> list[dict[str, Any]]:
    """Every history record whose cycle falls within ``window_days`` before
    ``reference_date``, inclusive."""
    path = _history_path(history_root)
    if not path.is_file():
        return []
    cutoff = reference_date - timedelta(days=window_days)
    result = []
    for row in read_jsonl(path):
        row_date = _cycle_date(row.get("cycle_id", ""))
        if row_date is not None and row_date >= cutoff:
            result.append(row)
    return result


def append_history(
    selected_clusters: list[dict[str, Any]],
    cycle_id: str,
    history_root: Path = DEFAULT_DATA_ROOT / "history",
    embed: EmbedFn = embed_titles,
) -> None:
    """Append this cycle's selected Clusters to the history file, then prune
    anything older than ``RETENTION_DAYS``.

    ``selected_clusters`` is rank's output shape — the Clusters that actually
    appeared in a Briefing, not everything the cluster stage produced.
    Recording only selected Clusters keeps history proportional to what a
    reader could have seen, not to total daily coverage volume.

    On an embedding failure, this cycle's Clusters are simply not added to
    history — a missed history entry costs one day's linking opportunity for
    those Clusters, never a false one, matching the same one-sided-error
    preference every merge layer in this pipeline already follows (AD-10).
    """
    path = _history_path(history_root)
    existing = list(read_jsonl(path)) if path.is_file() else []

    new_records: list[dict[str, Any]] = []
    # A clique formed entirely from historical entries (rank.py's
    # link_across_days, once wired into a real cycle) legitimately produces
    # `"members": []` -- that function's own comment calls this "a
    # completely ordinary case," not an edge case. Such a Cluster has
    # nothing new to embed or record here; skip it rather than crash on an
    # empty members[0] lookup, matching AD-10's degrade-not-abort pattern.
    embeddable = [c for c in selected_clusters if c.get("members")]
    if embeddable:
        # Story 3.1 replaced cluster.py's bare member_titles with full member
        # dicts ({"title": ..., "url": ..., ...}); the representative title
        # (members are sorted by title -- the first is a stable, arbitrary
        # pick, same as the old member_titles[0] convention) is all this
        # embedding call ever needed.
        titles = [cluster["members"][0]["title"] for cluster in embeddable]
        result = embed(titles)
        if not result.failures and len(result.vectors) == len(embeddable):
            for cluster, vector in zip(embeddable, result.vectors, strict=True):
                new_records.append(
                    {
                        "cycle_id": cycle_id,
                        "cluster_id": cluster["cluster_id"],
                        "embedding": list(vector),
                        "independent_source_count": cluster["independent_source_count"],
                        "country_count": cluster["country_count"],
                        "countries": cluster["countries"],
                        "origin_country": cluster["origin_country"],
                    }
                )

    reference_date = _cycle_date(cycle_id)
    if reference_date is None:
        # cycle_id is this cycle's own identifier -- normally always
        # well-formed (cycle_id_for()'s output), but --cycle-id is a
        # free-form CLI argument (pipeline/stages/cycle.py's main()), so an
        # operator-supplied value could still be malformed. Skip retention
        # pruning entirely rather than guess a cutoff from nothing; the new
        # records are still appended.
        write_jsonl(path, existing + new_records)
        return
    cutoff = reference_date - timedelta(days=RETENTION_DAYS)
    retained = []
    for row in existing:
        row_date = _cycle_date(row.get("cycle_id", ""))
        if row_date is not None and row_date >= cutoff:
            retained.append(row)

    write_jsonl(path, retained + new_records)
