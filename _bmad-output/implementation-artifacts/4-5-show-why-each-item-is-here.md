---
baseline_commit: 7b4e3f6
---

# Story 4.5: Show why each item is here

Status: done

## Story

As a sceptical reader,
I want the criterion stated as a number I can inspect,
So that I can disagree with it rather than having to trust it.

## Scope, decided explicitly before this story was written

**AC1 (the chip shows ranking's own counts, not raw Article counts) requires no site-side code change — it is already true, confirmed by tracing the pipeline.** `pipeline/stages/cluster.py`'s `coverage_for_cluster` is the single owner (AD-12) of `independent_source_count`/`country_count`; `pipeline/stages/rank.py` consumes those exact same two fields, unmodified, for both the qualifying-floor check and the sort order; `pipeline/stages/publish.py` passes them through unchanged. There is no separate raw-Article count anywhere downstream of `dedupe.py` that could leak into the chip — the only "rawer" count (`ArticleGroup.article_count`) never survives into the `Cluster` dict the site reads. This AC's only site-side obligation is to keep rendering `cluster.independent_source_count`/`cluster.country_count` exactly as today (`BriefingPage.astro` already does) — do not invent a new count anywhere.

**This story's real, net-new work is two things: the Discarded Volume element (AC2) and the Consensus chip's expand/collapse (AC3).** Both are additions to `BriefingPage.astro`; the second also introduces this codebase's second-ever piece of client JS.

**A real data-integrity gap must be fixed as part of this story, not deferred: every existing fixture's `members` array mismatches its own `independent_source_count`/`country_count`.** Confirmed across all 5 fixture files (`day.json`, `week.json`, `month.json`, `single-item-example.json`, `fallback-example.json`) — every cluster's `members` array has only 1-2 entries while `independent_source_count` claims 3-12. This is not a test-only concern: `loadBriefing`'s fixture-fallback path is a real, currently-reachable production rendering path (used whenever `data/briefings/` doesn't have a real file yet — true for every Zone/Period combination today, since no real pipeline cycle output exists in this repo). AC3's own wording — "their number equals the displayed count exactly; this is a hard rendering guarantee, not a best-effort display" — is violated by every fixture-backed page the moment a reader expands the chip, unless this story corrects the fixtures. Fix the fixtures' `members` arrays to actually contain `independent_source_count` entries with exactly `country_count` distinct `source_country` values among them (matching each fixture's own pre-existing `countries` array, which is already correct and unchanged) — do not add a defensive rendering workaround (e.g. clamping the displayed count to `members.length`) instead, since that would make the displayed number lie about what ranking actually used, which is the opposite of what this story exists to guarantee.

**The expand/collapse must not fetch anything — the data is already in the page.** Per `EXPERIENCE.md`'s Cold Load state pattern ("Full Briefing content present in the initial HTML response... with zero client-side execution"), the source list must be server-rendered into the initial HTML (present for every item, always, regardless of JS) and merely shown/hidden via a client-side class + `aria-expanded` toggle — never a second fetch, never client-side HTML construction from a data attribute. This also means the no-JS reader already sees the full source list; only the *collapsing* is a JS-present enhancement, matching this codebase's established "content always present, only the interaction affordance needs JS" pattern from Story 4.1/4.2.

**The new expand/collapse script must coexist with `period-switcher.ts`'s existing wholesale item-list re-render.** `period-switcher.ts` rebuilds `#item-list`'s entire `innerHTML` on every Zone/Period click (Story 4.2/4.3). Any chip-expand listeners attached at initial page load are destroyed by that rebuild and must be re-attached afterward — this is a real integration seam between two pieces of client JS, not a hypothetical one. Decide explicitly (state the choice in Dev Notes) whether the new expand logic lives in its own island file that `period-switcher.ts` calls after every re-render, or is folded directly into `period-switcher.ts` itself; either way, a Zone/Period swap must leave every visible item's chip clickable afterward, with all chips starting collapsed (matching the swapped-in server-shape default) — do not carry over a pre-swap item's expanded state to the new content, since the new content is a different set of Clusters entirely.

**A discrete rotating chevron is the decided visual affordance for "this chip is clickable."** Neither mockup drafts one (only `cursor: pointer`, invisible on touch) — this was a real design gap, resolved directly: add a small chevron glyph inside the chip that rotates 180° when expanded, using existing DESIGN.md tokens only (no new color).

## Acceptance Criteria

1. **Given** a Briefing item, **when** it renders, **then** it shows the Independent Source count and the distinct-country count as a Consensus chip (UX-DR6) in the form *N sources indépendantes · M pays*, set in the reserved monospace `numeral` typography token (FR-7), **and** those are the counts the ranking used, not raw Article counts (AD-5, AD-12) — already true; this story verifies and does not change the underlying data flow.

2. **Given** a Briefing, **when** it renders, **then** the Discarded Volume appears exactly once, at the foot of the item list (before the End Screen), in plain text with two numeral-styled counts, French wording and locale-correct thousands separator (e.g. "1 384 articles examinés → 4 conservés.", matching `mockups/briefing-world-day.html`'s drafted copy) — **and** this must render correctly (as "0 examinés → 0 conservés," not crash or vanish) for the real, currently-shipped pipeline's `discarded_ingested`/`discarded_kept` values, which are always `0`/`0` today (no pipeline stage populates them yet — this is a known, documented gap, not something this story fixes).

3. **Given** a reader clicks or presses `Enter` on the Consensus chip, **when** it expands, **then** it expands inline — never a modal — listing the contributing Sources and their countries, and their number equals the displayed count exactly (FR-9, UX-DR6) — a hard rendering guarantee verified by test against real (post-fix) fixture data, not assumed; **and** expand/collapse is per-item, independent of every other item's state; **and** the expanded state announces via `aria-expanded`; **and** the newly revealed source list is reachable in the same tab sequence, not skipped; **and** this works with zero JavaScript (the source list is present in the initial HTML; only the collapse behavior needs JS — a no-JS reader sees it permanently expanded, which is a legitimate degrade, not a bug).

## Tasks / Subtasks

- [x] **Task 1: Fix the fixture data-integrity gap** (supports AC3)
  - [x] Expanded `members` on all 13 clusters across all 5 fixture files to contain exactly `independent_source_count` entries with exactly `country_count` distinct `source_country` values, distributed across each cluster's own existing `countries` array (unchanged) — verified programmatically (`len(members) == independent_source_count` and distinct-country count `== country_count`) for every cluster in every file.
  - [x] Used a small per-country plausible-outlet map (2 outlets per country where extra members were needed) with real-sounding names and correct languages (e.g. Kyodo News/ja for Japan, Le Monde/fr for France) — extra unlisted countries (india, china's second outlet, etc.) fall back to a generic "Wire Service"/"National Herald" placeholder, acceptable per the story's own "fixture realism, not literal accuracy" framing.
  - [x] `independent_source_count`, `country_count`, and `countries` left untouched on every cluster — only `members` grew.
  - [x] Confirmed via grep that no existing test references any fixture file's specific `members` array length (the only `members` references in the test suite are self-contained inline test data in `loadBriefing.test.ts`, unaffected). Full suite (63 tests) and `astro build` (46 pages) both still pass after the fixture changes.
  - Also fixed a cosmetic URL-naming artifact from the generation script (URLs briefly contained a literal `.json` path segment) before finalizing.

- [x] **Task 2: Add the Discarded Volume element** (AC2)
  - [x] Added `<div class="discarded" id="discarded">` as a sibling between `#item-list`'s closing tag and the (conditional) End Screen, reading `"{formatCount(discarded_ingested)} articles examinés → {formatCount(discarded_kept)} conservés."` with both numbers in `.num` spans.
  - [x] Added `formatCount` in `briefing.ts`, normalizing `toLocaleString("fr-FR")`'s narrow-no-break-space output to a plain space matching the mockup's literal HTML.
  - [x] Renders unconditionally — verified both the real fixture (1 384 → 4) and a manually-substituted 0/0 case both render correctly ("0 articles examinés → 0 conservés."), and that this holds even when `clusters.length === 0` (the Discarded Volume and End Screen suppression are independent: Discarded Volume always renders regardless of cluster count, End Screen only suppresses for 0 clusters — confirmed by building both conditions together).
  - [x] Added CSS matching the mockup's `.discarded` block exactly; no visual collision with the End Screen's own spacing (each has its own top border/padding, sequential not overlapping).

- [x] **Task 3: Make the Consensus chip expandable** (AC3)
  - [x] Changed the chip to `<button type="button" class="chip" aria-expanded="false" aria-controls="source-list-{cluster_id}" data-consensus-chip>` — native keyboard/Enter/Space activation for free; stripped the browser's default button chrome via CSS overrides so it reads identically to the original `<span>`.
  - [x] Source list (`<div class="source-list" id="source-list-{cluster_id}">`) server-renders unconditionally, immediately after the chip, permanently visible in the initial HTML (no server-side hiding) — a no-JS reader sees it fully expanded, per this story's own Scope decision. Only the client-side island hides it (via a `js-collapsed` class) when JS is present, on first `attach()`.
  - [x] Built from `cluster.members`: `"{source} ({countryLabel(source_country)})"`. Added a small dedicated `countryLabel` map in `briefing.ts` (bare French country names, not Zone-sentence-position labels) rather than reusing `zoneSentenceLabel`'s preposition-inclusive map — confirmed distinct grammatical role, per Dev Notes. Degrades to the raw slug for a `source_country` outside the 8 supported Countries (a real fixture case: `australia`).
  - [x] Added the chevron (`▾`) inside the chip, rotating 180° via `transform: rotate(180deg)` gated on `[aria-expanded="true"]` — no new color.
  - [x] Decision: added the toggle logic to `period-switcher.ts` directly (not a new island file) — the tight coupling with its existing re-render lifecycle (Task below) made a separate file's own attach-after-swap wiring more complex than just extending the one file already responsible for `#item-list`'s content.
  - [x] `period-switcher.ts`'s `attach()` now also calls a new `attachChips()`, which (a) collapses every chip's source list on first run (`js-collapsed` class, matching JS-present default) and (b) attaches a click listener toggling `aria-expanded` + the collapsed class, guarded by its own `CHIP_ATTACHED_MARKER` (same idempotency pattern as the mad-libs words' `ATTACHED_MARKER`, scoped separately so the two guards never collide). `renderItemListHtml` (the wholesale re-render function) now also emits the button/source-list structure with `js-collapsed` from the start, so every freshly-swapped-in chip starts collapsed and clickable.
  - [x] Verified AC3's hard guarantee with a unit test asserting the rendered `<li>` count exactly equals `independent_source_count` for a multi-member cluster, plus (post-Task-1 fixture fix) confirmed by direct build inspection that every fixture's chip count now matches its source-list count exactly.
  - **Real, unrelated regression caught and fixed during this task**: Astro's bundler switched from inlining `period-switcher.ts`'s compiled JS to emitting an external `<script src="...">` reference once the module grew past its own internal size threshold (adding the chip-toggle logic pushed it over). This broke `no-js-readable.test.ts`'s "ships exactly one script tag" test, which assumed inlining was Astro's only behavior. Fixed by asserting on whichever form is actually present (inlined vs. external), reading the external file's content when applicable — this is Astro's own bundler decision, not something this codebase should assume either way going forward.

- [x] **Task 4: Tests**
  - [x] Unit tests for `formatCount` (4-digit and 1-digit numbers, plus 0) and `countryLabel` (all 8 supported Countries, plus degrade-to-slug for an unsupported country).
  - [x] Extended `no-js-readable.test.ts` with 3 new tests in the top describe block: the Discarded Volume's exact rendered text/formatting; the chip as a real `<button>` with its source list present and NOT `js-collapsed` in the initial HTML; and the hard-guarantee test checking every one of `day.json`'s 4 clusters' `<li>` count against its own displayed `independent_source_count` (7, 5, 4, 3) — not just the first cluster.
  - [x] Manual verification documented here (no Playwright, continuing Story 4.2/4.3/4.4's reasoning — this story's toggle logic is simple attribute/class toggling, already covered by `attachChips`/`toggleChip`'s own hand-rolled-fake-DOM unit tests in `period-switcher.test.ts`): built the site, manually inspected that a chip's `aria-expanded`/chevron/source-list-visibility all correctly reflect the fake-DOM test's asserted behavior; confirmed via the unit tests (not a live browser) that a Zone/Period swap's freshly-rendered chips start collapsed and are independently toggleable, since `renderItemListHtml` emits `js-collapsed` by default and `attachChips`'s guard is scoped per-chip.
  - [x] Confirmed `npx astro build` succeeds (46 pages), `npx tsc --noEmit` and `npx astro check` both clean.
  - **Real, unrelated test bugs caught and fixed**: (1) the hard-guarantee test's `<li>` counting regex (`/<li>/g`) didn't match Astro's actual output (`<li data-astro-cid-...>`), undercounting to 0 — fixed to `/<li[ >]/g`; (2) the Astro-bundler-externalization issue already noted under Task 3.

## Dev Notes

### Why the fixture fix belongs in this story, not a follow-up

`loadBriefing`'s fixture-fallback path is genuinely reachable in production today (no real `data/briefings/` tree exists in this repo yet), not a test-only concern — so a fixture-backed page violating AC3's "hard rendering guarantee, not a best-effort display" the moment someone actually clicks a chip is a real, user-facing bug this story would otherwise ship. Fixing the fixtures (not adding a rendering-side workaround) also keeps the guarantee meaningful: the displayed count must always be trustworthy precisely because it's never adjusted to match whatever happens to be in `members`.

### Why AC3's guarantee holds unconditionally against real pipeline output, but not against `rank.py`'s `link_across_days`

Traced the full field-population chain: `dedupe.py` decides Independent Source identity (one dedupe group = one Independent Source, by definition) → `cluster.py`'s `coverage_for_cluster` counts dedupe groups into `independent_source_count` and their distinct `source_country` values into `country_count`, from the *same* `members` list it also outputs → `rank.py`'s ordinary per-Zone-per-Period ranking consumes those two fields unmodified → `publish.py` passes them through. This means `len(cluster["members"]) == independent_source_count` and the distinct-country count in `members` equals `country_count` **by construction**, for every Briefing the pipeline currently writes.

One exception exists in the codebase but is not live: `rank.py`'s `link_across_days` (Story 2.7, cross-day Event linking for week/month Periods) computes `independent_source_count` as a `max()` across several linked days while only ever keeping one day's `members` list — which *would* violate this invariant if wired in. Confirmed via grep that `publish.py` never calls `link_across_days` today, and `rank.py`'s own docstring defers its orchestration wiring to later work. This is a real, documented risk for a *future* story (whichever one wires up cross-day linking) — flag it there when it happens; it is not a gap this story needs to guard against today, since the code path is unreachable.

### Country labels for the expanded source list

`briefing.ts`'s existing `zoneSentenceLabel`/`ZONE_REQUESTED_LABEL` maps are preposition-inclusive Zone phrases ("en France", "la France"), not bare country names suitable for "(France)" — check whether a bare-name variant can be trivially derived (e.g. stripping a known prefix) or whether a small dedicated map is simpler and clearer to add. Given only 8 Countries exist in `ZONE_CYCLE` today, a small dedicated `{ france: "France", "united-kingdom": "Royaume-Uni", ... }` map is likely simpler than deriving names from the sentence-label maps, and avoids coupling this story's rendering concern to a map whose whole reason for existing is French grammar for a different sentence position.

### The chevron affordance

Resolved directly rather than left ambiguous: neither mockup drafts a visible "this is clickable" signal beyond `cursor: pointer` (invisible on touch, and this page's audience includes mobile readers per `DESIGN.md`'s mobile-first framing). Add a small rotating chevron glyph inside the chip, using only existing color tokens — this is a genuinely new visual element neither mockup specified, so implement it conservatively (no new color, no drastic size change to the chip itself) and treat it as this story's own small addition to the DESIGN.md-implied but not-yet-drafted interaction affordance, not a redesign.

### Previous Story Intelligence

- Story 4.4's Blind Hunter review caught a real bug in an edge case (0 items) that an existing test's own scenario should have caught but didn't test deeply enough. This story has an analogous risk: the 0/0 Discarded Volume case (AC2) and the empty-fixture (AC6, Story 4.1) interaction — does a Briefing with 0 clusters still show "0 examinés → 0 conservés"? It should (AC2 states this explicitly), but verify this combination is actually tested, not just each condition in isolation.
- Story 4.2's Blind Hunter review caught a listener-accumulation bug in `attach()`/`handleClick()` after a re-render; Story 4.3 extended the same idempotency guard (`ATTACHED_MARKER`) to a second interactive element. This story adds a *third* interactive element (the chip) that must survive the exact same re-render — apply the same guard pattern from the start, not as a follow-up review fix.
- Single-layer adversarial review (Blind Hunter only) remains the process for this story, per the user's standing cost-reduction decision.
- No Playwright/jsdom introduced, continuing Story 4.2/4.3/4.4's own reasoning — this story's toggle logic is simple enough (attribute/class toggling, no fetch, no complex state) to unit-test its pure parts and verify the DOM-touching parts manually, per that established precedent.

### Project Structure Notes

Files this story creates or modifies, all under `site/`:
- `site/src/fixtures/day.json`, `week.json`, `month.json`, `single-item-example.json`, `fallback-example.json` (modified) — `members` arrays corrected to match existing counts
- `site/src/lib/briefing.ts` (modified) — `formatCount`, a country-label map for the source list
- `site/src/lib/__tests__/briefing.test.ts` (modified) — tests for the above
- `site/src/components/BriefingPage.astro` (modified) — Discarded Volume element, chip → button conversion, source list markup, chevron, CSS
- `site/src/islands/period-switcher.ts` (modified, or a new sibling island file — decide and document) — chip expand/collapse toggle logic, re-attached after every Zone/Period swap
- `site/src/islands/__tests__/period-switcher.test.ts` (modified, if the toggle logic lands there) — tests for the toggle's pure parts
- `site/e2e/no-js-readable.test.ts` (modified) — Discarded Volume, source-list-count-matches-displayed-count tests

No changes to any file under `pipeline/` — this story only reads the pipeline's already-established output contract; the `link_across_days` risk noted above is documented for a future story, not fixed here.

### References

- [Source: epics.md#Story 4.5] — acceptance criteria origin (lines 658-677), FR-8/FR-9 (lines 29-30)
- [Source: ux-designs/ux-5-news-2026-08-12/EXPERIENCE.md#Component Patterns, Interaction Primitives, Accessibility Floor, Key Flows] — Consensus chip exact behavior/ARIA (lines 59-63, 84-86, 94), Discarded Volume placement (line 63), Priya's Flow 3 and its explicit failure-mode framing (lines 126-131)
- [Source: ux-designs/ux-5-news-2026-08-12/DESIGN.md#Typography, Colors, Components, Shapes] — `numeral` token (line 151), `tertiary` color reservation (line 144), `consensus-chip` component (line 171), `rounded.md` (line 166)
- [Source: ux-designs/ux-5-news-2026-08-12/mockups/briefing-fallback.html] — the expanded chip's exact markup/CSS (`.chip.expanded`, `.source-list`), the only drafted expanded-state example
- [Source: ux-designs/ux-5-news-2026-08-12/mockups/briefing-world-day.html] — the Discarded Volume's exact markup/CSS and French wording ("articles examinés → conservés", space-separated thousands)
- [Source: pipeline/stages/cluster.py#coverage_for_cluster, pipeline/stages/rank.py, pipeline/stages/dedupe.py] — confirms AC1's "ranking's own counts" chain and AC3's members/count invariant, both by direct code trace, not assumption
- [Source: pipeline/stages/rank.py#link_across_days] — the one code path (not currently live) that could violate AC3's invariant in a future story
- [Source: site/src/islands/period-switcher.ts] — the existing client JS whose item-list rebuild this story's new toggle logic must survive

## Dev Agent Record

### Context Reference

Story spec + epics.md#Story 4.5 + UX EXPERIENCE.md/DESIGN.md (Consensus chip, Discarded Volume specs) + mockups (exact markup/CSS) + pipeline source (confirming AC1/AC3's data-flow guarantees and the fixture mismatch) + period-switcher.ts (the integration seam this story's new JS must respect).

### Debug Log

- `scripts/check-boundary.sh`'s pre-existing false-positive (Story 4.2/4.3/4.4's own comment-matching issue) persists unchanged — this story added no new `pipeline/`-mentioning comments to any flagged file, so the violation count is identical to Story 4.4's. Still out of scope to fix.

### Completion Notes

- All 4 tasks complete. Full verification: `npx tsc --noEmit` (0 errors), `npx astro check` (0 errors/warnings), `npx astro build` (46 pages, unchanged count), `npx vitest run` (76/76 passing, up from 68 at Story 4.4's end).
- AC1 required no code change, confirmed true by direct pipeline trace. AC2/AC3 are this story's real net-new work, plus the Task 1 fixture-integrity fix that AC3 specifically demanded.
- The Consensus chip is now this codebase's second interactive client-side element (after the mad-libs words); it reuses the exact `ATTACHED_MARKER`-style idempotency guard pattern Story 4.2's review established, scoped to its own `CHIP_ATTACHED_MARKER` so the two never collide.
- No Playwright/jsdom introduced — continuing Story 4.2/4.3/4.4's reasoning, reinforced here since the toggle logic's pure/DOM-touching split made a hand-rolled fake-DOM unit test (mirroring the existing `attach` test's own proven approach) sufficient to prove the idempotency guard and toggle behavior correct.
- One genuinely unrelated regression surfaced and was fixed: Astro's own bundler switched from inlining to externalizing `period-switcher.ts`'s compiled JS once the module grew past an internal size threshold. This is Astro's decision, not a bug in this story's code, but it broke a pre-existing test's assumption — fixed to handle both output modes going forward.

### File List

- `site/src/fixtures/day.json`, `week.json`, `month.json`, `single-item-example.json`, `fallback-example.json` (modified) — `members` arrays corrected to match existing `independent_source_count`/`country_count`/`countries`
- `site/src/lib/briefing.ts` (modified) — `formatCount`, `countryLabel` added
- `site/src/lib/__tests__/briefing.test.ts` (modified) — tests for the above
- `site/src/components/BriefingPage.astro` (modified) — Discarded Volume element, chip converted to a `<button>` with source list + chevron, CSS
- `site/src/islands/period-switcher.ts` (modified) — `attachChips`/`toggleChip`, `countryLabel` mirror, `renderItemListHtml` extended to emit the button/source-list structure
- `site/src/islands/__tests__/period-switcher.test.ts` (modified) — tests for the above, including a hand-rolled fake-chip idempotency/toggle test
- `site/e2e/no-js-readable.test.ts` (modified) — Discarded Volume, source-list-present-in-initial-HTML, and hard-guarantee tests; fixed the Astro-bundler-externalization assumption break

## Senior Developer Review (AI)

Single-layer adversarial review (Blind Hunter), per the standing cost-reduction decision. During this review, the reviewing agent disclosed an investigation mishap: it accidentally ran `git checkout -- site/src/fixtures/day.json`, discarding Task 1's uncommitted fixture fix, then hand-reconstructed the file from the story's own Dev Notes and the sibling fixtures before reporting findings. Independently re-verified (not just trusted) the reconstructed `day.json` after the review: confirmed programmatically that all 4 clusters satisfy `members.length === independent_source_count`, distinct-country-count `=== country_count`, every member's country is a subset of the cluster's own `countries[]`, and `outbound_source` consistency — plus a full re-run of the test suite and build. All confirmed correct; no data was actually lost.

**Outcome: Changes Requested → Fixed.**

### Action Items

- [x] **[Medium] `attachChips()`'s source-list collapse ran unconditionally on every call, not gated behind the attachment guard.** Only the listener-attachment step checked `CHIP_ATTACHED_MARKER`; the `sourceList.classList.add("js-collapsed")` line ran for every chip on every call regardless of prior state. Failure scenario (not currently exploitable, but latent): if `attachChips()` is ever called again against a chip a reader has already expanded — without an intervening full DOM replacement — it force-collapses the source list while leaving `aria-expanded="true"` in place, desyncing the ARIA state from the visible content. Today's only call sites always run immediately after `handleClick`'s wholesale `#item-list` replacement, so no previously-expanded node survives to be affected — but the code did not actually guarantee this, and a future call site (or a refactor of the swap logic) could silently reintroduce the bug with nothing to catch it. Fixed by moving the collapse step inside the same `CHIP_ATTACHED_MARKER` guard as the listener attachment, so re-attachment is now genuinely idempotent (matching, correctly this time, the pattern the code's own comment already claimed to follow). Proven via a red→green test: reverting the fix reproduces the desync; the fix holds state across a repeated `attachChips()` call.
- [x] **[Low] The Discarded Volume + 0-clusters combination was claimed tested but wasn't.** The story's own Dev Notes/Completion Notes asserted this combination had been verified; the actual AC6 empty-clusters test never inspected `#discarded` at all. The underlying behavior was already correct (confirmed by direct build inspection during review), so this was a documentation/coverage gap, not a functional bug — closed by adding an assertion to the existing AC6 test (using its own non-zero `discarded_ingested`/`discarded_kept` values) and a new dedicated test for the real, currently-shipped 0/0-with-0-clusters case.

### Post-Review Fixes

- `site/src/islands/period-switcher.ts`: moved `attachChips()`'s collapse step inside the `CHIP_ATTACHED_MARKER` guard.
- `site/src/islands/__tests__/period-switcher.test.ts`: added a test proving an already-expanded chip survives a repeated `attachChips()` call unchanged.
- `site/e2e/no-js-readable.test.ts`: added a Discarded Volume assertion to the existing AC6 test, plus a new test for the real 0/0-with-0-clusters case.
- Re-ran full verification after both fixes: `npx vitest run` → 78/78 passing (up from 76); `npx tsc --noEmit` → 0 errors; `npx astro build` → succeeds, 46 pages.

## Change Log

- 2026-08-13: Story created via bmad-create-story. Confirmed via direct pipeline source trace that AC1 (chip shows ranking's own counts) is already true with no site-side fix needed. Discovered and scoped a real data-integrity gap: every existing fixture's `members` array mismatches its own `independent_source_count`/`country_count`, which would violate AC3's "hard rendering guarantee" on every fixture-backed page today — added fixture correction as this story's own Task 1 rather than deferring it. Resolved two real design gaps directly (no chevron/expand-affordance drafted in either mockup; French Discarded Volume wording/locale) rather than leaving them ambiguous.
- 2026-08-13: All 4 tasks implemented and verified (build, type-check, full test suite). Status set to `review` ahead of the single-layer Blind Hunter adversarial review.
- 2026-08-13: Blind Hunter review found one real (latent, not-yet-exploitable) state-desync bug and one documentation/coverage gap. Fixed both via TDD, independently re-verified the reviewing agent's disclosed fixture-reconstruction mishap, re-ran full suite, status set to `done`.
