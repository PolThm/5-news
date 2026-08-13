// Story 5.2's pure caching-strategy logic (AD-8): which requests are
// Briefing content (network-first, short-timeout, cache as fallback
// only) versus hashed/effectively-immutable assets (cache-first).
//
// This file is imported ONLY by its own test file (sw-logic.test.ts) --
// it is NOT imported by site/public/sw.js, which cannot import TypeScript
// or anything under src/ (Astro copies public/ byte-for-byte, unprocessed;
// nothing in that directory goes through the bundler). sw.js hand-mirrors
// these same two functions as plain JS, the same "one owner conceptually,
// two hand-kept copies practically" pattern already established for
// briefing.ts <-> period-switcher.ts across Stories 4.2-4.7, for the same
// underlying reason: Astro/Node-side lib code isn't bundled for a context
// outside the main site bundle. Keep both copies in sync by hand whenever
// either changes.

export type RequestClass = "network-first" | "cache-first" | "passthrough";

// Hashed assets Astro emits under /_astro/ (JS/CSS, content-hash changes
// per build -- classified by path prefix, never a specific hardcoded
// hashed filename, since the hash itself is unpredictable ahead of a real
// build). manifest.json and the icon files are unhashed but effectively
// immutable between deploys (Story 5.1), so they're treated the same way.
const CACHE_FIRST_EXACT_PATHS = new Set(["/manifest.json", "/icon-192.png", "/icon-512.png"]);

export function classifyRequest(url: string): RequestClass {
  const { pathname } = new URL(url, "https://example.invalid");

  if (pathname === "/sw.js") return "passthrough";
  if (pathname.startsWith("/_astro/")) return "cache-first";
  if (CACHE_FIRST_EXACT_PATHS.has(pathname)) return "cache-first";
  if (pathname.startsWith("/briefings/") && pathname.endsWith(".json")) return "network-first";
  if (pathname.endsWith(".html")) return "network-first";

  // A path with no file extension in its last segment is treated as a
  // page navigation -- matches Astro's real route shape (`/`,
  // `/<lang>/<zone>/<period>` have no extension) without hardcoding the
  // Zone/Period/Language slug patterns here (those already live in
  // period-switcher.ts's own types; duplicating them into this
  // classifier would be a second copy of the same knowledge for no
  // benefit). Both real and not-actually-real page-shaped paths get
  // network-first: a fetch handler sees only the URL, not whether the
  // route exists, so an unknown page-shaped path degrades the same way a
  // real one would on a genuine 404 from the network.
  const lastSegment = pathname.slice(pathname.lastIndexOf("/") + 1);
  if (!lastSegment.includes(".")) return "network-first";

  // Anything else (an unrecognized file extension under an unrecognized
  // path) is neither a known Briefing-content shape nor a known
  // cache-first asset shape -- fall through to passthrough rather than
  // silently mis-classifying it as one or the other.
  return "passthrough";
}

// Races a promise against a timeout, WITHOUT using stale-while-revalidate
// semantics (AD-8 explicitly forbids it for Briefing content) -- this
// helper only ever resolves/rejects once, with whichever of the two
// settles first, and clears its own timer so it never fires after the
// real promise has already settled (no lingering handle, no risk of an
// unhandled-rejection warning from a timeout that fires after the caller
// has moved on).
export function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error(`withTimeout: timeout after ${ms}ms`));
    }, ms);

    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

// Minimal shapes covering only what networkFirst/cacheFirst/eviction
// actually use from the real fetch/Cache Storage APIs -- narrow enough
// to fake easily in tests, without pulling in a full Service Worker
// environment.
export interface ResponseLike {
  ok: boolean;
  contentType?: string;
  clone(): ResponseLike;
  text(): Promise<string>;
}
export interface CacheLike {
  match(request: string): Promise<ResponseLike | undefined>;
  put(request: string, response: ResponseLike): Promise<void>;
  keys(): Promise<string[]>;
  delete(request: string): Promise<boolean>;
}
export interface CacheStorageLike {
  open(name: string): Promise<CacheLike>;
  match(request: string): Promise<ResponseLike | undefined>;
}

// Story 5.4 (AC1): a response built from an offline-fallback path,
// distinguished from a normal ResponseLike by carrying the exact HTML
// body/lang the caller (sw.js) needs to construct a real Response --
// networkFirst decides WHAT to serve; sw.js's own thin wrapper is
// responsible for turning this description into an actual browser
// Response object (new Response(...), Headers, etc. -- none of which
// exist in this pure-logic module's own test environment).
export type NetworkFirstOutcome =
  | { kind: "network-success"; response: ResponseLike }
  | { kind: "offline-cache-hit"; cachedResponse: ResponseLike; isHtml: boolean }
  | { kind: "offline-no-cache"; lang: OfflineLanguage };

// Story 5.4 (AC1, AC2, NFR-6): "network-first" is not a single eviction
// pool -- a page navigation (e.g. /fr/world/day) and a /briefings/*.json
// fetch are two DIFFERENT representations of the same underlying
// Briefing, produced by two different client actions (a real navigation
// vs. a mad-libs click's in-place fetch, per period-switcher.ts's own
// history.pushState-based update). A reader who loads a page and then
// clicks a mad-libs word never triggers a second real navigation, so the
// SW's fetch handler never re-caches HTML for the new Zone/Period/
// Language -- if a single eviction pool covered both shapes, that JSON
// write would evict the still-currently-displayed page's own cached
// HTML with nothing to replace it, and a later offline reload would
// wrongly fall all the way through to the "nothing cached" page instead
// of AC1's "last-viewed, from an earlier cycle" banner. Each shape gets
// its own eviction pool instead -- the cache holds at most one page
// entry AND at most one JSON entry at a time (still "the reader's
// single last-viewed Briefing," just represented in the two forms this
// site's own architecture actually produces), never accumulating either
// shape across multiple Zone/Period/Language combinations.
export function isJsonBriefingFetch(url: string): boolean {
  const { pathname } = new URL(url, "https://example.invalid");
  return pathname.startsWith("/briefings/") && pathname.endsWith(".json");
}

export function evictOtherNetworkFirstEntries(
  existingNetworkFirstKeys: string[],
  newRequest: string
): string[] {
  const newRequestIsJson = isJsonBriefingFetch(newRequest);
  return existingNetworkFirstKeys.filter(
    (key) => key !== newRequest && isJsonBriefingFetch(key) === newRequestIsJson
  );
}

// Network-first, short-timeout, cache as fallback ONLY -- mirrors
// sw.js's own networkFirst exactly, including the fix for a real bug
// Blind Hunter review caught: the cache write is attached to the real
// fetch's own .then, not gated behind whichever branch of the timeout
// race wins, so a fetch that loses the race (times out) but eventually
// succeeds still updates the cache when it arrives, rather than leaving
// the cache stale on every timed-out-but-working visit.
//
// Story 5.4 (AC2): writes the new response FIRST, then evicts every
// other entry in the SAME sub-pool (page vs. JSON, per
// evictOtherNetworkFirstEntries's own reasoning) -- never the other
// order. Deleting first would open a real (if brief) window with ZERO
// cached entries in that sub-pool, during which a concurrent offline
// read (a second tab, or this same tab retrying after a transient blip)
// would see no cache hit at all and fall through to the "nothing
// cached" offline page, even though a perfectly good previous Briefing
// was on disk moments before and after. Writing first means the cache
// briefly holds two entries at worst, never zero.
//
// Story 5.4 (AC1, AC3): returns a discriminated NetworkFirstOutcome
// describing WHAT to serve, not a finished Response -- constructing a
// real browser Response (new Response(...), Headers) has no equivalent
// in this pure-logic module's own test environment, so that step is
// sw.js's own thin responsibility (see its call site). This function
// itself makes every actual decision (network vs. cache vs. synthesized
// fallback, HTML vs. JSON) so a test against this function is a test
// against exactly what sw.js ships, not a parallel reimplementation.
export async function networkFirst(
  request: string,
  cacheName: string,
  timeoutMs: number,
  fetchFn: (request: string) => Promise<ResponseLike>,
  cacheStorage: CacheStorageLike,
  classify: (url: string) => RequestClass
): Promise<NetworkFirstOutcome> {
  const networkFetch = fetchFn(request).then(async (response) => {
    if (response.ok) {
      const cache = await cacheStorage.open(cacheName);
      await cache.put(request, response.clone());
      const existingKeys = await cache.keys();
      const networkFirstKeys = existingKeys.filter((key) => classify(key) === "network-first");
      const staleKeys = evictOtherNetworkFirstEntries(networkFirstKeys, request);
      await Promise.all(staleKeys.map((key) => cache.delete(key)));
    }
    return response;
  });

  try {
    const response = await withTimeout(networkFetch, timeoutMs);
    return { kind: "network-success", response };
  } catch {
    const cached = await cacheStorage.match(request);
    if (cached) {
      return { kind: "offline-cache-hit", cachedResponse: cached, isHtml: !isJsonBriefingFetch(request) };
    }
    try {
      const response = await networkFetch;
      return { kind: "network-success", response };
    } catch {
      const lang = extractLangFromPath(new URL(request, "https://example.invalid").pathname);
      return { kind: "offline-no-cache", lang };
    }
  }
}

// Cache-first for hashed/effectively-immutable assets -- mirrors sw.js's
// own cacheFirst exactly.
export async function cacheFirst(
  request: string,
  cacheName: string,
  fetchFn: (request: string) => Promise<ResponseLike>,
  cacheStorage: CacheStorageLike
): Promise<ResponseLike> {
  const cached = await cacheStorage.match(request);
  if (cached) return cached;

  const response = await fetchFn(request);
  if (response.ok) {
    const cache = await cacheStorage.open(cacheName);
    void cache.put(request, response.clone());
  }
  return response;
}

// Story 5.3 (AD-9): a cache-name-safe rendering of a Briefing's
// `generated_at` ISO datetime, used as the per-cycle cache-version
// suffix. Cache names are technically permitted to contain `:`/`.`, but
// stripping them keeps the final name readable and avoids any
// tooling/DevTools quoting friction with a colon-heavy string. Derived
// ONLY from generated_at (cycle-derived), never from a build timestamp
// (deploy-derived) -- see this story's own Dev Notes on why: a build
// timestamp would make every rebuild look like a new cycle to a
// reader's browser, forcing an unnecessary cache-clear on every deploy
// regardless of whether the underlying content actually changed.
export function sanitizeCacheVersion(generatedAt: string): string {
  return generatedAt.replace(/[^0-9A-Za-z]/g, "-");
}

// Story 5.3 (AD-9): which existing cache names are from a PREVIOUS cycle
// and must be deleted on activation -- every name except the current,
// freshly-stamped one. This worker only ever creates one cache (the one
// named CACHE_NAME at any given moment), so "not the current name"
// correctly means "leftover from an earlier cycle's activation," not
// something unrelated.
export function staleCacheNames(existingNames: string[], currentCacheName: string): string[] {
  return existingNames.filter((name) => name !== currentCacheName);
}

// Story 5.4 (AC3): every request path this site can ever produce carries
// its Output Language as either the first segment (`/<lang>/...` for a
// page navigation) or the second (`/briefings/<lang>/...` for a JSON
// fetch) -- `/` itself has neither (Story 4.1's unconditional French
// default). Checks both positions so this degrades sensibly for either
// request shape, even though in practice AC3's "no page ever rendered"
// scenario only reaches this via a page-navigation path (a failed JSON
// fetch on an already-rendered page is a different, already-handled
// case -- the reader keeps seeing whatever page is already on screen).
export type OfflineLanguage = "fr" | "en" | "es";
const SUPPORTED_OFFLINE_LANGUAGES: readonly OfflineLanguage[] = ["fr", "en", "es"];

export function extractLangFromPath(pathname: string): OfflineLanguage {
  const segments = pathname.split("/");
  const candidate = segments[1] === "briefings" ? segments[2] : segments[1];
  const match = SUPPORTED_OFFLINE_LANGUAGES.find((lang) => lang === candidate);
  return match ?? "fr";
}

// Story 5.4 (AC1, AC3): per-language copy for the two new offline-facing
// pieces of text -- the "earlier cycle" banner shown when a cached
// Briefing IS available, and the dedicated fallback page's own message
// when nothing is cached at all. Each language's phrasing is authored on
// its own terms, not a mechanical per-word translation, matching every
// prior story's own standing per-language-content discipline.
const OFFLINE_BANNER_TEXT: Record<OfflineLanguage, string> = {
  fr: "Vous consultez une version en cache d'un cycle précédent.",
  en: "You're viewing a cached version from an earlier cycle.",
  es: "Estás viendo una versión en caché de un ciclo anterior.",
};

export function offlineBannerText(lang: OfflineLanguage): string {
  return OFFLINE_BANNER_TEXT[lang];
}

const OFFLINE_FALLBACK_TITLE: Record<OfflineLanguage, string> = {
  fr: "Hors ligne",
  en: "Offline",
  es: "Sin conexión",
};

const OFFLINE_FALLBACK_MESSAGE: Record<OfflineLanguage, string> = {
  fr: "Aucune connexion, et aucun Briefing n'est encore en cache sur cet appareil.",
  en: "No connection, and no Briefing is cached on this device yet.",
  es: "Sin conexión, y aún no hay ningún Briefing en caché en este dispositivo.",
};

// Story 5.4 (AC3): synthesized entirely by the worker itself, per
// request, with zero network/cache dependency of its own -- this is the
// "no connection AND no cached Briefing" case, so nothing else can be
// relied on to be available. NEVER written into the cache (see sw.js's
// own call site) -- it's not a real Briefing, and caching it would be a
// nonsensical entry that could itself violate AC2's "at most one
// Briefing" cap.
export function buildOfflineFallbackHtml(lang: OfflineLanguage): string {
  const title = OFFLINE_FALLBACK_TITLE[lang];
  const message = OFFLINE_FALLBACK_MESSAGE[lang];
  return (
    `<!DOCTYPE html><html lang="${lang}"><head><meta charset="utf-8">` +
    `<meta name="viewport" content="width=device-width, initial-scale=1">` +
    `<title>${title} — 5 News</title></head><body>` +
    `<h1>${title}</h1><p>${message}</p></body></html>`
  );
}

// Story 5.4 (AC1): the marker the worker injects into a cached page's
// own HTML when serving it from the offline-fallback path (a cache hit
// reached only after the network attempt itself failed) -- absent from
// a normal network-success response's HTML. HTTP response headers
// aren't readable by page JS after a real navigation has already
// completed, so the signal has to live IN the markup itself; a
// <meta name="..."> tag is a normal DOM read the client-side banner
// script can check for immediately on page load, no special API needed.
export const OFFLINE_BANNER_META_NAME = "offline-cache";

// Inserted right after the opening <head> tag -- present in every real
// page's HTML (BriefingPage.astro's own structure), so this insertion
// point is always available regardless of which route was cached.
export function injectOfflineBannerMeta(html: string): string {
  return html.replace(/<head>/i, `<head><meta name="${OFFLINE_BANNER_META_NAME}" content="true">`);
}
