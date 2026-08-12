import { describe, expect, it } from "vitest";
import { hasValidAttribution, nextPeriod, periodSentenceText } from "../briefing";

describe("hasValidAttribution", () => {
  it("accepts a well-formed http(s) URL with a non-empty source", () => {
    expect(
      hasValidAttribution({ outbound_url: "https://example.com/a", outbound_source: "Example" })
    ).toBe(true);
  });

  it("rejects when outbound_source is null despite a valid URL", () => {
    // A real, type-legal, degrade-path state (pipeline/domain's
    // _select_outbound_link can set either field independently) --
    // without this guard, the page would render "Rapporté par null".
    expect(
      hasValidAttribution({ outbound_url: "https://example.com/a", outbound_source: null })
    ).toBe(false);
  });

  it("rejects when outbound_url is null despite a valid source", () => {
    expect(
      hasValidAttribution({ outbound_url: null, outbound_source: "Example" })
    ).toBe(false);
  });

  it("rejects when both fields are undefined (absent from the JSON entirely)", () => {
    expect(hasValidAttribution({})).toBe(false);
  });

  it("rejects a non-http(s) scheme even with a valid-looking source", () => {
    expect(
      hasValidAttribution({ outbound_url: "javascript:alert(1)", outbound_source: "Example" })
    ).toBe(false);
  });

  it("rejects an empty-string url or source", () => {
    expect(hasValidAttribution({ outbound_url: "", outbound_source: "Example" })).toBe(false);
    expect(
      hasValidAttribution({ outbound_url: "https://example.com/a", outbound_source: "" })
    ).toBe(false);
  });
});

describe("nextPeriod", () => {
  it("cycles day -> week -> month -> day", () => {
    expect(nextPeriod("day")).toBe("week");
    expect(nextPeriod("week")).toBe("month");
    expect(nextPeriod("month")).toBe("day");
  });
});

describe("periodSentenceText", () => {
  it("returns the French mad-libs word for each Period", () => {
    expect(periodSentenceText("day")).toBe("aujourd'hui");
    expect(periodSentenceText("week")).toBe("cette semaine");
    expect(periodSentenceText("month")).toBe("ce mois");
  });
});
