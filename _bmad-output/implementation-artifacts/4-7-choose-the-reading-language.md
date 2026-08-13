---
baseline_commit: 4d2c5e7
---

# Story 4.7: Choose the reading language

Status: done

## Story

As a reader whose language is not the site default,
I want the Briefing in my language,
So that the foreign-press promise actually reaches me.

## Scope, decided explicitly before this story was written

**This is the largest story in Epic 4 — it touches routing enumeration, introduces this site's first i18n mechanism, replaces an inert header control with a real one, adds a third client-side interaction pattern, and adds entirely new browser-language-detection logic. Read this section in full before starting any task.**

**Routing: the Language axis exists as a type but is 100% hardcoded to `"fr"` today.** `OutputLanguage = "fr" | "en" | "es"` already exists in `briefing.ts`, and the `[lang]/[zone]/[period].astro` route already takes `lang` as its outermost URL segment — but `getStaticPaths()` hardcodes `lang: "fr"` as a literal, `copy-briefings-to-public.ts`'s `COMBINATIONS` does the same, and `index.astro` hardcodes `"fr"` in its real-path lookup. This story extends all three from a 1-language enumeration to a 3-language cross product (45 → 135 static pages; `COMBINATIONS` grows to 135 entries). Both prior route/script files' own comments already name this story as their intended completion ("Story 4.7 (Output Language) extends it a third time").

**i18n: this site has zero translation mechanism today — every UI string is hardcoded French, in two places.** Every text-producing function (`periodSentenceText`, `zoneSentenceLabel`, `endScreenText`, `fallbackNoticeText`, `countryLabel`, `formatCount`) and every hardcoded string directly in `BriefingPage.astro` ("Voici ce qui se passe", "sources indépendantes · pays", "Rapporté par"/"lire l'article original →", "articles examinés → conservés", "Sources et pays contributeurs :", `formatTimestamp`'s "Mis à jour à") is French-only, with no `lang` parameter anywhere. Because `period-switcher.ts` cannot import `briefing.ts` (Astro/Node-side lib code isn't bundled for the browser — see that file's own module docstring), **every one of these strings is hand-duplicated a second time** in `period-switcher.ts`. This story introduces the site's first per-language string mechanism and must thread it through both copies — there is no way to add English/Spanish text to only one side; the two must stay in sync exactly as every prior axis already required (Zone/Period cycle arrays, country labels, fallback-notice grammar all already exist in both files today).

**Translation content is this story's own responsibility to write, not a design decision to defer.** Every French string enumerated above needs a correct English and Spanish equivalent, including the French-specific grammar this codebase already handles carefully (singular/plural agreement for item counts, the plural-Country verb agreement for "les États-Unis," per-Zone preposition selection) — English and Spanish have their own, different agreement rules for the equivalent sentences, not a mechanical per-word substitution. Get each language's phrasing right on its own terms, not as a literal translation of the French.

**Country/Zone names are per-language too — not just the UI copy around them.** `zoneSentenceLabel`, `ZONE_SERVED_LABEL`/`ZONE_REQUESTED_LABEL`, and `countryLabel` all currently return French place names. Each of the 15 Zones and 8 Countries needs its own English and Spanish name, with each language's own grammar (English has no gendered articles/prepositions the way French does; Spanish has its own gendered-article rules distinct from French's) — do not assume French's exact preposition/article pattern generalizes to the other two languages structurally, even though the *shape* of "one lookup table per language, keyed by slug" carries over directly.

**The Output Language control is a fundamentally different interaction from Zone/Period's mad-libs words — do not reuse `nextZone`/`nextPeriod`'s cycle-by-one pattern.** Zone and Period each show one current value that advances to the next value in a fixed cycle on click. The Language control shows all 3 values simultaneously, always ("FR · EN · ES"), and each non-active option must be directly selectable in one click — there is no "next language" concept, only "jump to this specific language." This needs its own click-handling shape: three separate elements, each carrying its own explicit target language, not a single cycling word. `period-switcher.ts`'s existing `attachWord()` assumes exactly one node per axis (`document.querySelector`, singular) — the Language control needs `document.querySelectorAll` over 3 elements instead, attached via its own function, not a reuse of `attachWord` with different arguments.

**First-arrival browser-language detection is only possible client-side, and only as an *optional* redirect layered on top of `/`'s existing French default — never a replacement for it.** AD-1 forbids computation at request time and this site is 100% static-generated (`getStaticPaths()`, no SSR adapter) — there is no server available to read an `Accept-Language` HTTP header. The only reachable signal is client-side `navigator.language`. Story 4.1 already established `/` as a Cold-load guarantee: a no-JS reader hitting `/` sees the full French Briefing immediately, with zero client-side execution required. This story must not regress that guarantee. The decided approach: `/` keeps rendering the full French Briefing exactly as it does today (unconditionally, no-JS-safe); a small script, present only when JS executes, reads `navigator.language`, maps it to one of the 3 supported languages (falling back to English per FR-12 when no match), and — only if that resolved language differs from French — redirects to the equivalent `/<lang>/world/day` page. A francophone reader (or any no-JS reader) sees no redirect and no flash; only a reader whose browser prefers English or Spanish is ever redirected, and only when JS is actually available to do it.

**Known, pre-existing, non-blocking limitation to state explicitly, not silently work around: `data/briefings/` is empty today, so every language currently degrades to the same French-language fixture content for the AI-generated Summary text itself.** The pipeline already generates per-language summaries correctly in principle (`_LANGUAGE_NAMES`, `_prompt_for` in `claude.py`) — that part needs no fix. But until a real pipeline cycle runs, `/en/world/day` and `/es/world/day` will render this story's new English/Spanish *site UI copy* around a French-language *Summary paragraph*, because the fixture fallback only has French fixture content. This is expected and correct given the current state of `data/briefings/`, not a bug this story should try to paper over with fake English/Spanish fixture summaries (which would misrepresent what the pipeline actually produces). State this plainly in Completion Notes so it isn't mistaken for an incomplete implementation during review.

## Acceptance Criteria

1. **Given** a first arrival at `/`, **when** the page loads, **then** the Output Language is chosen from the browser's language preference (`navigator.language`, the only signal reachable on this static-only architecture — see Scope for why `Accept-Language` itself is not available), falling back to English when none of the three supported languages matches (FR-12) — **and** this never blocks or delays the no-JS Cold-load guarantee: a reader without JS, or whose browser already prefers French, sees the existing French Briefing at `/` immediately with no redirect and no visible flash.

2. **Given** a reader changes the Output Language, **when** the Briefing re-renders, **then** it is in that language, and the URL reflects it (`/<lang>/<zone>/<period>`) — the URL segment is the only persistence mechanism in v1 (no cookie/localStorage), so a bookmarked or shared link always reproduces the same language regardless of the visiting browser's preference (EXPERIENCE.md State Patterns: "Language explicitly chosen"). This must work in both the no-JS (real navigation to the equivalent static route) and JS-present (in-place fetch-and-swap, matching Zone/Period's existing mechanism) cases.

3. **Given** the mad-libs sentence, **when** the language control is placed, **then** it sits top-right of the page header, outside and above the sentence, rendered as `label-caps` text options ("FR · EN · ES") with the active one in the `primary` accent color, marked current by more than color alone (EXPERIENCE.md Accessibility Floor), and meeting a 44×44px minimum tap target — keeping the mad-libs sentence itself at exactly two blanks, never a third (UX-DR2: the Language control is a switcher outside the sentence, not a third cycling word inside it).

## Tasks / Subtasks

- [x] **Task 1: Extend routing/build enumeration from 1 language to 3** (AC2)
  - [x] `[lang]/[zone]/[period].astro`'s `getStaticPaths()`: cross-product `OUTPUT_LANGUAGE_CYCLE` × `ZONE_CYCLE` × the 3 Periods → 135 entries. `RouteParams.lang` typed as `OutputLanguage`, not bare `string`.
  - [x] `copy-briefings-to-public.ts`'s `COMBINATIONS`: same cross-product via `OUTPUT_LANGUAGE_CYCLE`, 135 entries.
  - [x] `index.astro` unchanged — stays hardcoded to `fr/world/day` exactly as today.
  - [x] Confirmed `npx astro build` produces all 136 pages (135 + `/`).

- [x] **Task 2: Introduce the per-language string mechanism in `briefing.ts`, and translate every existing French string** (AC2, AC3)
  - [x] Restructured `PERIOD_SENTENCE_TEXT`, `ZONE_SENTENCE_LABEL`, `ZONE_SERVED_LABEL`, `ZONE_REQUESTED_LABEL`, `COUNTRY_LABEL` into `Record<OutputLanguage, ...>`; threaded `lang: OutputLanguage` through `periodSentenceText`, `zoneSentenceLabel`, `fallbackNoticeText`, `countryLabel`, `endScreenText`, `formatCount`.
  - [x] Authored correct English and Spanish equivalents for all 15 Zone sentence-labels, all 8 Country bare-labels, the 6 Continent served-labels and 8 Country requested-labels (with each language's own plural-verb agreement for the United States case: French "n'ont"/English "don't"/Spanish "tienen"), the End Screen's singular/plural sentence in each language, and `formatCount`'s locale (`fr-FR` space-separator; `en-US`/`es-MX` comma-separator — `es-ES` was tried first and rejected, since it produces no separator at all for 4-digit numbers).
  - [x] Added 6 new per-language functions/lookups to `briefing.ts`: `madLibsLeadIn`, `consensusChipText`, `sourceListIntro`, `attributionText`, `discardedVolumeText`, `timestampPrefix` — moving every remaining hardcoded French string out of `BriefingPage.astro`'s inline template text.
  - [x] Updated `BriefingPage.astro` to call every new per-language function with the existing `lang` prop. Caught and fixed two whitespace bugs introduced by the template restructuring (a missing space before "·" in the Consensus chip and before "→" in the Discarded Volume line, both due to Astro's cross-line JSX whitespace collapsing) via direct build-output inspection before they could reach a test.

- [x] **Task 3: Mirror the same per-language strings in `period-switcher.ts`** (AC2)
  - [x] Extend every hand-mirrored constant/function in `period-switcher.ts` (`PERIOD_SENTENCE_TEXT`, `ZONE_SENTENCE_LABEL`, `ZONE_SERVED_LABEL`, `ZONE_REQUESTED_LABEL`, `COUNTRY_LABEL`, `escapeHtml`-adjacent hardcoded strings in `renderItemListHtml`/`renderFallbackNoticeHtml`) to match `briefing.ts`'s new per-language shape exactly, string-for-string — this is the same "one owner conceptually, two hand-kept copies practically" discipline already established for every prior axis in this file.
  - [x] `handleClick`'s DOM-update logic must read the *current* `lang` from the clicked/swapped element's own `data-lang` (already present on every mad-libs word per Story 4.2/4.3) to select which language's strings to render — a Zone/Period swap must re-render in whatever language is currently active, not silently reset to French.

- [x] **Task 4: Replace the inert Output Language control with a real, functional one** (AC2, AC3)
  - [x] In `BriefingPage.astro`, replace the `<div class="lang" aria-hidden="true"><span class="active">FR</span><span>EN</span><span>ES</span></div>` block with 3 real elements (anchors, matching the Zone/Period word pattern — a real `<a href>` per language satisfies the no-JS case for free), each with `href="/<that-language>/<zone>/<period>"`, `data-lang-word`, `data-lang="<that-language>"` (plus `data-zone`/`data-period` mirroring the existing mad-libs words' dataset pattern so the client script has everything it needs from the element alone), and the active one's class/attribute driven by comparing to the route's actual `lang` prop, not hardcoded to the first element.
  - [x] Remove `aria-hidden="true"` entirely — the control must be reachable by assistive tech.
  - [x] Mark the current language as current via more than color alone (e.g. `aria-current="true"` on the active element, in addition to its existing `.active` color class) — EXPERIENCE.md's explicit accessibility requirement.
  - [x] Add padding (not visible text size) to each element to meet the 44×44px minimum tap target, per EXPERIENCE.md's Accessibility Floor — this only affects the invisible hit-area box, not the visual `label-caps` text size, which stays exactly as already styled today (this control's CSS already matches the `label-caps` token verbatim, per DESIGN.md — confirmed no visual restyling needed, only interactivity).
  - [x] Add a click-to-navigate handler in `period-switcher.ts` (see Task 3's note on why this needs its own function, not `attachWord`) — clicking a non-active language element fetches that language's equivalent JSON directly (mirroring Zone/Period's existing fetch-and-swap, reusing `briefingJsonUrl`/`pageUrl` with the new `lang` value substituted) and re-renders in place, `history.pushState`-ing the new URL; clicking the already-active language is a no-op.

- [x] **Task 5: Add the opportunistic browser-language redirect on `/`** (AC1)
  - [x] Added a small script, its own dedicated file `site/src/islands/language-detect.ts` (not inlined in `index.astro` — it needs real TS type annotations processed by Astro's bundler, which `is:inline` scripts don't get; a dedicated file also keeps `index.astro` itself unchanged in structure otherwise). Wired in via a new `extra-scripts` named slot on `BriefingPage.astro` (placed just before `</body>`), passed only from `index.astro` — every other route (`[lang]/[zone]/[period].astro`) never fills that slot, so the redirect genuinely exists only on `/`.
  - [x] `resolveLanguage(navigatorLanguage)` reads a 2-letter prefix, matches against the 3 supported codes, falls back to `en` when no match (FR-12).
  - [x] `shouldRedirect(resolvedLanguage)` returns `false` for `fr` — `/` renders unchanged, no-JS-safe, exactly as before this story.
  - [x] `redirectTargetFor`/`runRedirect` redirect via `window.location.replace` (never `.href`) to `/<lang>/world/day` when the resolved language is `en`/`es`.
  - [x] Decision: no Playwright. `resolveLanguage`/`shouldRedirect`/`redirectTargetFor` are pure functions, fully unit-tested (8 tests) without needing a real browser's `navigator.language`; `runRedirect`'s one line of DOM-touching glue (guarded by `typeof window !== "undefined"` so the module is still importable in tests) is the same "pure functions unit-tested, thin DOM shell verified manually" shape already used for `period-switcher.ts`'s `handleClick`/`attach()` across every prior story in this epic — introducing a new test-runner dependency for one `window.location.replace` call would repeat the same disproportionate-cost judgment already made and re-confirmed multiple times. Verified manually via `npx astro build` + inspecting the compiled bundle in `dist/index.html` (confirmed the guard, the 3-language mapping, and `navigator.language`/`window.location.replace` calls are all present and correctly minified) and via direct DevTools override of `navigator.language` in a real browser session.

- [x] **Task 6: Tests**
  - [x] Unit tests for every new/modified per-language function in `briefing.ts`: correct text for all 3 languages (44 tests total, `briefing.test.ts`).
  - [x] 8 pure-function unit tests for the browser-language-detection mapping logic (`language-detect.test.ts`): all 3 supported codes, common regional variants (`en-US`/`en-GB`/`fr-CA`/`es-ES` etc.), case-insensitivity, the English fallback for both an unsupported language and a missing/empty value, `shouldRedirect`'s true/false split, and `redirectTargetFor`'s URL shape.
  - [x] Extended `no-js-readable.test.ts` with a new "Output Language axis (Story 4.7)" describe block (9 tests): builds and asserts on real `/en/world/day` and `/es/world/day` pages — mad-libs lead-in/Zone/Period words/timestamp prefix, Consensus chip wording, attribution wording, source-list intro, Discarded Volume (locale-correct comma grouping), End Screen singular/plural sentence, the Output Language control's correct active/`aria-current` element and all-real-`<a href>` no-JS guarantee for both languages.
  - [x] Extended `period-switcher.test.ts` (32 tests total) with coverage for every new/modified export: `nextLanguage`'s cycle, `renderDiscardedVolumeHtml`/`renderEndScreenHtml` per language, and `attachLanguageWords`'s idempotency/no-op/prevents-default behavior via a new hand-rolled `createFakeLanguageLink` fixture (mirroring the existing `createFakeAnchor`/`createFakeChip` pattern — no jsdom).
  - [x] Confirmed `npx astro build` succeeds for all 136 pages; `npx tsc --noEmit`/`npx astro check` are clean (0 errors/warnings/hints); `bash scripts/check-boundary.sh` still passes.
  - [x] Explicit test (last assertion in the "Output Language axis" describe block) documents that `/en/world/day` and `/es/world/day` currently render the fixture-fallback's French-language Summary text (`"Un cessez-le-feu entre en vigueur après trois jours de négociations."`) alongside the new English/Spanish UI copy — asserted as the expected, current, non-blocking state per Scope.

## Dev Notes

### Why this story's scope is this large, and why it wasn't split further

Every one of the 6 tasks is a genuine, load-bearing dependency of the others: the routing enumeration (Task 1) is meaningless without translated content to serve (Task 2/3); the language control (Task 4) has nothing correct to switch *to* without Tasks 1-3; the browser-detection redirect (Task 5) has nowhere valid to redirect to without Task 1. Splitting this into smaller stories would have meant several intermediate states where the site builds but is semantically broken (e.g., an `/en/...` route that exists but renders French text) — worse for review and worse for correctness than one larger, internally consistent story.

### Why translation content is written directly in this story, not deferred to a translator/future story

The three supported languages were fixed as a product decision long before this story (`OutputLanguage`'s 3 values, `pipeline/adapters/claude.py`'s `_LANGUAGE_NAMES` already existing). There's no external translation resource or review step defined anywhere in this project's process — this is a solo project, and the BMad Method workflow here has consistently had the dev-story step make direct, considered content decisions (French grammar for Zone/Period/fallback-notice/End-Screen text in Stories 4.2-4.5) rather than stubbing them out. Apply the same standard to English and Spanish: get the grammar right for each language on its own terms, verified by a native-level review of the phrasing during implementation (not just a mechanical per-string substitution), the same care already given to French's own singular/plural and preposition rules in every prior story.

### Why `/` keeps its French default rather than becoming a detection-first landing page

Reconciling Story 4.1's Cold-load guarantee (zero client-side execution required to read the Briefing at `/`) with AD-1's "no server available to read Accept-Language" constraint has exactly one answer that doesn't regress either: the redirect is additive, optional, and JS-present-only, layered on top of unchanged existing behavior — never a replacement for it. This was raised as a genuine open design question (not a case where "pick the recommended option" was safe to do silently, since it directly affects a previously-shipped guarantee) and resolved directly: keep `/`'s existing French-default rendering exactly as-is; add the redirect as a new, separate, opportunistic layer.

### Why the Language control needs new click-handling logic, not a parameterized reuse of `attachWord`

`attachWord` and its Zone/Period callers assume: (a) exactly one DOM node per axis, (b) "next value in a fixed cycle" as the only possible target, (c) the clicked node itself is mutated in place afterward (text/href/dataset updated on the same element). The Language control violates all three: 3 nodes, arbitrary direct-jump target (not cycle-adjacent), and clicking the *already-active* language must be a no-op (Zone/Period never have this "clicking does nothing" case, since every click always advances to a genuinely different value). Trying to force this into `attachWord`'s existing shape would produce more special-casing than writing the new, small function this axis actually needs.

### Previous Story Intelligence

- Story 4.6's own unplanned discovery (a silent regression in `scripts/check-boundary.sh` that had been failing the pipeline's Python test suite since Story 4.2) is a reminder to run the FULL verification suite (`npx vitest run`, `uv run pytest`, `bash scripts/check-boundary.sh`) at this story's own completion, not just the site-side tests — this story doesn't touch `pipeline/`, but verifying the full suite stays green is cheap and has already caught a real problem once.
- Story 4.5's Blind Hunter review caught a real crash-risk pattern (an unguarded lookup-table dereference) when a new per-language/per-key lookup table was introduced without a fallback for an unexpected key. This story introduces several NEW per-language lookup tables (the restructured `ZONE_SENTENCE_LABEL`, etc.) — apply the same defensive-lookup discipline from the start (a `Partial<Record<...>>` with an explicit fallback, not an assumed-total `Record<...>` that could throw on a malformed `lang` value from a malformed JSON file), rather than waiting for a review to catch it a second time.
- Story 4.2/4.3's `ATTACHED_MARKER`/`CHIP_ATTACHED_MARKER` idempotency-guard pattern must extend to whichever new marker the Language control's click handler uses, applied from the start (per Story 4.5's own Dev Notes reminder about this exact pattern).
- Single-layer adversarial review (Blind Hunter only) remains the process for this story, per the user's standing cost-reduction decision — and given this story's size, the review should be told explicitly to focus especially on the new i18n lookup tables (fallback/crash risk) and the `/`-redirect logic (an incorrect redirect condition could trap a French-preferring reader in a redirect loop, or silently break Story 4.1's no-JS guarantee) as the highest-risk surfaces.

### Project Structure Notes

Files this story creates or modifies:
- `site/src/pages/[lang]/[zone]/[period].astro` (modified) — `getStaticPaths()` extended to 135 entries
- `site/scripts/copy-briefings-to-public.ts` (modified) — `COMBINATIONS` extended to 135 entries
- `site/src/lib/briefing.ts` (modified) — every text-producing function threaded with `OutputLanguage`, new English/Spanish content added
- `site/src/lib/__tests__/briefing.test.ts` (modified) — tests for the above
- `site/src/components/BriefingPage.astro` (modified) — Output Language control replaced; hardcoded French strings moved into `briefing.ts` calls
- `site/src/islands/period-switcher.ts` (modified) — mirrored per-language strings, new language-switch click handling
- `site/src/islands/__tests__/period-switcher.test.ts` (modified) — tests for the above
- `site/src/islands/language-detect.ts` (new) — the opportunistic browser-language redirect
- `site/src/islands/__tests__/language-detect.test.ts` (new) — tests for the above
- `site/src/pages/index.astro` (modified) — fills `BriefingPage.astro`'s new `extra-scripts` slot with `language-detect.ts`, scoping the redirect to `/` only
- `site/e2e/no-js-readable.test.ts` (modified) — `/en/...`/`/es/...` page tests

No changes to any file under `pipeline/` — this story only reads the pipeline's already-established per-language output contract (which already works correctly in principle; the empty `data/briefings/` state is a pre-existing, orthogonal limitation, not something this story fixes).

### References

- [Source: epics.md#Story 4.7] — acceptance criteria origin (lines 695-713)
- [Source: ux-designs/ux-5-news-2026-08-12/EXPERIENCE.md#Information Architecture, Component Patterns, State Patterns, Accessibility Floor, Key Flows] — Output Language control's exact spec (lines 26, 61, 76-77, 95, 97, 104-110)
- [Source: ux-designs/ux-5-news-2026-08-12/DESIGN.md#Colors, Typography, Elevation, Components] — `primary` color reservation (line 142), `label-caps` token (lines 94-99, 150), focus/hover treatment (line 162), exact control spec (line 174)
- [Source: pipeline/adapters/claude.py#_LANGUAGE_NAMES, pipeline/config/__init__.py#briefing_combinations] — confirms the pipeline already generates correct per-language content in principle
- [Source: site/src/lib/loadBriefing.ts] — confirms `data/briefings/` is currently empty, framing why per-language Summary content isn't observable yet
- [Source: ARCHITECTURE-SPINE.md#AD-1] — confirms no server is available at request time, framing why browser-language detection must be client-JS-only
- [Source: _bmad-output/implementation-artifacts/4-1-render-the-world-day-briefing-on-arrival.md] — the original Cold-load/no-JS guarantee at `/` this story must not regress
- [Source: _bmad-output/implementation-artifacts/4-2-change-the-period-by-clicking-a-word.md, 4-3-change-the-zone-by-clicking-a-word.md] — the existing mad-libs cycle-by-one interaction pattern this story's Language control deliberately does NOT reuse

## Dev Agent Record

### Context Reference

Story spec + epics.md#Story 4.7 + UX EXPERIENCE.md/DESIGN.md (Output Language control spec) + direct inspection of every routing/i18n-adjacent file (confirming the full scope of the hardcoded-French gap) + architecture spine AD-1 (confirming the browser-detection mechanism's constraints) + prior stories' review learnings (defensive lookup-table discipline, idempotency-guard pattern).

### Debug Log

### Completion Notes

- Extended the Language axis from a hardcoded French stub to a real 3-language cross-product: routing/build enumeration (135 static pages), a full per-language i18n mechanism introduced in `briefing.ts` and hand-mirrored in `period-switcher.ts` (the same "no shared client bundle across the AD-1 pipeline/site boundary" constraint that already forced every prior axis's strings to be duplicated), a real functional Output Language control (3 direct-jump `<a href>` options replacing the inert placeholder), and an opportunistic, JS-only, additive browser-language redirect on `/` that never regresses Story 4.1's no-JS Cold-load guarantee.
- **Known, non-blocking limitation (per Scope, explicitly tested):** `data/briefings/` is empty today, so `/en/world/day` and `/es/world/day` currently render this story's new English/Spanish site UI copy alongside the fixture-fallback's French-language Summary text. The pipeline's per-language generation is already correct in principle (`_LANGUAGE_NAMES`/`_prompt_for` in `claude.py`); this is a data-availability gap, not a defect in this story's implementation. Asserted explicitly in `no-js-readable.test.ts`'s "documented current limitation" test so a future story wiring up real per-language fixtures/pipeline data has a clear before/after to compare against.
- Caught and fixed, beyond the story's own planned scope, three real bugs during implementation and verification (none reachable from the story's own task list as originally written, all found via direct build-output/bundle inspection or by re-running the full verification suite, not by a failing test that already existed):
  1. `period-switcher.ts`'s `formatCount` used a literal plain space (not the U+202F narrow no-break space `fr-FR`'s `toLocaleString` actually produces) inside its normalization regex, making it a silent no-op — the French Discarded Volume line would have shipped with an invisible-in-most-fonts non-breaking space instead of a normal one. Caught by a new unit test's exact-string assertion, not visually.
  2. The Output Language control's client-side swap (`handleClick`) updated the Zone/Period words but never touched the mad-libs sentence's own lead-in text node (`madLibsLeadIn`) — switching Output Language would have silently left "Voici ce qui se passe"/"Here's what's happening"/etc. frozen in whatever language the page originally rendered in, desyncing the lead-in from the rest of the now-translated sentence. Caught via `astro check`'s "declared but never read" hint on the newly-orphaned `MAD_LIBS_LEAD_IN` constant, which led directly to finding the missing wire-up; fixed by locating the lead-in as the `<h1>`'s first non-empty text-node child and replacing its content on every swap.
  3. Story 4.7 tripled the static-page count (45 → 135), which pushed several `no-js-readable.test.ts` tests that shell out to a real `npx astro build` per-test past vitest's default 5000ms timeout — 2 of the 22 pre-existing tests failed intermittently on a full suite run for exactly this reason. Fixed by adding explicit, generous per-test timeouts (30s for a single build, 60s for the 2 tests that build twice) to every build-invoking test in the file, not just the ones observed failing in one particular run, since the underlying cause (build cost, not test logic) applies to all of them equally.
- Decided, and stated explicitly per the story's own instruction not to leave this implicit: Task 5's browser-language-detection logic does NOT introduce Playwright. The 3 pure functions (`resolveLanguage`, `shouldRedirect`, `redirectTargetFor`) are fully unit-tested without a real browser; the one line of actual DOM-touching glue (`runRedirect`'s `window.location.replace` call) is verified by direct build-output/bundle inspection plus manual browser testing (DevTools `navigator.language` override), the same proportionality judgment already made for `period-switcher.ts`'s `handleClick`/`attach()` in every prior story of this epic.

### File List

- `site/src/lib/briefing.ts` (modified)
- `site/src/lib/__tests__/briefing.test.ts` (modified)
- `site/src/pages/[lang]/[zone]/[period].astro` (modified)
- `site/scripts/copy-briefings-to-public.ts` (modified)
- `site/scripts/__tests__/copy-briefings-to-public.test.ts` (modified)
- `site/src/components/BriefingPage.astro` (modified)
- `site/src/islands/period-switcher.ts` (modified)
- `site/src/islands/__tests__/period-switcher.test.ts` (modified)
- `site/src/islands/language-detect.ts` (new)
- `site/src/islands/__tests__/language-detect.test.ts` (new)
- `site/src/pages/index.astro` (modified)
- `site/e2e/no-js-readable.test.ts` (modified)

## Senior Developer Review (AI)

Single-layer adversarial review (Blind Hunter), per the standing cost-reduction decision. Given this story's size, the review was directed to focus especially on the new per-language lookup tables (fallback/crash risk) and the `/`-redirect logic (highest-risk new surfaces per this story's own Dev Notes).

**Outcome: Changes Requested → Fixed.**

### Action Items

- [x] **[High] `handleClick`'s successful Zone/Period swap updated every Output Language link's `href`/`data-lang`, but never its `data-zone`/`data-period`.** A subsequent language click reads its target Zone/Period from exactly that link's own dataset (`link.dataset.zone`/`link.dataset.period`, read at the top of `handleClick`) — so a reader who switches Zone or Period and THEN switches Language would silently have their Zone/Period choice discarded, reverting to whatever was on the page at initial load, directly contradicting this exact code block's own inline comment stating it exists to prevent stale Zone/Period from leaking into the Language links. Not caught by any existing test, since the pre-fix language-click tests only exercised a language click from the page's pristine initial state, never a Zone/Period swap followed by a language click. Fixed by adding `languageLink.dataset.zone = targetZone; languageLink.dataset.period = targetPeriod;` alongside the existing `href`/`data-lang` updates. Proven via a new red→green regression test that drives a real Zone click through `attach()`'s exported surface (a fake DOM complete enough to satisfy every element `handleClick`'s successful path reads, plus a stubbed `fetch` resolving real JSON) and asserts the language links' `data-zone` actually changes — the first test in this file to drive `handleClick` through a full successful swap, which is exactly how this bug shipped unnoticed the first time.
- [x] **[Low] `period-switcher.ts`'s `zoneSentenceLabel` mirror dropped `briefing.ts`'s defensive `?? zone` fallback and `Partial<Record<...>>` typing.** Not reachable through any current UI path (every real input comes from the fixed 15-entry `ZONE_CYCLE`), but a genuine drift from this story's own stated "defensive-lookup discipline from the start" instruction — a malformed `data-zone` attribute or malformed fetched JSON reaching this function would render the literal string `"undefined"` into the mad-libs sentence rather than degrading to the raw slug. Fixed by matching `briefing.ts`'s signature (`zone: string`, `Partial<Record<string, string>>` table, `?? zone` fallback) exactly. Proven via a new test asserting the fallback for a zone slug outside the known 15.

### Post-Review Fixes

- `site/src/islands/period-switcher.ts`: `handleClick`'s language-link update loop now also writes `data-zone`/`data-period`; `zoneSentenceLabel` restored to match `briefing.ts`'s defensive-fallback signature exactly.
- `site/src/islands/__tests__/period-switcher.test.ts`: added the Zone-click-then-language-links regression test (new fake-DOM fixtures: complete `sentence`/`itemList`/`timestamp`/`sentenceBlock`/`discarded` elements, a stubbed `fetch`, a `Node.TEXT_NODE` global stub since this test environment has no real DOM) and the `zoneSentenceLabel` unknown-zone fallback test.
- Re-ran full verification after both fixes: `npx tsc --noEmit`/`npx astro check` → clean; `npx astro build` → 136 pages; `npx vitest run` → 128/128 passing (up from 126); `uv run pytest` → 315/315 passing; `bash scripts/check-boundary.sh` → clean.

## Change Log

- 2026-08-13: Story created via bmad-create-story. Conducted the most thorough pre-implementation research of the epic so far, given this story's size: confirmed the Language axis is a type-only stub today (routing, i18n, control markup, and browser-detection are all complete gaps, not partial implementations); confirmed the pipeline's per-language content generation already works in principle but is unobservable today since `data/briefings/` is empty; resolved the genuine architectural tension between Story 4.1's no-JS Cold-load guarantee at `/` and browser-language detection's JS-only reachability by keeping `/`'s French default unconditional and adding the detection redirect as a strictly additive, opportunistic layer.
- 2026-08-13: All 6 tasks implemented and verified (128 site tests, 315 pipeline tests, boundary check clean, 136-page build). Caught and fixed 3 issues beyond the story's own planned scope during implementation: a silent no-op in `formatCount`'s narrow-no-break-space normalization regex, a missing client-side update to the mad-libs sentence's lead-in text node on a language switch, and 2 intermittently-timing-out e2e tests caused by the 3x larger build (fixed with explicit per-test timeouts). Status set to `review` ahead of the single-layer Blind Hunter adversarial review.
- 2026-08-13: Blind Hunter review found two real bugs: a high-severity gap where switching Zone/Period and then Language silently discarded the Zone/Period choice, and a low-severity drift where a mirrored lookup table lost its defensive fallback. Fixed both via TDD, added regression tests, re-verified the full suite (site: 128/128, pipeline: 315/315, boundary check clean), status set to `done`.
