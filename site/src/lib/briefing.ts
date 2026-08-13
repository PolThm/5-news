// The on-disk shape of a published Briefing, mirroring
// pipeline/domain/__init__.py's BriefingRecord.to_dict() field-for-field.
// Hand-written, not generated: this file must never import from pipeline/
// (scripts/check-boundary.sh forbids any cross-reference), so it is kept in
// sync by hand whenever BriefingRecord's schema changes -- a schema change
// there is a version bump (schemaVersion), never a silent field edit here.

export type ZoneKind = "world" | "continent" | "country";
export type Period = "day" | "week" | "month";
export type OutputLanguage = "fr" | "en" | "es";

export const OUTPUT_LANGUAGE_CYCLE: readonly OutputLanguage[] = ["fr", "en", "es"];

export interface ClusterMember {
  title: string;
  url: string;
  source: string;
  source_country: string;
  language: string;
}

export interface Cluster {
  cluster_id: string;
  members: ClusterMember[];
  independent_source_count: number;
  country_count: number;
  countries: string[];
  origin_country: string;
  rank: number;
  // Absent entirely (not just null) when the Cluster wasn't found in the
  // summarize pool -- publish.py's _attach_summary early-returns without
  // adding any of these three keys in that case. Treat "missing" and
  // "present but null" identically: both mean "no outbound link, and/or
  // no AI summary, for this item."
  summary?: string;
  outbound_url?: string | null;
  outbound_source?: string | null;
}

export interface BriefingRecord {
  schema_version: number;
  zone: string;
  zone_kind: ZoneKind;
  zone_continent: string | null;
  served_zone: string;
  served_zone_kind: ZoneKind;
  served_zone_continent: string | null;
  period: Period;
  language: OutputLanguage;
  clusters: Cluster[];
  // Always 0/0 today -- no pipeline stage populates real values yet
  // (BriefingRecord's own docstring flags this explicitly). Never treat
  // 0/0 as evidence nothing was filtered.
  discarded_ingested: number;
  discarded_kept: number;
  generated_at: string;
}

// The day -> week -> month -> day cycle Story 4.2's mad-libs Period word
// advances through on each click (FR-2). A plain array-index cycle, not a
// lookup table with explicit next-pointers, since three elements never
// need more machinery than that -- kept here (not in a page/component) so
// both the server-rendered link's href and the client island's click
// handler compute the identical next value from one source of truth.
const PERIOD_CYCLE: readonly Period[] = ["day", "week", "month"];

export function nextPeriod(current: Period): Period {
  const index = PERIOD_CYCLE.indexOf(current);
  return PERIOD_CYCLE[(index + 1) % PERIOD_CYCLE.length];
}

// The mad-libs sentence's Period word text, per Period, per Output
// Language (Story 4.7) -- distinct from the Period's own URL slug
// ("day"/"week"/"month"), which is never shown to a reader.
const PERIOD_SENTENCE_TEXT: Record<OutputLanguage, Record<Period, string>> = {
  fr: { day: "aujourd'hui", week: "cette semaine", month: "ce mois" },
  en: { day: "today", week: "this week", month: "this month" },
  es: { day: "hoy", week: "esta semana", month: "este mes" },
};

export function periodSentenceText(period: Period, lang: OutputLanguage): string {
  return PERIOD_SENTENCE_TEXT[lang][period];
}

/**
 * Whether a Cluster's outbound link is safe and complete enough to render.
 *
 * `outbound_url`/`outbound_source` can each independently be missing,
 * null, or an empty string (pipeline/domain's own documented range for
 * `_select_outbound_link`'s degrade path) -- attribution only renders
 * when BOTH are present, so a reader never sees a bare "Rapporté par
 * null" or a dead link with no outlet name. Also guards against an
 * unexpected non-http(s) scheme (e.g. "javascript:") ever reaching an
 * `<a href>` -- the pipeline should never produce one, but this is
 * externally-influenced content (an Article's own URL, several stages
 * removed), so validating the scheme here costs nothing and closes off a
 * class of bug this codebase has no other check against.
 */
export function hasValidAttribution(
  cluster: Pick<Cluster, "outbound_url" | "outbound_source">
): cluster is { outbound_url: string; outbound_source: string } {
  return (
    !!cluster.outbound_url && !!cluster.outbound_source && /^https?:\/\//i.test(cluster.outbound_url)
  );
}

// The 15 Zones (World, 6 Continents, 8 Countries), in the exact cycle order
// of pipeline/config/__init__.py's ZONES tuple. Hand-mirrored, not
// imported -- site/ must never import from pipeline/
// (scripts/check-boundary.sh forbids any cross-reference); this list is
// kept in sync by hand the same way BriefingRecord's fields above are.
// Adding a Zone there is a breaking routing change here too (see that
// file's own header comment).
export const ZONE_CYCLE: readonly string[] = [
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
];

export function nextZone(current: string): string {
  const index = ZONE_CYCLE.indexOf(current);
  return ZONE_CYCLE[(index + 1) % ZONE_CYCLE.length];
}

// The mad-libs sentence's Zone word text, per Zone, per Output Language --
// each entry is a full preposition-inclusive phrase ("dans le Monde", "in
// the World", "en el Mundo"), not a bare noun, because each language's
// geographic prepositions/articles vary by Zone in its own way (French:
// continents and non-plural feminine countries take "en", masculine
// countries take "au", the one plural country takes "aux", the World takes
// "dans le"; English uses a uniform "in" but "the" for a few proper nouns;
// Spanish uses "en" uniformly but "el"/no-article per Zone). Baking the
// preposition into the label keeps the surrounding sentence template (a
// single fixed per-language string) with no second per-Zone grammatical
// dimension to track. Each language's table is independently authored for
// that language's own grammar -- never derived from another language's
// structure.
const ZONE_SENTENCE_LABEL: Record<OutputLanguage, Partial<Record<string, string>>> = {
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

// Defensive fallback for a zone slug outside the known 15 (malformed data,
// per fallbackNoticeText's own precedent below) -- returns the raw slug
// rather than `undefined`/throwing, so a build never crashes on
// unexpected input.
export function zoneSentenceLabel(zone: string, lang: OutputLanguage): string {
  return ZONE_SENTENCE_LABEL[lang][zone] ?? zone;
}

// The Continent-fallback notice's clause forms -- distinct from
// ZONE_SENTENCE_LABEL because each language's grammatical role changes the
// article/verb: the mad-libs sentence uses a preposition form ("en
// France"/"in France"), but the fallback notice's subject clause uses a
// subject form with its own article and verb-number agreement ("la France
// n'a pas..."/"France doesn't have..."). Only Continents ever appear as
// `servedLabel` (a Country never falls back to another Country) and only
// Countries ever appear as `requestedLabel` (Continents and World never
// fall back, per pipeline/stages/rank.py's own logic) -- so each map only
// needs to cover the 6 Continents or 8 Countries respectively, not all 15
// Zones.
const ZONE_SERVED_LABEL: Record<OutputLanguage, Partial<Record<string, string>>> = {
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

const ZONE_REQUESTED_LABEL: Record<OutputLanguage, Partial<Record<string, RequestedLabel>>> = {
  fr: {
    france: { label: "la France", plural: false },
    "united-kingdom": { label: "le Royaume-Uni", plural: false },
    germany: { label: "l'Allemagne", plural: false },
    // The one Country whose name is grammatically plural in French -- the
    // verb in fallbackNoticeText's sentence must agree ("n'ont pas", not
    // "n'a pas") or the notice reads as a native-speaker-visible grammar
    // error. English/Spanish both also treat "the United States" as
    // formally plural for this same clause.
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

export function isZoneFallback(briefing: Pick<BriefingRecord, "zone" | "served_zone">): boolean {
  return briefing.served_zone !== briefing.zone;
}

/**
 * The Continent-fallback notice's exact sentence (FR-16), per Output
 * Language, or `null` when no fallback is active. Data-driven entirely
 * from `zone`/`served_zone` already present in the loaded `BriefingRecord`
 * -- the pipeline (pipeline/stages/rank.py) already decided the
 * substitution before writing the file; this only renders the decision,
 * never re-derives it.
 */
export function fallbackNoticeText(
  briefing: Pick<BriefingRecord, "zone" | "served_zone">,
  lang: OutputLanguage
): string | null {
  if (!isZoneFallback(briefing)) return null;

  const servedLabel = ZONE_SERVED_LABEL[lang][briefing.served_zone];
  const requested = ZONE_REQUESTED_LABEL[lang][briefing.zone];
  // Defense against a malformed data/briefings/**/*.json (partial write,
  // hand-edit, future pipeline bug): loadBriefing does no schema
  // validation, and this function runs unconditionally for every
  // statically-generated page at build time -- an uncaught crash here would
  // fail the whole `astro build`, not just one page. Today's pipeline logic
  // only ever produces zone/served_zone pairs both tables cover, but this
  // function must not assume that holds for every byte on disk.
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

/**
 * The End Screen's completion statement (FR-5, UX-DR8), per Output
 * Language, or `null` when there is nothing to declare complete (0 items
 * -- a real, already-observed state per Story 4.1's AC6 empty-clusters
 * case; no UX spec defines what this sentence should say for zero items,
 * so the End Screen is suppressed entirely rather than inventing copy).
 * Reuses periodSentenceText's exact wording (not a separate copy) so the
 * End Screen's period phrase and the mad-libs Period word never drift.
 * Singular/plural agreement changes with the item count in every
 * supported language, each with its own rule -- French's "1 sujet a
 * atteint..." vs "N sujets ont atteint...", the same class of agreement
 * fallbackNoticeText handles for "les États-Unis".
 */
export function endScreenText(
  itemCount: number,
  period: Period,
  lang: OutputLanguage
): string | null {
  if (itemCount === 0) return null;

  const periodText = periodSentenceText(period, lang);
  switch (lang) {
    case "fr": {
      const noun = itemCount === 1 ? "sujet" : "sujets";
      const verb = itemCount === 1 ? "a" : "ont";
      return `Vous avez atteint la fin. ${itemCount} ${noun} ${verb} atteint le seuil ${periodText}.`;
    }
    case "en": {
      const noun = itemCount === 1 ? "story" : "stories";
      return `You've reached the end. ${itemCount} ${noun} met the threshold ${periodText}.`;
    }
    case "es": {
      const noun = itemCount === 1 ? "tema" : "temas";
      const verb = itemCount === 1 ? "alcanzó" : "alcanzaron";
      return `Has llegado al final. ${itemCount} ${noun} ${verb} el umbral ${periodText}.`;
    }
  }
}

// French, English, and Spanish all use a different thousands-separator
// convention for the `numeral` typography token's numbers (the Discarded
// Volume line and the Consensus chip both display ranking-derived counts;
// DESIGN.md: "treat every number that comes from the ranking... as content
// worth its own typographic treatment") -- French uses a space, English
// and most Spanish-speaking locales use a comma. Deliberately "es-MX," not
// "es-ES": Spain's own locale data groups digits inconsistently below 5
// digits (`(1384).toLocaleString("es-ES")` produces "1384", no separator
// at all, for a 4-digit number) -- "es-MX" gives the more globally-typical
// comma grouping ("1,384") that matches this site's other two languages'
// visual weight, without picking a specific national variant as more
// "correct" Spanish than another.
const LOCALE_BY_LANGUAGE: Record<OutputLanguage, string> = {
  fr: "fr-FR",
  en: "en-US",
  es: "es-MX",
};

export function formatCount(n: number, lang: OutputLanguage): string {
  // n.toLocaleString("fr-FR") produces a narrow no-break space (U+202F)
  // as its thousands separator -- technically correct French typography,
  // but an invisible-looking character that's easy to mistype/mismatch in
  // source code and tests. Normalize to a plain space (U+0020), matching
  // mockups/briefing-world-day.html's own literal "1 384" HTML.
  return n.toLocaleString(LOCALE_BY_LANGUAGE[lang]).replace(/ /g, " ");
}

// Bare country names (no article, no preposition) for the Consensus chip's
// expanded source list, per Output Language -- distinct from
// ZONE_SENTENCE_LABEL (preposition-inclusive) and ZONE_REQUESTED_LABEL
// (subject-form with its own article) because the source list's "Source
// (Country)" format needs neither: just the bare name. Only the 8
// supported Countries are listed; a source_country outside this set (a
// real, fixture-observed case -- e.g. "australia", a real Article origin
// that isn't one of the 8 site-routable Countries) degrades to its own raw
// slug rather than throwing or rendering "undefined".
const COUNTRY_LABEL: Record<OutputLanguage, Partial<Record<string, string>>> = {
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

export function countryLabel(countrySlug: string, lang: OutputLanguage): string {
  return COUNTRY_LABEL[lang][countrySlug] ?? countrySlug;
}

// The mad-libs sentence's fixed lead-in ("Voici ce qui se passe {zone},
// {period}.") -- moved here from BriefingPage.astro (Story 4.7) alongside
// every other small per-language text function in this file, rather than
// left as inline JSX/template text with no single per-language owner.
const MAD_LIBS_LEAD_IN: Record<OutputLanguage, string> = {
  fr: "Voici ce qui se passe",
  en: "Here's what's happening",
  es: "Esto es lo que está pasando",
};

export function madLibsLeadIn(lang: OutputLanguage): string {
  return MAD_LIBS_LEAD_IN[lang];
}

// The Consensus chip's "N independent sources · M countries" wording, per
// Output Language. Returned as a pair (not one combined string) since the
// numeral <span>s are interleaved between the two phrase fragments in the
// markup -- see BriefingPage.astro/period-switcher.ts's own chip rendering.
const CONSENSUS_CHIP_TEXT: Record<OutputLanguage, { sources: string; countries: string }> = {
  fr: { sources: "sources indépendantes", countries: "pays" },
  en: { sources: "independent sources", countries: "countries" },
  es: { sources: "fuentes independientes", countries: "países" },
};

export function consensusChipText(lang: OutputLanguage): { sources: string; countries: string } {
  return CONSENSUS_CHIP_TEXT[lang];
}

// The Consensus chip's expanded source-list intro line ("Sources et pays
// contributeurs :"), per Output Language.
const SOURCE_LIST_INTRO: Record<OutputLanguage, string> = {
  fr: "Sources et pays contributeurs :",
  en: "Contributing sources and countries:",
  es: "Fuentes y países contribuyentes:",
};

export function sourceListIntro(lang: OutputLanguage): string {
  return SOURCE_LIST_INTRO[lang];
}

// Attribution's "Rapporté par {outlet} — lire l'article original →" wording,
// per Output Language. Returned as a pair for the same interleaving reason
// as consensusChipText.
const ATTRIBUTION_TEXT: Record<OutputLanguage, { reportedBy: string; readOriginal: string }> = {
  fr: { reportedBy: "Rapporté par", readOriginal: "lire l'article original →" },
  en: { reportedBy: "Reported by", readOriginal: "read the original article →" },
  es: { reportedBy: "Informado por", readOriginal: "leer el artículo original →" },
};

export function attributionText(lang: OutputLanguage): { reportedBy: string; readOriginal: string } {
  return ATTRIBUTION_TEXT[lang];
}

// Discarded Volume's "{n} articles examinés → {n} conservés." wording, per
// Output Language (FR-8). Returned as a pair for the same interleaving
// reason as consensusChipText -- the two numeral <span>s sit between the
// fragments.
const DISCARDED_VOLUME_TEXT: Record<OutputLanguage, { reviewed: string; kept: string }> = {
  fr: { reviewed: "articles examinés", kept: "conservés." },
  en: { reviewed: "articles reviewed", kept: "kept." },
  es: { reviewed: "artículos examinados", kept: "conservados." },
};

export function discardedVolumeText(lang: OutputLanguage): { reviewed: string; kept: string } {
  return DISCARDED_VOLUME_TEXT[lang];
}

// The header timestamp's "Mis à jour à {h}:{m} UTC" wording, per Output
// Language -- moved here from BriefingPage.astro's own formatTimestamp
// (Story 4.7), which now only formats the hours/minutes and delegates the
// surrounding phrase to this function.
const TIMESTAMP_PREFIX: Record<OutputLanguage, string> = {
  fr: "Mis à jour à",
  en: "Updated at",
  es: "Actualizado a las",
};

export function timestampPrefix(lang: OutputLanguage): string {
  return TIMESTAMP_PREFIX[lang];
}
