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

  it("renders the mad-libs sentence as static text", () => {
    expect(html).toContain("Voici ce qui se passe dans");
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
      expect(html).toContain("Voici ce qui se passe dans");
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
