"""Subject stage: what the serious press is covering, and how widely.

This stage decides what a Briefing is *about*. It replaces two earlier answers,
both of which were measured and found wanting.

**The Consensus Score alone** (Story 3.x) ranked by how many outlets reran a
dispatch. Measured on real output, that published a ZZ Top drummer's death and a
Belgian construction firm's revenue while the same cycle's corpus held almost
none of the events human editors recorded.

**The Wikipedia chronicle as the spine** (the agenda stage) fixed the editorial
judgment and introduced a different flaw: the Current Events portal records
*incidents* -- a helicopter crashed, a hotel burned, a mine collapsed. So the
output read like a wire ticker while 170 articles about Iran and the Strait of
Hormuz sat unused in the same corpus.

The reason neither worked is that nothing was forming *subjects*. The cluster
stage groups same-Event articles at a threshold of 0.28 cosine distance, which
is a near-duplicate threshold whatever its name says. Measured on the 2026-08-20
corpus it admitted 1.2% of the pairs among 49 articles about Ceuta, so those 49
fragmented into some 45 clusters, none of which weighed anything. Loosening the
threshold is not available: within-subject distances (p25 0.95-1.14 euclidean)
and between-subject distances (p5 1.18-1.30) leave a band too thin to sit a
threshold in without collapsing the corpus into one component.

What separates Ceuta from Hormuz is not proximity. It is that every one of those
articles names Ceuta. So subjects are keyed on names -- and the names come from
the reference press, not from GDELT.

**Why the reference press supplies the vocabulary.** GDELT publishes structured
entities per article, and reading them was the obvious approach. Measured, it
does not work: of six subjects the day's serious press led with, GDELT's entity
fields carried one. Ceuta, Hind Rajab, Iran and Ukraine came back empty, while
"Tehran" had 51 GDELT sources and no reference newsroom at all -- the serious
press writes "Iran" and "Téhéran". GDELT's vocabulary is canonical English; a
French and Spanish press review needs the vocabulary its own sources use.

So: the reference press decides *what is a subject* and *how much it matters*
(how many independent newsrooms lead with it), and GDELT supplies *breadth*
(how many sources and countries corroborate it). That is the division the
project asked for from the start -- serious sources deciding, volume
corroborating -- and it is the first version where the two are not confused.

Output is Cluster-shaped, written to
``data/intermediate/subject/<cycle-id>/items.jsonl``, so rank, summarize and
publish need no knowledge of where an item came from (AD-13).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.preprocessing import normalize

from pipeline.config import source_trust_tier
from pipeline.stages import (
    DEFAULT_DATA_ROOT,
    output_dir_for,
    trace,
    write_atomically,
    write_jsonl,
)

STAGE = "subject"

# How many distinct reference newsrooms must lead with a name before it is a
# subject at all.
#
# This is the editorial floor, and it is doing the work a stoplist would
# otherwise have to. Measured on 2026-08-20: "United States" was named by 187
# GDELT sources and one reference newsroom, while Ceuta was named by nine
# newsrooms. A name that the serious press does not put in a headline is not a
# subject however much wire volume mentions it, and three independent newsrooms
# is the smallest number that cannot be one outlet's preoccupation.
MIN_REFERENCE_NEWSROOMS = 3

# Two candidate names are one subject when their article sets coincide this
# much, as a Jaccard ratio -- shared over union.
#
# Jaccard, not "this share of the smaller set also belongs to the larger", which
# is what this was first written as. Measured, that rule let "Trump" absorb
# "Canada" and "Coree": a candidate with three articles, two of which also
# mention Trump, is two-thirds contained and merged, and the subject came out
# with 136 sources across 39 countries -- everything Trump was mentioned in.
# Against the union those same sets score 0.02 and stay apart, while "Harry" and
# "Meghan", which are genuinely the same story, score high and merge.
#
# Language and spelling still split a subject that names decide -- "Kiev" and
# "Kyiv" share no articles at all -- which is what the centroid rule below is
# for. Names cannot do that half, and embeddings cannot do subjects.
MERGE_OVERLAP = 0.40

# How close two candidates' article centroids must sit, in euclidean distance on
# unit vectors, before the nearest-neighbour rule merges them.
#
# Chosen by measuring three values on the 2026-08-20 corpus. At 1.10 "Colombia"
# reached Kenya, Ecuador, Congo and Ebola; at 1.05 "China" pulled in "India". At
# 0.95 the merges are the ones names could not make -- "China" with "Chine" and
# "Chinese", "Gaza" with "Israel" and "Israeli", "Ukraine" with "Zelensky" --
# and the subjects that should stay apart do: Hind Rajab, Ceuta, Evergrande and
# Kim Jong-un each remain their own.
#
# Set against the same corpus's between-subject floor of 1.18 euclidean, so this
# sits comfortably inside it rather than at its edge.
CENTROID_DISTANCE = 0.95

# A capitalized word is not a proper noun when it merely starts a sentence, and
# a headline is one sentence. Function words that can open a headline in the
# three output languages plus English (GDELT's own), and the wire-desk
# furniture the reference feeds prefix titles with.
_STOPWORD_TEXT = """
le la les des du de un une et en dans pour par sur avec au aux ce cette cet ces
il elle ils elles on ne pas plus que qui quoi dont ou mais donc or ni car son sa
ses leur leurs nos notre votre tout tous toute toutes apres avant ainsi alors
comment pourquoi quand depuis entre vers sans sous contre chez deja encore aussi
the of to in for on with at by from as is are was were be been being has have
had not and or but so if it its this that these those what why how when where
who which will would can could should may might there here about after before
el los las una y con por para del al se su sus como mas pero no lo ya muy este
esta estos estas cuando donde porque quien cual sobre entre hasta desde
direct video podcast tribune entretien analyse reportage recit carte chronique
edito editorial live blog opinion interview exclusif enquete decryptage vrai
faux infographie temoignage portrait serie episode saison partie chapitre
nord sud est ouest ans annees ete fait faire etre avoir dit dire selon
un uno dos tres cuatro cinco deux trois quatre cinq six sept huit neuf dix
"""
_STOPWORDS = _STOPWORD_TEXT.split()


def fold(text: str) -> str:
    """Casefold and strip diacritics, so one subject has one key.

    "Téhéran" and "Teheran" are the same name and must not be two subjects.
    Applied to both the vocabulary and the titles it is matched against, so the
    comparison is symmetric.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


_STOP = frozenset(fold(w) for w in _STOPWORDS)

# One or two capitalized words. Two because a person is "Hind Rajab" and an
# institution is "Conseil constitutionnel" -- keying on "Hind" alone would
# split the subject and key on nothing recognizable. Not three or more: the
# longer the phrase, the fewer newsrooms word it identically, and the editorial
# floor is a count of newsrooms.
_PROPER_PHRASE = re.compile(r"[A-ZÀ-Þ][\wÀ-ɏ'’-]{2,}(?:\s+[A-ZÀ-Þ][\wÀ-ɏ'’-]{2,})?")

# A word written in lower case: the evidence that a capitalized occurrence
# elsewhere was sentence position rather than a name.
_LOWER_WORD = re.compile(r"\b[a-zà-ÿ][\wà-ÿ'’-]{2,}\b")

# Every run of non-word characters, so a name is found whatever punctuates it.
# Hyphens and apostrophes stay inside words: "Kim Jong-un" and "aujourd'hui" are
# single tokens in the vocabulary and must be single tokens in a title too.
_NON_WORD = re.compile(r"[^\wÀ-ɏ'’-]+")


@dataclass(frozen=True, slots=True)
class WrittenSubjects:
    output_path: Path
    metadata_path: Path
    items_out: int
    subjects_considered: int
    degraded: bool


def subject_vocabulary(
    reference_articles: Sequence[dict],
    min_newsrooms: int = MIN_REFERENCE_NEWSROOMS,
) -> dict[str, set[str]]:
    """Candidate subject names, mapped to the reference newsrooms that lead
    with them.

    Only the reference press is read here. That is the point: this is the
    editorial judgment, and admitting the wire corpus would drown it -- the
    volume signal enters later, as corroboration.
    """
    by_phrase: defaultdict[str, set[str]] = defaultdict(set)
    # A common noun opening a headline is capitalized exactly like a name, and
    # no stoplist can enumerate the common nouns of three languages. What
    # separates them is that a common noun also appears in lower case
    # somewhere -- "la guerre en Ukraine", "le president" -- while a name never
    # does. Learned from the same corpus, so it needs no dictionary and grows
    # with the feeds.
    #
    # This replaced a position rule ("seen at least once away from the start of
    # a headline"), which removed "guerre" correctly but also removed any name
    # that always leads its headline -- Ceuta among them, in the stage's own
    # tests. Measured on the 2026-08-20 reference corpus, the lower-case rule
    # drops "guerre" (10 lower-case occurrences) and "president" (5) while
    # keeping Ceuta, Gaza, Trump, Hind Rajab and Conseil constitutionnel, all
    # at zero.
    #
    # Applied to single words only. A phrase of two CAPITALIZED words is a name
    # almost by construction -- "Hind Rajab", "Kim Jong-un" -- so it is exempt.
    #
    # Note what this does not reach: `_PROPER_PHRASE` requires both words
    # capitalized, so a French or Spanish institution whose second word is not
    # ("Conseil constitutionnel", "Assemblee nationale") is only ever seen as
    # its first word and goes through the lower-case test like any other single
    # word. Admitting a lower-case continuation would be worse -- every
    # "Trump durcit" and "Ceuta accueille" would become a phrase, fragmenting
    # the subjects this stage exists to join.
    lowercased: set[str] = set()
    for article in reference_articles:
        for word in _LOWER_WORD.findall(article.get("title") or ""):
            lowercased.add(fold(word))

    for article in reference_articles:
        title = article.get("title") or ""
        source = article.get("source") or ""
        if not source:
            continue
        for match in set(_PROPER_PHRASE.findall(title)):
            key = fold(match)
            words = key.split()
            # A phrase containing a function word is sentence structure, not a
            # name: "Why Trump" and "En Espagne" are not subjects.
            if any(word in _STOP for word in words):
                continue
            if len(words) == 1 and words[0] in lowercased:
                continue
            by_phrase[key].add(source)

    return {
        phrase: sources for phrase, sources in by_phrase.items() if len(sources) >= min_newsrooms
    }


def _tokenized(title: str) -> str:
    """A folded title with every non-word run turned into a single space, and a
    space at each end.

    Splitting on whitespace alone was wrong and silently so: "Ceuta:" is one
    token, so an index keyed on it never answers a lookup for "ceuta", and the
    subject lost every article whose headline happened to punctuate after the
    name. Headlines are mostly punctuation -- colons, commas, quotes -- so this
    was not an edge case; the stage's own tests caught it on the first run.

    The bracketing spaces are what make the containment check below a
    word-boundary check rather than a substring one, so "ceuta" does not match
    "ceutaville".
    """
    return f" {_NON_WORD.sub(' ', fold(title)).strip()} "


def _title_index(articles: Sequence[dict]) -> tuple[list[str], dict[str, list[int]]]:
    """Tokenized titles plus a token-to-article index.

    A phrase is checked against the articles its first token appears in, not
    against all of them: the naive scan is 118 phrases x 12,000 titles of regex
    and took longer than the whole rest of the cycle.
    """
    tokenized = [_tokenized(article.get("title") or "") for article in articles]
    index: defaultdict[str, list[int]] = defaultdict(list)
    for position, title in enumerate(tokenized):
        for token in set(title.split()):
            index[token].append(position)
    return tokenized, dict(index)


def members_by_phrase(articles: Sequence[dict], phrases: Iterable[str]) -> dict[str, list[int]]:
    """Which articles name each phrase, by index."""
    folded, index = _title_index(articles)
    found: dict[str, list[int]] = {}
    for phrase in phrases:
        head = phrase.split()[0]
        matched = [position for position in index.get(head, ()) if phrase in folded[position]]
        if matched:
            found[phrase] = matched
    return found


def _nearest_is(
    candidate: str,
    target: str,
    centroids: dict[str, np.ndarray],
    claimed: dict[str, str],
    radius: float,
) -> bool:
    """Whether `target` is `candidate`'s single nearest unclaimed neighbour, and
    within `radius`.

    Nearest-only, not every candidate inside the radius. A large subject's
    centroid drifts toward the corpus mean and so sits close to everything:
    measured with a plain radius test, "Trump" -- 455 articles -- absorbed
    "Iran" and "Kim Jong-un", and "Colombia" absorbed Kenya, Ecuador, Congo and
    Ebola. Requiring the target to be the nearest of all candidates makes the
    hub compete rather than swallow, so "Chine" still joins "China" (its true
    nearest) while "Iran" stays its own subject.
    """
    if candidate not in centroids or target not in centroids:
        return False
    here = centroids[candidate]
    gap = float(np.linalg.norm(here - centroids[target]))
    if gap > radius:
        return False
    for other, centroid in centroids.items():
        if other == candidate or (other in claimed and claimed[other] != target):
            continue
        if float(np.linalg.norm(here - centroid)) < gap:
            return False
    return True


def merge_phrases(
    members: dict[str, list[int]],
    weight: dict[str, int],
    vectors: np.ndarray | None = None,
    overlap: float = MERGE_OVERLAP,
    centroid_distance: float = CENTROID_DISTANCE,
) -> list[tuple[str, list[str], list[int]]]:
    """Collapse candidate names that describe one subject.

    Returns ``(label, names, article_indices)`` per subject, the label being the
    name the most reference newsrooms used -- so a subject is announced the way
    the serious press words it, not the way the longest match does.

    Two mechanisms, deliberately: shared articles catch "Kiev"/"Kyiv"/"Ukraine",
    where the same pieces name several forms; centroid proximity catches
    "China"/"Chine", where they do not overlap at all because the articles are
    in different languages. Names alone cannot do the second, and embeddings
    alone cannot do subjects -- this is the one place both are load-bearing.
    """
    ordered = sorted(members, key=lambda p: (-weight.get(p, 0), -len(members[p]), p))
    claimed: dict[str, str] = {}
    subjects: list[tuple[str, list[str], list[int]]] = []

    centroids: dict[str, np.ndarray] = {}
    if vectors is not None and len(vectors):
        unit = normalize(np.asarray(vectors, dtype=float))
        for phrase, positions in members.items():
            rows = [p for p in positions if p < len(unit)]
            if rows:
                centroids[phrase] = normalize(unit[rows].mean(axis=0).reshape(1, -1))[0]

    for phrase in ordered:
        if phrase in claimed:
            continue
        names = [phrase]
        indices = set(members[phrase])
        claimed[phrase] = phrase
        for other in ordered:
            if other in claimed:
                continue
            other_indices = set(members[other])
            union = indices | other_indices
            shared = indices & other_indices
            joins = bool(union) and len(shared) / len(union) >= overlap
            if not joins:
                joins = _nearest_is(other, phrase, centroids, claimed, centroid_distance)
            if joins:
                claimed[other] = phrase
                names.append(other)
                indices |= set(members[other])
        subjects.append((phrase, names, sorted(indices)))
    return subjects


def build_items(
    articles: Sequence[dict],
    vectors: np.ndarray | None = None,
    min_newsrooms: int = MIN_REFERENCE_NEWSROOMS,
) -> list[dict]:
    """Form subjects from a cycle's whole corpus and emit Briefing items.

    Pure: vectors are passed in rather than computed, the same injection
    discipline every other stage uses, so this is testable without a network.
    """
    reference = [a for a in articles if source_trust_tier(a.get("source") or "") >= 3]
    if not reference:
        return []

    vocabulary = subject_vocabulary(reference, min_newsrooms)
    if not vocabulary:
        return []
    weight = {phrase: len(sources) for phrase, sources in vocabulary.items()}
    members = members_by_phrase(articles, vocabulary)
    subjects = merge_phrases(members, weight, vectors)

    items: list[dict] = []
    for label, names, indices in subjects:
        group = [articles[i] for i in indices]
        newsrooms = {
            a.get("source")
            for a in group
            if a.get("source") and source_trust_tier(a["source"]) >= 3
        }
        # The editorial floor is re-checked against the MERGED subject, not the
        # winning name alone: merging can only add newsrooms, and a subject that
        # clears the floor only by absorbing a near-duplicate name has not been
        # led with by three independent newsrooms.
        if len(newsrooms) < min_newsrooms:
            continue

        sources = {a.get("source") for a in group if a.get("source")}
        countries = sorted({a.get("source_country") for a in group if a.get("source_country")})
        about: Counter[str] = Counter()
        for article in group:
            about.update(article.get("mentioned_countries") or ())

        items.append(
            {
                "cluster_id": f"subject-{fold(label).replace(' ', '-')}",
                "members": group,
                "independent_source_count": len(sources),
                "country_count": len(countries),
                "countries": countries,
                "origin_country": countries[0] if countries else "unknown",
                # What the subject is ABOUT: the countries its articles name,
                # never where their outlets sit. Ordered most-named first so a
                # Zone's relevance test reads the subject's own centre of
                # gravity rather than an alphabetical accident.
                "mentioned_countries": [country for country, _ in about.most_common()],
                "outbound_url": group[0].get("url"),
                "outbound_source": group[0].get("source"),
                "subject_label": label,
                "subject_names": sorted(names),
                # The editorial weight, kept on the item so a ranking can use
                # it and a reader can be told how many serious newsrooms led
                # with this.
                "reference_newsroom_count": len(newsrooms),
                "reference_newsrooms": sorted(newsrooms),
            }
        )
    return items


def run_subjects(
    articles_path: Path,
    cycle_id: str,
    data_root: Path = DEFAULT_DATA_ROOT,
    vectors: np.ndarray | None = None,
) -> WrittenSubjects:
    """Read a cycle's articles, form subjects, write items."""
    from pipeline.stages import read_jsonl

    destination = output_dir_for(STAGE, cycle_id, root=data_root)
    output_path = destination / "items.jsonl"
    metadata_path = destination / f"{STAGE}.json"

    articles = list(read_jsonl(articles_path)) if articles_path.is_file() else []
    trace(f"subject: forming subjects over {len(articles)} articles")
    items = build_items(articles, vectors)
    trace(f"subject: {len(items)} subjects cleared the editorial floor")

    write_jsonl(output_path, items)
    metadata = {
        "stage": STAGE,
        "cycle_id": cycle_id,
        "articles_in": len(articles),
        "items_out": len(items),
        "min_reference_newsrooms": MIN_REFERENCE_NEWSROOMS,
        "degraded": not items,
    }
    write_atomically(
        metadata_path, json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    return WrittenSubjects(
        output_path=output_path,
        metadata_path=metadata_path,
        items_out=len(items),
        subjects_considered=len(articles),
        degraded=not items,
    )


def main(argv: list[str] | None = None) -> int:
    import sys

    from pipeline.stages import cycle_id_for, stage_arg_parser

    parser = stage_arg_parser(STAGE)
    args = parser.parse_args(argv)
    written = run_subjects(
        Path(args.input), cycle_id=args.cycle_id or cycle_id_for(), data_root=args.data_root
    )
    if written.degraded:
        print(f"{STAGE}: no subject cleared the editorial floor", file=sys.stderr)
    print(f"{STAGE}: {written.items_out} subjects -> {written.output_path}")
    return 0


__all__: list[Any] = [
    "CENTROID_DISTANCE",
    "MERGE_OVERLAP",
    "MIN_REFERENCE_NEWSROOMS",
    "STAGE",
    "WrittenSubjects",
    "build_items",
    "fold",
    "members_by_phrase",
    "merge_phrases",
    "run_subjects",
    "subject_vocabulary",
]


if __name__ == "__main__":
    raise SystemExit(main())
