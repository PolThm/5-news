---
baseline_commit: 274598b
---

# Story 5.4: Serve an honest offline experience

Status: done

## Story

As a commuter in a tunnel,
I want to know that what I am reading is from an earlier cycle,
So that I am not misled about what is current.

## Scope, decided explicitly before this story was written

**A real, genuine gap exists relative to AC2 today — the current cache is unbounded, not "at most the reader's last-viewed Briefing."** Direct research confirmed: `networkFirst` writes every successful response (both page navigations AND `/briefings/*.json` fetches) into the single `CACHE_NAME` cache with no eviction, no cap, no "is this a different Briefing than last time" check. `Cache.put` keys by request URL, so each distinct Zone/Period/Language combination a reader clicks through (Story 4.2-4.7's own mad-libs interaction makes this easy — a reader can visit many combos in one session) becomes its own additive cache entry. Story 5.3's `activate` handler only deletes caches from a *previous cycle*; it does nothing about entries accumulating *within* the current cycle's single cache. Left alone, a reader who clicks through several Zone/Period/Language combinations would have all of them cached simultaneously — exactly the "full 135-Briefing matrix" scenario AC2 explicitly forbids, just reached one click at a time rather than all at once. This story must close that gap, not just build the offline-messaging UI on top of an already-correct cache.

**No shell/content classification distinction exists today — `classifyRequest` treats a page navigation and a Briefing JSON fetch identically (both "network-first," same cache).** This story needs to introduce that distinction: the application shell (the page's own HTML structure, CSS, JS — everything that ISN'T the Briefing's own data) should be treated as effectively cache-first/always-available, while Briefing content (both the HTML's data-bearing portions and the JSON) gets the "keep only the most recent one" eviction behavior. Given this site's actual architecture — Astro renders a single monolithic HTML document per route, with Briefing data baked directly into the same markup as the shell (Story 4.1's own design, no client-side hydration boundary) — a byte-level shell/content split within one HTML response is not feasible without a much larger restructuring. The pragmatic, correct-for-this-architecture approach: treat the *page navigation* cache entry itself as "the reader's last-viewed Briefing" (since, for this site, a cached page IS a cached Briefing — they're the same document), and additionally cache the *hashed assets* (already cache-first, already effectively "the shell" in practice) separately and permanently. Apply the "keep only the most recent" eviction rule to the network-first cache entries specifically (pages + JSON), not to the cache-first hashed-asset entries, which should keep accumulating exactly as they already do (they're small, immutable per build, and already correctly excluded from AD-9's per-cycle cache-clearing).

**No offline-detection, offline-UI, or fallback-page code exists anywhere in this codebase today — this is new, from scratch.** `networkFirst`'s own catch block already has the exact hook point (confirmed via direct code reading: on a cache miss + network failure, it currently does `return networkFetch`, propagating the raw failure, with an explicit code comment saying this exact scenario is "Story 5.4's own scope"). This story fills that hook, and adds the "no cached Briefing at all" case (AC3) as a distinct, explicit response — not a browser's own generic offline/error page.

**No staleness/freshness-comparison mechanism exists — `timestampPrefix`/`formatTimestamp` only format `generated_at` into a display string, with no comparison against the current time.** This story needs new logic (comparing the served-from-cache Briefing's `generated_at` against "now") to decide whether/how to show the "this is from an earlier cycle" banner (AC1) — though note AC1's own phrasing ("when the reader opens the application" with "no connection") ties the banner to the offline-fallback code path itself, not to a general "is this Briefing old" heuristic that would also need to fire for an online-but-slow-network scenario; scope the banner to the offline/cache-fallback path specifically, per AC1's own literal wording, not a broader "staleness" feature.

**This story does not change AD-8's network-first/cache-first classification logic for the cases it already handles correctly, and does not change AD-9's per-cycle cache-versioning mechanics (Story 5.3's own, already-shipped, already-reviewed work).** Only: (1) the network-first cache-write path gains a "delete other Briefing entries before writing this one" eviction step; (2) the offline-fallback path gains real logic instead of propagating a raw failure; (3) a new, dedicated offline-fallback HTML response is introduced for the "nothing cached at all" case.

## Acceptance Criteria

1. **Given** no connection, **when** the reader opens the application, **then** the last-viewed Briefing is served from cache **and** the page states that it is from an earlier cycle, with its generation timestamp (FR-21, FR-19).
2. **Given** the offline cache, **when** its contents are inspected, **then** it holds the application shell and at most the reader's last-viewed Briefing — never the full 135-Briefing matrix (NFR-6).
3. **Given** no connection and no cached Briefing, **when** the reader opens the application, **then** they see a stated offline condition rather than a blank page or a browser error.

## Tasks / Subtasks

- [x] **Task 1: Cap the network-first cache to the single most-recently-viewed Briefing** (AC2)
  - [x] `networkFirst`'s cache-write step (both `sw.template.js` and its `sw-logic.ts` mirror): writes the new response, THEN deletes every OTHER entry classified `"network-first"` — hashed assets/manifest/icon files (`"cache-first"`) are filtered out before the eviction step ever sees them, so they're never touched.
  - [x] Extracted as `evictOtherNetworkFirstEntries` in `sw-logic.ts`, unit-tested without a real Cache API.
  - [x] Decided write-then-delete (not delete-then-write), documented in Dev Notes: deleting first would open a real window with ZERO cached network-first entries, during which a concurrent offline read would see no cache hit at all — writing first means the cache briefly holds at most two entries, never zero, a strictly safer transient state for a cache whose whole purpose is being the offline safety net.

- [x] **Task 2: Add real offline-fallback logic to `networkFirst`'s catch path** (AC1, AC3)
  - [x] Decided the signaling mechanism (documented in Dev Notes, changed from the spec's own suggested "custom header" after discovering HTTP response headers aren't readable by page JS after a real navigation has already completed): the worker injects a `<meta name="offline-cache" content="true">` tag into a cached HTML page's own body when serving it from the offline-fallback path — a normal DOM read, available immediately on page load.
  - [x] When there's no cache hit and the network genuinely failed (AC3): a dedicated, minimal, per-language offline-fallback HTML page is synthesized entirely in the worker (`buildOfflineFallbackHtml`), using `extractLangFromPath` to determine the language from the request URL.
  - [x] Confirmed the offline-fallback HTML is never written to the cache — it's constructed and returned directly, with no `cache.put` call anywhere near it.

- [x] **Task 3: Show the "earlier cycle" banner client-side when serving from the offline cache** (AC1)
  - [x] `sw-register.ts` (extended, not a new file) checks for the `offline-cache` meta tag on page load and reveals `BriefingPage.astro`'s own server-rendered `#offline-banner` element (already correctly per-language, since it's rendered at build time with the same `lang` prop every other string uses) — no new client-side text-formatting logic needed at all.
  - [x] Banner copy added to `briefing.ts` (`offlineBannerText`) and hand-mirrored into `sw-logic.ts`'s own copy (used by the worker's build-output tests, not by `sw-register.ts` itself, which reads the already-rendered server-side text) — each language authored independently, not a mechanical translation.
  - [x] Decided the banner's color pairing differently than the spec originally suggested: `secondary`/`on-secondary-container` is explicitly reserved in DESIGN.md for exactly one meaning (the Continent-fallback notice) and `tertiary` is reserved for the Consensus source list — reusing either would violate DESIGN.md's own "must never appear for any other purpose" rule for both accent colors. Used the neutral `surface-container-high`/`on-surface-variant` pairing instead (already used for the Discarded Volume footer's own quiet, structural tone), documented in the CSS's own comment.

- [x] **Task 4: Tests**
  - [x] Unit tests for `evictOtherNetworkFirstEntries`/`networkFirst`'s eviction integration: N network-first entries + M cache-first entries → eviction leaves exactly 1 network-first entry, all M cache-first entries untouched.
  - [x] Unit tests for `buildOfflineFallbackHtml`: correct per-language content; confirmed by code inspection (not a test assertion, since "never written to cache" is an absence-of-a-call-site property) that no code path caches this response.
  - [x] Unit tests for `injectOfflineBannerMeta` (insertion, preservation of the rest of the document, no-op on no `<head>`) and `extractLangFromPath` (both page and JSON path shapes, root-path and unrecognized-segment fallback to French).
  - [x] Build-output tests: the banner markup/copy present (hidden by default) on both `/` and a `[lang]/[zone]/[period]` route; the detection script's `querySelector`/`getElementById` calls present on both; `sw.js`'s own real stamped output contains the new eviction/fallback/injection function definitions.
  - [x] Documented in Completion Notes: the full offline scenario (real browser offline mode, confirming the banner actually appears, confirming the dedicated fallback page actually appears with zero cache) is NOT mechanically tested end-to-end — no real Service Worker/offline-network-simulation runtime available in this implementation environment. What WAS verified: all pure logic via unit tests, and every piece of markup/script/generated-worker-content via build-output presence checks.
  - [x] Full verification pass run (see Completion Notes): all 6 commands clean.

## Dev Notes

### Why "the last-viewed Briefing" means "the last-viewed page navigation," not a separately-tracked concept

This site has no client-side Briefing state independent of the page itself (Story 4.1's architecture: Astro renders one full HTML document per route, Briefing data baked directly into that markup, no hydration boundary). A JS-present reader's `/briefings/*.json` fetches (after a Zone/Period/Language click) update the CURRENT page in place without a full navigation — so at any moment, "the last-viewed Briefing" is simply whichever page/JSON response was most recently cached, matching Task 1's eviction rule exactly. No separate "which Briefing is the reader currently looking at" tracking mechanism is needed beyond the cache's own most-recent-entry state.

### Why the offline-fallback page is synthesized in the worker, not a separate cached asset

A dedicated `/offline.html`-style asset would itself need to be reliably cache-first-available from the very first visit (install-time pre-caching) to guarantee it's there when genuinely needed — a real option, but this story's Task 2 note on why Story 5.2 deliberately avoided install-time pre-caching (Astro's per-build content hash makes pre-listing filenames impractical for a hand-written worker) applies with equal force here, and an unhashed, always-the-same offline page is a case where pre-caching WOULD be simple — reconsider if this turns out more complex in practice than the inline-string approach. Default to the inline-string approach for this story unless implementation reveals a concrete reason it's actually harder than pre-caching one small static file.

### Why the offline-signal mechanism changed from a header to an injected `<meta>` tag

This story's own Scope section originally floated "a custom response header the service worker adds" as one candidate mechanism. Implementation discovered a real blocker: `event.respondWith`'s response headers describe the HTTP exchange, but by the time page JS runs (after a real navigation has already completed and rendered), there is no API that exposes the ORIGINAL navigation response's own headers to that page's own script — `fetch()`'s own Response object exposes headers, but that's a different, JS-initiated request, not the browser's own top-level navigation. The signal has to live somewhere page JS CAN read after the fact: the document itself. Rewriting the cached HTML's body to inject a `<meta>` tag (only on the offline-fallback path, never on a normal network-success response) solves this with a completely ordinary `document.querySelector` check, no new browser API surface needed. A `/briefings/*.json` fetch (the OTHER network-first content type) doesn't have this problem at all — the client's own `fetch()` call site already has direct access to that response's real headers or body, so no rewrite is needed for that case (though this story doesn't actually add JSON-fetch-specific offline messaging, since AC1's own wording — "when the reader opens the application" — scopes the banner to a page navigation specifically, not a background JSON refetch).

### Why the banner's colors are `surface-container-high`/`on-surface-variant`, not `secondary`/`on-secondary-container`

This story's own Scope section originally suggested reusing the `secondary`/`on-secondary-container` pairing (the Continent-fallback notice's own colors), reasoning they were "thematically similar." Direct re-reading of `BriefingPage.astro`'s own CSS comment and DESIGN.md's Colors section revealed this was wrong: `secondary` is explicitly documented as reserved for exactly the Continent-fallback notice and must never appear elsewhere ("a reader who has learned 'red means substitution' must never have that association contradicted"), and `tertiary` is likewise reserved for the Consensus source list. Reusing either would violate DESIGN.md's own stated rule, not just a style preference. Used the neutral `surface-container-high`/`on-surface-variant` pairing instead — no semantic reservation, already used for the Discarded Volume footer's own quiet, structural tone, which matches this banner's own "calm disclosure, not alarm" framing better than either reserved accent color would have anyway.

### Previous Story Intelligence

- Story 5.2's Blind Hunter review caught a real Medium-severity bug in `networkFirst`'s own async cache-write timing — this file's control flow has already produced one subtle, easy-to-miss bug once; apply the same care to this story's own new eviction step, which touches the same function.
- Story 5.3's Blind Hunter review found no functional defects but is a reminder that this codebase's adversarial review process holds up well when the implementer independently re-derives correctness (e.g. tracing the real pipeline data flow) rather than trusting written reasoning at face value — apply the same standard to Task 1's ordering decision (delete-then-write vs. write-then-delete) and Task 2's chosen offline-signal mechanism.
- Every prior story's per-language content work (Zone/Period grammar, End Screen singular/plural, fallback-notice verb agreement, this epic's own Output-Language-control announcement text) was authored independently per language, never a mechanical translation — apply the same discipline to the new offline-banner copy in Task 3.
- This is the FINAL story of Epic 5 (and of the currently-planned epics) — after this story, run a final full-repo verification pass and consider whether a retrospective or summary is warranted, consistent with how prior epics closed out.

### Project Structure Notes

Files this story creates or modifies:
- `site/public/sw.template.js` (modified) — eviction logic, offline-fallback HTML generation, offline-signal header
- `site/src/islands/sw-logic.ts` (modified) — new pure eviction/fallback-generation functions
- `site/src/islands/__tests__/sw-logic.test.ts` (modified)
- `site/src/lib/briefing.ts` (modified) — new per-language banner copy, rendered server-side once
- `site/src/islands/sw-register.ts` (modified) — extended with the offline-cache meta-tag detection and banner-reveal logic
- `site/src/components/BriefingPage.astro` (modified) — new banner markup/CSS
- `site/src/lib/__tests__/briefing.test.ts` (modified)
- `site/e2e/no-js-readable.test.ts` (modified)

No changes to `pipeline/`.

### References

- [Source: epics.md#Story 5.4] — acceptance criteria origin (lines 807-826)
- [Source: ARCHITECTURE-SPINE.md#AD-8, NFR-6] — "the offline cache is a safety net, never the default source"; NFR-6's own offline-scope constraint
- [Source: site/public/sw.template.js, site/src/islands/sw-logic.ts] — confirmed the exact current gap: unbounded cache accumulation, no shell/content distinction, no offline-fallback logic (explicit code comment naming this story), no staleness-comparison mechanism
- [Source: site/src/lib/briefing.ts#timestampPrefix, site/src/islands/period-switcher.ts#formatTimestamp] — the existing per-language timestamp-formatting mechanism this story's banner reuses
- [Source: _bmad-output/implementation-artifacts/5-2-serve-fresh-content-first-cache-only-as-a-fallback.md, 5-3-invalidate-the-cache-on-every-published-cycle.md] — the service worker's current shipped behavior and review learnings this story builds directly on top of

## Dev Agent Record

### Context Reference

Story spec + epics.md#Story 5.4 + direct research confirming a real, previously-unaddressed gap in the current cache's unbounded accumulation (relative to AC2), confirming zero existing offline-detection/fallback-page code, and confirming the existing per-language timestamp-formatting mechanism this story's banner will reuse + Stories 5.2/5.3's own shipped service-worker code and review learnings.

### Debug Log

- The originally-planned "custom HTTP header" offline-signal mechanism (Task 2) turned out not to work: page JS has no API to read the original navigation response's own headers after the page has already loaded. Switched to injecting a `<meta>` tag into the cached HTML's own body instead — a normal DOM read, no new browser API surface needed. See Dev Notes for the full reasoning.
- The originally-planned `secondary`/`on-secondary-container` color pairing for the banner (Task 3) turned out to violate DESIGN.md's own explicit rule reserving that pairing for exactly the Continent-fallback notice (and `tertiary` for the Consensus source list). Switched to the neutral `surface-container-high`/`on-surface-variant` pairing. See Dev Notes for the full reasoning.
- A `sw-register.ts` initial draft duplicated the banner's per-language text as a second string table, mirroring the pattern used everywhere else in this codebase for genuinely client-side-computed content — caught during implementation that this was unnecessary here: the banner text is rendered server-side once (like every other static per-language string in `BriefingPage.astro`), so `sw-register.ts` only needs to reveal an already-correct, already-rendered element, not compute or format anything itself. Removed the unnecessary duplication.

### Completion Notes

- All 3 genuine gaps this story's own Scope section identified are closed: (1) the network-first cache now holds at most one entry (any previous Zone/Period/Language combination's cache entry is evicted the moment a new one is successfully written), closing the real AC2 gap that existed before this story; (2) a real network failure with a cached page now has that page's HTML tagged with an `offline-cache` meta marker, and `sw-register.ts` reveals the already-rendered, already-per-language `#offline-banner` element when it detects that marker; (3) a real network failure with nothing cached at all now serves a dedicated, minimal, per-language offline-fallback page synthesized entirely in the worker, never a blank page or browser error.
- Two implementation-time design decisions diverged from the story's own originally-suggested mechanisms (a header instead of a meta tag; `secondary` colors instead of neutral ones) — both changes are fully documented in Dev Notes with the concrete reason each original suggestion didn't actually work, not silently substituted.
- **Known, explicitly-flagged gap:** the full offline scenario (actually disabling network in a real browser, confirming the banner visually appears, confirming the dedicated fallback page visually appears with zero cache) was NOT tested end-to-end — no real Service Worker/offline-network-simulation runtime is available in this implementation environment. What WAS verified: every pure function via unit tests (eviction, HTML generation, meta-tag injection, language extraction), and every piece of generated content/markup/script via build-output presence checks against the REAL stamped `sw.js` and REAL built HTML (not just the source templates) — consistent with Stories 5.1-5.3's own established precedent for this exact class of gap.
- This is the final story of Epic 5 (and of all currently-planned epics). A final full-repo verification pass was run as part of this story's own closing sequence; no epic-level retrospective document was produced, since none of Epics 1-4 produced one either (checked `_bmad-output/implementation-artifacts/` for any `*-retrospective.md` file — none exists for any prior epic, so not introducing one now for consistency).

### File List

- `site/public/sw.template.js` (modified)
- `site/src/islands/sw-logic.ts` (modified)
- `site/src/islands/__tests__/sw-logic.test.ts` (modified)
- `site/src/lib/briefing.ts` (modified)
- `site/src/lib/__tests__/briefing.test.ts` (modified)
- `site/src/islands/sw-register.ts` (modified)
- `site/src/components/BriefingPage.astro` (modified)
- `site/e2e/no-js-readable.test.ts` (modified)

## Senior Developer Review (AI)

**Reviewer:** Blind Hunter (single adversarial layer, per this project's established review depth)
**Date:** 2026-08-13
**Outcome:** Changes Requested → Fixed

### Summary

Blind Hunter review found one real High-severity bug, one real Medium-severity divergence between tested and shipped logic, and one Low-severity observation that isn't a defect. Both actionable findings are fixed and re-verified; the Low finding is deliberately left as-is with reasoning recorded below, consistent with how Story 5.2's own Low findings were handled.

### Action Items

- [x] **[High]** `evictOtherNetworkFirstEntries` treated page-navigation HTML and same-page `/briefings/*.json` fetches as one shared eviction pool. Since a mad-libs click updates the page via `history.pushState` (never a real navigation, per `period-switcher.ts`), the resulting JSON fetch evicted the currently-displayed page's own cached HTML with nothing to replace it — going offline and reloading after any click would wrongly show the "nothing cached" fallback instead of the correct "last-viewed, from an earlier cycle" banner, violating both AC1 and AC2.
- [x] **[Medium]** `sw-logic.ts`'s unit-tested `networkFirst` never actually called `injectOfflineBannerMeta`/`buildOfflineFallbackHtml`/`extractLangFromPath` — it returned a bare `{response, servedFromOfflineCache}` shape while `sw.template.js`'s real shipped function had entirely separate inline orchestration logic. The tests were proving the wrong thing: a passing test suite gave no actual assurance about the shipped worker's real offline-fallback behavior.
- [ ] **[Low]** The `Content-Type` substring check (`!contentType.includes("json")`) used to distinguish cached HTML from cached JSON depends on an as-yet-undecided hosting target's content-type behavior. Not a defect now — no host configuration exists yet (the architecture's own hosting decision is still deferred) — so there's nothing concrete to fix. Revisit once a hosting target is chosen, if that target's actual `Content-Type` behavior differs from what's assumed here.

### Post-Review Fixes

- **High finding:** Split eviction into two independent sub-pools via a new `isJsonBriefingFetch(url)` classifier — `evictOtherNetworkFirstEntries` now only evicts other entries of the *same* shape (JSON vs. JSON, page vs. page), never across shapes. Applied identically in `sw-logic.ts` and `sw.template.js`. New regression test: "evicts other JSON entries when writing a new JSON entry, but never the currently-cached HTML page."
- **Medium finding:** Restructured `sw-logic.ts`'s `networkFirst` to return a `NetworkFirstOutcome` discriminated union (`"network-success"` / `"offline-cache-hit"` / `"offline-no-cache"`) that encodes every real decision the function makes, calling `isJsonBriefingFetch`/`extractLangFromPath` internally — the tested function's own logic is now what actually determines behavior. `sw.template.js`'s hand-mirrored `networkFirst` re-checked against this structure: its inline catch-branch logic (cache hit → HTML/JSON branch → tagged `Response` or raw cached JSON; no cache → synthesized fallback page) already implements the same decision tree byte-for-byte, just using real `Response`/`Headers` construction instead of a TypeScript union (a legitimate difference, since building a real browser `Response` object requires APIs unavailable in the pure-logic test environment). All `networkFirst` tests in `sw-logic.test.ts` rewritten for the new outcome shape.
- **Low finding:** Left as-is, with the reasoning above recorded here rather than acted on.

### Re-verification

All 6 verification commands re-run clean after fixes: `tsc --noEmit` (0 errors), `astro check` (0 errors/warnings/hints), `astro build` (136 pages), `vitest run` (189 tests passing, up from 187 — 2 new tests added by the fixes), `uv run pytest` (315 passed), `check-boundary.sh` (pipeline/site independence confirmed).

## Change Log

- 2026-08-13: Story created via bmad-create-story. Researched the current service worker's real behavior before writing the spec, rather than assuming AC2 was already satisfied: confirmed a genuine gap (the cache accumulates every distinct Briefing a reader visits in a session, unbounded, not "at most the last-viewed one") that this story must close as part of its own scope, not just build offline-messaging UI on top of an already-correct cache. Confirmed zero existing offline-detection/fallback-page/staleness-comparison code exists anywhere — this is new territory. Scoped the offline-fallback page as a worker-synthesized inline HTML string (not a separately-cached asset) and the "last-viewed Briefing" concept as simply "the cache's own most recent network-first entry," given this site's architecture has no separate client-side Briefing-tracking state to hook into.
- 2026-08-13: All 4 tasks implemented and verified (187 site tests, 315 pipeline tests, boundary check clean, 136-page build). Two of the spec's own originally-suggested mechanisms (a custom HTTP header for the offline signal; reusing `secondary` colors for the banner) were changed during implementation after discovering they didn't actually work/were disallowed — both changes fully documented in Dev Notes and Debug Log, not silently substituted. Status set to `review` ahead of the single-layer Blind Hunter adversarial review.
- 2026-08-13: Blind Hunter review completed — 1 High, 1 Medium, 1 Low finding. High (cross-shape eviction collision breaking AC1/AC2 on any mad-libs click) and Medium (tested `networkFirst` logic diverged from shipped logic) both fixed and re-verified; Low (Content-Type detection depends on an undecided hosting target) deliberately left open with reasoning recorded. All 6 verification commands clean (189 site tests, 315 pipeline tests). Status set to `done`.
