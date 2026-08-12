---
baseline_commit: da86935
---

# Story 4.1: Render the World / day Briefing on arrival

Status: done

## Story

As a first-time visitor,
I want the day's news already on screen when the page loads,
So that I get value before doing any work.

## Scope, decided explicitly before this story was written

This is the **first story of Epic 4** and the **first TypeScript/Astro code in this repository** — everything before it (Epics 1–3) is the Python pipeline. Two design decisions were made explicitly before this story was written:

1. **The SM-1 gate is deliberately bypassed.** `sprint-status.yaml` recorded a gate at the end of Epic 2 requiring a two-week real-cycle observation window (comparing the real World/day Briefing against independent knowledge) before starting Epic 4. That window has not happened — no `COHERE_API_KEY` repository secret exists, so no non-degraded scheduled cycle has ever run. The user explicitly decided to start Epic 4 now anyway, accepting the risk. This is a schedule decision, not a technical resolution of the gate — do not reopen it in this story; it is documented in `sprint-status.yaml`'s Epic 2 comment block.
2. **No separate headline field exists in the data.** The UX mockups originally implied a bolded per-item title distinct from its Summary paragraph, but `pipeline/domain/__init__.py`'s `BriefingRecord` schema carries only a single `summary` string per Cluster — there is no title to render separately. This was corrected in the UX spine/mockups (commit `da86935`) before this story was written: **an item's entire display copy is its Summary paragraph, full stop.** Do not invent a headline by truncating or bolding part of the Summary text.

## The real data contract this story reads

`data/briefings/<lang>/<zone>/<period>.json`, written by `pipeline/stages/publish.py`, exact shape from `BriefingRecord.to_dict()`:

```json
{
  "schema_version": 1,
  "zone": "world",
  "zone_kind": "world",
  "zone_continent": null,
  "served_zone": "world",
  "served_zone_kind": "world",
  "served_zone_continent": null,
  "period": "day",
  "language": "fr",
  "clusters": [
    {
      "cluster_id": "string",
      "members": [ { "title": "string", "url": "string", "source": "string", "source_country": "string", "language": "string" } ],
      "independent_source_count": 7,
      "country_count": 5,
      "countries": ["france", "united-kingdom", "..."],
      "origin_country": "united-kingdom",
      "rank": 1,
      "summary": "string",
      "outbound_url": "string | null",
      "outbound_source": "string | null"
    }
  ],
  "discarded_ingested": 0,
  "discarded_kept": 0,
  "generated_at": "2026-08-11T06:00:00+00:00"
}
```

**Real gaps to handle, not hypothetical ones:**

- **No real `data/briefings/` files exist yet** — the directory contains only `.gitkeep`. A real cycle that ran during this project (2026-08-12) produced **zero qualifying Clusters** (`clusters_selected: 0` in its `rank.json`), so even once `publish` output exists for real, an empty `clusters` array is a live, already-observed case, not an edge case invented for testing.
- **`outbound_url`/`outbound_source` can be `null`**, or **absent from a cluster dict entirely** (when a Cluster wasn't found in the summarize pool — `publish.py`'s `_attach_summary` early-returns without adding `summary`/`outbound_url`/`outbound_source` at all in that case). Code reading these fields must handle "missing key" and "present but null" identically — both mean "no outbound link for this item."
- **`served_zone*` differs from `zone*` only on a Continent fallback (FR-16).** This story's own scope is World/day only, where a fallback can never apply (World has no parent to fall back to) — but the type/parsing code this story writes will be reused by Story 4.3, so model both fields now even though this story's own AC never exercises the divergent case.
- **`discarded_ingested`/`discarded_kept` are always `0`/`0` today** — no pipeline stage populates real values yet (`pipeline/domain/__init__.py`'s own comment on `BriefingRecord` flags this explicitly). This story does not render Discarded Volume (that's FR-8, a sibling story's scope) — noted here only so nobody mistakes `0`/`0` for evidence of a bug if a later story renders it before the pipeline actually computes real values.

## Current state of `site/` (read before writing any code)

Bootstrapped, not built: Astro 7.2 is installed (`site/node_modules`, `site/package-lock.json` both present — `npm install` has already run), `site/astro.config.mjs` is already correctly configured (`output: "static"`, `build.format: "file"`) with AD-1/AD-2 boundary comments in place. `site/src/pages/index.astro` is a placeholder that explicitly says "the real page is Epic 4." No `tsconfig.json` exists anywhere in `site/` — add one. No routing, no data-loading code, no components, no test infrastructure (no Playwright/Vitest) exists yet — this story builds all of it for the World/day/French default route.

`scripts/check-boundary.sh` is already live and will run in CI against whatever this story writes — four checks: (1) `pipeline/` must never reference `site/` by path (not relevant to this story, but do not violate it), (2) `site/` must never `import`/`from`/`require` anything containing `../...pipeline`, (3) `site/` must never reference the literal string `pipeline/` anywhere, (4) `site/` must never mention `anthropic`, `cohere`, `gdelt`, or `newsapi` in any casing (case-insensitive substring match) — this is a live tripwire for this exact story, the first to write real `site/` code. Run `bash scripts/check-boundary.sh` before considering this story done.

## Acceptance Criteria

1. **Given** any visitor with no prior state, **when** the page loads, **then** the World / day Briefing is present in the initial HTML response, with no client-side fetch required (FR-1) — the build reads `data/briefings/fr/world/day.json` at build time (Astro static generation), not at request time. **And** no onboarding, cookie wall, or preference prompt precedes it.

2. **Given** the page is built, **when** the build runs, **then** it reads only `data/briefings/*.json` from the local filesystem and calls no external service, network request, or third-party API (AD-1, AD-2) — verified by `scripts/check-boundary.sh`'s check 4 passing, and by no `fetch`/`XMLHttpRequest`/network call anywhere in the new code.

3. **Given** a typical mobile connection, **when** the page loads, **then** first contentful paint occurs within 1 second at the 95th percentile (NFR-1). Since this page ships zero required JavaScript for its content (see AC5) and is a single static HTML file with inline or minimal CSS, this is expected to hold by construction — verify with a Lighthouse or WebPageTest run against the built `dist/` output on a throttled connection profile, not just asserted.

4. **Given** JavaScript is unavailable, **when** the page loads, **then** the Briefing content is fully readable — every item's Summary, Consensus figures, and attribution link are present in the static HTML with no client-side rendering step (NFR-4).

5. **Given** the page renders in French (the default arrival language for this story's scope), **when** the layout is composed, **then** it follows the single-column editorial stack from `EXPERIENCE.md`'s Information Architecture: header (site mark + Output Language control — the control itself is inert/non-interactive in this story, since Story 4.7 wires its behavior; render it visually per `DESIGN.md`, do not wire a click handler yet) → mad-libs sentence (rendered as static text in this story — Story 4.2/4.3 make the Zone/Period words clickable; this story renders "Voici ce qui se passe dans **le Monde**, **aujourd'hui**." with the two words visually styled per `DESIGN.md`'s Mad-libs word component but with no click behavior) → item list → (Discarded Volume and End Screen are explicitly out of scope for this story — Stories 4.4/4.5 own them; do not render placeholders for them, just stop after the item list) → freshness timestamp ("Mis à jour à HH:MM", derived from `generated_at`).

6. **Given** the `clusters` array in the source JSON is empty (a real, already-observed case — see "The real data contract" above), **when** the page renders, **then** it does not crash, and shows no item blocks — this story does not need to design a dedicated "no coverage today" empty state (not in this story's AC list), but the build must not fail and the page must still render its header and mad-libs sentence.

## Tasks / Subtasks

- [x] **Task 1: Add TypeScript config and the `BriefingRecord` type** (supports all ACs)
  - [x] `site/tsconfig.json` extends `astro/tsconfigs/strict`.
  - [x] `site/src/lib/briefing.ts` — `BriefingRecord`, `Cluster`, `ClusterMember` types matching `BriefingRecord.to_dict()`'s exact shape; `summary`/`outbound_url`/`outbound_source` typed optional (`?`), not just nullable, matching `publish.py`'s real omit-the-key-entirely behavior.
  - [x] No import from `pipeline/` anywhere — hand-written mirror only, verified by `scripts/check-boundary.sh` passing.

- [x] **Task 2: Add a build-time JSON reader with graceful degradation** (AC1, AC2, AC6)
  - [x] `site/src/lib/loadBriefing.ts` — `loadBriefing(realPath, fixturePath)`, `fs.existsSync`/`readFileSync`/`JSON.parse`, called only from Astro frontmatter.
  - [x] Missing-file fallback: a committed fixture (`site/src/fixtures/day.json`) used whenever the real path doesn't exist — decided as a permanent, real fallback behavior (not a test-only shim), since it keeps `astro dev`/`astro build` working before any real cycle has ever produced output, and continues to degrade gracefully later if a cycle run is ever missing for any reason. See Dev Notes.
  - [x] Empty `clusters` array returned as-is, not treated as an error — proven by both a loader unit test and an end-to-end build test (Task 5).
  - [x] Fixture (`site/src/fixtures/day.json`) has 4 Cluster entries mirroring the corrected mockup's real French Summary text; the 4th entry deliberately omits `summary`/`outbound_url`/`outbound_source` entirely, exercising the real "Cluster not in the summarize pool" gap.

- [x] **Task 3: Build the page template** (AC1, AC4, AC5)
  - [x] `site/src/pages/index.astro` replaces the placeholder: header (site mark + inert `FR · EN · ES` control, `aria-hidden` since it does nothing yet), mad-libs sentence (static text, Zone/Period words styled with the dotted-underline treatment but no click handler), item list (one block per Cluster — Summary paragraph, Consensus chip, attribution link only when `outbound_url` is present), freshness timestamp derived from `generated_at`.
  - [x] `DESIGN.md`'s tokens (colors, Source Serif 4 / IBM Plex Sans / IBM Plex Mono, spacing) applied directly in a scoped Astro `<style>` block, closely matching `mockups/briefing-world-day.html`'s corrected visual reference.
  - [x] Confirmed zero `<script>` tags in the built `dist/index.html` (verified both manually and by an automated test in Task 5).

- [x] **Task 4: Verify the boundary and NFR claims** (AC2, AC3)
  - [x] `bash scripts/check-boundary.sh` passes cleanly.
  - [x] `npm run build` succeeds, reading the fixture fallback (the real `data/briefings/fr/world/day.json` does not exist yet in this environment — no non-degraded cycle has run). No network call anywhere in the build (the loader is a pure filesystem read; confirmed by code inspection and by the boundary check's own AD-1 tripwire passing).
  - [x] **Measured, not assumed**: Lighthouse against the real `astro preview` static build (not `astro dev`, which loads the dev toolbar and inflates payload to ~1.7MB) measured **First Contentful Paint = 649ms** (well under the 1s p95 budget), Performance score 1.00, total page weight 4KB. See Completion Notes for the full measurement note, including an initial mismeasurement caught and corrected (see Debug Log).

- [x] **Task 5: Tests**
  - [x] Vitest chosen as the runner (`site/package.json`'s new `test` script). For AC4 ("readable without JS"), decided against adding Playwright for this story: the page has zero client-side logic to exercise in a real browser yet, so a text-level assertion on the built static HTML (`site/e2e/no-js-readable.test.ts`) is exactly as strong a proof with no new dependency — revisit with Playwright once Story 4.2/4.3 introduce real interactivity worth exercising.
  - [x] `site/src/lib/__tests__/loadBriefing.test.ts` — 5 tests: well-formed real file, fallback to fixture when real file missing, empty `clusters` array returned as-is, throws when neither path exists, a Cluster missing `outbound_url`/`summary` entirely preserves that as `undefined` rather than crashing.
  - [x] `site/e2e/no-js-readable.test.ts` — 6 tests: builds the real static output and asserts directly on the HTML: no `<script>` tag, Summary text present, Consensus figures present, a real `<a href>` attribution link present, the mad-libs sentence present as static text, and (AC6) an empty-clusters build still succeeds and still renders the header/sentence with zero item blocks.
  - [x] AC3's FCP number is measured manually via Lighthouse (see Task 4) rather than asserted as an automated pass/fail gate in this story — a reliable, non-flaky Lighthouse-in-CI setup is a bigger investment than this story's scope; the manual measurement is recorded, not skipped.

## Dev Notes

### Why the mad-libs words are static text in this story, not clickable

Story 4.2 (Period) and Story 4.3 (Zone) own making these words interactive and cycling their values. This story renders the World/day/French page only — building click behavior now would mean guessing at Story 4.2/4.3's exact interaction wiring before those stories exist to specify it precisely (mirrors the same reasoning Stories 3.2/3.4 used to defer the assembly loop to 3.5 — don't build a mechanism before the story that owns its real shape exists).

### Why the Output Language control is inert in this story

Story 4.7 owns the browser-language-detection logic and the control's actual behavior. Rendering it visually now (per `DESIGN.md`'s header layout) without wiring it prevents Story 4.7 from also having to build the control's markup from scratch, while not guessing at behavior this story doesn't own.

### Why Discarded Volume and the End Screen are explicitly excluded

They are FR-8 (Story 4.5, shared with Consensus display) and FR-5 (Story 4.4) respectively — neither is in this story's AC list (re-read the AC list above; it stops after the item list). Do not render placeholders for them "for completeness" — an empty placeholder that later stories must find and replace is worse than a clean stop point a later story extends.

### The fixture-vs-fallback decision, resolved

Decided: a single mechanism serves both purposes. `site/src/fixtures/day.json` is a permanently-committed fixture (useful for local dev forever — `astro dev` always has real-looking content to render without needing a live pipeline cycle), and it is *also* the production fallback `loadBriefing` reaches for whenever the real `data/briefings/fr/world/day.json` doesn't exist. This is one file serving both roles, not two separate mechanisms — simpler than maintaining a dev-only fixture and a separate production placeholder that could drift apart. The tradeoff: once real cycles start producing `data/briefings/` output, the fixture becomes dev-only in practice (the real file will always exist in a production build), but keeping it in place costs nothing and continues to protect local dev against a `data/briefings/` directory that's empty for any reason (a fresh clone, a cycle that hasn't run yet in a new environment).

### Project Structure Notes

Files this story creates or modifies, all under `site/`:
- `site/tsconfig.json` (new)
- `site/src/lib/briefing.ts` (new) — the `BriefingRecord`/`Cluster`/`ClusterMember` types
- `site/src/lib/loadBriefing.ts` (new) — the build-time loader with fixture fallback
- `site/src/lib/__tests__/loadBriefing.test.ts` (new) — 5 unit tests
- `site/src/fixtures/day.json` (new) — the fixture/fallback JSON
- `site/src/pages/index.astro` (modified) — replaces the placeholder with the real page
- `site/e2e/no-js-readable.test.ts` (new) — 6 build-and-assert tests
- `site/package.json` / `site/package-lock.json` (modified) — added `vitest`, `@astrojs/check`, `typescript`, `@types/node` as dev dependencies; added a `test` script

No changes to any file under `pipeline/` — this story only reads `pipeline`'s already-established output contract, never its source.

### References

- [Source: epics.md#Story 4.1] — acceptance criteria origin (AC text above is elaborated from, not verbatim to, the epics.md version — cross-check before implementing)
- [Source: ux-designs/ux-5-news-2026-08-12/DESIGN.md] — visual tokens (colors, typography, spacing, Mad-libs word / Consensus chip / attribution component specs)
- [Source: ux-designs/ux-5-news-2026-08-12/EXPERIENCE.md] — Information Architecture (the 4-region stack), State Patterns ("Cold load"), Accessibility Floor
- [Source: ux-designs/ux-5-news-2026-08-12/mockups/briefing-world-day.html] — the corrected (no-separate-headline) visual reference for this exact route
- [Source: pipeline/domain/__init__.py#BriefingRecord] — the exact JSON schema this story's type/loader must match
- [Source: pipeline/stages/publish.py#assemble_briefings, _attach_summary] — confirms `summary`/`outbound_url`/`outbound_source` can be entirely absent from a cluster dict, not just null
- [Source: pipeline/config/__init__.py#ZONES, PERIODS, OUTPUT_LANGUAGES] — exact slug values (`world`, `day`, `fr`) this story's default route must use
- [Source: scripts/check-boundary.sh] — the four live boundary checks this story's new code must pass
- [Source: architecture spine, AD-1/AD-2] — the no-external-call-ever and pipeline-writes/site-reads invariants this story is the first to actually implement against

## Dev Agent Record

### Context Reference

_To be filled by dev-story._

### Debug Log

- The local shell environment has a broken `nvm`-wrapping shell function around `node`/`npm` that loops infinitely when invoked directly. Worked around by calling `/opt/homebrew/bin/node`/`/opt/homebrew/bin/npm`/`npx` by absolute path throughout this story — not a project issue, an environment quirk unrelated to the code.
- `import.meta.url`-based path resolution in `index.astro` (the initial approach for locating `data/briefings/...` from the page module) broke the real build: Astro bundles page modules for prerendering, so at build time `import.meta.url` resolves to a path under `dist/.prerender/chunks/...`, not the source file's real location — `readFileSync` then looked for `dist/.prerender/fixtures/day.json`, which never exists. Fixed by building paths from `process.cwd()` instead (stable across `astro dev`/`astro build`, since both always run from `site/`).
- Initial Lighthouse measurement for AC3 was wrong by an order of magnitude (6.8s FCP, 1.7MB payload) because it targeted the wrong port — `astro dev` (with its dev toolbar, which loads ~1.7MB of Vite/aria-query/axobject-query dependencies) was still running in the background on the port I mistakenly measured, while the real `astro preview` static server was running on a different port. Caught by inspecting the network-requests breakdown, recognized the dev-toolbar asset names, killed the stray `astro dev` process, and re-measured against the correct `astro preview` port: 649ms FCP, 4KB payload, performance score 1.00. Recorded as a cautionary note: always verify which server a performance measurement actually hit, especially when multiple dev/preview servers might be running.

### Completion Notes

All 5 tasks complete, TDD throughout for the loader logic (RED confirmed via `Cannot find module` before `loadBriefing.ts` existed; RED confirmed for each new `no-js-readable.test.ts` assertion by checking it failed against the placeholder scaffold before the real page existed). 11/11 new tests passing (5 loader unit tests + 6 build-and-assert tests).

**Task 1:** `site/tsconfig.json` (extends `astro/tsconfigs/strict`) and `site/src/lib/briefing.ts` (the `BriefingRecord`/`Cluster`/`ClusterMember` types) — a hand-written mirror of `pipeline/domain/__init__.py`'s `BriefingRecord.to_dict()` shape, with `summary`/`outbound_url`/`outbound_source` typed as optional properties (not just nullable), matching `publish.py`'s real behavior of omitting those keys entirely for a Cluster absent from the summarize pool.

**Task 2:** `site/src/lib/loadBriefing.ts` — reads the real path if it exists, else a fixture path; both supplied by the caller, so the function itself has no hardcoded knowledge of either location. `site/src/fixtures/day.json` serves as both the permanent local-dev fixture and the production fallback (one mechanism, not two — see Dev Notes for the tradeoff).

**Task 3:** `site/src/pages/index.astro` — the real World/day/French page. Header, mad-libs sentence (static), item list (Summary + Consensus chip + conditional attribution), freshness timestamp. Discarded Volume and the End Screen are not rendered (out of this story's scope, owned by Stories 4.4/4.5). Visually verified close to `mockups/briefing-world-day.html`.

**Task 4:** `scripts/check-boundary.sh` passes. `npm run build` succeeds against the fixture fallback (no real `data/briefings/` output exists in this environment yet — no non-degraded cycle has ever run, consistent with the outstanding `COHERE_API_KEY` gap flagged since Story 2.1). Lighthouse against the real static `astro preview` build (after correcting the port mismeasurement — see Debug Log): **FCP 649ms**, performance score 1.00, total page weight 4KB — well under the 1s p95 budget (AC3), measured, not assumed.

**Task 5:** Vitest chosen over Playwright for AC4's no-JS proof, since this story's page has no client-side logic at all yet — a text assertion on the built static HTML is an equally strong proof with zero added tooling. 5 loader unit tests (happy path, fixture fallback, empty clusters, both-paths-missing throws, absent-summary-fields preserved as `undefined`) + 6 build-and-assert tests (no `<script>` tag, Summary text present, Consensus figures present, real attribution `<a href>`, mad-libs sentence present, and — AC6 — an empty-`clusters` build still succeeds and still renders the header/sentence with zero item blocks, verified by temporarily swapping the fixture to an empty-clusters variant, rebuilding, asserting, then restoring the original fixture in `afterAll`).

**Not built in this story, by explicit design (confirmed with the user before/during this story):** click behavior for the mad-libs words (Story 4.2/4.3), Output Language control behavior (Story 4.7), Discarded Volume (Story 4.5/FR-8), the End Screen (Story 4.4/FR-5), Playwright/browser-based testing (deferred until real client-side interactivity exists to test), and any automated CI gate on the literal FCP number (recorded manually instead, per the story's own Task 5 guidance).

### File List

**New:**
- `site/tsconfig.json`
- `site/src/lib/briefing.ts`
- `site/src/lib/loadBriefing.ts`
- `site/src/lib/__tests__/loadBriefing.test.ts`
- `site/src/fixtures/day.json`
- `site/e2e/no-js-readable.test.ts`

**Modified:**
- `site/src/pages/index.astro` (placeholder replaced with the real World/day/French page; post-review: timestamp labeled UTC explicitly, attribution now gated by `hasValidAttribution`)
- `site/src/lib/briefing.ts` (post-review: added `hasValidAttribution` type guard)
- `site/src/lib/loadBriefing.ts` (post-review: both failure paths now raise descriptive errors with `cause`)
- `site/src/lib/__tests__/loadBriefing.test.ts` (post-review: added a malformed-JSON regression test)
- `site/e2e/no-js-readable.test.ts` (post-review: AC6 test now backs up the fixture before mutating and restores via `try`/`finally`, not `afterAll` alone)
- `site/package.json` (added `vitest`, `@astrojs/check`, `typescript`, `@types/node` as dev dependencies; added a `test` script)
- `site/package-lock.json` (regenerated by `npm install`)

**New (post-review):**
- `site/src/lib/__tests__/briefing.test.ts` (6 tests for `hasValidAttribution`)

## Post-Review Fixes

Single-layer adversarial review (Blind Hunter) found 10 issues; 5 were genuine defects, fixed here. The rest were accepted trade-offs, out-of-scope, or nitpicks not worth the churn given this story's own deliberately narrow scope.

- **Confirmed bug: the freshness timestamp silently rendered UTC clock digits as if they were the reader's local time.** `EXPERIENCE.md` requires "Updated at HH:MM" in "the reader's chosen Output Language's local time convention," but this page is generated once at build time with no client JS — there is no way to know a visiting reader's real timezone without a script, which is out of this story's scope. Fixed by labeling the timestamp explicitly as UTC ("Mis à jour à 06:14 UTC") rather than silently implying local time. Revisit if a later story ever adds client-side timezone conversion.
- **Confirmed bug: `outbound_source` could render as the literal string "null."** `outbound_url`/`outbound_source` can each independently be missing, null, or empty (a real, documented degrade state from the pipeline's `_select_outbound_link`), but the page only checked `outbound_url` truthiness before rendering `<em>{outbound_source}</em>` unguarded. Extracted a `hasValidAttribution` type guard into `src/lib/briefing.ts` (testable in isolation, no longer trapped inside the `.astro` file) requiring both fields present and non-empty. Regression tests: 6 new cases in `src/lib/__tests__/briefing.test.ts`.
- **Hardened, not because of a known exploit but as defense-in-depth: `hasValidAttribution` also now requires an `http(s)://` scheme on `outbound_url`.** Astro's HTML escaping protects against injected markup but does not scheme-validate `href` values; a `javascript:`/`data:` URL would have rendered as a properly escaped, fully clickable link. The pipeline should never produce one, but this is externally-influenced content (an Article's own URL) several stages removed from this page — the check costs nothing and closes off a class of bug with no other guard anywhere in this codebase.
- **Fixed a real crash-safety gap in the AC6 test**: `no-js-readable.test.ts`'s empty-clusters test mutated the real, tracked `src/fixtures/day.json` in place, relying entirely on vitest's `afterAll` (application-level, not OS-guaranteed) to restore it — a hard process kill between the mutation and the restore would have left the tracked fixture permanently corrupted. Fixed by writing a `.bak` copy to disk before any mutation (outside any hook, so it survives even a crash that skips hook execution) and wrapping the mutate/build/assert/restore sequence in `try`/`finally` inside the `it` block itself, so a failing assertion still restores before the test exits.
- **Fixed a real error-message gap in `loadBriefing`**: a missing file or malformed JSON previously surfaced as a bare `ENOENT`/`SyntaxError` with no context pointing at which of the two paths (real vs. fixture) was involved. Wrapped both failure points to raise a descriptive error naming both checked paths, with the original error preserved via `cause`. Added a regression test for the malformed-JSON case (`loadBriefing.test.ts`'s new "throws a descriptive error on malformed JSON" case) — previously only the both-paths-missing case had coverage.
- **Rejected as non-issues or out-of-scope**: a `existsSync`-then-`readFileSync` TOCTOU race in `loadBriefing` (real but requires a concurrent write during a local single-writer build — the risk this codebase's architecture is designed around not having); no test coverage on `ClusterMember`'s shape (the field is carried through but never rendered in this story — revisit when a story that actually displays members exists); no cross-validation that `REAL_PATH`/`FIXTURE_PATH` represent the same Zone/Period/Language (both are hardcoded to `world`/`day`/`fr` in this same file today, so there is nothing to drift yet — revisit if a future story parameterizes either path independently); the fixture's `2026-08-11` date (matches this project's other fixtures' dating convention, not a copy-paste artifact).

18/18 tests passing after fixes (up from 11).

## Change Log

- 2026-08-12: Story created via bmad-create-story. First story of Epic 4 and first TypeScript/Astro story in the repository. Explicitly notes two pre-decided scope boundaries: the SM-1 gate bypass (a schedule decision recorded in sprint-status.yaml, not reopened here) and the no-separate-headline correction to the UX contract (commit `da86935`, made before this story was written).
- 2026-08-12: Implemented via bmad-dev-story. All 5 tasks complete, TDD throughout. Resolved the story's own open fixture-vs-fallback question (one file serves both roles). Caught and fixed two real bugs before they reached review: an `import.meta.url` path-resolution break under Astro's prerendering bundler, and a Lighthouse measurement that initially targeted the wrong server (dev toolbar inflating FCP to 6.8s) before being corrected to the real static build's measured 649ms. 11/11 new tests passing. Status set to review.
- 2026-08-13: Reviewed via bmad-code-review (single-layer Blind Hunter). Found and fixed a real UTC-labeled-as-local-time bug in the freshness timestamp, a real "Rapporté par null" rendering bug, a real crash-safety gap in a test that mutated a tracked fixture in place, and a real error-message clarity gap in the loader; hardened outbound-link rendering against a non-http(s) scheme as defense-in-depth. Rejected 4 findings as non-issues or genuinely out of this story's scope. 18/18 tests passing. Status set to done.
