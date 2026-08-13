// Story 5.3 (AD-9): reads the checked-in service-worker TEMPLATE
// (public/sw.template.js), substitutes its __CACHE_VERSION__ placeholder
// with the current cycle's sanitized generated_at, and writes the result
// to public/sw.js -- gitignored, regenerated every build, exactly the
// same "pre-build Node script rewrites a public/-destined file" pattern
// already established by copy-briefings-to-public.ts.
//
// The stamped identifier is derived ONLY from generated_at (cycle-
// derived), never from a build timestamp (deploy-derived) -- see this
// story's own Dev Notes on why: a build timestamp would make every
// rebuild look like a new cycle to a reader's browser, forcing an
// unnecessary cache-clear on every deploy regardless of whether the
// underlying content actually changed.
//
// Reads the same "canonical" Briefing (fr/world/day) that
// copy-briefings-to-public.ts and index.astro both already treat as the
// site's own reference point, via the same loadBriefing real-path/
// fixture-fallback resolution -- no new path-resolution convention
// introduced here.
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadBriefing } from "../src/lib/loadBriefing.ts";
import { sanitizeCacheVersion } from "../src/islands/sw-logic.ts";

export function stampServiceWorker(siteRoot: string): void {
  const realPath = join(siteRoot, "..", "data", "briefings", "fr", "world", "day.json");
  const fixturePath = join(siteRoot, "src", "fixtures", "day.json");
  const briefing = loadBriefing(realPath, fixturePath);

  const cacheVersion = sanitizeCacheVersion(briefing.generated_at);

  const templatePath = join(siteRoot, "public", "sw.template.js");
  const template = readFileSync(templatePath, "utf-8");
  const stamped = template.replace(/__CACHE_VERSION__/g, cacheVersion);

  if (stamped.includes("__CACHE_VERSION__")) {
    throw new Error(
      "stampServiceWorker: __CACHE_VERSION__ placeholder still present after substitution -- " +
        "check that sw.template.js's own token spelling matches this script's replace() pattern."
    );
  }

  const destination = join(siteRoot, "public", "sw.js");
  writeFileSync(destination, stamped, "utf-8");
}

// Invoked directly when run as a script from package.json's build step,
// not just imported for testing -- same isDirectRun convention as
// copy-briefings-to-public.ts.
const isDirectRun = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isDirectRun) {
  stampServiceWorker(process.cwd());
}
