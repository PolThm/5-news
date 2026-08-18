import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildOfflineFallbackHtml,
  cacheFirst,
  classifyRequest,
  extractLangFromPath,
  injectOfflineBannerMeta,
  networkFirst,
  offlineBannerText,
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
      return { id, ok, clone: this.clone, text: this.text };
    },
    text: async () => "",
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
    keys: async () => [...store.keys()],
    delete: async (request) => store.delete(request),
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
    expect(classifyRequest("/5news-logo/5news-favicon-16.png")).toBe("cache-first");
    expect(classifyRequest("/5news-logo/5news-favicon-32.png")).toBe("cache-first");
    expect(classifyRequest("/5news-logo/5news-icon-180.png")).toBe("cache-first");
    expect(classifyRequest("/5news-logo/5news-icon-512.png")).toBe("cache-first");
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

  it("returns a network-success outcome and caches it, on a fast success", async () => {
    const storage = createFakeCacheStorage();
    const response = createFakeResponse(true);
    const fetchFn = vi.fn(async () => response);

    const result = await networkFirst(
      "/briefings/fr/world/day.json",
      "v1",
      3000,
      fetchFn,
      storage,
      classifyRequest
    );

    expect(result.kind).toBe("network-success");
    if (result.kind !== "network-success") throw new Error("unreachable");
    expect(result.response).toBe(response);
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

    await networkFirst("/briefings/fr/world/day.json", "v1", 3000, fetchFn, storage, classifyRequest);

    expect(storage.store.has("/briefings/fr/world/day.json")).toBe(false);
  });

  it("falls back to the cache on a network timeout, returning an offline-cache-hit outcome flagged as HTML for a page request", async () => {
    const storage = createFakeCacheStorage();
    const cachedResponse = createFakeResponse(true);
    storage.store.set("/fr/world/day", cachedResponse);
    const fetchFn = vi.fn(() => new Promise<ResponseLike>(() => {})); // never resolves

    const resultPromise = networkFirst("/fr/world/day", "v1", 3000, fetchFn, storage, classifyRequest);
    await vi.advanceTimersByTimeAsync(3000);

    const result = await resultPromise;
    expect(result.kind).toBe("offline-cache-hit");
    if (result.kind !== "offline-cache-hit") throw new Error("unreachable");
    expect(result.cachedResponse).toBe(cachedResponse);
    expect(result.isHtml).toBe(true);
  });

  it("falls back to the cache on a network timeout, returning an offline-cache-hit outcome flagged as NOT HTML for a JSON request", async () => {
    const storage = createFakeCacheStorage();
    const cachedResponse = createFakeResponse(true);
    storage.store.set("/briefings/fr/world/day.json", cachedResponse);
    const fetchFn = vi.fn(() => new Promise<ResponseLike>(() => {}));

    const resultPromise = networkFirst(
      "/briefings/fr/world/day.json",
      "v1",
      3000,
      fetchFn,
      storage,
      classifyRequest
    );
    await vi.advanceTimersByTimeAsync(3000);

    const result = await resultPromise;
    expect(result.kind).toBe("offline-cache-hit");
    if (result.kind !== "offline-cache-hit") throw new Error("unreachable");
    expect(result.isHtml).toBe(false);
  });

  it("returns an offline-no-cache outcome, with the language extracted from the request path, on a real network failure with nothing cached", async () => {
    const storage = createFakeCacheStorage();
    const fetchFn = vi.fn(() => Promise.reject(new Error("network down")));

    const result = await networkFirst("/en/world/day", "v1", 3000, fetchFn, storage, classifyRequest);

    expect(result.kind).toBe("offline-no-cache");
    if (result.kind !== "offline-no-cache") throw new Error("unreachable");
    expect(result.lang).toBe("en");
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
    const resultPromise = networkFirst(
      "/briefings/fr/world/day.json",
      "v1",
      3000,
      fetchFn,
      storage,
      classifyRequest
    );
    await vi.advanceTimersByTimeAsync(3000); // the timeout fires first, no cache entry yet

    resolveNetwork(slowResponse); // the slow fetch finally arrives, well after the timeout
    const result = await resultPromise;

    expect(result.kind).toBe("network-success");
    if (result.kind !== "network-success") throw new Error("unreachable");
    expect((result.response as ResponseLike & { id: number }).id).toBe(slowResponse.id);
    expect(storage.store.get("/briefings/fr/world/day.json")?.id).toBe(slowResponse.id);
  });

  it("evicts other JSON entries when writing a new JSON entry, but never the currently-cached HTML page (the real bug Blind Hunter review of this story caught)", async () => {
    const storage = createFakeCacheStorage();
    // A page is currently displayed (cached from the real navigation
    // that loaded it) and the reader has already clicked through one
    // other Zone via a mad-libs click (an in-place JSON fetch, no real
    // navigation, per period-switcher.ts's own history.pushState-based
    // update) -- both must survive a THIRD click's own JSON write.
    const currentPageHtml = createFakeResponse(true);
    storage.store.set("/fr/world/day", currentPageHtml);
    storage.store.set("/briefings/fr/europe/day.json", createFakeResponse(true));

    const newJson = createFakeResponse(true);
    const fetchFn = vi.fn(async () => newJson);

    await networkFirst("/briefings/fr/japan/day.json", "v1", 3000, fetchFn, storage, classifyRequest);

    // The page HTML must survive -- this is the exact scenario that
    // regressed AC1 before the fix: without a separate JSON eviction
    // pool, this JSON write would have evicted the page, leaving nothing
    // to serve if the reader went offline and reloaded.
    expect(storage.store.get("/fr/world/day")?.id).toBe(currentPageHtml.id);
    expect(storage.store.has("/briefings/fr/europe/day.json")).toBe(false); // evicted
    expect(storage.store.get("/briefings/fr/japan/day.json")?.id).toBe(newJson.id);
  });

  it("evicts every OTHER network-first entry once the new response is written, leaving cache-first entries untouched", async () => {
    const storage = createFakeCacheStorage();
    // Simulate a reader who previously viewed a different Zone -- an
    // existing network-first entry from an earlier click -- plus a
    // cache-first hashed asset that must never be evicted by this logic.
    storage.store.set("/fr/europe/day", createFakeResponse(true));
    storage.store.set("/_astro/foo.ABC123.js", createFakeResponse(true));

    const newResponse = createFakeResponse(true);
    const fetchFn = vi.fn(async () => newResponse);

    await networkFirst("/fr/world/day", "v1", 3000, fetchFn, storage, classifyRequest);

    expect(storage.store.has("/fr/europe/day")).toBe(false); // evicted
    expect(storage.store.has("/_astro/foo.ABC123.js")).toBe(true); // untouched
    expect(storage.store.get("/fr/world/day")?.id).toBe(newResponse.id); // the new entry
    // Exactly one network-first entry survives, plus the untouched
    // cache-first one -- never both Zones at once.
    expect(storage.store.size).toBe(2);
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

describe("extractLangFromPath", () => {
  it("extracts the Output Language from a real [lang]/[zone]/[period] path", () => {
    expect(extractLangFromPath("/fr/world/day")).toBe("fr");
    expect(extractLangFromPath("/en/united-states/week")).toBe("en");
    expect(extractLangFromPath("/es/japan/month")).toBe("es");
  });

  it("extracts the Output Language from a /briefings/*.json path", () => {
    expect(extractLangFromPath("/briefings/en/world/day.json")).toBe("en");
  });

  it("falls back to French for the root path (no language segment at all)", () => {
    expect(extractLangFromPath("/")).toBe("fr");
  });

  it("falls back to French for an unrecognized first segment", () => {
    expect(extractLangFromPath("/de/world/day")).toBe("fr");
    expect(extractLangFromPath("/sw.js")).toBe("fr");
  });
});

describe("offlineBannerText", () => {
  it("returns independently-authored, non-mechanically-translated text for each language", () => {
    expect(offlineBannerText("fr")).toBe("Vous consultez une version en cache d'un cycle précédent.");
    expect(offlineBannerText("en")).toBe("You're viewing a cached version from an earlier cycle.");
    expect(offlineBannerText("es")).toBe("Estás viendo una versión en caché de un ciclo anterior.");
  });
});

describe("buildOfflineFallbackHtml", () => {
  it("produces a real, minimal HTML document stating the offline condition, per language", () => {
    const fr = buildOfflineFallbackHtml("fr");
    expect(fr).toContain("<html lang=\"fr\">");
    expect(fr).toContain("Hors ligne");
    expect(fr).toContain("Aucune connexion, et aucun Briefing n'est encore en cache sur cet appareil.");

    const en = buildOfflineFallbackHtml("en");
    expect(en).toContain("<html lang=\"en\">");
    expect(en).toContain("Offline");
    expect(en).toContain("No connection, and no Briefing is cached on this device yet.");

    const es = buildOfflineFallbackHtml("es");
    expect(es).toContain("<html lang=\"es\">");
    expect(es).toContain("Sin conexión");
    expect(es).toContain("Sin conexión, y aún no hay ningún Briefing en caché en este dispositivo.");
  });

  it("never contains an unescaped raw '<' from the message text that could break out of its own <p> tag", () => {
    // A defensive sanity check, not a security-critical escaping
    // requirement (the message text is 100% hardcoded, never
    // reader-supplied) -- but confirms the template's own structure is
    // well-formed HTML for each language's output.
    for (const lang of ["fr", "en", "es"] as const) {
      const html = buildOfflineFallbackHtml(lang);
      expect(html).toMatch(/<p>[^<]*<\/p>/);
    }
  });
});

describe("injectOfflineBannerMeta", () => {
  it("inserts the offline-cache meta tag right after the opening <head> tag", () => {
    const html = '<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"></head><body></body></html>';
    const result = injectOfflineBannerMeta(html);
    expect(result).toContain('<head><meta name="offline-cache" content="true"><meta charset="utf-8">');
  });

  it("preserves the rest of the document unchanged", () => {
    const html = '<html><head><title>5 News</title></head><body><h1>Hello</h1></body></html>';
    const result = injectOfflineBannerMeta(html);
    expect(result).toContain("<title>5 News</title>");
    expect(result).toContain("<h1>Hello</h1>");
  });

  it("is a no-op (returns the input unchanged) when no <head> tag is present", () => {
    const html = "<div>not a full document</div>";
    expect(injectOfflineBannerMeta(html)).toBe(html);
  });
});
