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
from dataclasses import dataclass
from pathlib import Path

from pipeline.domain import ArticleRecord
from pipeline.stages import (
    DEFAULT_DATA_ROOT,
    cycle_id_for,
    output_dir_for,
    read_jsonl,
    stage_arg_parser,
    write_jsonl,
)

STAGE = "dedupe"

# Outlets append their own name to syndicated headlines ("... | Reuters",
# "... - BBC News"). Stripping it lets the same dispatch match across
# republishers.
#
# Deliberately narrow: at most three words, each capitalized or an acronym.
# A greedy "everything after a dash" rule would also eat real headline tails
# like "— sources say", merging genuinely different headlines. Under-stripping
# costs a missed collapse; over-stripping corrupts the Consensus Score, which
# is the number the reader is shown as proof.
_OUTLET_SUFFIX = re.compile(
    r"\s*[|–—]\s*(?:[A-Z][\w.&']*\s*){1,3}$|\s+-\s+(?:[A-Z][\w.&']*\s*){1,3}$"
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
            # The representative's country, one per group — NOT every country
            # the group's articles came from. A single dispatch republished
            # across eight countries is one dispatch from one country; folding
            # in every republisher's country would reintroduce exactly the
            # inflation this stage removes, one level up.
            country_count=len({g.representative.source_country for g in groups}),
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
    groups = group_by_title(records)

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
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
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
