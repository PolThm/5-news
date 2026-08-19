import { describe, expect, it } from "vitest";
import {
  DEFAULT_ENTRY_PATH,
  entryTargetFor,
  redirectTargetFor,
  resolveLanguage,
  shouldRedirect,
} from "../language-detect";

describe("resolveLanguage", () => {
  it("resolves each of the 3 supported languages from their bare code", () => {
    expect(resolveLanguage("fr")).toBe("fr");
    expect(resolveLanguage("en")).toBe("en");
    expect(resolveLanguage("es")).toBe("es");
  });

  it("resolves common regional variants to their base language", () => {
    expect(resolveLanguage("en-US")).toBe("en");
    expect(resolveLanguage("en-GB")).toBe("en");
    expect(resolveLanguage("fr-FR")).toBe("fr");
    expect(resolveLanguage("fr-CA")).toBe("fr");
    expect(resolveLanguage("es-MX")).toBe("es");
    expect(resolveLanguage("es-ES")).toBe("es");
  });

  it("is case-insensitive", () => {
    expect(resolveLanguage("FR-fr")).toBe("fr");
  });

  it("falls back to English for an unsupported language (FR-12)", () => {
    expect(resolveLanguage("de-DE")).toBe("en");
    expect(resolveLanguage("ja")).toBe("en");
  });

  it("falls back to English when navigator.language is missing or empty", () => {
    expect(resolveLanguage(undefined)).toBe("en");
    expect(resolveLanguage(null)).toBe("en");
    expect(resolveLanguage("")).toBe("en");
  });
});

describe("shouldRedirect", () => {
  it("is false for French -- / already serves French correctly, no-JS-safe", () => {
    expect(shouldRedirect("fr")).toBe(false);
  });

  it("is true for English or Spanish", () => {
    expect(shouldRedirect("en")).toBe(true);
    expect(shouldRedirect("es")).toBe(true);
  });
});

describe("redirectTargetFor", () => {
  it("builds the equivalent /world/day route for the resolved language", () => {
    expect(redirectTargetFor("en")).toBe("/en/world/day");
    expect(redirectTargetFor("es")).toBe("/es/world/day");
  });
});

describe("entryTargetFor", () => {
  it("resumes the reader's stored preference, whatever their browser language says", () => {
    // The bug this exists for: a French reader physically in Spain
    // (navigator.language "es-ES") had to re-pick French on every open,
    // because the browser-language guess overrode the choice they'd
    // already made. A thing someone chose beats a guess about where
    // they are.
    expect(entryTargetFor({ lang: "fr", zone: "world", period: "day" }, "es-ES")).toBeNull();
    expect(entryTargetFor({ lang: "fr", zone: "spain", period: "week" }, "es-ES")).toBe(
      "/fr/spain/week"
    );
  });

  it("resumes a stored Zone and Period, not just the Language", () => {
    expect(entryTargetFor({ lang: "en", zone: "europe", period: "week" }, "en-US")).toBe(
      "/en/europe/week"
    );
  });

  it("stays put when the stored preference is exactly what `/` already renders", () => {
    // `/` is a real, statically-rendered fr/world/day page (index.astro).
    // Redirecting to its own content would cost a second page load for
    // nothing, and would defeat Story 4.1's no-flash cold load.
    expect(routeOf(entryTargetFor({ lang: "fr", zone: "world", period: "day" }, "fr-FR"))).toBe(
      DEFAULT_ENTRY_PATH
    );
  });

  it("falls back to the browser-language guess on a genuine first visit", () => {
    expect(entryTargetFor(null, "es-ES")).toBe("/es/world/day");
    expect(entryTargetFor(null, "en-GB")).toBe("/en/world/day");
    expect(entryTargetFor(null, "de-DE")).toBe("/en/world/day");
    // French needs no redirect at all -- `/` already serves it.
    expect(entryTargetFor(null, "fr-FR")).toBeNull();
    expect(entryTargetFor(null, null)).toBe("/en/world/day");
  });
});

// `null` from entryTargetFor means "stay on /", which serves exactly
// DEFAULT_ENTRY_PATH's content -- this makes that equivalence explicit at
// the one assertion that depends on it.
function routeOf(target: string | null): string {
  return target ?? DEFAULT_ENTRY_PATH;
}
