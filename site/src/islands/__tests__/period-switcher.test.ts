import { describe, expect, it } from "vitest";
import {
  attach,
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
          independent_source_count: 7,
          country_count: 5,
          outbound_url: "https://reuters.com/world/ceasefire-declared",
          outbound_source: "Reuters",
        },
      ],
    });

    expect(html).toContain('<p class="summary">Un cessez-le-feu entre en vigueur.</p>');
    expect(html).toContain('<span class="num">7</span> sources indépendantes');
    expect(html).toContain('<span class="num">5</span> pays');
    expect(html).toContain("Rapporté par <em>Reuters</em>");
    expect(html).toContain('<a href="https://reuters.com/world/ceasefire-declared">');
  });

  it("omits the summary paragraph when summary is absent from the cluster", () => {
    const html = renderItemListHtml({
      zone: "world",
      served_zone: "world",
      generated_at: "2026-08-12T06:14:00Z",
      clusters: [{ cluster_id: "b", independent_source_count: 3, country_count: 2 }],
    });

    expect(html).not.toContain("<p class=\"summary\">");
    expect(html).toContain('<span class="num">3</span> sources indépendantes');
  });

  it("omits the attribution span when outbound_source is missing despite a valid url", () => {
    const html = renderItemListHtml({
      zone: "world",
      served_zone: "world",
      generated_at: "2026-08-12T06:14:00Z",
      clusters: [
        {
          cluster_id: "c",
          independent_source_count: 4,
          country_count: 3,
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
          outbound_url: "https://example.com/a",
          outbound_source: "<b>Evil</b>",
        },
      ],
    });

    expect(html).not.toContain("<script>alert(1)</script>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<b>Evil</b>");
  });

  it("renders one item per cluster, in order, for multiple clusters", () => {
    const html = renderItemListHtml({
      zone: "world",
      served_zone: "world",
      generated_at: "2026-08-12T06:14:00Z",
      clusters: [
        { cluster_id: "e", independent_source_count: 1, country_count: 1 },
        { cluster_id: "f", independent_source_count: 2, country_count: 2 },
      ],
    });

    const itemCount = (html.match(/<div class="item">/g) ?? []).length;
    expect(itemCount).toBe(2);
    expect(html.indexOf('<span class="num">1</span>')).toBeLessThan(
      html.indexOf('<span class="num">2</span>')
    );
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
    // @ts-expect-error -- minimal stand-in, see createFakeAnchor's docstring
    globalThis.document = {
      querySelector: (selector: string) =>
        selector.includes("zone") ? zoneAnchor : periodAnchor,
    };

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
