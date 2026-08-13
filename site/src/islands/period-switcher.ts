// Story 4.2's client-side progressive enhancement, extended by Story 4.3
// to also handle the Zone mad-libs word: intercepts a click on either
// mad-libs word, fetches the target Briefing's JSON directly
// (EXPERIENCE.md: "no network round-trip beyond fetching that one file"
// -- not an HTML page fetch-and-swap), re-renders the sentence + fallback
// notice + item list in place, and updates the URL via history.pushState.
//
// The only client JS in this codebase (architecture spine, Structural
// Seed: "the mad-libs selector — the only client JS"). No framework --
// none is installed, and this is a small enough interaction that adding
// one specifically to share render logic with the server-side Astro
// component would be a disproportionate scope increase. This module's
// render functions intentionally mirror BriefingPage.astro's structure
// closely, not by import (Astro components don't run in the browser) but
// by hand -- see the story Dev Notes for why that duplication is accepted,
// not fixed.
//
// Exported pure functions are unit-testable in isolation (jsdom-free);
// `attach()`/`handleClick()` are the only pieces that touch the real
// DOM/network, exercised by manual verification per Story 4.2/4.3's own
// Playwright-deferral decision (see those stories' Dev Notes).

export interface ClusterMemberLike {
  source: string;
  source_country: string;
}

export interface ClusterLike {
  cluster_id: string;
  summary?: string;
  independent_source_count: number;
  country_count: number;
  members: ClusterMemberLike[];
  outbound_url?: string | null;
  outbound_source?: string | null;
}

export interface BriefingLike {
  zone: string;
  served_zone: string;
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

// Mirrors briefing.ts's ZONE_CYCLE/nextZone/zoneSentenceLabel exactly, for
// the same reason as the Period mirror above.
const ZONE_CYCLE = [
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
] as const;
export type ZoneSlug = (typeof ZONE_CYCLE)[number];

const ZONE_SENTENCE_LABEL: Record<ZoneSlug, string> = {
  world: "dans le Monde",
  europe: "en Europe",
  "north-america": "en Amérique du Nord",
  "south-america": "en Amérique du Sud",
  asia: "en Asie",
  africa: "en Afrique",
  oceania: "en Océanie",
  france: "en France",
  "united-kingdom": "au Royaume-Uni",
  germany: "en Allemagne",
  "united-states": "aux États-Unis",
  japan: "au Japon",
  china: "en Chine",
  india: "en Inde",
  brazil: "au Brésil",
};

const ZONE_SERVED_LABEL: Partial<Record<ZoneSlug, string>> = {
  europe: "l'Europe",
  "north-america": "l'Amérique du Nord",
  "south-america": "l'Amérique du Sud",
  asia: "l'Asie",
  africa: "l'Afrique",
  oceania: "l'Océanie",
};

const ZONE_REQUESTED_LABEL: Partial<Record<ZoneSlug, { label: string; plural: boolean }>> = {
  france: { label: "la France", plural: false },
  "united-kingdom": { label: "le Royaume-Uni", plural: false },
  germany: { label: "l'Allemagne", plural: false },
  "united-states": { label: "les États-Unis", plural: true },
  japan: { label: "le Japon", plural: false },
  china: { label: "la Chine", plural: false },
  india: { label: "l'Inde", plural: false },
  brazil: { label: "le Brésil", plural: false },
};

export function nextZone(current: ZoneSlug): ZoneSlug {
  const index = ZONE_CYCLE.indexOf(current);
  return ZONE_CYCLE[(index + 1) % ZONE_CYCLE.length];
}

export function zoneSentenceLabel(zone: ZoneSlug): string {
  return ZONE_SENTENCE_LABEL[zone];
}

export function isZoneFallback(briefing: Pick<BriefingLike, "zone" | "served_zone">): boolean {
  return briefing.served_zone !== briefing.zone;
}

/**
 * Mirrors briefing.ts's fallbackNoticeText exactly -- see that function's
 * own docstring for the grammar rules (article agreement, verb-number
 * agreement for "les États-Unis").
 */
export function fallbackNoticeText(
  briefing: Pick<BriefingLike, "zone" | "served_zone">
): string | null {
  if (!isZoneFallback(briefing)) return null;

  const servedLabel = ZONE_SERVED_LABEL[briefing.served_zone as ZoneSlug];
  const requested = ZONE_REQUESTED_LABEL[briefing.zone as ZoneSlug];
  if (!servedLabel || !requested) return null;

  const verb = requested.plural ? "n'ont" : "n'a";
  return `Affichage de ${servedLabel} — ${requested.label} ${verb} pas assez de couverture aujourd'hui.`;
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

// Mirrors briefing.ts's own countryLabel exactly, for the same reason as
// the other hand-kept mirrors in this file.
const COUNTRY_LABEL: Partial<Record<string, string>> = {
  france: "France",
  "united-kingdom": "Royaume-Uni",
  germany: "Allemagne",
  "united-states": "États-Unis",
  japan: "Japon",
  china: "Chine",
  india: "Inde",
  brazil: "Brésil",
};

function countryLabel(countrySlug: string): string {
  return COUNTRY_LABEL[countrySlug] ?? countrySlug;
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
 * Builds the fallback-notice HTML for a fetched Briefing -- a hand-kept
 * mirror of BriefingPage.astro's conditional `#fallback-notice` div. Empty
 * string (not just falsy) when no fallback is active, since callers assign
 * this directly to `innerHTML`.
 */
export function renderFallbackNoticeHtml(briefing: BriefingLike): string {
  const text = fallbackNoticeText(briefing);
  return text ? `<div class="fallback-notice" id="fallback-notice">${escapeHtml(text)}</div>` : "";
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
      const sourceListId = `source-list-${escapeHtml(cluster.cluster_id)}`;
      const membersHtml = cluster.members
        .map(
          (member) =>
            `<li>${escapeHtml(member.source)} (${escapeHtml(countryLabel(member.source_country))})</li>`
        )
        .join("");
      return (
        `<div class="item">${summaryHtml}` +
        `<button type="button" class="chip" aria-expanded="false" aria-controls="${sourceListId}" data-consensus-chip>` +
        `<span class="num">${cluster.independent_source_count}</span> sources indépendantes · ` +
        `<span class="num">${cluster.country_count}</span> pays` +
        `<span class="chevron" aria-hidden="true">▾</span></button>` +
        `<div class="source-list js-collapsed" id="${sourceListId}">Sources et pays contributeurs :<ul>${membersHtml}</ul></div>` +
        `${attributionHtml}</div>`
      );
    })
    .join("");
}

const ATTACHED_MARKER = "data-mad-libs-attached";

/**
 * Attaches the click-to-swap behavior to both mad-libs words (Zone and
 * Period) currently in the document. Called once on initial load and again
 * after every successful swap -- the swap mutates the existing anchor in
 * place rather than replacing it, so re-calling this is normally a no-op,
 * but the ATTACHED_MARKER guard keeps it safe (no duplicate listeners, no
 * multiply-firing clicks -- the exact bug Story 4.2's own adversarial
 * review caught and fixed) even if a future markup change ever does
 * replace a node outright.
 */
export function attach(): void {
  attachWord("[data-zone-word]", "zone");
  attachWord("[data-period-word]", "period");
  attachChips();
}

function attachWord(selector: string, axis: "zone" | "period"): void {
  const link = document.querySelector<HTMLAnchorElement>(selector);
  if (!link || link.hasAttribute(ATTACHED_MARKER)) return;

  link.setAttribute(ATTACHED_MARKER, "");
  link.addEventListener("click", (event) => {
    event.preventDefault();
    void handleClick(link, axis);
  });
}

const CHIP_ATTACHED_MARKER = "data-chip-attached";

/**
 * Attaches the expand/collapse toggle to every Consensus chip currently in
 * the document, and -- ONLY for chips not yet attached -- collapses their
 * source list (EXPERIENCE.md's Cold Load pattern requires the source list
 * present-and-visible in the initial server-rendered HTML for a no-JS
 * reader; only *collapsing* it is a JS-present enhancement, done here on
 * first attach). Called once on initial load and again after every
 * Zone/Period swap, since `handleClick`'s wholesale `#item-list`
 * replacement destroys the previous chips' listeners entirely (unlike the
 * mad-libs words, which are mutated in place) -- every freshly-rendered
 * chip starts collapsed, matching `renderItemListHtml`'s own
 * `js-collapsed`-by-default output.
 *
 * The collapse step is gated behind the SAME `CHIP_ATTACHED_MARKER` guard
 * as the listener attachment, not run unconditionally on every call --
 * an adversarial review caught that an earlier version collapsed every
 * chip's source list on every call regardless of prior state, which would
 * force-collapse a reader's already-expanded chip (leaving `aria-expanded`
 * desynced from the hidden content) the next time this function ran for
 * any reason. Not exploitable today only because every current call site
 * runs immediately after a full `#item-list` DOM replacement, so no
 * previously-expanded node survives to be affected -- but a future call
 * site without that property would silently reintroduce the bug, so the
 * guard is real, not decorative.
 */
export function attachChips(): void {
  const chips = document.querySelectorAll<HTMLButtonElement>("[data-consensus-chip]");
  for (const chip of chips) {
    if (chip.hasAttribute(CHIP_ATTACHED_MARKER)) continue;
    chip.setAttribute(CHIP_ATTACHED_MARKER, "");

    const sourceList = document.getElementById(chip.getAttribute("aria-controls") ?? "");
    if (sourceList) sourceList.classList.add("js-collapsed");

    chip.addEventListener("click", () => toggleChip(chip));
  }
}

function toggleChip(chip: HTMLButtonElement): void {
  const sourceList = document.getElementById(chip.getAttribute("aria-controls") ?? "");
  if (!sourceList) return;

  const expanded = chip.getAttribute("aria-expanded") === "true";
  chip.setAttribute("aria-expanded", expanded ? "false" : "true");
  sourceList.classList.toggle("js-collapsed", expanded);
}

async function handleClick(link: HTMLAnchorElement, axis: "zone" | "period"): Promise<void> {
  const lang = link.dataset.lang;
  const zone = link.dataset.zone as ZoneSlug | undefined;
  const period = link.dataset.period as PeriodSlug | undefined;
  if (!lang || !zone || !period) {
    window.location.href = link.href;
    return;
  }

  const targetZone = axis === "zone" ? nextZone(zone) : zone;
  const targetPeriod = axis === "period" ? nextPeriod(period) : period;
  const jsonUrl = briefingJsonUrl(lang, targetZone, targetPeriod);

  try {
    const response = await fetch(jsonUrl);
    if (!response.ok) throw new Error(`unexpected status ${response.status}`);
    const briefing = (await response.json()) as BriefingLike;

    const sentence = document.getElementById("mad-libs-sentence");
    const itemList = document.getElementById("item-list");
    const timestamp = document.getElementById("timestamp");
    const sentenceBlock = document.getElementById("sentence-block");
    if (!sentence || !itemList || !timestamp || !sentenceBlock) {
      window.location.href = pageUrl(lang, targetZone, targetPeriod);
      return;
    }

    const zoneLink = sentence.querySelector<HTMLAnchorElement>("[data-zone-word]");
    const periodLink = sentence.querySelector<HTMLAnchorElement>("[data-period-word]");
    for (const wordLink of [zoneLink, periodLink]) {
      if (!wordLink) continue;
      wordLink.dataset.zone = targetZone;
      wordLink.dataset.period = targetPeriod;
    }
    if (zoneLink) {
      zoneLink.textContent = zoneSentenceLabel(targetZone);
      zoneLink.href = pageUrl(lang, nextZone(targetZone), targetPeriod);
    }
    if (periodLink) {
      periodLink.textContent = periodSentenceText(targetPeriod);
      periodLink.href = pageUrl(lang, targetZone, nextPeriod(targetPeriod));
    }

    const existingNotice = document.getElementById("fallback-notice");
    existingNotice?.remove();
    const noticeHtml = renderFallbackNoticeHtml(briefing);
    if (noticeHtml) sentence.insertAdjacentHTML("afterend", noticeHtml);

    itemList.innerHTML = renderItemListHtml(briefing);
    timestamp.textContent = formatTimestamp(briefing.generated_at);

    window.history.pushState({}, "", pageUrl(lang, targetZone, targetPeriod));
    attach();
  } catch {
    // Degrade to a real navigation rather than leaving the reader on a
    // half-updated page (AD-10's "degrade, don't break" applied to the
    // reader's own path) -- a network hiccup or unexpected 404 must not
    // silently fail into a dead click.
    window.location.href = pageUrl(lang, targetZone, targetPeriod);
  }
}

if (typeof document !== "undefined") {
  attach();
}
