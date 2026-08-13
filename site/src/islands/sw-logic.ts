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

// Minimal shapes covering only what networkFirst/cacheFirst actually use
// from the real fetch/Cache Storage APIs -- narrow enough to fake easily
// in tests, without pulling in a full Service Worker environment.
export interface ResponseLike {
  ok: boolean;
  clone(): ResponseLike;
}
export interface CacheLike {
  match(request: string): Promise<ResponseLike | undefined>;
  put(request: string, response: ResponseLike): Promise<void>;
}
export interface CacheStorageLike {
  open(name: string): Promise<CacheLike>;
  match(request: string): Promise<ResponseLike | undefined>;
}

// Network-first, short-timeout, cache as fallback ONLY -- mirrors
// sw.js's own networkFirst exactly, including the fix for a real bug
// Blind Hunter review caught: the cache write is attached to the real
// fetch's own .then, not gated behind whichever branch of the timeout
// race wins, so a fetch that loses the race (times out) but eventually
// succeeds still updates the cache when it arrives, rather than leaving
// the cache stale on every timed-out-but-working visit.
export async function networkFirst(
  request: string,
  cacheName: string,
  timeoutMs: number,
  fetchFn: (request: string) => Promise<ResponseLike>,
  cacheStorage: CacheStorageLike
): Promise<ResponseLike> {
  const networkFetch = fetchFn(request).then((response) => {
    if (response.ok) {
      void cacheStorage.open(cacheName).then((cache) => cache.put(request, response.clone()));
    }
    return response;
  });

  try {
    return await withTimeout(networkFetch, timeoutMs);
  } catch {
    const cached = await cacheStorage.match(request);
    if (cached) return cached;
    return networkFetch;
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
