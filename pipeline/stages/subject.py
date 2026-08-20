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

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering
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

# How far apart two articles about the same event sit, in euclidean distance on
# unit vectors.
#
# A subject is a container, not an item. "China" held both Evergrande's founder
# being jailed for life and a hotel fire killing nine in India, and the
# summarizer welded them into one headline because it was handed both. Splitting
# the subject into events is what stops that.
#
# Measured inside the "china" subject on 2026-08-20. At 0.90 the Evergrande
# story forms one group of 12 articles spanning Spanish, English and German --
# the cross-language merge is the point, and at 0.80 it breaks into one group
# per language. Going looser than 0.90 starts pulling in China's robotics
# coverage.
#
# Note this is far looser than `cluster.py`'s same-Event threshold of 0.748, and
# safely so: these articles already share a subject, so the only question left is
# which event within it, not whether they are related at all.
EVENT_DISTANCE = 0.90

# An event needs this many reference newsrooms of its own.
#
# Applied to the event, not the subject it came from: a subject clearing the
# floor says the press is covering Ceuta, and an item has to say which
# development. Lower than the subject floor because splitting divides the
# newsrooms among the events -- three newsrooms on one subject cannot be three
# on each of its events.
MIN_EVENT_NEWSROOMS = 2

# Two events built from different subjects are the same event when their article
# sets overlap this much, as a Jaccard ratio.
#
# An article belongs to every subject it names, so one event surfaces once per
# subject that touches it. Measured on 2026-08-20, "Gaza" and "Hind Rajab" both
# produced the identical 14-source event, as did "Fedorov" and "Ukraine",
# "Trump" and "Canada", "China" and "Evergrande" -- six duplicate pairs among 88
# events. Left in, a Briefing would run the same story twice under two labels.
#
# Higher than MERGE_OVERLAP because this is a different claim: that one is "two
# names for one subject", where a partial overlap is evidence; this one is "two
# descriptions of one event", where it has to be near-identity.
EVENT_DEDUPE_OVERLAP = 0.70

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


# How many random samples per size when calibrating dispersion, and which
# sizes. Raw dispersion around a centroid rises with the number of articles, so
# comparing a 22-article subject to a 358-article one on it directly measures
# size, not coherence. Calibrating against random samples of the SAME size
# removes that: what is left is how much tighter than chance the subject is.
_BASELINE_TRIALS = 8
_BASELINE_SIZES = (4, 8, 16, 32, 64, 128, 256, 512)


def _dispersion(unit: np.ndarray) -> float:
    """Mean distance from a set of unit vectors to their own centroid."""
    centroid = normalize(unit.mean(axis=0).reshape(1, -1))[0]
    return float(np.mean(np.linalg.norm(unit - centroid, axis=1)))


def _baseline_dispersion(unit: np.ndarray, seed: int = 0) -> dict[int, float]:
    """Dispersion a random subset of each size would show, for calibration."""
    rng = np.random.default_rng(seed)
    baseline: dict[int, float] = {}
    for size in _BASELINE_SIZES:
        if size > len(unit):
            break
        trials = [
            _dispersion(unit[rng.choice(len(unit), size, replace=False)])
            for _ in range(_BASELINE_TRIALS)
        ]
        baseline[size] = float(np.mean(trials))
    return baseline


def coherence_of(unit: np.ndarray, rows: Sequence[int], baseline: dict[int, float]) -> float | None:
    """How much tighter than chance a subject's articles sit, 0 to 1.

    This is what tells a story from a container. Measured on 2026-08-20, the
    size-normalized ratio separates them cleanly: Hind Rajab 0.59, Evergrande
    0.62, Kyiv 0.69, Hormuz 0.79 and Ceuta 0.79 on one side, and "Espana" 0.93,
    "France" 0.90, "Europa" 0.89, "Etats-Unis" 0.88 on the other. A subject
    named after a country collects everything that country appears in, and the
    summarizer then welds unrelated events into one item -- a real Briefing said
    "Evergrande's founder jailed for life and a hotel fire kills nine in India"
    because both sat under "china".

    Returns None when there is too little to judge: a two-article subject has
    no meaningful dispersion, and inventing a number for it would rank it on
    noise.
    """
    if len(rows) < 4 or not baseline:
        return None
    observed = _dispersion(unit[rows])
    nearest = min(baseline, key=lambda size: abs(size - len(rows)))
    expected = baseline[nearest]
    if expected <= 0:
        return None
    # 1 - ratio, so more is better and the factor reads the same way as every
    # other one. Clamped: a subject can be tighter than any random sample.
    return max(0.0, min(1.0, 1.0 - observed / expected))


def split_into_events(unit: np.ndarray, rows: Sequence[int]) -> list[list[int]]:
    """Partition a subject's articles into the events inside it.

    Average linkage, not the connected components `cluster.py` uses: within one
    subject there is no chain of unrelated articles to guard against, and
    average linkage is what merges the same event told in three languages
    without also merging the subject's other stories.
    """
    if len(rows) < 2:
        return [list(rows)]
    labels = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=EVENT_DISTANCE,
        metric="euclidean",
        linkage="average",
    ).fit_predict(unit[list(rows)])
    grouped: defaultdict[int, list[int]] = defaultdict(list)
    for position, label in enumerate(labels):
        grouped[int(label)].append(rows[position])
    return [sorted(group) for group in grouped.values()]


def _without_source_duplicates(articles: Sequence[dict]) -> list[dict]:
    """Drop the same headline appearing twice from the same source.

    GDELT indexes some pages repeatedly, and a few of those pages are not
    articles at all: measured on 2026-08-20 the corpus carried "Making sure
    you're not a bot!" 33 times from one source, and two celebrity headlines 36
    times each. They cannot inflate `independent_source_count`, which counts
    distinct sources, but they do drag a subject's centroid and so its coherence.

    Keyed on (source, title), so genuine syndication survives untouched -- the
    same wire piece run by eleven different outlets is eleven real sources.
    """
    seen: set[tuple[str, str]] = set()
    kept: list[dict] = []
    for article in articles:
        key = (article.get("source") or "", fold(article.get("title") or ""))
        if key in seen:
            continue
        seen.add(key)
        kept.append(article)
    return kept


def _newsrooms_of(articles: Iterable[dict]) -> set[str]:
    """The reference newsrooms among a set of articles."""
    return {
        article["source"]
        for article in articles
        if article.get("source") and source_trust_tier(article["source"]) >= 3
    }


def _event_id(label: str, group: Sequence[dict]) -> str:
    """A stable id for one event, keyed on its articles.

    Keyed on the URLs rather than the subject label, because one subject now
    yields several items and a label-derived id would collide. Sorted first, so
    the id does not depend on the order the corpus happened to arrive in.
    """
    urls = ";".join(sorted(article.get("url", "") for article in group))
    digest = hashlib.sha256(urls.encode("utf-8")).hexdigest()[:12]
    return f"subject-{fold(label).replace(' ', '-')}-{digest}"


def _latest_day(group: Sequence[dict]) -> str:
    """The most recent day any of a subject's articles carries.

    Most recent, not median: a subject the press returned to today is today's
    however long it has been running, and the ranking's own novelty factor is
    what distinguishes a development from a repetition.
    """
    days = [
        (article.get("published_at") or "")[:10] for article in group if article.get("published_at")
    ]
    return max(days) if days else ""


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

    unit = None
    baseline: dict[int, float] = {}
    if vectors is not None and len(vectors):
        unit = normalize(np.asarray(vectors, dtype=float))
        baseline = _baseline_dispersion(unit)

    items: list[dict] = []
    for label, names, indices in subjects:
        subject_rows = [i for i in indices if unit is None or i < len(unit)]
        subject_newsrooms = _newsrooms_of(articles[i] for i in subject_rows)
        # The editorial floor is re-checked against the MERGED subject, not the
        # winning name alone: merging can only add newsrooms, and a subject that
        # clears the floor only by absorbing a near-duplicate name has not been
        # led with by three independent newsrooms.
        if len(subject_newsrooms) < min_newsrooms:
            continue

        # A subject is a container; an item is an event inside it. Without this
        # split, "China" was handed both Evergrande's founder being jailed and a
        # hotel fire in India, and the summarizer welded them into one headline.
        #
        # It also disposes of the country-shaped subjects that no amount of
        # score tuning could demote. Measured on 2026-08-20, "Espana" held 40
        # articles that split into 40 events of one article each: 40 unrelated
        # Spanish stories, not a subject with events in it. None clears the
        # floor, so the container simply stops producing items.
        events = split_into_events(unit, subject_rows) if unit is not None else [subject_rows]
        for rows in events:
            group = _without_source_duplicates([articles[i] for i in rows])
            newsrooms = _newsrooms_of(group)
            if len(newsrooms) < MIN_EVENT_NEWSROOMS:
                continue

            sources = {a.get("source") for a in group if a.get("source")}
            countries = sorted({a.get("source_country") for a in group if a.get("source_country")})
            about: Counter[str] = Counter()
            for article in group:
                about.update(article.get("mentioned_countries") or ())

            items.append(
                {
                    # Keyed on the articles, not the subject label: one subject
                    # now yields several items and they must not collide. Stable
                    # across a resumed cycle, which AD-11's two-phase summarize
                    # depends on.
                    "cluster_id": _event_id(label, group),
                    "members": group,
                    "independent_source_count": len(sources),
                    "country_count": len(countries),
                    "countries": countries,
                    "origin_country": countries[0] if countries else "unknown",
                    # What the event is ABOUT: the countries its articles name,
                    # never where their outlets sit. Ordered most-named first so
                    # a Zone's relevance test reads the event's own centre of
                    # gravity rather than an alphabetical accident.
                    "mentioned_countries": [country for country, _ in about.most_common()],
                    "outbound_url": group[0].get("url"),
                    "outbound_source": group[0].get("source"),
                    # When it last moved, from its own articles. Named
                    # `editorial_day` rather than reusing the agenda's field:
                    # the two answer the same question for the ranking, but one
                    # is a chronicle's dateline and this is our corpus's own.
                    "editorial_day": _latest_day(group),
                    # Measured on the EVENT, not the subject. A container's
                    # dispersion says nothing about the event pulled out of it.
                    "coherence": (coherence_of(unit, rows, baseline) if unit is not None else None),
                    # The editorial weight that decides the ranking, counted on
                    # this event. A subject clearing the floor says the press is
                    # covering Ceuta; an item has to say which development.
                    "reference_newsroom_count": len(newsrooms),
                    "reference_newsrooms": sorted(newsrooms),
                    # Kept for provenance: which subject this came out of, and
                    # how widely that subject was led with.
                    "subject_label": label,
                    "subject_names": sorted(names),
                    "subject_newsroom_count": len(subject_newsrooms),
                    # Internal: which corpus rows this event holds, so the
                    # duplicate pass can compare centroids. Stripped before the
                    # item leaves this function.
                    "_rows": list(rows),
                }
            )
    centroids = None
    if unit is not None:
        centroids = {
            item["cluster_id"]: normalize(
                unit[[row for row in item["_rows"] if row < len(unit)]].mean(axis=0).reshape(1, -1)
            )[0]
            for item in items
            if item["_rows"]
        }
    deduped = _without_duplicate_events(items, centroids)
    for item in deduped:
        item.pop("_rows", None)
    return deduped


def _without_duplicate_events(
    items: list[dict], centroids: dict[str, np.ndarray] | None = None
) -> list[dict]:
    """Collapse events that different subjects built from the same story.

    Keeps the one the most reference newsrooms led with, and records the labels
    it absorbed -- the alternative is a Briefing running "Gaza" and "Hind Rajab"
    as two items off one set of fourteen sources.

    Two tests, for the same reason `merge_phrases` needs two: shared articles
    catch the ordinary case, and centroid proximity catches the one where a
    story split by language shares no article at all. Measured, "Evergrande"
    (French and English) and "China" (Spanish) were the same sentencing and
    overlapped on nothing; so were "Fedorov" and "Ukraine".
    """
    ordered = sorted(
        items,
        key=lambda item: (
            -item["reference_newsroom_count"],
            -item["independent_source_count"],
            item["cluster_id"],
        ),
    )
    kept: list[dict] = []
    kept_urls: list[set[str]] = []
    for item in ordered:
        urls = {member.get("url", "") for member in item["members"]}
        here = (centroids or {}).get(item["cluster_id"])
        duplicate_of = None
        for position, seen in enumerate(kept_urls):
            union = urls | seen
            if union and len(urls & seen) / len(union) >= EVENT_DEDUPE_OVERLAP:
                duplicate_of = position
                break
            there = (centroids or {}).get(kept[position]["cluster_id"])
            close = (
                here is not None
                and there is not None
                and float(np.linalg.norm(here - there)) <= EVENT_DISTANCE
            )
            if close:
                duplicate_of = position
                break
        if duplicate_of is None:
            kept.append(item)
            kept_urls.append(urls)
        else:
            # Provenance, not decoration: an operator reading the item should be
            # able to see it was reached from more than one subject.
            other = kept[duplicate_of]
            merged = sorted({*other["subject_names"], *item["subject_names"]})
            other["subject_names"] = merged
    return kept


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
