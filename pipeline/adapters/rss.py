"""RSS adapter.

Coverage that does not depend on a single upstream. GDELT is the primary
signal, but its rate limits and its rolling ~3-month window are outside this
project's control; a handful of major outlets' own feeds cost nothing and keep
collection working when GDELT is throttled.

RSS carries no source metadata of its own — a feed does not say what country it
represents — so country and language are configured per feed rather than
inferred. That configuration is the price of the resilience.

Produces the same ``ArticleRecord`` shape as the GDELT adapter, so nothing
downstream can tell the two apart except by reading ``collected_by`` (AD-13).
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


# A deliberately small set: enough to keep collection alive when GDELT is
# throttled, few enough to stay maintainable. Every country here is a Zone slug
# (PRD FR-3) — a feed attributed to anything else would be invisible to every
# Country Briefing.
FEEDS: tuple[Feed, ...] = (
    Feed("https://www.lemonde.fr/rss/une.xml", "lemonde.fr", "france", "fr"),
    Feed("https://www.francetvinfo.fr/titres.rss", "francetvinfo.fr", "france", "fr"),
    Feed("https://feeds.bbci.co.uk/news/world/rss.xml", "bbc.co.uk", "united-kingdom", "en"),
    Feed("https://www.theguardian.com/world/rss", "theguardian.com", "united-kingdom", "en"),
    Feed("https://rss.dw.com/rdf/rss-en-world", "dw.com", "germany", "en"),
    Feed("https://www.spiegel.de/international/index.rss", "spiegel.de", "germany", "en"),
    Feed("https://feeds.npr.org/1004/rss.xml", "npr.org", "united-states", "en"),
    Feed("https://www.japantimes.co.jp/feed/", "japantimes.co.jp", "japan", "en"),
    Feed("https://www.scmp.com/rss/91/feed", "scmp.com", "china", "en"),
    Feed("https://feeds.feedburner.com/ndtvnews-world-news", "ndtv.com", "india", "en"),
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
