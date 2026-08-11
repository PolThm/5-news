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


def _parse_atom_date(value: str) -> datetime:
    """Atom uses ISO-8601 rather than RFC 2822."""
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

    for item in root.iter("item"):  # RSS
        record = _record_from(
            title=item.findtext("title"),
            link=item.findtext("link"),
            date_text=item.findtext("pubDate"),
            date_parser=parse_rfc2822,
            source=source,
            source_country=source_country,
            language=language,
        )
        if record:
            records.append(record)

    for entry in root.iter(f"{ATOM_NS}entry"):  # Atom
        link_element = entry.find(f"{ATOM_NS}link")
        record = _record_from(
            title=entry.findtext(f"{ATOM_NS}title"),
            link=link_element.get("href") if link_element is not None else None,
            date_text=entry.findtext(f"{ATOM_NS}updated") or entry.findtext(f"{ATOM_NS}published"),
            date_parser=_parse_atom_date,
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
