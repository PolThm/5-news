import { existsSync, readFileSync } from "node:fs";
import type { BriefingRecord } from "./briefing";

/**
 * Read a published Briefing JSON file at build time.
 *
 * `realPath` is the pipeline's real output path
 * (`data/briefings/<lang>/<zone>/<period>.json`). `fixturePath` is a
 * committed fallback used when that file doesn't exist yet -- the real
 * production state today: `data/briefings/` contains only `.gitkeep`,
 * because no non-degraded scheduled cycle has run yet. This is a real
 * fallback behavior, not a test-only shim: it keeps `astro build`/`astro
 * dev` working before the pipeline has ever produced real output, and
 * continues to degrade gracefully if a future cycle run is ever missing
 * for some reason.
 *
 * Never reads across the pipeline/site boundary in the forbidden sense
 * (`scripts/check-boundary.sh`) -- both paths are supplied by the caller,
 * this function only reads whichever one exists.
 */
export function loadBriefing(realPath: string, fixturePath: string): BriefingRecord {
  const path = existsSync(realPath) ? realPath : fixturePath;

  let raw: string;
  try {
    raw = readFileSync(path, "utf-8");
  } catch (cause) {
    throw new Error(
      `loadBriefing: could not read "${path}" (checked real path "${realPath}", ` +
        `then fixture "${fixturePath}"): ${(cause as Error).message}`,
      { cause }
    );
  }

  try {
    return JSON.parse(raw) as BriefingRecord;
  } catch (cause) {
    throw new Error(
      `loadBriefing: "${path}" is not valid JSON -- refusing to render a Briefing ` +
        `from a possibly-truncated or corrupt file: ${(cause as Error).message}`,
      { cause }
    );
  }
}
