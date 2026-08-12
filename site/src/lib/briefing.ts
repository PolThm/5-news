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
