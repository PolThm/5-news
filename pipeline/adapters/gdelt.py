"""GDELT GKG 2.1 raw-file adapter.

The primary ingestion signal: free, no API key, worldwide, with a title and
a language on every article. Verified against live files on 2026-08-18.

**Why raw files rather than the DOC 2.0 API.** Story 6.2 replaced the search
API with this. The API is an interactive search endpoint, and using it for
ingestion earned a sticky per-IP throttle: measured on 2026-08-18, roughly
one request in six succeeded even at the documented 6-second spacing, with
no ``Retry-After`` header to pace against. Every one of the eight recorded
production cycles carried a GDELT failure, so the corpus was in practice the
eleven RSS feeds alone. GDELT's own 429 body says it plainly: "All
high-traffic users should switch to our ngrams dataset." The project is
healthy — its 15-minute file pipeline is current — only the channel was
wrong. These files have no rate limit at all.

Four properties of this format shape everything below, and each is a trap if
you assume the obvious instead:

**There is no title column.** The GKG's 27 columns do not include one, which
makes the format look unusable for this pipeline — ``ArticleRecord.title`` is
required. The title is inside ``Extras`` (the last column) as
``<PAGE_TITLE>...</PAGE_TITLE>``, present on 100% of rows in both files
sampled, and carrying numeric HTML entities that must be decoded.

**There are two files per slot, and the English one is not enough.**
``.gkg.csv.zip`` is English-only (913 rows in the sampled slot).
``.translation.gkg.csv.zip`` is the multilingual companion (3,442 rows) and
is where French and Spanish coverage lives. A product publishing in three
languages needs both.

**The source's country is not in the file either.** ``V2Locations`` holds the
places an article *mentions*, not where its outlet is; the TLD is useless for
the 58% of domains on ``.com``. GDELT publishes a separate domain-to-country
lookup (``DOMAIN_COUNTRY_URL`` below) whose second column is a FIPS code —
the same vocabulary ``FIPS_BY_ZONE`` already speaks, so it inverts directly
into Zone slugs. Measured coverage on a live slot: 94.7%.

**Country codes are FIPS 10-4, not ISO 3166.** ``CH`` is China in FIPS and
Switzerland in ISO; the UK is ``UK`` not ``GB``, Germany ``GM`` not ``DE``,
Japan ``JA`` not ``JP``. Reusing an ISO table would mis-attribute articles to
the wrong country — and country diversity is half the Consensus Score.
"""

from __future__ import annotations

import csv
import html
import io
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pipeline.adapters import CollectionResult, Failure
from pipeline.domain import ArticleRecord

ADAPTER = "gdelt"

# The 15-minute file pipeline. Both names are needed per slot: the first is
# English-only, the second carries every other language.
FILE_BASE = "http://data.gdeltproject.org/gdeltv2"
ENGLISH_SUFFIX = "gkg.csv.zip"
TRANSLINGUAL_SUFFIX = "translation.gkg.csv.zip"

# GDELT's own domain -> FIPS country lookup ("Mapping The Media", May 2018).
# 189,545 rows, ~5.4 MB, fetched in ~0.6s. Deliberately not vendored: it is a
# published dataset that may be refreshed, and a stale committed copy would
# silently mis-attribute countries with no signal that it had drifted.
#
# HTTP, not HTTPS: data.gdeltproject.org serves a certificate for
# *.storage.googleapis.com. The same constraint already applies to the slot
# files, so this adds no new exposure — and the payload is a public lookup
# table, not a credential.
DOMAIN_COUNTRY_URL = (
    "http://data.gdeltproject.org/blog/2018-news-outlets-by-country-may2018-update"
    "/MASTER-GDELTDOMAINSBYCOUNTRY-MAY2018.TXT"
)

# Slots are published every 15 minutes; only :00/:15/:30/:45 timestamps exist.
SLOT_MINUTES = 15

# How much of the day to sample. All 96 slots would be ~418,000 articles and
# ~1.7 GB — impossible inside the job's timeout.
#
# The binding constraint is not download time but **clustering memory**, and
# it bites far sooner than the volume suggests. `cluster_vectors` builds a
# full pairwise distance matrix: pdist gives n(n-1)/2 float64s and squareform
# expands to n², so peak memory grows quadratically. Measured on live data:
#
#   8 slots / 3h apart -> 27,064 articles -> 24,400 groups -> ~7.1 GB peak
#   3 slots / 8h apart -> 10,026 articles ->  ~9,000 groups -> ~1.0 GB peak
#
# A GitHub runner has 7 GB total, shared with Python, numpy, and the articles
# themselves, so the 8-slot configuration OOMs rather than merely running
# slowly. Three slots leave real headroom while still collecting 27x the
# 11-feed RSS corpus this replaced.
#
# This is a coverage/cost decision, not a tuning constant: an Event breaking
# between two sampled slots is seen by fewer outlets than full coverage would
# show, so its Consensus Score understates reality. Spacing them evenly is
# what keeps that bias from favouring one timezone. Raising the count means
# recomputing the memory peak first — this is the constraint that decides it,
# not download time.
SLOTS_PER_COLLECTION = 3
SLOT_SPACING_HOURS = 8

# Politeness pacing between file fetches. These are static files with no
# documented rate limit and none observed, so this is courtesy rather than a
# constraint -- unlike the DOC API's 6s, which was a limit and still failed.
REQUEST_INTERVAL_SECONDS = 1.0

# Story 6.2 keeps the wall-clock bound Story 6.1 added: the request budget
# that used to sit beside it counted DOC API calls and has no meaning here.
# A cycle killed by the job timeout loses everything it has already done,
# including batches it has already paid for.
MAX_COLLECTION_SECONDS = 15 * 60

# Rows carry very large fields (GCAM, V2Themes run to tens of kilobytes).
# Python's default field limit raises on them, so raise it once at import
# rather than per-parse.
csv.field_size_limit(sys.maxsize)

# GKG 2.1 column positions actually read. Named rather than inlined so a
# format change fails somewhere legible.
_COL_DATE = 1
_COL_SOURCE = 3
_COL_URL = 4
# V2EnhancedLocations. Every place the article mentions, one entry per
# occurrence, `;`-separated, fields `#`-separated with the FIPS country code
# third. Repetition is the point: a country named eight times is what the
# article is about, one named once is usually incidental, and the counts are
# what `focus_countries` weighs. Verified against live files on 2026-08-19 --
# populated on 80.2% of rows, with a median of 1 distinct country per article
# and a median dominant share of 100%.
_COL_LOCATIONS = 10
_COL_TRANSLATION_INFO = 25
_COL_EXTRAS = 26
_GKG_COLUMNS = 27

_PAGE_TITLE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.DOTALL)
_SRCLC = re.compile(r"srclc:(\w+)")

# FIPS 10-4 codes for the countries this adapter can name. NOT ISO 3166 --
# see the module docstring. Spain is SP, not ES, for exactly that reason.
#
# Deliberately NOT trimmed alongside `pipeline.config.ZONES` when the routable
# Zones narrowed to World/Europe/France/Spain on 2026-08-19: this table does a
# different job. It resolves an *Article's origin country* so a Cluster's
# `countries` -- the "covered in N countries" proof shown to the reader -- can
# read "germany" instead of the bare FIPS "gm" that `zone_slug_for_fips`
# falls back to. Dropping a country here would not remove it from the corpus,
# it would only make its name unreadable wherever it appears as a source.
FIPS_BY_ZONE: dict[str, str] = {
    "france": "FR",
    "spain": "SP",
    "united-kingdom": "UK",
    "germany": "GM",
    "united-states": "US",
    "japan": "JA",
    "china": "CH",
    "india": "IN",
    "brazil": "BR",
}

# The lookup table speaks FIPS; Zone slugs are what the rest of the pipeline
# speaks. Derived from the table above so the two can never drift.
ZONE_BY_FIPS: dict[str, str] = {code: zone for zone, code in FIPS_BY_ZONE.items()}


def zone_slug_for_fips(fips: str | None) -> str:
    """A Zone slug for a FIPS code, or a stable slug for the rest of the world.

    The eight Country Zones get their real slug, because those are the Zones a
    reader can select. Every *other* country still gets a distinct value —
    lowercased FIPS, e.g. ``as`` for Australia — rather than being flattened
    into one bucket.

    That distinction is load-bearing and easy to get wrong (I did, first
    pass). ``cluster.py`` computes ``countries = frozenset(...)`` and the
    Consensus Score reports how many *distinct* countries covered an Event.
    Collapsing the ~36 non-Zone countries in a typical slot into a single
    ``unknown`` would make an Event covered by Italian, Korean, Greek and
    Taiwanese outlets report as one country instead of four — understating
    the very number the product asks readers to trust.

    ``unknown`` is reserved for a genuinely unresolved domain (~5% of rows),
    where no country is known at all.
    """
    if not fips:
        return "unknown"
    return ZONE_BY_FIPS.get(fips, fips.strip().lower())


# GDELT's translation info uses ISO 639-2/3 codes; the pipeline speaks
# two-letter codes. Only the languages the pipeline can act on need an entry --
# anything else falls back to the raw code, which is still honest data.
LANGUAGE_CODES: dict[str, str] = {
    "eng": "en",
    "fra": "fr",
    "spa": "es",
    "deu": "de",
    "ger": "de",
    "por": "pt",
    "jpn": "ja",
    "zho": "zh",
    "chi": "zh",
    "hin": "hi",
    "ara": "ar",
    "rus": "ru",
    "ita": "it",
    "nld": "nl",
}


class Response(Protocol):
    status_code: int
    content: bytes


class _UrllibResponse:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content


def _default_fetch(url: str) -> Response:
    request = urllib.request.Request(url, headers={"User-Agent": "5-news/0.1 (batch collector)"})
    try:
        with urllib.request.urlopen(request, timeout=60) as handle:  # noqa: S310 - fixed host
            return _UrllibResponse(handle.status, handle.read())
    except urllib.error.HTTPError as exc:
        return _UrllibResponse(exc.code, b"")


# --- Parsing -----------------------------------------------------------------


def slot_timestamps(
    now: datetime | None = None,
    count: int = SLOTS_PER_COLLECTION,
    spacing_hours: int = SLOT_SPACING_HOURS,
) -> list[str]:
    """The slot identifiers to fetch, newest first.

    Each is floored to a real 15-minute boundary, because those are the only
    timestamps that exist. The most recent boundary is skipped: a slot is
    published a few minutes after its timestamp, so asking for the current one
    is a reliable 404.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    floored = moment.replace(
        minute=(moment.minute // SLOT_MINUTES) * SLOT_MINUTES, second=0, microsecond=0
    ) - timedelta(minutes=SLOT_MINUTES)
    return [
        (floored - timedelta(hours=spacing_hours * i)).strftime("%Y%m%d%H%M%S")
        for i in range(count)
    ]


def parse_domain_country(text: str) -> dict[str, str]:
    """Parse the domain -> FIPS lookup into a dict.

    Three tab-separated columns, no header: domain, FIPS code, English name.
    The name is ignored -- Zone slugs come from ``ZONE_BY_FIPS``, not from
    slugifying prose.
    """
    table: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] and parts[1]:
            table[parts[0].strip().lower()] = parts[1].strip()
    return table


def country_for_domain(domain: str, table: dict[str, str]) -> str | None:
    """FIPS code for a source domain, or ``None`` when unknown.

    Falls back to progressively shorter suffixes because GDELT records the
    registrable domain while the GKG sometimes reports a subdomain:
    ``g1.globo.com`` is absent from the table, ``globo.com`` is present.
    Measured: exact matching alone resolves 93.5%, the suffix fallback takes
    it to 94.7%.
    """
    candidate = domain.strip().lower()
    if not candidate:
        return None
    if candidate in table:
        return table[candidate]
    parts = candidate.split(".")
    for i in range(1, len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in table:
            return table[suffix]
    return None


# A country must account for at least this share of an article's location
# mentions to count as something the article is about. Measured on a live
# slice (841 located articles): 98.5% of articles still keep a country at this
# threshold, while it drops the incidental tail -- a tennis report from the
# Cincinnati Open mentions the United States 50% of the time and Russia 20%
# (the player's nationality), and only the former is what the piece covers.
#
# The dominant country is always kept regardless, so an article with locations
# is never left unplaceable by arithmetic alone.
FOCUS_MENTION_SHARE = 0.30

# ...and be named more than once, unless it is the dominant country.
#
# The share test alone is weak when an article names few places: with three
# mentions spread over three countries, every incidental one clears 30%. That
# is how a suspended Australian tennis player reached the Europe Briefing on
# 2026-08-19, on a single passing mention each of the United Kingdom and
# Ukraine. Measured on a live slice, requiring two mentions lifts single-
# country articles from 86% to 90% and drops exactly that tail: "Remember
# Monday release new single" stops being about Switzerland (named once), and a
# National Trust site in Northumberland stops being about the United States.
#
# The honest cost: where the signal is a genuine 1-1 tie ("Williams' Instagram
# page revived to fight AI abuse", Australia once and the US once), this keeps
# whichever sorts dominant and discards the other. At one mention apiece there
# is no evidence to prefer either, so no threshold recovers that -- it trades
# an arbitrary inclusion for an arbitrary omission, and the omission at least
# keeps the Briefing's placements defensible.
FOCUS_MIN_MENTIONS = 2


def focus_countries(locations: str) -> tuple[str, ...]:
    """The countries an article is about, from a V2EnhancedLocations field.

    Returns Zone-style slugs (the same vocabulary as ``source_country``, via
    ``zone_slug_for_fips``) ordered most-mentioned first, or an empty tuple
    when the field carries no usable location -- which is the honest answer
    for ~20% of GKG rows, not a failure.
    """
    counts: Counter[str] = Counter()
    for entry in locations.split(";"):
        fields = entry.split("#")
        if len(fields) > 2 and fields[2].strip():
            counts[fields[2].strip()] += 1
    if not counts:
        return ()
    total = sum(counts.values())
    ranked = counts.most_common()
    dominant = ranked[0][0]
    kept = [
        code
        for code, n in ranked
        if code == dominant or (n / total >= FOCUS_MENTION_SHARE and n >= FOCUS_MIN_MENTIONS)
    ]
    return tuple(zone_slug_for_fips(code) for code in kept)


def parse_gkg_date(value: str) -> datetime:
    """Slot timestamp format: ``YYYYMMDDHHMMSS``, UTC."""
    return datetime.strptime(value.strip(), "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def _language_code(srclc: str | None) -> str:
    """Two-letter code for a GKG source language.

    ``TranslationInfo`` is blank for documents that were already in English,
    which is the signal for English rather than missing data.
    """
    if not srclc:
        return "en"
    return LANGUAGE_CODES.get(srclc.strip().lower(), srclc.strip().lower())


def parse_gkg(text: str, domain_country: dict[str, str]) -> list[ArticleRecord]:
    """Turn one GKG file into domain records.

    A row missing anything required is skipped rather than failing the file --
    one malformed row should not cost a slot's coverage. A row whose title is
    absent or blank after decoding is skipped too: an Article with no title
    cannot be deduped, clustered, or summarized, and admitting a placeholder
    would put that placeholder on the page.
    """
    records: list[ArticleRecord] = []
    for row in csv.reader(io.StringIO(text), delimiter="\t"):
        if len(row) < _GKG_COLUMNS:
            continue
        match = _PAGE_TITLE.search(row[_COL_EXTRAS])
        if not match:
            continue
        title = html.unescape(match.group(1)).strip()
        if not title:
            continue
        source = row[_COL_SOURCE].strip()
        fips = country_for_domain(source, domain_country)
        srclc = _SRCLC.search(row[_COL_TRANSLATION_INFO] or "")
        try:
            records.append(
                ArticleRecord(
                    title=title,
                    url=row[_COL_URL].strip(),
                    published_at=parse_gkg_date(row[_COL_DATE]),
                    source=source,
                    # Real country for every resolved domain, Zone slug or
                    # not -- see zone_slug_for_fips. An unresolved domain is
                    # "unknown" rather than dropped: the Article is still
                    # real coverage and still counts toward Independent
                    # Sources; it just cannot contribute to country
                    # diversity.
                    source_country=zone_slug_for_fips(fips),
                    language=_language_code(srclc.group(1) if srclc else None),
                    collected_by=ADAPTER,
                    mentioned_countries=focus_countries(row[_COL_LOCATIONS]),
                )
            )
        except (KeyError, ValueError):
            continue
    return records


def _unzip_single(payload: bytes) -> str:
    """The one CSV inside a slot archive, decoded leniently.

    GKG files carry raw bytes from the open web; a strict decode raises on
    the first malformed sequence and costs the whole slot.
    """
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = archive.namelist()[0]
        return archive.read(name).decode("utf-8", errors="replace")


# --- Client ------------------------------------------------------------------


class GdeltClient:
    """Fetches raw GKG slot files.

    ``fetch`` is injectable so tests can drive every error path -- a 404, a
    corrupt archive, a raised connection error -- without a network.
    """

    def __init__(
        self,
        fetch: Callable[[str], Response] = _default_fetch,
        pace: bool = False,
    ) -> None:
        self._fetch = fetch
        self._pace = pace
        self._last_request_at: float | None = None

    def _wait_for_slot(self) -> None:
        if not self._pace or self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < REQUEST_INTERVAL_SECONDS:
            time.sleep(REQUEST_INTERVAL_SECONDS - elapsed)

    def fetch_file(self, url: str) -> tuple[str | None, Failure | None]:
        """One archive, unzipped, or the reason it could not be. Never raises."""
        self._wait_for_slot()
        try:
            response = self._fetch(url)
        except Exception as exc:  # noqa: BLE001 - the boundary is the point (AD-10)
            return None, Failure(ADAPTER, f"{url}: request failed: {exc}")
        finally:
            self._last_request_at = time.monotonic()

        if response.status_code != 200:
            return None, Failure(ADAPTER, f"{url}: HTTP {response.status_code}")
        try:
            return _unzip_single(response.content), None
        except (zipfile.BadZipFile, IndexError, OSError) as exc:
            return None, Failure(ADAPTER, f"{url}: could not read archive: {exc}")

    def fetch_domain_country(self) -> tuple[dict[str, str], Failure | None]:
        """The domain -> FIPS lookup, or an empty table plus a failure.

        Degrades rather than aborting: without it every Article lands in
        ``source_country="unknown"``, so Zone Briefings thin out and country
        diversity stops counting -- a visible, recorded shortfall, not a
        crashed cycle (AD-10).
        """
        self._wait_for_slot()
        try:
            response = self._fetch(DOMAIN_COUNTRY_URL)
        except Exception as exc:  # noqa: BLE001 - adapter boundary
            return {}, Failure(ADAPTER, f"domain-country lookup failed: {exc}")
        finally:
            self._last_request_at = time.monotonic()

        if response.status_code != 200:
            return {}, Failure(ADAPTER, f"domain-country lookup: HTTP {response.status_code}")
        table = parse_domain_country(response.content.decode("utf-8", errors="replace"))
        if not table:
            return {}, Failure(ADAPTER, "domain-country lookup was empty")
        return table, None

    def collect(self, now: datetime | None = None) -> CollectionResult:
        """Fetch the sampled slots and return every Article they carry.

        Deduplicates on URL: the same article appears in more than one slot,
        and in both the English and translingual files.
        """
        deadline = time.monotonic() + MAX_COLLECTION_SECONDS
        failures: list[Failure] = []

        domain_country, lookup_failure = self.fetch_domain_country()
        if lookup_failure is not None:
            failures.append(lookup_failure)

        collected: dict[str, dict] = {}
        for slot in slot_timestamps(now):
            if time.monotonic() >= deadline:
                failures.append(
                    Failure(
                        ADAPTER,
                        f"collection deadline of {MAX_COLLECTION_SECONDS}s reached; "
                        "remaining slots skipped and coverage is incomplete",
                    )
                )
                break
            for suffix in (ENGLISH_SUFFIX, TRANSLINGUAL_SUFFIX):
                url = f"{FILE_BASE}/{slot}.{suffix}"
                text, failure = self.fetch_file(url)
                if failure is not None:
                    failures.append(failure)
                    continue
                for record in parse_gkg(text or "", domain_country):
                    collected.setdefault(record.url, record.to_dict())

        if not collected:
            failures.append(
                Failure(ADAPTER, "no slot yielded any Article; coverage for this cycle is empty")
            )
        return CollectionResult(articles=list(collected.values()), failures=failures)


def collect_world_day(now: datetime | None = None) -> CollectionResult:
    """The day's collection: sampled slots from GDELT's raw file pipeline.

    Name kept from the DOC 2.0 era so `collect_all` and its tests read the
    same; the channel beneath it is entirely different.
    """
    return GdeltClient(pace=True).collect(now=now)


__all__ = [
    "ADAPTER",
    "DOMAIN_COUNTRY_URL",
    "FIPS_BY_ZONE",
    "FOCUS_MENTION_SHARE",
    "FOCUS_MIN_MENTIONS",
    "LANGUAGE_CODES",
    "MAX_COLLECTION_SECONDS",
    "SLOTS_PER_COLLECTION",
    "ZONE_BY_FIPS",
    "ArticleRecord",
    "CollectionResult",
    "Failure",
    "GdeltClient",
    "collect_world_day",
    "focus_countries",
    "country_for_domain",
    "zone_slug_for_fips",
    "parse_domain_country",
    "parse_gkg",
    "parse_gkg_date",
    "slot_timestamps",
]
