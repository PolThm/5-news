import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cacheFirst,
  classifyRequest,
  networkFirst,
  sanitizeCacheVersion,
  staleCacheNames,
  withTimeout,
} from "../sw-logic";
import type { CacheLike, CacheStorageLike, ResponseLike } from "../sw-logic";

let nextResponseId = 0;

// A test-only ResponseLike carrying an `id` so cached vs. original
// responses can be compared by identity-of-origin (toEqual, not toBe --
// the real Response.clone() always returns a distinct object, never the
// same reference, and clone()'d objects can't carry function properties
// through vitest's toEqual comparison either way).
function createFakeResponse(ok: boolean): ResponseLike & { id: number } {
  const id = nextResponseId++;
  return {
    id,
    ok,
    clone() {
      return { id, ok, clone: this.clone };
    },
  };
}

function createFakeCacheStorage(): CacheStorageLike & {
  store: Map<string, ResponseLike & { id: number }>;
} {
  const store = new Map<string, ResponseLike & { id: number }>();
  const cache: CacheLike = {
    match: async (request) => store.get(request),
    put: async (request, response) => {
      // Every ResponseLike this test suite ever constructs is actually a
      // createFakeResponse() carrying its own `id` -- the base
      // CacheLike/ResponseLike interfaces (shared with the real
      // sw-logic.ts implementation) don't know about that test-only
      // field, so this cast is safe within this file's own closed set of
      // response-producing helpers.
      store.set(request, response as ResponseLike & { id: number });
    },
  };
  return {
    store,
    open: async () => cache,
    match: async (request) => store.get(request),
  };
}

describe("classifyRequest", () => {
  it("classifies every Briefing JSON path as network-first", () => {
    expect(classifyRequest("/briefings/fr/world/day.json")).toBe("network-first");
    expect(classifyRequest("/briefings/en/united-states/month.json")).toBe("network-first");
    expect(classifyRequest("/briefings/es/japan/week.json")).toBe("network-first");
  });

  it("classifies every HTML page path as network-first, including / and a [lang]/[zone]/[period] route", () => {
    expect(classifyRequest("/")).toBe("network-first");
    expect(classifyRequest("/fr/world/day")).toBe("network-first");
    expect(classifyRequest("/en/united-kingdom/week")).toBe("network-first");
    // .html extension is not actually present in real navigation request
    // URLs (Astro's file:"file" format serves /fr/world/day, not
    // /fr/world/day.html, per its own routing) -- but a direct .html
    // request (e.g. from a test fetching the built file) must classify
    // the same way, since it's still Briefing content either way.
    expect(classifyRequest("/fr/world/day.html")).toBe("network-first");
  });

  it("classifies hashed assets under /_astro/ as cache-first", () => {
    expect(classifyRequest("/_astro/BriefingPage.astro_astro_type_script_index_0_lang.BzAVeIHx.js")).toBe(
      "cache-first"
    );
    expect(classifyRequest("/_astro/loadBriefing.AjlMxPw4.css")).toBe("cache-first");
  });

  it("classifies manifest.json and icon files as cache-first", () => {
    expect(classifyRequest("/manifest.json")).toBe("cache-first");
    expect(classifyRequest("/icon-192.png")).toBe("cache-first");
    expect(classifyRequest("/icon-512.png")).toBe("cache-first");
  });

  it("classifies the service worker's own script as passthrough", () => {
    expect(classifyRequest("/sw.js")).toBe("passthrough");
  });

  it("classifies a path with no file extension as a page route (network-first), even if not a real known route", () => {
    // Matches Astro's real route shape (/fr/world/day has no extension) --
    // a path shaped like a page but not actually a real route still gets
    // network-first rather than a special "unknown" treatment, since a
    // service worker fetch handler sees the URL, not whether the route
    // exists; an unrecognized page-shaped path degrades the same way a
    // real one would on a genuine 404 from the network.
    expect(classifyRequest("/some/unrelated/path")).toBe("network-first");
  });

  it("classifies a path with an unrecognized file extension as passthrough", () => {
    expect(classifyRequest("/some/file.xyz")).toBe("passthrough");
  });

  it("classifies by pathname only, ignoring query strings and origin", () => {
    expect(classifyRequest("https://example.com/briefings/fr/world/day.json?cachebust=1")).toBe(
      "network-first"
    );
    expect(classifyRequest("https://example.com/_astro/foo.ABC123.js")).toBe("cache-first");
  });
});

describe("withTimeout", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("resolves with the underlying promise's result when it settles before the timeout", async () => {
    const fast = Promise.resolve("network-response");
    const result = withTimeout(fast, 3000);
    await expect(result).resolves.toBe("network-response");
  });

  it("rejects when the timeout elapses before the underlying promise settles", async () => {
    const never = new Promise(() => {}); // never resolves/rejects
    const result = withTimeout(never, 3000);
    const assertion = expect(result).rejects.toThrow(/timeout/i);
    await vi.advanceTimersByTimeAsync(3000);
    await assertion;
  });

  it("propagates the underlying promise's own rejection when it rejects before the timeout", async () => {
    const failing = Promise.reject(new Error("network down"));
    const result = withTimeout(failing, 3000);
    await expect(result).rejects.toThrow("network down");
  });

  it("does not fire the timeout after the underlying promise has already settled", async () => {
    const fast = Promise.resolve("ok");
    await withTimeout(fast, 3000);
    // Advancing timers past the deadline after settlement must not throw
    // or produce an unhandled rejection -- the timer should have been
    // cleared, not just ignored.
    await vi.advanceTimersByTimeAsync(5000);
  });
});

describe("networkFirst", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the network response and caches it, on a fast success", async () => {
    const storage = createFakeCacheStorage();
    const response = createFakeResponse(true);
    const fetchFn = vi.fn(async () => response);

    const result = await networkFirst("/briefings/fr/world/day.json", "v1", 3000, fetchFn, storage);

    expect(result).toBe(response);
    // The real Response.clone() (mirrored here) always returns a
    // distinct object, never the same reference -- compare by the
    // fake response's own `id` (assigned once per createFakeResponse
    // call), matching the real API's "same underlying response" contract
    // without relying on object identity or a fragile toEqual across
    // objects carrying function properties.
    expect(storage.store.get("/briefings/fr/world/day.json")?.id).toBe(response.id);
  });

  it("does not cache a non-ok network response", async () => {
    const storage = createFakeCacheStorage();
    const fetchFn = vi.fn(async () => createFakeResponse(false));

    await networkFirst("/briefings/fr/world/day.json", "v1", 3000, fetchFn, storage);

    expect(storage.store.has("/briefings/fr/world/day.json")).toBe(false);
  });

  it("falls back to the cache on a network timeout", async () => {
    const storage = createFakeCacheStorage();
    const cachedResponse = createFakeResponse(true);
    storage.store.set("/briefings/fr/world/day.json", cachedResponse);
    const fetchFn = vi.fn(() => new Promise<ResponseLike>(() => {})); // never resolves

    const resultPromise = networkFirst("/briefings/fr/world/day.json", "v1", 3000, fetchFn, storage);
    await vi.advanceTimersByTimeAsync(3000);

    await expect(resultPromise).resolves.toBe(cachedResponse);
  });

  // Regression test for the real bug Blind Hunter review of Story 5.2
  // caught: the FIRST version of networkFirst only wrote to the cache
  // inside the branch that had directly awaited the network response --
  // a fetch that lost the timeout race (triggering the cache-fallback
  // path) but eventually succeeded afterward never updated the cache at
  // all, silently leaving a stale entry there indefinitely. A reader who
  // repeatedly visits on a slow-but-working connection would never get a
  // fresher cached fallback, and a later fully-offline visit would serve
  // an older Briefing than they'd actually already seen online.
  it("still writes the eventually-successful response to cache after losing the timeout race", async () => {
    const storage = createFakeCacheStorage();
    let resolveNetwork: (response: ResponseLike) => void = () => {};
    const slowResponse = createFakeResponse(true);
    const fetchFn = vi.fn(
      () =>
        new Promise<ResponseLike>((resolve) => {
          resolveNetwork = resolve;
        })
    );

    // No cache entry exists, so networkFirst's own catch branch has
    // nothing to fall back to and must wait for the real (slow) fetch to
    // eventually settle -- exactly like a real reader with an empty
    // cache on a slow-but-working connection: the read genuinely can't
    // complete faster than the network does, regardless of the 3s
    // timeout having already fired once.
    const resultPromise = networkFirst("/briefings/fr/world/day.json", "v1", 3000, fetchFn, storage);
    await vi.advanceTimersByTimeAsync(3000); // the timeout fires first, no cache entry yet

    resolveNetwork(slowResponse); // the slow fetch finally arrives, well after the timeout
    const result = (await resultPromise) as ResponseLike & { id: number };

    expect(result.id).toBe(slowResponse.id);
    expect(storage.store.get("/briefings/fr/world/day.json")?.id).toBe(slowResponse.id);
  });
});

describe("cacheFirst", () => {
  it("returns the cached response on a hit, without calling fetch at all", async () => {
    const storage = createFakeCacheStorage();
    const cachedResponse = createFakeResponse(true);
    storage.store.set("/_astro/foo.ABC123.js", cachedResponse);
    const fetchFn = vi.fn();

    const result = await cacheFirst("/_astro/foo.ABC123.js", "v1", fetchFn, storage);

    expect(result).toBe(cachedResponse);
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("fetches and caches on a miss", async () => {
    const storage = createFakeCacheStorage();
    const response = createFakeResponse(true);
    const fetchFn = vi.fn(async () => response);

    const result = await cacheFirst("/_astro/foo.ABC123.js", "v1", fetchFn, storage);

    expect(result).toBe(response);
    expect(storage.store.get("/_astro/foo.ABC123.js")?.id).toBe(response.id);
  });

  it("does not cache a non-ok response on a miss", async () => {
    const storage = createFakeCacheStorage();
    const fetchFn = vi.fn(async () => createFakeResponse(false));

    await cacheFirst("/_astro/foo.ABC123.js", "v1", fetchFn, storage);

    expect(storage.store.has("/_astro/foo.ABC123.js")).toBe(false);
  });
});

describe("sanitizeCacheVersion", () => {
  it("strips colons and other non-alphanumeric characters from a real generated_at ISO datetime", () => {
    expect(sanitizeCacheVersion("2026-08-12T05:30:00.000Z")).toBe("2026-08-12T05-30-00-000Z");
  });

  it("produces different output for different inputs (the whole point of stamping)", () => {
    const a = sanitizeCacheVersion("2026-08-12T05:30:00.000Z");
    const b = sanitizeCacheVersion("2026-08-13T05:30:00.000Z");
    expect(a).not.toBe(b);
  });

  it("produces identical output for identical input (a rebuild against the same cycle must not spuriously differ)", () => {
    const a = sanitizeCacheVersion("2026-08-12T05:30:00.000Z");
    const b = sanitizeCacheVersion("2026-08-12T05:30:00.000Z");
    expect(a).toBe(b);
  });
});

describe("staleCacheNames", () => {
  it("returns every cache name except the current one", () => {
    const existing = ["briefings-2026-08-11T05-30-00-000Z", "briefings-2026-08-12T05-30-00-000Z"];
    const result = staleCacheNames(existing, "briefings-2026-08-12T05-30-00-000Z");
    expect(result).toEqual(["briefings-2026-08-11T05-30-00-000Z"]);
  });

  it("returns an empty array when only the current cache name exists", () => {
    const result = staleCacheNames(["briefings-2026-08-12T05-30-00-000Z"], "briefings-2026-08-12T05-30-00-000Z");
    expect(result).toEqual([]);
  });

  it("returns an empty array when no caches exist yet", () => {
    expect(staleCacheNames([], "briefings-2026-08-12T05-30-00-000Z")).toEqual([]);
  });

  it("treats every non-matching name as stale, even one from an unrelated origin/cache", () => {
    const existing = ["some-other-unrelated-cache", "briefings-2026-08-12T05-30-00-000Z"];
    const result = staleCacheNames(existing, "briefings-2026-08-12T05-30-00-000Z");
    expect(result).toEqual(["some-other-unrelated-cache"]);
  });
});
