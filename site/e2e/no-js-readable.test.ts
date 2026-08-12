import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

// AC4: the Briefing content is readable with JavaScript unavailable. Proven
// here by building the real static output and asserting on the HTML
// directly, rather than driving a real browser with JS disabled (Playwright).
//
// Story 4.2 adds real client-side interactivity (the Period-switcher
// island), but the no-JS proof this suite exists for doesn't change: content
// and every mad-libs word's href are still fully present and correct in the
// server-rendered HTML with zero script execution -- these are static-HTML
// assertions, not a running browser. Introducing Playwright now, for one
// click handler, would be a disproportionate new dependency for a solo
// project; period-switcher.ts's pure functions (URL/text computation) are
// unit-tested directly instead (see islands/__tests__/period-switcher.test.ts),
// and its DOM-touching `attach()`/`handleClick()` are exercised only by
// manual verification in this story (see Dev Notes). Revisit Playwright if a
// future story needs to assert real click-driven DOM mutation in a browser.

const SITE_ROOT = join(__dirname, "..");
const DIST_INDEX = join(SITE_ROOT, "dist", "index.html");

describe("no-JS readability of the built page", () => {
  let html: string;

  beforeAll(() => {
    execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });
    expect(existsSync(DIST_INDEX)).toBe(true);
    html = readFileSync(DIST_INDEX, "utf-8");
  });

  it("ships exactly one <script> tag, the Period-switcher island (progressive enhancement only)", () => {
    const scriptTags = html.match(/<script[^>]*>/gi) ?? [];
    expect(scriptTags).toHaveLength(1);
    // Astro inlines the module's compiled body directly rather than an
    // external src="..." reference (see the built output) -- assert on a
    // symbol from the island's own compiled code instead of a filename.
    expect(html).toContain("data-period-word");
    expect(html).toMatch(/briefings\/\$\{|\/briefings\//);
  });

  it("renders the Period word as a real <a href> to the equivalent static route, not a placeholder", () => {
    expect(html).toMatch(
      /<a class="word" data-period-word data-lang="fr" data-zone="world" data-period="day" href="\/fr\/world\/week"[^>]*>aujourd&#39;hui<\/a>/
    );
  });

  it("includes every item's Summary text as plain HTML content", () => {
    expect(html).toContain("Un cessez-le-feu entre en vigueur");
  });

  it("includes the Consensus figures as plain HTML content", () => {
    expect(html).toMatch(/<span class="num"[^>]*>7<\/span> sources/);
  });

  it("includes the outbound attribution link as a real <a href>, not a placeholder", () => {
    expect(html).toMatch(/<a href="https:\/\/reuters\.com\/[^"]*"[^>]*>lire l'article original/);
  });

  it("renders the mad-libs sentence's fixed lead-in as static text", () => {
    expect(html).toContain("Voici ce qui se passe");
  });

  it("renders the Zone word as a real <a href> to the equivalent static route, not a placeholder", () => {
    expect(html).toMatch(
      /<a class="word" data-zone-word data-lang="fr" data-zone="world" data-period="day" href="\/fr\/europe\/day"[^>]*>dans le Monde<\/a>/
    );
  });
});

// Story 4.3: the Zone axis extends beyond World to Continents and
// Countries, and introduces the Continent-fallback notice (FR-16, AC3/AC4).
// Same no-JS build-and-assert discipline as the describe block above.
//
// Each `it` below builds for itself rather than sharing one `beforeAll`
// build across the block -- this file also has an AC3 block (below) and an
// AC6 block that each temporarily mutate src/fixtures/day.json (every
// Zone's day-period fixture-fallback source) and rebuild; a `beforeAll`
// here raced against those mutations in an earlier version of this file,
// so every `it` that inspects `dist/` now performs its own build against
// the fixtures as they stand at that exact moment, eliminating the race
// rather than relying on describe-block ordering.
describe("Zone axis: Continent and Country pages (Story 4.3)", () => {
  const DIST_EUROPE_DAY = join(SITE_ROOT, "dist", "fr", "europe", "day.html");
  const DIST_JAPAN_DAY = join(SITE_ROOT, "dist", "fr", "japan", "day.html");

  it("builds a Continent page (Europe) with the correct sentence label and Zone-word target", () => {
    execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });
    const html = readFileSync(DIST_EUROPE_DAY, "utf-8");
    expect(html).toMatch(
      /<a class="word" data-zone-word data-lang="fr" data-zone="europe" data-period="day" href="\/fr\/north-america\/day"[^>]*>en Europe<\/a>/
    );
  });

  it("builds a Country page (Japan) with the correct sentence label and Zone-word target, and no fallback notice (AC4)", () => {
    execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });
    const html = readFileSync(DIST_JAPAN_DAY, "utf-8");
    expect(html).toMatch(
      /<a class="word" data-zone-word data-lang="fr" data-zone="japan" data-period="day" href="\/fr\/china\/day"[^>]*>au Japon<\/a>/
    );

    // Strip both <style> (the .fallback-notice CSS rule, always present)
    // and <script> (the island's own compiled source, which carries the
    // literal string `id="fallback-notice"` as part of its template-literal
    // rendering logic, unrelated to whether an element was actually
    // server-rendered -- the exact same false-positive class as AC6's
    // `class="item"` check below).
    const htmlWithoutStyleOrScript = html
      .replace(/<style[\s\S]*?<\/style>/gi, "")
      .replace(/<script[\s\S]*?<\/script>/gi, "");
    expect(htmlWithoutStyleOrScript).not.toContain('id="fallback-notice"');
  });
});

// AC3: the Continent-fallback notice, actually rendered in a real build by
// temporarily substituting france/day.json's fixture-fallback content with
// fallback-example.json (zone: france / served_zone: europe) -- no route's
// normal data ever has zone != served_zone today (see Task 3's Dev Notes
// decision not to entangle the general Zone fixtures with this one-off
// case), so this test creates that condition itself, the same way the AC6
// describe block below temporarily empties day.json's clusters. Same
// crash-safety discipline as that block: .bak written before mutation,
// restore in try/finally inside the `it` block itself, mutate/build/assert/
// restore all within the one `it` (no shared `beforeAll`) so this block's
// build can never race another block's fixture state.
describe("Continent-fallback notice (AC3)", () => {
  const FIXTURE_PATH = join(SITE_ROOT, "src", "fixtures", "day.json");
  const BACKUP_PATH = `${FIXTURE_PATH}.ac3.bak`;
  const FALLBACK_EXAMPLE_PATH = join(SITE_ROOT, "src", "fixtures", "fallback-example.json");
  const originalFixture = readFileSync(FIXTURE_PATH, "utf-8");
  writeFileSync(BACKUP_PATH, originalFixture);

  afterAll(() => {
    if (existsSync(BACKUP_PATH)) rmSync(BACKUP_PATH);
  });

  it("renders the exact French sentence with the secondary color styling for a fallback Briefing", () => {
    const fallbackContent = readFileSync(FALLBACK_EXAMPLE_PATH, "utf-8");
    writeFileSync(FIXTURE_PATH, fallbackContent);

    try {
      execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });

      const html = readFileSync(join(SITE_ROOT, "dist", "fr", "france", "day.html"), "utf-8");
      expect(html).toMatch(
        /<div class="fallback-notice" id="fallback-notice"[^>]*>Affichage de l&#39;Europe — la France n&#39;a pas assez de couverture aujourd&#39;hui\.<\/div>/
      );
      expect(html).toMatch(/\.fallback-notice[^{]*\{[^}]*color:#8a3a2b/);
      expect(html).toMatch(/\.fallback-notice[^{]*\{[^}]*background:#f6dcd4/);
    } finally {
      writeFileSync(FIXTURE_PATH, originalFixture);
      // Rebuild once more with the restored fixture so dist/ never reflects
      // this test's temporary mutation for whichever test runs next (the
      // real fix for the cross-block contamination this story's own review
      // caught -- restoring the source file isn't enough on its own if a
      // later test only reads a stale dist/ build instead of building
      // fresh itself, so both disciplines now apply together).
      execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });
    }
  });
});

// AC6: an empty `clusters` array is a real, already-observed case (a real
// cycle run during this project produced zero qualifying Clusters) -- the
// build must not crash, and the header/sentence must still render.
//
// This mutates a real, tracked file (the fixture doubles as both the local
// dev fixture and the production fallback -- see the story's Dev Notes) --
// so restoration is not left to `afterAll` alone (vitest's own hook
// lifecycle is application-level, not OS-guaranteed against a hard process
// kill mid-test). A `.bak` file is written to disk *before* any mutation,
// outside any hook, and restoration is wrapped in try/finally inside the
// `it` block itself so a failing assertion still restores before the test
// exits. If this process is ever killed hard enough to skip even the
// `finally`, the `.bak` file survives on disk as a manual recovery path.
describe("empty clusters array (AC6)", () => {
  const FIXTURE_PATH = join(SITE_ROOT, "src", "fixtures", "day.json");
  const BACKUP_PATH = `${FIXTURE_PATH}.bak`;
  const originalFixture = readFileSync(FIXTURE_PATH, "utf-8");
  writeFileSync(BACKUP_PATH, originalFixture);

  afterAll(() => {
    // Belt-and-suspenders: the `it` block's own try/finally already
    // restores on the success/failure paths vitest can see; this cleans
    // up the backup file once we know it's no longer needed.
    if (existsSync(BACKUP_PATH)) rmSync(BACKUP_PATH);
  });

  it("builds successfully and still renders the header and sentence", () => {
    const emptyRecord = { ...JSON.parse(originalFixture), clusters: [] };
    writeFileSync(FIXTURE_PATH, JSON.stringify(emptyRecord));

    try {
      expect(() =>
        execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" })
      ).not.toThrow();

      const html = readFileSync(DIST_INDEX, "utf-8");
      expect(html).toContain("5 NEWS");
      expect(html).toContain("Voici ce qui se passe");
      // Strip the inlined island's <script> body before this check -- its
      // compiled source contains the literal string `class="item"` as part
      // of the item-rendering template it carries for later client-side use
      // (Story 4.2), which is unrelated to whether any .item div was
      // actually server-rendered onto the page.
      const htmlWithoutScripts = html.replace(/<script[\s\S]*?<\/script>/gi, "");
      expect(htmlWithoutScripts).not.toMatch(/class="item"[ >]/);
    } finally {
      writeFileSync(FIXTURE_PATH, originalFixture);
    }
  });
});
