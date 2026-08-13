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
// This file cannot import anything -- Astro copies site/public/ to
// dist/ byte-for-byte, unprocessed, and a service worker script itself
// runs in its own worker global scope with no bundler involved. The pure
// functions below (classifyRequest, withTimeout, staleCacheNames) are a
// hand-kept mirror of site/src/islands/sw-logic.ts, which exists ONLY
// for that TypeScript file's own unit tests. (sw-logic.ts also has a
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

// Network-first, short-timeout, cache as fallback ONLY -- never
// stale-while-revalidate (AD-8 explicitly forbids it for Briefing
// content: serving a cached response while silently kicking off a
// background revalidation would still guarantee the first paint is
// whatever was previously cached). The only cache write here happens
// AFTER a real, foreground, awaited network success.
async function networkFirst(request) {
  // The cache write is attached directly to the real fetch's own .then,
  // not gated behind whichever branch of the timeout race actually wins
  // -- a slow-but-eventually-successful fetch that loses the race to the
  // timeout must still update the cache when it finally arrives (Blind
  // Hunter review of this story caught that the first version only
  // cached the response on the branch that awaited it directly, silently
  // leaving the cache stale on every timed-out-but-working visit; a
  // later fully-offline visit would then serve an older Briefing than
  // the reader had actually already seen).
  const networkFetch = fetch(request).then((response) => {
    if (response.ok) {
      void caches.open(CACHE_NAME).then((cache) => cache.put(request, response.clone()));
    }
    return response;
  });

  try {
    return await withTimeout(networkFetch, NETWORK_TIMEOUT_MS);
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    // No cache entry and the network genuinely failed -- let the real
    // failure propagate rather than fabricating a fake response. The
    // browser's own offline/error handling takes over from here (Story
    // 5.4 owns building a dedicated, honest offline UI on top of this).
    // networkFetch (not a fresh fetch(request)) is reused here so a
    // timeout-then-success still benefits from the cache-write .then
    // already attached above, and no duplicate network request is made.
    return networkFetch;
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
