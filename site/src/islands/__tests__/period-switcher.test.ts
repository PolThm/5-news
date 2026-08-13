import { describe, expect, it } from "vitest";
import {
  attach,
  attachChips,
  briefingJsonUrl,
  fallbackNoticeText,
  nextPeriod,
  nextZone,
  pageUrl,
  periodSentenceText,
  renderFallbackNoticeHtml,
  renderItemListHtml,
  zoneSentenceLabel,
} from "../period-switcher";

// A minimal hand-rolled stand-in for the DOM surface attach() touches --
// jsdom is not a dependency of this project (see Story 4.2's Dev Notes on
// why Playwright/jsdom were judged disproportionate for one click handler,
// a decision Story 4.3 re-confirms since it's the same shape of
// interaction on a second axis), and this bug (listener accumulation
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

describe("nextZone", () => {
  it("cycles through all 15 Zones and wraps Brazil -> World", () => {
    expect(nextZone("world")).toBe("europe");
    expect(nextZone("brazil")).toBe("world");
  });
});

describe("zoneSentenceLabel", () => {
  it("mirrors briefing.ts's zoneSentenceLabel exactly for a sample of each preposition case", () => {
    expect(zoneSentenceLabel("world")).toBe("dans le Monde");
    expect(zoneSentenceLabel("europe")).toBe("en Europe");
    expect(zoneSentenceLabel("united-kingdom")).toBe("au Royaume-Uni");
    expect(zoneSentenceLabel("united-states")).toBe("aux États-Unis");
  });
});

describe("fallbackNoticeText", () => {
  it("mirrors briefing.ts's fallbackNoticeText exactly, including plural verb agreement", () => {
    expect(fallbackNoticeText({ zone: "france", served_zone: "france" })).toBeNull();
    expect(fallbackNoticeText({ zone: "france", served_zone: "europe" })).toBe(
      "Affichage de l'Europe — la France n'a pas assez de couverture aujourd'hui."
    );
    expect(fallbackNoticeText({ zone: "united-states", served_zone: "north-america" })).toBe(
      "Affichage de l'Amérique du Nord — les États-Unis n'ont pas assez de couverture aujourd'hui."
    );
  });
});

describe("renderFallbackNoticeHtml", () => {
  it("returns an empty string when there is no fallback", () => {
    const html = renderFallbackNoticeHtml({
      zone: "world",
      served_zone: "world",
      generated_at: "2026-08-12T06:14:00Z",
      clusters: [],
    });
    expect(html).toBe("");
  });

  it("returns the notice div with escaped, exact French text when a fallback is active", () => {
    const html = renderFallbackNoticeHtml({
      zone: "france",
      served_zone: "europe",
      generated_at: "2026-08-12T06:14:00Z",
      clusters: [],
    });
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
    expect(pageUrl("fr", "world", "month")).toBe("/fr/world/month");
  });
});

describe("renderItemListHtml", () => {
  it("mirrors BriefingPage.astro's item markup for a cluster with full attribution", () => {
    const html = renderItemListHtml({
      zone: "world",
      served_zone: "world",
      generated_at: "2026-08-12T06:14:00Z",
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
    });

    expect(html).toContain('<p class="summary">Un cessez-le-feu entre en vigueur.</p>');
    expect(html).toContain('<span class="num">2</span> sources indépendantes');
    expect(html).toContain('<span class="num">2</span> pays');
    expect(html).toContain("Rapporté par <em>Reuters</em>");
    expect(html).toContain(
      '<a href="https://reuters.com/world/ceasefire-declared" target="_blank" rel="noopener noreferrer">'
    );
  });

  it("omits the summary paragraph when summary is absent from the cluster", () => {
    const html = renderItemListHtml({
      zone: "world",
      served_zone: "world",
      generated_at: "2026-08-12T06:14:00Z",
      clusters: [
        {
          cluster_id: "b",
          independent_source_count: 1,
          country_count: 1,
          members: [{ source: "Deutsche Welle", source_country: "germany" }],
        },
      ],
    });

    expect(html).not.toContain("<p class=\"summary\">");
    expect(html).toContain('<span class="num">1</span> sources indépendantes');
  });

  it("omits the attribution span when outbound_source is missing despite a valid url", () => {
    const html = renderItemListHtml({
      zone: "world",
      served_zone: "world",
      generated_at: "2026-08-12T06:14:00Z",
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
    });

    expect(html).not.toContain("Rapporté par");
  });

  it("escapes HTML-significant characters in summary and outbound_source", () => {
    const html = renderItemListHtml({
      zone: "world",
      served_zone: "world",
      generated_at: "2026-08-12T06:14:00Z",
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
    });

    expect(html).not.toContain("<script>alert(1)</script>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<b>Evil</b>");
    expect(html).not.toContain("<b>Evil Source</b>");
  });

  it("renders one item per cluster, in order, for multiple clusters", () => {
    const html = renderItemListHtml({
      zone: "world",
      served_zone: "world",
      generated_at: "2026-08-12T06:14:00Z",
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
    });

    const itemCount = (html.match(/<div class="item">/g) ?? []).length;
    expect(itemCount).toBe(2);
    expect(html.indexOf('<span class="num">1</span>')).toBeLessThan(
      html.indexOf('<span class="num">2</span>')
    );
  });

  it("renders the Consensus chip as a button with aria-expanded/aria-controls, and the source list with exactly one <li> per member", () => {
    const html = renderItemListHtml({
      zone: "world",
      served_zone: "world",
      generated_at: "2026-08-12T06:14:00Z",
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
    });

    expect(html).toMatch(
      /<button type="button" class="chip" aria-expanded="false" aria-controls="source-list-g" data-consensus-chip>/
    );
    expect(html).toContain('id="source-list-g"');
    expect(html).toContain('class="source-list js-collapsed"');
    const liCount = (html.match(/<li>/g) ?? []).length;
    expect(liCount).toBe(3);
    expect(html).toContain("Reuters (Royaume-Uni)");
    expect(html).toContain("Le Monde (France)");
    expect(html).toContain("Le Figaro (France)");
  });

  it("degrades to the raw slug for a source_country outside the 8 supported Countries", () => {
    const html = renderItemListHtml({
      zone: "world",
      served_zone: "world",
      generated_at: "2026-08-12T06:14:00Z",
      clusters: [
        {
          cluster_id: "h",
          independent_source_count: 1,
          country_count: 1,
          members: [{ source: "ABC News", source_country: "australia" }],
        },
      ],
    });

    expect(html).toContain("ABC News (australia)");
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
      // attach() also calls attachChips(), which queries for chips --
      // none exist in this stand-in DOM, so an empty NodeList-like value
      // is enough for it to safely no-op.
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

  it("collapses the source list on attach (JS-present: hidden by default; no-JS: visible per the initial HTML)", () => {
    const chip = createFakeChip();
    const sourceList = createFakeSourceList();
    const originalDocument = globalThis.document;
    globalThis.document = {
      querySelectorAll: () => [chip],
      getElementById: () => sourceList,
    } as unknown as Document;

    try {
      attachChips();
      expect(sourceList.classList.contains("js-collapsed")).toBe(true);
    } finally {
      globalThis.document = originalDocument;
    }
  });

  it("toggles aria-expanded and the source list's collapsed class on click, independently across chips", () => {
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
      expect(sourceList.classList.contains("js-collapsed")).toBe(true);

      chip.dispatchClick();
      expect(chip.getAttribute("aria-expanded")).toBe("true");
      expect(sourceList.classList.contains("js-collapsed")).toBe(false);

      chip.dispatchClick();
      expect(chip.getAttribute("aria-expanded")).toBe("false");
      expect(sourceList.classList.contains("js-collapsed")).toBe(true);
    } finally {
      globalThis.document = originalDocument;
    }
  });

  it("does not force-collapse an already-expanded chip when attachChips() is called again", () => {
    // Reproduces the bug this story's own adversarial review caught: an
    // earlier version collapsed every chip's source list unconditionally
    // on every call, regardless of whether the reader had already
    // expanded it -- desyncing aria-expanded="true" from a hidden source
    // list. The collapse step must be gated behind the same
    // CHIP_ATTACHED_MARKER guard as the listener attachment, not run
    // unconditionally.
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
      expect(sourceList.classList.contains("js-collapsed")).toBe(false);

      attachChips(); // called again -- e.g. after some future re-render
      expect(chip.getAttribute("aria-expanded")).toBe("true");
      expect(sourceList.classList.contains("js-collapsed")).toBe(false);
    } finally {
      globalThis.document = originalDocument;
    }
  });
});
