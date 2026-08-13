import { describe, expect, it } from "vitest";
import {
  attributionText,
  consensusChipText,
  countryLabel,
  discardedVolumeText,
  endScreenText,
  fallbackNoticeText,
  formatCount,
  hasValidAttribution,
  isZoneFallback,
  madLibsLeadIn,
  nextPeriod,
  nextZone,
  offlineBannerText,
  OUTPUT_LANGUAGE_CYCLE,
  periodSentenceText,
  sourceListIntro,
  timestampPrefix,
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

describe("OUTPUT_LANGUAGE_CYCLE", () => {
  it("has exactly the 3 supported languages, fr first", () => {
    expect(OUTPUT_LANGUAGE_CYCLE).toEqual(["fr", "en", "es"]);
  });
});

describe("periodSentenceText", () => {
  it("returns the correct word for each Period, in each language", () => {
    expect(periodSentenceText("day", "fr")).toBe("aujourd'hui");
    expect(periodSentenceText("week", "fr")).toBe("cette semaine");
    expect(periodSentenceText("month", "fr")).toBe("ce mois");

    expect(periodSentenceText("day", "en")).toBe("today");
    expect(periodSentenceText("week", "en")).toBe("this week");
    expect(periodSentenceText("month", "en")).toBe("this month");

    expect(periodSentenceText("day", "es")).toBe("hoy");
    expect(periodSentenceText("week", "es")).toBe("esta semana");
    expect(periodSentenceText("month", "es")).toBe("este mes");
  });
});

describe("ZONE_CYCLE", () => {
  it("has exactly the 15 Zones from the pipeline's config.ZONES, in the same order", () => {
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
    expect(zoneSentenceLabel("world", "fr")).toBe("dans le Monde");
    expect(zoneSentenceLabel("europe", "fr")).toBe("en Europe");
    expect(zoneSentenceLabel("north-america", "fr")).toBe("en Amérique du Nord");
    expect(zoneSentenceLabel("south-america", "fr")).toBe("en Amérique du Sud");
    expect(zoneSentenceLabel("asia", "fr")).toBe("en Asie");
    expect(zoneSentenceLabel("africa", "fr")).toBe("en Afrique");
    expect(zoneSentenceLabel("oceania", "fr")).toBe("en Océanie");
    expect(zoneSentenceLabel("france", "fr")).toBe("en France");
    expect(zoneSentenceLabel("united-kingdom", "fr")).toBe("au Royaume-Uni");
    expect(zoneSentenceLabel("germany", "fr")).toBe("en Allemagne");
    expect(zoneSentenceLabel("united-states", "fr")).toBe("aux États-Unis");
    expect(zoneSentenceLabel("japan", "fr")).toBe("au Japon");
    expect(zoneSentenceLabel("china", "fr")).toBe("en Chine");
    expect(zoneSentenceLabel("india", "fr")).toBe("en Inde");
    expect(zoneSentenceLabel("brazil", "fr")).toBe("au Brésil");
  });

  it("returns the correct English phrase for a sample of each preposition case", () => {
    expect(zoneSentenceLabel("world", "en")).toBe("in the World");
    expect(zoneSentenceLabel("europe", "en")).toBe("in Europe");
    expect(zoneSentenceLabel("united-kingdom", "en")).toBe("in the United Kingdom");
    expect(zoneSentenceLabel("japan", "en")).toBe("in Japan");
  });

  it("returns the correct Spanish phrase for a sample of each preposition case", () => {
    expect(zoneSentenceLabel("world", "es")).toBe("en el Mundo");
    expect(zoneSentenceLabel("europe", "es")).toBe("en Europa");
    expect(zoneSentenceLabel("united-kingdom", "es")).toBe("en el Reino Unido");
    expect(zoneSentenceLabel("japan", "es")).toBe("en Japón");
  });

  it("degrades to the raw slug for an unknown zone rather than returning undefined", () => {
    expect(zoneSentenceLabel("not-a-real-zone", "en")).toBe("not-a-real-zone");
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
  it("returns null when there is no fallback, in any language", () => {
    expect(fallbackNoticeText({ zone: "france", served_zone: "france" }, "fr")).toBeNull();
    expect(fallbackNoticeText({ zone: "france", served_zone: "france" }, "en")).toBeNull();
    expect(fallbackNoticeText({ zone: "france", served_zone: "france" }, "es")).toBeNull();
  });

  it("returns the exact French sentence from the UX mockup when France falls back to Europe", () => {
    expect(fallbackNoticeText({ zone: "france", served_zone: "europe" }, "fr")).toBe(
      "Affichage de l'Europe — la France n'a pas assez de couverture aujourd'hui."
    );
  });

  it("returns the correct English sentence when France falls back to Europe", () => {
    expect(fallbackNoticeText({ zone: "france", served_zone: "europe" }, "en")).toBe(
      "Showing Europe — France doesn't have enough coverage today."
    );
  });

  it("returns the correct Spanish sentence when France falls back to Europe", () => {
    expect(fallbackNoticeText({ zone: "france", served_zone: "europe" }, "es")).toBe(
      "Mostrando Europa — Francia no tiene suficiente cobertura hoy."
    );
  });

  it("uses each country's correct subject-form article in the requested-zone clause", () => {
    expect(fallbackNoticeText({ zone: "united-kingdom", served_zone: "europe" }, "fr")).toBe(
      "Affichage de l'Europe — le Royaume-Uni n'a pas assez de couverture aujourd'hui."
    );
    expect(fallbackNoticeText({ zone: "japan", served_zone: "asia" }, "fr")).toBe(
      "Affichage de l'Asie — le Japon n'a pas assez de couverture aujourd'hui."
    );
  });

  it("agrees the verb in number for a grammatically plural country, in every language", () => {
    // "les États-Unis"/"the United States"/"Estados Unidos" is treated as
    // plural in this clause across all 3 languages -- the only one of the
    // 8 supported Countries where this agreement matters.
    expect(fallbackNoticeText({ zone: "united-states", served_zone: "north-america" }, "fr")).toBe(
      "Affichage de l'Amérique du Nord — les États-Unis n'ont pas assez de couverture aujourd'hui."
    );
    expect(fallbackNoticeText({ zone: "united-states", served_zone: "north-america" }, "en")).toBe(
      "Showing North America — the United States don't have enough coverage today."
    );
    expect(fallbackNoticeText({ zone: "united-states", served_zone: "north-america" }, "es")).toBe(
      "Mostrando América del Norte — Estados Unidos no tienen suficiente cobertura hoy."
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
    expect(
      fallbackNoticeText({ zone: "not-a-real-zone", served_zone: "also-not-real" }, "fr")
    ).toBeNull();
    expect(fallbackNoticeText({ zone: "world", served_zone: "not-a-real-zone" }, "en")).toBeNull();
  });
});

describe("endScreenText", () => {
  it("uses singular French grammar for exactly 1 item", () => {
    expect(endScreenText(1, "day", "fr")).toBe(
      "Vous avez atteint la fin. 1 sujet a atteint le seuil aujourd'hui."
    );
  });

  it("uses plural French grammar for 2 or more items", () => {
    expect(endScreenText(2, "day", "fr")).toBe(
      "Vous avez atteint la fin. 2 sujets ont atteint le seuil aujourd'hui."
    );
    expect(endScreenText(4, "day", "fr")).toBe(
      "Vous avez atteint la fin. 4 sujets ont atteint le seuil aujourd'hui."
    );
  });

  it("uses correct singular/plural English grammar", () => {
    expect(endScreenText(1, "day", "en")).toBe(
      "You've reached the end. 1 story met the threshold today."
    );
    expect(endScreenText(4, "day", "en")).toBe(
      "You've reached the end. 4 stories met the threshold today."
    );
  });

  it("uses correct singular/plural Spanish grammar", () => {
    expect(endScreenText(1, "day", "es")).toBe(
      "Has llegado al final. 1 tema alcanzó el umbral hoy."
    );
    expect(endScreenText(4, "day", "es")).toBe(
      "Has llegado al final. 4 temas alcanzaron el umbral hoy."
    );
  });

  it("reuses periodSentenceText's exact wording for each Period, in each language", () => {
    expect(endScreenText(3, "day", "fr")).toContain("aujourd'hui.");
    expect(endScreenText(3, "week", "fr")).toContain("cette semaine.");
    expect(endScreenText(3, "month", "fr")).toContain("ce mois.");
    expect(endScreenText(3, "day", "en")).toContain("today.");
    expect(endScreenText(3, "day", "es")).toContain("hoy.");
  });

  it("returns null for 0 items instead of a nonsensical sentence, in any language", () => {
    // A real, already-observed case (Story 4.1's AC6: a real cycle run
    // produced zero qualifying Clusters). There is nothing to declare
    // "complete" when nothing rendered above it -- the End Screen must be
    // suppressed entirely for this input, not given invented copy no UX
    // spec defines.
    expect(endScreenText(0, "day", "fr")).toBeNull();
    expect(endScreenText(0, "day", "en")).toBeNull();
    expect(endScreenText(0, "day", "es")).toBeNull();
  });
});

describe("formatCount", () => {
  it("uses a space as the French-locale thousands separator, not a comma", () => {
    expect(formatCount(1384, "fr")).toBe("1 384");
  });

  it("uses a comma as the thousands separator for English and Spanish", () => {
    expect(formatCount(1384, "en")).toBe("1,384");
    expect(formatCount(1384, "es")).toBe("1,384");
  });

  it("returns single- and double-digit numbers unchanged, in any language", () => {
    expect(formatCount(4, "fr")).toBe("4");
    expect(formatCount(42, "en")).toBe("42");
  });

  it("handles 0 correctly (a real, currently-true state for discarded_ingested/kept)", () => {
    expect(formatCount(0, "fr")).toBe("0");
    expect(formatCount(0, "en")).toBe("0");
  });
});

describe("countryLabel", () => {
  it("returns the bare French country name for each of the 8 supported Countries", () => {
    expect(countryLabel("france", "fr")).toBe("France");
    expect(countryLabel("united-kingdom", "fr")).toBe("Royaume-Uni");
    expect(countryLabel("germany", "fr")).toBe("Allemagne");
    expect(countryLabel("united-states", "fr")).toBe("États-Unis");
    expect(countryLabel("japan", "fr")).toBe("Japon");
    expect(countryLabel("china", "fr")).toBe("Chine");
    expect(countryLabel("india", "fr")).toBe("Inde");
    expect(countryLabel("brazil", "fr")).toBe("Brésil");
  });

  it("returns the bare English country name for each of the 8 supported Countries", () => {
    expect(countryLabel("france", "en")).toBe("France");
    expect(countryLabel("united-kingdom", "en")).toBe("United Kingdom");
    expect(countryLabel("germany", "en")).toBe("Germany");
    expect(countryLabel("united-states", "en")).toBe("United States");
    expect(countryLabel("japan", "en")).toBe("Japan");
    expect(countryLabel("china", "en")).toBe("China");
    expect(countryLabel("india", "en")).toBe("India");
    expect(countryLabel("brazil", "en")).toBe("Brazil");
  });

  it("returns the bare Spanish country name for each of the 8 supported Countries", () => {
    expect(countryLabel("france", "es")).toBe("Francia");
    expect(countryLabel("united-kingdom", "es")).toBe("Reino Unido");
    expect(countryLabel("germany", "es")).toBe("Alemania");
    expect(countryLabel("united-states", "es")).toBe("Estados Unidos");
    expect(countryLabel("japan", "es")).toBe("Japón");
    expect(countryLabel("china", "es")).toBe("China");
    expect(countryLabel("india", "es")).toBe("India");
    expect(countryLabel("brazil", "es")).toBe("Brasil");
  });

  it("returns the slug itself for a country outside the 8 supported Countries (fixture realism, e.g. australia)", () => {
    // Fixture data plausibly includes source_country values like
    // "australia" that aren't among the 8 supported Countries this site
    // routes to -- countryLabel must degrade to the raw slug rather than
    // throwing or rendering "undefined" in the expanded source list.
    expect(countryLabel("australia", "fr")).toBe("australia");
    expect(countryLabel("australia", "en")).toBe("australia");
  });
});

describe("madLibsLeadIn", () => {
  it("returns the correct fixed lead-in for each language", () => {
    expect(madLibsLeadIn("fr")).toBe("Voici ce qui se passe");
    expect(madLibsLeadIn("en")).toBe("Here's what's happening");
    expect(madLibsLeadIn("es")).toBe("Esto es lo que está pasando");
  });
});

describe("consensusChipText", () => {
  it("returns the correct chip wording pair for each language", () => {
    expect(consensusChipText("fr")).toEqual({ sources: "sources indépendantes", countries: "pays" });
    expect(consensusChipText("en")).toEqual({ sources: "independent sources", countries: "countries" });
    expect(consensusChipText("es")).toEqual({
      sources: "fuentes independientes",
      countries: "países",
    });
  });
});

describe("sourceListIntro", () => {
  it("returns the correct source-list intro for each language", () => {
    expect(sourceListIntro("fr")).toBe("Sources et pays contributeurs :");
    expect(sourceListIntro("en")).toBe("Contributing sources and countries:");
    expect(sourceListIntro("es")).toBe("Fuentes y países contribuyentes:");
  });
});

describe("attributionText", () => {
  it("returns the correct attribution wording pair for each language", () => {
    expect(attributionText("fr")).toEqual({
      reportedBy: "Rapporté par",
      readOriginal: "lire l'article original →",
    });
    expect(attributionText("en")).toEqual({
      reportedBy: "Reported by",
      readOriginal: "read the original article →",
    });
    expect(attributionText("es")).toEqual({
      reportedBy: "Informado por",
      readOriginal: "leer el artículo original →",
    });
  });
});

describe("discardedVolumeText", () => {
  it("returns the correct Discarded Volume wording pair for each language", () => {
    expect(discardedVolumeText("fr")).toEqual({ reviewed: "articles examinés", kept: "conservés." });
    expect(discardedVolumeText("en")).toEqual({ reviewed: "articles reviewed", kept: "kept." });
    expect(discardedVolumeText("es")).toEqual({
      reviewed: "artículos examinados",
      kept: "conservados.",
    });
  });
});

describe("timestampPrefix", () => {
  it("returns the correct timestamp prefix for each language", () => {
    expect(timestampPrefix("fr")).toBe("Mis à jour à");
    expect(timestampPrefix("en")).toBe("Updated at");
    expect(timestampPrefix("es")).toBe("Actualizado a las");
  });
});

describe("offlineBannerText", () => {
  it("returns independently-authored text for each language, matching period-switcher.ts's own mirror", () => {
    expect(offlineBannerText("fr")).toBe("Vous consultez une version en cache d'un cycle précédent.");
    expect(offlineBannerText("en")).toBe("You're viewing a cached version from an earlier cycle.");
    expect(offlineBannerText("es")).toBe("Estás viendo una versión en caché de un ciclo anterior.");
  });
});
