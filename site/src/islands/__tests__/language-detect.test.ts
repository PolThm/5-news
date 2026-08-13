import { describe, expect, it } from "vitest";
import { redirectTargetFor, resolveLanguage, shouldRedirect } from "../language-detect";

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
