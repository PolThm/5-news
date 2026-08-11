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
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path

from pipeline.domain import ArticleRecord
from pipeline.stages import (
    DEFAULT_DATA_ROOT,
    cycle_id_for,
    output_dir_for,
    read_jsonl,
    stage_arg_parser,
    write_atomically,
    write_jsonl,
)

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
    required specifically to avoid a third occurrence.

    Merging requires every pair within a cluster to directly clear both
    signals — a clique, not a connected component. An adversarial review of
    the first version of this function found that comparing every candidate
    only against the *first* group encountered let a chain of individually-
    passing pairs (A-B similar, B-C similar, A-C not) fold C into A's cluster
    anyway — the single-linkage chaining bug this docstring already claimed
    to defend against, reintroduced by a different path. A plain connected-
    components graph (Story 2.1's own fix for the same bug in the cluster
    stage) has the identical weakness here: A-B and B-C edges alone connect
    all three even when A-C never qualifies. Requiring every pair in the
    final group to pass, not just an edge to some member, closes that gap for
    real rather than moving it one hop over.

    A group with no recognized agency attribution (the common case — GDELT
    articles, and RSS articles from feeds like BBC's that never populate
    ``dc:creator``) is left untouched; this is not a failure (AC3).
    """
    n = len(groups)

    agencies_by_index: dict[int, frozenset[str]] = {}
    for i in range(n):
        agencies = _agencies_in(groups[i])
        if agencies and len(groups[i].normalized_title) >= _AGENCY_MERGE_MIN_TITLE_LENGTH:
            agencies_by_index[i] = agencies

    # Every directly-qualifying pair, computed once: shared agency AND
    # SequenceMatcher.ratio() over the floor. "Directly" is the whole point
    # — nothing here ever infers a merge from two other merges.
    qualifies: set[tuple[int, int]] = set()
    for i in agencies_by_index:
        for j in agencies_by_index:
            if j <= i or not (agencies_by_index[i] & agencies_by_index[j]):
                continue
            similarity = SequenceMatcher(
                None, groups[i].normalized_title, groups[j].normalized_title
            ).ratio()
            if similarity >= _AGENCY_MERGE_SIMILARITY_FLOOR:
                qualifies.add((i, j))

    def directly_qualifies(a: int, b: int) -> bool:
        return a == b or (min(a, b), max(a, b)) in qualifies

    # A cluster is valid only if every pair inside it directly qualifies — a
    # clique, not a connected component. Built greedily: start from each
    # unclaimed group and absorb every remaining candidate that directly
    # qualifies against *every* member already in the cluster, in
    # descending-similarity order so the strongest matches are tried first.
    # This is not a general maximum-clique solver — it does not need to be:
    # the input is a handful of same-day, same-agency dedupe groups, and a
    # merge left too conservative here (a group that could have joined but
    # didn't, because a stronger candidate claimed a slot first) only costs
    # a missed collapse, never a false one, which is the one-sided error
    # this whole layer is designed to prefer.
    claimed: set[int] = set()
    clusters: list[list[int]] = []

    for i in sorted(agencies_by_index):
        if i in claimed:
            continue
        cluster = [i]
        candidates = sorted(
            (j for j in agencies_by_index if j != i and j not in claimed),
            key=lambda j: SequenceMatcher(
                None, groups[i].normalized_title, groups[j].normalized_title
            ).ratio(),
            reverse=True,
        )
        for j in candidates:
            if all(directly_qualifies(j, member) for member in cluster):
                cluster.append(j)
        claimed.update(cluster)
        clusters.append(cluster)

    clustered_indices = {index for cluster in clusters for index in cluster}
    for i in range(n):
        if i not in clustered_indices:
            clusters.append([i])

    merged: list[ArticleGroup] = []
    for cluster in sorted(clusters, key=min):
        cluster_articles: list[ArticleRecord] = []
        for index in cluster:
            cluster_articles.extend(groups[index].articles)
        anchor = groups[min(cluster)]
        merged.append(
            replace(
                anchor,
                articles=tuple(sorted(cluster_articles, key=lambda a: (a.published_at, a.url))),
                formed_by="agency" if len(cluster) > 1 else "title",
            )
        )

    return merged


@dataclass(frozen=True, slots=True)
class WrittenDedupe:
    output_path: Path
    metadata_path: Path
    groups_out: int


def run_dedupe(
    input_path: Path,
    cycle_id: str,
    data_root: Path = DEFAULT_DATA_ROOT,
) -> WrittenDedupe:
    """Collapse verbatim reprints and write the counts everything downstream
    will use."""
    records = [ArticleRecord.from_dict(row) for row in read_jsonl(input_path)]
    groups = merge_by_agency(group_by_title(records))

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
