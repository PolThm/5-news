import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { copyBriefingsToPublic } from "../copy-briefings-to-public";

describe("copyBriefingsToPublic", () => {
  let siteRoot: string;

  beforeEach(() => {
    siteRoot = mkdtempSync(join(tmpdir(), "copy-briefings-test-"));
    mkdirSync(join(siteRoot, "src", "fixtures"), { recursive: true });
  });

  afterEach(() => {
    rmSync(siteRoot, { recursive: true, force: true });
  });

  it("writes each combination's Briefing to public/briefings/<lang>/<zone>/<period>.json", () => {
    writeFileSync(
      join(siteRoot, "src", "fixtures", "day.json"),
      JSON.stringify({ schema_version: 1, period: "day", clusters: [] })
    );

    copyBriefingsToPublic(siteRoot, [{ lang: "fr", zone: "world", period: "day" }]);

    const destination = join(siteRoot, "public", "briefings", "fr", "world", "day.json");
    expect(existsSync(destination)).toBe(true);
    const written = JSON.parse(readFileSync(destination, "utf-8"));
    expect(written.period).toBe("day");
  });

  it("creates every intermediate directory that doesn't exist yet", () => {
    writeFileSync(
      join(siteRoot, "src", "fixtures", "month.json"),
      JSON.stringify({ schema_version: 1, period: "month", clusters: [] })
    );

    copyBriefingsToPublic(siteRoot, [{ lang: "es", zone: "brazil", period: "month" }]);

    expect(existsSync(join(siteRoot, "public", "briefings", "es", "brazil", "month.json"))).toBe(
      true
    );
  });

  it("writes valid, re-parseable JSON even when the source came from the fixture fallback", () => {
    writeFileSync(
      join(siteRoot, "src", "fixtures", "week.json"),
      JSON.stringify({ schema_version: 1, period: "week", clusters: [{ cluster_id: "x" }] })
    );

    copyBriefingsToPublic(siteRoot, [{ lang: "fr", zone: "world", period: "week" }]);

    const written = JSON.parse(
      readFileSync(join(siteRoot, "public", "briefings", "fr", "world", "week.json"), "utf-8")
    );
    expect(written.clusters).toEqual([{ cluster_id: "x" }]);
  });

  it("processes every combination in the provided list, not just the first", () => {
    writeFileSync(
      join(siteRoot, "src", "fixtures", "day.json"),
      JSON.stringify({ schema_version: 1, period: "day", clusters: [] })
    );
    writeFileSync(
      join(siteRoot, "src", "fixtures", "week.json"),
      JSON.stringify({ schema_version: 1, period: "week", clusters: [] })
    );

    copyBriefingsToPublic(siteRoot, [
      { lang: "fr", zone: "world", period: "day" },
      { lang: "fr", zone: "world", period: "week" },
    ]);

    expect(existsSync(join(siteRoot, "public", "briefings", "fr", "world", "day.json"))).toBe(
      true
    );
    expect(existsSync(join(siteRoot, "public", "briefings", "fr", "world", "week.json"))).toBe(
      true
    );
  });
});
