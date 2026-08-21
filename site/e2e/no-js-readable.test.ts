import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
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

// This whole file's premise is `loadBriefing`'s fixture fallback (see its own
// docstring): every `it` below builds against `src/fixtures/*.json` and
// asserts on that fixture's exact, known content. That fallback only fires
// when `data/briefings/<lang>/<zone>/<period>.json` -- the pipeline's real
// output -- does NOT exist for a given route. It didn't, for any route,
// until the first real cycle published on 2026-08-14; every cycle since
// (most recently 2026-08-18) has grown that tree to cover all 24 routes, so
// a normal checkout now has real data everywhere and this suite was silently
// asserting on ever-changing cycle content instead of the fixtures it was
// written against -- correct in principle (`loadBriefing` does exactly what
// its docstring says), wrong for a suite whose entire point is a controlled,
// known input.
//
// Renaming the real directory aside for this file's duration -- rather than
// rewriting every assertion to tolerate arbitrary cycle content, which would
// defeat the point of asserting exact strings/counts at all -- restores that
// controlled input without changing `loadBriefing` or either page's
// production fallback behavior. Same backup-before-mutate, restore-in-
// finally discipline already used below for the fixture files themselves;
// scoped to this file only via one top-level beforeAll/afterAll rather than
// per-`it`, since every build in this file needs the same isolation and
// nothing here ever wants the real data.
const REAL_BRIEFINGS_DIR = join(SITE_ROOT, "..", "data", "briefings");
const REAL_BRIEFINGS_MOVED_ASIDE = `${REAL_BRIEFINGS_DIR}.e2e-hidden`;

beforeAll(() => {
  if (existsSync(REAL_BRIEFINGS_DIR)) {
    renameSync(REAL_BRIEFINGS_DIR, REAL_BRIEFINGS_MOVED_ASIDE);
  }
});

afterAll(() => {
  if (existsSync(REAL_BRIEFINGS_MOVED_ASIDE)) {
    renameSync(REAL_BRIEFINGS_MOVED_ASIDE, REAL_BRIEFINGS_DIR);
  }
});

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

// Astro inlines the page's compiled CSS directly into a <style> tag when
// the stylesheet is small, but switches to an external
// <link rel="stylesheet" href="..."> reference once it crosses its own
// internal size threshold (observed when Story 4.8 added new
// :focus-visible/aria-live rules) -- the same bundler-size decision
// already documented above for the island's own JS, now also applying to
// CSS. Resolves to whichever form is actually present so CSS-content
// assertions don't need to assume one or the other.
function resolveCss(html: string): string {
  const inlineMatch = html.match(/<style[^>]*>([\s\S]*?)<\/style>/);
  if (inlineMatch) return inlineMatch[1] ?? "";
  const linkMatch = html.match(/<link rel="stylesheet" href="([^"]+)"/);
  if (!linkMatch) return "";
  const cssPath = join(SITE_ROOT, "dist", linkMatch[1] ?? "");
  return existsSync(cssPath) ? readFileSync(cssPath, "utf-8") : "";
}

describe("no-JS readability of the built page", () => {
  let html: string;

  beforeAll(() => {
    execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });
    expect(existsSync(DIST_INDEX)).toBe(true);
    html = readFileSync(DIST_INDEX, "utf-8");
  }, 30000);

  it("ships exactly three <script> tags on / -- the Period-switcher island, the SW registration, and the opportunistic language-detect redirect (progressive enhancement only)", () => {
    // Story 4.7 (AC1) adds a second script, present only on `/`: the
    // browser-language-detection redirect. Story 5.2 adds a third,
    // present on every page (not /-only): the service-worker
    // registration. All three are progressive enhancement -- none is
    // required to read the page, which the rest of this describe block's
    // assertions prove directly against the server-rendered HTML.
    // Match tag+body pairs by POSITION, not by re-searching for the tag
    // text -- two of the three <script> tags are byte-identical
    // (`<script type="module">` with no distinguishing attribute), so a
    // naive `html.indexOf(tag)` lookup for each would always resolve to
    // the FIRST occurrence for both, silently comparing the same script
    // against itself twice. `matchAll` walks the string once and yields
    // each match's own real position, avoiding that trap entirely.
    const scriptMatches = [...html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/gi)];
    expect(scriptMatches).toHaveLength(3);
    const scripts = scriptMatches.map((m) => ({ tag: `<script${m[1]}>`, body: m[2] ?? "" }));

    // Whether Astro inlines a compiled module or emits an external
    // src="..." reference is its own bundler-size decision (see this
    // file's stripInlineScript docstring), and it re-decides per script
    // as the modules change size -- language-detect crossed that
    // threshold when it grew a preferences import. So resolve every
    // script to its real code first, then tell the three apart by a
    // distinctive marker each one alone contains (navigator.language for
    // the language-detect redirect; navigator.serviceWorker for the SW
    // registration; data-period-word for the Period-switcher island).
    // Marker, not tag position and not inline-ness -- neither is stable.
    const resolved = scripts.map((s) => {
      const srcMatch = s.tag.match(/src="([^"]+)"/);
      if (!srcMatch) return { ...s, code: s.body };
      const scriptPath = join(SITE_ROOT, "dist", srcMatch[1] ?? "");
      expect(existsSync(scriptPath)).toBe(true);
      return { ...s, code: readFileSync(scriptPath, "utf-8") };
    });

    const languageDetect = resolved.find((s) => s.code.includes("navigator.language"));
    expect(languageDetect).toBeDefined();

    const swRegister = resolved.find((s) => s.code.includes("navigator.serviceWorker"));
    expect(swRegister).toBeDefined();

    const periodSwitcher = resolved.find((s) => s.code.includes("data-period-word"));
    if (!periodSwitcher) throw new Error("could not identify the Period-switcher <script> tag");
    // All three must be genuinely distinct tags, not one tag matching
    // several markers because the bundler merged entry points.
    expect(new Set([languageDetect, swRegister, periodSwitcher]).size).toBe(3);
    expect(periodSwitcher.code).toMatch(/briefings\/\$\{|\/briefings\//);
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
    expect(html).toMatch(/<a href="https:\/\/reuters\.com\/[^"]*"[^>]*>lire l&#39;article original/);
  });

  it("opens the outbound attribution link in a new tab with rel=noopener noreferrer (AC1)", () => {
    expect(html).toMatch(
      /<a href="https:\/\/reuters\.com\/[^"]*" target="_blank" rel="noopener noreferrer"[^>]*>lire l&#39;article original/
    );
  });

  it("gives the attribution link a solid underline, distinct from the mad-libs words' dotted underline (AC1, UX-DR9)", () => {
    // Bounded to exactly "underline" with nothing else following before
    // the next `}`/`;` -- an adversarial review caught that a naive
    // negative lookahead for "dotted" doesn't actually work against the
    // real compiled CSS shorthand (`text-decoration:underline 2px dotted
    // #8fc2ac` for the mad-libs word -- "dotted" is two tokens away from
    // "underline", past the lookahead's reach), so this test previously
    // passed for the wrong reason (saved only by the outer `.attribution`
    // selector prefix, not by this assertion's own logic). Assert the
    // property's value is the bare keyword, not merely absent of one
    // specific following word.
    const css = resolveCss(html);
    expect(css).toMatch(/\.attribution[^{]* a[^{]*\{[^}]*text-decoration:underline[;}]/);
    // And confirm the mad-libs word's own rule is NOT bare "underline" --
    // proving this test would actually fail if attribution ever
    // regressed to share that rule's dotted styling.
    expect(css).toMatch(/h1[^{]*\.word[^{]*\{[^}]*text-decoration:underline\s+\S/);
  });

  // The page is rendered twice by two different owners: Astro renders it
  // on the server, and period-switcher.ts rebuilds the item list, fallback
  // notice, Discarded Volume line and End Screen in the browser after every
  // Zone/Period/Language swap. Astro's DEFAULT style scoping silently
  // breaks the second half: it compiles every selector to
  // `.item[data-astro-cid-<hash>]`, matching only what Astro itself
  // stamped, and plain innerHTML in the island cannot reproduce a
  // build-specific hash it has no way to know. Every swapped-in element
  // therefore matched NO rule at all -- item separators vanished, the
  // headline/summary fell back to browser default fonts, and
  // `.source-list{display:none}` stopped applying, so every Consensus
  // source list sprang open and could not be closed again.
  //
  // BriefingPage.astro's `<style is:global>` is what prevents that. This
  // asserts the *outcome* (no scoping attribute survives into any
  // selector) rather than the source spelling, so reverting to a scoped
  // <style> fails here regardless of how the revert is written.
  it("ships styles that match client-rendered markup too, not only Astro-stamped elements", () => {
    const css = resolveCss(html);
    expect(css).not.toContain("data-astro-cid-");

    // Every class period-switcher.ts writes via innerHTML must be
    // reachable by a bare class selector. `source-list` is the one that
    // failed most visibly for the reader (it carries the collapsed-by-
    // default rule directly now, not via a `js-collapsed` modifier
    // class), so it is asserted explicitly rather than left to the loop.
    for (const className of [
      "item",
      "headline",
      "summary",
      "chip",
      "source-list",
      "end-screen",
      "fallback-notice",
      "attribution",
      "num",
      "rule",
    ]) {
      expect(css).toContain(`.${className}`);
    }
    expect(css).toMatch(/\.source-list\{[^}]*display:none/);
  });

  // Story 4.8 (AC1): every interactive element needs a visible
  // :focus-visible style -- an audit before this story found ZERO
  // :focus/:focus-visible/outline rules anywhere in this stylesheet.
  // Astro's data-astro-cid-* scoping attribute is appended to every
  // selector, so `[^{]*` tolerance between the class/selector fragment
  // and the opening `{` is required, per this file's own established
  // pattern for every other CSS assertion.
  it("gives every interactive element type a visible :focus-visible style, never outline:none (AC1)", () => {
    // Astro appends its data-astro-cid-* scoping attribute BETWEEN the
    // selector's own class/tag fragment and any trailing pseudo-class
    // (e.g. `.word[data-astro-cid-72kvvfgf]:focus-visible`, not
    // `.word:focus-visible[data-astro-cid-...]`) -- `[^{]*` tolerance
    // must sit between the fragment and `:focus-visible` itself, not
    // only between `:focus-visible` and the opening `{`.
    const css = resolveCss(html);
    // The two mad-libs Zone/Period words.
    expect(css).toMatch(/\.word[^{]*:focus-visible[^{]*\{[^}]*outline/);
    // The three Output Language options -- Astro's scoping attribute is
    // injected between `.lang` and ` a` too (`.lang[data-astro-cid-...]
    // a[data-astro-cid-...]:focus-visible`), so tolerance is needed there
    // as well, not just before the pseudo-class.
    expect(css).toMatch(/\.lang[^{]*\sa[^{]*:focus-visible[^{]*\{[^}]*outline/);
    // The Consensus chip button.
    expect(css).toMatch(/\.chip[^{]*:focus-visible[^{]*\{[^}]*outline/);
    // The outbound attribution link -- same `.attribution ... a` gap.
    expect(css).toMatch(/\.attribution[^{]*\sa[^{]*:focus-visible[^{]*\{[^}]*outline/);
    // No rule anywhere disables the outline outright.
    expect(css).not.toMatch(/outline:\s*none/);
    expect(css).not.toMatch(/outline:\s*0(?:[;}]|\s)/);
  });

  // Story 4.8 (AC2): a screen-reader-reachable aria-live region, present
  // in the initial server-rendered HTML for every route (not injected
  // only after JS runs), so a screen reader attached before any click
  // already has something to observe.
  it("renders a visually-hidden aria-live=\"polite\" region in the initial HTML (AC2)", () => {
    expect(html).toMatch(/<div id="sr-announcer" aria-live="polite"[^>]*><\/div>/);
    // Visually hidden via clip/absolute positioning, NOT display:none or
    // visibility:hidden -- some screen readers ignore live-region updates
    // on an element hidden that way.
    const css = resolveCss(html);
    expect(css).toMatch(/#sr-announcer[^{]*\{[^}]*position:absolute/);
    expect(css).not.toMatch(/#sr-announcer[^{]*\{[^}]*display:\s*none/);
    expect(css).not.toMatch(/#sr-announcer[^{]*\{[^}]*visibility:\s*hidden/);
  });

  it("renders the attribution span as a sibling after the Consensus chip's source list, never nested inside it, and unconditionally regardless of that item's source-list length (AC1)", () => {
    // The ceasefire cluster (7 members, longest source list) and the
    // trade-agreement cluster (3 members, no attribution at all -- a
    // legitimate degrade case) both come from the same real fixture --
    // this proves attribution rendering is structurally independent of
    // both the chip's own disclosure state and that item's source-list
    // size, not just checked for one convenient case.
    const htmlWithoutScripts = stripInlineScript(html);
    const itemBlocks = htmlWithoutScripts.match(/<div class="item"[^>]*>[\s\S]*?<\/div>(?=<div class="item"|<\/div><div class="discarded")/g);
    expect(itemBlocks).not.toBeNull();

    const ceasefireItem = itemBlocks!.find((block) => block.includes("source-list-ceasefire"));
    expect(ceasefireItem).toBeDefined();
    // The attribution span must appear strictly after the source-list's
    // own closing </div>, never inside it or inside the chip's <button>.
    const sourceListClose = ceasefireItem!.indexOf("</ul></div>");
    const attributionOpen = ceasefireItem!.indexOf('<span class="attribution"');
    expect(sourceListClose).toBeGreaterThan(-1);
    expect(attributionOpen).toBeGreaterThan(sourceListClose);
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
    expect(resolveCss(html)).toMatch(/\.rule[^{]*\{[^}]*background:#cac5b8/);
    // day.json has 4 clusters, day period -> plural French grammar.
    expect(html).toContain("Vous avez atteint la fin. 4 sujets ont atteint le seuil aujourd&#39;hui.");
  });

  it("renders nothing after the End Screen (AC2's 'nothing further' clause)", () => {
    // The End Screen's own <p> completion statement must be the last piece
    // of real READING content before the .page container closes and the
    // island's <script> tag begins -- i.e. only the End Screen's own
    // closing tags (</p></div>), the .page/.body/.html closings, and
    // Story 4.8's invisible #sr-announcer accessibility artifact (never
    // visible, never reading content -- an aria-live region existing in
    // the DOM is not the kind of "further content" this AC guards
    // against) separate it from <script>, with no OTHER element's opening
    // tag in between.
    const endScreenIndex = html.indexOf('id="end-screen"');
    expect(endScreenIndex).toBeGreaterThan(-1);

    const afterEndScreen = html.slice(endScreenIndex);
    const beforeScript = afterEndScreen.slice(0, afterEndScreen.indexOf("<script"));
    // Only the rule div, the <p>, their own closing tags, and the
    // sr-announcer div should appear -- no further <div>/<span>/<a>
    // opening tag past the <p> itself, other than that one exception.
    const afterCompletionStatement = beforeScript
      .slice(beforeScript.indexOf("</p>") + "</p>".length)
      .replace(/<div id="sr-announcer" aria-live="polite"[^>]*><\/div>/, "");
    expect(afterCompletionStatement).not.toMatch(/<(div|span|a|p|h1|ul|li)[ >]/);
  });

  it("renders the Discarded Volume once, at the foot of the item list, with French-locale-formatted counts (AC2)", () => {
    expect(html).toMatch(
      /<div class="discarded" id="discarded"[^>]*><span class="num"[^>]*>1 384<\/span> articles examinés → <span class="num"[^>]*>4<\/span> conservés\.<\/div>/
    );
    expect((html.match(/id="discarded"/g) ?? []).length).toBe(1);
  });

  it("renders the Consensus chip as a real <button> with its source list already present in the initial HTML (AC3, no-JS)", () => {
    const htmlWithoutScripts = stripInlineScript(html);
    expect(htmlWithoutScripts).toMatch(
      /<button type="button" class="chip" aria-expanded="false" aria-controls="source-list-ceasefire-2026-08-11"[^>]*data-consensus-chip[^>]*>/
    );
    // Present in the DOM -- no js-collapsed/js-expanded modifier class on
    // the markup itself -- in the server-rendered HTML either way. Its
    // *visibility* is governed by a plain CSS rule (`.source-list {
    // display: none }`, overridden back to visible by a <noscript> rule
    // later in the page) rather than by a class the server stamps here,
    // so a no-JS reader still sees the full list despite this element
    // having no distinguishing class of its own.
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
  const DIST_SPAIN_DAY = join(SITE_ROOT, "dist", "fr", "spain", "day.html");

  // Story 4.7 narrowed the routing enumeration to 24 pages (was 135), so a
  // fresh `astro build` now runs noticeably longer -- these tests'
  // explicit 30s timeout replaces vitest's 5s default, which the build
  // started intermittently exceeding once the page count grew.
  it(
    "builds a Continent page (Europe) with the correct sentence label and Zone-word target",
    () => {
      execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });
      const html = readFileSync(DIST_EUROPE_DAY, "utf-8");
      expect(html).toMatch(
        /<a class="word" data-zone-word data-lang="fr" data-zone="europe" data-period="day" href="\/fr\/france\/day"[^>]*>en Europe<\/a>/
      );
    },
    30000
  );

  it(
    "builds a Country page (Spain) with the correct sentence label and Zone-word target, and no fallback notice (AC4)",
    () => {
      execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });
      const html = readFileSync(DIST_SPAIN_DAY, "utf-8");
      expect(html).toMatch(
        /<a class="word" data-zone-word data-lang="fr" data-zone="spain" data-period="day" href="\/fr\/world\/day"[^>]*>en Espagne<\/a>/
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
    },
    30000
  );
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

  // This test runs astro build TWICE (once for the fallback fixture, once
  // more in the finally block to restore dist/) -- doubly exposed to
  // Story 4.7's 3x larger page count, hence a longer explicit timeout than
  // the single-build tests above.
  it(
    "renders the exact French sentence with the secondary color styling for a fallback Briefing",
    () => {
      const fallbackContent = readFileSync(FALLBACK_EXAMPLE_PATH, "utf-8");
      writeFileSync(FIXTURE_PATH, fallbackContent);

      try {
        execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });

        const html = readFileSync(join(SITE_ROOT, "dist", "fr", "france", "day.html"), "utf-8");
        expect(html).toMatch(
          /<div class="fallback-notice" id="fallback-notice"[^>]*>Affichage de l&#39;Europe — la France n&#39;a pas assez de couverture aujourd&#39;hui\.<\/div>/
        );
        const css = resolveCss(html);
        expect(css).toMatch(/\.fallback-notice[^{]*\{[^}]*color:#8a3a2b/);
        expect(css).toMatch(/\.fallback-notice[^{]*\{[^}]*background:#f6dcd4/);
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
    },
    60000
  );
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

  it(
    "renders exactly as many .item divs as clusters exist, for 3 and 4 clusters (existing fixtures)",
    () => {
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
    },
    30000
  );

  // Runs astro build twice (fixture swap + finally-block restore), like the
  // Continent-fallback test above -- same 60s allowance.
  it(
    "renders exactly 1 .item div, with no height/overflow constraint, for a single-cluster Briefing (AC1, AC3)",
    () => {
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
        // Uses resolveCss, not a local inline-only extraction -- Story
        // 4.8's own Blind Hunter review caught that this test's original
        // hand-rolled <style> match silently returned "" once the
        // stylesheet externalized (crossed Astro's inlining threshold),
        // making this negative assertion vacuously true and unable to
        // catch a real future regression.
        const css = resolveCss(html);
        expect(css).not.toMatch(/\.item(?:-list)?\[[^\]]*\]\s*\{[^}]*(?:max-height|overflow)/);
      } finally {
        writeFileSync(FIXTURE_PATH, originalFixture);
        execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });
      }
    },
    60000
  );
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

  it(
    "builds successfully and still renders the header and sentence",
    () => {
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
    },
    30000
  );

  it(
    "renders the Discarded Volume correctly for the real 0 ingested / 0 kept case, combined with 0 clusters",
    () => {
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
    },
    30000
  );
});

// Story 4.7 (AC2, AC3): the Output Language axis. Builds real /en/... and
// /es/... static pages and asserts the language-specific UI copy renders
// correctly, the control shows the right active/current element, and every
// one of its 3 options is a real <a href> (no-JS case) -- the same
// no-JS-readability proof this whole file exists for, extended to the new
// third axis.
describe("Output Language axis (Story 4.7)", () => {
  let englishHtml: string;
  let spanishHtml: string;

  beforeAll(() => {
    execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });
    englishHtml = readFileSync(join(SITE_ROOT, "dist", "en", "world", "day.html"), "utf-8");
    spanishHtml = readFileSync(join(SITE_ROOT, "dist", "es", "world", "day.html"), "utf-8");
  }, 30000);

  it("renders the English mad-libs lead-in, Zone/Period words, and timestamp prefix as static text", () => {
    expect(englishHtml).toContain("Here&#39;s what&#39;s happening");
    expect(englishHtml).toMatch(
      /<a class="word" data-zone-word data-lang="en" data-zone="world" data-period="day" href="\/en\/europe\/day"[^>]*>in the World<\/a>/
    );
    expect(englishHtml).toMatch(
      /<a class="word" data-period-word data-lang="en" data-zone="world" data-period="day" href="\/en\/world\/week"[^>]*>today<\/a>/
    );
    expect(englishHtml).toContain("Updated at ");
  });

  it("renders the Spanish mad-libs lead-in, Zone/Period words, and timestamp prefix as static text", () => {
    expect(spanishHtml).toContain("Esto es lo que está pasando");
    expect(spanishHtml).toMatch(
      /<a class="word" data-zone-word data-lang="es" data-zone="world" data-period="day" href="\/es\/europe\/day"[^>]*>en el Mundo<\/a>/
    );
    expect(spanishHtml).toMatch(
      /<a class="word" data-period-word data-lang="es" data-zone="world" data-period="day" href="\/es\/world\/week"[^>]*>hoy<\/a>/
    );
    expect(spanishHtml).toContain("Actualizado a las ");
  });

  it("renders the English Consensus chip wording, attribution wording, and source-list intro", () => {
    const htmlWithoutScripts = stripInlineScript(englishHtml);
    expect(htmlWithoutScripts).toContain("independent sources");
    expect(htmlWithoutScripts).toMatch(/<span class="num"[^>]*>\d+<\/span> countries/);
    expect(htmlWithoutScripts).toContain("Contributing sources and countries:");
    expect(htmlWithoutScripts).toMatch(/Reported by <em[^>]*>/);
    expect(htmlWithoutScripts).toContain("read the original article");
  });

  it("renders the Spanish Consensus chip wording, attribution wording, and source-list intro", () => {
    const htmlWithoutScripts = stripInlineScript(spanishHtml);
    expect(htmlWithoutScripts).toContain("fuentes independientes");
    expect(htmlWithoutScripts).toMatch(/<span class="num"[^>]*>\d+<\/span> países/);
    expect(htmlWithoutScripts).toContain("Fuentes y países contribuyentes:");
    expect(htmlWithoutScripts).toMatch(/Informado por <em[^>]*>/);
    expect(htmlWithoutScripts).toContain("leer el artículo original");
  });

  it("renders the English Discarded Volume with comma-grouped counts and the English End Screen sentence", () => {
    const htmlWithoutScripts = stripInlineScript(englishHtml);
    expect(htmlWithoutScripts).toMatch(
      /<div class="discarded" id="discarded"[^>]*><span class="num"[^>]*>1,384<\/span> articles reviewed → <span class="num"[^>]*>4<\/span> kept\.<\/div>/
    );
    expect(htmlWithoutScripts).toContain("stories met the threshold today.");
  });

  it("renders the Spanish Discarded Volume with comma-grouped counts and the Spanish End Screen sentence", () => {
    const htmlWithoutScripts = stripInlineScript(spanishHtml);
    expect(htmlWithoutScripts).toMatch(
      /<div class="discarded" id="discarded"[^>]*><span class="num"[^>]*>1,384<\/span> artículos examinados → <span class="num"[^>]*>4<\/span> conservados\.<\/div>/
    );
    expect(htmlWithoutScripts).toContain("temas alcanzaron el umbral hoy.");
  });

  it("marks EN as the current language on /en/world/day, and every option as a real <a href> (no-JS case)", () => {
    expect(englishHtml).toMatch(
      /<a class="active" aria-current="true" data-lang-word data-target-lang="en" data-lang="en" data-zone="world" data-period="day" href="\/en\/world\/day"[^>]*>EN<\/a>/
    );
    expect(englishHtml).toMatch(
      /<a class[^>]* data-lang-word data-target-lang="fr" data-lang="en" data-zone="world" data-period="day" href="\/fr\/world\/day"[^>]*>FR<\/a>/
    );
    expect(englishHtml).toMatch(
      /<a class[^>]* data-lang-word data-target-lang="es" data-lang="en" data-zone="world" data-period="day" href="\/es\/world\/day"[^>]*>ES<\/a>/
    );
    // Only the active option carries aria-current -- FR/ES must not.
    const activeCount = (englishHtml.match(/aria-current="true"/g) ?? []).length;
    expect(activeCount).toBe(1);
  });

  it("marks ES as the current language on /es/world/day, and every option as a real <a href> (no-JS case)", () => {
    expect(spanishHtml).toMatch(
      /<a class="active" aria-current="true" data-lang-word data-target-lang="es" data-lang="es" data-zone="world" data-period="day" href="\/es\/world\/day"[^>]*>ES<\/a>/
    );
    expect(spanishHtml).toMatch(
      /<a class[^>]* data-lang-word data-target-lang="fr" data-lang="es" data-zone="world" data-period="day" href="\/fr\/world\/day"[^>]*>FR<\/a>/
    );
    expect(spanishHtml).toMatch(
      /<a class[^>]* data-lang-word data-target-lang="en" data-lang="es" data-zone="world" data-period="day" href="\/en\/world\/day"[^>]*>EN<\/a>/
    );
    const activeCount = (spanishHtml.match(/aria-current="true"/g) ?? []).length;
    expect(activeCount).toBe(1);
  });

  // Scope's own explicitly-documented, non-blocking limitation: data/briefings/
  // is empty today, so every language degrades to the same French-fixture
  // Summary content -- the pipeline's per-language generation is correct in
  // principle (_LANGUAGE_NAMES/_prompt_for in claude.py), just not exercised
  // by a real cycle yet. This is expected, current behavior, not a bug --
  // asserted explicitly here so a future story wiring up real per-language
  // fixtures/pipeline data has a clear before/after to compare against.
  it("renders /en/world/day and /es/world/day with the fixture-fallback's French-language Summary text alongside the new English/Spanish UI copy (documented current limitation)", () => {
    expect(englishHtml).toContain("Here&#39;s what&#39;s happening");
    expect(englishHtml).toContain(
      "Un cessez-le-feu entre en vigueur après trois jours de négociations."
    );
    expect(spanishHtml).toContain("Esto es lo que está pasando");
    expect(spanishHtml).toContain(
      "Un cessez-le-feu entre en vigueur après trois jours de négociations."
    );
  });
});

// Story 5.1 (AC1): the web app manifest and its 2 required icon sizes,
// referenced from every page. Astro copies site/public/ to dist/
// byte-for-byte, unprocessed (unlike src/, which the bundler transforms)
// -- this suite verifies that behavior directly against the real build
// output rather than assuming it, per this story's own Dev Notes.
describe("PWA installability (Story 5.1)", () => {
  const MANIFEST_PATH = join(SITE_ROOT, "dist", "manifest.json");
  const ICON_192_PATH = join(SITE_ROOT, "dist", "icon-192.png");
  const ICON_512_PATH = join(SITE_ROOT, "dist", "icon-512.png");

  // This block's own build -- do not rely on a preceding describe block
  // having left dist/ populated. Blind Hunter review of this story caught
  // that running this block in isolation (a clean dist/) made every test
  // fail with ENOENT, since no build step of its own existed; every other
  // build-dependent block in this file has one, this was the exception.
  beforeAll(() => {
    execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });
  }, 30000);

  it("serves a valid manifest.json with the required fields", () => {
    expect(existsSync(MANIFEST_PATH)).toBe(true);
    const manifest = JSON.parse(readFileSync(MANIFEST_PATH, "utf-8"));

    expect(manifest.name).toBe("5 News");
    expect(manifest.display).toBe("standalone");
    expect(manifest.start_url).toBe("/");
    expect(manifest.theme_color).toBe("#1f4d3d");
    expect(manifest.background_color).toBe("#faf9f6");
    expect(Array.isArray(manifest.icons)).toBe(true);
    const sizes = manifest.icons.map((icon: { sizes: string }) => icon.sizes);
    expect(sizes).toContain("192x192");
    expect(sizes).toContain("512x512");
  });

  it("copies both icon PNGs to dist/, unprocessed, at the correct real dimensions", () => {
    expect(existsSync(ICON_192_PATH)).toBe(true);
    expect(existsSync(ICON_512_PATH)).toBe(true);

    // Verify structurally (real PNG dimensions read from the file's own
    // IHDR chunk), not just "the file exists" -- Story 4.8's own Blind
    // Hunter review is the reminder here: a file existing at a path is
    // not proof its content is what it claims to be.
    const readPngDimensions = (path: string) => {
      const buf = readFileSync(path);
      // PNG signature (8 bytes) + IHDR chunk length (4) + "IHDR" (4) = 16,
      // then width (4 bytes BE) and height (4 bytes BE) follow directly.
      const width = buf.readUInt32BE(16);
      const height = buf.readUInt32BE(20);
      return { width, height };
    };

    expect(readPngDimensions(ICON_192_PATH)).toEqual({ width: 192, height: 192 });
    expect(readPngDimensions(ICON_512_PATH)).toEqual({ width: 512, height: 512 });
  });

  it("links the manifest and theme-color meta tag from both / and a [lang]/[zone]/[period] route", () => {
    const indexHtml = readFileSync(DIST_INDEX, "utf-8");
    const routeHtml = readFileSync(join(SITE_ROOT, "dist", "fr", "world", "day.html"), "utf-8");

    for (const pageHtml of [indexHtml, routeHtml]) {
      expect(pageHtml).toContain('<link rel="manifest" href="/manifest.json">');
      expect(pageHtml).toContain('<meta name="theme-color" content="#1f4d3d">');
      expect(pageHtml).toContain(
        '<link rel="icon" type="image/png" sizes="32x32" href="/5news-logo/5news-favicon-32.png">'
      );
      expect(pageHtml).toContain(
        '<link rel="icon" type="image/png" sizes="16x16" href="/5news-logo/5news-favicon-16.png">'
      );
      expect(pageHtml).toContain(
        '<link rel="apple-touch-icon" sizes="180x180" href="/5news-logo/5news-icon-180.png">'
      );
    }
  });

  it("copies the 5news-logo icon set to dist/, unprocessed", () => {
    for (const name of [
      "5news-favicon-16.png",
      "5news-favicon-32.png",
      "5news-icon-180.png",
      "5news-icon-512.png",
      "5news-icon-1024.png",
    ]) {
      expect(existsSync(join(SITE_ROOT, "dist", "5news-logo", name))).toBe(true);
    }
  });

  it("never references Notification/PushManager/requestPermission/showNotification anywhere in the built output (AC3)", () => {
    const indexHtml = readFileSync(DIST_INDEX, "utf-8");
    expect(indexHtml).not.toMatch(/Notification|PushManager|requestPermission|showNotification/);
  });
});

// Story 5.2 (AD-8): the service worker itself, and its registration
// reaching every page. This block builds its own dist/ -- Story 5.1's
// own Blind Hunter review caught a real bug where a different describe
// block silently relied on a preceding, unrelated block having already
// built dist/, so every build-dependent block in this file has its own
// explicit build step.
describe("Service worker registration (Story 5.2)", () => {
  const SW_PATH = join(SITE_ROOT, "dist", "sw.js");

  beforeAll(() => {
    // Story 5.3: public/sw.js is now itself a generated file (stamped
    // from public/sw.template.js) -- must run the stamping script BEFORE
    // astro build, same as every other pre-build step this file's own
    // build-dependent blocks already account for. A bare `astro build`
    // alone (without this step) would build against whatever public/sw.js
    // happened to be left on disk from a previous run, not a fresh stamp.
    execFileSync("node", ["scripts/stamp-service-worker.ts"], { cwd: SITE_ROOT, stdio: "pipe" });
    execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });
  }, 30000);

  it("serves sw.js, copied byte-for-byte from public/", () => {
    expect(existsSync(SW_PATH)).toBe(true);
    const built = readFileSync(SW_PATH, "utf-8");
    const source = readFileSync(join(SITE_ROOT, "public", "sw.js"), "utf-8");
    expect(built).toBe(source);
  });

  it("registers the service worker from both / and a [lang]/[zone]/[period] route", () => {
    const indexHtml = readFileSync(DIST_INDEX, "utf-8");
    const routeHtml = readFileSync(join(SITE_ROOT, "dist", "fr", "world", "day.html"), "utf-8");

    for (const pageHtml of [indexHtml, routeHtml]) {
      expect(pageHtml).toMatch(/serviceWorker.{0,20}in navigator/);
      expect(pageHtml).toMatch(/navigator\.serviceWorker\.register\(.\/sw\.js.\)/);
    }
  });

  it("guards registration behind a serviceWorker-support feature check, and swallows a rejected registration", () => {
    const indexHtml = readFileSync(DIST_INDEX, "utf-8");
    // The registration call itself is chained with .catch(...) -- a
    // rejected registration (unsupported browser, blocked context) must
    // never surface as an uncaught error on the page.
    expect(indexHtml).toMatch(/register\(.\/sw\.js.\)\.catch\(/);
  });
});

// Story 5.3 (AD-9): cycle-identifier stamping and the install/activate
// lifecycle. This block runs the real pre-build stamping script and
// asserts on its actual output -- byte-for-byte idempotence for the same
// cycle, a real difference across cycles, and the 3 required lifecycle
// behaviors (skipWaiting, stale-cache deletion, clients.claim), all
// against the real built dist/sw.js, not the checked-in template.
describe("Service worker cycle invalidation (Story 5.3)", () => {
  const TEMPLATE_PATH = join(SITE_ROOT, "public", "sw.template.js");
  const SW_JS_PATH = join(SITE_ROOT, "public", "sw.js");
  const FIXTURE_PATH = join(SITE_ROOT, "src", "fixtures", "day.json");
  const originalFixture = readFileSync(FIXTURE_PATH, "utf-8");

  function stamp(): string {
    execFileSync("node", ["scripts/stamp-service-worker.ts"], { cwd: SITE_ROOT, stdio: "pipe" });
    return readFileSync(SW_JS_PATH, "utf-8");
  }

  it("never leaves the __CACHE_VERSION__ placeholder unsubstituted in the stamped output", () => {
    const stamped = stamp();
    expect(stamped).not.toContain("__CACHE_VERSION__");
    // And confirm the template itself DOES still carry the placeholder --
    // proving this test would fail if the substitution step were ever
    // silently skipped, not just checking a string that happens to be
    // permanently absent from an unrelated file.
    const template = readFileSync(TEMPLATE_PATH, "utf-8");
    expect(template).toContain("__CACHE_VERSION__");
  });

  it("produces byte-identical sw.js across two stamps of the same underlying cycle data", () => {
    const first = stamp();
    const second = stamp();
    expect(first).toBe(second);
  });

  it("produces a different sw.js when the underlying cycle's generated_at changes", () => {
    const beforeStamp = stamp();

    try {
      const modified = { ...JSON.parse(originalFixture), generated_at: "2099-01-01T00:00:00+00:00" };
      writeFileSync(FIXTURE_PATH, JSON.stringify(modified));

      const afterStamp = stamp();
      expect(afterStamp).not.toBe(beforeStamp);
      expect(afterStamp).toContain("2099-01-01T00-00-00-00-00");
    } finally {
      writeFileSync(FIXTURE_PATH, originalFixture);
      stamp(); // restore sw.js to reflect the restored fixture too
    }
  });

  it("includes skipWaiting on install, and stale-cache deletion + clients.claim on activate", () => {
    const stamped = stamp();
    expect(stamped).toMatch(/addEventListener\(.install.,[\s\S]{0,80}skipWaiting\(\)/);
    expect(stamped).toMatch(/addEventListener\(.activate.,/);
    expect(stamped).toMatch(/caches\s*\.\s*keys\(\)/);
    expect(stamped).toMatch(/caches\.delete\(/);
    expect(stamped).toMatch(/clients\.claim\(\)/);
  });

  it("includes the network-first cache-eviction logic and the offline-fallback synthesis (Story 5.4)", () => {
    const stamped = stamp();
    expect(stamped).toMatch(/function evictOtherNetworkFirstEntries/);
    expect(stamped).toMatch(/function buildOfflineFallbackHtml/);
    expect(stamped).toMatch(/function injectOfflineBannerMeta/);
    expect(stamped).toContain('OFFLINE_BANNER_META_NAME = "offline-cache"');
  });
});

// Story 5.4 (AC1, AC2, AC3): the honest-offline-experience UI. This
// block builds its own dist/ -- every build-dependent block in this file
// has its own explicit build step, per Stories 5.1/5.2's own Blind
// Hunter-caught precedent.
describe("Honest offline experience (Story 5.4)", () => {
  beforeAll(() => {
    execFileSync("node", ["scripts/stamp-service-worker.ts"], { cwd: SITE_ROOT, stdio: "pipe" });
    execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });
  }, 30000);

  it("renders the offline banner (hidden by default) with the correct per-language text on both / and a [lang]/[zone]/[period] route", () => {
    const indexHtml = readFileSync(DIST_INDEX, "utf-8");
    const enRouteHtml = readFileSync(join(SITE_ROOT, "dist", "en", "world", "day.html"), "utf-8");

    expect(indexHtml).toContain('<div class="offline-banner" id="offline-banner"');
    expect(indexHtml).toContain("Vous consultez une version en cache d&#39;un cycle précédent.");
    expect(enRouteHtml).toContain("You&#39;re viewing a cached version from an earlier cycle.");

    const css = resolveCss(indexHtml);
    expect(css).toMatch(/\.offline-banner[^{]*\{[^}]*display:none/);
  });

  it("registers the offline-banner detection script (checks for the offline-cache meta marker) on both entry points", () => {
    const indexHtml = readFileSync(DIST_INDEX, "utf-8");
    const routeHtml = readFileSync(join(SITE_ROOT, "dist", "fr", "world", "day.html"), "utf-8");

    for (const pageHtml of [indexHtml, routeHtml]) {
      // Minification rewrites double-quoted string literals to
      // backtick-quoted ones -- tolerate either quote character rather
      // than assuming one.
      expect(pageHtml).toMatch(/querySelector\(.meta\[name=.offline-cache.\]./);
      expect(pageHtml).toMatch(/getElementById\(.offline-banner.\)/);
    }
  });
});

describe("Item headlines and heading hierarchy (Story 6.1)", () => {
  // Own build step, per this file's established convention (Stories 5.1/5.2
  // Blind Hunter precedent: never rely on another block having populated
  // dist/ first).
  let html: string;

  beforeAll(() => {
    execFileSync("npx", ["astro", "build"], { cwd: SITE_ROOT, stdio: "pipe" });
    html = readFileSync(DIST_INDEX, "utf-8");
  }, 30000);

  it("renders each item's headline as a real <h2> in the initial HTML, no JS required", () => {
    // Astro appends its scoping attribute to the tag, so match the shape
    // rather than a literal opening tag.
    expect(html).toMatch(
      /<h2 class="headline"[^>]*>Un cessez-le-feu entre en vigueur après trois jours de négociations<\/h2>/
    );
  });

  it("keeps exactly one <h1> — the mad-libs sentence — with the item headlines one level below it", () => {
    // The page's document outline: a single h1, then one h2 per item. This
    // is the accessibility win of Story 6.1 (a screen-reader user can jump
    // item to item), and it only holds if no second h1 sneaks in.
    const h1Count = (html.match(/<h1[ >]/g) ?? []).length;
    expect(h1Count).toBe(1);
    expect(html).toMatch(/<h1 id="mad-libs-sentence"/);

    // One h2 per item, and never a skipped level (no h3 without an h2).
    const itemCount = (html.match(/<div class="item"/g) ?? []).length;
    const h2Count = (html.match(/<h2[ >]/g) ?? []).length;
    expect(h2Count).toBe(itemCount);
    expect(html).not.toMatch(/<h3[ >]/);
  });

  it("renders the headline in the serif face above a grotesque summary, so the two levels are visually distinct", () => {
    // Astro scopes component styles by injecting a data-astro-cid-* attribute
    // into the selector, so `.item h2.headline` compiles to
    // `.item[data-astro-cid-x] h2[data-astro-cid-x].headline` -- match
    // tolerantly rather than pinning the generated hash.
    const css = resolveCss(html);
    expect(css).toMatch(/\.item[^{]*h2[^{]*\.headline\{[^}]*font-size:24px/);
    expect(css).toMatch(/\.item[^{]*h2[^{]*\.headline\{[^}]*Source Serif 4/);
    expect(css).toMatch(/\.item[^{]*p[^{]*\.summary\{[^}]*IBM Plex Sans/);
  });

  it("renders nothing after the End Screen — now including headings (closes a gap in the Story 4.4 check)", () => {
    // The original assertion listed div|span|a|p|h1|ul|li but omitted h2,
    // so a stray heading after the completion statement would have passed.
    // Same slicing approach as the Story 4.4 check this extends: find the
    // End Screen's completion <p>, then assert on everything after it. The
    // sr-announcer div is the one documented exception.
    const beforeScript = html.slice(0, html.indexOf("<script"));
    // Anchor on the End Screen itself, then step past its completion <p>.
    // (Slicing from the first "</p>" in the document would land inside the
    // first item's summary instead -- item headlines legitimately follow it.)
    const endScreenIndex = beforeScript.indexOf('<div class="end-screen"');
    expect(endScreenIndex).toBeGreaterThan(-1);
    const endScreen = beforeScript.slice(endScreenIndex);
    const afterCompletionStatement = endScreen
      .slice(endScreen.indexOf("</p>") + "</p>".length)
      .replace(/<div id="sr-announcer" aria-live="polite"[^>]*><\/div>/, "");
    expect(afterCompletionStatement).not.toMatch(/<(div|span|a|p|h1|h2|h3|ul|li)[ >]/);
  });
});
