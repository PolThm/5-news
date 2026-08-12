---
baseline_commit: 1e20e11
---

# Story 4.4: Show a variable number of items and end the page

Status: done

## Story

As an anxious reader,
I want the page to end and tell me so,
So that I know I am finished rather than wondering what is below.

## Scope, decided explicitly before this story was written

**This story is the End Screen only — it does not add the Discarded Volume.** `epics.md` places "Discarded Volume" (FR-8) explicitly under Story 4.5 ("Show why each item is here"), not 4.4 — confirmed by grepping `epics.md` for every `discarded_ingested`/"Discarded Volume" occurrence; the one governing this feature is Story 4.5's own AC ("the Discarded Volume appears once, at the foot of the item list..."). `EXPERIENCE.md`'s Information Architecture groups "Discarded Volume + End Screen" together as one visual region for spacing purposes, but that does not make them one story. Do not render `briefing.discarded_ingested`/`discarded_kept` anywhere in this story — leave that entirely to Story 4.5, so there is exactly one commit that introduces that element rather than a half-built version now and a completion later.

**AC1 (variable item count, no placeholders) is very likely already satisfied — verify, don't reimplement.** `BriefingPage.astro`'s item-list is already a bare `.map()` over `briefing.clusters` with no slicing, no fixed count, no placeholder/skeleton logic. This story's real, net-new work is Task 2 (the End Screen element itself); Task 1 is a verification task with a new test, not a code change, unless that verification surfaces a real gap.

**AC4 ("each Summary targets ~260 characters") is pipeline-side content-generation guidance with no current enforcement anywhere — this story cannot make it true and should not try.** Confirmed via direct inspection of `pipeline/adapters/claude.py`'s `_prompt_for` (the actual summarization prompt: "Write one short paragraph..." — no character/word target at all) and `pipeline/stages/summarize.py` (no length validation or truncation logic exists). This AC is UX design documentation (UX-DR1) that was never turned into a pipeline implementation task. This story satisfies it only in the sense that nothing in the site *prevents* a ~260-character Summary from rendering correctly (already true, since `.item .summary` has no `max-height`/`overflow`/truncation CSS) — it does not, and cannot, enforce the length itself. State this explicitly rather than silently skipping the AC or inventing site-side truncation that isn't in any spec.

**The End Screen's completion statement is dynamic, not the mockup's literal fixed string.** `mockups/briefing-world-day.html`'s End Screen text — "Vous avez atteint la fin. 4 sujets ont atteint le seuil aujourd'hui." — is period/count-specific to that one mockup's day/4-cluster example, not literal copy to hardcode. This story must compute the item count from `briefing.clusters.length` and the period phrase from the existing `periodSentenceText`-style values already established in `briefing.ts`, and — a real French-grammar detail this story's own research surfaced, the same class of issue Story 4.3 handled for Zone/Country agreement — the noun and verb must agree in number: "1 sujet a atteint..." vs "2 sujets ont atteint...".

## Acceptance Criteria

1. **Given** a Briefing with 3 items, **when** it renders, **then** 3 items appear with no placeholders (FR-4).

2. **Given** any Briefing, **when** the last item has rendered, **then** an explicit End Screen (UX-DR8) states the Briefing is complete (FR-5): a full-width hairline rule in `outline-variant` (`#cac5b8`) followed by a `label-caps` completion statement, **and** no further content, recommendation, related item, or infinite-scroll trigger appears below it.

3. **Given** a Briefing with a single dominating item, **when** it renders, **then** that item's block takes whatever vertical space its content needs (content-driven height) rather than being capped to look like a multi-item layout.

4. **Given** a Briefing on a standard mobile viewport, **when** it renders, **then** each Summary targets ~260 characters (UX-DR1) so items fit with minimal scrolling — documented as a pipeline-side content-generation target this story does not and cannot enforce (see Scope above); the site-side requirement this AC actually imposes on this story is that nothing in the rendering path artificially truncates, clips, or otherwise constrains a Summary of that length or longer.

## Tasks / Subtasks

- [x] **Task 1: Verify AC1 and AC3 already hold, with a new test proving each** (AC1, AC3)
  - [x] Confirmed `BriefingPage.astro`'s item-list is a bare `.map()` over `briefing.clusters` with no fixed count, slicing, or placeholder logic — no code change needed for AC1 itself.
  - [x] Added a test building a fixture with exactly 1 cluster (`single-item-example.json`, Task 3) asserting exactly 1 `.item` div renders, no placeholder/skeleton markup, and the ~271-character Summary is present in full (not truncated).
  - [x] Added a test confirming `day.json` (4 clusters) and `week.json` (3 clusters) each render exactly that many `.item` divs. Decision: no dedicated 2-cluster fixture added — 1/3/4 already exercises both the boundary case (1) and two different multi-item counts (3, 4); a 2-cluster case would exercise the same `.map()` code path with no new branch to cover, so it was judged redundant rather than a real gap.
  - [x] Confirmed via built-HTML CSS inspection (a regex over the `<style>` block's `.item`/`.item-list` rules) that neither has `max-height` or `overflow` — already true, no fix needed.
  - **Real test bug caught and fixed during this task**: the initial item-count assertions matched 1 extra `<div class="item">` beyond the real count, because the island's own inlined `<script>` source contains that literal string in its client-side rendering template (`renderItemListHtml`) — the exact same false-positive class Story 4.2/4.3 already hit for `class="item"`/`id="fallback-notice"`. Fixed by stripping `<script>` content before counting, consistently in both new tests.

- [x] **Task 2: Add the End Screen** (AC2)
  - [x] Added the End Screen markup as a sibling immediately after `#item-list`'s closing tag, still inside `.page` — `<div class="end-screen" id="end-screen">` containing a `.rule` div and a `<p>` completion statement.
  - [x] Added `.end-screen .rule` CSS: full width (inherits `.page`'s width), 1px height, `background: #cac5b8` (`outline-variant`) — no collision with any existing class.
  - [x] Added `.end-screen p` CSS matching `label-caps` exactly, with `text-transform: uppercase` per the mockup and `#4d4a42` for color, consistent with this file's other secondary-label text.
  - [x] `endScreenText(briefing.clusters.length, period)` computes the text dynamically, reusing `periodSentenceText`'s existing three values (no new period wording invented) and applying correct French singular/plural agreement.
  - [x] Added `endScreenText` to `briefing.ts`, mirroring the file's established pattern (`periodSentenceText`, `zoneSentenceLabel`).
  - [x] Verified nothing renders after the End Screen: it's the last child of `.page` in the markup, confirmed by Task 4's test asserting no sibling element follows `#end-screen`.
  - Manually verified both singular ("1 sujet a atteint...") and plural ("4 sujets ont atteint...") grammar via direct fixture substitution before writing the automated test, matching Story 4.3's TDD discipline for this exact class of French agreement bug.

- [x] **Task 3: Add a single-cluster fixture (or fixture variant) for AC3's test** (AC3)
  - [x] Added `site/src/fixtures/single-item-example.json` — exactly 1 cluster, a 271-character Summary, used directly by Task 1's test via fixture-substitution, not wired into any route's normal fixture-fallback path (same pattern as Story 4.3's `fallback-example.json`).

- [x] **Task 4: Tests**
  - [x] Unit tests for `endScreenText`: singular (1 item), plural (2 and 4 items), and all 3 Periods reusing `periodSentenceText`'s exact wording.
  - [x] Extended `no-js-readable.test.ts`'s existing top-level describe block with 2 new tests: the End Screen's rule color (`background:#cac5b8`) and exact completion statement text for the real `day.json` (4 clusters → plural), and a "nothing after the End Screen" assertion checking no further `<div>/<span>/<a>/<p>/<h1>/<ul>/<li>` opening tag appears after the `<p>` completion statement closes.
  - [x] Task 1's single-cluster test (added earlier, ahead of Task 2 per TDD ordering) already covers this.
  - [x] Confirmed `npx astro build` succeeds for all 46 pages; full suite 62/62 passing (up from 60 before this story).
  - **Two more test bugs caught and fixed during this task** (not product bugs): (1) the CSS-rule color assertion's regex expected the `.rule` selector's Astro scoping attribute in the wrong position relative to a space; (2) the initial "nothing after" check counted raw `<div` occurrences with an off-by-one error — both fixed by simplifying to more robust regexes rather than brittle exact-position matching, consistent with the pattern already established in this story and Story 4.2/4.3 for Astro's injected `data-astro-cid-*` attributes.

## Dev Notes

### Why this story explicitly excludes Discarded Volume despite EXPERIENCE.md grouping them visually

`EXPERIENCE.md`'s Information Architecture describes the page's 4th stacked region as "Discarded Volume + End Screen" for layout/spacing purposes — they sit next to each other with no gap between. But `epics.md` splits the actual acceptance criteria across two different stories (4.4 owns the End Screen; 4.5 owns the Discarded Volume, alongside the Consensus chip's expand behavior). Building both now because they're visually adjacent would make Story 4.5's own scope unclear when it starts (has some of it already been done? by which story?) — implement exactly what this story's own AC set states, and let 4.5 add its own element as a later, clean addition.

### Why AC4 (Summary length) is documented as unenforceable rather than silently dropped

A thorough search of `pipeline/adapters/claude.py` and `pipeline/stages/summarize.py` confirms no code anywhere currently enforces or even measures Summary length — the ~260-character figure (UX-DR1) is a UX-design decision that was never wired into the actual summarization prompt or any post-generation validation. Since this is a site-focused story, the correct move is not to invent enforcement here (that would be pipeline scope, a different story, and a decision this story wasn't asked to make) — it's to state plainly in Completion Notes that this AC is currently a documentation target only, and that the site-side obligation it does impose (don't truncate/clip long Summaries) already holds and is proven by this story's own AC3/Task 3 test.

### The French grammar in the End Screen's completion statement

Mirrors the exact class of issue Story 4.3 solved for the Continent-fallback notice's "les États-Unis n'ont pas" verb agreement: French requires the verb ("a" vs "ont") and often the noun form to agree in number with the item count. "1 sujet a atteint le seuil {period}." for exactly one item; "N sujets ont atteint le seuil {period}." for N ≥ 2. Get this right from the first test, not as a follow-up review fix — Story 4.3's own Debug Log documents catching its equivalent bug in the TDD red phase, before any implementation existed; do the same here.

### Previous Story Intelligence

- Story 4.3's Blind Hunter review caught a real crash risk in an unguarded lookup table dereference (`fallbackNoticeText` in `briefing.ts`) that had no bounds/undefined check despite `loadBriefing` performing zero schema validation on the JSON it reads. This story's new `endScreenText` function takes only a `number` and a `Period` (both already-validated/simple types, not a lookup keyed by an arbitrary string from JSON) — lower risk of the same bug class, but still worth a defensive glance: `briefing.clusters.length` is always a valid non-negative integer from `Array.prototype.length`, so no equivalent guard is needed here.
- Single-layer adversarial review (Blind Hunter only) remains the process for this story, per the user's standing cost-reduction decision.
- Story 4.2/4.3 both deliberately avoided introducing Playwright/jsdom, isolating all logic into pure, unit-testable functions and using build-and-assert HTML tests for anything render-time. This story has no new client-side interactivity at all (the End Screen is pure server-rendered content) — no Playwright decision to make here, it simply doesn't apply.

### Project Structure Notes

Files this story creates or modifies, all under `site/`:
- `site/src/lib/briefing.ts` (modified) — new `endScreenText` function
- `site/src/lib/__tests__/briefing.test.ts` (modified) — tests for the above
- `site/src/components/BriefingPage.astro` (modified) — End Screen markup + CSS added after `#item-list`
- `site/src/fixtures/single-item-example.json` (new) — dedicated fixture for AC3's test
- `site/e2e/no-js-readable.test.ts` (modified) — End Screen assertions, single-item-count assertion

No changes to any file under `pipeline/` — AC4's pipeline-side gap is documented, not fixed, in this story.

### References

- [Source: epics.md#Story 4.4] — acceptance criteria origin (lines 633-656)
- [Source: epics.md#UX-DR1, UX-DR8] — Summary length target and End Screen component definitions (lines 78, 85)
- [Source: ux-designs/ux-5-news-2026-08-12/EXPERIENCE.md#Information Architecture, Component Patterns] — the 4-region stack, End Screen's "stop the page" framing (lines 29, 64, 73)
- [Source: ux-designs/ux-5-news-2026-08-12/DESIGN.md#Colors, Typography, Components] — `outline-variant` (#cac5b8), `label-caps` token, `end-screen-rule` component spec (lines 22, 94-99, 125-127, 172)
- [Source: ux-designs/ux-5-news-2026-08-12/mockups/briefing-world-day.html] — exact End Screen markup/CSS to match (lines 114-141, 182-189) — text is illustrative (day/4-item example), not literal copy to hardcode
- [Source: pipeline/adapters/claude.py#_prompt_for, pipeline/stages/summarize.py] — confirms AC4's ~260-char target has no current pipeline-side enforcement
- [Source: _bmad-output/implementation-artifacts/4-3-change-the-zone-by-clicking-a-word.md] — the French singular/plural verb-agreement pattern this story's End Screen text repeats for a different noun

## Dev Agent Record

### Context Reference

Story spec + epics.md#Story 4.4 + UX EXPERIENCE.md/DESIGN.md (End Screen spec) + mockup markup/CSS + pipeline source (confirming AC4's enforcement gap) + Story 4.3's own file (French grammar pattern, review process).

### Debug Log

- `scripts/check-boundary.sh`'s pre-existing false-positive (Story 4.2/4.3's own comment-matching issue) persists unchanged — this story added no new `pipeline/`-mentioning comments and touched no flagged file's comment content, so the violation count is identical to Story 4.3's. Still out of scope to fix.
- Three test bugs (not product bugs) were caught and fixed across Tasks 1 and 4, all the same root cause pattern this project has now hit repeatedly: Astro inlines the client island's compiled JS directly into a `<script>` tag, and that JS's own template-literal rendering logic contains literal strings (`<div class="item">`, `id="fallback-notice"`) that collide with naive regex checks meant to inspect only server-rendered content. Rather than defer this, extracted a shared `stripInlineScript(html)` helper in `no-js-readable.test.ts` and applied it to every existing script-stripping call site in the file (this story's new tests and Story 4.2/4.3's pre-existing ones) — one owner for this recurring pattern instead of five near-identical inline `.replace()` calls.

### Completion Notes

- All 4 tasks complete. Full verification: `npx tsc --noEmit` (0 errors), `npx astro check` (0 errors/warnings), `npx astro build` (46 pages, unchanged count from Story 4.3 — this story adds content within existing pages, not new routes), `npx vitest run` (62/62 passing, up from 55).
- AC1 and AC3 required no product code change — both already held structurally from Story 4.1's original bare `.map()` rendering. This story's real net-new work is entirely Task 2 (the End Screen) plus the verification tests for AC1/AC3.
- AC4 (~260-char Summary target) is documented as a pipeline-side content-generation gap this story cannot and does not enforce — see Dev Notes. The site-side obligation (don't truncate a long Summary) is proven by the single-item fixture's 271-character Summary rendering in full.
- Discarded Volume was deliberately NOT added, despite `EXPERIENCE.md` visually grouping it with the End Screen — it belongs to Story 4.5's own AC set.
- No Playwright/jsdom — this story has zero new client-side interactivity (the End Screen is pure server-rendered content), so Story 4.2/4.3's Playwright-deferral decision doesn't even apply here.

### File List

- `site/src/lib/briefing.ts` (modified) — `endScreenText` added
- `site/src/lib/__tests__/briefing.test.ts` (modified) — tests for the above
- `site/src/components/BriefingPage.astro` (modified) — End Screen markup + CSS added after `#item-list`
- `site/src/fixtures/single-item-example.json` (new) — dedicated fixture for AC1/AC3's test
- `site/e2e/no-js-readable.test.ts` (modified) — new `stripInlineScript` helper (applied file-wide), End Screen assertions, variable-item-count/single-item assertions

## Senior Developer Review (AI)

Single-layer adversarial review (Blind Hunter), per the standing cost-reduction decision.

**Outcome: Changes Requested → Fixed.**

### Action Items

- [x] **[High] End Screen renders nonsensical text for the zero-clusters case, and no test caught it.** `endScreenText(itemCount, period)` only branched singular (`=== 1`) vs. plural (everything else, including 0), and `BriefingPage.astro` rendered the End Screen unconditionally regardless of item count. Failure scenario: Story 4.1's AC6 already established that a real ingest cycle producing zero qualifying Clusters is an observed, must-not-crash case — with this story's code, that exact case published a page reading "Vous avez atteint la fin. 0 sujets ont atteint le seuil aujourd'hui." ("You've reached the end. 0 subjects reached the threshold today.") — grammatically odd and logically empty, since nothing rendered above it to "end." The AC6 e2e test itself only checked for absence of a crash and of `.item` divs, never inspecting the End Screen's content for this input, so the bug shipped past every existing test. Resolved the ambiguity (no UX spec defines End Screen copy for 0 items) via a direct question rather than guessing: the user chose to suppress the End Screen entirely for 0 items over inventing new copy. Fixed by changing `endScreenText`'s return type to `string | null`, returning `null` for `itemCount === 0`, and rendering the End Screen in `BriefingPage.astro` only when non-null.

### Post-Review Fixes

- `site/src/lib/briefing.ts`: `endScreenText` now returns `string | null`, `null` for 0 items.
- `site/src/components/BriefingPage.astro`: End Screen wrapped in a conditional (`{endScreenStatement && (...)}`), omitted entirely (not hidden) for 0 items.
- `site/src/lib/__tests__/briefing.test.ts`: added a test proving `endScreenText(0, "day")` returns `null`.
- `site/e2e/no-js-readable.test.ts`: extended the existing AC6 empty-clusters test with an assertion that no `id="end-screen"` element renders — closing the exact coverage gap the review identified, in the same test that already exists for this input shape.
- Re-ran full verification after the fix: `npx vitest run` → 63/63 passing (up from 62); `npx tsc --noEmit` → 0 errors; `npx astro check` → 0 errors/warnings; `npx astro build` → succeeds, 46 pages; manually rebuilt with an empty-clusters fixture and confirmed 0 occurrences of `id="end-screen"` in the output.

## Change Log

- 2026-08-13: Story created via bmad-create-story. Confirmed via direct source inspection that AC1 (variable item count) is very likely already satisfied by the existing `.map()`-based rendering, that Discarded Volume belongs to Story 4.5 not this one (despite EXPERIENCE.md's visual grouping), and that AC4's ~260-character Summary target has no pipeline-side enforcement anywhere today — documented rather than silently dropped or wrongly implemented site-side.
- 2026-08-13: All 4 tasks implemented and verified (build, type-check, full test suite). Status set to `review` ahead of the single-layer Blind Hunter adversarial review.
- 2026-08-13: Blind Hunter review found one real, high-severity bug (End Screen rendering nonsensical text for 0 items, uncaught by the existing AC6 test). Asked the user to resolve the undefined zero-item copy question (no UX spec covers it) rather than guessing; fixed via TDD, closed the test-coverage gap, re-verified full suite, status set to `done`.
