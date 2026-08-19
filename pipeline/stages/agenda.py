"""Agenda stage: turn an editorial chronicle into the Briefing's spine.

This stage inverts what decided a Briefing's contents. Selection used to start
from our own corpus and keep whatever the most outlets had rerun -- the
Consensus Score as the only gate. Measured on real output, that gate published
a ZZ Top drummer's death, a suspended tennis player and a Belgian
construction firm's revenue, while the same cycle's corpus of 10,948 articles
contained 2 of the 19 events human editors recorded for those days.

So the chronicle leads now, and the corpus corroborates. Each event a human
editor judged worth recording becomes a candidate item; the Clusters we
collected are matched against it to supply the Articles, the source list and
the Consensus Score. An event nothing in our corpus covered is still an event,
and it keeps the citation the chronicle gave it.

**The Consensus Score keeps its meaning and loses its veto.** It still counts
Independent Sources and countries, still shows only what the source list can
substantiate, and is still shown to the reader as proof of coverage. What it no
longer does is decide *importance*, which it was never able to measure: five
local radio stations rerunning one wire dispatch out-score any single
newsroom's own reporting.

Output goes to ``data/intermediate/agenda/<cycle-id>/items.jsonl`` in the same
shape the Cluster stage emits, so rank, summarize and publish need no knowledge
of where an item came from (AD-12: rank decides what qualifies, this stage
decides what is a candidate).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.preprocessing import normalize

from pipeline.adapters import Failure
from pipeline.adapters.cohere_embed import EmbeddingResult, embed_titles
from pipeline.adapters.editorial_agenda import EditorialEvent, Fetch, collect_agenda
from pipeline.stages import (
    DEFAULT_DATA_ROOT,
    output_dir_for,
    trace,
    write_atomically,
    write_jsonl,
)
from pipeline.stages.cluster import EmbedFn

STAGE = "agenda"

# How close a Cluster must sit to a chronicle event to count as covering it,
# as a cosine distance on unit-normalized embeddings.
#
# Deliberately looser than cluster.py's own same-Event threshold. Those compare
# two headlines about one happening; this compares an encyclopedic sentence
# ("The United Arab Emirates's defence ministry detects two missiles fired from
# Iran") against a newsroom headline ("Iran rejects UAE statement on
# missiles") -- the same event told at different distances, in different
# registers, often in another language. Measured on real pairs from 2026-08-19:
# genuine matches landed at 0.28-0.40, and the nearest unrelated pair sat at
# 0.54, so the band between them is wide and 0.45 sits inside it.
#
# A miss here is not fatal: an uncorroborated event still publishes with the
# chronicle's own citation. A false match is worse, because it would attach the
# wrong source list to an event, so this errs toward missing.
COVERAGE_DISTANCE = 0.45


@dataclass(frozen=True, slots=True)
class WrittenAgenda:
    output_path: Path
    metadata_path: Path
    items_out: int
    corroborated: int
    degraded: bool


def event_id(event: EditorialEvent) -> str:
    """A stable id for an event, keyed on its text.

    The chronicle restates an ongoing story across days with slightly different
    wording, so this is not a cross-day identity -- the rank stage's own
    linking handles that. What it guarantees is that the same sentence produces
    the same id on a resumed cycle, which is what AD-11's two-phase summarize
    depends on.
    """
    return hashlib.sha256(event.text.encode("utf-8")).hexdigest()[:16]


def _members_from_clusters(clusters: list[dict]) -> list[dict]:
    """Every Article backing a set of Clusters, de-duplicated by URL."""
    members: dict[str, dict] = {}
    for cluster in clusters:
        for member in cluster.get("members", []) or []:
            url = member.get("url", "")
            if url and url not in members:
                members[url] = member
    return sorted(members.values(), key=lambda m: m.get("title", ""))


def build_items(
    events: list[EditorialEvent],
    clusters: list[dict],
    event_vectors: list[list[float]],
    cluster_vectors: list[list[float]],
) -> list[dict]:
    """Match each event to the Clusters covering it and emit Briefing items.

    Vectors are passed in rather than computed here, so this function is pure
    and testable without a network (the same injection discipline every other
    stage uses).
    """
    if not events:
        return []

    events_array = normalize(np.asarray(event_vectors, dtype=float))
    if clusters and cluster_vectors:
        clusters_array = normalize(np.asarray(cluster_vectors, dtype=float))
        # One matrix product for every event-cluster pair: a few tens of events
        # against a few thousand Clusters is trivial in BLAS and was the shape
        # that made a per-pair Python loop cost 25 minutes elsewhere in this
        # pipeline.
        distances = 1.0 - (events_array @ clusters_array.T)
    else:
        distances = np.ones((len(events), 0))

    items: list[dict] = []
    for index, event in enumerate(events):
        covering = (
            [clusters[j] for j in np.flatnonzero(distances[index] <= COVERAGE_DISTANCE)]
            if distances.shape[1]
            else []
        )
        members = _members_from_clusters(covering)

        # Coverage comes from the Articles actually attached, never from the
        # Clusters' own stored counts: an item must only ever claim what its
        # own source list can show (the invariant AC3 states and a real cycle
        # broke on 2026-08-19).
        sources = {m.get("source", "") for m in members if m.get("source")}
        countries = sorted(
            {m.get("source_country", "") for m in members if m.get("source_country")}
        )

        # Where the reader is sent. Our own corpus first -- it is the source we
        # can describe and count -- then the chronicle's citation, which is how
        # an event no outlet in our corpus covered still reaches a reader. Those
        # citations lean on AP, Reuters and the BBC, which GDELT cannot give us.
        outbound_url = (
            members[0].get("url") if members else (event.sources[0] if event.sources else None)
        )
        outbound_source = (
            members[0].get("source")
            if members
            else (event.sources[0].split("/")[2] if event.sources else None)
        )

        items.append(
            {
                "cluster_id": event_id(event),
                "members": members,
                "independent_source_count": len(sources),
                "country_count": len(countries),
                "countries": countries,
                "origin_country": countries[0] if countries else "unknown",
                # What the event is ABOUT, never where its outlets sit.
                #
                # `countries` above is source_country -- the newsroom's own
                # location -- and folding it in here would repeat the exact bug
                # this pipeline was fixed for earlier today: a Swiss paper
                # covering a Russian missile strike in Kharkiv would place that
                # event in Switzerland. The event's own countries come from the
                # chronicle's wikilinks and prose; the corroborating Clusters
                # contribute the countries THEY are about, which the collect
                # stage read out of each Article's own location field.
                "mentioned_countries": sorted(
                    set(event.countries)
                    | {
                        country
                        for cluster in covering
                        for country in (cluster.get("mentioned_countries") or ())
                    }
                ),
                "outbound_url": outbound_url,
                "outbound_source": outbound_source,
                # The editorial provenance. `agenda_text` is what summarize
                # falls back to when no Article of ours covered the event, and
                # `agenda_category` is the chronicle's own taxonomy ("Armed
                # conflicts and attacks"), the first signal this pipeline has
                # ever had for telling hard news from entertainment.
                "agenda_text": event.text,
                "agenda_category": event.category,
                "agenda_day": event.day,
                "agenda_sources": list(event.sources),
                "corroborated": bool(members),
            }
        )
    return items


def run_agenda(
    cluster_path: Path,
    cycle_id: str,
    data_root: Path = DEFAULT_DATA_ROOT,
    embed: EmbedFn = embed_titles,
    days: int = 7,
    fetch: Fetch | None = None,
) -> WrittenAgenda:
    """Fetch the agenda, match it against this cycle's Clusters, write items.

    Degrades to an empty agenda rather than failing the cycle (AD-10). An empty
    agenda means no items, which means no Briefing published and the previous
    set left in place (AD-7) -- the honest outcome when the one signal that
    decides importance is unavailable.
    """
    from pipeline.stages import read_jsonl

    destination = output_dir_for(STAGE, cycle_id, root=data_root)
    output_path = destination / "items.jsonl"
    metadata_path = destination / f"{STAGE}.json"

    failures: list[Failure] = []
    events, agenda_failures = (
        collect_agenda(days=days) if fetch is None else collect_agenda(days=days, fetch=fetch)
    )
    failures.extend(agenda_failures)
    trace(f"agenda: {len(events)} editorial events over {days} days")

    clusters = list(read_jsonl(cluster_path)) if cluster_path.is_file() else []

    items: list[dict] = []
    if events:
        # Titles, not summaries: the Clusters are represented by their first
        # member's headline, the same representative convention every other
        # stage uses.
        cluster_titles = [(c.get("members") or [{}])[0].get("title", "") for c in clusters]
        result: EmbeddingResult = embed([e.text for e in events] + cluster_titles)
        expected = len(events) + len(cluster_titles)
        if result.failures or len(result.vectors) != expected:
            detail = "; ".join(f.detail for f in result.failures) or (
                f"expected {expected} vectors, got {len(result.vectors)}"
            )
            failures.append(Failure(STAGE, f"embedding failed, agenda uncorroborated: {detail}"))
            # Still emit the events: uncorroborated items carry the chronicle's
            # own citation and remain publishable, which is strictly better
            # than losing the day.
            items = build_items(events, [], [], [])
        else:
            items = build_items(
                events,
                clusters,
                result.vectors[: len(events)],
                result.vectors[len(events) :],
            )

    corroborated = sum(1 for i in items if i["corroborated"])
    trace(f"agenda: {len(items)} items, {corroborated} corroborated by our own corpus")

    write_jsonl(output_path, items)
    metadata = {
        "stage": STAGE,
        "cycle_id": cycle_id,
        "events_in": len(events),
        "clusters_in": len(clusters),
        "items_out": len(items),
        "corroborated": corroborated,
        "degraded": bool(failures),
        "failures": [f.to_dict() for f in failures],
    }
    write_atomically(
        metadata_path, json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )

    return WrittenAgenda(
        output_path=output_path,
        metadata_path=metadata_path,
        items_out=len(items),
        corroborated=corroborated,
        degraded=bool(failures),
    )


def main(argv: list[str] | None = None) -> int:
    import sys

    from pipeline.stages import cycle_id_for, stage_arg_parser

    parser = stage_arg_parser(STAGE)
    args = parser.parse_args(argv)
    written = run_agenda(
        Path(args.input), cycle_id=args.cycle_id or cycle_id_for(), data_root=args.data_root
    )
    if written.degraded:
        print(f"{STAGE}: degraded — see {written.metadata_path}", file=sys.stderr)
    print(
        f"{STAGE}: {written.items_out} items "
        f"({written.corroborated} corroborated) -> {written.output_path}"
    )
    return 0


__all__: list[Any] = [
    "COVERAGE_DISTANCE",
    "STAGE",
    "WrittenAgenda",
    "build_items",
    "event_id",
    "run_agenda",
]


if __name__ == "__main__":
    raise SystemExit(main())
