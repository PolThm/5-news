// Story 5.2 (AD-8): network-first-with-timeout for Briefing content (both
// the server-rendered HTML pages and the /briefings/*.json files a
// JS-present reader fetches after a Zone/Period/Language click),
// cache-first for hashed assets and the manifest/icon files.
//
// Story 5.3 (AD-9): this file (public/sw.template.js) is the checked-in
// TEMPLATE, never the final artifact -- site/scripts/stamp-service-worker.ts
// reads it, substitutes the CACHE_NAME placeholder token below (see that
// constant's own declaration) with the current cycle's sanitized
// generated_at, and writes the result to public/sw.js (gitignored,
// regenerated every build, same convention as public/briefings/).
// Different cycles produce different sw.js bytes, which is exactly the
// mechanism that makes the browser notice an update at all; a rebuild
// against the SAME cycle's data must substitute the same value every
// time, or every redeploy would look like a new cycle to a reader's
// browser. (This comment deliberately never spells out the literal
// placeholder token, so the stamping script's global substitution can't
// accidentally rewrite this prose too.)
//
// Story 5.4: the cache holds at most ONE network-first entry (the
// reader's single last-viewed Briefing/page) at any time -- never the
// full 135-Briefing matrix a reader could accumulate one Zone/Period/
// Language click at a time (AC2, NFR-6). On a real network failure with
// nothing cached, a dedicated, per-language offline-fallback page is
// synthesized entirely by this worker (AC3); on a real network failure
// WITH a cached HTML page as fallback, this worker injects a <meta> tag
// into that page's own markup (HTTP response headers aren't readable by
// page JS after a real navigation has already completed, so the signal
// has to live in the markup itself) -- the client-side banner script
// (site/src/islands/sw-register.ts) checks for that tag to show an
// honest "you're viewing an earlier cycle" disclosure (AC1).
//
// This file cannot import anything -- Astro copies site/public/ to
// dist/ byte-for-byte, unprocessed, and a service worker script itself
// runs in its own worker global scope with no bundler involved. The pure
// functions below (classifyRequest, withTimeout, staleCacheNames,
// evictOtherNetworkFirstEntries, extractLangFromPath, offlineBannerText,
// buildOfflineFallbackHtml, injectOfflineBannerMeta) are a hand-kept
// mirror of site/src/islands/sw-logic.ts, which exists ONLY for that
// TypeScript file's own unit tests. (sw-logic.ts also has a
// sanitizeCacheVersion function, but it's build-time-only, run by the
// Node stamping script and never at worker runtime -- its sanitized
// output is baked directly into CACHE_NAME below as a string literal,
// so there is nothing to mirror here for that one function
// specifically.) The same "one owner conceptually, two hand-kept copies
// practically" pattern already established for briefing.ts <->
// period-switcher.ts (Stories 4.2-4.7). Keep both copies in sync by hand
// whenever either changes.
const CACHE_NAME = "briefings-__CACHE_VERSION__";
const NETWORK_TIMEOUT_MS = 3000;

const CACHE_FIRST_EXACT_PATHS = new Set(["/manifest.json", "/icon-192.png", "/icon-512.png"]);

function classifyRequest(url) {
  const { pathname } = new URL(url);

  if (pathname === "/sw.js") return "passthrough";
  if (pathname.startsWith("/_astro/")) return "cache-first";
  if (CACHE_FIRST_EXACT_PATHS.has(pathname)) return "cache-first";
  if (pathname.startsWith("/briefings/") && pathname.endsWith(".json")) return "network-first";
  if (pathname.endsWith(".html")) return "network-first";

  const lastSegment = pathname.slice(pathname.lastIndexOf("/") + 1);
  if (!lastSegment.includes(".")) return "network-first";

  return "passthrough";
}

function withTimeout(promise, ms) {
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

// Story 5.4 (AC3): every request path this site can ever produce carries
// its Output Language as either the first segment (`/<lang>/...` for a
// page navigation) or the second (`/briefings/<lang>/...` for a JSON
// fetch) -- `/` itself has neither (Story 4.1's unconditional French
// default).
const SUPPORTED_OFFLINE_LANGUAGES = ["fr", "en", "es"];

function extractLangFromPath(pathname) {
  const segments = pathname.split("/");
  const candidate = segments[1] === "briefings" ? segments[2] : segments[1];
  return SUPPORTED_OFFLINE_LANGUAGES.find((lang) => lang === candidate) ?? "fr";
}

const OFFLINE_BANNER_TEXT = {
  fr: "Vous consultez une version en cache d'un cycle précédent.",
  en: "You're viewing a cached version from an earlier cycle.",
  es: "Estás viendo una versión en caché de un ciclo anterior.",
};

function offlineBannerText(lang) {
  return OFFLINE_BANNER_TEXT[lang];
}

const OFFLINE_FALLBACK_TITLE = { fr: "Hors ligne", en: "Offline", es: "Sin conexión" };
const OFFLINE_FALLBACK_MESSAGE = {
  fr: "Aucune connexion, et aucun Briefing n'est encore en cache sur cet appareil.",
  en: "No connection, and no Briefing is cached on this device yet.",
  es: "Sin conexión, y aún no hay ningún Briefing en caché en este dispositivo.",
};

// Story 5.4 (AC3): synthesized entirely by this worker, per request,
// with zero network/cache dependency of its own. NEVER written into the
// cache (see networkFirst's own call site) -- it's not a real Briefing.
function buildOfflineFallbackHtml(lang) {
  const title = OFFLINE_FALLBACK_TITLE[lang];
  const message = OFFLINE_FALLBACK_MESSAGE[lang];
  return (
    `<!DOCTYPE html><html lang="${lang}"><head><meta charset="utf-8">` +
    `<meta name="viewport" content="width=device-width, initial-scale=1">` +
    `<title>${title} — 5 News</title></head><body>` +
    `<h1>${title}</h1><p>${message}</p></body></html>`
  );
}

// Story 5.4 (AC1): the marker this worker injects into a cached page's
// own HTML when serving it from the offline-fallback path -- absent
// from a normal network-success response's HTML. Inserted right after
// the opening <head> tag, present in every real page's HTML
// (BriefingPage.astro's own structure), so this insertion point is
// always available regardless of which route was cached.
const OFFLINE_BANNER_META_NAME = "offline-cache";

function injectOfflineBannerMeta(html) {
  return html.replace(/<head>/i, `<head><meta name="${OFFLINE_BANNER_META_NAME}" content="true">`);
}

// Story 5.4 (AC1, AC2, NFR-6): "network-first" is not a single eviction
// pool -- a page navigation and a /briefings/*.json fetch are two
// DIFFERENT representations of the same underlying Briefing (a mad-libs
// click never triggers a real navigation, per period-switcher.ts's own
// history.pushState-based update, so the fetch handler never re-caches
// HTML for the new Zone/Period/Language). Each shape gets its own
// eviction pool -- the cache holds at most one page entry AND at most
// one JSON entry at a time, never accumulating either shape across
// multiple combinations. Cache-first entries (hashed assets, manifest/
// icons) are a completely separate concern, filtered out by the caller
// before this function ever sees them.
function isJsonBriefingFetch(url) {
  const { pathname } = new URL(url);
  return pathname.startsWith("/briefings/") && pathname.endsWith(".json");
}

function evictOtherNetworkFirstEntries(existingNetworkFirstKeys, newRequest) {
  const newRequestIsJson = isJsonBriefingFetch(newRequest);
  return existingNetworkFirstKeys.filter(
    (key) => key !== newRequest && isJsonBriefingFetch(key) === newRequestIsJson
  );
}

// Network-first, short-timeout, cache as fallback ONLY -- never
// stale-while-revalidate (AD-8 explicitly forbids it for Briefing
// content: serving a cached response while silently kicking off a
// background revalidation would still guarantee the first paint is
// whatever was previously cached).
//
// Story 5.4 (AC2): writes the new response FIRST, then evicts every
// other network-first entry -- never the other order, so the cache is
// never briefly empty (see sw-logic.ts's own comment for the full
// reasoning: writing first means at most two entries exist transiently,
// never zero, which matters for a cache whose entire purpose is being
// the reader's offline safety net).
async function networkFirst(request) {
  // The cache write is attached directly to the real fetch's own .then,
  // not gated behind whichever branch of the timeout race actually wins
  // -- a slow-but-eventually-successful fetch that loses the race to the
  // timeout must still update the cache when it finally arrives (Blind
  // Hunter review of Story 5.2 caught that the first version only cached
  // the response on the branch that awaited it directly, silently
  // leaving the cache stale on every timed-out-but-working visit).
  const networkFetch = fetch(request).then(async (response) => {
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      await cache.put(request, response.clone());
      const existingKeys = (await cache.keys()).map((req) => req.url);
      const networkFirstKeys = existingKeys.filter((key) => classifyRequest(key) === "network-first");
      const staleKeys = evictOtherNetworkFirstEntries(networkFirstKeys, request.url);
      await Promise.all(staleKeys.map((key) => cache.delete(key)));
    }
    return response;
  });

  try {
    const response = await withTimeout(networkFetch, NETWORK_TIMEOUT_MS);
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) {
      // AC1: a real network failure occurred, and this is whatever the
      // reader last successfully viewed, not fresh content. HTTP
      // response headers aren't readable by page JS after a real
      // navigation has already completed, so the signal has to live IN
      // the page's own HTML -- only rewrite the body for an actual HTML
      // response (a page navigation); a cached /briefings/*.json
      // response is read directly by the client's own fetch() call
      // site, which already has everything it needs without this
      // rewrite.
      const contentType = cached.headers.get("Content-Type") ?? "";
      if (!contentType.includes("json")) {
        const html = await cached.clone().text();
        const tagged = injectOfflineBannerMeta(html);
        return new Response(tagged, {
          status: cached.status,
          statusText: cached.statusText,
          headers: cached.headers,
        });
      }
      return cached;
    }
    // No cache entry and the network genuinely failed (AC3): nothing
    // else can be relied on to be available, so synthesize a dedicated
    // offline-fallback page entirely in-worker, in whichever Output
    // Language the request path itself indicates. Never written into
    // the cache -- it's not a real Briefing.
    const lang = extractLangFromPath(new URL(request.url).pathname);
    return new Response(buildOfflineFallbackHtml(lang), {
      status: 200,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  }
}

// Cache-first for hashed/effectively-immutable assets: a cache hit never
// touches the network at all; a miss fetches once and caches the result
// for next time.
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(CACHE_NAME);
    void cache.put(request, response.clone());
  }
  return response;
}

function staleCacheNames(existingNames, currentCacheName) {
  return existingNames.filter((name) => name !== currentCacheName);
}

// Story 5.3 (AD-9): skipWaiting so a newly-installed worker (this one,
// carrying the new cycle's own CACHE_NAME) doesn't wait for every
// existing tab of this origin to close before activating -- the update
// must land on the visit that discovers it, not the next one.
self.addEventListener("install", () => {
  self.skipWaiting();
});

// Story 5.3 (AD-9): on activation, delete every cache whose name doesn't
// carry the CURRENT cycle's identifier (i.e. every cache from a previous
// cycle -- this worker only ever creates one cache, the one named
// CACHE_NAME at any given moment, so "not the current name" correctly
// means "leftover from an earlier activation"), then claim every
// already-open tab so this worker starts controlling them immediately.
// Deletion is awaited (via Promise.all inside event.waitUntil) BEFORE
// clients.claim() runs, so a freshly-claimed tab's very next fetch never
// races a half-cleaned-up cache set -- by the time any client is
// claimed, only the current cycle's cache can possibly exist.
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((existingNames) =>
        Promise.all(
          staleCacheNames(existingNames, CACHE_NAME).map((name) => caches.delete(name))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const requestClass = classifyRequest(event.request.url);

  if (requestClass === "network-first") {
    event.respondWith(networkFirst(event.request));
  } else if (requestClass === "cache-first") {
    event.respondWith(cacheFirst(event.request));
  }
  // "passthrough": don't call respondWith at all -- the browser's own
  // default network handling takes over, untouched by this worker.
});
