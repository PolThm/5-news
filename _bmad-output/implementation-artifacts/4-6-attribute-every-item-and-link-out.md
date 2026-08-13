---
baseline_commit: 52f265c
---

# Story 4.6: Attribute every item and link out

Status: done

## Story

As a publisher whose reporting is summarized,
I want visible attribution and a prominent link to my article,
So that the Summary sends readers to the original rather than replacing it.

## Scope, decided explicitly before this story was written

**AC1 is already fully implemented — this story verifies it with tests, it does not add new markup.** Confirmed by direct inspection of `BriefingPage.astro`: the `.attribution` span (outlet name as plain text + solid-underlined `<a>`) is a sibling of the Consensus chip's `<button>`/`.source-list`, not nested inside either, rendered unconditionally in the initial server-rendered HTML with no client-JS gate of any kind — structurally independent of the chip's `aria-expanded`/`js-collapsed` state by construction. The CSS already applies a plain `text-decoration: underline` (solid, no `-style` modifier), contrasting with the mad-libs words' explicit `underline dotted` — the exact distinction DESIGN.md calls for. No test currently locks in this structural independence, so this story's real work is the verification test, not new code — unless that verification surfaces a real gap.

**One small, explicitly-decided addition: the outbound link opens in a new tab with `rel="noopener noreferrer"`.** Neither `EXPERIENCE.md`/`DESIGN.md`/the AC's own wording requires this, but it was raised and decided directly: `target="_blank"` (a reader following an outbound link shouldn't lose the Briefing page) with `rel="noopener noreferrer"` (standard security practice for a `target="_blank"` link to an untrusted external origin — prevents the opened page from accessing `window.opener`). This is the one piece of genuinely new markup this story adds.

**AC2 ("no synthesized statement is attributed to a named outlet") is a pipeline prompt-engineering concern, already well-addressed, but unverified — this story adds the missing verification, it does not invent new enforcement.** `pipeline/adapters/claude.py`'s `_NO_FABRICATION_INSTRUCTION` already contains wording matching this AC almost verbatim: *"Never attribute a synthesized statement to a named outlet -- if you are not directly quoting an outlet, do not say '\<outlet\> reports that...'."* This instruction is injected into every summarization prompt unconditionally via `_prompt_for`. However, zero code anywhere (confirmed via grep across `pipeline/`) tests that this instruction is actually present in every generated prompt, or exercises its effect. This story's pipeline-side task is exactly that: a test asserting `_NO_FABRICATION_INSTRUCTION`'s exact text is present in `_prompt_for`'s output for a representative case — proving the mechanism this AC depends on is wired in, not proving the model obeys it (an LLM's actual compliance with a prompt instruction is not something a unit test can verify; that would require output-inspection/eval tooling far beyond this story's scope, and is explicitly not what this story adds).

**Do not add a runtime/heuristic check scanning `cluster.summary` text for outlet-name-plus-reporting-verb patterns.** This was considered and explicitly rejected as out of scope: such a check would be a new, nontrivial piece of content-moderation logic (false positives on legitimate quoted attribution, false negatives on paraphrased fabrication) that no spec asks for and that belongs to a dedicated future story if this ever becomes a real, observed problem — not something to improvise here as a defensive measure.

## Acceptance Criteria

1. **Given** a Briefing item, **when** it renders, **then** the outlet name is visible as plain text immediately followed by a solid-underlined outbound link to an original Article, present on initial render — not behind a menu, hover state, or the Consensus chip's expansion (FR-14, UX-DR9). The outbound link opens in a new tab (`target="_blank"`, `rel="noopener noreferrer"`) — a small, explicitly-decided addition beyond the AC's literal wording (see Scope).

2. **Given** a Summary, **when** it is read, **then** no synthesized statement is attributed to a named outlet — enforced pipeline-side by `_NO_FABRICATION_INSTRUCTION`'s existing prompt wording (already present, not added by this story), verified by a new test asserting that instruction is actually included in every generated summarization prompt. This AC does not, and cannot, verify the model's actual compliance — only that the mechanism it depends on is correctly wired in (see Scope for why runtime content-scanning is explicitly out of scope).

## Tasks / Subtasks

- [x] **Task 1: Add `target="_blank"`/`rel="noopener noreferrer"` to the outbound link** (AC1)
  - [x] Added `target="_blank" rel="noopener noreferrer"` to `BriefingPage.astro`'s `<a href={cluster.outbound_url}>`.
  - [x] Mirrored identically in `period-switcher.ts`'s `renderItemListHtml`.
  - [x] Confirmed via build inspection in both the server-rendered `dist/index.html` and the compiled island JS bundle (`dist/_astro/BriefingPage.astro_astro_type_script_index_0_lang.*.js`) — both carry the attribute correctly. Fixed one pre-existing test (`period-switcher.test.ts`) whose exact-match assertion needed updating for the new attributes.

- [x] **Task 2: Add site-side tests proving AC1's structural guarantee** (AC1)
  - [x] Added a test asserting the outbound link opens in a new tab with `rel="noopener noreferrer"`.
  - [x] Added a test asserting the attribution `<a>`'s CSS uses a plain (solid) `text-decoration: underline`, distinct from the mad-libs words' `underline dotted` — a negative lookahead specifically excludes the dotted variant, so this test would fail if a future change accidentally applied the wrong underline style.
  - [x] Added a test asserting the attribution span's structural position: extracted the ceasefire cluster's full item block (7-member source list, the longest) and confirmed the attribution span's opening tag index is strictly after the source list's closing `</ul></div>` — proving it's a sibling, never nested inside the chip or source list, for the item with the most content to potentially confuse a naive check.
  - [x] Confirmed (via the same fixture's trade-agreement cluster, which has no `outbound_source`/`outbound_url`) that the existing `hasValidAttribution` degrade path already correctly renders no attribution element at all for that case — already covered by Story 4.1's own prior tests, re-confirmed here as still true.

- [x] **Task 3: Verify `_NO_FABRICATION_INSTRUCTION`'s presence in every generated prompt** (AC2)
  - [x] Added `test_the_prompt_includes_the_no_fabrication_instruction_for_every_language` to `tests/test_claude_adapter.py`, asserting `_prompt_for`'s output contains `_NO_FABRICATION_INSTRUCTION`'s exact text for all 3 supported languages.
  - [x] Added a second test, `test_the_no_fabrication_instruction_explicitly_names_the_outlet_attribution_case`, guarding the instruction's own wording against future drift away from this AC's specific scenario.
  - [x] No new prompt wording added — confirmed `_NO_FABRICATION_INSTRUCTION` already exists verbatim as cited in Scope.
  - [x] Stated explicitly in the tests' own docstrings and Dev Notes: this proves the instruction reaches every prompt, not that the model obeys it.
  - **Unplanned but necessary fix, discovered while running the full pipeline test suite for the first time in this story** (previous stories only ran the site's own test suite and manually inspected `scripts/check-boundary.sh`'s shell output, never the Python test suite that validates that script): `tests/test_boundary_check.py`'s `test_clean_tree_passes` and `test_a_clean_site_with_only_briefings_json_references_passes` had been silently failing since Story 4.2 — the "pre-existing false positive" documented (but never fixed) in Stories 4.2 through 4.5's Debug Logs is a real regression in the project's own test suite, not just a manual annoyance. Fixed `scripts/check-boundary.sh`'s check #3 to exclude comment-only lines before matching `pipeline/`, and renamed one test description string in `briefing.test.ts` that legitimately mentioned "pipeline/config" in prose (not a comment, so the comment-exclusion fix alone didn't cover it). All 12 tests in `test_boundary_check.py`, all 312 pipeline tests, and all 81 site tests now pass — the full test suite is genuinely clean for the first time since Story 4.2.

## Dev Notes

### Why AC1 needed almost no new code, but did need a new test

Every structural element AC1 asks for — plain-text outlet name, solid underline, unconditional initial render, independence from the Consensus chip's own disclosure state — was already correctly implemented as a side effect of how Story 4.1 originally wrote the `.attribution` markup and how Story 4.5 later added the chip as a structural *sibling*, not a wrapper, of that same markup. This is a case where "verify, don't reimplement" (the same framing Story 4.4 used for AC1/AC3) applies again — but unlike Story 4.4, where the underlying property held with zero risk of drift, here a *future* story could accidentally nest attribution inside a chip-related conditional while refactoring `BriefingPage.astro`'s item markup, with nothing today to catch that regression. The new structural-position test this story adds is what actually protects the guarantee going forward, not the (already-correct) markup itself.

### Why AC2's verification test only proves the prompt contains the instruction, not that the model obeys it

This mirrors Story 4.4's own precedent exactly (the ~260-character Summary target, which had zero pipeline enforcement at all) but is one step further along: here, real prompt-side enforcement *does* exist (`_NO_FABRICATION_INSTRUCTION`), it's just unverified that it's actually being sent. A unit test asserting a string is present in a prompt is a meaningfully different, much weaker claim than "the AI never fabricates an attributed statement" — state this distinction explicitly rather than letting a passing test imply a stronger guarantee than it actually proves. If a future story ever wants stronger enforcement (e.g., an eval harness sampling real outputs, or a runtime heuristic check), that is new scope for that story, not something this one should quietly half-attempt.

### Why a runtime content-scan of `cluster.summary` was considered and rejected

The one theoretically "site-side" lever available for AC2 — scanning the generated Summary text for an outlet name adjacent to reporting-verb phrasing (e.g., "Reuters affirme que...") — was deliberately not built. It would require nontrivial pattern-matching prone to both false positives (a summary that legitimately, correctly quotes an outlet, which is allowed) and false negatives (paraphrased fabrication with no literal outlet-name-plus-verb pattern), and no spec anywhere asks for this. If fabricated attribution becomes a real, observed problem in production output, that is grounds for a dedicated future story with its own considered design — not a defensive addition improvised here.

### Previous Story Intelligence

- Story 4.5's Blind Hunter review caught a real state-desync bug in `attachChips()` and a documentation/test-coverage gap (a claimed-tested combination that wasn't actually tested) — this story's own Task 2 explicitly exists to avoid the second failure mode: rather than assert in prose that AC1 already holds, add the test that actually proves it.
- Story 4.2/4.3/4.4/4.5 all deliberately avoided introducing Playwright/jsdom. This story has no new client-side interactivity at all beyond the one-line `target`/`rel` attribute addition (mirrored in `period-switcher.ts`'s existing render function) — no Playwright decision to make here, it simply doesn't apply.
- Single-layer adversarial review (Blind Hunter only) remains the process for this story, per the user's standing cost-reduction decision.

### Project Structure Notes

Files this story creates or modifies:
- `site/src/components/BriefingPage.astro` (modified) — `target="_blank" rel="noopener noreferrer"` added to the attribution link
- `site/src/islands/period-switcher.ts` (modified) — same attribute addition mirrored in `renderItemListHtml`
- `site/e2e/no-js-readable.test.ts` (modified) — new AC1 structural/attribute tests
- `pipeline/tests/` (or wherever `claude.py`'s existing tests live — check before creating a new file) (modified or new) — `_NO_FABRICATION_INSTRUCTION` presence test

### References

- [Source: epics.md#Story 4.6] — acceptance criteria origin (lines 679-693), UX-DR9 definition (line 86)
- [Source: ux-designs/ux-5-news-2026-08-12/EXPERIENCE.md#Component Patterns, Interaction Primitives, Accessibility Floor] — attribution's exact behavior/placement (line 60), hover-absence requirement (line 85), focus-order position (line 86)
- [Source: ux-designs/ux-5-news-2026-08-12/DESIGN.md#Components, Colors] — attribution link's exact visual spec (line 173), the dotted-vs-solid underline distinction from mad-libs words (line 170)
- [Source: site/src/components/BriefingPage.astro] — the already-correct `.attribution` markup and CSS this story verifies, not rewrites
- [Source: pipeline/adapters/claude.py#_NO_FABRICATION_INSTRUCTION, _prompt_for] — the existing prompt-side mechanism this story's Task 3 verifies is wired in
- [Source: pipeline/stages/summarize.py] — confirms zero post-generation content validation exists today, framing why Task 3's test is a presence-check, not a compliance-check
- [Source: _bmad-output/implementation-artifacts/4-4-show-a-variable-number-of-items-and-end-the-page.md] — the precedent for treating an unenforced UX-documented target as a documented pipeline gap rather than a site-side workaround

## Dev Agent Record

### Context Reference

Story spec + epics.md#Story 4.6 + UX EXPERIENCE.md/DESIGN.md (attribution spec) + direct inspection of BriefingPage.astro (confirming AC1 already holds) + pipeline source (confirming AC2's existing prompt instruction and its verification gap).

### Debug Log

- Discovered while running the pipeline's Python test suite for the first time in this multi-story engagement (previous stories only checked `scripts/check-boundary.sh`'s shell exit code manually, never the `tests/test_boundary_check.py` suite that validates it against a real sandboxed copy of the repo): the "pre-existing false positive" documented but left unfixed in Stories 4.2 through 4.5's Debug Logs was a real, silent regression in the project's own test suite (`test_clean_tree_passes`, `test_a_clean_site_with_only_briefings_json_references_passes` both failing) — not merely a manual annoyance, as it had been characterized every time. Raised this explicitly rather than continuing to defer it, given the "document, don't fix" precedent no longer applied once a real test failure was confirmed; user chose to fix now. Root cause: check #3's bare `grep 'pipeline/'` substring match fired on comment prose explaining the boundary (this codebase's own comments reference "pipeline/" extensively to explain AD-2), not just real code references. Fixed by excluding comment-only lines before matching, plus renaming one test description string that legitimately mentioned "pipeline/config" in prose (not a comment, so needed its own fix). All 12 `test_boundary_check.py` tests, all 312 pipeline tests, and all 81 site tests pass — first fully clean full-suite run since Story 4.2.

### Completion Notes

- All 3 tasks complete, plus the unplanned `check-boundary.sh` fix. Full verification: `npx tsc --noEmit` (0 errors), `npx astro check` (0 errors/warnings), `npx astro build` (46 pages), `npx vitest run` (81/81 passing), `bash scripts/check-boundary.sh` (passes cleanly for the first time since Story 4.2), `uv run pytest` (312/312 pipeline tests passing).
- AC1 required no new rendering logic — only the `target`/`rel` addition and the tests that lock in what was already correct. AC2's real work was entirely verification (a presence-check test), explicitly not new prompt content or a runtime content-scan (both considered, both rejected per Scope).
- The `check-boundary.sh` fix, while outside this story's official AC scope, was judged necessary once discovered to be a real test-suite regression rather than a cosmetic annoyance — fixed with the user's explicit sign-off rather than silently expanding scope.

### File List

- `site/src/components/BriefingPage.astro` (modified) — `target="_blank" rel="noopener noreferrer"` added to the attribution link
- `site/src/islands/period-switcher.ts` (modified) — same attribute addition mirrored
- `site/src/islands/__tests__/period-switcher.test.ts` (modified) — updated one pre-existing exact-match assertion for the new attributes
- `site/e2e/no-js-readable.test.ts` (modified) — new AC1 tests (target/rel, solid underline, structural sibling position)
- `site/src/lib/__tests__/briefing.test.ts` (modified) — renamed one test description to avoid a `check-boundary.sh` false positive
- `tests/test_claude_adapter.py` (modified) — 2 new tests verifying `_NO_FABRICATION_INSTRUCTION`'s presence and wording
- `scripts/check-boundary.sh` (modified) — fixed check #3's comment-vs-code false positive (unplanned, see Debug Log); re-fixed after Blind Hunter found 2 real gaps in the first fix
- `tests/test_boundary_check.py` (modified) — 3 new regression tests covering the Blind Hunter-caught gaps and the original comment-prose exclusion

## Senior Developer Review (AI)

Single-layer adversarial review (Blind Hunter), per the standing cost-reduction decision. This review's own scope necessarily extended to the unplanned `check-boundary.sh` fix, since that fix touched a security/architecture-boundary-enforcing mechanism.

**Outcome: Changes Requested → Fixed.**

### Action Items

- [x] **[High] The `check-boundary.sh` fix's whole-line comment exclusion let a real violation through undetected.** The fix's first version excluded any line whose trimmed content started with `//` or `*` before matching `pipeline/`. Two real gaps: (1) a violation on the SAME line as a trailing comment (e.g. `import x from "pipeline/y"; // comment`) was incorrectly excluded, since the exclusion is whole-line, not comment-portion-only; (2) a violation on a continuation line that happens to start with a multiplication operator (`x\n  * fetchWeight("pipeline/secret")`) was indistinguishable from a JSDoc continuation line by a bare `^\s*\*` heuristic, and was silently let through. Confirmed via direct adversarial construction of both cases against the flagged code. Fixed by switching from whole-line exclusion to actual comment-*content* stripping (`//...` to end-of-line via `sed`; `/* ... */` blocks via `perl`, preserving line counts by replacing block-comment content with just its own embedded newlines) before matching — a real violation now survives even next to a stripped same-line comment, and a non-comment line is never touched regardless of its leading character. Added 3 new regression tests to `tests/test_boundary_check.py` covering both adversarial cases plus the original comment-prose exclusion, none of which existed before this review.
- [x] **[Low] The "solid underline, distinct from dotted" test passed for the wrong reason.** Its negative lookahead `(?!\s+dotted)` doesn't actually reach past the real compiled CSS shorthand's intervening `2px` token (`text-decoration:underline 2px dotted #8fc2ac`), so the test was saved entirely by the outer `.attribution` selector prefix excluding the `.word` rule by name, not by the dotted-detection logic its own comment claimed. Fixed by asserting the property's value is the bare `underline` keyword bounded by `;`/`}` (nothing else following), plus an added assertion confirming the mad-libs word's own rule is NOT bare `underline` — so this test would now actually fail if attribution ever regressed to share the word's dotted styling.

### Post-Review Fixes

- `scripts/check-boundary.sh`: replaced whole-line comment exclusion with comment-content stripping (line-preserving), fixing both adversarial gaps.
- `tests/test_boundary_check.py`: added `test_ignores_prose_in_comments_mentioning_pipeline`, `test_catches_a_violation_on_a_line_starting_with_a_multiplication_operator`, `test_catches_a_violation_that_trails_a_same_line_comment`.
- `site/e2e/no-js-readable.test.ts`: fixed the solid-underline test's regex to check the actual distinguishing property, not a lookahead that never reached its target.
- Re-ran full verification after both fixes: `bash scripts/check-boundary.sh` → clean; `uv run pytest` → 315/315 passing (up from 312); `npx vitest run` → 81/81 passing.

## Change Log

- 2026-08-13: Story created via bmad-create-story. Confirmed via direct source inspection that AC1's structural guarantee (attribution independent of the Consensus chip's expansion) already holds, with no new markup needed beyond a small, explicitly-decided `target`/`rel` addition. Confirmed AC2's prompt-side mechanism (`_NO_FABRICATION_INSTRUCTION`) already exists and already matches the AC's exact scenario, but is unverified — scoped this story's pipeline task as closing that verification gap, explicitly not as adding new enforcement or a runtime content-scan (considered and rejected).
- 2026-08-13: All 3 tasks implemented and verified. Discovered and fixed (with explicit user sign-off) a real, multi-story-old regression in `scripts/check-boundary.sh` that had been silently failing the pipeline's own test suite since Story 4.2. Status set to `review` ahead of the single-layer Blind Hunter adversarial review.
- 2026-08-13: Blind Hunter review found two real bugs, both introduced by this story's own unplanned boundary-check fix: a high-severity gap letting real violations through undetected in two adversarial cases, and a low-severity test that passed for the wrong reason. Fixed both via TDD, added regression tests, re-verified the full suite (site, pipeline, and boundary check all clean), status set to `done`.
