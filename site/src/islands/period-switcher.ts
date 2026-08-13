// Story 4.2's client-side progressive enhancement, extended by Story 4.3
// to also handle the Zone mad-libs word, by Story 4.5 for the Consensus
// chip's expand/collapse, and by Story 4.7 for the Output Language
// control: intercepts a click on any mad-libs word or language option,
// fetches the target Briefing's JSON directly (EXPERIENCE.md: "no network
// round-trip beyond fetching that one file" -- not an HTML page
// fetch-and-swap), re-renders the sentence + fallback notice + item list +
// language control in place, and updates the URL via history.pushState.
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
  discarded_ingested: number;
  discarded_kept: number;
  generated_at: string;
}

const PERIOD_CYCLE = ["day", "week", "month"] as const;
export type PeriodSlug = (typeof PERIOD_CYCLE)[number];

const LANGUAGE_CYCLE = ["fr", "en", "es"] as const;
export type LanguageSlug = (typeof LANGUAGE_CYCLE)[number];

// Mirrors briefing.ts's own PERIOD_SENTENCE_TEXT/periodSentenceText
// exactly -- see this file's module docstring for why this is a
// hand-kept mirror, not an import (Astro/Node-side lib code is not
// bundled for the browser here).
const PERIOD_SENTENCE_TEXT: Record<LanguageSlug, Record<PeriodSlug, string>> = {
  fr: { day: "aujourd'hui", week: "cette semaine", month: "ce mois" },
  en: { day: "today", week: "this week", month: "this month" },
  es: { day: "hoy", week: "esta semana", month: "este mes" },
};

export function nextPeriod(current: PeriodSlug): PeriodSlug {
  const index = PERIOD_CYCLE.indexOf(current);
  return PERIOD_CYCLE[(index + 1) % PERIOD_CYCLE.length];
}

export function periodSentenceText(period: PeriodSlug, lang: LanguageSlug): string {
  return PERIOD_SENTENCE_TEXT[lang][period];
}

export function nextLanguage(current: LanguageSlug): LanguageSlug {
  const index = LANGUAGE_CYCLE.indexOf(current);
  return LANGUAGE_CYCLE[(index + 1) % LANGUAGE_CYCLE.length];
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

const ZONE_SENTENCE_LABEL: Record<LanguageSlug, Partial<Record<string, string>>> = {
  fr: {
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
  },
  en: {
    world: "in the World",
    europe: "in Europe",
    "north-america": "in North America",
    "south-america": "in South America",
    asia: "in Asia",
    africa: "in Africa",
    oceania: "in Oceania",
    france: "in France",
    "united-kingdom": "in the United Kingdom",
    germany: "in Germany",
    "united-states": "in the United States",
    japan: "in Japan",
    china: "in China",
    india: "in India",
    brazil: "in Brazil",
  },
  es: {
    world: "en el Mundo",
    europe: "en Europa",
    "north-america": "en América del Norte",
    "south-america": "en América del Sur",
    asia: "en Asia",
    africa: "en África",
    oceania: "en Oceanía",
    france: "en Francia",
    "united-kingdom": "en el Reino Unido",
    germany: "en Alemania",
    "united-states": "en Estados Unidos",
    japan: "en Japón",
    china: "en China",
    india: "en India",
    brazil: "en Brasil",
  },
};

const ZONE_SERVED_LABEL: Record<LanguageSlug, Partial<Record<ZoneSlug, string>>> = {
  fr: {
    europe: "l'Europe",
    "north-america": "l'Amérique du Nord",
    "south-america": "l'Amérique du Sud",
    asia: "l'Asie",
    africa: "l'Afrique",
    oceania: "l'Océanie",
  },
  en: {
    europe: "Europe",
    "north-america": "North America",
    "south-america": "South America",
    asia: "Asia",
    africa: "Africa",
    oceania: "Oceania",
  },
  es: {
    europe: "Europa",
    "north-america": "América del Norte",
    "south-america": "América del Sur",
    asia: "Asia",
    africa: "África",
    oceania: "Oceanía",
  },
};

interface RequestedLabel {
  label: string;
  plural: boolean;
}

const ZONE_REQUESTED_LABEL: Record<LanguageSlug, Partial<Record<ZoneSlug, RequestedLabel>>> = {
  fr: {
    france: { label: "la France", plural: false },
    "united-kingdom": { label: "le Royaume-Uni", plural: false },
    germany: { label: "l'Allemagne", plural: false },
    "united-states": { label: "les États-Unis", plural: true },
    japan: { label: "le Japon", plural: false },
    china: { label: "la Chine", plural: false },
    india: { label: "l'Inde", plural: false },
    brazil: { label: "le Brésil", plural: false },
  },
  en: {
    france: { label: "France", plural: false },
    "united-kingdom": { label: "the United Kingdom", plural: false },
    germany: { label: "Germany", plural: false },
    "united-states": { label: "the United States", plural: true },
    japan: { label: "Japan", plural: false },
    china: { label: "China", plural: false },
    india: { label: "India", plural: false },
    brazil: { label: "Brazil", plural: false },
  },
  es: {
    france: { label: "Francia", plural: false },
    "united-kingdom": { label: "el Reino Unido", plural: false },
    germany: { label: "Alemania", plural: false },
    "united-states": { label: "Estados Unidos", plural: true },
    japan: { label: "Japón", plural: false },
    china: { label: "China", plural: false },
    india: { label: "India", plural: false },
    brazil: { label: "Brasil", plural: false },
  },
};

export function nextZone(current: ZoneSlug): ZoneSlug {
  const index = ZONE_CYCLE.indexOf(current);
  return ZONE_CYCLE[(index + 1) % ZONE_CYCLE.length];
}

export function zoneSentenceLabel(zone: string, lang: LanguageSlug): string {
  // Defensive fallback for a zone slug outside the known 15 (a malformed
  // data-zone attribute, or malformed fetched JSON) -- returns the raw
  // slug rather than "undefined", mirroring briefing.ts's own
  // zoneSentenceLabel exactly.
  return ZONE_SENTENCE_LABEL[lang][zone] ?? zone;
}

export function isZoneFallback(briefing: Pick<BriefingLike, "zone" | "served_zone">): boolean {
  return briefing.served_zone !== briefing.zone;
}

/**
 * Mirrors briefing.ts's fallbackNoticeText exactly -- see that function's
 * own docstring for the grammar rules (article agreement, verb-number
 * agreement for "les États-Unis"/"the United States"/"Estados Unidos").
 */
export function fallbackNoticeText(
  briefing: Pick<BriefingLike, "zone" | "served_zone">,
  lang: LanguageSlug
): string | null {
  if (!isZoneFallback(briefing)) return null;

  const servedLabel = ZONE_SERVED_LABEL[lang][briefing.served_zone as ZoneSlug];
  const requested = ZONE_REQUESTED_LABEL[lang][briefing.zone as ZoneSlug];
  if (!servedLabel || !requested) return null;

  switch (lang) {
    case "fr": {
      const verb = requested.plural ? "n'ont" : "n'a";
      return `Affichage de ${servedLabel} — ${requested.label} ${verb} pas assez de couverture aujourd'hui.`;
    }
    case "en": {
      const verb = requested.plural ? "don't" : "doesn't";
      return `Showing ${servedLabel} — ${requested.label} ${verb} have enough coverage today.`;
    }
    case "es": {
      const verb = requested.plural ? "tienen" : "tiene";
      return `Mostrando ${servedLabel} — ${requested.label} no ${verb} suficiente cobertura hoy.`;
    }
  }
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
const COUNTRY_LABEL: Record<LanguageSlug, Partial<Record<string, string>>> = {
  fr: {
    france: "France",
    "united-kingdom": "Royaume-Uni",
    germany: "Allemagne",
    "united-states": "États-Unis",
    japan: "Japon",
    china: "Chine",
    india: "Inde",
    brazil: "Brésil",
  },
  en: {
    france: "France",
    "united-kingdom": "United Kingdom",
    germany: "Germany",
    "united-states": "United States",
    japan: "Japan",
    china: "China",
    india: "India",
    brazil: "Brazil",
  },
  es: {
    france: "Francia",
    "united-kingdom": "Reino Unido",
    germany: "Alemania",
    "united-states": "Estados Unidos",
    japan: "Japón",
    china: "China",
    india: "India",
    brazil: "Brasil",
  },
};

function countryLabel(countrySlug: string, lang: LanguageSlug): string {
  return COUNTRY_LABEL[lang][countrySlug] ?? countrySlug;
}

function hasValidAttribution(cluster: ClusterLike): cluster is ClusterLike & {
  outbound_url: string;
  outbound_source: string;
} {
  return (
    !!cluster.outbound_url && !!cluster.outbound_source && /^https?:\/\//i.test(cluster.outbound_url)
  );
}

const TIMESTAMP_PREFIX: Record<LanguageSlug, string> = {
  fr: "Mis à jour à",
  en: "Updated at",
  es: "Actualizado a las",
};

function formatTimestamp(iso: string, lang: LanguageSlug): string {
  const date = new Date(iso);
  const hours = String(date.getUTCHours()).padStart(2, "0");
  const minutes = String(date.getUTCMinutes()).padStart(2, "0");
  return `${TIMESTAMP_PREFIX[lang]} ${hours}:${minutes} UTC`;
}

const CONSENSUS_CHIP_TEXT: Record<LanguageSlug, { sources: string; countries: string }> = {
  fr: { sources: "sources indépendantes", countries: "pays" },
  en: { sources: "independent sources", countries: "countries" },
  es: { sources: "fuentes independientes", countries: "países" },
};

const SOURCE_LIST_INTRO: Record<LanguageSlug, string> = {
  fr: "Sources et pays contributeurs :",
  en: "Contributing sources and countries:",
  es: "Fuentes y países contribuyentes:",
};

const ATTRIBUTION_TEXT: Record<LanguageSlug, { reportedBy: string; readOriginal: string }> = {
  fr: { reportedBy: "Rapporté par", readOriginal: "lire l'article original →" },
  en: { reportedBy: "Reported by", readOriginal: "read the original article →" },
  es: { reportedBy: "Informado por", readOriginal: "leer el artículo original →" },
};

const DISCARDED_VOLUME_TEXT: Record<LanguageSlug, { reviewed: string; kept: string }> = {
  fr: { reviewed: "articles examinés", kept: "conservés." },
  en: { reviewed: "articles reviewed", kept: "kept." },
  es: { reviewed: "artículos examinados", kept: "conservados." },
};

const LOCALE_BY_LANGUAGE: Record<LanguageSlug, string> = {
  fr: "fr-FR",
  en: "en-US",
  es: "es-MX",
};

function formatCount(n: number, lang: LanguageSlug): string {
  // n.toLocaleString("fr-FR") produces a narrow no-break space (U+202F)
  // as its thousands separator; normalize to a plain space for
  // consistent, readable HTML output (mirrors briefing.ts's formatCount).
  return n.toLocaleString(LOCALE_BY_LANGUAGE[lang]).replace(/ /g, " ");
}

const MAD_LIBS_LEAD_IN: Record<LanguageSlug, string> = {
  fr: "Voici ce qui se passe",
  en: "Here's what's happening",
  es: "Esto es lo que está pasando",
};

const NOUN_SINGULAR_PLURAL: Record<LanguageSlug, { singular: string; plural: string }> = {
  fr: { singular: "sujet", plural: "sujets" },
  en: { singular: "story", plural: "stories" },
  es: { singular: "tema", plural: "temas" },
};

/**
 * Mirrors briefing.ts's own endScreenText exactly -- see that function's
 * own docstring for the singular/plural agreement rationale.
 */
function endScreenText(itemCount: number, period: PeriodSlug, lang: LanguageSlug): string | null {
  if (itemCount === 0) return null;

  const periodText = periodSentenceText(period, lang);
  const noun = itemCount === 1 ? NOUN_SINGULAR_PLURAL[lang].singular : NOUN_SINGULAR_PLURAL[lang].plural;
  switch (lang) {
    case "fr": {
      const verb = itemCount === 1 ? "a" : "ont";
      return `Vous avez atteint la fin. ${itemCount} ${noun} ${verb} atteint le seuil ${periodText}.`;
    }
    case "en":
      return `You've reached the end. ${itemCount} ${noun} met the threshold ${periodText}.`;
    case "es": {
      const verb = itemCount === 1 ? "alcanzó" : "alcanzaron";
      return `Has llegado al final. ${itemCount} ${noun} ${verb} el umbral ${periodText}.`;
    }
  }
}

/**
 * Builds the fallback-notice HTML for a fetched Briefing -- a hand-kept
 * mirror of BriefingPage.astro's conditional `#fallback-notice` div. Empty
 * string (not just falsy) when no fallback is active, since callers assign
 * this directly to `innerHTML`.
 */
export function renderFallbackNoticeHtml(briefing: BriefingLike, lang: LanguageSlug): string {
  const text = fallbackNoticeText(briefing, lang);
  return text ? `<div class="fallback-notice" id="fallback-notice">${escapeHtml(text)}</div>` : "";
}

/**
 * Builds the item-list HTML for a fetched Briefing -- a hand-kept mirror
 * of BriefingPage.astro's `.item` markup. Returns an HTML string (not DOM
 * nodes) so callers can assign it via `innerHTML` in one step, matching
 * how small vanilla-JS DOM updates are conventionally done without a
 * templating library.
 */
export function renderItemListHtml(briefing: BriefingLike, lang: LanguageSlug): string {
  const chipText = CONSENSUS_CHIP_TEXT[lang];
  const attribution = ATTRIBUTION_TEXT[lang];
  const intro = SOURCE_LIST_INTRO[lang];

  return briefing.clusters
    .map((cluster) => {
      const summaryHtml = cluster.summary
        ? `<p class="summary">${escapeHtml(cluster.summary)}</p>`
        : "";
      const attributionHtml = hasValidAttribution(cluster)
        ? `<span class="attribution">${escapeHtml(attribution.reportedBy)} <em>${escapeHtml(cluster.outbound_source)}</em> — <a href="${escapeHtml(cluster.outbound_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(attribution.readOriginal)}</a></span>`
        : "";
      const sourceListId = `source-list-${escapeHtml(cluster.cluster_id)}`;
      const membersHtml = cluster.members
        .map(
          (member) =>
            `<li>${escapeHtml(member.source)} (${escapeHtml(countryLabel(member.source_country, lang))})</li>`
        )
        .join("");
      return (
        `<div class="item">${summaryHtml}` +
        `<button type="button" class="chip" aria-expanded="false" aria-controls="${sourceListId}" data-consensus-chip>` +
        `<span class="num">${cluster.independent_source_count}</span> ${escapeHtml(chipText.sources)} · ` +
        `<span class="num">${cluster.country_count}</span> ${escapeHtml(chipText.countries)}` +
        `<span class="chevron" aria-hidden="true">▾</span></button>` +
        `<div class="source-list js-collapsed" id="${sourceListId}">${escapeHtml(intro)}<ul>${membersHtml}</ul></div>` +
        `${attributionHtml}</div>`
      );
    })
    .join("");
}

/**
 * Builds the Discarded Volume line's HTML for a fetched Briefing -- a
 * hand-kept mirror of BriefingPage.astro's `#discarded` div. Renders
 * unconditionally (FR-8 -- never suppressed, unlike the End Screen).
 */
export function renderDiscardedVolumeHtml(briefing: BriefingLike, lang: LanguageSlug): string {
  const text = DISCARDED_VOLUME_TEXT[lang];
  return (
    `<span class="num">${formatCount(briefing.discarded_ingested, lang)}</span> ${escapeHtml(text.reviewed)} ` +
    `→ <span class="num">${formatCount(briefing.discarded_kept, lang)}</span> ${escapeHtml(text.kept)}`
  );
}

/**
 * Builds the End Screen's HTML for a fetched Briefing -- a hand-kept
 * mirror of BriefingPage.astro's conditional `#end-screen` div. Empty
 * string (not just falsy) for 0 items, matching endScreenText's own null
 * return for that case.
 */
export function renderEndScreenHtml(
  itemCount: number,
  period: PeriodSlug,
  lang: LanguageSlug
): string {
  const text = endScreenText(itemCount, period, lang);
  return text
    ? `<div class="end-screen" id="end-screen"><div class="rule"></div><p>${escapeHtml(text)}</p></div>`
    : "";
}

const ATTACHED_MARKER = "data-mad-libs-attached";

/**
 * Attaches the click-to-swap behavior to both mad-libs words (Zone and
 * Period) and every Output Language option currently in the document.
 * Called once on initial load and again after every successful swap -- the
 * mad-libs words are mutated in place rather than replaced, so re-calling
 * this is normally a no-op, but the ATTACHED_MARKER guard keeps it safe
 * (no duplicate listeners, no multiply-firing clicks -- the exact bug
 * Story 4.2's own adversarial review caught and fixed) even if a future
 * markup change ever does replace a node outright.
 */
export function attach(): void {
  attachWord("[data-zone-word]", "zone");
  attachWord("[data-period-word]", "period");
  attachLanguageWords();
  attachChips();
}

function attachWord(selector: string, axis: "zone" | "period"): void {
  const link = document.querySelector<HTMLAnchorElement>(selector);
  if (!link || link.hasAttribute(ATTACHED_MARKER)) return;

  link.setAttribute(ATTACHED_MARKER, "");
  link.addEventListener("click", (event) => {
    event.preventDefault();
    void handleClick(link, { axis: axis });
  });
}

const LANGUAGE_ATTACHED_MARKER = "data-lang-attached";

/**
 * Attaches the click-to-switch behavior to every Output Language option
 * currently in the document -- a fundamentally different shape from
 * attachWord's single-node cycle-by-one pattern (see this story's own Dev
 * Notes): 3 separate elements, each with its own explicit target language
 * rather than a "next value" to compute, and clicking the already-active
 * language must be a no-op (Zone/Period never have this case, since every
 * click always advances to a genuinely different value). Uses the same
 * per-element idempotency-guard pattern as attachChips, scoped to its own
 * marker.
 */
function attachLanguageWords(): void {
  const links = document.querySelectorAll<HTMLAnchorElement>("[data-lang-word]");
  for (const link of links) {
    if (link.hasAttribute(LANGUAGE_ATTACHED_MARKER)) continue;
    link.setAttribute(LANGUAGE_ATTACHED_MARKER, "");

    link.addEventListener("click", (event) => {
      const targetLang = link.dataset.targetLang as LanguageSlug | undefined;
      const currentLang = link.dataset.lang;
      if (!targetLang || targetLang === currentLang) {
        // Clicking the already-active language is a no-op -- deliberately
        // NOT calling preventDefault(), so the click falls through to the
        // real <a href> (which points at this exact same page): a normal,
        // harmless navigation to where the reader already is, rather than
        // a click that visibly does nothing. A missing/malformed
        // data-target-lang degrades the same way.
        return;
      }
      event.preventDefault();
      void handleClick(link, { axis: "lang", targetLang });
    });
  }
}

const CHIP_ATTACHED_MARKER = "data-chip-attached";

/**
 * Attaches the expand/collapse toggle to every Consensus chip currently in
 * the document, and -- ONLY for chips not yet attached -- collapses their
 * source list (EXPERIENCE.md's Cold Load pattern requires the source list
 * present-and-visible in the initial server-rendered HTML for a no-JS
 * reader; only *collapsing* it is a JS-present enhancement, done here on
 * first attach). Called once on initial load and again after every
 * Zone/Period/Language swap, since `handleClick`'s wholesale `#item-list`
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

interface ClickTarget {
  axis: "zone" | "period" | "lang";
  targetLang?: LanguageSlug;
}

async function handleClick(link: HTMLAnchorElement, target: ClickTarget): Promise<void> {
  const lang = link.dataset.lang as LanguageSlug | undefined;
  const zone = link.dataset.zone as ZoneSlug | undefined;
  const period = link.dataset.period as PeriodSlug | undefined;
  if (!lang || !zone || !period) {
    window.location.href = link.href;
    return;
  }

  const targetZone = target.axis === "zone" ? nextZone(zone) : zone;
  const targetPeriod = target.axis === "period" ? nextPeriod(period) : period;
  const targetLang = target.axis === "lang" ? target.targetLang ?? lang : lang;
  const jsonUrl = briefingJsonUrl(targetLang, targetZone, targetPeriod);

  try {
    const response = await fetch(jsonUrl);
    if (!response.ok) throw new Error(`unexpected status ${response.status}`);
    const briefing = (await response.json()) as BriefingLike;

    const sentence = document.getElementById("mad-libs-sentence");
    const itemList = document.getElementById("item-list");
    const timestamp = document.getElementById("timestamp");
    const sentenceBlock = document.getElementById("sentence-block");
    const discarded = document.getElementById("discarded");
    if (!sentence || !itemList || !timestamp || !sentenceBlock || !discarded) {
      window.location.href = pageUrl(targetLang, targetZone, targetPeriod);
      return;
    }

    // The sentence's lead-in ("Voici ce qui se passe" / "Here's what's
    // happening" / ...) is a plain text node, not an element -- it has no
    // selector to target, so find it as the first text-node child of the
    // <h1> that precedes the Zone word.
    const leadInNode = Array.from(sentence.childNodes).find(
      (node) => node.nodeType === Node.TEXT_NODE && node.textContent?.trim()
    );
    if (leadInNode) {
      leadInNode.textContent = `${MAD_LIBS_LEAD_IN[targetLang]} `;
    }

    const zoneLink = sentence.querySelector<HTMLAnchorElement>("[data-zone-word]");
    const periodLink = sentence.querySelector<HTMLAnchorElement>("[data-period-word]");
    for (const wordLink of [zoneLink, periodLink]) {
      if (!wordLink) continue;
      wordLink.dataset.zone = targetZone;
      wordLink.dataset.period = targetPeriod;
      wordLink.dataset.lang = targetLang;
    }
    if (zoneLink) {
      zoneLink.textContent = zoneSentenceLabel(targetZone, targetLang);
      zoneLink.href = pageUrl(targetLang, nextZone(targetZone), targetPeriod);
    }
    if (periodLink) {
      periodLink.textContent = periodSentenceText(targetPeriod, targetLang);
      periodLink.href = pageUrl(targetLang, targetZone, nextPeriod(targetPeriod));
    }

    // Update every Output Language option's href/dataset/active-state to
    // reflect the new Zone/Period (so switching Zone, say, doesn't leave
    // a stale Period baked into the Language links) and, when this click
    // WAS a language switch, which option is now active.
    const languageLinks = document.querySelectorAll<HTMLAnchorElement>("[data-lang-word]");
    for (const languageLink of languageLinks) {
      const optionLang = languageLink.dataset.targetLang as LanguageSlug | undefined;
      if (!optionLang) continue;
      languageLink.href = pageUrl(optionLang, targetZone, targetPeriod);
      languageLink.dataset.lang = targetLang;
      // A subsequent language click reads its target Zone/Period from
      // THIS link's own dataset (see handleClick's own zone/period reads
      // above) -- without updating these too, switching Zone or Period
      // and then Language would silently revert to whatever Zone/Period
      // was on the page at initial load.
      languageLink.dataset.zone = targetZone;
      languageLink.dataset.period = targetPeriod;
      const isActive = optionLang === targetLang;
      languageLink.classList.toggle("active", isActive);
      if (isActive) languageLink.setAttribute("aria-current", "true");
      else languageLink.removeAttribute("aria-current");
    }

    const existingNotice = document.getElementById("fallback-notice");
    existingNotice?.remove();
    const noticeHtml = renderFallbackNoticeHtml(briefing, targetLang);
    if (noticeHtml) sentence.insertAdjacentHTML("afterend", noticeHtml);

    itemList.innerHTML = renderItemListHtml(briefing, targetLang);
    discarded.innerHTML = renderDiscardedVolumeHtml(briefing, targetLang);
    timestamp.textContent = formatTimestamp(briefing.generated_at, targetLang);

    const existingEndScreen = document.getElementById("end-screen");
    existingEndScreen?.remove();
    const endScreenHtml = renderEndScreenHtml(briefing.clusters.length, targetPeriod, targetLang);
    if (endScreenHtml) discarded.insertAdjacentHTML("afterend", endScreenHtml);

    window.history.pushState({}, "", pageUrl(targetLang, targetZone, targetPeriod));
    attach();
  } catch {
    // Degrade to a real navigation rather than leaving the reader on a
    // half-updated page (AD-10's "degrade, don't break" applied to the
    // reader's own path) -- a network hiccup or unexpected 404 must not
    // silently fail into a dead click.
    window.location.href = pageUrl(targetLang, targetZone, targetPeriod);
  }
}

if (typeof document !== "undefined") {
  attach();
}
