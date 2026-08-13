---
baseline_commit: e43d835
---

# Story 5.1: Make the application installable

Status: done

## Story

As a daily reader,
I want 5 News on my home screen,
So that opening it is a gesture rather than a search.

## Scope, decided explicitly before this story was written

**This is the first story of Epic 5, and it is deliberately narrow: a web app manifest plus its two required assets (icons) and its `<link>` reference — nothing else.** Stories 5.2/5.3/5.4 own the service worker (AD-8/AD-9's network-first/cache-first caching logic, cycle-identifier stamping, offline fallback UI) entirely; this story does not touch `site/public/sw.js` at all, and does not register a service worker. A manifest and installability do not require a service worker to exist — Chromium-based browsers' install criteria check for a valid manifest with the required fields; a service worker is a *separate*, additional install signal some browsers also accept, and Epic 5's own story split already assigns it to later stories. Confirm this split holds if implementing in a browser that behaves differently than expected, but do not preemptively add service-worker registration here to "help" — that is explicitly out of scope and would duplicate Story 5.2/5.3's own work.

**No icon assets exist anywhere in this repo today.** Grepped the full `site/` tree: zero `.png`/`.ico`/icon files of any kind. `DESIGN.md` defines a full color-token palette (`primary: #1f4d3d`, `background: #faf9f6`, etc.) and a wordmark name ("Wire & Ledger" is the *design system's* name; the *product's* own wordmark, already rendered as plain text in the header, is "5 NEWS" — see `BriefingPage.astro`'s `.mark` element) but no icon artwork. This story must create the icon(s) itself — there is no existing asset to link to. Keep it simple and consistent with the site's own restrained, text-forward visual language (serif/mono type, no illustration, no photography anywhere else on the site) rather than inventing a new illustrative mark from nothing: a simple typographic icon (e.g. the numeral "5" or the initials, set on a solid `primary`-colored background) is more consistent with this product's existing visual identity than a novel pictorial logo would be.

**No deployment/hosting target is configured in this repository yet** (`.github/workflows/` has `collect.yml` and `ci.yml`, no deploy workflow) — "served over HTTPS" (AC1's premise) is an assumption about wherever this eventually deploys, not something this story configures. Do not add a deploy workflow or hosting configuration as part of this story; that is a distinct, unscoped concern.

**AC2's "opens in the reader's Output Language, identically to a browser visit" requires no new logic.** Story 4.7 already established that `/` is the unconditional French default (Story 4.1's no-JS Cold-load guarantee), with an opportunistic, JS-only, additive `language-detect.ts` redirect to the reader's browser-preferred language layered on top — and that the URL segment is the *only* persistence mechanism for a chosen Output Language (no cookie/localStorage exists). A PWA's `start_url` is opened exactly like any other browser navigation to that URL: the manifest's `start_url` should be `/`, and the existing redirect script (already present on every visit to `/`, browser or installed) already satisfies this AC with zero additional code. Do not add a second, PWA-specific language-detection mechanism.

**AC3 ("no notification permission requested, nothing sent") requires no new logic either — it is a negative assertion about something this codebase already doesn't do.** Confirm via a direct grep that no `Notification.requestPermission()`, `PushManager`, or service-worker push-subscription code exists anywhere in `site/`, and keep it that way. This AC is closed by the manifest itself never requesting `permissions` (the current W3C manifest spec has no such field for notifications — that's a runtime API, not a manifest declaration) and by continuing not to write any push/notification code.

## Acceptance Criteria

1. **Given** the site is served over HTTPS, **when** a supporting browser loads it, **then** a web application manifest is served with name, icons, theme colour, and standalone display mode (FR-20) **and** installation is offered without further configuration.
2. **Given** the installed application, **when** it is launched, **then** it opens the World / day Briefing in the reader's Output Language, identically to a browser visit (FR-1).
3. **Given** installation, **when** it completes, **then** no notification permission is requested and nothing is sent (PRD §9.2).

## Tasks / Subtasks

- [x] **Task 1: Create the manifest's icon assets** (AC1)
  - [x] Created `site/public/icon-192.png` and `site/public/icon-512.png` — solid `#1f4d3d` squares, no typographic mark (see Dev Notes for why this diverges from the originally-planned typographic icon).
  - [x] Produced via a small one-off Node script using only the built-in `zlib` module (no new dependency) to hand-construct valid PNG files byte-by-byte per the PNG spec — no image library (Pillow, sharp, an SVG rasterizer) was available in this environment, and adding one for 2 static icons was judged disproportionate.
  - [x] Verified independently via `file` and macOS's `sips` tool (not just trusting the generating script) — both confirm valid 192×192 and 512×512 8-bit RGB PNGs.

- [x] **Task 2: Author `site/public/manifest.json`** (AC1)
  - [x] `name`/`short_name`: both "5 News".
  - [x] `icons`: both PNGs, `sizes`/`type` set correctly.
  - [x] `theme_color: "#1f4d3d"`, `background_color: "#faf9f6"` (DESIGN.md's `primary`/`background` tokens).
  - [x] `display: "standalone"`.
  - [x] `start_url: "/"`.
  - [x] `id: "/"` set explicitly, per current manifest spec guidance for stable app identity across future manifest edits.

- [x] **Task 3: Link the manifest from every page** (AC1)
  - [x] Added `<link rel="manifest" href="/manifest.json" />` to `BriefingPage.astro`'s shared `<head>` — reaches all 136 pages.
  - [x] Added `<meta name="theme-color" content="#1f4d3d" />` alongside it.

- [x] **Task 4: Confirm no notification/push code exists, and add none** (AC3)
  - [x] Grepped the full `site/` tree for `Notification`/`requestPermission`/`PushManager`/`pushManager`/`showNotification` — zero matches, before and after this story's changes.

- [x] **Task 5: Tests**
  - [x] `no-js-readable.test.ts`: new "PWA installability (Story 5.1)" describe block — `manifest.json` presence/validity/required-fields, both icon PNGs present in `dist/` at their real, structurally-verified dimensions (read directly from each PNG's own IHDR chunk, not just "the file exists"), `<link rel="manifest">`/`<meta name="theme-color">` present on both `/` and a `[lang]/[zone]/[period]` route, and a negative regression test for notification/push references in the built output.
  - [x] Full verification pass run (see Completion Notes): all 6 commands clean.
  - [x] Manual browser installability check: NOT performed in this environment (no interactive browser session available to this implementation) — see Completion Notes for what was verified instead (structural confirmation that the manifest satisfies every documented Chromium install-criteria field) and what remains the user's own manual step.

## Dev Notes

### Why this story is deliberately narrow

Epic 5's own story split (5.1 manifest/installability, 5.2 caching strategy, 5.3 cache invalidation, 5.4 offline UX) exists because each is independently shippable and independently risky: a wrong caching strategy (5.2/5.3) could silently serve stale news, which is this product's single worst failure mode per AD-8's own stated rationale — that risk deserves its own focused story and review, not to be bundled with the comparatively low-risk manifest work. Resist the temptation to "get ahead" on the service worker here even though it would feel like natural momentum; a service worker written without 5.2/5.3's own AD-8/AD-9-mandated network-first/cache-first split and cycle-identifier stamping would need to be redone anyway, wasting the work.

### Why the icon is a solid color field, not the originally-planned typographic mark

The spec's own intent (a simple typographic mark, e.g. "5", on a solid `primary`-colored field) is the right visual direction — consistent with every other visual element on this site (per DESIGN.md's own Brand & Style section and direct inspection of `BriefingPage.astro`: no icons anywhere in the reading UI except the chevron (▾) and "·" separator, both simple Unicode glyphs, not custom artwork). However, no image-generation library (Pillow, sharp, an SVG rasterizer) was available in this implementation's environment, and adding one as a new dependency solely to render 2 static icons once was judged disproportionate for a solo project — the same proportionality judgment this codebase has applied repeatedly (Playwright deferral across Epic 4). The icons actually shipped are solid `#1f4d3d` squares with no text, produced by a small one-off script using only Node's built-in `zlib` to construct valid PNGs by hand. This satisfies AC1's structural requirement (a valid icon at both required sizes) but not the full visual intent. Revisit with an actual typographic/mark icon when either a lightweight rasterization path becomes available or this is done via a real design tool outside this implementation environment — flagged here explicitly so it isn't mistaken for a deliberate design choice.

### Previous Story Intelligence

- Story 4.7's `language-detect.ts` (`site/src/islands/language-detect.ts`) is the mechanism that makes AC2 free — read it before starting, to confirm it is genuinely still wired only into `index.astro`'s `extra-scripts` slot and still fires on every visit to `/`, installed or not (nothing about PWA installation changes how a `<script>` tag executes).
- Story 4.8's Blind Hunter review caught two real bugs from insufficiently-verified assumptions (a self-referential test asserting the code's own buggy output; a test that silently lost its ability to catch a regression after an Astro CSS-bundling threshold changed). Apply the same skepticism here: actually open the built manifest/icons and verify them structurally (valid JSON, real image files of the stated dimensions), not just "the file exists."
- Astro's own asset-bundling behavior has repeatedly surprised this codebase (JS inlining thresholds in Stories 4.5/4.7, CSS inlining thresholds in Story 4.8) — confirm `site/public/manifest.json`, `icon-192.png`, and `icon-512.png` (all under `public/`, not `src/`) are copied to `dist/` byte-for-byte, unprocessed, which is Astro's documented behavior for the `public/` directory specifically (unlike `src/`, which the bundler transforms) — verify this behavior directly against the real build output rather than assuming it.

### Project Structure Notes

Files this story creates or modifies:
- `site/public/manifest.json` (new)
- `site/public/icon-192.png` (new)
- `site/public/icon-512.png` (new)
- `site/src/components/BriefingPage.astro` (modified) — `<link rel="manifest">` and `<meta name="theme-color">` added to `<head>`
- A new test file or an extension of `site/e2e/no-js-readable.test.ts` (new/modified) — manifest/icon/link/no-notification tests

No changes to `site/public/sw.js` (does not exist yet — Story 5.2/5.3's job) and no changes to any file under `pipeline/`.

### References

- [Source: epics.md#Story 5.1] — acceptance criteria origin (lines 745-764)
- [Source: ARCHITECTURE-SPINE.md#AD-8, AD-9] — confirms the service worker's caching/invalidation logic is explicitly out of this story's scope (bound to later stories); confirms `FR-20 installability` traces to `site/public/manifest.json` specifically, bound only to AD-8 (not AD-9, which is service-worker-specific)
- [Source: ux-designs/ux-5-news-2026-08-12/DESIGN.md#colors] — `primary` (`#1f4d3d`) and `background` (`#faf9f6`) tokens, reused for `theme_color`/`background_color`
- [Source: ux-designs/ux-5-news-2026-08-12/EXPERIENCE.md] — confirms no custom install-prompt UI is specced (line 14: "No native app shell in v1 beyond Epic 5's PWA installability... same single page")
- [Source: _bmad-output/implementation-artifacts/4-7-choose-the-reading-language.md] — `language-detect.ts`'s existing behavior, which this story relies on for AC2 without modification

## Dev Agent Record

### Context Reference

Story spec + epics.md#Story 5.1 + architecture spine AD-8/AD-9 (confirming the service-worker/manifest scope split) + DESIGN.md's color tokens + direct inspection confirming zero existing icon assets and zero existing notification/push code + Story 4.7's `language-detect.ts` (confirming AC2 needs no new code).

### Debug Log

- No Pillow/sharp/SVG-rasterization tooling was available in this implementation's environment (confirmed via direct probing: `python3 -c "import PIL"` fails, no `PIL` in the pipeline's `uv` environment either, no `rsvg-convert`/`inkscape`/`magick`/`convert` on PATH). Rather than adding a new dependency for 2 static icons, wrote a small one-off Node script using only the built-in `zlib` module to hand-construct valid PNG files (signature + IHDR + IDAT + IEND chunks, each with its own CRC-32, per the PNG spec) — solid `#1f4d3d` squares, no text (no font-rendering capability available this way). See Dev Notes for the resulting visual-intent gap versus the originally-planned typographic mark.

### Completion Notes

- AC1 (manifest with name/icons/theme colour/standalone display, installation offered without further configuration) and AC3 (no notification permission requested) are both structurally satisfied: the manifest contains every field Chromium's documented install criteria check for, both icon files are valid, correctly-sized, real PNGs (verified independently via `file`/`sips`, not just existence), and a full-tree grep confirms zero notification/push code exists anywhere in `site/`.
- AC2 (opens the World/day Briefing in the reader's Output Language identically to a browser visit) required no new code — `start_url: "/"` reuses Story 4.7's already-existing `language-detect.ts` opportunistic redirect, which fires identically whether the page was opened via a normal browser navigation or an installed PWA's launch icon (nothing about installation changes how a `<script>` tag on `/` executes).
- **Known, explicitly-flagged gap, not a silent omission:** the 2 icon files are solid-color squares, not the typographic mark ("5" or similar) the story's own Scope/Dev Notes describe as the intended visual direction. This is a direct consequence of no image-generation tooling being available in this implementation's environment (see Debug Log) — installing a new dependency for 2 one-off static images was judged disproportionate. The icons are structurally valid and satisfy AC1's letter (a real icon exists at both required sizes), but not the originally-described visual intent. Flagged explicitly here and in Dev Notes so a future pass (with access to a design tool or a lightweight rasterization path) can replace them without this being mistaken for a deliberate, already-considered design choice.
- **Known, explicitly-flagged gap:** the manual real-browser installability check (Task 5's last item) was NOT performed — no interactive browser session is available to this implementation. What WAS verified instead: the manifest's fields structurally satisfy every documented Chromium install-criteria requirement (checked directly against the real built `manifest.json`, not just the source file), and both icons are confirmed-valid real PNGs at the dist/ paths the manifest references. The user's own remaining step: open the built site in a real Chromium-based browser and confirm an install prompt/icon actually appears, per the story's own task description.

### File List

- `site/public/manifest.json` (new)
- `site/public/icon-192.png` (new)
- `site/public/icon-512.png` (new)
- `site/src/components/BriefingPage.astro` (modified)
- `site/e2e/no-js-readable.test.ts` (modified)

## Senior Developer Review (AI)

Single-layer adversarial review (Blind Hunter), per the standing cost-reduction decision. Directed to focus on manifest correctness against real Chromium install-criteria requirements, icon file validity, build-output reachability, and test quality — explicitly told not to re-flag the two gaps this story's own Completion Notes already disclosed (solid-color icons, no manual browser check).

**Outcome: Changes Requested → Fixed.**

### Action Items

- [x] **[Low/Med] The new "PWA installability" test block had no build step of its own, relying on a preceding, unrelated describe block having left `dist/` populated.** Confirmed concretely: running the block in isolation against a clean `dist/` made all 4 tests fail with `ENOENT`. It passed in the full suite only because vitest's default file-declaration-order execution happened to run an earlier block's build first — fragile, since a future reorder or insertion could silently break it (either hard failures, or worse, checking stale content without any test noticing). Every other build-dependent describe block in this file has its own explicit `beforeAll` build step; this was the one exception. Fixed by adding the same `beforeAll(() => execFileSync("npx", ["astro", "build"], ...), 30000)` pattern already used elsewhere in the file. Verified fixed by re-running the block in isolation against a freshly-wiped `dist/` — passes independently now.
- [x] **[Low, deferred, not fixed now] No icon carries `purpose: "maskable"`.** Not a Chromium install-criteria blocker (a quality recommendation, not a hard gate) and a non-issue visually today since the icons are solid-color squares with no edge content that could be clipped badly by a maskable mask. Deliberately not fixed in this pass — worth adding only once the icons carry their originally-intended typographic mark (this story's own already-disclosed gap), since a maskable-safe-zone calculation is meaningless against a flat color field.

### Post-Review Fixes

- `site/e2e/no-js-readable.test.ts`: added a `beforeAll` build step to the "PWA installability (Story 5.1)" describe block, matching every other build-dependent block in the file.
- Re-ran full verification after the fix: `npx tsc --noEmit`/`npx astro check` → clean; `npx astro build` → 136 pages plus manifest/icons; `npx vitest run` → 138/138 passing (including the isolation-fixed block re-verified standalone against a freshly-wiped `dist/`); `uv run pytest` → 315/315 passing; `bash scripts/check-boundary.sh` → clean.

## Change Log

- 2026-08-13: Story created via bmad-create-story. Confirmed via direct inspection that no icon assets, no manifest, and no notification/push code exist anywhere in the repo today, and that the architecture spine's own AD-8/AD-9 split already assigns the service worker (caching strategy, cycle-identifier stamping) to Stories 5.2/5.3, not this one — scoped this story narrowly to the manifest, its 2 required icon sizes, and the `<link>`/`<meta>` wiring, explicitly deferring the service worker. Confirmed AC2 requires no new code, since Story 4.7's `language-detect.ts` already satisfies it via the existing `/` redirect behavior.
- 2026-08-13: All 5 tasks implemented and verified (138 site tests, 315 pipeline tests, boundary check clean, 136-page build plus manifest/icons in `dist/`). Icons are solid-color squares rather than the originally-planned typographic mark, since no image-generation tooling was available in this environment — flagged explicitly in Completion Notes/Dev Notes, not silently substituted. The manual real-browser installability check was not performed for the same environment-access reason; a structural equivalent (verifying every manifest field against Chromium's documented install criteria) was done instead. Status set to `review` ahead of the single-layer Blind Hunter adversarial review.
- 2026-08-13: Blind Hunter review found one real issue (a test-isolation fragility in the new PWA test block, masked by describe-block execution order) and noted one deliberately-deferred low-severity item (missing maskable icon purpose, meaningless against the current placeholder icons). Fixed the isolation issue via TDD-verified re-run, re-verified the full suite (site: 138/138, pipeline: 315/315, boundary check clean), status set to `done`.
