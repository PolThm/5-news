// Exposes each Briefing JSON (real or fixture-fallback, matching
// loadBriefing's own resolution) as a fetchable static asset under
// site/public/briefings/<lang>/<zone>/<period>.json -- Astro serves
// everything under public/ verbatim at the site root, so the client
// island (period-switcher.ts) can `fetch("/briefings/fr/world/week.json")`
// and get exactly the same data the corresponding page was statically
// rendered from (EXPERIENCE.md: "no network round-trip beyond fetching
// that one file").
//
// A plain pre-build script (invoked via package.json's `build` script,
// before `astro build`) rather than a custom Astro integration hook --
// simplest mechanism that does the job for a solo project's small,
// fixed combination list; revisit only if this list ever grows large
// enough that a build-time integration hook becomes clearly better.
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { ZONE_CYCLE } from "../src/lib/briefing.ts";
import { loadBriefing } from "../src/lib/loadBriefing.ts";

export interface Combination {
  lang: string;
  zone: string;
  period: string;
}

const PERIODS = ["day", "week", "month"];

// Cross product of all 15 Zones (Story 4.3, reusing briefing.ts's own
// ZONE_CYCLE rather than a third hand-duplicated copy of the same list --
// [lang]/[zone]/[period].astro's getStaticPaths does the same) x all 3
// Periods x fr (Story 4.7 extends the Language axis). Both this list and
// that route file's getStaticPaths must stay in sync by hand (see that
// route file's own comment) since neither can import the other.
export const COMBINATIONS: Combination[] = ZONE_CYCLE.flatMap((zone) =>
  PERIODS.map((period) => ({ lang: "fr", zone, period }))
);

export function copyBriefingsToPublic(
  siteRoot: string,
  combinations: Combination[] = COMBINATIONS
): void {
  for (const { lang, zone, period } of combinations) {
    const realPath = join(siteRoot, "..", "data", "briefings", lang, zone, `${period}.json`);
    const fixturePath = join(siteRoot, "src", "fixtures", `${period}.json`);
    const briefing = loadBriefing(realPath, fixturePath);

    const destination = join(siteRoot, "public", "briefings", lang, zone, `${period}.json`);
    const destinationDir = dirname(destination);
    if (!existsSync(destinationDir)) {
      mkdirSync(destinationDir, { recursive: true });
    }

    // Write the *loaded* (and therefore validated-as-parseable) content,
    // not a raw file copy -- this guarantees the exposed asset is always
    // valid JSON matching BriefingRecord's shape, even when it came from
    // the fixture fallback rather than a real file.
    writeFileSync(destination, JSON.stringify(briefing), "utf-8");
  }
}

// Invoked directly when run as a script from package.json's build step,
// not just imported for testing. import.meta.url comparison is the ESM
// equivalent of CommonJS's `require.main === module` -- this project's
// package.json is "type": "module".
const isDirectRun = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isDirectRun) {
  copyBriefingsToPublic(process.cwd());
}
