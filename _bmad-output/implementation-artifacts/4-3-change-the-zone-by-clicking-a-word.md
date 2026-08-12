---
baseline_commit: ac778af
---

# Story 4.3: Change the Zone by clicking a word

Status: done

## Story

As an expatriate reader,
I want to switch between World, a continent, and a country the same way,
So that following two places costs two clicks.

## Scope, decided explicitly before this story was written

**This story extends Story 4.2's exact mechanism to a second axis — it does not build a new one.** Story 4.2 already built the dynamic route, the shared `BriefingPage` component, the JSON-fetch-and-swap island, and the day→week→month→day cycle pattern. This story:
1. Adds the 15-value Zone cycle (World → 6 Continents → 8 Countries → World) the same way 4.2 added the 3-value Period cycle.
2. Extends `getStaticPaths()` from 3 combinations (World × 3 Periods) to 45 (15 Zones × 3 Periods) — still hardcoded to `lang: "fr"`; Language is Story 4.7's axis, not this one.
3. Adds the Continent-fallback notice (FR-16) — a new concern Story 4.2 did not have, since Period never falls back.

Do not touch Language switching (Story 4.7) or the End Screen/variable item count (Story 4.4) in this story.

**The Zone slugs are pipeline-owned; the site hand-mirrors them, it does not import them.** `pipeline/config/__init__.py`'s `ZONES` tuple is the single source of truth for the 15 slugs and their order — but `site/` must never import from `pipeline/` (`scripts/check-boundary.sh` forbids any cross-reference, and Story 4.2's `[period].astro` already established the precedent of hand-maintaining a small hardcoded list on the TS side rather than importing). This story hand-mirrors the same 15 slugs, in the same order, on the TS side — exactly as `briefing.ts`'s header comment already states is the standing convention for this schema boundary ("kept in sync by hand whenever `BriefingRecord`'s schema changes").

**The Continent-fallback signal is already in the JSON — this story reads it, does not compute it.** The pipeline (Story 2.5) already resolves a too-thin Country Zone to its Continent's content *before* writing the file. The single Briefing JSON the site already reads contains: `zone`/`zone_kind`/`zone_continent` (what was *requested*) and `served_zone`/`served_zone_kind`/`served_zone_continent` (what actually populates `clusters`). A fallback happened if and only if `served_zone !== zone` (plain string comparison — mirrors the pipeline's own `ZoneRanking.substituted` property, which is not itself serialized into the JSON). No second fetch, no client-side guess — the notice is entirely data-driven from fields already present in the one file the page already loads.

## Exact reference data (verified against `pipeline/config/__init__.py` and `pipeline/domain/__init__.py`)

**The 15 Zone slugs, in cycle order** (mirrors `ZONES` tuple order exactly — do not re-sort):

```
world
europe, north-america, south-america, asia, africa, oceania
france, united-kingdom, germany, united-states, japan, china, india, brazil
```

**Country → parent continent** (needed only for the fallback notice's continent name, not for cycling):

| Country | Continent |
|---|---|
| france, united-kingdom, germany | europe |
| united-states | north-america |
| japan, china, india | asia |
| brazil | south-america |

(`africa` and `oceania` currently have zero Countries defined — a fallback can never target them, and no Zone in the cycle has them as a parent; this is a pipeline-config fact, not something this story needs to special-case, since the cycle simply never produces that combination today.)

**`BriefingRecord`'s zone-related fields** (already in the schema `site/src/lib/briefing.ts` mirrors; no interface change needed — these fields already exist on `BriefingRecord` per that file's current content):

```typescript
zone: string;                    // requested — what the URL/route asked for
zone_kind: ZoneKind;              // requested Zone's kind
zone_continent: string | null;    // requested Zone's parent continent slug, or null
served_zone: string;              // what actually populates `clusters` (differs from `zone` only on fallback)
served_zone_kind: ZoneKind;
served_zone_continent: string | null;
```

A fallback is active exactly when `briefing.served_zone !== briefing.zone`.

## Acceptance Criteria

1. **Given** a rendered Briefing, **when** the reader clicks the Zone word, **then** the Zone cycles World → Europe → North America → South America → Asia → Africa → Oceania → France → United Kingdom → Germany → United States → Japan → China → India → Brazil → World (FR-3, exact `ZONES` order above) and the Briefing is replaced, **and** the URL reflects the selection (`/fr/<zone>/<period>`) — true in both the no-JS (real navigation) and JS-present (`history.pushState`) cases, exactly mirroring Story 4.2's Period mechanism.

2. **Given** the Zone mad-libs word, **when** it renders, **then** it shows the same dotted-underline `primary`-color treatment as the Period word (DESIGN.md Components) — visually consistent between the two mad-libs words, whether or not JavaScript is present.

3. **Given** a Country Zone that fell back to its Continent (`served_zone !== zone` in the loaded `BriefingRecord`), **when** the Briefing renders, **then** a `secondary`-colored (`#8a3a2b` text on `#f6dcd4` background) inline sentence appears directly beneath the mad-libs title sentence, reading (French) "Affichage de [la/l'] `<Continent>` — `<Country>` n'a pas assez de couverture aujourd'hui." (exact pattern from `mockups/briefing-fallback.html`), **and** this notice is never a dismissible banner or toast, **and** `secondary` is used nowhere else on the page (DESIGN.md's explicit "reserved for exactly one meaning" rule).

4. **Given** a Zone that did *not* fall back (`served_zone === zone`), **when** the Briefing renders, **then** no fallback notice appears at all — not an empty container, not a hidden element, nothing in the DOM for it.

5. **Given** the reader changes Zone with JavaScript present, **when** the new Briefing renders, **then** the fallback notice (if any) updates correctly as part of the same in-place swap Story 4.2 already built (fetch target Zone's JSON, re-render sentence + item list + notice, `history.pushState`) — no separate mechanism, no separate fetch.

6. **Given** JavaScript is unavailable, **when** the reader clicks the Zone word, **then** a normal link navigation occurs to the equivalent static route (`/fr/<next-zone>/<period>`), full page load, same content and same fallback-notice behavior as a JS-present swap — verified the same way Story 4.1/4.2 verified their own no-JS claims (build-and-assert on static HTML).

7. **Given** all 15 Zones × 3 Periods, **when** the site builds, **then** all 45 pages generate successfully, each falling back to a fixture exactly like Story 4.2's mechanism when its real `data/briefings/` file doesn't exist yet — no new failure mode for any of the 12 newly-added Zones (World was already covered by Story 4.1/4.2).

## Tasks / Subtasks

- [x] **Task 1: Add the `Zone` cycle and fallback-detection helpers to `site/src/lib/briefing.ts`** (AC1, AC3, AC4)
  - [x] Added `ZONE_CYCLE: readonly string[]`, hand-mirroring the exact 15-slug order from `pipeline/config/__init__.py`'s `ZONES` tuple.
  - [x] Added `nextZone(current: string): string`, mirroring `nextPeriod`'s exact index-lookup + modular-increment shape.
  - [x] Added `zoneSentenceLabel(zone: string): string` returning a full preposition-inclusive French phrase per Zone ("dans le Monde", "en Europe", "au Japon", "aux États-Unis") — see Dev Notes for why the preposition had to be baked into the label rather than kept as a separate lookup, a real French-grammar detail the mockups only partially covered (World and France).
  - [x] Added `isZoneFallback(briefing): boolean` returning `served_zone !== zone`.
  - [x] Added `fallbackNoticeText(briefing): string | null` — exact sentence from `mockups/briefing-fallback.html:126`, with correct article-form labels for the 6 Continents (`servedLabel`, always "de l'X" since all 6 start with a vowel) and 8 Countries (`requestedLabel`, subject-form article, e.g. "la France"/"le Japon"/"les États-Unis") — distinct from `zoneSentenceLabel`'s preposition-form labels, since French grammatical role changes the article. Also handles verb-number agreement ("n'a" vs "n'ont") for the one grammatically plural Country (les États-Unis).

- [x] **Task 2: Extend `getStaticPaths()` in `[lang]/[zone]/[period].astro`** (AC1, AC7)
  - [x] Replaced the single hardcoded `zone: "world"` with `ZONE_CYCLE` imported from `briefing.ts` (reused the one constant, not duplicated a second time — per Story 4.2's "one owner" discipline).
  - [x] `flatMap` cross product with the existing 3 Periods → 45 `{lang: "fr", zone, period}` entries.
  - [x] `REAL_PATH`/`FIXTURE_PATH` construction needed no change — `REAL_PATH` already parameterizes on `zone`; `FIXTURE_PATH` stays period-only by design (see Task 3).

- [x] **Task 3: Add fixtures for the 14 newly-routed Zones** (AC7)
  - [x] Decision: kept the existing single-fixture-set-regardless-of-zone behavior (every Zone's dev-mode miss still falls back to the same 3 period fixtures) — simplest, and consistent with the fixture's role as "something valid to render," not "realistic per-zone content." No new per-Zone fixture files added for the general case.
  - [x] Added exactly one dedicated fixture, `site/src/fixtures/fallback-example.json` (`zone: "france"`, `served_zone: "europe"`), used directly by the fallback-notice test's own `loadBriefing` call — not wired into `[period].astro`'s routing, since that file's normal fixture-fallback path never needs to simulate a Zone fallback (real `data/briefings/` files, once they exist, will carry real fallback state; this fixture only exists to exercise `fallbackNoticeText`/the rendered notice in a test).

- [x] **Task 4: Render the Zone mad-libs word as a real link, and the fallback notice conditionally** (AC1, AC2, AC3, AC4, AC6)
  - [x] Changed the Zone word from static `<span class="word">le Monde</span>` text to `<a class="word" data-zone-word data-lang data-zone data-period href="/{lang}/{nextZone(zone)}/{period}">{zoneSentenceLabel(zone)}</a>` — same `.word`/`h1 a.word` CSS treatment as the Period word, and reused the same `data-lang`/`data-zone`/`data-period` attribute set (sufficient for the island to compute both next-values from either anchor's own dataset, since both anchors carry the full current `{lang, zone, period}` triple).
  - [x] Added the fallback-notice element exactly per `mockups/briefing-fallback.html`'s markup/CSS (`color: #8a3a2b`, `background: #f6dcd4`, `border-radius: 3px`), as a sibling directly after the `<h1>`, inside `.sentence-block`, before `.timestamp`, rendered only when `fallbackNoticeText(briefing)` is non-null — omitted entirely (not hidden) otherwise; verified via built-HTML inspection that no `<div class="fallback-notice">` element exists on a non-fallback page.
  - [x] Gave it `id="fallback-notice"` for the island (Task 5) to target.
  - [x] Also removed the now-hardcoded "dans" from the sentence's static lead-in text (moved into `zoneSentenceLabel`'s per-Zone preposition, since French prepositions vary by Zone — see Task 1) and updated the two e2e tests that had hardcoded "Voici ce qui se passe dans" as a fixed string.

- [x] **Task 5: Extend `period-switcher.ts` to also handle the Zone word, and to swap the fallback notice** (AC1, AC3, AC5)
  - [x] Decision: a single parameterized `handleClick(link, axis)` (`axis: "zone" | "period"`) rather than two near-duplicate handlers — avoids duplicating the fetch/render/pushState logic twice; `attachWord(selector, axis)` attaches each mad-libs word's listener with its own axis baked in as a closure argument.
  - [x] On either word's click: compute the target Zone/Period (only the clicked axis advances; the other stays as-is), fetch `/briefings/<lang>/<target-zone>/<target-period>.json`, re-render both mad-libs words' text/href/dataset (since a Zone change moves the Period word's `href` too, and vice versa — both anchors always reflect the *current* full `{zone, period}` pair), the fallback notice (remove any existing `#fallback-notice` element, then insert a fresh one via `renderFallbackNoticeHtml` only if the freshly-fetched Briefing's `zone`/`served_zone` differ), and the item list — then `history.pushState` to `/fr/<target-zone>/<target-period>`.
  - [x] `renderItemListHtml`'s existing logic needed no change (still Zone-agnostic, only reads `clusters`); `BriefingLike` gained `zone`/`served_zone` fields for the new fallback-notice logic.
  - [x] Preserved the `ATTACHED_MARKER` idempotency guard from Story 4.2's review fix, now applied identically to both `[data-zone-word]` and `[data-period-word]` via the shared `attachWord` helper — verified via a test asserting exactly one listener per word after 3 repeated `attach()` calls.

- [x] **Task 6: Extend `copy-briefings-to-public.ts`'s `COMBINATIONS`** (AC7)
  - [x] Cross product reusing `ZONE_CYCLE` imported from `briefing.ts` (not a third hand-duplicated copy) x 3 Periods → 45 entries, `lang: "fr"` throughout. Verified via direct `node scripts/copy-briefings-to-public.ts` run: writes exactly 45 files under `site/public/briefings/`.
  - [x] Existing tests all pass explicit combination lists, not `COMBINATIONS` itself, so none needed updating; added one new test asserting `COMBINATIONS` now has exactly 45 entries.

- [x] **Task 7: Tests**
  - [x] Full 15-step `nextZone` unit test (every transition, not just a sample) in `briefing.test.ts`.
  - [x] Unit tests for `isZoneFallback`/`fallbackNoticeText` in `briefing.test.ts`: no-fallback case, France→Europe fallback (exact mockup wording), and the plural-verb-agreement case (les États-Unis n'ont pas, not n'a pas) — a real French-grammar bug this story's own TDD red phase caught before any implementation existed (see Dev Notes).
  - [x] Extended `no-js-readable.test.ts` with a new "Zone axis" describe block (Continent page: Europe; Country page: Japan) asserting the Zone word's real `<a href>` target, and a new "Continent-fallback notice (AC3)" describe block that temporarily substitutes `day.json`'s content with the dedicated `fallback-example.json` fixture (mutate/build/assert/restore-and-rebuild, same crash-safety discipline as the existing AC6 block) to render a real fallback notice in a real build and assert its exact text and `color`/`background` CSS values.
  - [x] AC4 (no notice element at all) proven in the same "Zone axis" block's Japan test.
  - [x] Extended `period-switcher.test.ts` with unit tests mirroring `briefing.ts`'s Zone helpers, plus an updated `attach` test proving the `ATTACHED_MARKER` guard holds independently for both mad-libs words. Re-confirmed the no-Playwright decision: the Zone axis reuses the exact same swap mechanism as Period, no new class of client-side risk.
  - [x] Confirmed `npx astro build` produces all 46 pages (45 + `/`); `grep`-verified the Zone word's `href` on Europe/Japan/France pages points at the correct next-Zone sibling.
  - **Two real bugs found and fixed during this task's own TDD process** (both in test assertions, not product code — see Dev Notes for full detail): (1) a false-positive `id="fallback-notice"` match inside the island's own inlined `<script>` source (its template-literal rendering code contains that literal string) required stripping `<script>` content before the AC4 "no notice" assertion, mirroring the AC6 block's pre-existing `class="item"` fix; (2) an exact-string `toContain` assertion for the fallback notice's HTML didn't account for Astro's injected `data-astro-cid-*` scoping attribute, fixed by switching to a regex match.

## Dev Notes

### Why this story is "extend," not "rebuild"

Story 4.2 already solved every mechanical problem this story needs — the dynamic route, the shared component, the fetch-and-swap island, the static-asset exposure script, the no-JS/JS-present duality, and (via its own review fix) the listener-idempotency guard. The only genuinely new concern here is the Continent-fallback notice, because Period never falls back but Zone does. Resist the temptation to generalize prematurely beyond what this story needs (e.g. do not build a generic "N-axis mad-libs" abstraction) — Story 4.2's own Dev Notes already anticipated this story would come and deliberately kept `[period].astro`/`period-switcher.ts` "generic across all three axes via BriefingPage" without over-abstracting the mechanism itself; extend concretely.

### Why the fallback notice must read data already in the file, never compute it client-side or pipeline-side again

The pipeline (Story 2.5, `pipeline/stages/rank.py`) already did the substitution work before the file was ever written. `served_zone != zone` is a complete, sufficient, already-correct signal sitting in the exact JSON the site already loads for every other purpose. Re-deriving "is this Zone too thin" on the site side would require the site to have opinions about `MIN_QUALIFYING_FOR_ZONE` or Cluster counts — a pipeline concern this story must not duplicate (mirrors AD-1's "the site performs no computation" spirit even though AD-1 is literally about AI/embedding calls; the underlying principle — don't re-derive what the pipeline already decided — applies here too).

### Why `zone_continent`/`served_zone_continent` are not needed by this story's own logic

The fallback notice's wording only needs the *served* Zone's label (the Continent name) and the *requested* Zone's label (the Country name) — both already derivable from `served_zone`/`zone` via Task 1's `ZONE_LABEL` map. The `*_continent` fields exist in the schema for other reasons (likely relevant to a future story, e.g. breadcrumb-style navigation) — reading them is not wrong, but this story's Task 1 helpers do not require them, and inventing a use for them here would be scope creep.

### The mad-libs word hrefs must never use `served_zone` for navigation

Already stated as a warning in `BriefingPage.astro`'s own existing comment (written during Story 4.2, anticipating this exact story): the Zone word's `href` must be built from the *route's* `zone` prop (what was requested), never `briefing.served_zone` (what was actually served). Getting this backwards would mean clicking "next Zone" from a fallback page silently keeps navigating through the served Continent's cycle position instead of the requested Country's — a subtle, easy-to-miss bug this story must not introduce.

### Previous Story Intelligence

- Story 4.2's Blind Hunter review caught a real click-listener-accumulation bug in `attach()`/`handleClick()` (fixed with an `ATTACHED_MARKER` idempotency guard) — re-read that story's Post-Review Fixes section before extending the same island file; apply the same guard pattern to any new anchor this story adds a listener to, rather than rediscovering the same bug class.
- Story 4.2 deliberately did not introduce Playwright/jsdom, isolating all DOM-adjacent logic into pure, unit-testable functions and testing `attach()`'s idempotency via a hand-rolled minimal DOM stub rather than a new test-runner dependency. This story's Zone-word swap is the same shape of interaction (click → fetch → in-place re-render → pushState) — the same reasoning should apply unless this story's own review surfaces a reason it doesn't.
- Story 4.2's Lighthouse measurement discipline: always verify which server (`astro dev` vs `astro preview`) and which port is actually being measured, killing/stopping any stray prior instance first. This story doesn't have a new latency claim to verify (AC5 reuses Story 4.2's already-proven mechanism), but if a Lighthouse check is run anyway, follow the same discipline.
- Single-layer adversarial review (Blind Hunter only) remains the process for this story, per the user's standing cost-reduction decision.

### Project Structure Notes

Files this story creates or modifies, all under `site/`:
- `site/src/lib/briefing.ts` (modified) — `ZONE_CYCLE`, `nextZone`, `ZONE_LABEL`, `isZoneFallback`, `fallbackNoticeText`
- `site/src/lib/__tests__/briefing.test.ts` (modified) — tests for the above
- `site/src/pages/[lang]/[zone]/[period].astro` (modified) — `getStaticPaths()` extended to 45 entries
- `site/src/components/BriefingPage.astro` (modified) — Zone word becomes a real link, fallback notice added conditionally
- `site/src/islands/period-switcher.ts` (modified, possibly renamed) — Zone-word click handling, fallback-notice swap
- `site/src/islands/__tests__/period-switcher.test.ts` (modified) — new unit tests
- `site/scripts/copy-briefings-to-public.ts` (modified) — `COMBINATIONS` extended to 45 entries
- `site/scripts/__tests__/copy-briefings-to-public.test.ts` (modified, if any hardcoded-count assertion exists)
- `site/src/fixtures/` — new fixture(s) per Task 3's decision
- `site/e2e/no-js-readable.test.ts` (modified) — Continent/Country page + fallback-notice assertions

No changes to any file under `pipeline/` — this story only reads `pipeline`'s already-established output contract (the `zone`/`served_zone` fields it already writes).

### References

- [Source: epics.md#Story 4.3] — acceptance criteria origin (lines 616-631)
- [Source: pipeline/config/__init__.py#ZONES] — the exact 15 slugs and their order (lines 37-53), `MIN_QUALIFYING_FOR_ZONE` (line 88)
- [Source: pipeline/stages/rank.py#_rank_for_zone, ZoneRanking] — the fallback mechanism itself (lines 198-304), read-only reference, never imported into `site/`
- [Source: pipeline/domain/__init__.py#BriefingRecord] — `zone`/`served_zone` field semantics (lines 355-378)
- [Source: ux-designs/ux-5-news-2026-08-12/EXPERIENCE.md#Component Patterns, State Patterns] — Continent-fallback notice placement/behavior/trigger, Zone mad-libs word cycle order and a11y requirements
- [Source: ux-designs/ux-5-news-2026-08-12/DESIGN.md#Colors, Components] — `secondary`/`secondary-container` exact hex values and the "reserved for exactly one meaning" rule
- [Source: ux-designs/ux-5-news-2026-08-12/mockups/briefing-fallback.html] — exact notice markup, CSS, and French wording to match verbatim
- [Source: _bmad-output/implementation-artifacts/4-2-change-the-period-by-clicking-a-word.md] — the mechanism this story extends; its Post-Review Fixes section (the `ATTACHED_MARKER` guard) and its Playwright-deferral reasoning

## Dev Agent Record

### Context Reference

Story spec + epics.md#Story 4.3 + pipeline/config & domain source (Zone slugs, fallback mechanism) + UX EXPERIENCE.md/DESIGN.md (fallback notice spec) + Story 4.2's own file (mechanism being extended, review learnings).

### Debug Log

- `scripts/check-boundary.sh` continues to fail on its pre-existing false-positive pattern (first documented in Story 4.2's Debug Log): its grep matches the literal substring `pipeline/` inside comments, not actual import statements. This story's new comments (explaining the hand-mirrored `ZONE_CYCLE`, the fallback mechanism's pipeline-side origin) added more matches, but zero real cross-boundary imports exist — confirmed via `grep "^import\|from ['\"]"` across every flagged file, finding no `pipeline/` import anywhere. Left unfixed, consistent with Story 4.2's decision: the script itself is not owned by this story's scope.
- TDD's red phase for `fallbackNoticeText` caught a real French-grammar bug before any implementation existed: a fixed "n'a pas" verb for every Country would have been wrong for "les États-Unis" (grammatically plural), which needs "n'ont pas". Caught by writing the test first with the correct grammar, not by writing the code first and hoping it was right.
- Two of this story's own e2e test assertions were initially wrong (not product bugs): (1) checking for `id="fallback-notice"` without first stripping the island's `<script>` tag produced a false positive, since the compiled JS source contains that literal string in its own template-literal rendering logic (exact same class of issue as Story 4.2's `class="item"` fix); (2) an exact-string `toContain` match for the fallback notice's HTML failed because Astro injects a `data-astro-cid-*` scoping attribute between `id="fallback-notice"` and the closing `>`, requiring a regex match instead of an exact substring.
- The mad-libs sentence's "dans" was hardcoded static text before this story (Story 4.1/4.2); Story 4.3 discovered this doesn't generalize, since French geographic prepositions vary by Zone (en/au/aux/dans le). Moved the preposition into `zoneSentenceLabel`'s own per-Zone phrase and updated the two Story-4.2-era e2e assertions that had hardcoded "Voici ce qui se passe dans" as a fixed string.

### Completion Notes

- All 7 tasks complete. Full verification: `npx tsc --noEmit` (0 errors), `npx astro check` (0 errors/warnings), `npx astro build` (46 pages, up from 4 before this story), `npx vitest run` (54/54 passing, up from 45). `scripts/check-boundary.sh`'s pre-existing false-positive (Story 4.2's own comment-matching issue) persists and is documented, not fixed, as out of this story's scope.
- The two hardest correctness risks in this story were French-grammar accuracy (15 Zones × 2 grammatical roles — sentence-preposition form and fallback-notice subject form — with one genuinely plural Country requiring verb agreement) and avoiding a routing bug where a Continent-fallback page's mad-libs Zone link could silently navigate from the *served* Zone instead of the *requested* one (guarded against by always building hrefs from the route's own `zone` prop, per `BriefingPage.astro`'s pre-existing warning comment from Story 4.2).
- No Playwright/jsdom introduced, extending Story 4.2's own decision: the Zone axis is the same swap mechanism on a second data field, not a new interaction class.

### File List

- `site/src/lib/briefing.ts` (modified) — `ZONE_CYCLE`, `nextZone`, `zoneSentenceLabel`, `isZoneFallback`, `fallbackNoticeText`
- `site/src/lib/__tests__/briefing.test.ts` (modified) — tests for the above
- `site/src/pages/[lang]/[zone]/[period].astro` (modified) — `getStaticPaths()` extended to 45 entries via `ZONE_CYCLE`
- `site/src/components/BriefingPage.astro` (modified) — Zone word is now a real link; fallback notice added conditionally; sentence's "dans" moved into `zoneSentenceLabel`
- `site/src/islands/period-switcher.ts` (modified) — extended to handle both mad-libs words via a parameterized `handleClick(link, axis)`; added Zone/fallback-notice mirrors of `briefing.ts`'s helpers
- `site/src/islands/__tests__/period-switcher.test.ts` (modified) — new Zone/fallback-notice tests; `attach` test extended to cover both words
- `site/scripts/copy-briefings-to-public.ts` (modified) — `COMBINATIONS` extended to 45 entries via `ZONE_CYCLE`
- `site/scripts/__tests__/copy-briefings-to-public.test.ts` (modified) — new `COMBINATIONS` count test
- `site/src/fixtures/fallback-example.json` (new) — dedicated fixture for the AC3 fallback-notice test
- `site/e2e/no-js-readable.test.ts` (modified) — new "Zone axis" and "Continent-fallback notice (AC3)" describe blocks; fixed two pre-existing Story-4.2-era assertions that hardcoded "dans" as static text

## Senior Developer Review (AI)

Single-layer adversarial review (Blind Hunter), per the standing cost-reduction decision.

**Outcome: Changes Requested → Fixed.**

### Action Items

- [x] **[High] Unguarded lookup crash in `briefing.ts`'s `fallbackNoticeText`.** `ZONE_SERVED_LABEL[briefing.served_zone]` and `ZONE_REQUESTED_LABEL[briefing.zone]` were dereferenced (`requested.plural`) with no check that either lookup actually returned a value. `period-switcher.ts`'s hand-mirrored copy of this same function already had the guard (`if (!servedLabel || !requested) return null`) — a real drift between the two copies this story's own comments say must stay in sync. Failure scenario: `loadBriefing.ts` does a bare `JSON.parse` with zero schema validation, and `BriefingPage.astro` calls `fallbackNoticeText` unconditionally for every one of the 45 statically-generated pages at build time — a single malformed `data/briefings/**/*.json` file (partial write, hand-edit, future pipeline bug) with a `zone`/`served_zone` pair outside either lookup table throws an uncaught `TypeError` and fails the *entire* `astro build`, not just that one page. Fixed by adding the identical guard to `briefing.ts`'s copy, returning `null` instead of throwing. Proven via a new test asserting `fallbackNoticeText` returns `null` (not a throw) for zone/served_zone values absent from both tables.

### Post-Review Fixes

- `site/src/lib/briefing.ts`: added the missing `if (!servedLabel || !requested) return null;` guard to `fallbackNoticeText`, matching `period-switcher.ts`'s already-correct copy.
- `site/src/lib/__tests__/briefing.test.ts`: added a test proving the guard.
- Re-ran full verification after the fix: `npx vitest run` → 55/55 passing (up from 54); `npx tsc --noEmit` → 0 errors; `npx astro build` → succeeds, 46 pages.

## Change Log

- 2026-08-13: Story created via bmad-create-story. Verified the 15 Zone slugs, their cycle order, and the Continent-fallback mechanism directly against `pipeline/config/__init__.py` and `pipeline/stages/rank.py` rather than assuming; confirmed the fallback signal (`served_zone != zone`) is already present in the JSON the site reads, requiring no new pipeline-side work. Verified the exact fallback-notice wording and styling against the existing `mockups/briefing-fallback.html` and `DESIGN.md`'s color tokens rather than inventing new copy.
- 2026-08-13: All 7 tasks implemented and verified (build, type-check, full test suite). Status set to `review` ahead of the single-layer Blind Hunter adversarial review.
- 2026-08-13: Blind Hunter review found one real, high-severity bug (unguarded lookup crash risk in `fallbackNoticeText`). Fixed via TDD, re-verified full suite, status set to `done`.
