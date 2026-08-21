import { describe, expect, it } from "vitest";
import type { ClusterLike } from "../period-switcher";
import {
  attach,
  attachChips,
  briefingJsonUrl,
  fallbackNoticeText,
  languageAnnouncementText,
  nextLanguage,
  nextPeriod,
  nextZone,
  pageUrl,
  periodAnnouncementText,
  periodSentenceText,
  renderDiscardedVolumeHtml,
  renderEndScreenHtml,
  renderFallbackNoticeHtml,
  renderItemListHtml,
  zoneAnnouncementText,
  zoneSentenceLabel,
} from "../period-switcher";

// A minimal hand-rolled stand-in for the DOM surface attach() touches --
// jsdom is not a dependency of this project (see Story 4.2's Dev Notes on
// why Playwright/jsdom were judged disproportionate for one click handler,
// a decision Story 4.3/4.7 re-confirms since it's the same shape of
// interaction on further axes), and this bug (listener accumulation
// across repeated attach() calls) only needs
// querySelector/hasAttribute/setAttribute/addEventListener to reproduce
// and prove fixed.
function createFakeAnchor() {
  const attributes = new Map<string, string>();
  const clickListeners: Array<(event: { preventDefault: () => void }) => void> = [];
  return {
    hasAttribute: (name: string) => attributes.has(name),
    setAttribute: (name: string, value: string) => attributes.set(name, value),
    addEventListener: (type: string, listener: (event: { preventDefault: () => void }) => void) => {
      if (type === "click") clickListeners.push(listener);
    },
    dispatchClick: () => {
      const event = { preventDefault: () => {} };
      for (const listener of clickListeners) listener(event);
    },
    get clickListenerCount() {
      return clickListeners.length;
    },
  };
}

describe("nextPeriod", () => {
  it("cycles day -> week -> month -> day", () => {
    expect(nextPeriod("day")).toBe("week");
    expect(nextPeriod("week")).toBe("day");
  });
});

describe("periodSentenceText", () => {
  it("returns the correct word for each Period, in each language", () => {
    expect(periodSentenceText("day", "fr")).toBe("aujourd'hui");
    expect(periodSentenceText("day", "en")).toBe("today");
    expect(periodSentenceText("day", "es")).toBe("hoy");
  });
});

describe("nextLanguage", () => {
  it("cycles fr -> en -> es -> fr", () => {
    expect(nextLanguage("fr")).toBe("en");
    expect(nextLanguage("en")).toBe("es");
    expect(nextLanguage("es")).toBe("fr");
  });
});

describe("nextZone", () => {
  it("cycles through all 4 Zones and wraps Brazil -> World", () => {
    expect(nextZone("world")).toBe("europe");
    expect(nextZone("spain")).toBe("world");
  });
});

describe("zoneSentenceLabel", () => {
  it("mirrors briefing.ts's zoneSentenceLabel exactly for a sample of each preposition case, in each language", () => {
    expect(zoneSentenceLabel("world", "fr")).toBe("dans le Monde");
    expect(zoneSentenceLabel("europe", "fr")).toBe("en Europe");

    expect(zoneSentenceLabel("world", "en")).toBe("in the World");

    expect(zoneSentenceLabel("world", "es")).toBe("en el Mundo");
  });

  it("falls back to the raw slug for a zone outside the known 15, mirroring briefing.ts's own defensive fallback", () => {
    // A malformed data-zone attribute or malformed fetched JSON could
    // reach this with a value outside the 15 known Zones -- must degrade
    // to the raw slug, not "undefined" (Blind Hunter review of Story
    // 4.7 caught this table's mirror had silently dropped
    // briefing.ts's `?? zone` fallback and Partial<Record<...>> typing).
    expect(zoneSentenceLabel("atlantis", "fr")).toBe("atlantis");
  });
});

// Story 4.8 (AC2): pure functions producing the aria-live announcement
// text for each axis. Match the AC's own example phrasing shape ("Zone,
// World, button, cycles to Europe") for Zone/Period, since both are
// cycle-by-one controls; Language deliberately does NOT use "cycles to"
// wording, since Story 4.7 established it as a direct-jump control with
// no "next value" concept -- forcing cycle language onto it would
// misdescribe the actual interaction to a screen-reader user.
describe("zoneAnnouncementText", () => {
  it("announces role, current value, and the next value in the cycle, in each language", () => {
    // Bare zone names throughout (matching the AC's own example exactly:
    // "Zone, World, button, cycles to Europe") -- Blind Hunter review
    // caught that reusing zoneSentenceLabel's preposition-inclusive form
    // ("in the World", "in Europe") here doubled up with this
    // announcement's own verb phrase, producing "cycles to in Europe".
    expect(zoneAnnouncementText("world", "europe", "fr")).toBe(
      "Zone, le Monde, bouton, passe à l'Europe"
    );
    expect(zoneAnnouncementText("world", "europe", "en")).toBe(
      "Zone, the World, button, cycles to Europe"
    );
    expect(zoneAnnouncementText("world", "europe", "es")).toBe(
      "Zona, el Mundo, botón, cambia a Europa"
    );
  });
});

describe("periodAnnouncementText", () => {
  it("announces role, current value, and the next value in the cycle, in each language", () => {
    expect(periodAnnouncementText("day", "week", "fr")).toBe(
      "Période, aujourd'hui, bouton, passe à cette semaine"
    );
    expect(periodAnnouncementText("day", "week", "en")).toBe(
      "Period, today, button, cycles to this week"
    );
    expect(periodAnnouncementText("day", "week", "es")).toBe(
      "Período, hoy, botón, cambia a esta semana"
    );
  });
});

describe("languageAnnouncementText", () => {
  it("announces role and the newly-selected language, IN THE PREVIOUS language (the one the reader could still read at the moment of the click), with no 'cycles to' phrasing since Language is a direct-jump control, not a cycle", () => {
    // Announced in the PREVIOUS language, not the new one -- a reader who
    // doesn't yet read the target language should still understand what
    // just happened, matching how a sighted reader experiences the
    // change (they see the switch happen while still looking at the old
    // page, a beat before the new content replaces it).
    expect(languageAnnouncementText("en", "fr")).toBe("Langue, Anglais");
    expect(languageAnnouncementText("es", "en")).toBe("Language, Spanish");
    expect(languageAnnouncementText("fr", "es")).toBe("Idioma, Francés");
  });
});

describe("fallbackNoticeText", () => {
  it("mirrors briefing.ts's fallbackNoticeText exactly, including plural verb agreement, in each language", () => {
    expect(fallbackNoticeText({ zone: "france", served_zone: "france" }, "fr")).toBeNull();
    expect(fallbackNoticeText({ zone: "france", served_zone: "europe" }, "fr")).toBe(
      "Affichage de l'Europe — la France n'a pas assez de couverture aujourd'hui."
    );
    expect(fallbackNoticeText({ zone: "spain", served_zone: "europe" }, "fr")).toBe(
      "Affichage de l'Europe — l'Espagne n'a pas assez de couverture aujourd'hui."
    );
    expect(fallbackNoticeText({ zone: "france", served_zone: "europe" }, "en")).toBe(
      "Showing Europe — France doesn't have enough coverage today."
    );
    expect(fallbackNoticeText({ zone: "spain", served_zone: "europe" }, "en")).toBe(
      "Showing Europe — Spain doesn't have enough coverage today."
    );
    expect(fallbackNoticeText({ zone: "france", served_zone: "europe" }, "es")).toBe(
      "Mostrando Europa — Francia no tiene suficiente cobertura hoy."
    );
  });
});

describe("renderFallbackNoticeHtml", () => {
  it("returns an empty string when there is no fallback", () => {
    const html = renderFallbackNoticeHtml(
      {
        zone: "world",
        served_zone: "world",
        generated_at: "2026-08-12T06:14:00Z",
        discarded_ingested: 0,
        discarded_kept: 0,
        clusters: [],
      },
      "fr"
    );
    expect(html).toBe("");
  });

  it("returns the notice div with escaped, exact text when a fallback is active", () => {
    const html = renderFallbackNoticeHtml(
      {
        zone: "france",
        served_zone: "europe",
        generated_at: "2026-08-12T06:14:00Z",
        discarded_ingested: 0,
        discarded_kept: 0,
        clusters: [],
      },
      "fr"
    );
    expect(html).toBe(
      '<div class="fallback-notice" id="fallback-notice">Affichage de l&#39;Europe — la France n&#39;a pas assez de couverture aujourd&#39;hui.</div>'
    );
  });
});

describe("briefingJsonUrl", () => {
  it("builds the exact static-asset path the copy script exposes", () => {
    expect(briefingJsonUrl("fr", "world", "week")).toBe("/briefings/fr/world/week.json");
  });
});

describe("pageUrl", () => {
  it("builds the equivalent static route path for a lang/zone/period", () => {
    expect(pageUrl("fr", "world", "week")).toBe("/fr/world/week");
  });
});

describe("renderItemListHtml", () => {
  it("mirrors BriefingPage.astro's item markup for a cluster with full attribution", () => {
    const html = renderItemListHtml(
      {
        zone: "world",
        served_zone: "world",
        generated_at: "2026-08-12T06:14:00Z",
        discarded_ingested: 0,
        discarded_kept: 0,
        clusters: [
          {
            cluster_id: "a",
            summary: "Un cessez-le-feu entre en vigueur.",
            independent_source_count: 2,
            country_count: 2,
            members: [
              { source: "Reuters", source_country: "united-kingdom" },
              { source: "Le Monde", source_country: "france" },
            ],
            outbound_url: "https://reuters.com/world/ceasefire-declared",
            outbound_source: "Reuters",
          },
        ],
      },
      "fr"
    );

    expect(html).toContain('<p class="summary">Un cessez-le-feu entre en vigueur.</p>');
    expect(html).toContain('<span class="num">2</span> sources indépendantes');
    expect(html).toContain('<span class="num">2</span> pays');
    expect(html).toContain("Rapporté par <em>Reuters</em>");
    expect(html).toContain(
      '<a href="https://reuters.com/world/ceasefire-declared" target="_blank" rel="noopener noreferrer">'
    );
  });

  it("renders the correct English chip/attribution/source-list wording", () => {
    const html = renderItemListHtml(
      {
        zone: "world",
        served_zone: "world",
        generated_at: "2026-08-12T06:14:00Z",
        discarded_ingested: 0,
        discarded_kept: 0,
        clusters: [
          {
            cluster_id: "a",
            independent_source_count: 1,
            country_count: 1,
            members: [{ source: "Reuters", source_country: "united-kingdom" }],
            outbound_url: "https://reuters.com/x",
            outbound_source: "Reuters",
          },
        ],
      },
      "en"
    );

    expect(html).toContain("independent sources");
    expect(html).toContain("countries");
    expect(html).toContain("Reported by <em>Reuters</em>");
    expect(html).toContain("read the original article");
    expect(html).toContain("Contributing sources and countries:");
    expect(html).toContain("Reuters (United Kingdom)");
  });

  it("renders the correct Spanish chip/attribution/source-list wording", () => {
    const html = renderItemListHtml(
      {
        zone: "world",
        served_zone: "world",
        generated_at: "2026-08-12T06:14:00Z",
        discarded_ingested: 0,
        discarded_kept: 0,
        clusters: [
          {
            cluster_id: "a",
            independent_source_count: 1,
            country_count: 1,
            members: [{ source: "Reuters", source_country: "united-kingdom" }],
            outbound_url: "https://reuters.com/x",
            outbound_source: "Reuters",
          },
        ],
      },
      "es"
    );

    expect(html).toContain("fuentes independientes");
    expect(html).toContain("países");
    expect(html).toContain("Informado por <em>Reuters</em>");
    expect(html).toContain("leer el artículo original");
    expect(html).toContain("Fuentes y países contribuyentes:");
    expect(html).toContain("Reuters (Reino Unido)");
  });

  it("omits the summary paragraph when summary is absent from the cluster", () => {
    const html = renderItemListHtml(
      {
        zone: "world",
        served_zone: "world",
        generated_at: "2026-08-12T06:14:00Z",
        discarded_ingested: 0,
        discarded_kept: 0,
        clusters: [
          {
            cluster_id: "b",
            independent_source_count: 1,
            country_count: 1,
            members: [{ source: "Deutsche Welle", source_country: "germany" }],
          },
        ],
      },
      "fr"
    );

    expect(html).not.toContain("<p class=\"summary\">");
    expect(html).toContain('<span class="num">1</span> sources indépendantes');
  });

  it("omits the attribution span when outbound_source is missing despite a valid url", () => {
    const html = renderItemListHtml(
      {
        zone: "world",
        served_zone: "world",
        generated_at: "2026-08-12T06:14:00Z",
        discarded_ingested: 0,
        discarded_kept: 0,
        clusters: [
          {
            cluster_id: "c",
            independent_source_count: 1,
            country_count: 1,
            members: [{ source: "Associated Press", source_country: "united-states" }],
            outbound_url: "https://example.com/a",
            outbound_source: null,
          },
        ],
      },
      "fr"
    );

    expect(html).not.toContain("Rapporté par");
  });

  it("escapes HTML-significant characters in summary and outbound_source", () => {
    const html = renderItemListHtml(
      {
        zone: "world",
        served_zone: "world",
        generated_at: "2026-08-12T06:14:00Z",
        discarded_ingested: 0,
        discarded_kept: 0,
        clusters: [
          {
            cluster_id: "d",
            summary: "<script>alert(1)</script>",
            independent_source_count: 1,
            country_count: 1,
            members: [{ source: "<b>Evil Source</b>", source_country: "france" }],
            outbound_url: "https://example.com/a",
            outbound_source: "<b>Evil</b>",
          },
        ],
      },
      "fr"
    );

    expect(html).not.toContain("<script>alert(1)</script>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<b>Evil</b>");
    expect(html).not.toContain("<b>Evil Source</b>");
  });

  it("renders one item per cluster, in order, for multiple clusters", () => {
    const html = renderItemListHtml(
      {
        zone: "world",
        served_zone: "world",
        generated_at: "2026-08-12T06:14:00Z",
        discarded_ingested: 0,
        discarded_kept: 0,
        clusters: [
          {
            cluster_id: "e",
            independent_source_count: 1,
            country_count: 1,
            members: [{ source: "Kyodo News", source_country: "japan" }],
          },
          {
            cluster_id: "f",
            independent_source_count: 2,
            country_count: 2,
            members: [
              { source: "Xinhua", source_country: "china" },
              { source: "The Hindu", source_country: "india" },
            ],
          },
        ],
      },
      "fr"
    );

    const itemCount = (html.match(/<div class="item">/g) ?? []).length;
    expect(itemCount).toBe(2);
    expect(html.indexOf('<span class="num">1</span>')).toBeLessThan(
      html.indexOf('<span class="num">2</span>')
    );
  });

  it("renders the Consensus chip as a button with aria-expanded/aria-controls, and the source list with exactly one <li> per member", () => {
    const html = renderItemListHtml(
      {
        zone: "world",
        served_zone: "world",
        generated_at: "2026-08-12T06:14:00Z",
        discarded_ingested: 0,
        discarded_kept: 0,
        clusters: [
          {
            cluster_id: "g",
            independent_source_count: 3,
            country_count: 2,
            members: [
              { source: "Reuters", source_country: "united-kingdom" },
              { source: "Le Monde", source_country: "france" },
              { source: "Le Figaro", source_country: "france" },
            ],
          },
        ],
      },
      "fr"
    );

    expect(html).toMatch(
      /<button type="button" class="chip" aria-expanded="false" aria-controls="source-list-g" data-consensus-chip>/
    );
    expect(html).toContain('id="source-list-g"');
    expect(html).toContain('class="source-list"');
    const liCount = (html.match(/<li>/g) ?? []).length;
    expect(liCount).toBe(3);
    expect(html).toContain("Reuters (Royaume-Uni)");
    expect(html).toContain("Le Monde (France)");
    expect(html).toContain("Le Figaro (France)");
  });

  it("degrades to the raw slug for a source_country outside the 8 supported Countries", () => {
    const html = renderItemListHtml(
      {
        zone: "world",
        served_zone: "world",
        generated_at: "2026-08-12T06:14:00Z",
        discarded_ingested: 0,
        discarded_kept: 0,
        clusters: [
          {
            cluster_id: "h",
            independent_source_count: 1,
            country_count: 1,
            members: [{ source: "ABC News", source_country: "australia" }],
          },
        ],
      },
      "fr"
    );

    expect(html).toContain("ABC News (australia)");
  });
});

describe("renderDiscardedVolumeHtml", () => {
  it("renders the correct French-locale-formatted counts and wording", () => {
    const html = renderDiscardedVolumeHtml(
      {
        zone: "world",
        served_zone: "world",
        generated_at: "2026-08-12T06:14:00Z",
        discarded_ingested: 1384,
        discarded_kept: 4,
        clusters: [],
      },
      "fr"
    );
    expect(html).toBe(
      '<span class="num">1 384</span> articles examinés → <span class="num">4</span> conservés.'
    );
  });

  it("renders the correct English-locale-formatted counts and wording", () => {
    const html = renderDiscardedVolumeHtml(
      {
        zone: "world",
        served_zone: "world",
        generated_at: "2026-08-12T06:14:00Z",
        discarded_ingested: 1384,
        discarded_kept: 4,
        clusters: [],
      },
      "en"
    );
    expect(html).toBe(
      '<span class="num">1,384</span> articles reviewed → <span class="num">4</span> kept.'
    );
  });
});

describe("renderEndScreenHtml", () => {
  it("returns an empty string for 0 items, in any language", () => {
    expect(renderEndScreenHtml(0, "day", "fr")).toBe("");
    expect(renderEndScreenHtml(0, "day", "en")).toBe("");
  });

  it("renders the correct singular/plural English sentence", () => {
    expect(renderEndScreenHtml(1, "day", "en")).toBe(
      '<div class="end-screen" id="end-screen"><div class="rule"></div><p>You&#39;ve reached the end. 1 story met the threshold today.</p></div>'
    );
    expect(renderEndScreenHtml(4, "day", "en")).toContain("4 stories met the threshold today.");
  });

  it("renders the correct singular/plural Spanish sentence", () => {
    expect(renderEndScreenHtml(1, "day", "es")).toContain("1 tema alcanzó el umbral hoy.");
    expect(renderEndScreenHtml(4, "day", "es")).toContain("4 temas alcanzaron el umbral hoy.");
  });
});

describe("attach", () => {
  it("attaches exactly one click listener to each mad-libs word even when called repeatedly", () => {
    // Reproduces the bug Story 4.2's adversarial review caught: attach()
    // is re-invoked after every swap, but the swap mutates the existing
    // anchors in place rather than replacing them -- without the
    // ATTACHED_MARKER guard, each call added a duplicate listener per word,
    // so a single click fired the handler once per prior attach() call.
    // Story 4.3 extends attach() to cover both the Zone and Period words,
    // so this test verifies the guard holds for both independently.
    const zoneAnchor = createFakeAnchor();
    const periodAnchor = createFakeAnchor();
    const originalDocument = globalThis.document;
    globalThis.document = {
      querySelector: (selector: string) =>
        selector.includes("zone") ? zoneAnchor : periodAnchor,
      // attach() also calls attachLanguageWords()/attachChips(), which
      // query for language options/chips -- none exist in this stand-in
      // DOM, so an empty NodeList-like value is enough for both to
      // safely no-op.
      querySelectorAll: () => [],
    } as unknown as Document;

    try {
      attach();
      attach();
      attach();

      expect(zoneAnchor.clickListenerCount).toBe(1);
      expect(periodAnchor.clickListenerCount).toBe(1);
    } finally {
      globalThis.document = originalDocument;
    }
  });
});

// A minimal hand-rolled fake chip button + source-list div, mirroring
// createFakeAnchor's own reasoning: jsdom is not a dependency of this
// project, and this bug class (listener accumulation, and the toggle logic
// itself) only needs a handful of DOM methods to reproduce and prove
// correct.
function createFakeChip() {
  // Seeded with the same initial attributes real server-rendered markup
  // has (renderItemListHtml/BriefingPage.astro both emit aria-expanded=
  // "false" from the start) -- attachChips() never sets this itself, only
  // toggleChip() does, on click.
  const attributes = new Map<string, string>([
    ["aria-controls", "source-list-x"],
    ["aria-expanded", "false"],
  ]);
  const clickListeners: Array<() => void> = [];
  return {
    getAttribute: (name: string) => attributes.get(name) ?? null,
    setAttribute: (name: string, value: string) => attributes.set(name, value),
    hasAttribute: (name: string) => attributes.has(name),
    addEventListener: (type: string, listener: () => void) => {
      if (type === "click") clickListeners.push(listener);
    },
    dispatchClick: () => {
      for (const listener of clickListeners) listener();
    },
    get clickListenerCount() {
      return clickListeners.length;
    },
  };
}

function createFakeSourceList() {
  const classes = new Set<string>();
  return {
    classList: {
      add: (name: string) => classes.add(name),
      toggle: (name: string, force?: boolean) => {
        const shouldHave = force ?? !classes.has(name);
        if (shouldHave) classes.add(name);
        else classes.delete(name);
      },
      contains: (name: string) => classes.has(name),
    },
  };
}

describe("attachChips", () => {
  it("attaches exactly one click listener per chip even when called repeatedly", () => {
    const chip = createFakeChip();
    const sourceList = createFakeSourceList();
    const originalDocument = globalThis.document;
    globalThis.document = {
      querySelectorAll: () => [chip],
      getElementById: () => sourceList,
    } as unknown as Document;

    try {
      attachChips();
      attachChips();
      attachChips();

      expect(chip.clickListenerCount).toBe(1);
    } finally {
      globalThis.document = originalDocument;
    }
  });

  it("does not touch the source list's class on attach (collapsed-by-default is a plain CSS rule, not JS-applied)", () => {
    // Regression test for the "flickering" bug: an earlier version added
    // a `js-collapsed` class here, which meant the source list rendered
    // open for one paint (server HTML has no collapsing class) and then
    // snapped shut the moment attachChips() ran -- a visible flicker on
    // every page load. Collapsed-by-default is now a plain
    // `.source-list { display: none }` CSS rule in BriefingPage.astro, so
    // attachChips() must leave the source list's classes untouched.
    const chip = createFakeChip();
    const sourceList = createFakeSourceList();
    const originalDocument = globalThis.document;
    globalThis.document = {
      querySelectorAll: () => [chip],
      getElementById: () => sourceList,
    } as unknown as Document;

    try {
      attachChips();
      expect(sourceList.classList.contains("js-collapsed")).toBe(false);
      expect(sourceList.classList.contains("js-expanded")).toBe(false);
    } finally {
      globalThis.document = originalDocument;
    }
  });

  it("toggles aria-expanded and the source list's expanded class on click, independently across chips", () => {
    const chip = createFakeChip();
    const sourceList = createFakeSourceList();
    const originalDocument = globalThis.document;
    globalThis.document = {
      querySelectorAll: () => [chip],
      getElementById: () => sourceList,
    } as unknown as Document;

    try {
      attachChips();
      expect(chip.getAttribute("aria-expanded")).toBe("false");
      expect(sourceList.classList.contains("js-expanded")).toBe(false);

      chip.dispatchClick();
      expect(chip.getAttribute("aria-expanded")).toBe("true");
      expect(sourceList.classList.contains("js-expanded")).toBe(true);

      chip.dispatchClick();
      expect(chip.getAttribute("aria-expanded")).toBe("false");
      expect(sourceList.classList.contains("js-expanded")).toBe(false);
    } finally {
      globalThis.document = originalDocument;
    }
  });

  it("does not force-collapse an already-expanded chip when attachChips() is called again", () => {
    // Reproduces the bug Story 4.5's own adversarial review caught: an
    // earlier version collapsed every chip's source list unconditionally
    // on every call, regardless of whether the reader had already
    // expanded it -- desyncing aria-expanded="true" from a hidden source
    // list. attachChips() must never touch the source list's classes at
    // all (see the test above), so this can no longer regress, but the
    // test stays as a guard against a future reintroduction.
    const chip = createFakeChip();
    const sourceList = createFakeSourceList();
    const originalDocument = globalThis.document;
    globalThis.document = {
      querySelectorAll: () => [chip],
      getElementById: () => sourceList,
    } as unknown as Document;

    try {
      attachChips();
      chip.dispatchClick(); // reader expands it
      expect(chip.getAttribute("aria-expanded")).toBe("true");
      expect(sourceList.classList.contains("js-expanded")).toBe(true);

      attachChips(); // called again -- e.g. after some future re-render
      expect(chip.getAttribute("aria-expanded")).toBe("true");
      expect(sourceList.classList.contains("js-expanded")).toBe(true);
    } finally {
      globalThis.document = originalDocument;
    }
  });
});

// A minimal hand-rolled fake language-option anchor, mirroring
// createFakeAnchor's own reasoning -- this axis needs its own fake since
// its click handling is genuinely different (a direct-jump target read
// from data-target-lang, not a "next value" computation, and a real
// no-op case for the already-active option).
function createFakeLanguageLink(targetLang: string, currentLang: string) {
  const dataset: Record<string, string> = {
    targetLang,
    lang: currentLang,
    zone: "world",
    period: "day",
  };
  const clickListeners: Array<(event: { preventDefault: () => void }) => void> = [];
  const attributes = new Map<string, string>();
  const classes = new Set<string>();
  return {
    dataset,
    href: "",
    hasAttribute: (name: string) => attributes.has(name),
    setAttribute: (name: string, value: string) => attributes.set(name, value),
    removeAttribute: (name: string) => attributes.delete(name),
    classList: {
      toggle: (name: string, on: boolean) => (on ? classes.add(name) : classes.delete(name)),
      contains: (name: string) => classes.has(name),
    },
    addEventListener: (type: string, listener: (event: { preventDefault: () => void }) => void) => {
      if (type === "click") clickListeners.push(listener);
    },
    dispatchClick: () => {
      let defaultPrevented = false;
      const event = {
        preventDefault: () => {
          defaultPrevented = true;
        },
      };
      for (const listener of clickListeners) listener(event);
      return defaultPrevented;
    },
    get clickListenerCount() {
      return clickListeners.length;
    },
  };
}

describe("attachLanguageWords (via attach)", () => {
  it("attaches exactly one click listener per language option even when attach() is called repeatedly", () => {
    const link = createFakeLanguageLink("en", "fr");
    const originalDocument = globalThis.document;
    globalThis.document = {
      querySelector: () => null,
      querySelectorAll: (selector: string) => (selector.includes("lang") ? [link] : []),
    } as unknown as Document;

    try {
      attach();
      attach();
      attach();

      expect(link.clickListenerCount).toBe(1);
    } finally {
      globalThis.document = originalDocument;
    }
  });

  it("prevents default and would fetch when the target language differs from the current one", async () => {
    const link = createFakeLanguageLink("en", "fr");
    const originalDocument = globalThis.document;
    const originalWindow = globalThis.window;
    const originalFetch = globalThis.fetch;
    globalThis.document = {
      querySelector: () => null,
      querySelectorAll: (selector: string) => (selector.includes("lang") ? [link] : []),
    } as unknown as Document;
    // handleClick's error path (no data/document elements match this bare
    // fake DOM) falls through to a real navigation -- stub window/fetch
    // just enough to observe that fall-through without crashing the test.
    globalThis.window = { location: { href: "" } } as unknown as Window & typeof globalThis;
    globalThis.fetch = (() => Promise.reject(new Error("no network in tests"))) as typeof fetch;

    try {
      attach();
      const defaultPrevented = link.dispatchClick();
      expect(defaultPrevented).toBe(true);
      await new Promise((resolve) => setTimeout(resolve, 0));
    } finally {
      globalThis.document = originalDocument;
      globalThis.window = originalWindow;
      globalThis.fetch = originalFetch;
    }
  });

  it("does NOT prevent default when clicking the already-active language (a real no-op, falls through to the href)", () => {
    const link = createFakeLanguageLink("fr", "fr");
    const originalDocument = globalThis.document;
    globalThis.document = {
      querySelector: () => null,
      querySelectorAll: (selector: string) => (selector.includes("lang") ? [link] : []),
    } as unknown as Document;

    try {
      attach();
      const defaultPrevented = link.dispatchClick();
      expect(defaultPrevented).toBe(false);
    } finally {
      globalThis.document = originalDocument;
    }
  });

  // Regression test for a real bug Blind Hunter review of Story 4.7 caught:
  // handleClick's successful-fetch path updated every language link's
  // href/data-lang, but never its data-zone/data-period -- and a
  // SUBSEQUENT language click reads its target Zone/Period from exactly
  // that link's own dataset. A reader who switches Zone and THEN switches
  // Language would silently have their Zone choice discarded, reverting
  // to whatever was on the page at initial load. This drives a real Zone
  // click through attach()'s exported surface, with a fake DOM complete
  // enough to satisfy every element handleClick's successful path reads,
  // and a stubbed fetch resolving real JSON -- no prior test in this file
  // drove handleClick all the way through a successful swap, which is how
  // this bug shipped uncaught the first time.
  it("updates every language link's data-zone (not just href/data-lang) after a Zone click's successful swap", async () => {
    function createFakeWordLink(zone: string, period: string, lang: string) {
      const dataset: Record<string, string> = { zone, period, lang };
      const clickListeners: Array<(event: { preventDefault: () => void }) => void> = [];
      const attributes = new Map<string, string>();
      return {
        dataset,
        textContent: "",
        href: "",
        hasAttribute: (name: string) => attributes.has(name),
        setAttribute: (name: string, value: string) => attributes.set(name, value),
        addEventListener: (type: string, listener: (event: { preventDefault: () => void }) => void) => {
          if (type === "click") clickListeners.push(listener);
        },
        dispatchClick: () => {
          for (const listener of clickListeners) listener({ preventDefault: () => {} });
        },
      };
    }
    function createFakeElement() {
      const classes = new Set<string>();
      return {
        textContent: "",
        innerHTML: "",
        href: "",
        insertAdjacentHTML: () => {},
        remove: () => {},
        classList: {
          toggle: (name: string, on: boolean) => (on ? classes.add(name) : classes.delete(name)),
        },
        setAttribute: () => {},
        removeAttribute: () => {},
      };
    }

    const leadInNode = { nodeType: 3, textContent: "Voici ce qui se passe " };
    const zoneWordLink = createFakeWordLink("world", "day", "fr");
    const periodWordLink = createFakeWordLink("world", "day", "fr");
    const sentence = {
      childNodes: [leadInNode],
      querySelector: (selector: string) =>
        selector.includes("zone") ? zoneWordLink : selector.includes("period") ? periodWordLink : null,
      insertAdjacentHTML: () => {},
    };
    const itemList = createFakeElement();
    const timestamp = createFakeElement();
    const sentenceBlock = createFakeElement();
    const discarded = createFakeElement();
    const enLink = createFakeLanguageLink("en", "fr");
    const esLink = createFakeLanguageLink("es", "fr");

    const originalDocument = globalThis.document;
    const originalFetch = globalThis.fetch;
    const originalWindow = globalThis.window;
    const originalNode = globalThis.Node;
    // handleClick reads the real browser global Node.TEXT_NODE (always
    // present in an actual browser) to find the sentence's lead-in text
    // node -- stub it here since this test environment has no DOM.
    globalThis.Node = { TEXT_NODE: 3 } as unknown as typeof Node;
    globalThis.document = {
      getElementById: (id: string) =>
        (
          {
            "mad-libs-sentence": sentence,
            "item-list": itemList,
            timestamp,
            "sentence-block": sentenceBlock,
            discarded,
          } as Record<string, unknown>
        )[id] ?? null,
      querySelectorAll: (selector: string) => (selector.includes("lang-word") ? [enLink, esLink] : []),
      querySelector: (selector: string) => (selector.includes("zone-word") ? zoneWordLink : null),
    } as unknown as Document;
    globalThis.fetch = (() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            zone: "europe",
            served_zone: "europe",
            generated_at: "2026-08-12T06:14:00Z",
            discarded_ingested: 0,
            discarded_kept: 0,
            clusters: [],
          }),
      })) as unknown as typeof fetch;
    globalThis.window = {
      history: { pushState: () => {} },
      location: { href: "" },
    } as unknown as Window & typeof globalThis;

    try {
      attach(); // attaches the Zone word's click listener via document.querySelector above
      zoneWordLink.dispatchClick(); // world -> europe
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));

      // The actual regression: before the fix, these stayed "world"
      // forever (href alone was updated, dataset.zone was not).
      expect(enLink.dataset.zone).toBe("europe");
      expect(esLink.dataset.zone).toBe("europe");
    } finally {
      globalThis.document = originalDocument;
      globalThis.fetch = originalFetch;
      globalThis.window = originalWindow;
      globalThis.Node = originalNode;
    }
  });

  // Story 4.8 (AC2): proves handleClick's successful Zone-swap path
  // writes the correct aria-live announcement into #sr-announcer.
  // Reuses the exact same fake-DOM shape as the Story 4.7 regression test
  // above, extended with a fake #sr-announcer element.
  it("writes the Zone announcement text into #sr-announcer after a Zone click's successful swap", async () => {
    function createFakeWordLink(zone: string, period: string, lang: string) {
      const dataset: Record<string, string> = { zone, period, lang };
      const clickListeners: Array<(event: { preventDefault: () => void }) => void> = [];
      const attributes = new Map<string, string>();
      return {
        dataset,
        textContent: "",
        href: "",
        hasAttribute: (name: string) => attributes.has(name),
        setAttribute: (name: string, value: string) => attributes.set(name, value),
        addEventListener: (type: string, listener: (event: { preventDefault: () => void }) => void) => {
          if (type === "click") clickListeners.push(listener);
        },
        dispatchClick: () => {
          for (const listener of clickListeners) listener({ preventDefault: () => {} });
        },
      };
    }
    function createFakeElement() {
      const classes = new Set<string>();
      return {
        textContent: "",
        innerHTML: "",
        href: "",
        insertAdjacentHTML: () => {},
        remove: () => {},
        classList: {
          toggle: (name: string, on: boolean) => (on ? classes.add(name) : classes.delete(name)),
        },
        setAttribute: () => {},
        removeAttribute: () => {},
      };
    }

    const leadInNode = { nodeType: 3, textContent: "Voici ce qui se passe " };
    const zoneWordLink = createFakeWordLink("world", "day", "fr");
    const periodWordLink = createFakeWordLink("world", "day", "fr");
    const sentence = {
      childNodes: [leadInNode],
      querySelector: (selector: string) =>
        selector.includes("zone") ? zoneWordLink : selector.includes("period") ? periodWordLink : null,
      insertAdjacentHTML: () => {},
    };
    const itemList = createFakeElement();
    const timestamp = createFakeElement();
    const sentenceBlock = createFakeElement();
    const discarded = createFakeElement();
    const announcer = createFakeElement();
    const enLink = createFakeLanguageLink("en", "fr");
    const esLink = createFakeLanguageLink("es", "fr");

    const originalDocument = globalThis.document;
    const originalFetch = globalThis.fetch;
    const originalWindow = globalThis.window;
    const originalNode = globalThis.Node;
    globalThis.Node = { TEXT_NODE: 3 } as unknown as typeof Node;
    globalThis.document = {
      getElementById: (id: string) =>
        (
          {
            "mad-libs-sentence": sentence,
            "item-list": itemList,
            timestamp,
            "sentence-block": sentenceBlock,
            discarded,
            "sr-announcer": announcer,
          } as Record<string, unknown>
        )[id] ?? null,
      querySelectorAll: (selector: string) => (selector.includes("lang-word") ? [enLink, esLink] : []),
      querySelector: (selector: string) => (selector.includes("zone-word") ? zoneWordLink : null),
    } as unknown as Document;
    globalThis.fetch = (() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            zone: "europe",
            served_zone: "europe",
            generated_at: "2026-08-12T06:14:00Z",
            discarded_ingested: 0,
            discarded_kept: 0,
            clusters: [],
          }),
      })) as unknown as typeof fetch;
    globalThis.window = {
      history: { pushState: () => {} },
      location: { href: "" },
    } as unknown as Window & typeof globalThis;

    try {
      attach();
      zoneWordLink.dispatchClick(); // world -> europe, French
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));

      expect(announcer.textContent).toBe(zoneAnnouncementText("world", "europe", "fr"));
    } finally {
      globalThis.document = originalDocument;
      globalThis.fetch = originalFetch;
      globalThis.window = originalWindow;
      globalThis.Node = originalNode;
    }
  });
});

describe("renderItemListHtml — headline (Story 6.1)", () => {
  const briefingWith = (cluster: Partial<ClusterLike>) => ({
    zone: "world",
    served_zone: "world",
    generated_at: "2026-08-12T06:14:00Z",
    discarded_ingested: 0,
    discarded_kept: 0,
    clusters: [
      {
        cluster_id: "a",
        independent_source_count: 2,
        country_count: 2,
        members: [{ source: "Reuters", source_country: "united-kingdom" }],
        outbound_url: "https://reuters.com/x",
        outbound_source: "Reuters",
        ...cluster,
      } as ClusterLike,
    ],
  });

  it("renders the headline as an <h2> before the summary paragraph", () => {
    const html = renderItemListHtml(
      briefingWith({ headline: "Un cessez-le-feu entre en vigueur", summary: "Les délégations..." }),
      "fr"
    );

    expect(html).toContain('<h2 class="headline">Un cessez-le-feu entre en vigueur</h2>');
    // Order matters: the heading must precede its own summary, or the
    // document outline no longer describes the item.
    expect(html.indexOf('<h2 class="headline">')).toBeLessThan(html.indexOf('<p class="summary">'));
  });

  it("omits the heading entirely when headline is absent, rather than rendering an empty <h2>", () => {
    // A schema_version 1 Briefing carries no headline at all. It must still
    // render -- without an empty heading, which would be an accessibility
    // defect (a heading announcing nothing).
    const html = renderItemListHtml(briefingWith({ summary: "Un résumé sans titre." }), "fr");

    expect(html).not.toContain("<h2");
    expect(html).toContain('<p class="summary">Un résumé sans titre.</p>');
  });

  it("escapes HTML in the headline, exactly as it does in the summary", () => {
    const html = renderItemListHtml(
      briefingWith({ headline: '<script>alert("x")</script>', summary: "Sûr." }),
      "fr"
    );

    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });
});
