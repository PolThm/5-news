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

import {
  browserStorage,
  LANGUAGE_CYCLE,
  PERIOD_CYCLE,
  rememberCurrentRoute,
  writePreference,
  ZONE_CYCLE,
  type LanguageSlug,
  type PeriodSlug,
  type ZoneSlug,
} from "./preferences";

export interface ClusterMemberLike {
  source: string;
  source_country: string;
}

export interface ClusterLike {
  cluster_id: string;
  // Story 6.1 -- hand-mirrored from briefing.ts's own Cluster, per this
  // file's established duplication convention (see the module docstring).
  headline?: string;
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

// The three slug cycles (and their types) live in preferences.ts, which
// owns the browser-side definition of "a real, routable Briefing address"
// -- one copy shared by both islands rather than a second hand-mirror
// here. Re-exported so this module's public surface is unchanged for its
// existing importers/tests.
export type { LanguageSlug, PeriodSlug, ZoneSlug };

// Mirrors briefing.ts's own PERIOD_SENTENCE_TEXT/periodSentenceText
// exactly -- see this file's module docstring for why this is a
// hand-kept mirror, not an import (Astro/Node-side lib code is not
// bundled for the browser here).
const PERIOD_SENTENCE_TEXT: Record<LanguageSlug, Record<PeriodSlug, string>> = {
  fr: { day: "aujourd'hui", week: "cette semaine" },
  en: { day: "today", week: "this week" },
  es: { day: "hoy", week: "esta semana" },
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

// Mirrors briefing.ts's zoneSentenceLabel exactly, for the same reason as
// the Period mirror above (the Zone slug list itself now comes from
// preferences.ts -- see the import at the top of this file).
const ZONE_SENTENCE_LABEL: Record<LanguageSlug, Partial<Record<string, string>>> = {
  fr: {
    world: "dans le Monde",
    europe: "en Europe",
    france: "en France",
    spain: "en Espagne",
  },
  en: {
    world: "in the World",
    europe: "in Europe",
    france: "in France",
    spain: "in Spain",
  },
  es: {
    world: "en el Mundo",
    europe: "en Europa",
    france: "en Francia",
    spain: "en España",
  },
};

const ZONE_SERVED_LABEL: Record<LanguageSlug, Partial<Record<ZoneSlug, string>>> = {
  fr: {
    europe: "l'Europe",
  },
  en: {
    europe: "Europe",
  },
  es: {
    europe: "Europa",
  },
};

interface RequestedLabel {
  label: string;
  plural: boolean;
}

const ZONE_REQUESTED_LABEL: Record<LanguageSlug, Partial<Record<ZoneSlug, RequestedLabel>>> = {
  fr: {
    france: { label: "la France", plural: false },
    spain: { label: "l'Espagne", plural: false },
  },
  en: {
    france: { label: "France", plural: false },
    spain: { label: "Spain", plural: false },
  },
  es: {
    france: { label: "Francia", plural: false },
    spain: { label: "España", plural: false },
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

// Story 4.8 (AC2): aria-live announcement text for each mad-libs axis --
// role, current value, and (for the two cycle-by-one axes) what changing
// it does. Match the AC's own example phrasing shape ("Zone, World,
// button, cycles to Europe") for Zone/Period; Language deliberately does
// NOT use "cycles to" wording, since it's a direct-jump control with no
// "next value" concept (Story 4.7) -- forcing cycle language onto it
// would misdescribe the actual interaction to a screen-reader user.
// The AC's own example phrasing ("Zone, World, button, cycles to
// Europe") uses BARE zone names, with no preposition -- ZONE_SENTENCE_LABEL
// above bakes a preposition into every entry for its own mad-libs-sentence
// use case ("in the World", "in Europe"), which would double up with this
// announcement's own verb phrase ("cycles to in Europe") if reused
// directly. A separate bare-name table avoids that, at the cost of a
// third hand-mirrored lookup for the same 15 Zones.
const ZONE_BARE_NAME: Record<LanguageSlug, Partial<Record<string, string>>> = {
  fr: {
    world: "le Monde",
    europe: "l'Europe",
    france: "la France",
    spain: "l'Espagne",
  },
  en: {
    world: "the World",
    europe: "Europe",
    france: "France",
    spain: "Spain",
  },
  es: {
    world: "el Mundo",
    europe: "Europa",
    france: "Francia",
    spain: "España",
  },
};

function zoneBareName(zone: string, lang: LanguageSlug): string {
  return ZONE_BARE_NAME[lang][zone] ?? zone;
}

const ZONE_ANNOUNCEMENT_ROLE: Record<LanguageSlug, { role: string; verb: string }> = {
  fr: { role: "Zone", verb: "passe à" },
  en: { role: "Zone", verb: "cycles to" },
  es: { role: "Zona", verb: "cambia a" },
};

export function zoneAnnouncementText(
  currentZone: string,
  nextZoneSlug: string,
  lang: LanguageSlug
): string {
  const { role, verb } = ZONE_ANNOUNCEMENT_ROLE[lang];
  return `${role}, ${zoneBareName(currentZone, lang)}, ${lang === "fr" ? "bouton" : lang === "es" ? "botón" : "button"}, ${verb} ${zoneBareName(nextZoneSlug, lang)}`;
}

const PERIOD_ANNOUNCEMENT_ROLE: Record<LanguageSlug, { role: string; verb: string }> = {
  fr: { role: "Période", verb: "passe à" },
  en: { role: "Period", verb: "cycles to" },
  es: { role: "Período", verb: "cambia a" },
};

export function periodAnnouncementText(
  currentPeriod: PeriodSlug,
  nextPeriodSlug: PeriodSlug,
  lang: LanguageSlug
): string {
  const { role, verb } = PERIOD_ANNOUNCEMENT_ROLE[lang];
  return `${role}, ${periodSentenceText(currentPeriod, lang)}, ${lang === "fr" ? "bouton" : lang === "es" ? "botón" : "button"}, ${verb} ${periodSentenceText(nextPeriodSlug, lang)}`;
}

const LANGUAGE_ANNOUNCEMENT_ROLE: Record<LanguageSlug, string> = {
  fr: "Langue",
  en: "Language",
  es: "Idioma",
};

// Every language's own name, as said IN each of the 3 languages -- e.g.
// LANGUAGE_NAME.fr.en === "Anglais" (French for "English").
const LANGUAGE_NAME: Record<LanguageSlug, Record<LanguageSlug, string>> = {
  fr: { fr: "Français", en: "Anglais", es: "Espagnol" },
  en: { fr: "French", en: "English", es: "Spanish" },
  es: { fr: "Francés", en: "Inglés", es: "Español" },
};

// Announced IN the previous language (the one the reader could still
// read at the moment of the click), not the new one -- a reader who
// doesn't yet read the target language should still understand what
// just happened, matching how a sighted reader experiences the change
// (they see the switch happen while still looking at the old page, a
// beat before the new content replaces it).
export function languageAnnouncementText(targetLang: LanguageSlug, previousLang: LanguageSlug): string {
  const role = LANGUAGE_ANNOUNCEMENT_ROLE[previousLang];
  const targetName = LANGUAGE_NAME[previousLang][targetLang];
  return `${role}, ${targetName}`;
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
// Bare country names for the Consensus chip's source list, keyed on an
// Article's `source_country`, per Output Language.
//
// Deliberately NOT trimmed when the routable Zones narrowed to
// World/Europe/France/Spain on 2026-08-19: this is keyed on where an Article
// came *from*, not where a reader can navigate to. A published cycle's
// Articles span ~145 countries; an unlisted one renders as its raw slug in
// the one place the product asks the reader to trust a count. Mirrors
// briefing.ts's table.
const COUNTRY_LABEL: Record<LanguageSlug, Partial<Record<string, string>>> = {
  fr: {
    france: "France",
    spain: "Espagne",
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
    spain: "Spain",
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
    spain: "España",
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

// The server renders this timestamp in UTC because a statically prerendered
// page cannot know the reader's timezone (see BriefingPage.astro's own
// comment). Here in the browser it *is* knowable, so the reader gets their
// own wall clock instead of having to convert one in their head: a Paris
// reader sees "07:54 CEST", a Madrid reader the same, a New York reader
// "01:54 EDT" -- and the abbreviation follows the season on its own, which
// is the half a hardcoded "CEST" would get wrong for five months of the year.

// Why the abbreviation is derived here rather than taken from Intl.
//
// `timeZoneName: "short"` is the obvious way to get "CEST", and it does not
// work for the zone this site cares most about. CLDR has no short
// abbreviation for Europe/Paris in most locales, so Intl falls back to an
// offset, and *which* fallback you get depends on the locale:
//
//   fr -> "UTC+2"    en -> "GMT+2"    es -> "CEST"
//
// So the reader's label would change with the Output Language for the same
// instant in the same city, and French -- the primary language -- would be
// the one that never shows "CEST" at all. Deriving it from the UTC offset
// gives every language the same, expected abbreviation.
//
// The table covers Central/Western/Eastern Europe, which is what this site's
// Zones (france, spain, europe, world) actually put readers in. Anywhere
// else falls through to Intl's own short name, which is correct for the
// Americas ("EDT", "PST") and degrades to a readable "GMT+9" elsewhere --
// better than inventing an abbreviation for a zone we have not reasoned about.
const EUROPEAN_ZONE_ABBREVIATIONS: Record<string, { standard: string; daylight: string }> = {
  "Europe/Paris": { standard: "CET", daylight: "CEST" },
  "Europe/Madrid": { standard: "CET", daylight: "CEST" },
  "Europe/Brussels": { standard: "CET", daylight: "CEST" },
  "Europe/Berlin": { standard: "CET", daylight: "CEST" },
  "Europe/Rome": { standard: "CET", daylight: "CEST" },
  "Europe/Amsterdam": { standard: "CET", daylight: "CEST" },
  "Europe/Vienna": { standard: "CET", daylight: "CEST" },
  "Europe/Zurich": { standard: "CET", daylight: "CEST" },
  "Europe/Warsaw": { standard: "CET", daylight: "CEST" },
  "Europe/Prague": { standard: "CET", daylight: "CEST" },
  "Europe/Stockholm": { standard: "CET", daylight: "CEST" },
  "Europe/Oslo": { standard: "CET", daylight: "CEST" },
  "Europe/Copenhagen": { standard: "CET", daylight: "CEST" },
  "Europe/Budapest": { standard: "CET", daylight: "CEST" },
  "Europe/Lisbon": { standard: "WET", daylight: "WEST" },
  "Europe/London": { standard: "GMT", daylight: "BST" },
  "Europe/Dublin": { standard: "GMT", daylight: "IST" },
  "Europe/Athens": { standard: "EET", daylight: "EEST" },
  "Europe/Helsinki": { standard: "EET", daylight: "EEST" },
  "Europe/Bucharest": { standard: "EET", daylight: "EEST" },
};

/** The zone's offset from UTC, in minutes, at a given instant. */
function zoneOffsetMinutes(date: Date, timeZone: string): number {
  // Intl has no "give me the offset" call, so read the wall clock in the
  // target zone and diff it against the same instant read as UTC. `en-CA`
  // for its ISO-shaped output, which parses back reliably.
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(date);

  const field = (type: string): number => Number(parts.find((part) => part.type === type)?.value);
  // Hour 24 is how some engines spell midnight here; Date.UTC handles the
  // rollover correctly, so it needs no special-casing beyond being allowed.
  const asUtc = Date.UTC(
    field("year"),
    field("month") - 1,
    field("day"),
    field("hour"),
    field("minute"),
    field("second")
  );

  // date.getTime() carries milliseconds the formatted parts above dropped, so
  // floor both to the second before diffing -- otherwise a stamp like
  // ...:12.555Z yields a fractional offset that rounds unpredictably.
  return Math.round((asUtc - Math.floor(date.getTime() / 1000) * 1000) / 60_000);
}

/**
 * Whether daylight saving is in force in `timeZone` at `date`.
 *
 * Compares the instant's offset against January's and July's: the larger of
 * those two is the daylight offset, and a zone that does not observe DST has
 * both equal, so this correctly reports false for it.
 */
function isDaylightSaving(date: Date, timeZone: string): boolean {
  const year = Number(
    new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric" }).format(date)
  );
  const january = zoneOffsetMinutes(new Date(Date.UTC(year, 0, 1, 12)), timeZone);
  const july = zoneOffsetMinutes(new Date(Date.UTC(year, 6, 1, 12)), timeZone);

  return zoneOffsetMinutes(date, timeZone) > Math.min(january, july);
}

/** The zone abbreviation to print -- "CEST", "EDT", "GMT+9". */
export function zoneAbbreviation(date: Date, timeZone: string): string {
  const european = EUROPEAN_ZONE_ABBREVIATIONS[timeZone];
  if (european) {
    return isDaylightSaving(date, timeZone) ? european.daylight : european.standard;
  }

  // Pinned to en-US rather than the reader's language, for the same reason
  // the table above exists: the short name is locale-dependent, and only
  // en-US reliably yields the real abbreviation where one exists ("EDT",
  // "PST"). Asking in French for New York gives "UTC−4" instead. Zones with
  // no abbreviation at all still degrade to a readable "GMT+9".
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    timeZoneName: "short",
  }).formatToParts(date);

  return parts.find((part) => part.type === "timeZoneName")?.value ?? "UTC";
}

// The fallback below matters more than it looks: `resolvedOptions().timeZone`
// is empty on some older engines and a bad TZ throws from the Intl
// constructor, and a Briefing header reading UTC is a far better outcome than
// one that renders nothing.
export function formatTimestamp(iso: string, lang: LanguageSlug, timeZone?: string): string {
  const date = new Date(iso);

  try {
    const zone = timeZone ?? new Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (zone) {
      const parts = new Intl.DateTimeFormat(lang, {
        timeZone: zone,
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).formatToParts(date);

      const hour = parts.find((part) => part.type === "hour")?.value;
      const minute = parts.find((part) => part.type === "minute")?.value;

      if (hour && minute) {
        const abbreviation = zoneAbbreviation(date, zone);
        return `${TIMESTAMP_PREFIX[lang]} ${hour}:${minute} ${abbreviation}`;
      }
    }
  } catch {
    // Fall through to UTC below.
  }

  const hours = String(date.getUTCHours()).padStart(2, "0");
  const minutes = String(date.getUTCMinutes()).padStart(2, "0");
  return `${TIMESTAMP_PREFIX[lang]} ${hours}:${minutes} UTC`;
}

/**
 * Rewrite the server-rendered UTC timestamp into the reader's own timezone.
 *
 * The server-side markup carries UTC and a `data-generated-at` ISO stamp;
 * this reads that stamp and replaces the text in place. Runs at module load
 * alongside attach(), so a direct link, a bookmark and a back-navigation all
 * get it, not only a mad-libs swap.
 *
 * No-ops when the element or the stamp is missing, which is what keeps a
 * no-JS reader (and the pre-hydration paint) on the honest UTC string rather
 * than a blank or a wrong local time.
 */
export function localiseTimestamp(): void {
  // Guarded rather than called straight: this runs from attach(), which the
  // suite drives against hand-built stand-in documents (this module is
  // deliberately jsdom-free -- see the module docstring), and a Briefing
  // page must not lose its header to a DOM that is missing a method.
  if (typeof document === "undefined" || typeof document.getElementById !== "function") {
    return;
  }

  const timestamp = document.getElementById("timestamp");
  if (!timestamp) return;

  const iso = timestamp.dataset?.generatedAt;
  const lang = timestamp.dataset?.lang as LanguageSlug | undefined;
  if (!iso || !lang) return;

  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return;

  timestamp.textContent = formatTimestamp(iso, lang);
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
      // Story 6.1: the headline is an <h2> -- the page's first real heading
      // level below the mad-libs <h1>, giving screen-reader users a
      // navigable item list. Rendered before the summary, mirroring
      // BriefingPage.astro exactly.
      const headlineHtml = cluster.headline
        ? `<h2 class="headline">${escapeHtml(cluster.headline)}</h2>`
        : "";
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
        `<div class="item">${headlineHtml}${summaryHtml}` +
        `<button type="button" class="chip" aria-expanded="false" aria-controls="${sourceListId}" data-consensus-chip>` +
        `<span class="num">${cluster.independent_source_count}</span> ${escapeHtml(chipText.sources)} · ` +
        `<span class="num">${cluster.country_count}</span> ${escapeHtml(chipText.countries)}` +
        `<span class="chevron" aria-hidden="true">▾</span></button>` +
        `<div class="source-list" id="${sourceListId}">${escapeHtml(intro)}<ul>${membersHtml}</ul></div>` +
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
  localiseTimestamp();
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
 * the document. The source list starts collapsed via a plain CSS rule
 * (`.source-list { display: none }` in BriefingPage.astro) present in the
 * server-rendered HTML itself, NOT via a class this function adds after
 * the fact -- an earlier version added a `js-collapsed` class here, which
 * meant the source list rendered open for one paint and then snapped
 * shut the moment this ran, a visible "flicker" on every page load. A
 * `<noscript>` override restores the EXPERIENCE.md Cold Load requirement
 * (source list readable with zero client-side execution) for the reader
 * this function never runs for.
 *
 * Called once on initial load and again after every Zone/Period/Language
 * swap, since `handleClick`'s wholesale `#item-list` replacement destroys
 * the previous chips' listeners entirely (unlike the mad-libs words,
 * which are mutated in place) -- every freshly-rendered chip starts
 * collapsed, matching that same base CSS rule.
 */
export function attachChips(): void {
  const chips = document.querySelectorAll<HTMLButtonElement>("[data-consensus-chip]");
  for (const chip of chips) {
    if (chip.hasAttribute(CHIP_ATTACHED_MARKER)) continue;
    chip.setAttribute(CHIP_ATTACHED_MARKER, "");

    chip.addEventListener("click", () => toggleChip(chip));
  }
}

function toggleChip(chip: HTMLButtonElement): void {
  const sourceList = document.getElementById(chip.getAttribute("aria-controls") ?? "");
  if (!sourceList) return;

  const expanded = chip.getAttribute("aria-expanded") === "true";
  chip.setAttribute("aria-expanded", expanded ? "false" : "true");
  sourceList.classList.toggle("js-expanded", !expanded);
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
    // Keep the dataset in step with the text. attach() runs at the end of
    // this handler and calls localiseTimestamp(), which re-derives the text
    // from these attributes -- leaving them stale would let the *previous*
    // Briefing's timestamp overwrite the one just rendered.
    timestamp.setAttribute("data-generated-at", briefing.generated_at);
    timestamp.setAttribute("data-lang", targetLang);
    timestamp.textContent = formatTimestamp(briefing.generated_at, targetLang);

    const existingEndScreen = document.getElementById("end-screen");
    existingEndScreen?.remove();
    const endScreenHtml = renderEndScreenHtml(briefing.clusters.length, targetPeriod, targetLang);
    if (endScreenHtml) discarded.insertAdjacentHTML("afterend", endScreenHtml);

    // AC2's aria-live announcement -- exactly one axis changes per click
    // (target.axis), so only that axis's announcement is written; the
    // other two axes' values are unchanged and don't need announcing.
    // Language is announced in the PREVIOUS language (lang, not
    // targetLang) -- see languageAnnouncementText's own docstring.
    const announcer = document.getElementById("sr-announcer");
    if (announcer) {
      if (target.axis === "zone") {
        announcer.textContent = zoneAnnouncementText(zone, targetZone, targetLang);
      } else if (target.axis === "period") {
        announcer.textContent = periodAnnouncementText(period, targetPeriod, targetLang);
      } else if (target.axis === "lang") {
        announcer.textContent = languageAnnouncementText(targetLang, lang);
      }
    }

    // The document's own language must follow the swap, not stay frozen
    // at whatever `/[lang]/...` was server-rendered. Without this, a
    // browser keeps applying the OLD language's font fallback, hyphenation
    // and quote conventions to the new text, and a screen reader keeps
    // announcing it in the old language's voice -- the swapped page ends
    // up looking and sounding subtly different from the same page reached
    // by a real navigation.
    document.documentElement.lang = targetLang;

    window.history.pushState({}, "", pageUrl(targetLang, targetZone, targetPeriod));

    // Persisted here as well as on page load (see this module's own
    // bottom-of-file init): a swap only pushState's the URL, so the
    // next load-time capture would never run for this choice -- close
    // the app right after switching and the choice would be lost.
    writePreference(browserStorage(), {
      lang: targetLang,
      zone: targetZone,
      period: targetPeriod,
    });

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
  // Every Briefing page load records where the reader is, so `/` can send
  // them back here next time (language-detect.ts's entryTargetFor). Covers
  // the paths a swap can't: a direct link, a bookmark, the no-JS `<a>`
  // navigation, and handleClick's own degrade-to-navigation fallback.
  rememberCurrentRoute(window.location.pathname);
}
