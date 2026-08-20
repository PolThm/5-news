"""RSS adapter: the serious press, read from the feeds they publish.

GDELT indexes what it can crawl, which turns out to be the long tail. Measured
2026-08-19 on a 10,331-article cycle: Le Monde, Le Figaro, Libération, Reuters,
AP, the NYT, the FT, El Mundo, Corriere and FAZ returned ZERO articles, while
iheart.com alone returned 298 and the published Briefings were built from small
US local TV stations and Balkan portals. Nothing downstream can fix a corpus
that does not contain the news.

So this reads the feeds those outlets publish themselves -- a channel built to
be read by machines, requiring no key, no account and no circumvention. It was
deleted in Story 6.2 when the project moved to GDELT and never restored after
GDELT was fixed; this is that adapter rebuilt, with a far wider and more
deliberate feed set.

**Only facts are persisted.** This is the design constraint that shapes
everything here, and it comes from what press-publishers' rights actually
cover. DSM Recital 57, verbatim: those rights "should not extend to acts of
hyperlinking" and "should also not extend to mere facts reported in press
publications." Recital 9 adds that mining mere facts "requires no
authorisation". So the event, who reported it, how many outlets in how many
countries, and the URL are all outside the right -- while the publisher's own
headline is inside it.

A headline is therefore used and discarded, never stored: it is read into
memory, embedded to group articles covering one event, and passed to the
summarizer that writes this project's own text. It does not reach a published
Briefing (see `pipeline.stages.publish`, which strips it). The CJEU brackets
this precisely -- PRCA v NLA allowed transient on-screen and cache copies made
while viewing, while Infopaq failed exactly because an 11-word extract was
*printed*, making deletion "entirely dependent on the will of the user". The
line is persistence, not retrieval.

**Feed selection.** Curated fronts ("une", "portada", "top stories") are
preferred over firehoses: this adapter exists to add editorial judgment, and a
front page is a newsroom stating what it considers today's news. Every feed
below was verified to respond 200 with real items on 2026-08-19.

Wire agency attribution from `dc:creator` is preserved from the original
adapter and matters more than it looks: it is what feeds dedupe layer 2, which
has been dead code for as long as GDELT (which never provides it) was the only
source.
"""

from __future__ import annotations

import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol
from xml.etree import ElementTree

from pipeline.adapters import CollectionResult, Failure
from pipeline.config import country_slugs_in_text
from pipeline.domain import ArticleRecord

ADAPTER = "rss"

ATOM_NS = "{http://www.w3.org/2005/Atom}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"
RDF_NS = "{http://purl.org/rss/1.0/}"

# Story 2.3 (FR-10 layer 2): a narrow, RSS-only wire-attribution signal.
#
# There is no cross-source attribution field — GDELT exposes none at all
# (confirmed against a live response: title/url/seendate/domain/language/
# sourcecountry is the complete schema), and RSS's Dublin Core dc:creator is
# overloaded: the same element holds a human byline for original reporting
# and a wire-service name for republished dispatches, with no way to tell
# them apart except by matching known agency names. Some configured feeds
# (BBC) never populate dc:creator at all — that is a real, accepted gap in
# this layer's coverage, not a bug.
#
# Deliberately a small, explicit table rather than a fuzzy matcher: a missed
# variant means an Article is (correctly, safely) treated as independent,
# which is the harmless direction of error. A false match would inflate the
# Independent Source count — the display-facing number this whole pipeline
# protects — so guessing is not an acceptable tradeoff here.
_WIRE_SERVICE_NAMES: dict[str, str] = {
    "ap": "AP",
    "associated press": "AP",
    "the associated press": "AP",
    "ap news": "AP",
    "by the associated press": "AP",
    "reuters": "Reuters",
    "reuters staff": "Reuters",
    "by reuters staff": "Reuters",
    "reuters editorial": "Reuters",
    "afp": "AFP",
    "agence france-presse": "AFP",
    "by afp": "AFP",
}


def resolve_wire_agency(creator: str | None) -> str | None:
    """Match a raw ``dc:creator`` value against known wire-service names.

    Case-insensitive; anything unrecognized — including an ordinary human
    byline, which shares this same overloaded field — resolves to ``None``.

    Normalized the same way ``normalize_title`` handles headlines (NFC,
    collapsed internal whitespace): an XML-formatted feed can carry a
    double space or a non-breaking space around ``dc:creator``'s text, and
    an accented name (e.g. a future agency with a diacritic) could arrive in
    a different Unicode normal form. Neither should cost a match against an
    otherwise-identical, exact-string table entry.
    """
    if not creator:
        return None
    normalized = unicodedata.normalize("NFC", creator).strip()
    normalized = " ".join(normalized.split())
    return _WIRE_SERVICE_NAMES.get(normalized.lower())


@dataclass(frozen=True, slots=True)
class Feed:
    """One outlet's feed, with the attribution RSS itself does not provide."""

    url: str
    source: str
    source_country: str
    language: str


# Verified to respond 200 with real items on 2026-08-19. `source_country` is
# where the newsroom sits, which is what the Consensus Score counts; it is NOT
# where a story happened (`mentioned_countries`, read from the article's own
# locations, does that).
#
# Curated fronts first for each outlet, because a front page is a newsroom
# saying what today's news is -- the judgment this adapter exists to add.
FEEDS: tuple[Feed, ...] = (
    # --- France ---
    Feed("https://www.lemonde.fr/rss/une.xml", "lemonde.fr", "france", "fr"),
    Feed("https://www.lemonde.fr/international/rss_full.xml", "lemonde.fr", "france", "fr"),
    Feed("https://www.lemonde.fr/europe/rss_full.xml", "lemonde.fr", "france", "fr"),
    Feed("https://www.lefigaro.fr/rss/figaro_actualites.xml", "lefigaro.fr", "france", "fr"),
    Feed("https://www.lefigaro.fr/rss/figaro_international.xml", "lefigaro.fr", "france", "fr"),
    # Libération's documented /rss/ path 403s; only this Arc feed answers.
    Feed(
        "https://www.liberation.fr/arc/outboundfeeds/rss-all/?outputType=xml",
        "liberation.fr",
        "france",
        "fr",
    ),
    Feed("https://www.la-croix.com/RSS", "la-croix.com", "france", "fr"),
    Feed("https://www.mediapart.fr/articles/feed", "mediapart.fr", "france", "fr"),
    Feed("https://www.francetvinfo.fr/titres.rss", "francetvinfo.fr", "france", "fr"),
    Feed("https://www.francetvinfo.fr/monde.rss", "francetvinfo.fr", "france", "fr"),
    Feed("https://www.france24.com/fr/rss", "france24.com", "france", "fr"),
    Feed("https://www.rfi.fr/fr/rss", "rfi.fr", "france", "fr"),
    # More French newsrooms, because a France Briefing was thin for a
    # structural reason rather than a quiet news day.
    #
    # An event needs two reference newsrooms to exist and three to qualify on
    # editorial weight alone. With eight French sources -- two of which,
    # France 24 and RFI, are outward-facing international services -- French
    # domestic news had about six newsrooms to draw three from, and measured on
    # 2026-08-20 only three French events cleared the floor out of a 53-event
    # pool. The corpus was too thin on exactly the country a country Briefing is
    # for.
    #
    # Verified responding with parseable items on 2026-08-20, item counts as
    # measured then. Several obvious candidates are absent because they refuse
    # us: Les Echos, Le Point, Sud Ouest and Marianne all answer 403, Le
    # Parisien and La Tribune parse to zero items, and L'Humanite and L'Opinion
    # 404. Courrier International responds but is deliberately excluded -- it
    # translates and republishes other newsrooms, which is the republisher tier,
    # not an independent editorial judgment.
    Feed("https://www.nouvelobs.com/rss.xml", "nouvelobs.com", "france", "fr"),  # 200
    Feed("https://www.lexpress.fr/rss/alaune.xml", "lexpress.fr", "france", "fr"),  # 100
    Feed("https://www.challenges.fr/rss.xml", "challenges.fr", "france", "fr"),  # 50
    Feed("https://www.radiofrance.fr/franceinter/rss", "radiofrance.fr", "france", "fr"),  # 20
    Feed("https://www.ouest-france.fr/rss/une", "ouest-france.fr", "france", "fr"),  # 10
    # --- Spain ---
    Feed(
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
        "elpais.com",
        "spain",
        "es",
    ),
    Feed(
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/internacional/portada",
        "elpais.com",
        "spain",
        "es",
    ),
    Feed("https://www.abc.es/rss/2.0/portada/", "abc.es", "spain", "es"),
    Feed("https://www.abc.es/rss/feeds/abc_Internacional.xml", "abc.es", "spain", "es"),
    Feed("https://www.lavanguardia.com/rss/internacional.xml", "lavanguardia.com", "spain", "es"),
    Feed("https://www.eldiario.es/rss/internacional/", "eldiario.es", "spain", "es"),
    # More Spanish newsrooms, for the same structural reason as the French block
    # above: five sources gave Spanish domestic news too few newsrooms to draw
    # three from, and only four Spain events cleared the floor on 2026-08-20.
    #
    # Verified on 2026-08-20 with the item counts shown. Absent because they
    # refuse or return nothing: La Razon, Publico, La Voz de Galicia and Heraldo
    # 404, Nius 403, El Periodico parses to zero.
    Feed("https://www.eldiario.es/rss/", "eldiario.es", "spain", "es"),  # 90, front page
    Feed("https://e00-expansion.uecdn.es/rss/portada.xml", "expansion.com", "spain", "es"),  # 67
    Feed("https://e00-elmundo.uecdn.es/elmundo/rss/espana.xml", "elmundo.es", "spain", "es"),  # 54
    Feed("https://www.infolibre.es/rss/", "infolibre.es", "spain", "es"),  # 50
    Feed("https://api2.rtve.es/rss/temas_noticias.xml", "rtve.es", "spain", "es"),  # 40
    Feed("https://www.elespanol.com/rss/", "elespanol.com", "spain", "es"),  # 30
    Feed("https://e00-elmundo.uecdn.es/elmundo/rss/portada.xml", "elmundo.es", "spain", "es"),  # 29
    Feed("https://rss.elconfidencial.com/espana/", "elconfidencial.com", "spain", "es"),  # 15
    Feed("https://www.europapress.es/rss/rss.aspx", "europapress.es", "spain", "es"),  # 10
    Feed("https://www.20minutos.es/rss/internacional/", "20minutos.es", "spain", "es"),
    # --- Europe and the wider world ---
    Feed("https://www.theguardian.com/world/rss", "theguardian.com", "united-kingdom", "en"),
    Feed("https://feeds.bbci.co.uk/news/world/rss.xml", "bbc.co.uk", "united-kingdom", "en"),
    Feed(
        "https://feeds.bbci.co.uk/news/world/europe/rss.xml",
        "bbc.co.uk",
        "united-kingdom",
        "en",
    ),
    Feed("https://www.spiegel.de/international/index.rss", "spiegel.de", "germany", "en"),
    Feed("https://www.tagesschau.de/xml/rss2/", "tagesschau.de", "germany", "de"),
    Feed("https://rss.dw.com/rdf/rss-en-world", "dw.com", "germany", "en"),
    Feed("https://newsfeed.zeit.de/politik/index", "zeit.de", "germany", "de"),
    Feed("https://www.euronews.com/rss?level=vertical&name=my-europe", "euronews.com", "it", "en"),
    Feed("https://www.euronews.com/rss?level=theme&name=news", "euronews.com", "it", "en"),
    Feed("https://www.repubblica.it/rss/esteri/rss2.0.xml", "repubblica.it", "it", "it"),
    Feed("https://xml2.corriereobjects.it/rss/esteri.xml", "corriere.it", "it", "it"),
    # ANSA is a wire agency, and dedupe's whole purpose is telling a wire
    # dispatch apart from independent reporting -- having one in the corpus
    # makes that detection testable against reality rather than assumed.
    Feed("https://www.ansa.it/english/english_rss.xml", "ansa.it", "it", "en"),
    Feed("https://feeds.nos.nl/nosnieuwsbuitenland", "nos.nl", "nl", "nl"),
    Feed("https://feeds.npr.org/1004/rss.xml", "npr.org", "united-states", "en"),
    Feed("https://www.pbs.org/newshour/feeds/rss/world", "pbs.org", "united-states", "en"),
    Feed("https://g1.globo.com/rss/g1/mundo/", "globo.com", "brazil", "pt"),
)


class Response(Protocol):
    status_code: int
    text: str
    headers: dict[str, str]


class _UrllibResponse:
    def __init__(self, status_code: int, text: str, headers: dict[str, str]) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers


def _default_fetch(url: str) -> Response:
    request = urllib.request.Request(url, headers={"User-Agent": "5-news/0.1 (batch collector)"})
    try:
        with urllib.request.urlopen(request, timeout=30) as handle:  # noqa: S310 - configured https feeds
            body = handle.read().decode("utf-8", errors="replace")
            return _UrllibResponse(handle.status, body, dict(handle.headers))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return _UrllibResponse(exc.code, body, dict(exc.headers or {}))


def parse_rfc2822(value: str) -> datetime:
    """RSS dates are RFC 2822. Normalized to UTC — the pipeline speaks UTC
    everywhere internally (spine conventions)."""
    parsed = parsedate_to_datetime(value)
    if parsed is None:
        raise ValueError(f"unparseable date: {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_iso8601_date(value: str) -> datetime:
    """Atom's updated/published, and RSS 1.0/RDF's dc:date, use ISO-8601
    rather than RSS 2.0's RFC 2822."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_feed(body: str, source: str, source_country: str, language: str) -> list[ArticleRecord]:
    """Parse RSS or Atom into domain records.

    Returns an empty list rather than raising on malformed XML: a feed that
    served an error page instead of a feed is a coverage gap for the caller to
    record, not an exception to propagate.
    """
    try:
        root = ElementTree.fromstring(body)  # noqa: S314 - feeds are configured, not user input
    except ElementTree.ParseError:
        return []

    records: list[ArticleRecord] = []
    seen_links: set[str] = set()

    # RSS 2.0's <item> is unprefixed; RSS 1.0/RDF's is namespaced under
    # http://purl.org/rss/1.0/ (confirmed live on dw.com, whose <rdf:RDF>
    # root declares that as the default namespace). A feed is one or the
    # other, never both, but iterating both tags unconditionally is
    # harmless -- an RSS 2.0 feed has zero RDF_NS-prefixed items and vice
    # versa. seen_links guards against ElementTree.iter() ever double-
    # visiting an element under two equivalent tag spellings.
    for item in [*root.iter("item"), *root.iter(f"{RDF_NS}item")]:
        link = item.findtext("link") or item.findtext(f"{RDF_NS}link")
        if link and link in seen_links:
            continue
        # RSS 2.0 dates items with pubDate (RFC 2822). RSS 1.0/RDF has no
        # pubDate at all and uses Dublin Core's dc:date (ISO-8601) instead —
        # the same namespace this adapter already reads dc:creator from.
        # Without this fallback, every item from an RDF feed fails
        # _record_from's "no date, no record" check and is silently
        # dropped, which is exactly what happened to dw.com before this was
        # noticed against a real cycle.
        pub_date = item.findtext("pubDate")
        if pub_date:
            date_text, date_parser = pub_date, parse_rfc2822
        else:
            date_text, date_parser = item.findtext(f"{DC_NS}date"), _parse_iso8601_date
        record = _record_from(
            title=item.findtext("title") or item.findtext(f"{RDF_NS}title"),
            link=link,
            date_text=date_text,
            date_parser=date_parser,
            source=source,
            source_country=source_country,
            language=language,
            wire_agency=resolve_wire_agency(item.findtext(f"{DC_NS}creator")),
        )
        if record:
            records.append(record)
            if link:
                seen_links.add(link)

    # Atom entries do not get dc:creator extraction: none of the currently
    # configured feeds are Atom, and Dublin Core-in-Atom is a separate,
    # unconfirmed convention — not worth speculatively supporting.
    for entry in root.iter(f"{ATOM_NS}entry"):  # Atom
        link_element = entry.find(f"{ATOM_NS}link")
        record = _record_from(
            title=entry.findtext(f"{ATOM_NS}title"),
            link=link_element.get("href") if link_element is not None else None,
            date_text=entry.findtext(f"{ATOM_NS}updated") or entry.findtext(f"{ATOM_NS}published"),
            date_parser=_parse_iso8601_date,
            source=source,
            source_country=source_country,
            language=language,
        )
        if record:
            records.append(record)

    return records


def _record_from(
    title: str | None,
    link: str | None,
    date_text: str | None,
    date_parser: Callable[[str], datetime],
    source: str,
    source_country: str,
    language: str,
    wire_agency: str | None = None,
) -> ArticleRecord | None:
    """Build a record, or None when the item lacks what a record requires.

    An Article without a timestamp cannot be placed in a Period window, so it
    is dropped rather than guessed at.
    """
    if not title or not link or not date_text:
        return None
    try:
        published_at = date_parser(date_text)
    except (ValueError, TypeError):
        return None
    return ArticleRecord(
        title=title.strip(),
        url=link.strip(),
        published_at=published_at,
        source=source,
        source_country=source_country,
        language=language,
        collected_by=ADAPTER,
        wire_agency=wire_agency,
        # Read out of the headline, because RSS publishes no locations at all.
        #
        # That absence had a cost: measured on 2026-08-20, 0 of 1,151 reference
        # articles carried `mentioned_countries` against 8,790 of 11,120 from
        # GDELT, so an event covered only by the French press -- a French court
        # case, the thing a France Briefing exists for -- could not be placed in
        # France. Both country Briefings fell back to Europe and served an item
        # about Harry and Meghan.
        #
        # The headline, not the whole entry: a summary or a category list names
        # countries the article merely mentions, and `mentioned_countries` is
        # meant to say what a piece is ABOUT. A headline naming a country is
        # about that country.
        mentioned_countries=tuple(country_slugs_in_text(title)),
    )


class RssClient:
    """Fetches a set of feeds, reporting each failure without abandoning the rest."""

    def __init__(self, fetch: Callable[[str], Response] | None = None) -> None:
        self._fetch = fetch or _default_fetch

    def collect(self, feeds: Iterable[Feed] | None = None) -> CollectionResult:
        articles: list[dict[str, str]] = []
        failures: list[Failure] = []
        seen: set[str] = set()

        for feed in feeds if feeds is not None else FEEDS:
            try:
                response = self._fetch(feed.url)
            except Exception as exc:  # noqa: BLE001 - the boundary is the point (AD-10)
                failures.append(Failure(ADAPTER, f"{feed.source}: request failed: {exc}"))
                continue

            if response.status_code != 200:
                failures.append(Failure(ADAPTER, f"{feed.source}: HTTP {response.status_code}"))
                continue

            records = parse_feed(
                response.text,
                source=feed.source,
                source_country=feed.source_country,
                language=feed.language,
            )
            if not records:
                failures.append(Failure(ADAPTER, f"{feed.source}: no items parsed from response"))
                continue

            for record in records:
                if record.url not in seen:
                    seen.add(record.url)
                    articles.append(record.to_dict())

        return CollectionResult(articles=articles, failures=failures)


__all__ = ["ADAPTER", "FEEDS", "Feed", "RssClient", "parse_feed", "parse_rfc2822"]
