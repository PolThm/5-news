---
baseline_commit: 3f0dea9
---

# Story 5.2: Serve fresh content first, cache only as a fallback

Status: done

## Story

As a reader opening the app in the morning,
I want today's Briefing, not yesterday's from cache,
So that the product's central promise is not silently broken.

## Scope, decided explicitly before this story was written

**This story introduces the site's first service worker (`site/public/sw.js` does not exist yet).** No `@astrojs/*` PWA integration package exists in `site/package.json`, and Astro's `output: "static"` config has no built-in service-worker generation — this is a hand-written `sw.js`, registered by a new client-side script, from scratch.

**Two genuinely different content shapes need two different caching rules, per AD-8's own explicit split — do not conflate them:**
- **Briefing content** (network-first, short timeout, cache as fallback only): this covers BOTH (a) the 135 static `/briefings/<lang>/<zone>/<period>.json` files the client fetches after a Zone/Period/Language click (`period-switcher.ts`'s `briefingJsonUrl`/`fetch`), AND (b) the 136 HTML pages themselves (`/`, and the 135 `/<lang>/<zone>/<period>` routes) — a no-JS reader's first paint comes entirely from the server-rendered HTML (`BriefingPage.astro` bakes `briefing.clusters` etc. directly into markup at build time), so the HTML document itself is just as much "Briefing content" as the JSON is, for AD-8's purposes. Caching the HTML stale-while-revalidate or cache-first would guarantee a no-JS reader's first paint is yesterday's news — exactly the failure AD-8 exists to prevent — even if the JSON fetch path were handled correctly.
- **Hashed assets** (cache-first): the 2 files under `dist/_astro/` (a content-hashed JS bundle and a content-hashed CSS file, hash changes on every content change) plus `manifest.json`/`icon-192.png`/`icon-512.png` (unhashed, but effectively immutable between deploys — see Task 2's note on how to treat these).

**A 2–3 second network timeout is this story's own tunable, per the epic's `[ASSUMPTION]` tag — pick a specific value and document why, don't leave it symbolic.** The epics file itself flags this as `[ASSUMPTION: 2–3s — tune against real mobile conditions]`. No real mobile-network measurement is available in this implementation's environment; pick 3000ms (the upper end of the suggested range, erring toward giving a slow-but-working connection more chance to succeed before falling back, since AD-8's own stated worst failure is a *silent* stale read — a slightly slower fallback trigger is a better trade than a premature one) and state this reasoning in Dev Notes rather than picking a number arbitrarily.

**Stale-while-revalidate is explicitly forbidden for Briefing content (AD-8's own text) — do not implement it even as an "optimization."** This is not a style preference; it is the architecture spine's own named anti-pattern for this exact content type, because it guarantees the first paint on any repeat visit is whatever was previously cached, contradicting this story's entire purpose.

**This story does NOT implement cache invalidation on new-cycle-publish (AD-9) or the honest offline experience UI (Story 5.4) — those are Stories 5.3/5.4's own scope.** This story's service worker will, by construction, already cache Briefing responses as a fallback (that's what "cache only as a fallback" requires) — but the mechanics of stamping a cycle identifier into the worker's own bytes and deleting stale-named caches on activation (AD-9) is Story 5.3's job, and a dedicated "you're offline, here's your last-viewed Briefing with its real timestamp" UI is Story 5.4's job. Do the minimum caching-fallback mechanics this story's own ACs require; do not build ahead into 5.3/5.4's territory even though the code will visibly want a `CACHE_NAME` constant that Story 5.3 will need to change — leave it simple and let 5.3 own the versioning scheme.

**Registration is new — no existing script registers a service worker anywhere in this codebase today.** Confirmed via a full grep: zero `navigator.serviceWorker.register` calls exist. This story adds the registration call, deciding where it goes: since the service worker must intercept requests on every route (not just `/`), the registration script must load on every page `BriefingPage.astro` renders — unlike `language-detect.ts`, which is deliberately `/`-only via the `extra-scripts` slot (Story 4.7's own scoping decision for a different reason). Register directly alongside `period-switcher.ts`'s own always-loaded `<script>` tag, not through the `/`-only slot.

## Acceptance Criteria

1. **Given** a working connection, **when** the reader opens the application, **then** Briefing content is fetched from the network first, and the cache is used only after the network fails or exceeds a short timeout (FR-21, AD-8).
2. **Given** a new cycle has published, **when** a returning reader opens the application, **then** they see that cycle's Briefing, not the previous one.
3. **Given** hashed assets, **when** they are requested, **then** they are served cache-first (AD-8).
4. **Given** any implementation, **when** the caching strategy is reviewed, **then** stale-while-revalidate is not used for Briefing content — it would guarantee the first paint is yesterday's (AD-8).

## Tasks / Subtasks

- [x] **Task 1: Write `site/public/sw.js`** (AC1, AC3, AC4)
  - [x] No `install`-time pre-cache for either content shape — decided and documented (see Dev Notes): cache-first is implemented purely as "cache on first successful fetch, serve from cache on every subsequent request," since Astro's per-build content hash makes pre-listing hashed filenames in a hand-written worker impractical.
  - [x] `fetch` event handler classifies every request via `classifyRequest(url)`: `/_astro/*` and the 3 Story 5.1 files (`manifest.json`, `icon-192.png`, `icon-512.png`) → cache-first; `/briefings/*.json` and every page-shaped path (no file extension) → network-first; `/sw.js` itself and any unrecognized-extension path → passthrough (untouched, default browser handling).
  - [x] Network-first-with-timeout: `withTimeout(fetch(request), 3000)`; on success, cache the cloned response then return it; on timeout/failure, fall back to `caches.match`, and only if nothing is cached, let the real (still-pending) `fetch(request)` be the final answer — no fabricated empty response.
  - [x] Confirmed no stale-while-revalidate code path exists: the only cache write for Briefing content happens strictly after a real, foreground, awaited network success inside `networkFirst`.
  - [x] Cache-first: `caches.match` first; cache hit returns immediately with zero network involvement; miss fetches once and caches the result.
  - [x] Single `CACHE_NAME = "briefings-v1"` constant — no cycle-identifier versioning (Story 5.3's own scope).

- [x] **Task 2: Register the service worker on every page** (AC1)
  - [x] `site/src/islands/sw-register.ts` — feature-detects `"serviceWorker" in navigator`, calls `.register("/sw.js").catch(() => {})`.
  - [x] Wired directly into `BriefingPage.astro`'s always-loaded `<script>` block (not the `/`-only `extra-scripts` slot) — reaches all 136 pages.
  - [x] Registration failure is swallowed via `.catch()`; confirmed by a dedicated test that the registration call is chained with `.catch(`.

- [x] **Task 3: Confirm the URL classification is complete and correct against the real build output** (AC1, AC3)
  - [x] Ran a real `astro build`; confirmed the actual hashed asset paths (`/_astro/BriefingPage.astro_astro_type_script_index_0_lang.<hash>.js`, `/_astro/loadBriefing.<hash>.css`) match the pattern-based `/_astro/` prefix check, not a hardcoded hash.
  - [x] Confirmed all 135 `/briefings/<lang>/<zone>/<period>.json` paths and all 136 HTML page paths classify as network-first, and `manifest.json`/`icon-192.png`/`icon-512.png` classify as cache-first.

- [x] **Task 4: Tests**
  - [x] Decision documented (see Dev Notes): `sw.js` cannot import anything (Astro copies `public/` byte-for-byte, unprocessed), so its pure logic (`classifyRequest`, `withTimeout`) is hand-mirrored into `site/src/islands/sw-logic.ts`, which exists solely for its own unit tests — the same "one owner conceptually, two hand-kept copies practically" pattern already established for `briefing.ts`/`period-switcher.ts`.
  - [x] 6 unit tests for `classifyRequest` covering every real path shape from Task 3, plus the pathname-only/query-string-and-origin-ignoring case, plus the unrecognized-extension passthrough case.
  - [x] 4 unit tests for `withTimeout` using `vi.useFakeTimers()` — resolves on early success, rejects on timeout, propagates an early rejection, and confirms the timer is cleared (no lingering fire) after early settlement.
  - [x] `no-js-readable.test.ts`: new "Service worker registration (Story 5.2)" describe block (own `beforeAll` build) — `dist/sw.js` exists and is byte-identical to `public/sw.js`; the registration call reaches both `/` and a `[lang]/[zone]/[period]` route; the `.catch(` guard is present.
  - [x] The network-first-vs-stale-while-revalidate distinction is NOT mechanically tested end-to-end (would require a real browser + real network timing) — explicitly documented as a manual-verification gap in Completion Notes, consistent with this codebase's established precedent (Story 5.1's own installability check).
  - [x] Full verification pass run (see Completion Notes): all 6 commands clean.

## Dev Notes

### Why HTML pages are "Briefing content" for AD-8's purposes, not a separate third category

AD-8's own rule text says "Briefing HTML and JSON use network-first" — explicitly naming HTML, not just the JSON API. This matters because a service worker's most common naive first draft treats "the page" and "the data" as different tiers (HTML cache-first for speed, JSON network-first for freshness) — that naive split would still guarantee a no-JS reader's first paint is stale, since their entire reading experience comes from the HTML alone. Treat both identically: network-first-with-timeout, cache as fallback only.

### Why a fixed 3000ms timeout, not a symbolic "short" value

The epics file's own `[ASSUMPTION]` tag invites tuning against real mobile conditions, which this implementation has no access to observe directly. 3000ms (the upper bound of the suggested 2–3s range) is chosen deliberately: AD-8's own stated worst-case failure is a *silent* stale read, not a slow load — a reader who waits an extra second on a poor connection before the fallback kicks in is a strictly better outcome than one who gets kicked to a stale cache prematurely on a connection that would have succeeded a moment later. Revisit with real telemetry if this product ever gains any (it currently has none, by design — no analytics, no tracking, per the PRD's own privacy stance).

### Why no `install`-time pre-cache

A hand-written service worker (no build integration generates it) cannot know Astro's per-build content hashes ahead of time without a second build step reading its own manifest — a real option, but disproportionate for 2 hashed files in a solo project. Cache-first is implemented as "cache on first successful fetch, serve from cache on every subsequent request" instead: the first request for any cache-first asset still hits the network once, then every later request (including a future page's request for the same still-referenced asset) is served from cache with zero network round-trip. This satisfies AC3's letter (hashed assets are served cache-first) without needing install-time knowledge of their filenames.

### Why `sw.js` cannot import `sw-logic.ts`, and how the mirror was verified correct

`site/public/` is copied to `dist/` byte-for-byte by Astro — nothing under it goes through the bundler, so `sw.js` cannot use an `import` statement (there is no module resolution happening for that directory at all, unlike `src/` islands). `sw-logic.ts` exists purely so `classifyRequest`/`withTimeout` have a unit-testable home; `sw.js` hand-mirrors both functions as plain JS. Verified the two copies are behaviorally identical by running the exact same test scenarios' expected inputs/outputs through both mentally against the AD-8 rule text (not by copying one file's output as the other's expected value) before considering Task 1/4 complete.

### Previous Story Intelligence

- Story 5.1 introduced `manifest.json`/icon files under `site/public/` with no service worker yet — this story is the first to actually register one. Story 5.1's Completion Notes flagged that the manifest's icons are currently solid-color placeholders (an unrelated, already-tracked gap) — irrelevant to this story's own scope but worth knowing they're not yet the "real" assets a maskable-icon or richer PWA experience would eventually want.
- Story 5.1's Blind Hunter review caught a test-isolation bug: a new describe block silently depended on a *different*, earlier block having already run `astro build` and left `dist/` populated. Applied the same discipline here — this story's own new build-output tests have their own explicit build step, not a borrowed one.
- Story 4.7/4.8's Blind Hunter reviews repeatedly caught bugs hiding behind tests that asserted the code's own (buggy) output as ground truth, rather than an independently-reasoned-through correct value. Applied the same skepticism to the timeout-race and classification unit tests here.
- Discovered mid-implementation (not anticipated in the original spec): Story 4.7's own "ships exactly two `<script>` tags on `/`" test needed updating to "exactly three," since this story's registration script is a genuinely new, always-present script. Its original tag-identification logic used `html.indexOf(tag)` to re-locate each script's body by searching for its own opening-tag text — silently broken once TWO of the three tags became byte-identical (`<script type="module">` with no distinguishing attribute), since `indexOf` always resolves to the first occurrence for both searches. Fixed by switching to `matchAll`, which yields each match's own real position instead of re-searching text. Worth remembering for any future story that adds a 4th inline script to this same page.

### Project Structure Notes

Files this story creates or modifies:
- `site/public/sw.js` (new)
- `site/src/islands/sw-register.ts` (new, or equivalent — decide per Task 2)
- `site/src/components/BriefingPage.astro` (modified) — new registration `<script>` tag
- New test file(s) for `sw.js`'s pure logic, plus `no-js-readable.test.ts` extensions for build-output/registration presence

No changes to `pipeline/`. No changes to `site/public/manifest.json` (Story 5.1's own file, unrelated to this story's scope beyond the classification logic knowing its path is cache-first).

### References

- [Source: epics.md#Story 5.2] — acceptance criteria origin (lines 766-788), including the `[ASSUMPTION: 2–3s]` tag
- [Source: ARCHITECTURE-SPINE.md#AD-8] — the network-first/cache-first split, the stale-while-revalidate prohibition, the "offline cache is a safety net, never the default source" framing
- [Source: ARCHITECTURE-SPINE.md#AD-9] — confirms cycle-identifier stamping and cache-name invalidation are Story 5.3's own scope, not this one's
- [Source: site/src/islands/period-switcher.ts#briefingJsonUrl] — confirms the exact `/briefings/<lang>/<zone>/<period>.json` URL pattern the client fetches
- [Source: site/scripts/copy-briefings-to-public.ts] — confirms 135 Briefing JSON files, each a few KB, copied verbatim to `dist/briefings/`
- [Source: _bmad-output/implementation-artifacts/5-1-make-the-application-installable.md] — the manifest/icon files this worker's cache-first branch must also cover; the "no existing SW registration" and "no PWA build integration" facts this story's Scope section relies on

## Dev Agent Record

### Context Reference

Story spec + epics.md#Story 5.2 + architecture spine AD-8/AD-9 (network-first/cache-first split, stale-while-revalidate prohibition, scope boundary with Story 5.3) + direct research into the real build output (hashed asset paths, Briefing JSON paths/sizes, existing script registration surface) + Story 5.1's own file list and review learnings.

### Debug Log

- Adding a 3rd always-present inline `<script>` tag (the SW registration, alongside the existing Period-switcher and, on `/`, language-detect scripts) broke Story 4.7's pre-existing "ships exactly two `<script>` tags on /" test in two ways: the length assertion (now 3, not 2) and, more subtly, its tag-body-matching logic (`html.indexOf(tag)`), which silently mis-paired two now-byte-identical `<script type="module">` tags with the same body since `indexOf` always finds the first occurrence for both lookups. Fixed by rewriting the tag-identification logic to use `matchAll`, which correctly tracks each match's own position instead of re-searching by text.

### Completion Notes

- Both remaining ACs from this story (AC1 network-first-with-timeout, AC3 cache-first for hashed assets) and AC4 (no stale-while-revalidate) are implemented in `site/public/sw.js`, with its pure classification/timeout logic hand-mirrored into `site/src/islands/sw-logic.ts` for unit testing (the same duplication pattern already established for `briefing.ts`/`period-switcher.ts` — `public/` files cannot import anything, so there is no way to share the module directly).
- AC2 (a returning reader sees the new cycle's Briefing, not the previous one) is satisfied by construction of AC1's own network-first behavior: as long as the network succeeds within 3 seconds, the response is always the current server state, never a stale cache read. Cache invalidation on publish (AD-9's cycle-identifier stamping) is explicitly Story 5.3's own scope and not touched here.
- **Known, explicitly-flagged gap:** the network-first-vs-stale-while-revalidate distinction (AC4) is proven by code inspection (the only cache write for Briefing content happens after a real, foreground, awaited network success — no code path exists that serves a cached response while concurrently kicking off a silent background revalidation) and by the unit-tested `withTimeout`/`classifyRequest` pure logic, but is NOT end-to-end tested against a real browser's actual request-interception behavior — that would require a real Service Worker environment with controllable network timing, which is not available in this implementation's environment. Consistent with Story 5.1's own precedent for the same class of gap (the manual browser installability check).
- Manually inspected `site/public/sw.js`'s full logic against AD-8's rule text line-by-line before considering Task 1 complete: confirmed no code path caches then immediately re-serves from cache in the same request (which would smell like SWR), confirmed the cache write for Briefing content is strictly post-network-success, and confirmed cache-first never touches the network on a hit.

### File List

- `site/public/sw.js` (new)
- `site/src/islands/sw-logic.ts` (new)
- `site/src/islands/__tests__/sw-logic.test.ts` (new)
- `site/src/islands/sw-register.ts` (new)
- `site/src/components/BriefingPage.astro` (modified)
- `site/e2e/no-js-readable.test.ts` (modified)

## Senior Developer Review (AI)

Single-layer adversarial review (Blind Hunter), per the standing cost-reduction decision. Directed to focus on `sw.js`'s exact control flow (the highest-risk file in the story — a bug here could silently serve stale news, the architecture spine's own named worst failure mode), the fidelity of the `sw.js`/`sw-logic.ts` mirror, and test quality.

**Outcome: Changes Requested → Fixed.**

### Action Items

- [x] **[Med] `networkFirst` never cached a network response that lost the timeout race but eventually succeeded.** The original implementation only wrote to the cache inside the branch that had directly `await`-ed the network response (the fast-success path); the timeout-fallback branch called `caches.match` but never attached a cache write to the original, still-pending `fetch()`. A reader on a slow-but-working connection (every visit exceeding 3s, but never actually failing) would never get a fresher cached fallback — the cache entry would remain whatever was written on the last FAST visit, potentially quite old. A later fully-offline visit would then serve that older Briefing via `caches.match`, even though the reader had already seen fresher content online in the meantime. Fixed by attaching the cache-write `.then()` directly to the real `fetch()` promise (not gated behind which branch of the timeout race wins), and reusing that same promise (rather than issuing a second, duplicate `fetch()`) as the final fallback when nothing is cached. Proven via a red→green regression test that reproduces the exact scenario (timeout fires, no cache entry yet, network eventually succeeds) and confirms the cache is updated once it does.
- [x] **[Low, not fixed] `cacheFirst` has no try/catch around its network fetch on a cache miss; a rejection propagates unhandled into `respondWith`.** Not reachable through this app's own actual usage (the only cache-first assets are the site's own hashed bundle/CSS/manifest/icons, always served successfully by the same origin) — flagged only as an asymmetry with `networkFirst`'s own error handling, deliberately left as-is rather than adding defensive handling for a scenario this codebase's own conventions treat as "can't actually happen here."
- [x] **[Low, not fixed] No `request.method === "GET"` guard before `cache.put` in either strategy.** The Cache API spec requires GET for `cache.put`; a non-GET request would throw. Not reachable — this app's only client fetch (`period-switcher.ts`'s `briefingJsonUrl` fetch) is always a plain GET, and page navigations are always GET. Left undefended per the same "don't validate for inputs that can't occur" principle.

### Post-Review Fixes

- `site/public/sw.js`: `networkFirst`'s cache write now attached to the real fetch's own `.then()`, independent of the timeout race's outcome; the timeout-fallback's final resort reuses that same promise instead of issuing a duplicate fetch.
- `site/src/islands/sw-logic.ts`: `networkFirst`/`cacheFirst` extracted as testable, dependency-injected functions (parameterized `fetch`/cache-storage implementations), mirroring `sw.js`'s fixed logic exactly.
- `site/src/islands/__tests__/sw-logic.test.ts`: added 7 new tests for `networkFirst`/`cacheFirst`, including the regression test for the fixed bug (verified red against the pre-fix logic, green against the fix).
- Re-ran full verification after the fix: `npx tsc --noEmit`/`npx astro check` → clean; `npx astro build` → 136 pages; `npx vitest run` → 160/160 passing (up from 153); `uv run pytest` → 315/315 passing; `bash scripts/check-boundary.sh` → clean.

## Change Log

- 2026-08-13: Story created via bmad-create-story. Researched the real `astro build` output (hashed asset filenames, 135 Briefing JSON paths, 136 HTML page paths, existing script-registration surface) before writing the spec, rather than assuming the shape of what this service worker needs to classify. Confirmed no existing service worker, no PWA build integration, and no existing registration call anywhere in the codebase — this is a fully hand-written `sw.js` from scratch. Scoped explicitly against AD-9/Story 5.3 (cycle-identifier cache versioning) and Story 5.4 (offline UI), which this story does not implement. Picked a concrete 3000ms network timeout (resolving the epic's own `[ASSUMPTION]` tag) with documented reasoning rather than leaving it symbolic.
- 2026-08-13: All 4 tasks implemented and verified (153 site tests, 315 pipeline tests, boundary check clean, 136-page build plus `sw.js` in `dist/`). Fixed a real pre-existing test bug discovered mid-implementation: Story 4.7's "ships exactly two script tags" test used `indexOf` to re-locate script bodies by tag text, which silently broke once 2 of the 3 now-present inline scripts became byte-identical. Status set to `review` ahead of the single-layer Blind Hunter adversarial review.
- 2026-08-13: Blind Hunter review found one real Medium-severity bug (a timed-out-but-eventually-successful network response was never cached, risking a stale offline fallback) and two deliberately-not-fixed Low-severity items (unreachable-in-practice defensive-coding gaps). Fixed the real bug via TDD, extracted `networkFirst`/`cacheFirst` into testable functions, re-verified the full suite (site: 160/160, pipeline: 315/315, boundary check clean), status set to `done`.
