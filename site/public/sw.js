// Story 5.2 (AD-8): network-first-with-timeout for Briefing content (both
// the server-rendered HTML pages and the /briefings/*.json files a
// JS-present reader fetches after a Zone/Period/Language click),
// cache-first for hashed assets and the manifest/icon files.
//
// This file cannot import anything -- Astro copies site/public/ to
// dist/ byte-for-byte, unprocessed, and a service worker script itself
// runs in its own worker global scope with no bundler involved. The two
// pure functions below (classifyRequest, withTimeout) are a hand-kept
// mirror of site/src/islands/sw-logic.ts, which exists ONLY for that
// TypeScript file's own unit tests -- the same "one owner conceptually,
// two hand-kept copies practically" pattern already established for
// briefing.ts <-> period-switcher.ts (Stories 4.2-4.7). Keep both copies
// in sync by hand whenever either changes.
//
// AD-9's cycle-identifier-stamped cache versioning and cache-cleanup on
// activation are Story 5.3's own scope, not this one's -- CACHE_NAME is
// deliberately a single, simple constant here.
const CACHE_NAME = "briefings-v1";
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
