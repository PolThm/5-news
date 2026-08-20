"""Tests for the subject stage.

The measurements these guards encode all come from the 2026-08-20 corpus, and
each one is a rule that was wrong at least once before it was right. The
docstrings say which, because the reason a threshold has its value is the only
thing that lets a later reader change it safely.
"""

from __future__ import annotations

import numpy as np
from pipeline.stages.subject import (
    MIN_REFERENCE_NEWSROOMS,
    build_items,
    fold,
    members_by_phrase,
    merge_phrases,
    subject_vocabulary,
)

# A reference newsroom (trust tier 3, derived from rss.FEEDS) and an ordinary
# wire source, so a test can put an article on either side of the editorial
# floor without asserting on the tier machinery itself.
_REFERENCE = ("lemonde.fr", "elpais.com", "theguardian.com", "lefigaro.fr", "spiegel.de")
_WIRE = "some-aggregator.example"


def _article(title: str, source: str, *, country: str = "france", about: tuple = ()) -> dict:
    return {
        "title": title,
        "url": f"https://{source}/{abs(hash(title))}",
        "source": source,
        "source_country": country,
        "language": "fr",
        "collected_by": "rss" if source in _REFERENCE else "gdelt",
        "mentioned_countries": list(about),
    }


def test_folding_makes_one_name_one_key() -> None:
    """ "Téhéran" and "Teheran" are the same name. Two keys would be two
    subjects, each with half the coverage."""
    assert fold("Téhéran") == fold("Teheran")
    assert fold("CEUTA") == fold("Ceuta")


def test_a_name_the_serious_press_does_not_lead_with_is_not_a_subject() -> None:
    """The editorial floor, and the reason there is no stoplist for wire noise.
    Measured on 2026-08-20: "United States" was named by 187 GDELT sources and
    one reference newsroom, Ceuta by nine newsrooms. Volume is not judgment.
    """
    articles = [
        _article(f"Reprise sur les United States numero {i}", f"wire{i}.example") for i in range(50)
    ] + [_article("Crise a Ceuta", src) for src in _REFERENCE[:3]]

    vocabulary = subject_vocabulary([a for a in articles if a["source"] in _REFERENCE])

    assert "ceuta" in vocabulary
    assert "united states" not in vocabulary, "50 wire sources are not an editorial signal"


def test_a_common_noun_opening_a_headline_is_not_a_name() -> None:
    """No stoplist can enumerate the common nouns of three languages. What
    separates them is that a common noun also appears in lower case somewhere in
    the corpus -- "la guerre en Ukraine" -- while a name never does.

    This replaced a position rule ("seen at least once away from the start of a
    headline"), which removed "guerre" correctly but also removed any name that
    always leads its headline. Ceuta was one, and it failed in this very file.
    """
    articles = [_article("Guerre au Proche-Orient, jour 12", src) for src in _REFERENCE[:4]]
    # The same word, lower case, as it appears in any real corpus.
    articles += [_article("Ce que la guerre a change pour Kyiv", _REFERENCE[0])]
    articles += [_article("Trump durcit le ton", src) for src in _REFERENCE[:4]]
    # A name that only ever leads its headline must survive.
    articles += [_article("Ceuta, la crise s'aggrave", src) for src in _REFERENCE[:3]]

    vocabulary = subject_vocabulary(articles)

    assert "guerre" not in vocabulary, "seen in lower case, so a common noun"
    assert "trump" in vocabulary
    assert "ceuta" in vocabulary, "never lower case, even though it always leads"


def test_a_two_capital_name_is_exempt_from_the_lower_case_test() -> None:
    """A phrase of two capitalized words is a name almost by construction, so it
    is not put through the lower-case test.

    The limit this documents: `_PROPER_PHRASE` needs BOTH words capitalized, so
    an institution like "Conseil constitutionnel" is only ever seen as
    "Conseil" and goes through the single-word test like anything else.
    Admitting a lower-case continuation would be worse -- every "Trump durcit"
    would become a phrase and fragment the subjects this stage exists to join.
    """
    articles = [_article("Le dossier Hind Rajab relance", src) for src in _REFERENCE[:3]]
    # Both words also appear in lower case; the phrase survives anyway.
    articles += [_article("hind et rajab, deux prenoms", _REFERENCE[0])]

    vocabulary = subject_vocabulary(articles)

    assert "hind rajab" in vocabulary
    assert "hind" not in vocabulary, "the single word is not exempt"


def test_a_two_word_name_stays_whole() -> None:
    """A person is "Hind Rajab" and keying on "Hind" alone splits the subject
    and labels it with nothing recognizable."""
    articles = [_article("L'enquete sur Hind Rajab avance", src) for src in _REFERENCE[:3]]

    vocabulary = subject_vocabulary(articles)

    assert "hind rajab" in vocabulary


def test_membership_reaches_the_wire_corpus_the_vocabulary_never_saw() -> None:
    """The division of labour: the reference press decides what a subject is,
    the wire corpus says how widely it is carried. A subject whose members were
    only its reference articles would report a Consensus Score of three."""
    articles = [_article("Crise a Ceuta", src) for src in _REFERENCE[:3]]
    articles += [_article(f"Ceuta: arrivees en hausse {i}", f"wire{i}.example") for i in range(6)]

    items = build_items(articles)

    ceuta = next(i for i in items if i["subject_label"] == "ceuta")
    assert ceuta["reference_newsroom_count"] == 3
    assert ceuta["independent_source_count"] == 9, "3 newsrooms + 6 wire sources"


def test_a_small_candidate_is_not_swallowed_by_a_large_unrelated_one() -> None:
    """Merging was first written as "this share of the smaller set also belongs
    to the larger", and measured, that let "Trump" absorb "Canada" and "Coree":
    a candidate with three articles, two of which also mention Trump, is
    two-thirds contained. The subject came out with 136 sources across 39
    countries -- everything Trump was mentioned in. Jaccard against the union
    scores those same sets at 0.02.
    """
    trump = [f"t{i}" for i in range(100)]
    members = {"trump": list(range(100)), "canada": [0, 1, 200]}
    weight = {"trump": 20, "canada": 4}

    subjects = merge_phrases(members, weight)

    labels = {label for label, _, _ in subjects}
    assert labels == {"trump", "canada"}, "two subjects, not one"
    assert trump  # keeps the fixture honest about what 100 articles means


def test_two_spellings_with_no_shared_articles_still_merge() -> None:
    """ "China" and "Chine" share no articles at all -- they are the same subject
    in two languages. Names cannot see that; centroids can. This is the one
    place both mechanisms are load-bearing."""
    members = {"china": [0, 1, 2], "chine": [3, 4]}
    weight = {"china": 10, "chine": 7}
    # Two tight groups placed close together: one subject, two vocabularies.
    vectors = np.array(
        [[1.0, 0.02, 0.0], [1.0, 0.0, 0.02], [1.0, 0.01, 0.01], [1.0, 0.0, 0.03], [1.0, 0.02, 0.01]]
    )

    subjects = merge_phrases(members, weight, vectors)

    assert len(subjects) == 1
    label, names, _ = subjects[0]
    assert label == "china", "labelled the way the most newsrooms worded it"
    assert set(names) == {"china", "chine"}


def test_a_hub_subject_competes_for_neighbours_rather_than_swallowing_them() -> None:
    """A large subject's centroid drifts toward the corpus mean and so sits
    close to everything. Measured with a plain radius test, "Trump" (455
    articles) absorbed "Iran" and "Kim Jong-un", and "Colombia" absorbed Kenya,
    Ecuador, Congo and Ebola. Requiring the target to be the nearest of ALL
    candidates makes the hub compete instead.
    """
    members = {"hub": [0, 1], "near": [2], "far": [3]}
    weight = {"hub": 20, "near": 5, "far": 5}
    # `near` and `far` are each closer to one another than either is to `hub`,
    # so neither may join the hub even though both are inside its radius.
    vectors = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 1.0, 0.02]])

    subjects = merge_phrases(members, weight, vectors)

    by_label = {label: set(names) for label, names, _ in subjects}
    assert "near" not in by_label.get("hub", set())
    assert "far" not in by_label.get("hub", set())


def test_the_editorial_floor_is_rechecked_after_merging() -> None:
    """Merging can only add newsrooms, so a subject could clear the floor by
    absorbing a near-duplicate name rather than by being led with. Re-checking
    against the merged subject is what keeps the floor meaning what it says."""
    # Two newsrooms name one subject: below the floor of three, and no merge
    # can make three independent newsrooms out of two.
    articles = [_article("Crise a Ceuta", src) for src in _REFERENCE[:2]]
    articles += [_article(f"Ceuta encore {i}", f"wire{i}.example") for i in range(20)]

    items = build_items(articles)

    assert items == [], "20 wire sources do not substitute for a third newsroom"
    assert MIN_REFERENCE_NEWSROOMS == 3


def test_a_subject_is_placed_by_what_its_articles_are_about() -> None:
    """`mentioned_countries`, never `source_country`. A Swiss paper covering a
    strike in Kharkiv must not place that subject in Switzerland -- the bug this
    pipeline was fixed for once already."""
    articles = [
        _article("Frappe sur Kharkiv", src, country="switzerland", about=("ukraine",))
        for src in _REFERENCE[:3]
    ]

    items = build_items(articles)

    subject = items[0]
    assert subject["mentioned_countries"] == ["ukraine"]
    assert subject["countries"] == ["switzerland"], "where the outlets sit, kept separately"


def test_the_most_named_country_leads_the_placement_list() -> None:
    """Ordered most-named first so a Zone's relevance test reads the subject's
    own centre of gravity rather than an alphabetical accident."""
    articles = [
        _article("Ceuta et le Maroc", src, about=("morocco", "spain")) for src in _REFERENCE[:2]
    ]
    articles += [_article("Ceuta, la reponse de Madrid", _REFERENCE[2], about=("spain",))]

    items = build_items(articles)

    assert items[0]["mentioned_countries"][0] == "spain", "3 mentions to 2"


def test_no_reference_press_yields_no_subjects_rather_than_wire_noise() -> None:
    """A cycle whose reference feeds all failed has no editorial judgment
    available. Falling back to the wire corpus is exactly how a ZZ Top
    drummer's death got published, so it returns nothing and lets AD-7 leave
    the previous Briefings in place."""
    articles = [_article(f"Depeche {i}", f"wire{i}.example") for i in range(200)]

    assert build_items(articles) == []


def test_membership_matching_only_scans_articles_that_share_the_first_token() -> None:
    """An optimization, and a semantic no-op: the naive version was 118 phrases
    against 12,000 titles of regex and took longer than the rest of the cycle.
    Any article the index skips is one the phrase check would reject."""
    articles = [_article("Crise a Ceuta aujourd'hui", "a.example")]
    articles += [_article("Rien a voir", "b.example")]

    found = members_by_phrase(articles, ["ceuta", "absent"])

    assert found == {"ceuta": [0]}


def test_a_subject_is_split_into_the_events_inside_it() -> None:
    """A subject is a container; an item is an event. Without the split, "China"
    was handed both Evergrande's founder being jailed for life and a hotel fire
    killing nine in India, and the summarizer welded them into one headline:
    "Le fondateur d'Evergrande condamne a perpetuite et un incendie d'hotel tue
    neuf personnes en Inde". That item was published.
    """
    verdict = [_article("Le fondateur d'Evergrande condamne", src) for src in _REFERENCE[:3]]
    fire = [_article("Un incendie d'hotel tue neuf personnes", src) for src in _REFERENCE[:3]]
    # Both name the subject, and each event's articles sit together.
    for article in verdict + fire:
        article["title"] += " en Chine"
    vectors = np.array([[1.0, 0.0, 0.0]] * 3 + [[0.0, 1.0, 0.0]] * 3)

    items = build_items(verdict + fire, vectors)

    assert len(items) == 2, "one item per event, not one welded item"
    titles = {item["members"][0]["title"] for item in items}
    assert any("Evergrande" in t for t in titles)
    assert any("incendie" in t for t in titles)


def test_a_country_shaped_container_stops_producing_items() -> None:
    """What no amount of score tuning could fix. Measured on 2026-08-20,
    "Espana" held 40 articles that split into 40 events of one article each --
    40 unrelated Spanish stories, not a subject with events in it. None clears
    the per-event floor, so the container simply stops producing."""
    # Five newsrooms all naming Espana, each about something different.
    articles = [
        _article(f"En Espana, un fait divers numero {i}", src) for i, src in enumerate(_REFERENCE)
    ]
    vectors = np.eye(len(articles))[:, :5].astype(float)

    items = build_items(articles, vectors)

    assert items == [], "five unrelated stories are not an event"


def test_one_event_reached_from_two_subjects_is_published_once() -> None:
    """An article belongs to every subject it names, so one event surfaces once
    per subject that touches it. Measured, "Gaza" and "Hind Rajab" both produced
    the identical 14-source event, as did "Fedorov" and "Ukraine" and "China"
    and "Evergrande" -- six duplicate pairs among 88 events. Left in, a Briefing
    runs the same story twice under two labels.
    """
    articles = [
        _article("A Gaza, deux ans apres la mort de Hind Rajab", src) for src in _REFERENCE[:3]
    ]
    vectors = np.array([[1.0, 0.0]] * 3)

    items = build_items(articles, vectors)

    assert len(items) == 1
    # Both names travel with the surviving item, so the provenance is not lost.
    assert {"gaza", "hind rajab"} <= set(items[0]["subject_names"])


def test_the_same_headline_twice_from_one_source_is_dropped() -> None:
    """GDELT indexes some pages repeatedly, and a few are not articles: the
    2026-08-20 corpus carried "Making sure you're not a bot!" 33 times from one
    source. They cannot inflate `independent_source_count`, which counts
    distinct sources, but they drag a subject's centroid and so its coherence.
    Genuine syndication -- one wire piece run by eleven outlets -- survives."""
    repeated = [_article("Crise a Ceuta", _REFERENCE[0]) for _ in range(8)]
    syndicated = [_article("Crise a Ceuta", src) for src in _REFERENCE[1:4]]

    items = build_items(repeated + syndicated)

    assert len(items[0]["members"]) == 4, "one per source, not one per indexing"
    assert items[0]["independent_source_count"] == 4


def test_the_event_carries_its_own_newsroom_count_not_the_subjects() -> None:
    """A subject clearing the floor says the press is covering Ceuta; an item has
    to say which development. Splitting divides the newsrooms among the events,
    so the count that decides the ranking is measured on the event."""
    big = [_article("Ceuta: transfert de 500 mineurs", src) for src in _REFERENCE[:4]]
    small = [_article("Ceuta: la police evacue les plages", src) for src in _REFERENCE[:2]]
    vectors = np.array([[1.0, 0.0]] * 4 + [[0.0, 1.0]] * 2)

    items = build_items(big + small, vectors)

    by_count = sorted(items, key=lambda i: -i["reference_newsroom_count"])
    assert [i["reference_newsroom_count"] for i in by_count] == [4, 2]
    # The subject's own count travels alongside, for provenance.
    assert all(i["subject_newsroom_count"] == 4 for i in items)
