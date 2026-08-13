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

// Astro inlines the island's compiled JS directly into a <script> tag when
// the bundle is small, but switches to an external src="..." reference once
// the bundle crosses its own internal size threshold (observed when Story
// 4.5 grew period-switcher.ts with the chip-toggle logic) -- which mode it
// picks is Astro's own bundler decision, not something this codebase
// controls or should assume either way. When inlined, that JS's own
// template-literal rendering logic contains literal strings (`<div
// class="item">`, `id="fallback-notice"`, etc.) that collide with a naive
// presence/count check meant to inspect only server-rendered content; when
// externalized, the <script> tag is self-closing and carries no such text
// at all. Stripping any <script>...</script> *pair* handles the inlined
// case; a self-closing external <script src="..."/> has no closing tag for
// that regex to match, so it's left alone -- correctly, since it contributes
// no false-positive text either way.
function stripInlineScript(html: string): string {
  return html.replace(/<script[\s\S]*?<\/script>/gi, "");
}

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
    const scriptTag = scriptTags[0];
    if (!scriptTag) throw new Error("unreachable: length asserted above");
    // Whether Astro inlines the compiled module or emits an external
    // src="..." reference is its own bundler-size decision (see this
    // file's stripInlineScript docstring) -- assert on whichever form
    // is present, not on inlining specifically.
    const isExternal = /<script[^>]+src=/i.test(scriptTag);
    if (isExternal) {
      const srcMatch = scriptTag.match(/src="([^"]+)"/);
      if (!srcMatch) throw new Error("external <script> tag has no src attribute");
      const scriptPath = join(SITE_ROOT, "dist", srcMatch[1]);
      expect(existsSync(scriptPath)).toBe(true);
      const scriptContent = readFileSync(scriptPath, "utf-8");
      expect(scriptContent).toContain("data-period-word");
      expect(scriptContent).toMatch(/briefings\/\$\{|\/briefings\//);
    } else {
      expect(html).toContain("data-period-word");
      expect(html).toMatch(/briefings\/\$\{|\/briefings\//);
    }
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

  it("renders the End Screen with the outline-variant hairline and the correct item-count/period completion statement (AC2)", () => {
    expect(html).toMatch(/\.rule[^{]*\{[^}]*background:#cac5b8/);
    // day.json has 4 clusters, day period -> plural French grammar.
    expect(html).toContain("Vous avez atteint la fin. 4 sujets ont atteint le seuil aujourd&#39;hui.");
  });

  it("renders nothing after the End Screen (AC2's 'nothing further' clause)", () => {
    // The End Screen's own <p> completion statement must be the last piece
    // of real page content before the .page container closes and the
    // island's <script> tag begins -- i.e. only the End Screen's own
    // closing tags (</p></div>) and the .page/.body/.html closings separate
    // it from <script>, with no other element's opening tag in between.
    const endScreenIndex = html.indexOf('id="end-screen"');
    expect(endScreenIndex).toBeGreaterThan(-1);

    const afterEndScreen = html.slice(endScreenIndex);
    const beforeScript = afterEndScreen.slice(0, afterEndScreen.indexOf("<script"));
    // Only the rule div, the <p>, and their own closing tags should appear
    // -- no further <div>/<span>/<a> opening tag past the <p> itself.
    const afterCompletionStatement = beforeScript.slice(beforeScript.indexOf("</p>") + "</p>".length);
    expect(afterCompletionStatement).not.toMatch(/<(div|span|a|p|h1|ul|li)[ >]/);
  });

  it("renders the Discarded Volume once, at the foot of the item list, with French-locale-formatted counts (AC2)", () => {
    expect(html).toMatch(
      /<div class="discarded" id="discarded"[^>]*><span class="num"[^>]*>1 384<\/span> articles examinés → <span class="num"[^>]*>4<\/span> conservés\.<\/div>/
    );
    expect((html.match(/id="discarded"/g) ?? []).length).toBe(1);
  });

  it("renders the Consensus chip as a real <button> with its source list already present and visible in the initial HTML (AC3, no-JS)", () => {
    const htmlWithoutScripts = stripInlineScript(html);
    expect(htmlWithoutScripts).toMatch(
      /<button type="button" class="chip" aria-expanded="false" aria-controls="source-list-ceasefire-2026-08-11"[^>]*data-consensus-chip[^>]*>/
    );
    // Present and NOT hidden -- no js-collapsed class -- in the
    // server-rendered HTML, since a no-JS reader must see it already
    // expanded (this story's own Scope decision: only the client-side
    // island collapses it, and that never executes without JS).
    expect(htmlWithoutScripts).toMatch(
      /<div class="source-list" id="source-list-ceasefire-2026-08-11"[^>]*>(?!.*js-collapsed)/
    );
  });

  it("has exactly as many source-list entries as the chip's own displayed independent_source_count, for every item (AC3's hard guarantee)", () => {
    // day.json's 4 clusters, after Task 1's fixture fix: 7, 5, 4, 3.
    const expectedCounts = [7, 5, 4, 3];
    const sourceListBlocks = stripInlineScript(html).match(
      /<div class="source-list"[^>]*>.*?<\/div>/gs
    );
    expect(sourceListBlocks).toHaveLength(4);
    sourceListBlocks!.forEach((block, index) => {
      const liCount = (block.match(/<li[ >]/g) ?? []).length;
      expect(liCount).toBe(expectedCounts[index]);
    });
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
    const htmlWithoutStyleOrScript = stripInlineScript(html).replace(
      /<style[\s\S]*?<\/style>/gi,
      ""
    );
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

// Story 4.4: AC1 (variable item count, no placeholders) and AC3 (a single
// dominating item's block is content-driven height, not capped). This
// describe block only verifies -- BriefingPage.astro's item-list rendering
// is already a bare `.map()` with no fixed count or placeholder logic, so
// these are proving an existing property, not exercising new code, except
// for the "no height/overflow constraint" CSS check.
describe("variable item count (AC1, AC3)", () => {
  const FIXTURE_PATH = join(SITE_ROOT, "src", "fixtures", "day.json");
  const BACKUP_PATH = `${FIXTURE_PATH}.ac1ac3.bak`;
  const SINGLE_ITEM_PATH = join(SITE_ROOT, "src", "fixtures", "single-item-example.json");
  const originalFixture = readFileSync(FIXTURE_PATH, "utf-8");
  writeFileSync(BACKUP_PATH, originalFixture);

  afterAll(() => {
    if (existsSync(BACKUP_PATH)) rmSync(BACKUP_PATH);
  });

  it("renders exactly as many .item divs as clusters exist, for 3 and 4 clusters (existing fixtures)", () => {
    execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });

    const dayHtml = readFileSync(DIST_INDEX, "utf-8"); // day.json: 4 clusters
    const weekHtml = readFileSync(join(SITE_ROOT, "dist", "fr", "world", "week.html"), "utf-8"); // week.json: 3 clusters

    // Count only server-rendered .item divs -- the island's own inlined
    // <script> source carries the literal string `<div class="item">` as
    // part of its client-side rendering template (renderItemListHtml),
    // which would otherwise inflate this count by 1 regardless of the real
    // server-rendered total (the same false-positive class Story 4.2/4.3
    // already hit for `class="item"`/`id="fallback-notice"` -- strip
    // <script> first, every time this pattern is checked).
    const countItems = (html: string) =>
      (stripInlineScript(html).match(/<div class="item"/g) ?? []).length;
    expect(countItems(dayHtml)).toBe(4);
    expect(countItems(weekHtml)).toBe(3);
  });

  it("renders exactly 1 .item div, with no height/overflow constraint, for a single-cluster Briefing (AC1, AC3)", () => {
    const singleItemContent = readFileSync(SINGLE_ITEM_PATH, "utf-8");
    writeFileSync(FIXTURE_PATH, singleItemContent);

    try {
      execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });

      const html = readFileSync(DIST_INDEX, "utf-8");
      const htmlWithoutScripts = stripInlineScript(html);
      const itemCount = (htmlWithoutScripts.match(/<div class="item"/g) ?? []).length;
      expect(itemCount).toBe(1);

      // AC3: no placeholder/skeleton markup filling a gap, and the long
      // (~260+ char) Summary is not truncated -- proves AC4's "nothing
      // clips a long Summary" claim concretely, not just by CSS inspection.
      expect(htmlWithoutScripts).not.toMatch(/skeleton|placeholder|loading-more/i);
      expect(html).toContain(
        "Une mission diplomatique de longue haleine aboutit enfin à un accord-cadre"
      );
      expect(html).toContain("dossier sensible.");

      // AC3: no CSS rule caps .item/.item-list height or clips overflow.
      const styleMatch = html.match(/<style[^>]*>([\s\S]*?)<\/style>/);
      const css = styleMatch?.[1] ?? "";
      expect(css).not.toMatch(/\.item(?:-list)?\[[^\]]*\]\s*\{[^}]*(?:max-height|overflow)/);
    } finally {
      writeFileSync(FIXTURE_PATH, originalFixture);
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
      const htmlWithoutScripts = stripInlineScript(html);
      expect(htmlWithoutScripts).not.toMatch(/class="item"[ >]/);
      // Story 4.4's own Blind Hunter review caught a real bug here: the End
      // Screen originally rendered unconditionally, producing a
      // nonsensical "0 sujets ont atteint le seuil..." for this exact
      // input. It must be suppressed entirely for 0 clusters, not just
      // avoid crashing.
      expect(htmlWithoutScripts).not.toContain('id="end-screen"');
      // Story 4.5's own Blind Hunter review flagged this combination
      // (Discarded Volume + 0 clusters together) as claimed-tested but
      // not actually exercised by any test -- Discarded Volume renders
      // unconditionally (AC2), independent of item count, so it must
      // still appear here using discarded_ingested/discarded_kept's own
      // (unchanged, non-zero) values from the mutated fixture.
      expect(htmlWithoutScripts).toMatch(
        /<div class="discarded" id="discarded"[^>]*><span class="num"[^>]*>1 384<\/span> articles examinés → <span class="num"[^>]*>4<\/span> conservés\.<\/div>/
      );
    } finally {
      writeFileSync(FIXTURE_PATH, originalFixture);
    }
  });

  it("renders the Discarded Volume correctly for the real 0 ingested / 0 kept case, combined with 0 clusters", () => {
    // The real, currently-shipped pipeline always produces 0/0 for these
    // two fields (no stage populates them yet) -- this is the actual
    // production state, tested here together with 0 clusters since both
    // conditions are independent and both are real today.
    const emptyRecord = {
      ...JSON.parse(originalFixture),
      clusters: [],
      discarded_ingested: 0,
      discarded_kept: 0,
    };
    writeFileSync(FIXTURE_PATH, JSON.stringify(emptyRecord));

    try {
      execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });

      const html = readFileSync(DIST_INDEX, "utf-8");
      const htmlWithoutScripts = stripInlineScript(html);
      expect(htmlWithoutScripts).toMatch(
        /<div class="discarded" id="discarded"[^>]*><span class="num"[^>]*>0<\/span> articles examinés → <span class="num"[^>]*>0<\/span> conservés\.<\/div>/
      );
      expect(htmlWithoutScripts).not.toContain('id="end-screen"');
    } finally {
      writeFileSync(FIXTURE_PATH, originalFixture);
    }
  });
});
