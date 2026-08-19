"""The editorial agenda adapter and the stage that builds Briefing items from it.

Network-free throughout: `fetch` is injected, exactly as the GDELT adapter's is,
and the wikitext fixtures below are trimmed from the real 2026-08-18 chronicle
page so a change in Wikipedia's markup conventions fails here rather than in
production.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pipeline.adapters.editorial_agenda import (
    ADAPTER,
    MIN_EVENT_LENGTH,
    EditorialEvent,
    collect_agenda,
    fetch_day,
    page_title_for,
    parse_events,
    strip_wikitext,
)
from pipeline.stages.agenda import COVERAGE_DISTANCE, build_items, event_id

# Trimmed from the real page: one category heading, a three-level thread whose
# event sits at `***`, and a two-level thread whose event sits at `**`. Both
# shapes occur, which is why depth is judged per thread rather than fixed.
REAL_WIKITEXT = """{{Current events|year=2026|month=08|day=18|top=yes}}
<!-- All news items below this line -->
'''Armed conflicts and attacks'''
*[[2026 Iran war]]
**[[United Arab Emirates in the 2026 Iran war]]
***The [[United Arab Emirates]]'s [[Ministry of defence|defence ministry]] detects two missiles \
fired from [[Iran]]. [https://gulfnews.com/x (Gulf News)]
*[[Russo-Ukrainian war (2022–present)|Russo-Ukrainian war]]
**A [[Russian Armed Forces|Russian]] [[ballistic missile]] strike kills ten [[civilian]]s in \
[[Kharkiv Oblast]], [[Ukraine]]. [https://apnews.com/y (AP)]
'''Disasters and accidents'''
*Twenty-three people are killed in a collision between a bus and a truck in [[Brazil]]. \
[https://www.reuters.com/z (Reuters)]
*(see below)
"""


def _response(payload: dict) -> tuple[int, bytes]:
    return 200, json.dumps(payload).encode("utf-8")


def _parse_ok(wikitext: str):
    return lambda _url: _response({"parse": {"wikitext": wikitext}})


# --- Page addressing ---------------------------------------------------------


def test_the_page_title_matches_the_chronicle_s_own_naming() -> None:
    """Wikipedia names these pages "Portal:Current events/2026 August 18" --
    month spelled out, no zero padding. Getting it wrong yields missingtitle,
    which degrades silently into "no editorial signal today"."""
    assert (
        page_title_for(datetime(2026, 8, 18, tzinfo=UTC)) == "Portal:Current events/2026 August 18"
    )
    assert (
        page_title_for(datetime(2026, 1, 5, tzinfo=UTC)) == "Portal:Current events/2026 January 5"
    )


# --- Wikitext reduction ------------------------------------------------------


def test_wikitext_is_reduced_to_the_sentence_a_reader_would_see() -> None:
    raw = (
        "The [[United Arab Emirates]]'s [[Ministry of defence|defence ministry]] detects "
        "two missiles fired from [[Iran]].<ref>noise</ref> "
        "[https://gulfnews.com/x (Gulf News)] {{cite}}"
    )
    # The citation label goes too: "(Gulf News)" is the outlet's name, not part
    # of the event, and it would pull unrelated events cited to the same wire
    # together in the embedding.
    assert strip_wikitext(raw) == (
        "The United Arab Emirates's defence ministry detects two missiles fired from Iran"
    )


def test_a_piped_link_keeps_what_was_displayed_not_the_target() -> None:
    """`[[Ministry of defence|defence ministry]]` reads as "defence ministry".
    Keeping the target instead would embed the wrong words."""
    assert strip_wikitext("the [[Prime Minister of the United Kingdom|British PM]] said") == (
        "the British PM said"
    )


# --- Event extraction --------------------------------------------------------


def test_only_the_deepest_bullet_of_a_thread_is_an_event() -> None:
    """`*` and `**` lines name an ongoing topic ("2026 Iran war"); the event
    sentence is the deepest level. Embedding a bare topic label would match far
    too much, and depth varies per thread, so a fixed `***` filter would drop
    the events stated at `**`."""
    events = parse_events(REAL_WIKITEXT, "2026-08-18")
    texts = [e.text for e in events]

    assert any(t.startswith("The United Arab Emirates's defence ministry") for t in texts)
    assert any(t.startswith("A Russian ballistic missile strike") for t in texts)
    assert any(t.startswith("Twenty-three people are killed") for t in texts)
    # The topic labels themselves are never events.
    assert not any(t in {"2026 Iran war", "Russo-Ukrainian war"} for t in texts)


def test_a_fragment_too_short_to_be_an_event_is_dropped() -> None:
    events = parse_events(REAL_WIKITEXT, "2026-08-18")
    assert all(len(e.text) >= MIN_EVENT_LENGTH for e in events)
    assert not any("see below" in e.text for e in events)


def test_each_event_carries_the_category_it_was_filed_under() -> None:
    """The chronicle's taxonomy is the first signal this pipeline has for
    telling hard news from entertainment -- a ZZ Top drummer's death has no
    category here, a missile strike does."""
    by_category: dict[str, list[str]] = {}
    for event in parse_events(REAL_WIKITEXT, "2026-08-18"):
        by_category.setdefault(event.category, []).append(event.text)

    armed = by_category["Armed conflicts and attacks"]
    assert len(armed) == 2, "both threads under the heading keep it"
    assert any(t.startswith("The United Arab Emirates") for t in armed)
    assert any(t.startswith("A Russian ballistic missile") for t in armed)
    assert by_category["Disasters and accidents"] == [
        "Twenty-three people are killed in a collision between a bus and a truck in Brazil"
    ]


def test_each_event_keeps_the_sources_the_chronicle_cited() -> None:
    """These citations are the point: they lean on AP, Reuters and the BBC,
    which this project cannot reach any other way, and they give a reader
    somewhere authoritative to go when our own corpus covered nothing."""
    events = parse_events(REAL_WIKITEXT, "2026-08-18")
    hosts = {e.text[:12]: [s.split("/")[2] for s in e.sources] for e in events}
    assert hosts["The United A"] == ["gulfnews.com"]
    assert hosts["A Russian ba"] == ["apnews.com"]
    assert hosts["Twenty-three"] == ["www.reuters.com"]


def test_countries_come_from_both_the_wikilinks_and_the_prose() -> None:
    """A country is often named only inside a longer linked title ("Israel
    Defense Forces") or as an adjective ("a Russian strike"), so reading link
    targets alone loses it."""
    events = {e.text[:12]: e.countries for e in parse_events(REAL_WIKITEXT, "2026-08-18")}
    assert "up" in events["A Russian ba"], "Ukraine, from the [[Ukraine]] wikilink"
    assert "brazil" in events["Twenty-three"]


# --- Retrieval and degradation ----------------------------------------------


def test_a_missing_page_degrades_that_day_only() -> None:
    """Today's page does not exist early in the UTC morning, before editors
    have written it. That is the ordinary case, not a fault, and it must not
    cost the other six days."""
    calls: list[str] = []

    def fetch(url: str) -> tuple[int, bytes]:
        calls.append(url)
        if len(calls) == 1:
            return _response({"error": {"code": "missingtitle"}})
        return _response({"parse": {"wikitext": REAL_WIKITEXT}})

    events, failures = collect_agenda(now=datetime(2026, 8, 19, tzinfo=UTC), days=3, fetch=fetch)

    assert len(failures) == 1
    assert "missingtitle" in failures[0].detail
    assert failures[0].adapter == ADAPTER
    assert events, "the remaining days still yielded events"


def test_an_http_error_degrades_rather_than_raising() -> None:
    events, failures = collect_agenda(
        now=datetime(2026, 8, 19, tzinfo=UTC), days=1, fetch=lambda _u: (503, b"")
    )
    assert events == []
    assert "HTTP 503" in failures[0].detail


def test_a_non_json_response_degrades_rather_than_raising() -> None:
    events, failures = collect_agenda(
        now=datetime(2026, 8, 19, tzinfo=UTC), days=1, fetch=lambda _u: (200, b"<html>nope")
    )
    assert events == []
    assert "not JSON" in failures[0].detail


def test_the_same_ongoing_story_restated_across_days_is_not_duplicated() -> None:
    """The chronicle repeats an ongoing story verbatim on consecutive days;
    identical sentences add nothing to a similarity comparison."""
    events, _ = collect_agenda(
        now=datetime(2026, 8, 19, tzinfo=UTC), days=3, fetch=_parse_ok(REAL_WIKITEXT)
    )
    assert len(events) == len({e.text for e in events})


def test_fetch_day_reports_the_title_it_could_not_read() -> None:
    _, failure = fetch_day(datetime(2026, 8, 18, tzinfo=UTC), fetch=lambda _u: (404, b""))
    assert failure is not None
    assert "2026 August 18" in failure.detail


# --- Building Briefing items -------------------------------------------------


def _event(
    text: str, countries: tuple[str, ...] = (), sources: tuple[str, ...] = ()
) -> EditorialEvent:
    return EditorialEvent(
        text=text,
        category="Armed conflicts and attacks",
        day="2026-08-19",
        sources=sources,
        countries=countries,
    )


def _cluster(cid: str, source: str, source_country: str, about: list[str]) -> dict:
    return {
        "cluster_id": cid,
        "members": [
            {
                "title": f"headline {cid}",
                "url": f"https://{source}/{cid}",
                "source": source,
                "source_country": source_country,
                "language": "en",
            }
        ],
        "independent_source_count": 1,
        "country_count": 1,
        "countries": [source_country],
        "mentioned_countries": about,
        "origin_country": source_country,
    }


def test_a_matching_cluster_supplies_the_articles_and_the_score() -> None:
    events = [_event("A Russian missile strike kills ten civilians", countries=("up",))]
    clusters = [_cluster("c1", "laregione.ch", "sz", ["up"])]

    item = build_items(events, clusters, [[1.0, 0.0]], [[1.0, 0.0]])[0]

    assert item["corroborated"] is True
    assert item["independent_source_count"] == 1
    assert item["members"][0]["source"] == "laregione.ch"
    assert item["outbound_url"] == "https://laregione.ch/c1"


def test_the_reporting_outlet_s_country_never_places_the_event() -> None:
    """The bug this pipeline was fixed for earlier the same day, in a new
    place: a Swiss paper covering a strike in Kharkiv must not put that event
    in Switzerland. `countries` is where the newsroom sits; placement uses what
    the event is about."""
    events = [_event("A Russian missile strike kills ten civilians", countries=("up",))]
    clusters = [_cluster("c1", "laregione.ch", "sz", ["up"])]

    item = build_items(events, clusters, [[1.0, 0.0]], [[1.0, 0.0]])[0]

    assert item["countries"] == ["sz"], "the source list still says where the outlet is"
    assert "sz" not in item["mentioned_countries"]
    assert item["mentioned_countries"] == ["up"]


def test_an_uncorroborated_event_still_publishes_with_the_chronicle_s_citation() -> None:
    """The whole reason the agenda leads: an event no outlet in our corpus
    covered is still an event. Losing it would put us back to publishing only
    what the long tail happened to rerun."""
    events = [
        _event(
            "The Rapid Support Forces launches a crackdown in Nyala",
            countries=(),
            sources=("https://apnews.com/sudan",),
        )
    ]

    item = build_items(events, [], [[1.0, 0.0]], [])[0]

    assert item["corroborated"] is False
    assert item["members"] == []
    assert item["independent_source_count"] == 0
    assert item["outbound_url"] == "https://apnews.com/sudan"
    assert item["outbound_source"] == "apnews.com"
    assert item["agenda_text"].startswith("The Rapid Support Forces")


def test_an_unrelated_cluster_is_not_attached() -> None:
    """A false match would hang the wrong source list under an event, which is
    worse than no source list at all -- so the threshold errs toward missing."""
    events = [_event("A Russian missile strike kills ten civilians")]
    clusters = [_cluster("c1", "example.com", "us", ["united-states"])]

    # Orthogonal vectors: cosine distance 1.0, far past COVERAGE_DISTANCE.
    item = build_items(events, clusters, [[1.0, 0.0]], [[0.0, 1.0]])[0]

    assert item["corroborated"] is False
    assert item["members"] == []


def test_the_coverage_threshold_is_the_one_that_was_measured() -> None:
    """Guards the constant against a well-meaning tightening: measured on real
    2026-08-19 pairs, genuine matches sat at 0.28-0.40 and the nearest
    unrelated pair at 0.54. Tightening below 0.40 drops real coverage --
    at 0.35 only 2 of 19 events matched, at 0.45 it was 11 of 19."""
    assert 0.40 < COVERAGE_DISTANCE < 0.54


def test_an_item_only_ever_claims_sources_it_can_list() -> None:
    """AC3's guarantee, at the stage that now produces the numbers. Coverage is
    counted off the attached members, never copied from a Cluster's own stored
    count."""
    events = [_event("Something widely covered")]
    clusters = [
        _cluster("c1", "a.example", "france", ["france"]),
        _cluster("c2", "b.example", "spain", ["france"]),
    ]

    item = build_items(events, clusters, [[1.0, 0.0]], [[1.0, 0.0], [1.0, 0.0]])[0]

    assert item["independent_source_count"] == len(item["members"]) == 2
    assert item["country_count"] == len(item["countries"])


def test_the_same_event_text_always_yields_the_same_id() -> None:
    """A resumed cycle re-reads its own items, and AD-11's two-phase summarize
    matches results back by id."""
    first = _event("The Rapid Support Forces launches a crackdown in Nyala")
    second = _event("The Rapid Support Forces launches a crackdown in Nyala")
    assert event_id(first) == event_id(second)
    assert event_id(_event("A different event entirely")) != event_id(first)


def test_no_events_means_no_items_rather_than_an_error() -> None:
    """An empty agenda leaves the pipeline exactly where it was before this
    signal existed, and publishes nothing -- which is the honest outcome when
    the signal that decides importance is unavailable (AD-7)."""
    assert build_items([], [_cluster("c1", "a.example", "france", ["france"])], [], [[1.0]]) == []
