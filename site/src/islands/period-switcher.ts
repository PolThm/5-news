// Story 4.2's client-side progressive enhancement: intercepts a click on
// the Period mad-libs word, fetches the target Briefing's JSON directly
// (EXPERIENCE.md: "no network round-trip beyond fetching that one file"
// -- not an HTML page fetch-and-swap), re-renders the sentence + item
// list in place, and updates the URL via history.pushState.
//
// The only client JS in this codebase (architecture spine, Structural
// Seed: "the mad-libs selector — the only client JS"). No framework --
// none is installed, and this is a small enough interaction that adding
// one specifically to share render logic with the server-side Astro
// component would be a disproportionate scope increase. This module's
// `renderBriefing`/`buildUrl` functions intentionally mirror
// BriefingPage.astro's structure closely, not by import (Astro
// components don't run in the browser) but by hand -- see this story's
// Dev Notes for why that duplication is accepted, not fixed.
//
// Exported pure functions are unit-testable in isolation (jsdom-free);
// `attach()` is the only piece that touches the real DOM/network and is
// exercised by this story's Playwright suite instead.

export interface ClusterLike {
  cluster_id: string;
  summary?: string;
  independent_source_count: number;
  country_count: number;
  outbound_url?: string | null;
  outbound_source?: string | null;
}

export interface BriefingLike {
  clusters: ClusterLike[];
  generated_at: string;
}

const PERIOD_CYCLE = ["day", "week", "month"] as const;
export type PeriodSlug = (typeof PERIOD_CYCLE)[number];

const PERIOD_SENTENCE_TEXT: Record<PeriodSlug, string> = {
  day: "aujourd'hui",
  week: "cette semaine",
  month: "ce mois",
};

// Mirrors briefing.ts's own nextPeriod/periodSentenceText exactly -- see
// this file's module docstring for why this is a hand-kept mirror, not an
// import (Astro/Node-side lib code is not bundled for the browser here).
export function nextPeriod(current: PeriodSlug): PeriodSlug {
  const index = PERIOD_CYCLE.indexOf(current);
  return PERIOD_CYCLE[(index + 1) % PERIOD_CYCLE.length];
}

export function periodSentenceText(period: PeriodSlug): string {
  return PERIOD_SENTENCE_TEXT[period];
}

export function briefingJsonUrl(lang: string, zone: string, period: PeriodSlug): string {
  return `/briefings/${lang}/${zone}/${period}.json`;
}

export function pageUrl(lang: string, zone: string, period: PeriodSlug): string {
  return `/${lang}/${zone}/${period}`;
}

const HTML_ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => HTML_ESCAPES[char]);
}

function hasValidAttribution(cluster: ClusterLike): cluster is ClusterLike & {
  outbound_url: string;
  outbound_source: string;
} {
  return (
    !!cluster.outbound_url && !!cluster.outbound_source && /^https?:\/\//i.test(cluster.outbound_url)
  );
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  const hours = String(date.getUTCHours()).padStart(2, "0");
  const minutes = String(date.getUTCMinutes()).padStart(2, "0");
  return `Mis à jour à ${hours}:${minutes} UTC`;
}

/**
 * Builds the item-list HTML for a fetched Briefing -- a hand-kept mirror
 * of BriefingPage.astro's `.item` markup. Returns an HTML string (not DOM
 * nodes) so callers can assign it via `innerHTML` in one step, matching
 * how small vanilla-JS DOM updates are conventionally done without a
 * templating library.
 */
export function renderItemListHtml(briefing: BriefingLike): string {
  return briefing.clusters
    .map((cluster) => {
      const summaryHtml = cluster.summary
        ? `<p class="summary">${escapeHtml(cluster.summary)}</p>`
        : "";
      const attributionHtml = hasValidAttribution(cluster)
        ? `<span class="attribution">Rapporté par <em>${escapeHtml(cluster.outbound_source)}</em> — <a href="${escapeHtml(cluster.outbound_url)}">lire l'article original →</a></span>`
        : "";
      return (
        `<div class="item">${summaryHtml}` +
        `<span class="chip"><span class="num">${cluster.independent_source_count}</span> sources indépendantes · ` +
        `<span class="num">${cluster.country_count}</span> pays</span>${attributionHtml}</div>`
      );
    })
    .join("");
}

const ATTACHED_MARKER = "data-period-switcher-attached";

/**
 * Attaches the click-to-swap behavior to the Period mad-libs word currently
 * in the document. Called once on initial load and again after every
 * successful swap -- the swap mutates the existing anchor in place rather
 * than replacing it, so re-calling this is normally a no-op, but the
 * ATTACHED_MARKER guard keeps it safe (no duplicate listeners, no
 * multiply-firing clicks) even if a future markup change ever does replace
 * the node outright.
 */
export function attach(): void {
  const link = document.querySelector<HTMLAnchorElement>("[data-period-word]");
  if (!link || link.hasAttribute(ATTACHED_MARKER)) return;

  link.setAttribute(ATTACHED_MARKER, "");
  link.addEventListener("click", (event) => {
    event.preventDefault();
    void handleClick(link);
  });
}

async function handleClick(link: HTMLAnchorElement): Promise<void> {
  const lang = link.dataset.lang;
  const zone = link.dataset.zone;
  const period = link.dataset.period as PeriodSlug | undefined;
  if (!lang || !zone || !period) {
    window.location.href = link.href;
    return;
  }

  const target = nextPeriod(period);
  const jsonUrl = briefingJsonUrl(lang, zone, target);

  try {
    const response = await fetch(jsonUrl);
    if (!response.ok) throw new Error(`unexpected status ${response.status}`);
    const briefing = (await response.json()) as BriefingLike;

    const sentence = document.getElementById("mad-libs-sentence");
    const itemList = document.getElementById("item-list");
    const timestamp = document.getElementById("timestamp");
    if (!sentence || !itemList || !timestamp) {
      window.location.href = pageUrl(lang, zone, target);
      return;
    }

    link.textContent = periodSentenceText(target);
    link.href = pageUrl(lang, zone, nextPeriod(target));
    link.dataset.period = target;
    itemList.innerHTML = renderItemListHtml(briefing);
    timestamp.textContent = formatTimestamp(briefing.generated_at);

    window.history.pushState({}, "", pageUrl(lang, zone, target));
    attach();
  } catch {
    // Degrade to a real navigation rather than leaving the reader on a
    // half-updated page (AD-10's "degrade, don't break" applied to the
    // reader's own path) -- a network hiccup or unexpected 404 must not
    // silently fail into a dead click.
    window.location.href = pageUrl(lang, zone, target);
  }
}

if (typeof document !== "undefined") {
  attach();
}
