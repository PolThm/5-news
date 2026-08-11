"""GDELT DOC 2.0 adapter.

The primary ingestion signal: free, no API key, 65 languages, with source
country and language on every article. Verified against the live API on
2026-08-10/11.

Three properties of this API shape everything below, and each of them is a trap
if you assume the obvious instead:

**There is no pagination.** ``maxrecords`` caps at 250 and stops — no offset, no
cursor, no page parameter. The only way past the ceiling is to split the query
by time. Worse, a window returning exactly 250 is *truncated*, not complete, so
250 must be read as a saturation signal and the window bisected. A collector
that requests 250 and moves on silently loses everything past the cap on any
busy day.

**Query errors arrive as HTTP 200 with a plain-text body.** Asking for 500
records returns ``200 A maximum of 250 records can be returned.`` — not JSON,
not an error status. Trusting ``status_code == 200`` means ingesting an error
message as if it were news.

**Country codes are FIPS 10-4, not ISO 3166.** ``CH`` is China in FIPS and
Switzerland in ISO; the UK is ``UK`` not ``GB``, Germany ``GM`` not ``DE``,
Japan ``JA`` not ``JP``. Reusing an ISO table would mis-attribute articles to
the wrong country — and country diversity is half the Consensus Score.

The response is also asymmetric with the query: queries take codes, responses
return full English names (``"sourcecountry": "France"``). Mapping back to Zone
slugs happens here, so nothing downstream ever sees a vendor-shaped value
(AD-13).
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pipeline.adapters import CollectionResult, Failure
from pipeline.domain import ArticleRecord

ADAPTER = "gdelt"

ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"

# Verified ceiling. Requesting more returns HTTP 200 with a plain-text refusal.
MAX_RECORDS = 250

# The documented limit is one request per 5 seconds, but observed behavior is a
# sticky per-IP cooldown that can persist far longer once tripped. Pacing well
# clear of the stated limit is cheaper than being throttled for minutes.
REQUEST_INTERVAL_SECONDS = 6.0

# Below this, bisecting further buys nothing — accept truncation and say so.
MIN_WINDOW = timedelta(minutes=1)


# FIPS 10-4 country codes for the eight Country Zones (PRD FR-3).
# NOT ISO 3166 — see the module docstring.
FIPS_BY_ZONE: dict[str, str] = {
    "france": "FR",
    "united-kingdom": "UK",
    "germany": "GM",
    "united-states": "US",
    "japan": "JA",
    "china": "CH",
    "india": "IN",
    "brazil": "BR",
}

# GDELT returns full English language names; the pipeline speaks two-letter
# codes. Only the languages the pipeline can act on need an entry — anything
# else falls back to a lowercased name, which is still honest data.
LANGUAGE_CODES: dict[str, str] = {
    "english": "en",
    "french": "fr",
    "spanish": "es",
    "german": "de",
    "portuguese": "pt",
    "japanese": "ja",
    "chinese": "zh",
    "hindi": "hi",
    "arabic": "ar",
    "russian": "ru",
    "italian": "it",
    "dutch": "nl",
}


class Response(Protocol):
    """The subset of an HTTP response this adapter needs.

    Narrow on purpose: it keeps the vendor client swappable and lets tests
    supply a plain object instead of mocking a library.
    """

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
        with urllib.request.urlopen(request, timeout=30) as handle:  # noqa: S310 - fixed https endpoint
            body = handle.read().decode("utf-8", errors="replace")
            return _UrllibResponse(handle.status, body, dict(handle.headers))
    except urllib.error.HTTPError as exc:  # 429 and friends arrive here
        body = exc.read().decode("utf-8", errors="replace")
        return _UrllibResponse(exc.code, body, dict(exc.headers or {}))


# --- Parsing -----------------------------------------------------------------


def format_query_datetime(moment: datetime) -> str:
    """Query format: 14 digits, UTC, no separators.

    Deliberately distinct from the response format (``YYYYMMDDTHHMMSSZ``) —
    confusing the two is a silent parse failure.
    """
    return moment.astimezone(UTC).strftime("%Y%m%d%H%M%S")


def parse_seendate(value: str) -> datetime:
    """Response format: ``YYYYMMDDTHHMMSSZ``, UTC."""
    return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def _slugify_country(name: str) -> str:
    """'United States' -> 'united-states', matching the Zone slugs."""
    return name.strip().lower().replace(" ", "-")


def _language_code(name: str) -> str:
    return LANGUAGE_CODES.get(name.strip().lower(), name.strip().lower())


def parse_articles(payload: dict[str, Any]) -> list[ArticleRecord]:
    """Turn a GDELT response into domain records.

    A row missing required fields is skipped rather than failing the batch —
    one malformed article should not cost a whole window's coverage.
    """
    records: list[ArticleRecord] = []
    for raw in payload.get("articles", []):
        try:
            records.append(
                ArticleRecord(
                    title=raw["title"],
                    url=raw["url"],
                    published_at=parse_seendate(raw["seendate"]),
                    source=raw["domain"],
                    source_country=_slugify_country(raw["sourcecountry"]),
                    language=_language_code(raw["language"]),
                    collected_by=ADAPTER,
                )
            )
        except (KeyError, ValueError):
            continue
    return records


def is_saturated(article_count: int) -> bool:
    """250 means the window was truncated, not that it held exactly 250."""
    return article_count >= MAX_RECORDS


def split_window(
    start: datetime, end: datetime
) -> tuple[tuple[datetime, datetime], tuple[datetime, datetime]] | None:
    """Bisect a time window, or return None when it is too narrow to matter."""
    if end - start <= MIN_WINDOW:
        return None
    midpoint = start + (end - start) / 2
    return (start, midpoint), (midpoint, end)


# --- Client ------------------------------------------------------------------


class GdeltClient:
    """Fetches article windows, respecting the ceiling and the throttle.

    ``fetch`` is injectable so tests can drive the error paths — HTTP 200 with
    a text body, 429, a raised connection error — without a network.
    """

    def __init__(
        self,
        fetch: Callable[[str], Response] | None = None,
        max_retries: int = 2,
        pace: bool = False,
    ) -> None:
        self._fetch = fetch or _default_fetch
        self._max_retries = max_retries
        self._pace = pace
        self._last_request_at: float | None = None

    def _wait_for_slot(self) -> None:
        if not self._pace or self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < REQUEST_INTERVAL_SECONDS:
            time.sleep(REQUEST_INTERVAL_SECONDS - elapsed)

    def _build_url(self, query: str, start: datetime, end: datetime) -> str:
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(MAX_RECORDS),
            "sort": "dateasc",
            "startdatetime": format_query_datetime(start),
            "enddatetime": format_query_datetime(end),
        }
        return f"{ENDPOINT}?{urllib.parse.urlencode(params)}"

    def fetch_window(self, query: str, start: datetime, end: datetime) -> CollectionResult:
        """One request for one window. Never raises."""
        url = self._build_url(query, start, end)
        window = f"{start.isoformat()}..{end.isoformat()}"

        for attempt in range(self._max_retries + 1):
            self._wait_for_slot()
            try:
                response = self._fetch(url)
            except Exception as exc:  # noqa: BLE001 - the boundary is the point (AD-10)
                return CollectionResult(
                    failures=[Failure(ADAPTER, f"{window}: request failed: {exc}")]
                )
            finally:
                self._last_request_at = time.monotonic()

            if response.status_code == 429:
                if attempt < self._max_retries:
                    # Observed cooldowns far exceed the documented 5s.
                    time.sleep(REQUEST_INTERVAL_SECONDS * (2 ** (attempt + 1)))
                    continue
                return CollectionResult(
                    failures=[
                        Failure(ADAPTER, f"{window}: throttled (429) after {attempt + 1} attempts")
                    ]
                )

            if response.status_code != 200:
                return CollectionResult(
                    failures=[Failure(ADAPTER, f"{window}: HTTP {response.status_code}")]
                )

            # HTTP 200 does not mean success — query errors come back as text.
            try:
                payload = json.loads(response.text) if response.text.strip() else {}
            except json.JSONDecodeError:
                detail = response.text.strip()[:200]
                return CollectionResult(
                    failures=[Failure(ADAPTER, f"{window}: query error: {detail}")]
                )

            return CollectionResult(articles=[r.to_dict() for r in parse_articles(payload)])

        return CollectionResult(failures=[Failure(ADAPTER, f"{window}: exhausted retries")])

    def collect(self, query: str, start: datetime, end: datetime) -> CollectionResult:
        """Fetch a window, bisecting recursively wherever it saturates.

        Deduplicates on URL: bisected windows share a boundary instant and can
        return the same article twice.
        """
        collected: dict[str, dict[str, Any]] = {}
        failures: list[Failure] = []
        self._collect_into(query, start, end, collected, failures)
        return CollectionResult(articles=list(collected.values()), failures=failures)

    def _collect_into(
        self,
        query: str,
        start: datetime,
        end: datetime,
        collected: dict[str, dict[str, Any]],
        failures: list[Failure],
    ) -> None:
        result = self.fetch_window(query, start, end)
        failures.extend(result.failures)

        if not is_saturated(len(result.articles)):
            for article in result.articles:
                collected.setdefault(article["url"], article)
            return

        halves = split_window(start, end)
        if halves is None:
            # Too narrow to bisect: keep what we have and say it is incomplete,
            # rather than pretending 250 was the true count.
            for article in result.articles:
                collected.setdefault(article["url"], article)
            failures.append(
                Failure(
                    ADAPTER,
                    f"{start.isoformat()}..{end.isoformat()}: saturated at {MAX_RECORDS} "
                    "and too narrow to split; coverage for this window is truncated",
                )
            )
            return

        for half_start, half_end in halves:
            self._collect_into(query, half_start, half_end, collected, failures)


def collect_world_day(now: datetime | None = None) -> CollectionResult:
    """The World / day collection the Build Order starts with.

    Widening to the full 15-Zone matrix is Story 1.5's scheduling concern; this
    is the one combination the inspection window needs.
    """
    end = now or datetime.now(UTC)
    start = end - timedelta(days=1)
    client = GdeltClient(pace=True)
    # A query needs at least one real operator. Sorting by language rather than
    # keyword keeps the result set representative of general coverage.
    return client.collect(
        query="sourcelang:eng OR sourcelang:fra OR sourcelang:spa", start=start, end=end
    )


__all__ = [
    "ADAPTER",
    "FIPS_BY_ZONE",
    "MAX_RECORDS",
    "GdeltClient",
    "collect_world_day",
    "format_query_datetime",
    "is_saturated",
    "parse_articles",
    "parse_seendate",
    "split_window",
]
