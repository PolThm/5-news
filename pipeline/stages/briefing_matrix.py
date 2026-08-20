"""The 15 Zone x 3 Period assembly loop that ``rank.py``'s ``rank_for_zone``
and ``link_across_days`` were always meant to be wired into.

Both mechanisms already exist, fully unit-tested in isolation, since Story
2.5/2.7 -- ``rank_for_zone``'s own docstring names this exact loop as
deferred work ("later Epic 3/4 work"), and Story 3.5 is that work.

One mechanism, one file, matching this pipeline's existing convention
(``rank.py``, ``history.py``): this module owns building the three per-
Period Cluster pools and ranking each of them against all 15 Zones.
``pipeline.stages.cycle`` orchestrates -- it calls this module, then
summarize, then publish, in that order -- but does not contain any of this
module's own logic.

``day``'s pool is this cycle's own qualifying Clusters, unchanged --
``link_across_days`` is never called for it (that window is a single ingest
day by definition). ``week``/``month`` pools first merge today's Clusters
with the relevant window of ``data/history/clusters.jsonl`` entries via
``link_across_days``, then rank exactly like ``day`` does.

The deduplicated-by-``cluster_id`` union across all 45 (Zone x Period)
rankings is what gets submitted to summarize (Story 3.5's fan-out decision,
made explicitly with the user): a Cluster selected into more than one Zone's
Briefing is summarized once, not once per Zone it appears in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pipeline.config import ZONES
from pipeline.domain import Period
from pipeline.stages.history import cycle_date
from pipeline.stages.rank import ZoneRanking, link_across_days, rank_for_zone

# FR-18/AC2 of Story 2.7: a week Briefing looks back 7 days, a month
# Briefing 30 -- matching history.py's own RETENTION_DAYS = 30 ceiling
# (a month window can never see further back than history itself retains).
_WINDOW_DAYS: dict[Period, int] = {
    Period.WEEK: 7,
}


def build_period_pools(
    today_clusters: list[dict],
    history_entries: list[dict],
    embedding_by_id: dict[str, list[float]],
    reference_date: datetime | None = None,
) -> dict[Period, list[dict]]:
    """The qualifying-Cluster pool for each of the 3 Periods.

    ``history_entries`` is the full set the caller already read from
    ``data/history/`` (any window, typically the full 30-day retention) --
    this function does its own per-Period window filtering rather than
    requiring the caller to pre-slice it three different ways, so
    day/week/month windows can never drift out of sync with each other by a
    caller's mistake.

    ``embedding_by_id`` must cover every id in both ``today_clusters`` and
    ``history_entries`` that might need to be compared -- built by the
    caller (today's Clusters need a fresh embed call; history entries
    already carry their own stored embedding, per Story 2.7).

    ``day``'s pool is ``today_clusters`` unchanged: ``link_across_days`` is
    never called for it (rank.py's own docstring -- "that window is a
    single ingest day by definition").

    A Cluster in ``today_clusters`` with no entry in ``embedding_by_id`` --
    an upstream embedding failure (Cohere outage) degrades ``cluster.py``'s
    own output but does not remove the Cluster (AD-10) -- cannot be
    compared by ``link_across_days``, which requires every item it receives
    to have one. Such a Cluster is passed through unlinked in every
    Period's pool (present, just never merged with history) rather than
    crashing the whole ranking matrix over one degraded Cluster.
    """
    reference = reference_date or datetime.now(UTC)
    linkable = [c for c in today_clusters if c["cluster_id"] in embedding_by_id]
    unlinkable = [c for c in today_clusters if c["cluster_id"] not in embedding_by_id]

    # The day pool is the day's own events, not everything on hand.
    #
    # It used to be `today_clusters` unfiltered, which was right while that
    # meant one cycle's Clusters. Since the editorial agenda supplies
    # candidates it means seven days of them, so a "today" Briefing could lead
    # on something from five days ago -- and did, until scoring made it visible.
    # The spec puts the daily window at 24-36h (§7.2); one calendar day of the
    # chronicle is the closest thing this pipeline can state exactly.
    #
    # Items with no editorial day (the fallback path, when the agenda is
    # unavailable) are kept: they come from this cycle's own collection by
    # definition, so they ARE today's.
    pools: dict[Period, list[dict]] = {
        Period.DAY: [
            cluster
            for cluster in today_clusters
            if not (cluster.get("editorial_day") or cluster.get("agenda_day"))
            or (cluster.get("editorial_day") or cluster["agenda_day"])
            >= (reference - timedelta(days=1)).date().isoformat()
        ]
    }
    for period, window_days in _WINDOW_DAYS.items():
        window_history = _within_window(history_entries, reference, window_days)
        pools[period] = [
            *link_across_days(linkable, window_history, embedding_by_id),
            *unlinkable,
        ]
    return pools


def _within_window(
    history_entries: list[dict], reference_date: datetime, window_days: int
) -> list[dict]:
    """The same cutoff arithmetic ``history.read_history`` applies when
    reading from disk, applied here to an already-loaded list -- this
    module receives ``history_entries`` once from its caller and filters
    per Period, rather than every Period re-reading ``clusters.jsonl``
    itself. Mirrors ``history.cycle_date``'s malformed-row tolerance: an
    undatable row is excluded rather than crashing this filter."""
    cutoff = reference_date - timedelta(days=window_days)
    result = []
    for entry in history_entries:
        entry_date = cycle_date(entry.get("cycle_id", ""))
        if entry_date is not None and entry_date >= cutoff:
            result.append(entry)
    return result


def rank_all_zones(
    clusters: list[dict],
    period: Period = Period.DAY,
    reference_day: str = "",
) -> list[ZoneRanking]:
    """Run ``rank_for_zone`` for all 15 Zones against one Period's pool.

    One call per Zone -- ``rank_for_zone`` already handles FR-16's Continent
    fallback and FR-17's anti-concentration cap internally; this function
    adds nothing but the loop across Zones.
    """
    return [rank_for_zone(clusters, zone, period, reference_day) for zone in ZONES]


def dedupe_union(rankings: list[ZoneRanking]) -> list[dict]:
    """Every distinct Cluster (by ``cluster_id``) selected into any Zone's
    Briefing, exactly once -- the shared pool summarize is submitted
    against (Story 3.5's fan-out decision: one batch per Output Language,
    not one per Zone x Period x Language).

    First-seen wins on a duplicate `cluster_id`. Within one Period this is
    not a meaningful choice: every `ZoneRanking` for the same Period ranks
    from the same underlying pool, so a Cluster's fields never vary across
    the Zones that select it.

    Across Periods, they can: a Cluster linked into the week/month pool
    (``link_across_days``) carries a recomputed `independent_source_count`/
    `country_count`/`countries` reflecting every linked day's coverage,
    while its `day`-Period, unlinked occurrence carries only today's. This
    function is typically called with rankings already flattened across
    Periods (`cycle.py`'s call site), so whichever occurrence is first-seen
    in iteration order is the one whose *text* gets summarized -- a linked
    Cluster's day-Briefing entry can then display slightly different
    counts than the summary text was generated against. This is a known,
    deliberately accepted approximation (the alternative -- submitting a
    separate summarize request per Period-variant of the same Cluster --
    reintroduces exactly the redundant-summarization cost Story 3.5's
    fan-out decision exists to avoid), not an oversight; revisit only if
    real cycle output shows this drifting the displayed counts noticeably.
    """
    seen: dict[str, dict] = {}
    for ranking in rankings:
        for cluster in ranking.ranked_clusters:
            seen.setdefault(cluster["cluster_id"], cluster)
    return list(seen.values())


__all__ = ["build_period_pools", "dedupe_union", "rank_all_zones"]
