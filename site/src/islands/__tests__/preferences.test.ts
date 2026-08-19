import { describe, expect, it } from "vitest";
import {
  browserStorage,
  parsePreference,
  PREFERENCE_STORAGE_KEY,
  readPreference,
  rememberCurrentRoute,
  routeFromPathname,
  routePath,
  serializePreference,
  writePreference,
  type RoutePreference,
  type StorageLike,
} from "../preferences";

// A plain in-memory stand-in for the Storage interface -- jsdom is not a
// dependency of this project (see period-switcher.test.ts's own note on
// why), and the read/write helpers were written against StorageLike
// precisely so they need nothing more than this.
function fakeStorage(initial?: string): StorageLike & { store: Map<string, string> } {
  const store = new Map<string, string>();
  if (initial !== undefined) store.set(PREFERENCE_STORAGE_KEY, initial);
  return {
    store,
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, value) => {
      store.set(key, value);
    },
  };
}

const FRENCH_WORLD_DAY: RoutePreference = { lang: "fr", zone: "world", period: "day" };

describe("routeFromPathname", () => {
  it("reads the triple out of a published Briefing path", () => {
    expect(routeFromPathname("/es/france/week")).toEqual({
      lang: "es",
      zone: "france",
      period: "week",
    });
  });

  it("tolerates a trailing slash and a trailing .html", () => {
    expect(routeFromPathname("/en/spain/day/")).toEqual({
      lang: "en",
      zone: "spain",
      period: "day",
    });
    // astro.config.mjs's `format: "file"` emits one .html file per route;
    // Vercel's cleanUrls hides the extension in production, but a direct
    // file hit or a local `astro preview` can still surface it.
    expect(routeFromPathname("/en/spain/day.html")).toEqual({
      lang: "en",
      zone: "spain",
      period: "day",
    });
  });

  it("returns null for `/` -- the neutral entry point, never an explicit choice", () => {
    // Load-bearing: index.astro loads both islands, and if `/` recorded
    // itself as fr/world/day, period-switcher.ts's load-time capture would
    // overwrite a returning reader's real preference on the very load that
    // language-detect.ts is about to read it on.
    expect(routeFromPathname("/")).toBeNull();
    expect(routeFromPathname("")).toBeNull();
  });

  it("returns null for a path that isn't three segments", () => {
    expect(routeFromPathname("/fr/world")).toBeNull();
    expect(routeFromPathname("/fr/world/day/extra")).toBeNull();
    expect(routeFromPathname("/briefings/fr/world/day.json")).toBeNull();
  });

  it("returns null for a slug this build no longer publishes", () => {
    // The Zone list narrowed from 15 to 4 on 2026-08-19. A reader whose
    // stored (or bookmarked) Zone was dropped must not be routed to a 404.
    expect(routeFromPathname("/fr/germany/day")).toBeNull();
    expect(routeFromPathname("/de/world/day")).toBeNull();
    expect(routeFromPathname("/fr/world/month")).toBeNull();
  });
});

describe("routePath", () => {
  it("builds the canonical page path for a preference", () => {
    expect(routePath({ lang: "es", zone: "europe", period: "week" })).toBe("/es/europe/week");
  });

  it("round-trips with routeFromPathname", () => {
    const preference: RoutePreference = { lang: "en", zone: "spain", period: "week" };
    expect(routeFromPathname(routePath(preference))).toEqual(preference);
  });
});

describe("parsePreference", () => {
  it("parses a well-formed stored value", () => {
    expect(parsePreference('{"lang":"fr","zone":"spain","period":"week"}')).toEqual({
      lang: "fr",
      zone: "spain",
      period: "week",
    });
  });

  it("returns null for an absent value", () => {
    expect(parsePreference(null)).toBeNull();
    expect(parsePreference(undefined)).toBeNull();
    expect(parsePreference("")).toBeNull();
  });

  it("returns null for malformed JSON rather than throwing", () => {
    expect(parsePreference("not json at all")).toBeNull();
    expect(parsePreference("{")).toBeNull();
  });

  it("returns null for JSON that isn't an object with the three keys", () => {
    expect(parsePreference('"fr"')).toBeNull();
    expect(parsePreference("null")).toBeNull();
    expect(parsePreference("[1,2,3]")).toBeNull();
    expect(parsePreference('{"lang":"fr","zone":"world"}')).toBeNull();
  });

  it("returns null for a slug this build no longer publishes", () => {
    // Same 404-stranding hazard as routeFromPathname's own case, but worse:
    // a stale STORED value would keep redirecting the reader there on every
    // single open, with no way out short of clearing site data.
    expect(parsePreference('{"lang":"fr","zone":"germany","period":"day"}')).toBeNull();
    expect(parsePreference('{"lang":"de","zone":"world","period":"day"}')).toBeNull();
    expect(parsePreference('{"lang":"fr","zone":"world","period":"month"}')).toBeNull();
  });

  it("round-trips with serializePreference", () => {
    const preference: RoutePreference = { lang: "es", zone: "france", period: "day" };
    expect(parsePreference(serializePreference(preference))).toEqual(preference);
  });
});

describe("readPreference / writePreference", () => {
  it("writes and reads back a preference", () => {
    const storage = fakeStorage();
    writePreference(storage, { lang: "es", zone: "europe", period: "week" });
    expect(readPreference(storage)).toEqual({ lang: "es", zone: "europe", period: "week" });
  });

  it("returns null when storage is unavailable", () => {
    expect(readPreference(null)).toBeNull();
  });

  it("does nothing, and does not throw, when storage is unavailable", () => {
    expect(() => writePreference(null, FRENCH_WORLD_DAY)).not.toThrow();
  });

  it("swallows a throwing setItem -- Safari private mode, or a full quota", () => {
    // Persisting is a convenience; it must never interrupt the swap that
    // triggered it, nor surface to the reader.
    const throwing: StorageLike = {
      getItem: () => null,
      setItem: () => {
        throw new DOMException("QuotaExceededError");
      },
    };
    expect(() => writePreference(throwing, FRENCH_WORLD_DAY)).not.toThrow();
  });

  it("swallows a throwing getItem -- site data blocked, or a sandboxed frame", () => {
    const throwing: StorageLike = {
      getItem: () => {
        throw new DOMException("SecurityError");
      },
      setItem: () => {},
    };
    expect(readPreference(throwing)).toBeNull();
  });

  it("stores under a versioned key, so a future shape change needs no migration code", () => {
    const storage = fakeStorage();
    writePreference(storage, FRENCH_WORLD_DAY);
    expect([...storage.store.keys()]).toEqual([PREFERENCE_STORAGE_KEY]);
    expect(PREFERENCE_STORAGE_KEY).toMatch(/\.v\d+$/);
  });
});

describe("browserStorage", () => {
  it("returns null outside a browser, rather than throwing on the bare access", () => {
    // vitest's default environment has no localStorage at all -- the same
    // shape as a sandboxed iframe or a browser with site data blocked,
    // where merely *touching* localStorage throws.
    expect(browserStorage()).toBeNull();
  });
});

describe("rememberCurrentRoute", () => {
  it("does not throw when there is no storage to write to", () => {
    // Runs on every Briefing page load; a browser refusing storage must
    // not break the page.
    expect(() => rememberCurrentRoute("/fr/world/day")).not.toThrow();
    expect(() => rememberCurrentRoute("/")).not.toThrow();
  });
});
