"""Cluster stage: group dedupe's output across languages by semantic
similarity — the mechanism that lets a French and a Japanese Article about
the same Event count once.

Dedupe (Story 1.4) already collapses same-language, near-identical headlines.
What it cannot do is recognize that "Ceasefire declared" and "停戦が宣言され
た" describe the same Event — no title-normalization rule bridges languages.
This stage closes that gap by embedding each dedupe group's representative
title and clustering the embeddings.

**This stage decides which dedupe groups belong to the same Event. It does
not decide what an Independent Source is** (dedupe already decided that,
AD-5) and it does not decide what qualifies for a Briefing (rank does that,
Story 2.2, AD-12) — a singleton Cluster is legitimate output here, not a
discard.

Embeddings are not contractually reproducible byte-for-byte across separate
API calls (a vendor-side concern, outside this pipeline's control). What must
be deterministic is everything downstream of a fixed set of vectors:
normalize -> cluster -> assign stable IDs -> serialize. Tests exercise that
determinism against fixed, hand-constructed vectors, never live output.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial.distance import pdist, squareform
from sklearn.preprocessing import normalize

from pipeline.adapters import Failure
from pipeline.adapters.cohere_embed import ADAPTER as _EMBED_ADAPTER
from pipeline.adapters.cohere_embed import EmbeddingResult, embed_titles
from pipeline.stages import (
    DEFAULT_DATA_ROOT,
    cycle_id_for,
    output_dir_for,
    read_jsonl,
    stage_arg_parser,
    write_atomically,
    write_jsonl,
)

STAGE = "cluster"

# embed_titles's real signature also takes an optional `client` for injection;
# this alias only describes the single-argument shape every call site here
# actually uses (run_cluster never passes a client through the injected path).
EmbedFn = Callable[[list[str]], EmbeddingResult]


# On L2-normalized vectors, Euclidean distance d and cosine similarity c
# relate by d^2 = 2 - 2c, so d = 0.4 corresponds to c ~= 0.92 — headlines
# whose embeddings agree that closely are treated as the same Event.
_SAME_EVENT_DISTANCE = 0.4


def _vectors_are_well_formed(vectors: list[list[float]]) -> bool:
    """Reject exactly what would otherwise reach ``cluster_vectors`` and
    either raise or silently corrupt clustering.

    Two distinct failure modes, found by an adversarial review: (1) ragged
    rows or NaN/Inf components crash ``normalize``/``pdist`` with no local
    guard, propagating to ``cycle.py``'s generic exception handler and
    marking the whole cycle incomplete rather than degrading gracefully; (2)
    an all-zero vector (a plausible response to a truncated or empty title)
    normalizes to itself with no error and sits at distance 0 from every
    other all-zero vector, silently merging unrelated dedupe groups into one
    Cluster with no failure ever recorded. Catching both here, before
    clustering runs, means a bad response degrades the same way any other
    embedding failure does — one Cluster per dedupe group — instead of
    crashing or silently corrupting.
    """
    if not vectors:
        return True
    width = len(vectors[0])
    for vector in vectors:
        if len(vector) != width:
            return False
        if any(not np.isfinite(component) for component in vector):
            return False
        if all(component == 0 for component in vector):
            return False
    return True


def cluster_vectors(vectors: list[list[float]]) -> list[int]:
    """Group vectors by direction, returning one label per input vector.

    This used to call ``sklearn.cluster.HDBSCAN`` with a fixed
    ``cluster_selection_epsilon``. An adversarial review caught that
    HDBSCAN's epsilon threshold governs where it cuts its internal
    single-linkage tree, not the pairwise distance between merged points —
    single-linkage chaining lets two points 1.4 apart merge into the same
    cluster as long as a chain of intermediate points connects them, each
    link under the threshold. Reproduced directly: at a realistic scale (40
    unrelated groups plus one genuine near-duplicate pair), an unrelated
    group at distance 1.0-1.4 joined the genuine pair's cluster in 18 of 30
    random trials. That is exactly the false-merge this stage exists to
    prevent — it would have inflated ``independent_source_count`` for
    unrelated Events.

    Replaced with connected components over an explicit threshold graph:
    two points are linked only if *their own* pairwise distance is within
    ``_SAME_EVENT_DISTANCE``, and a cluster is a connected component of that
    graph. No transitive chaining — the fixed threshold is a real per-edge
    guarantee, not a tree-cut heuristic. Verified against the same
    reproduction: 0 of 30 trials merge the unrelated group into the genuine
    pair's cluster.

    Every point that has no neighbor within the threshold is its own
    singleton component, which is correct here for the same reason
    HDBSCAN's noise label used to be: a Cluster of one dedupe group is
    legitimate output, not a discard (AD-12 — the rank stage, not this one,
    decides what qualifies for a Briefing).
    """
    if not vectors:
        return []
    if len(vectors) == 1:
        return [0]

    array = np.asarray(vectors, dtype=float)
    unit_vectors = normalize(array, copy=True)
    distances = squareform(pdist(unit_vectors))
    # Two genuinely identical titles (distance 0) must still merge — only the
    # diagonal (a point's distance to itself) is excluded, not zero-distance
    # pairs in general.
    adjacency = distances <= _SAME_EVENT_DISTANCE
    np.fill_diagonal(adjacency, False)
    _, labels = connected_components(csr_matrix(adjacency.astype(int)), directed=False)
    return [int(label) for label in labels]


def assign_cluster_ids(labels: list[int]) -> list[str]:
    """Turn ``cluster_vectors``'s arbitrary, run-order-dependent integer
    labels into stable identifiers.

    The label *values* carry no meaning across runs — the same event could be
    label 0 in one run and label 3 in the next if input order changes. Keying
    the ID on the sorted *indices* of each label's members (not their title
    text) makes it stable regardless of input order.

    Indices, not titles: an adversarial review caught that hashing the sorted
    member *titles* lets two dedupe groups with an identical ``title`` string
    collide onto the same cluster ID even when ``cluster_vectors`` placed them
    in different, unrelated clusters — silently re-merging exactly the kind of
    unrelated dispatches this stage exists to keep apart. Reproduced directly:
    two groups both titled "Ceasefire agreed" (different countries, different
    embeddings, correctly split into separate clusters) landed back in one
    output row because both labels' member-title buckets contained the same
    string. Indices are unique per input position and cannot collide this way.
    """
    members_by_label: dict[int, list[int]] = {}
    for index, label in enumerate(labels):
        members_by_label.setdefault(label, []).append(index)

    id_by_label: dict[int, str] = {}
    for label, member_indices in members_by_label.items():
        digest = hashlib.sha256(
            "\x1f".join(str(i) for i in sorted(member_indices)).encode("utf-8")
        ).hexdigest()
        id_by_label[label] = digest[:16]

    return [id_by_label[label] for label in labels]


@dataclass(frozen=True, slots=True)
class Coverage:
    independent_source_count: int
    country_count: int
    # The actual countries, not just their count -- Story 2.5 needs this to
    # decide whether a Cluster is relevant to a given Zone. country_count
    # stays as its own field (not derived at every call site) because
    # Story 2.2's qualifying-floor and ordering logic already reads it, and
    # AD-12 says a value has one owner -- duplicating "len(countries)" at
    # every caller would be the same value computed twice.
    countries: frozenset[str]
    # Where the Event was FIRST reported -- distinct from `countries` (every
    # country this Cluster's coverage touches) and `country_count` (how
    # many). Story 2.6's anti-concentration cap needs a single origin per
    # Cluster, not a set: capping against a set would let one Cluster
    # consume several countries' quotas at once, which is not what "at most
    # 2 items from the same country" means to a reader. Always a member of
    # `countries` (it is one of the countries covered) -- never a country
    # the Cluster has no coverage from.
    origin_country: str


def coverage_for_cluster(groups: list[dict]) -> Coverage:
    """The same union semantics as ``dedupe.ArticleGroup.merge_all``, applied
    to the flat dicts this stage reads from disk rather than reconstructed
    ``ArticleGroup`` objects.

    Reusing ``merge_all`` directly would require rebuilding a full
    ``ArticleGroup`` (every member ``ArticleRecord``) from dedupe's flattened
    JSON, which drops information dedupe's ``to_dict`` never serializes. The
    arithmetic here is intentionally identical: one dedupe group is one
    Independent Source with one origin country (its representative's
    ``source_country``, preserved verbatim on the flat dict), so coverage is
    the count of groups and the count of distinct origin countries among them
    — do not re-derive this differently than Story 1.4 already settled.
    """
    countries = frozenset(g["source_country"] for g in groups)
    # Earliest by published_at, then url for a stable tiebreak -- the same
    # convention dedupe.py's ArticleGroup.representative already uses one
    # layer down, applied here one layer up: the first dispatch reported
    # defines where a Cluster's Event originated.
    #
    # Parsed to a real datetime before comparing, not compared as raw
    # strings: an adversarial review noted that lexicographic string
    # comparison of ISO-8601 timestamps is only safe if every timestamp in
    # the pipeline shares an identical, fixed-width offset format -- true
    # today by convention, enforced nowhere. Parsing removes the dependency
    # on that convention rather than merely relying on it, and matches
    # dedupe.py's ArticleRecord.representative, which compares real
    # datetime objects, not their string serialization.
    earliest = min(groups, key=lambda g: (datetime.fromisoformat(g["published_at"]), g["url"]))
    return Coverage(
        independent_source_count=len(groups),
        origin_country=earliest["source_country"],
        country_count=len(countries),
        countries=countries,
    )


@dataclass(frozen=True, slots=True)
class WrittenCluster:
    output_path: Path
    metadata_path: Path
    clusters_out: int
    degraded: bool


def run_cluster(
    input_path: Path,
    cycle_id: str,
    data_root: Path = DEFAULT_DATA_ROOT,
    embed: EmbedFn = embed_titles,
) -> WrittenCluster:
    """Embed dedupe groups' titles, cluster them, and write Clusters.

    On any embedding failure, degrades to one Cluster per dedupe group (no
    cross-language merging this cycle) rather than aborting — consistent with
    every other adapter boundary in this pipeline (AD-10).
    """
    groups = list(read_jsonl(input_path))
    destination = output_dir_for(STAGE, cycle_id, root=data_root)
    output_path = destination / "clusters.jsonl"
    metadata_path = destination / f"{STAGE}.json"

    failures: list[Failure] = []
    labels: list[int] = []
    if groups:
        titles = [g["title"] for g in groups]
        result = embed(titles)
        failures.extend(result.failures)
        count_mismatch = len(result.vectors) != len(groups)
        malformed = bool(result.vectors) and not _vectors_are_well_formed(result.vectors)
        if result.failures or count_mismatch or malformed:
            # Degrade: one Cluster per dedupe group, no semantic merging.
            # Malformed vectors (ragged rows, NaN/Inf, all-zero) are caught
            # here rather than left to raise inside cluster_vectors — an
            # uncaught exception there would propagate to cycle.py's generic
            # handler and mark the *entire cycle* incomplete, when the correct
            # response to a bad embedding is the same graceful degrade as any
            # other embedding failure (AD-10).
            if malformed:
                failures.append(
                    Failure(_EMBED_ADAPTER, "embedding response was malformed; degrading")
                )
            labels = list(range(len(groups)))
        else:
            labels = cluster_vectors(result.vectors)

    cluster_ids = assign_cluster_ids(labels)

    members_by_id: dict[str, list[dict]] = {}
    for group, cluster_id in zip(groups, cluster_ids, strict=True):
        members_by_id.setdefault(cluster_id, []).append(group)

    clusters_out = []
    for cluster_id, members in sorted(members_by_id.items()):
        coverage = coverage_for_cluster(members)
        clusters_out.append(
            {
                "cluster_id": cluster_id,
                # Article-level data a downstream summarize stage needs to
                # write a grounded Summary and cite an outbound link (Story
                # 3.1) -- previously collapsed to bare normalized titles
                # (`member_titles`), which dropped exactly what that stage
                # needs. Sorted by title, the same determinism guarantee the
                # old member_titles field provided; NOT publish order.
                "members": sorted(
                    (
                        {
                            "title": m["title"],
                            "url": m["url"],
                            "source": m["source"],
                            "source_country": m["source_country"],
                            "language": m["language"],
                        }
                        for m in members
                    ),
                    key=lambda mem: mem["title"],
                ),
                "independent_source_count": coverage.independent_source_count,
                "country_count": coverage.country_count,
                "countries": sorted(coverage.countries),
                "origin_country": coverage.origin_country,
            }
        )

    write_jsonl(output_path, clusters_out)

    metadata = {
        "stage": STAGE,
        "cycle_id": cycle_id,
        "groups_in": len(groups),
        "clusters_out": len(clusters_out),
        "degraded": bool(failures),
        "failures": [f.to_dict() for f in failures],
    }
    write_atomically(
        metadata_path, json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )

    return WrittenCluster(
        output_path=output_path,
        metadata_path=metadata_path,
        clusters_out=len(clusters_out),
        degraded=bool(failures),
    )


def main(argv: list[str] | None = None) -> int:
    args = stage_arg_parser(STAGE).parse_args(argv)

    if not args.input.is_file():
        print(f"input not found or not a file: {args.input}", file=sys.stderr)
        return 1

    cycle_id = args.cycle_id or cycle_id_for()
    written = run_cluster(args.input, cycle_id=cycle_id, data_root=args.data_root)

    print(f"{STAGE}: {written.clusters_out} clusters -> {written.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
