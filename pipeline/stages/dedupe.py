"""Dedupe stage: Syndication Detection, layer 1 — collapse verbatim reprints.

The single most consequential stage in the pipeline, because the number it
produces does two jobs at once: it is the ranking input *and* the proof shown
to the reader ("covered by 34 independent sources across 12 countries"). Wire
copy inflating that number breaks the ranking and the trust artifact
simultaneously, and the reader cannot tell.

A Reuters dispatch republished under an identical headline by thirty outlets is
one story covered once. Thirty newsrooms independently judging a story worth
covering is something else entirely, and the whole product rests on
distinguishing the two.

**This stage is the only place that decides what an Independent Source is.**
Downstream stages consume its verdict and never recount (AD-5, AD-12).

Layer 1 only: exact-after-normalization title matching. It catches verbatim
reprints, which the brief identifies as the bulk of the noise, and it is cheap
enough to run from day one of the inspection window. Layers 2 (wire attribution
metadata) and 3 (rewrite detection) arrive in Stories 2.3 and 2.4 — deliberately
after there is real output to tune them against.

The layer errs toward *under*-collapsing. Wrongly merging two independently
reported stories understates real consensus, which is the same class of error
in the opposite direction, and harder to notice.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from sklearn.neighbors import radius_neighbors_graph
from sklearn.preprocessing import normalize

from pipeline.adapters.cohere_embed import EmbeddingResult, embed_titles
from pipeline.config import REWRITE_SIMILARITY_FLOOR
from pipeline.domain import ArticleRecord
from pipeline.stages import (
    DEFAULT_DATA_ROOT,
    clique_partition,
    cycle_id_for,
    output_dir_for,
    read_jsonl,
    stage_arg_parser,
    trace,
    write_atomically,
    write_jsonl,
)

# embed_titles's real signature also takes an optional `client` for
# injection; this alias only describes the single-argument shape every call
# site here actually uses, mirroring cluster.py's identical alias.
EmbedFn = Callable[[list[str]], EmbeddingResult]

STAGE = "dedupe"

# Outlets append their own name to syndicated headlines ("... | Reuters",
# "... - BBC News"). Stripping it lets the same dispatch match across
# republishers.
#
# Matched against a KNOWN LIST rather than a shape, because shape alone cannot
# distinguish a republisher's brand from a real headline tail. Wire headlines
# routinely end in an attribution that IS the story:
#
#     "Ukraine strikes back - Zelensky"     <- attribution, must survive
#     "Death toll rises - UN"               <- attribution, must survive
#     "Ceasefire agreed - Reuters"          <- branding, should go
#
# A "capitalized words after a dash" rule eats all three, merging genuinely
# different dispatches. Over-stripping corrupts the Consensus Score — the
# number shown to the reader as proof — while under-stripping only costs a
# missed collapse. The asymmetry decides the design: match what we recognize,
# leave everything else alone.
#
# Separator handling is deliberately permissive about spacing and case, because
# "agreed-Reuters" and "agreed | reuters" are the same dispatch as
# "agreed - Reuters" and must land in the same group.
_KNOWN_OUTLETS = (
    "reuters",
    "ap",
    "associated press",
    "afp",
    "bloomberg",
    "bbc",
    "bbc news",
    "cnn",
    "the guardian",
    "guardian",
    "the times",
    "nyt",
    "the new york times",
    "wsj",
    "the washington post",
    "washington post",
    "npr",
    "pbs",
    "sky news",
    "al jazeera",
    "dw",
    "france 24",
    "rfi",
    "le monde",
    "le figaro",
    "liberation",
    "el pais",
    "el mundo",
    "der spiegel",
    "spiegel",
    "die welt",
    "faz",
    "the japan times",
    "nhk",
    "kyodo",
    "scmp",
    "xinhua",
    "ndtv",
    "the hindu",
    "times of india",
    "globo",
    "folha",
    "efe",
    "ansa",
    "pa media",
    "pti",
    "ians",
)
_OUTLET_SUFFIX = re.compile(
    r"\s*[|•·–—]\s*(?:" + "|".join(re.escape(o) for o in _KNOWN_OUTLETS) + r")\s*$"
    r"|\s*-\s*(?:" + "|".join(re.escape(o) for o in _KNOWN_OUTLETS) + r")\s*$",
    flags=re.IGNORECASE,
)

_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """Reduce a headline to what two outlets running the same wire copy share.

    Case, punctuation, spacing, and a trailing outlet suffix all vary between
    republishers of an identical dispatch. Accents are preserved — they carry
    meaning in French, Spanish, and German headlines, and stripping them would
    merge genuinely different words.
    """
    text = unicodedata.normalize("NFC", title).strip()
    text = _OUTLET_SUFFIX.sub("", text)
    text = _PUNCTUATION.sub(" ", text)
    text = _WHITESPACE.sub(" ", text)
    return text.casefold().strip()


@dataclass(frozen=True, slots=True)
class ArticleGroup:
    """Articles that share a normalized headline — one story, however many
    outlets ran it.

    ``independent_source_count`` is the number of *distinct sources*, not the
    number of articles: an outlet republishing its own piece twice is still one
    source.
    """

    normalized_title: str
    articles: tuple[ArticleRecord, ...]
    # Which mechanism formed this group: "title" (layer 1, Story 1.4) or
    # "agency" (layer 2, Story 2.3). Recorded on the output so a change in
    # grouping introduced by this layer is inspectable by diffing
    # groups.jsonl, not a silent difference in composition (AC4).
    formed_by: str = "title"

    @property
    def sources(self) -> frozenset[str]:
        return frozenset(a.source for a in self.articles)

    @property
    def countries(self) -> frozenset[str]:
        return frozenset(a.source_country for a in self.articles)

    @property
    def mentioned_countries(self) -> frozenset[str]:
        """Every country any Article in this group is *about*.

        Unioned across the group rather than read off the representative:
        which member happens to sort first is arbitrary, and an Article that
        located the story should not lose that just because another member
        did not. Distinct from `countries`, which is where the outlets sit.
        """
        return frozenset(country for a in self.articles for country in a.mentioned_countries)

    @property
    def independent_source_count(self) -> int:
        """One, by definition of this layer.

        Every Article in this group shares a normalized headline, which is what
        layer 1 treats as evidence of a single dispatch republished. The PRD is
        explicit: an Independent Source is "a Source whose Article is not a
        republication of another Source's dispatch". Six outlets running the
        same wire headline are one dispatch, not six confirmations — counting
        distinct sources here would reintroduce exactly the inflation this
        stage exists to remove.

        Genuinely independent reporting produces genuinely different headlines,
        lands in different groups, and is counted separately. That is the whole
        mechanism.
        """
        return 1

    @property
    def country_count(self) -> int:
        """One, for the same reason.

        A single dispatch republished across twelve countries is not
        twelve-country consensus — and "covered in 12 countries" is precisely
        the claim the reader is shown as proof.
        """
        return 1

    @property
    def representative(self) -> ArticleRecord:
        """The article that stands for the group.

        Earliest by publication time, then by URL for a stable tiebreak — the
        first outlet to run a dispatch is the most defensible representative,
        and determinism matters more than the choice itself.
        """
        return min(self.articles, key=lambda a: (a.published_at, a.url))

    @property
    def origin_country(self) -> str:
        """Where this dispatch originated: the earliest publisher's country.

        One country per dispatch. Not "every country that republished it" —
        that is the inflation this stage removes — and not a stand-in for the
        others either: when several *distinct* dispatches describe one Event,
        it is these origin countries, unioned, that make up real geographic
        consensus.
        """
        return self.representative.source_country

    def to_dict(self) -> dict[str, object]:
        record = self.representative
        return {
            **record.to_dict(),
            "normalized_title": self.normalized_title,
            "independent_source_count": self.independent_source_count,
            "country_count": self.country_count,
            "sources": sorted(self.sources),
            "countries": sorted(self.countries),
            # Explicit, overriding the representative's own value that arrives
            # via `**record.to_dict()` above -- this is the whole group's.
            "mentioned_countries": sorted(self.mentioned_countries),
            "article_count": len(self.articles),
            "formed_by": self.formed_by,
        }

    @staticmethod
    def merge_all(groups: list[ArticleGroup]) -> Coverage:
        """Aggregate several distinct groups into one coverage measure.

        Each group is one dispatch, so the counts here are over *groups*, not
        over articles: three distinct stories from three countries is
        three-source, three-country coverage. This is what the cluster and rank
        stages will consume once an Event spans several distinct dispatches.
        """
        return Coverage(
            independent_source_count=len(groups),
            # The PRD defines the country count as "the count of distinct
            # countries AMONG the Independent Sources". One dispatch is one
            # Independent Source with one origin country, so this is the union
            # of origin countries — one per dispatch.
            #
            # Both neighbouring readings are wrong, in opposite directions:
            # unioning every republisher's country reinflates exactly what this
            # stage removes, while collapsing to a single country understates
            # genuine multi-country coverage. Two French dispatches really are
            # one country; a French and a German dispatch really are two.
            country_count=len({g.origin_country for g in groups}),
        )


@dataclass(frozen=True, slots=True)
class Coverage:
    """Consensus measured across distinct dispatches.

    One ``ArticleGroup`` is one dispatch and therefore always counts as one
    Independent Source. Coverage is what you get when several *different*
    dispatches describe the same Event — that is real consensus, and it is what
    the Consensus Score is built from.
    """

    independent_source_count: int
    country_count: int


def group_by_title(records: list[ArticleRecord]) -> list[ArticleGroup]:
    """Group Articles by normalized headline.

    Output order is by normalized title, not input order: the intermediate
    files are diffed between cycles by hand, and ordering that follows input
    would make every diff noise.
    """
    buckets: dict[str, list[ArticleRecord]] = {}
    for record in records:
        buckets.setdefault(normalize_title(record.title), []).append(record)

    return [
        ArticleGroup(
            normalized_title=title,
            articles=tuple(sorted(articles, key=lambda a: (a.published_at, a.url))),
        )
        for title, articles in sorted(buckets.items())
    ]


# Below this ratio, two titles are not treated as the same dispatch even if
# they share an agency attribution. difflib's SequenceMatcher.ratio() is
# stdlib, needs no new dependency, and is symmetric — good enough for "is
# this plausibly the same headline, lightly edited" without importing an
# NLP library for what is fundamentally a corroborating check, not the
# primary signal (title normalization, layer 1, already did the heavy
# lifting; this only catches near-misses that share an agency).
_AGENCY_MERGE_SIMILARITY_FLOOR = 0.6

# SequenceMatcher.ratio() on short strings is dominated by character overlap
# rather than semantic similarity — verified directly: "un dead" vs. "un
# lead" scores 0.857, comfortably above the floor, despite describing
# opposite outcomes. Below this length, similarity alone is not trustworthy
# enough to corroborate an agency match; the pair is left unmerged rather
# than risk a false merge on a coincidence of short, similar-looking words.
_AGENCY_MERGE_MIN_TITLE_LENGTH = 20

# Applied to rewrite detection too, defensively rather than on verified
# evidence: semantic embeddings are not character-overlap algorithms and are
# not expected to share SequenceMatcher's specific short-string failure mode
# (no live Cohere call was available to confirm this directly — see Story
# 2.4's Dev Notes). Given this layer has no second corroborating signal at
# all, the cost of being wrong about that assumption is high enough that a
# free, zero-evidence floor is worth keeping anyway.
_REWRITE_MERGE_MIN_TITLE_LENGTH = _AGENCY_MERGE_MIN_TITLE_LENGTH


def _agencies_in(group: ArticleGroup) -> frozenset[str]:
    """Every recognized wire-service attribution present anywhere in the
    group, not just its representative.

    A title-normalization group can mix an attributed and an unattributed
    Article under the identical headline (one republisher's feed populates
    ``dc:creator``, another's doesn't) — an adversarial review found that
    reading only ``representative.wire_agency`` made a group's visibility to
    this layer depend on which member happened to publish earliest, an
    accident unrelated to whether the attribution evidence actually exists.
    """
    return frozenset(a.wire_agency for a in group.articles if a.wire_agency is not None)


def _clique_merge(
    groups: list[ArticleGroup],
    eligible: Callable[[int], bool],
    directly_qualifies: Callable[[int, int], bool],
    similarity: Callable[[int, int], float],
    formed_by: str,
    candidates_of: Callable[[int], Iterable[int]] | None = None,
) -> list[ArticleGroup]:
    """Merge ``ArticleGroup``s into cliques under an arbitrary pairwise
    qualification rule, using ``pipeline.stages.clique_partition`` for the
    index-level mechanism shared by every Syndication Detection layer past
    layer 1 (see that function's docstring for why cliques, not connected
    components).
    """
    cliques = clique_partition(
        len(groups), eligible, directly_qualifies, similarity, candidates_of=candidates_of
    )

    merged: list[ArticleGroup] = []
    for clique in cliques:
        cluster_articles: list[ArticleRecord] = []
        for index in clique:
            cluster_articles.extend(groups[index].articles)
        anchor = groups[min(clique)]
        merged.append(
            replace(
                anchor,
                articles=tuple(sorted(cluster_articles, key=lambda a: (a.published_at, a.url))),
                formed_by=formed_by if len(clique) > 1 else anchor.formed_by,
            )
        )

    return merged


def merge_by_agency(groups: list[ArticleGroup]) -> list[ArticleGroup]:
    """Layer 2 (FR-10, Story 2.3): merge separate title-normalization groups
    that share a recognized wire-service attribution AND a similar-enough
    title — corroborating evidence that a near-miss on title normalization
    (translation, local editing) is still one dispatch.

    Agency alone is deliberately never sufficient. Two different Reuters
    stories published the same day share ``wire_agency="Reuters"`` but are
    not the same Event — merging on that alone would silently inflate
    ``independent_source_count`` for unrelated stories, the same class of
    false-merge bug an adversarial review caught twice in Story 2.1
    (HDBSCAN chaining, then a cluster-ID hash collision). Both signals are
    required specifically to avoid a third occurrence. See ``_clique_merge``
    for how the merge itself avoids transitive false-chaining.

    A group with no recognized agency attribution (the common case — GDELT
    articles, and RSS articles from feeds like BBC's that never populate
    ``dc:creator``) is left untouched; this is not a failure (AC3).
    """
    agencies_by_index: dict[int, frozenset[str]] = {}
    for i, group in enumerate(groups):
        agencies = _agencies_in(group)
        if agencies and len(group.normalized_title) >= _AGENCY_MERGE_MIN_TITLE_LENGTH:
            agencies_by_index[i] = agencies

    def title_similarity(i: int, j: int) -> float:
        return SequenceMatcher(None, groups[i].normalized_title, groups[j].normalized_title).ratio()

    def directly_qualifies(i: int, j: int) -> bool:
        if i not in agencies_by_index or j not in agencies_by_index:
            return False
        if not (agencies_by_index[i] & agencies_by_index[j]):
            return False
        return title_similarity(i, j) >= _AGENCY_MERGE_SIMILARITY_FLOOR

    return _clique_merge(
        groups,
        eligible=lambda i: i in agencies_by_index,
        directly_qualifies=directly_qualifies,
        similarity=title_similarity,
        formed_by="agency",
    )


def _vectors_are_well_formed(vectors: list[list[float]]) -> bool:
    """Same guard as ``pipeline.stages.cluster``'s helper of the same name,
    duplicated rather than imported: importing from ``cluster`` here would
    point a dependency backward across the pipeline's own stage order
    (cluster runs after dedupe), and the check is small enough that the
    duplication costs less than the layering violation would.

    **Keep this in sync with ``pipeline.stages.cluster._vectors_are_well_formed``
    by hand.** An adversarial review found the two copies' call sites had
    already drifted — one guarded unconditionally, the other only when
    ``result.vectors`` was non-empty — even though both copies of this
    function's body were still identical. There is no test enforcing parity
    between the two files; if this function's logic ever needs to change,
    change both.

    Rejects a malformed vendor response (ragged rows, NaN/Inf, all-zero)
    before it reaches ``cosine``/``normalize``, which would otherwise either
    raise (escalating to a whole-cycle failure) or silently produce a
    meaningless distance of 0 between two all-zero vectors.
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


def merge_by_rewrite_detection(
    groups: list[ArticleGroup],
    embed: EmbedFn = embed_titles,
    return_degraded: bool = False,
) -> list[ArticleGroup] | tuple[list[ArticleGroup], str | None]:
    """Layer 3 (FR-10, Story 2.4): merge groups whose representative titles
    are close enough, by embedding, to be the same dispatch reworded rather
    than two independent reports of the same Event.

    **Deliberately built before the Build Order's prescribed inspection
    window closed** — see Story 2.4's Dev Notes for the explicit decision
    and its reasoning. ``pipeline.config.REWRITE_SIMILARITY_FLOOR`` is a
    starting hypothesis, not a measured constant; treat any surprising
    behavior here as a config-value question first, not a bug report.

    This layer has no second corroborating signal the way layer 2 does
    (shared agency attribution) — semantic similarity via embedding is the
    only evidence available, which is exactly why the threshold is
    deliberately stricter than ``pipeline.stages.cluster``'s
    ``_SAME_EVENT_DISTANCE``. That constant answers "same real-world Event"
    (a question where two Independent Sources both counting is the *desired*
    outcome); this threshold answers "same dispatch, reworded" (where two
    Independent Sources collapsing into one would silently erase real
    coverage). Reusing the looser constant here would be a correctness bug,
    not a simplification.

    On any embedding failure, this layer's merge is skipped for the cycle —
    the input groups pass through unchanged, matching every other adapter
    boundary in this pipeline (AD-10). ``return_degraded`` exposes *why*, not
    just whether, that happened — an adversarial review found a bare boolean
    collapsed three distinct failure modes (the embed call itself failing,
    a malformed response, a vector-count mismatch) into one flag, losing the
    detail ``cluster.py`` already records for the same three cases. Callers
    that don't need it can ignore the second element by leaving
    ``return_degraded`` at its default ``False`` and taking the plain list.
    """
    if not groups:
        return (groups, None) if return_degraded else groups

    titles = [group.representative.title for group in groups]
    result = embed(titles)

    reason: str | None = None
    if result.failures:
        detail = "; ".join(f.detail for f in result.failures)
        reason = f"embedding request failed: {detail}"
    elif len(result.vectors) != len(groups):
        reason = f"embedding returned {len(result.vectors)} vectors for {len(groups)} groups"
    elif result.vectors and not _vectors_are_well_formed(result.vectors):
        reason = "embedding response was malformed"

    if reason is not None:
        return (groups, reason) if return_degraded else groups

    unit_vectors = normalize(np.asarray(result.vectors, dtype=float), copy=True)

    # Which pairs fall within REWRITE_SIMILARITY_FLOOR, resolved in one
    # vectorized neighbor search rather than a scipy `cosine` call per pair.
    #
    # This layer sets `eligible=lambda _i: True`, so clique_partition asks
    # about O(n^2) pairs. Per-pair Python metric calls were fine at the RSS
    # corpus's ~350 titles; at Story 6.2's ~9,400 GDELT groups they became
    # tens of millions of scipy round-trips and pushed the cycle past its
    # 30-minute job timeout three runs in a row. `radius_neighbors_graph`
    # does the same comparison in chunked BLAS and answers in seconds.
    #
    # `mode="connectivity"`, not `"distance"`: a distance-mode graph cannot
    # represent a genuinely identical pair (distance exactly 0) as anything
    # but a structural zero, so two identical titles would silently drop out
    # of their own neighbor set -- the same trap cluster.py's
    # `fill_diagonal` comment guards against. Connectivity stores 1.0 for
    # every in-radius neighbor regardless of distance.
    #
    # sklearn's radius search is inclusive (`<= radius`), matching the
    # comparison this replaces exactly.
    trace(f"layer3: neighbor search over {len(groups)} groups")
    neighbor_rows = (
        radius_neighbors_graph(
            unit_vectors,
            radius=REWRITE_SIMILARITY_FLOOR,
            metric="cosine",
            mode="connectivity",
            include_self=False,
        )
        .tolil()
        .rows
    )
    neighbors_of: list[set[int]] = [set(row) for row in neighbor_rows]
    trace(f"layer3: {sum(len(n) for n in neighbors_of) // 2} in-radius pairs; partitioning")

    def cosine_similarity(i: int, j: int) -> float:
        # 1 - cosine distance; higher means more similar, matching the other
        # merge layers' "similarity" convention despite the underlying metric
        # being a distance. For unit-normalized vectors that is exactly the
        # dot product, so this stays a two-vector operation -- and, with
        # clique_partition now filtering before it ranks, it is only ever
        # asked about pairs already known to qualify.
        return float(unit_vectors[i] @ unit_vectors[j])

    def directly_qualifies(i: int, j: int) -> bool:
        # `titles` above, not `groups[i].representative.title`: that is a
        # property recomputing a `min()` over the group's articles on every
        # access, and this runs once per candidate pair.
        if (
            len(titles[i]) < _REWRITE_MERGE_MIN_TITLE_LENGTH
            or len(titles[j]) < _REWRITE_MERGE_MIN_TITLE_LENGTH
        ):
            return False
        return j in neighbors_of[i]

    merged = _clique_merge(
        groups,
        eligible=lambda _i: True,
        directly_qualifies=directly_qualifies,
        similarity=cosine_similarity,
        formed_by="rewrite",
        candidates_of=lambda i: neighbors_of[i],
    )
    trace(f"layer3: done -> {len(merged)} groups")
    return (merged, None) if return_degraded else merged


@dataclass(frozen=True, slots=True)
class WrittenDedupe:
    output_path: Path
    metadata_path: Path
    groups_out: int


def run_dedupe(
    input_path: Path,
    cycle_id: str,
    data_root: Path = DEFAULT_DATA_ROOT,
    embed: EmbedFn = embed_titles,
) -> WrittenDedupe:
    """Collapse verbatim reprints and write the counts everything downstream
    will use.

    Three layers, in order: title normalization (Story 1.4), agency
    attribution (Story 2.3), then embedding-based rewrite detection (Story
    2.4). Each layer only sees what the ones before it left unmerged.
    """
    records = [ArticleRecord.from_dict(row) for row in read_jsonl(input_path)]
    after_title_and_agency = merge_by_agency(group_by_title(records))
    groups, rewrite_degraded_reason = merge_by_rewrite_detection(
        after_title_and_agency, embed=embed, return_degraded=True
    )

    destination = output_dir_for(STAGE, cycle_id, root=data_root)
    output_path = destination / "groups.jsonl"
    metadata_path = destination / f"{STAGE}.json"

    write_jsonl(output_path, [group.to_dict() for group in groups])

    metadata = {
        "stage": STAGE,
        "cycle_id": cycle_id,
        "articles_in": len(records),
        "groups_out": len(groups),
        # How much inflation this layer removed. During the inspection window
        # this ratio is the evidence the layer is doing anything at all.
        "collapsed": len(records) - len(groups),
        # None when layer 3 ran normally; otherwise the specific reason it
        # was skipped (embed call failed, malformed response, or a vector
        # count mismatch) rather than a bare boolean losing that detail.
        "rewrite_detection_degraded": rewrite_degraded_reason,
    }
    write_atomically(
        metadata_path, json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )

    return WrittenDedupe(
        output_path=output_path,
        metadata_path=metadata_path,
        groups_out=len(groups),
    )


def main(argv: list[str] | None = None) -> int:
    args = stage_arg_parser(STAGE).parse_args(argv)

    if not args.input.is_file():
        print(f"input not found or not a file: {args.input}", file=sys.stderr)
        return 1

    cycle_id = args.cycle_id or cycle_id_for()
    written = run_dedupe(args.input, cycle_id=cycle_id, data_root=args.data_root)

    print(f"{STAGE}: {written.groups_out} groups -> {written.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
