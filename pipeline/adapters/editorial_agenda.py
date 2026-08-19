"""Editorial agenda adapter: what a human editor judged worth recording today.

The pipeline's only quality gate used to be the Consensus Score -- how many
outlets covered a story. That measures syndication, not importance, and the
published output showed it: a ZZ Top drummer's death and a suspended tennis
player cleared the bar because they were internationally rerun, while nothing
distinguished them from a war. Five local US radio stations rerunning one AP
dispatch clear it; a Spiegel investigation nobody else picked up does not.

This adapter supplies the missing axis. Wikipedia's Current Events Portal is a
daily chronicle where volunteer editors decide, by hand, which events belong in
the record of a day -- and they organise them under a fixed taxonomy ("Armed
conflicts and attacks", "Politics and elections", "Disasters and accidents",
"Business and economy"). That is an editorial judgment this project cannot
produce on its own and does not have to: it is published, free, and openly
licensed.

**Why this and not the newspapers themselves.** The obvious answer to "no major
papers in the corpus" is to read their feeds. Their terms mostly forbid it for
what this product does. Verified 2026-08-19 by reading the actual terms: Le
Monde's feeds are contractually closed absent written permission; the BBC
permits RSS only unmodified, which an AI-written summary is not; the NYT closes
every route; the Guardian's Open Platform grants a free key then forbids
altering, translating, retaining beyond 24 hours, and using the content with
generative AI at all. Reuters serves a bot wall and AP has closed its routes --
their absence from GDELT is deliberate, not a crawling limitation, so scraping
would not fix it either, and France has transposed the press publishers' right
(art. L211-3-1 CPI) on top. Wikipedia, by contrast, publishes under CC BY-SA
4.0 and invites reuse.

**What this adapter does NOT do.** It does not ingest Articles and nothing it
returns is ever published. No Wikipedia prose reaches a Briefing; these strings
exist only to be embedded and compared against Clusters the pipeline already
collected elsewhere, so the product still shows its own summary of its own
sources. That keeps the CC BY-SA attribution obligation off the published
output, because nothing derived from the text is served -- and it is why the
chronicle's heavy citation of Reuters and AP is useful: it tells us which
subjects the closed wires are covering without touching their content.

Retrieved through the MediaWiki action API -- a public, documented interface,
no key, no account, no scraping (NFR-5).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pipeline.adapters import Failure
from pipeline.config import country_slug_for_english_name, country_slugs_in_english_text

ADAPTER = "editorial_agenda"

API = "https://en.wikipedia.org/w/api.php"

# The chronicle is written in English on en.wikipedia. There is no daily
# equivalent on fr or es -- probed 2026-08-19: fr's Portail:Actualités and
# es's dated Portal:Actualidad subpages do not exist. That costs nothing here,
# because these strings are only ever compared to Clusters through
# multilingual embeddings, which is the one thing embed-v4 is for. The events
# themselves are worldwide and name their own countries.
_PAGE = "Portal:Current events/{year} {month} {day}"
_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

# A day's page nests three levels deep: `*` a running theme ("2026 Iran war"),
# `**` a sub-thread, `***` the actual event sentence. Only the deepest level is
# a reportable event; the shallower ones are navigation. Verified against the
# 2026-08-18 page, which held 29 bullets under 6 category headings.
_BULLET = re.compile(r"^(\*+)\s*(.+)$")

# Category headings are bold-quoted lines between bullet groups.
_HEADING = re.compile(r"^'''(.+?)'''\s*$")

# Wikitext to strip. Order matters: piped links before bare links, so
# `[[Target|shown]]` keeps `shown` rather than `Target|shown`.
_PIPED_LINK = re.compile(r"\[\[[^\]|]*\|([^\]]+)\]\]")
_BARE_LINK = re.compile(r"\[\[([^\]]+)\]\]")
# External links are removed WITH their label. The label is the cited outlet's
# name -- "(Gulf News)", "(AP)" -- never part of what happened, and leaving it
# in skews the embedding this text exists to produce: two unrelated events both
# cited to Reuters would be pulled together by the word "Reuters".
_EXTERNAL = re.compile(r"\[https?://\S+[^\]]*\]")
_TEMPLATE = re.compile(r"\{\{[^}]*\}\}")
_REF = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_QUOTES = re.compile(r"'{2,}")
_WHITESPACE = re.compile(r"\s+")

# Cited source URLs, and the wikilink targets an entry names.
_SOURCE_URL = re.compile(r"\[(https?://[^\s\]]+)")
_LINK_TARGET = re.compile(r"\[\[([^\]|]+)")

# An event sentence shorter than this is a fragment, not something worth
# embedding -- a stray "(see below)" or a bare date.
MIN_EVENT_LENGTH = 30


class EditorialEvent:
    """One event a human editor recorded for a given day.

    A plain class rather than a frozen dataclass to keep this module free of
    the domain layer: nothing here is an Article and nothing here is published,
    so it deliberately does not reuse ArticleRecord.

    ``sources`` are the URLs the chronicle cites for the event. They matter
    disproportionately: the entries lean on exactly the wires this project
    cannot otherwise reach -- AP, Reuters, BBC, Al Jazeera -- so they give a
    reader somewhere authoritative to go even when nothing in our own corpus
    covered the story. Linking to a page is not reproducing it.

    ``countries`` are Zone-style slugs read out of the entry's wikilinks, so an
    event can be placed without depending on our corpus having found it.
    """

    __slots__ = ("text", "category", "day", "sources", "countries")

    def __init__(
        self,
        text: str,
        category: str,
        day: str,
        sources: tuple[str, ...] = (),
        countries: tuple[str, ...] = (),
    ) -> None:
        self.text = text
        self.category = category
        self.day = day
        self.sources = sources
        self.countries = countries

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"EditorialEvent({self.day} {self.category!r} {self.text[:40]!r})"

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "category": self.category,
            "day": self.day,
            "sources": list(self.sources),
            "countries": list(self.countries),
        }


def page_title_for(day: datetime) -> str:
    """The chronicle page title for a date, in the API's own format."""
    moment = day.astimezone(UTC)
    return _PAGE.format(year=moment.year, month=_MONTHS[moment.month - 1], day=moment.day)


def strip_wikitext(raw: str) -> str:
    """Reduce a wikitext bullet to the sentence a reader would see."""
    text = _COMMENT.sub("", raw)
    text = _REF.sub("", text)
    text = _TEMPLATE.sub("", text)
    text = _PIPED_LINK.sub(r"\1", text)
    text = _BARE_LINK.sub(r"\1", text)
    text = _EXTERNAL.sub("", text)
    text = _TAG.sub("", text)
    text = _QUOTES.sub("", text)
    return _WHITESPACE.sub(" ", text).strip(" .;,")


def parse_events(wikitext: str, day: str) -> list[EditorialEvent]:
    """The reportable events on one chronicle page.

    Keeps only the deepest bullet level of each thread, which is where the
    event sentence lives; a `*`/`**` line names an ongoing topic and would
    embed as a bare label ("Gaza war") that matches far too much.

    Depth is judged per group rather than globally: some threads run three
    levels deep and others state their event at `**`, so a fixed `***` filter
    would silently drop the shallower ones.
    """
    events: list[EditorialEvent] = []
    category = ""
    group: list[tuple[int, str]] = []

    def flush() -> None:
        if not group:
            return
        deepest = max(depth for depth, _ in group)
        for depth, body in group:
            if depth != deepest:
                continue
            text = strip_wikitext(body)
            if len(text) < MIN_EVENT_LENGTH:
                continue
            # Wikilinks first -- an explicit [[Ukraine]] is the strongest
            # signal -- then the sentence itself, which catches countries named
            # only inside a longer linked title ("Israel Defense Forces").
            countries: list[str] = []
            for target in _LINK_TARGET.findall(body):
                slug = country_slug_for_english_name(target)
                # Most wikilinks are people, bodies or sub-national places
                # ("Andy Burnham", "Ministry of defence", "Kharkiv Oblast"),
                # which resolve to None and are simply not countries.
                if slug is not None and slug not in countries:
                    countries.append(slug)
            for slug in country_slugs_in_english_text(text):
                if slug not in countries:
                    countries.append(slug)
            events.append(
                EditorialEvent(
                    text=text,
                    category=category,
                    day=day,
                    sources=tuple(dict.fromkeys(_SOURCE_URL.findall(body))),
                    countries=tuple(countries),
                )
            )
        group.clear()

    for line in wikitext.splitlines():
        stripped = line.strip()
        heading = _HEADING.match(stripped)
        if heading:
            flush()
            category = strip_wikitext(heading.group(1))
            continue
        bullet = _BULLET.match(stripped)
        if not bullet:
            continue
        depth = len(bullet.group(1))
        # A top-level bullet starts a new thread, so the previous one is done.
        if depth == 1 and group:
            flush()
        group.append((depth, bullet.group(2)))
    flush()
    return events


def _default_fetch(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url,
        headers={
            # Wikimedia's User-Agent policy asks for a contactable identifier.
            # Sending a generic one risks being blocked, and being blocked here
            # degrades silently into "no editorial signal today".
            "User-Agent": "5-news/0.1 (https://github.com/PolThm/5-news)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as handle:
            return handle.status, handle.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


Fetch = Callable[[str], tuple[int, bytes]]


def fetch_day(
    day: datetime, fetch: Fetch = _default_fetch
) -> tuple[list[EditorialEvent], Failure | None]:
    """One day's events, or a Failure describing why there are none."""
    title = page_title_for(day)
    query = urllib.parse.urlencode(
        {
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "format": "json",
            "formatversion": "2",
        }
    )
    status, body = fetch(f"{API}?{query}")
    if status != 200:
        return [], Failure(ADAPTER, f"{title}: HTTP {status}")
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [], Failure(ADAPTER, f"{title}: response was not JSON: {exc}")
    if "error" in payload:
        # A missing page is the ordinary case for today before editors have
        # started it, not a fault -- reported so a thin cycle is explainable.
        code = payload["error"].get("code", "unknown")
        return [], Failure(ADAPTER, f"{title}: {code}")
    try:
        wikitext = payload["parse"]["wikitext"]
    except (KeyError, TypeError):
        return [], Failure(ADAPTER, f"{title}: no wikitext in response")
    return parse_events(wikitext, day.astimezone(UTC).strftime("%Y-%m-%d")), None


# How many days back to read. Seven so the `week` Period has a full window of
# editorial judgment behind it, matching briefing_matrix's own 7-day week.
DEFAULT_DAYS = 7


def collect_agenda(
    now: datetime | None = None,
    days: int = DEFAULT_DAYS,
    fetch: Fetch = _default_fetch,
) -> tuple[list[EditorialEvent], list[Failure]]:
    """The editorial agenda for the last ``days`` days, newest first.

    Degrades per day rather than all-or-nothing (AD-10): a missing page --
    which today's normally is, early in the UTC morning, before editors have
    written it -- costs that day's events and no more. An empty result is a
    legitimate outcome and leaves the pipeline exactly as it was before this
    signal existed, which is what makes adding it safe.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    events: list[EditorialEvent] = []
    failures: list[Failure] = []
    seen: set[str] = set()
    for offset in range(days):
        day_events, failure = fetch_day(moment - timedelta(days=offset), fetch=fetch)
        if failure is not None:
            failures.append(failure)
            continue
        for event in day_events:
            # The same ongoing story is often restated across consecutive days;
            # identical sentences add nothing to a similarity comparison.
            if event.text not in seen:
                seen.add(event.text)
                events.append(event)
    return events, failures


__all__ = [
    "ADAPTER",
    "DEFAULT_DAYS",
    "MIN_EVENT_LENGTH",
    "EditorialEvent",
    "collect_agenda",
    "fetch_day",
    "page_title_for",
    "parse_events",
    "strip_wikitext",
]
