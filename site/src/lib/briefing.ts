// The on-disk shape of a published Briefing, mirroring
// pipeline/domain/__init__.py's BriefingRecord.to_dict() field-for-field.
// Hand-written, not generated: this file must never import from pipeline/
// (scripts/check-boundary.sh forbids any cross-reference), so it is kept in
// sync by hand whenever BriefingRecord's schema changes -- a schema change
// there is a version bump (schemaVersion), never a silent field edit here.

export type ZoneKind = "world" | "continent" | "country";
export type Period = "day" | "week" | "month";
export type OutputLanguage = "fr" | "en" | "es";

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

// The mad-libs sentence's Period word text, per Period -- distinct from
// the Period's own URL slug ("day"/"week"/"month"), which is never shown
// to a reader. French only in this story's scope (Story 4.7 owns Output
// Language switching); a future story generalizes this per language.
const PERIOD_SENTENCE_TEXT: Record<Period, string> = {
  day: "aujourd'hui",
  week: "cette semaine",
  month: "ce mois",
};

export function periodSentenceText(period: Period): string {
  return PERIOD_SENTENCE_TEXT[period];
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

// The mad-libs sentence's Zone word text, per Zone -- each entry is a full
// preposition-inclusive French phrase ("dans le Monde", "en Europe", "au
// Japon"), not a bare noun, because French geographic prepositions vary by
// Zone (continents and non-plural feminine countries take "en", masculine
// countries take "au", the one plural country takes "aux", the World takes
// "dans le"). Baking the preposition into the label keeps the surrounding
// sentence template ("Voici ce qui se passe {label}, {period}.") a single
// fixed string with no second per-Zone grammatical dimension to track.
const ZONE_SENTENCE_LABEL: Record<string, string> = {
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

export function zoneSentenceLabel(zone: string): string {
  return ZONE_SENTENCE_LABEL[zone];
}

// The Continent-fallback notice's clause forms -- distinct from
// ZONE_SENTENCE_LABEL because French grammatical role changes the article:
// the mad-libs sentence uses "en France" (preposition), but the fallback
// notice's subject clause uses "la France n'a pas..." (subject, own
// article, own verb-number agreement). Only Continents ever appear as
// `servedLabel` (a Country never falls back to another Country) and only
// Countries ever appear as `requestedLabel` (Continents and World never
// fall back, per pipeline/stages/rank.py's own logic) -- so each map only
// needs to cover the 6 Continents or 8 Countries respectively, not all 15
// Zones.
const ZONE_SERVED_LABEL: Record<string, string> = {
  europe: "l'Europe",
  "north-america": "l'Amérique du Nord",
  "south-america": "l'Amérique du Sud",
  asia: "l'Asie",
  africa: "l'Afrique",
  oceania: "l'Océanie",
};

const ZONE_REQUESTED_LABEL: Record<string, { label: string; plural: boolean }> = {
  france: { label: "la France", plural: false },
  "united-kingdom": { label: "le Royaume-Uni", plural: false },
  germany: { label: "l'Allemagne", plural: false },
  // The one Country whose French name is grammatically plural -- the verb
  // in fallbackNoticeText's sentence must agree ("n'ont pas", not "n'a
  // pas") or the notice reads as a native-speaker-visible grammar error.
  "united-states": { label: "les États-Unis", plural: true },
  japan: { label: "le Japon", plural: false },
  china: { label: "la Chine", plural: false },
  india: { label: "l'Inde", plural: false },
  brazil: { label: "le Brésil", plural: false },
};

export function isZoneFallback(briefing: Pick<BriefingRecord, "zone" | "served_zone">): boolean {
  return briefing.served_zone !== briefing.zone;
}

/**
 * The Continent-fallback notice's exact French sentence (FR-16), or `null`
 * when no fallback is active. Data-driven entirely from `zone`/`served_zone`
 * already present in the loaded `BriefingRecord` -- the pipeline
 * (pipeline/stages/rank.py) already decided the substitution before writing
 * the file; this only renders the decision, never re-derives it.
 */
export function fallbackNoticeText(
  briefing: Pick<BriefingRecord, "zone" | "served_zone">
): string | null {
  if (!isZoneFallback(briefing)) return null;

  const servedLabel = ZONE_SERVED_LABEL[briefing.served_zone];
  const requested = ZONE_REQUESTED_LABEL[briefing.zone];
  // Defense against a malformed data/briefings/**/*.json (partial write,
  // hand-edit, future pipeline bug): loadBriefing does no schema
  // validation, and this function runs unconditionally for every
  // statically-generated page at build time -- an uncaught crash here would
  // fail the whole `astro build`, not just one page. Today's pipeline logic
  // only ever produces zone/served_zone pairs both tables cover, but this
  // function must not assume that holds for every byte on disk.
  if (!servedLabel || !requested) return null;

  const verb = requested.plural ? "n'ont" : "n'a";
  return `Affichage de ${servedLabel} — ${requested.label} ${verb} pas assez de couverture aujourd'hui.`;
}

/**
 * The End Screen's completion statement (FR-5, UX-DR8), or `null` when
 * there is nothing to declare complete (0 items -- a real, already-observed
 * state per Story 4.1's AC6 empty-clusters case; no UX spec defines what
 * this sentence should say for zero items, so the End Screen is suppressed
 * entirely rather than inventing copy). Reuses periodSentenceText's exact
 * wording (not a separate copy) so the End Screen's period phrase and the
 * mad-libs Period word never drift. French noun/verb agreement changes
 * with the item count ("1 sujet a atteint..." vs "N sujets ont atteint..."
 * for N > 1) -- the same class of singular/plural agreement
 * fallbackNoticeText already handles for "les États-Unis".
 */
export function endScreenText(itemCount: number, period: Period): string | null {
  if (itemCount === 0) return null;

  const noun = itemCount === 1 ? "sujet" : "sujets";
  const verb = itemCount === 1 ? "a" : "ont";
  return `Vous avez atteint la fin. ${itemCount} ${noun} ${verb} atteint le seuil ${periodSentenceText(period)}.`;
}
