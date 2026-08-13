---
baseline_commit: 9dd44d0
---

# Story 5.3: Invalidate the cache on every published cycle

Status: done

## Story

As a reader,
I want a new cycle to take effect on the visit that discovers it,
So that I am never one visit behind.

## Scope, decided explicitly before this story was written

**No `cycle_id` field exists anywhere in the published Briefing schema — this story cannot read one from `data/briefings/`.** Confirmed via direct research: `pipeline/stages/__init__.py`'s `cycle_id_for(instant)` produces a UTC-timestamp-derived string (e.g. `2026-08-12T05-30-00Z`) used internally to name `data/intermediate/<cycle_id>/`, but `pipeline/stages/publish.py`'s `assemble_briefings` only stamps `generated_at` (an ISO-8601 datetime) into each published Briefing — the `cycle_id` string itself never reaches `data/briefings/`. The architecture spine's own AD-9 text and Consistency Conventions table both describe the cycle identifier "stamping the service worker," but neither specifies HOW the site build (a separate, currently-disconnected process — see below) is supposed to obtain it. This story's own job is to close that gap on the site side using what's actually available: `generated_at`.

**The pipeline's cycle workflow and the site's build are two separate, currently-disconnected processes — this story does not connect them, and does not add a deploy pipeline.** `.github/workflows/collect.yml` runs the pipeline and commits `data/`; it never runs `npm run build` in `site/`. `.github/workflows/ci.yml`'s `site` job runs `npm run build` on push/PR/dispatch, with no cycle-awareness at all. There is no combined "pipeline cycle → site build → deploy" workflow anywhere in this repo today, and adding one is a distinct, unscoped infrastructure concern (deployment target, hosting, CI wiring) well beyond this story's own ACs. This story's job is narrower: make `site/public/sw.js`'s own build-time content vary correctly whenever the site IS built against a new cycle's data, whenever and however that build eventually runs (locally, in CI, or from a future deploy pipeline this repo doesn't have yet).

**The stamped identifier is derived from a Briefing's own `generated_at` field at site-build time, read the same way `copy-briefings-to-public.ts` already reads Briefings — this is new site-build logic, not a pipeline change.** Since every one of the 135 Briefings in a single cycle shares the same `generated_at` (one datetime is passed to `assemble_briefings` for the whole cycle), reading any one of them (the existing `fr/world/day` fixture-or-real-data path, already the site's own established "canonical" Briefing for other purposes — e.g. `index.astro`'s own `REAL_PATH`) is sufficient to derive a per-cycle-unique value. No pipeline file changes; this is a new small Node script/step in `site/`, run before `astro build`, mirroring `copy-briefings-to-public.ts`'s own established "a pre-build Node script rewrites a `public/` file's content" pattern — the first precedent for exactly this kind of build-time text injection into an otherwise-static `public/` file.

**AD-9's full rule has 3 distinct requirements — implement all 3, not just the byte-stamping:** (1) the cycle identifier is stamped into `sw.js`'s own bytes so they differ per cycle (a build-time content change); (2) on activation, caches whose name does not carry the current identifier are deleted (new `activate` event listener — does not exist in `sw.js` today); (3) `skipWaiting` and `clients.claim` are used so an update lands on the current visit, not the next one (also does not exist in `sw.js` today — Story 5.2 deliberately left this out, flagged as this story's own scope in its own code comment).

**This story does not add or change any offline-experience UI (Story 5.4's scope) and does not change the network-first/cache-first classification logic itself (Story 5.2's own, already-shipped, already-reviewed `classifyRequest`/`networkFirst`/`cacheFirst` functions stay untouched)** — only `CACHE_NAME`'s own value becomes cycle-dependent, plus the new `install`/`activate` lifecycle handling AD-9 requires.

## Acceptance Criteria

1. **Given** a published cycle, **when** the service worker is generated, **then** the cycle's build identifier is stamped into it, so its bytes differ from the previous cycle's (AD-9).
2. **Given** a new service worker is discovered, **when** it activates, **then** caches whose name does not carry the current identifier are deleted **and** `skipWaiting` and `clients.claim` are used so the update lands on the current visit, not the next one (AD-9).

## Tasks / Subtasks

- [ ] **Task 1: Stamp the cycle identifier into `sw.js` at site-build time** (AC1)
  - [ ] Add a new pre-build Node script (e.g. `site/scripts/stamp-service-worker.ts`, mirroring `copy-briefings-to-public.ts`'s own existing shape/conventions) that: reads the canonical Briefing's `generated_at` field (same file `index.astro`/`copy-briefings-to-public.ts` already treat as canonical — confirm and reuse the exact same path resolution, including its fixture fallback for local dev when `data/briefings/` is empty); derives a cache-name-safe identifier string from it (e.g. sanitizing `:`/`.` characters the same way `cycle_id_for` does, since `generated_at` is a raw ISO datetime with colons a cache name can technically contain but which reads awkwardly — decide and document the exact sanitization); reads `site/public/sw.js`'s source template, substitutes the identifier into a single, clearly-marked placeholder (e.g. a `__CACHE_VERSION__` token) for the `CACHE_NAME` constant's own value; writes the result to `site/public/sw.js` (or directly into a pre-`dist` staging step — decide consistent with `copy-briefings-to-public.ts`'s own precedent of writing into `public/` before `astro build` runs, so Astro's existing byte-for-byte copy behavior needs no changes).
  - [x] Added `site/scripts/stamp-service-worker.ts` (mirroring `copy-briefings-to-public.ts`'s conventions exactly) and updated `site/package.json`'s `build`/`dev` scripts to run it before `astro build`/`astro dev`.
  - [x] `site/public/sw.js` (the Story 5.2 checked-in file) was renamed via `git mv` to `site/public/sw.template.js` — the checked-in TEMPLATE, carrying the `__CACHE_VERSION__` placeholder inside `CACHE_NAME`. `public/sw.js` is now the generated artifact (added to `site/.gitignore`, same convention as `public/briefings/`), produced fresh by the stamping script every build.
  - [x] Confirmed via real builds: two stamps against identical `generated_at` data produce byte-identical `sw.js`; a stamp against modified `generated_at` produces different bytes containing the new value. Both confirmed by direct `diff`/inspection, not just by trusting the script's own logic.

- [x] **Task 2: Add `activate` handling — stale cache cleanup, `skipWaiting`, `clients.claim`** (AC2)
  - [x] `install` handler calls `self.skipWaiting()`.
  - [x] `activate` handler enumerates `caches.keys()`, deletes every name not equal to the current `CACHE_NAME` via `staleCacheNames`, confirmed this worker only ever creates the one cache both `networkFirst`/`cacheFirst` already read/write.
  - [x] `clients.claim()` is called only after the stale-cache deletion `Promise.all` has resolved (chained via `.then`, both inside the same `event.waitUntil`) — reasoned through explicitly in Dev Notes: by the time any client is claimed, only the current cycle's cache can possibly exist, so a freshly-claimed tab's next fetch never races a half-cleaned-up cache set.

- [x] **Task 3: Mirror the stamped `CACHE_NAME` reference into `sw-logic.ts`'s tests appropriately** (AC1, AC2)
  - [x] Confirmed `networkFirst`/`cacheFirst` need no changes (already take `cacheName` as a parameter). Extracted the 2 new pure pieces (`sanitizeCacheVersion`, `staleCacheNames`) into `sw-logic.ts`, hand-mirrored into `sw.js` exactly, matching Story 5.2's own established split.

- [x] **Task 4: Tests**
  - [x] 3 unit tests for `sanitizeCacheVersion`: real ISO string → exact expected sanitized output, different inputs produce different outputs, identical inputs produce identical output.
  - [x] 4 unit tests for `staleCacheNames`: filters correctly with 1 stale + 1 current, empty when only current exists, empty when nothing exists, and an unrelated cache name is also correctly treated as stale.
  - [x] New "Service worker cycle invalidation (Story 5.3)" describe block in `no-js-readable.test.ts`: confirms no leftover placeholder in stamped output (and that the template itself still carries it, proving the test isn't vacuous); byte-identical output across 2 stamps of the same data; different output when `generated_at` changes (fixture mutated and restored, same crash-safety discipline as prior stories' fixture-mutating tests); presence of `skipWaiting`, the `activate` listener, `caches.keys()`, `caches.delete`, and `clients.claim` in the real stamped output.
  - [x] The real cache-enumeration-and-deletion behavior is NOT exercised end-to-end against a real Service Worker runtime (not available in this implementation environment) — documented explicitly in Completion Notes, consistent with Stories 5.1/5.2's own precedent.
  - [x] Full verification pass run (see Completion Notes): all 6 commands clean.

## Dev Notes

### Why `generated_at`, not a new `cycle_id` field threaded through the pipeline

Adding a `cycle_id` field to the published Briefing schema would touch `pipeline/domain/`, `pipeline/stages/publish.py`, and the schema version (per the architecture spine's own "a schema change is a version bump, never a silent field edit" convention) — a real, cross-boundary change for a site-side-only story to make, and disproportionate when `generated_at` already uniquely identifies a cycle for this exact purpose (two different cycles always have different `generated_at` values; the same cycle's own 135 Briefings all share one). Revisit only if a future need requires distinguishing something `generated_at` genuinely can't (e.g. two cycles that could ever share a timestamp, which the pipeline's own `cycle_id_for` derivation makes structurally impossible today).

### Why the site build needs its own pre-build stamping script, not a pipeline-side change

AD-9's rule text says the cycle identifier "stamps the service worker" but the service worker is a `site/`-owned artifact (`site/public/sw.js`), built by `site/`'s own build process, entirely on the other side of AD-1/AD-2's pipeline/site boundary from where `cycle_id_for` is computed. The pipeline has no business writing into `site/public/`, and doesn't today. This story's stamping step reads already-published data (`data/briefings/.../generated_at`) the same way every other site-build-time read already does (`loadBriefing.ts`), respecting the existing boundary rather than reaching across it.

### Why same-cycle rebuilds must NOT change `sw.js`'s bytes

AD-9's own stated purpose is preventing "a stale service worker surviving a deploy and continuing to serve an old cache generation" — the mechanism is: new bytes → browser detects an update → new worker installs → activates → clears the old cycle's cache. If merely re-running the build (with no new cycle, same `generated_at`) also changed the bytes (e.g. by including a build timestamp instead of the cycle's own `generated_at`), every CI rebuild or redeploy would look like a new cycle to a reader's browser, forcing an unnecessary cache-clear-and-reactivate on every deploy regardless of whether the underlying content actually changed. Derive the stamp ONLY from `generated_at` (cycle-derived), never from `Date.now()`/a build timestamp (deploy-derived) — these are different things this story must not conflate.

### Previous Story Intelligence

- Story 5.2's own `sw.js` code comment (lines 16-18 of that story's shipped file) explicitly names this exact scope as "Story 5.3's own scope, not this one's" — confirms this story's boundary was anticipated correctly, not discovered as scope creep.
- Story 5.2's Blind Hunter review caught a real Medium-severity bug in `networkFirst`'s cache-write timing (a response that lost the timeout race but eventually succeeded was never cached) — a reminder that this file's async control flow has already produced one subtle, easy-to-miss bug; apply the same care to the new `activate` handler's own async sequencing (Task 2's explicit ordering concern).
- Story 5.1/5.2's Blind Hunter reviews both caught test-isolation bugs (a describe block silently depending on a different block's build; later, `indexOf`-based tag matching silently breaking once 2 scripts became byte-identical). Apply the same discipline: this story's own new build-output tests need their own explicit build step and must not assume anything about `dist/`'s prior state.
- `site/scripts/copy-briefings-to-public.ts` is the direct, load-bearing precedent for this story's new stamping script — read it in full before writing the new one, to match its established conventions (how it resolves the real-vs-fixture path, how it's wired into `package.json`'s scripts) rather than inventing a divergent new pattern for a structurally similar problem.

### Project Structure Notes

Files this story creates or modifies:
- `site/scripts/stamp-service-worker.ts` (new, or equivalent name)
- `site/public/sw.js` (modified — becomes a template with a placeholder token, plus new `install`/`activate` handlers)
- `site/src/islands/sw-logic.ts` (modified — new pure functions for sanitization/stale-cache filtering, per Task 3's decision)
- `site/src/islands/__tests__/sw-logic.test.ts` (modified)
- `site/package.json` (modified — new build/dev step)
- New or extended build-output tests (likely `no-js-readable.test.ts` or a new dedicated file)

No changes to `pipeline/` — confirmed no `cycle_id` field is added to the published schema; this story reads only the already-existing `generated_at` field.

### References

- [Source: epics.md#Story 5.3] — acceptance criteria origin (lines 790-805)
- [Source: ARCHITECTURE-SPINE.md#AD-9, Consistency Conventions "Cycle identity" row] — the 3-part rule (byte-stamping, stale-cache deletion, skipWaiting/clients.claim) and the cycle-identifier's own derivation (`cycle_id_for`, UTC-instant-derived)
- [Source: pipeline/stages/__init__.py#cycle_id_for] — confirms the exact cycle-identifier format used internally by the pipeline (not directly reusable site-side, since it never reaches the published schema)
- [Source: pipeline/stages/publish.py#assemble_briefings] — confirms `generated_at` (not `cycle_id`) is the only cycle-identifying field that actually reaches `data/briefings/`
- [Source: site/scripts/copy-briefings-to-public.ts] — the direct precedent for a pre-`astro build` Node script rewriting a `public/`-destined file's content
- [Source: _bmad-output/implementation-artifacts/5-2-serve-fresh-content-first-cache-only-as-a-fallback.md] — `sw.js`'s current shape (`CACHE_NAME` constant, `networkFirst`/`cacheFirst`, no `install`/`activate` handlers yet), and its own review learnings about async cache-write timing bugs

## Dev Agent Record

### Context Reference

Story spec + epics.md#Story 5.3 + architecture spine AD-9 + direct research confirming no `cycle_id` field exists in the published Briefing schema, confirming the pipeline/site build processes are currently disconnected, and confirming `copy-briefings-to-public.ts` as the direct precedent for pre-build `public/` file rewriting + Story 5.2's own shipped `sw.js`/`sw-logic.ts`.

### Debug Log

- The `sw.template.js` header comment's own prose originally spelled out the literal `__CACHE_VERSION__` token to explain what it does — since the stamping script's substitution is a global regex replace, this caused the comment's own prose to get silently corrupted too (the comment's example text got replaced along with the real placeholder). Fixed by rewording the comment to describe the mechanism without ever spelling out the literal token string.

### Completion Notes

- All 3 parts of AD-9's rule are implemented: (1) `CACHE_NAME` is stamped from the current cycle's sanitized `generated_at` at site-build time, confirmed byte-identical across same-cycle rebuilds and different across cycles; (2) `activate` deletes every cache not carrying the current identifier; (3) `skipWaiting`/`clients.claim` are both present and correctly sequenced.
- Introduced a new checked-in/generated file split, following `public/briefings/`'s own established convention exactly: `site/public/sw.template.js` (checked in, carries the placeholder) vs. `site/public/sw.js` (gitignored, regenerated every build by the new `stamp-service-worker.ts` script). This is a repo-shape change worth flagging explicitly: Story 5.2's `sw.js` is now `sw.template.js`, and anyone running the site locally for the first time after this story needs `npm run build` or `npm run dev` (both now run the stamping step) before `public/sw.js` exists at all.
- **Known, explicitly-flagged gap:** the real cache-enumeration-and-deletion behavior (does `caches.keys()` + `caches.delete()` actually work correctly when a real browser has a real previous-cycle cache sitting around) is verified by code inspection and by confirming the right API calls are present in the real stamped output, but not exercised end-to-end against a real Service Worker runtime — consistent with Stories 5.1/5.2's own precedent for this exact class of gap (no interactive browser/Service Worker environment available in this implementation).
- The `activate` handler's ordering (stale-cache deletion awaited via `Promise.all` before `clients.claim()` runs) was reasoned through explicitly rather than assumed: by the time any client is claimed, deletion has already resolved, so a freshly-claimed tab's very next fetch can only ever see the current cycle's cache — never a half-cleaned-up set.

### File List

- `site/public/sw.template.js` (renamed from `site/public/sw.js` via `git mv`, modified)
- `site/scripts/stamp-service-worker.ts` (new)
- `site/src/islands/sw-logic.ts` (modified)
- `site/src/islands/__tests__/sw-logic.test.ts` (modified)
- `site/package.json` (modified)
- `site/.gitignore` (modified)
- `site/e2e/no-js-readable.test.ts` (modified)

## Senior Developer Review (AI)

Single-layer adversarial review (Blind Hunter), per the standing cost-reduction decision. Directed to hunt for a cache-name collision via timezone-offset sanitization, tracking/gitignore interaction risk from the `sw.js` → `sw.template.js` rename, the `activate` handler's real async ordering, and mirror fidelity between `sw-logic.ts` and `sw.template.js`.

**Outcome: Approved, no functional findings.**

### Findings

No High/Med/Low functional defects survived verification. The reviewer traced a theoretical `sanitizeCacheVersion` collision (two different `generated_at` values with opposite-sign timezone offsets both sanitizing to the same string) but confirmed by reading the actual pipeline data flow (`pipeline/stages/cycle.py` → `datetime.now(UTC).isoformat()`) that the pipeline can only ever produce a `+00:00`-suffixed `generated_at` — never a non-zero offset — so the collision has no reachable input in this codebase today; correctly not filed as a defect. The reviewer independently re-verified (not just trusted the story's own Dev Notes prose) that the `activate` handler's `Promise.all(...).then(() => clients.claim())` composition genuinely cannot let `clients.claim()` run before cache deletion resolves, that the `sw.js` → `sw.template.js` rename left no stale tracked file or gitignore interaction bug, and that the fixture-mutating test correctly restores state via `try/finally` even on a failed assertion.

One cosmetic-only nit was raised (not a formal finding): `sw.template.js`'s own header comment listed `sanitizeCacheVersion` among the functions "hand-kept mirrored" in that file, when in fact that function is build-time-only (runs in the Node stamping script, never at worker runtime) and has no runtime mirror to keep in sync. Fixed directly (no action-item cycle needed) by rewording the comment to name only the functions actually mirrored there (`classifyRequest`, `withTimeout`, `staleCacheNames`) and explain why `sanitizeCacheVersion` is the one exception.

### Post-Review Fixes

- `site/public/sw.template.js`: corrected the header comment's inaccurate claim about which functions are hand-mirrored there.
- Re-ran full verification after the fix: `npx tsc --noEmit`/`npx astro check` → clean; stamp + `npx astro build` → 136 pages; `npx vitest run` → 171/171 passing; `uv run pytest` → 315/315 passing; `bash scripts/check-boundary.sh` → clean.

## Change Log

- 2026-08-13: Story created via bmad-create-story. Researched the real cycle-identifier data flow before writing the spec: confirmed no `cycle_id` field reaches the published Briefing schema (only `generated_at` does), confirmed the pipeline's cycle workflow and the site's build are two disconnected processes with no combined deploy pipeline in this repo, and confirmed `copy-briefings-to-public.ts` as the established precedent for pre-build `public/` file content rewriting. Scoped this story to derive the stamped identifier from `generated_at` (not a new pipeline-side `cycle_id` field) explicitly to avoid a disproportionate cross-boundary schema change, and to implement all 3 parts of AD-9's rule (byte-stamping, stale-cache deletion on activate, skipWaiting/clients.claim) rather than just the most obvious one.
- 2026-08-13: All 4 tasks implemented and verified (171 site tests, 315 pipeline tests, boundary check clean, 136-page build with a freshly-stamped `sw.js`). Introduced the `sw.template.js` (checked-in) / `sw.js` (generated, gitignored) split, mirroring `public/briefings/`'s own established convention. Caught and fixed a self-inflicted bug during implementation: the template's own header comment spelled out the literal placeholder token, which the global substitution then silently corrupted along with the real code. Status set to `review` ahead of the single-layer Blind Hunter adversarial review.
- 2026-08-13: Blind Hunter review found no functional defects — traced a theoretical cache-name-collision concern to a non-reachable input space, and independently re-verified (not just trusted) the `activate` handler's async ordering and the rename's git-tracking safety. Fixed one cosmetic comment-accuracy nit directly. Status set to `done`.
