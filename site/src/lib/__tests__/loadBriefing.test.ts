import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { loadBriefing } from "../loadBriefing";
import type { BriefingRecord } from "../briefing";

// A well-formed BriefingRecord fixture, built inline rather than reused from
// src/fixtures/day.json -- these tests exercise the loader's own fallback
// logic against paths it never touches in real dev/build usage, so a
// throwaway temp directory keeps them independent of that fixture's content.
function record(overrides: Partial<BriefingRecord> = {}): BriefingRecord {
  return {
    schema_version: 1,
    zone: "world",
    zone_kind: "world",
    zone_continent: null,
    served_zone: "world",
    served_zone_kind: "world",
    served_zone_continent: null,
    period: "day",
    language: "fr",
    clusters: [],
    discarded_ingested: 0,
    discarded_kept: 0,
    generated_at: "2026-08-11T06:00:00+00:00",
    ...overrides,
  };
}

describe("loadBriefing", () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "briefing-test-"));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("reads a well-formed real file when it exists", () => {
    const target = record({
      clusters: [
        {
          cluster_id: "a",
          members: [],
          independent_source_count: 3,
          country_count: 2,
          countries: ["france", "germany"],
          origin_country: "france",
          rank: 1,
          summary: "Un résumé.",
          outbound_url: "https://example.com/a",
          outbound_source: "example.com",
        },
      ],
    });
    writeFileSync(join(dir, "day.json"), JSON.stringify(target));

    const result = loadBriefing(join(dir, "day.json"), join(dir, "fixture.json"));

    expect(result.clusters).toHaveLength(1);
    expect(result.clusters[0].cluster_id).toBe("a");
  });

  it("falls back to the fixture path when the real file is missing", () => {
    const fixture = record({ zone: "world", period: "day" });
    writeFileSync(join(dir, "fixture.json"), JSON.stringify(fixture));

    const result = loadBriefing(join(dir, "does-not-exist.json"), join(dir, "fixture.json"));

    expect(result.zone).toBe("world");
  });

  it("returns an empty clusters array as-is, not an error", () => {
    const target = record({ clusters: [] });
    writeFileSync(join(dir, "day.json"), JSON.stringify(target));

    const result = loadBriefing(join(dir, "day.json"), join(dir, "fixture.json"));

    expect(result.clusters).toEqual([]);
  });

  it("throws when neither the real file nor the fixture exists", () => {
    expect(() =>
      loadBriefing(join(dir, "does-not-exist.json"), join(dir, "also-missing.json"))
    ).toThrow();
  });

  it("preserves a cluster missing outbound_url/outbound_source entirely", () => {
    const target = record({
      clusters: [
        {
          cluster_id: "no-link",
          members: [],
          independent_source_count: 2,
          country_count: 2,
          countries: ["china", "germany"],
          origin_country: "germany",
          rank: 1,
        },
      ],
    });
    writeFileSync(join(dir, "day.json"), JSON.stringify(target));

    const result = loadBriefing(join(dir, "day.json"), join(dir, "fixture.json"));

    expect(result.clusters[0].outbound_url).toBeUndefined();
    expect(result.clusters[0].summary).toBeUndefined();
  });

  it("throws a descriptive error on malformed JSON rather than a bare parse error", () => {
    writeFileSync(join(dir, "day.json"), "{ this is not valid JSON");

    expect(() => loadBriefing(join(dir, "day.json"), join(dir, "fixture.json"))).toThrow(
      /not valid JSON/
    );
  });
});
