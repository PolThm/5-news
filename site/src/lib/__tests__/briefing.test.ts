import { describe, expect, it } from "vitest";
import {
  endScreenText,
  fallbackNoticeText,
  hasValidAttribution,
  isZoneFallback,
  nextPeriod,
  nextZone,
  periodSentenceText,
  ZONE_CYCLE,
  zoneSentenceLabel,
} from "../briefing";

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

describe("ZONE_CYCLE", () => {
  it("has exactly the 15 Zones from pipeline/config's ZONES, in the same order", () => {
    expect(ZONE_CYCLE).toEqual([
      "world",
      "europe",
      "north-america",
      "south-america",
      "asia",
      "africa",
      "oceania",
      "france",
      "united-kingdom",
      "germany",
      "united-states",
      "japan",
      "china",
      "india",
      "brazil",
    ]);
  });
});

describe("nextZone", () => {
  it("cycles through all 15 Zones in order and wraps Brazil -> World", () => {
    expect(nextZone("world")).toBe("europe");
    expect(nextZone("europe")).toBe("north-america");
    expect(nextZone("north-america")).toBe("south-america");
    expect(nextZone("south-america")).toBe("asia");
    expect(nextZone("asia")).toBe("africa");
    expect(nextZone("africa")).toBe("oceania");
    expect(nextZone("oceania")).toBe("france");
    expect(nextZone("france")).toBe("united-kingdom");
    expect(nextZone("united-kingdom")).toBe("germany");
    expect(nextZone("germany")).toBe("united-states");
    expect(nextZone("united-states")).toBe("japan");
    expect(nextZone("japan")).toBe("china");
    expect(nextZone("china")).toBe("india");
    expect(nextZone("india")).toBe("brazil");
    expect(nextZone("brazil")).toBe("world");
  });
});

describe("zoneSentenceLabel", () => {
  it("returns the full preposition-inclusive French phrase for each Zone", () => {
    expect(zoneSentenceLabel("world")).toBe("dans le Monde");
    expect(zoneSentenceLabel("europe")).toBe("en Europe");
    expect(zoneSentenceLabel("north-america")).toBe("en Amérique du Nord");
    expect(zoneSentenceLabel("south-america")).toBe("en Amérique du Sud");
    expect(zoneSentenceLabel("asia")).toBe("en Asie");
    expect(zoneSentenceLabel("africa")).toBe("en Afrique");
    expect(zoneSentenceLabel("oceania")).toBe("en Océanie");
    expect(zoneSentenceLabel("france")).toBe("en France");
    expect(zoneSentenceLabel("united-kingdom")).toBe("au Royaume-Uni");
    expect(zoneSentenceLabel("germany")).toBe("en Allemagne");
    expect(zoneSentenceLabel("united-states")).toBe("aux États-Unis");
    expect(zoneSentenceLabel("japan")).toBe("au Japon");
    expect(zoneSentenceLabel("china")).toBe("en Chine");
    expect(zoneSentenceLabel("india")).toBe("en Inde");
    expect(zoneSentenceLabel("brazil")).toBe("au Brésil");
  });
});

describe("isZoneFallback", () => {
  it("is false when served_zone equals zone", () => {
    expect(isZoneFallback({ zone: "france", served_zone: "france" })).toBe(false);
  });

  it("is true when served_zone differs from zone", () => {
    expect(isZoneFallback({ zone: "france", served_zone: "europe" })).toBe(true);
  });
});

describe("fallbackNoticeText", () => {
  it("returns null when there is no fallback", () => {
    expect(fallbackNoticeText({ zone: "france", served_zone: "france" })).toBeNull();
  });

  it("returns the exact French sentence from the UX mockup when France falls back to Europe", () => {
    expect(fallbackNoticeText({ zone: "france", served_zone: "europe" })).toBe(
      "Affichage de l'Europe — la France n'a pas assez de couverture aujourd'hui."
    );
  });

  it("uses each country's correct subject-form article in the requested-zone clause", () => {
    expect(fallbackNoticeText({ zone: "united-kingdom", served_zone: "europe" })).toBe(
      "Affichage de l'Europe — le Royaume-Uni n'a pas assez de couverture aujourd'hui."
    );
    expect(fallbackNoticeText({ zone: "japan", served_zone: "asia" })).toBe(
      "Affichage de l'Asie — le Japon n'a pas assez de couverture aujourd'hui."
    );
  });

  it("agrees the verb in number for a grammatically plural country (les États-Unis n'ont pas...)", () => {
    // "les États-Unis" is plural in French despite being a single Country --
    // the only one of the 8 supported Countries where this agreement
    // matters; a fixed "n'a pas" for every Country would be a real,
    // native-speaker-visible grammar error for this one case.
    expect(fallbackNoticeText({ zone: "united-states", served_zone: "north-america" })).toBe(
      "Affichage de l'Amérique du Nord — les États-Unis n'ont pas assez de couverture aujourd'hui."
    );
  });

  it("returns null instead of throwing when zone/served_zone don't match either lookup table", () => {
    // Defense against a malformed data/briefings/**/*.json (partial write,
    // hand-edit, future pipeline bug): loadBriefing does no schema
    // validation, and this function is called unconditionally for every
    // statically-generated page at build time -- an uncaught TypeError here
    // would fail the entire `astro build`, not just one page. Today's
    // pipeline logic only ever produces zone/served_zone pairs that are
    // covered by ZONE_SERVED_LABEL/ZONE_REQUESTED_LABEL, but this function
    // must not assume the input is always well-formed.
    expect(fallbackNoticeText({ zone: "not-a-real-zone", served_zone: "also-not-real" })).toBeNull();
    expect(fallbackNoticeText({ zone: "world", served_zone: "not-a-real-zone" })).toBeNull();
  });
});

describe("endScreenText", () => {
  it("uses singular French grammar for exactly 1 item", () => {
    expect(endScreenText(1, "day")).toBe(
      "Vous avez atteint la fin. 1 sujet a atteint le seuil aujourd'hui."
    );
  });

  it("uses plural French grammar for 2 or more items", () => {
    expect(endScreenText(2, "day")).toBe(
      "Vous avez atteint la fin. 2 sujets ont atteint le seuil aujourd'hui."
    );
    expect(endScreenText(4, "day")).toBe(
      "Vous avez atteint la fin. 4 sujets ont atteint le seuil aujourd'hui."
    );
  });

  it("reuses periodSentenceText's exact wording for each Period", () => {
    expect(endScreenText(3, "day")).toContain("aujourd'hui.");
    expect(endScreenText(3, "week")).toContain("cette semaine.");
    expect(endScreenText(3, "month")).toContain("ce mois.");
  });

  it("returns null for 0 items instead of a nonsensical '0 sujets ont atteint...' sentence", () => {
    // A real, already-observed case (Story 4.1's AC6: a real cycle run
    // produced zero qualifying Clusters). There is nothing to declare
    // "complete" when nothing rendered above it -- the End Screen must be
    // suppressed entirely for this input, not given invented copy no UX
    // spec defines.
    expect(endScreenText(0, "day")).toBeNull();
  });
});
