---
baseline_commit: 1845aae
---

# Story 3.6: Keep generation cost independent of readership

Status: done

## Story

As the developer,
I want AI cost bounded by the Briefing matrix rather than by traffic,
So that the product cannot become expensive by becoming popular.

## Scope, decided explicitly before this story was written

**All three ACs are already true by construction, engineered by Stories 3.1, 3.4, and 3.5 — nothing this story does makes any of them true for the first time.** This story's entire job is to make each claim explicit and regression-tested, not to build a new mechanism:

- **AC1** (Batch API) was built in Story 3.1 and split into submit/collect in Story 3.4. `pipeline/adapters/claude.py`'s `submit_batch`/`collect_batch` already call `client.messages.batches.create`/`.retrieve`/`.results` exclusively — there is no `client.messages.create` call site anywhere in this codebase (confirmed by grep before this story was scoped).
- **AC2** (no AI/embedding/ingestion call in the reader's path) is *vacuously* true today: `site/` (Story 1.1's Astro scaffold, `output: "static"`, no server) already carries explicit AD-1 comments in `astro.config.mjs` and `index.astro`, and Epic 4 (the only place a reader-facing route could exist) is entirely `backlog` — there is no reader request path with any logic in it yet, let alone a network call. `scripts/check-boundary.sh` already enforces the adjacent invariant (`site/` never imports/path-references `pipeline/`) in CI.
- **AC3** (cost scales with Briefings, not traffic) was explicitly engineered *one story early* by Story 3.5's own fan-out decision: summarize submits exactly 3 batches per cycle (one per Output Language), against a deduplicated Cluster union, regardless of how many of the 15 Zones × 3 Periods exist or how many readers request a Briefing. Story 3.5's own spec text says so outright ("directly serving Story 3.6's 'cost independent of readership/Zone-count' goal one story early").

**User explicitly decided, before this story was written: build regression tests that prove each claim, not a new cost-measurement mechanism.** No token/dollar tracking exists anywhere in this pipeline today (only `MAX_TOKENS = 512`, a request-shaping constant, not a usage-measurement one), and building one would be new observability infrastructure the architecture spine never asked for, exercised against a pipeline that has never yet run a real production cycle to validate against. If real cost data becomes actionable later (e.g. after the Build Order's inspection window produces real cycles), that is a future, separately-scoped story — not this one.

## Acceptance Criteria

1. **Summarize requests are submitted through the Batch API, never the synchronous Messages API.** Given a generation cycle, when summarization runs, then every Claude call this pipeline makes goes through `client.messages.batches.create`/`.retrieve`/`.results` — verified by a repository-wide, structural assertion that no call site anywhere in `pipeline/` invokes `client.messages.create` (the synchronous endpoint), not merely by the existing per-function Batch-API-shape tests.

2. **The number of summarize batches submitted per cycle is fixed at 3 (one per Output Language) regardless of how many Zones, Periods, or Clusters exist.** Given a cycle with an arbitrarily larger or smaller Cluster union (varying the number of qualifying Clusters, Zones considered, or Periods), when `run_cycle` submits, then exactly one `submit_summarize_fn` call happens per `OutputLanguage` — never one per Zone, Period, or combination — proven by a test that varies cluster/Zone volume and asserts the submission count stays at 3.

3. **No reader-facing code path in this repository makes an AI, embedding, or ingestion call.** Given the current state of `site/` (Epic 4 not yet built), when its source is inspected, then no file under `site/` references any AI/embedding/ingestion adapter, network client, or API key — verified by a structural test (extending `scripts/check-boundary.sh`'s existing import/path-reference check, or a parallel assertion) that fails if `site/` ever imports from `pipeline.adapters` or references an AI/embedding provider by name. This test is a tripwire for Epic 4, not a claim that Epic 4's future code will never need such a check again — it exists so a future story cannot silently violate AD-1 without a test catching it.

## Tasks / Subtasks

- [x] **Task 1: Prove AC1 structurally, not just per-function** (AC1)
  - [x] New `tests/test_batch_api_boundary.py` — an AST-based check (not a bare grep, which would also match the correct `.messages.batches.create(...)` call) that walks every `.py` file under `pipeline/` looking for a call shaped exactly `<expr>.messages.create(...)` with no `.batches` in the chain, asserting zero matches. Proved the detector itself works via a planted-violation test (`test_the_detector_actually_catches_a_planted_synchronous_call`) and a false-positive regression guard (`test_the_detector_does_not_flag_the_real_batch_api_call`), mirroring `test_boundary_check.py`'s existing plant-and-verify discipline.
  - [x] Confirmed `pipeline/adapters/claude.py`'s docstring already states this design decision (from Story 3.1/3.4) — no documentation change needed, only the missing regression test.

- [x] **Task 2: Prove AC2/AC3's fixed-cost claim with a varying-volume test** (AC2)
  - [x] `tests/test_cycle.py::test_summarize_submission_count_stays_fixed_regardless_of_cluster_volume` — runs `run_cycle` twice (1 qualifying Cluster vs. 50), counting `submit_summarize_fn` calls via an injected counting stub, and asserts exactly 3 calls in both runs. Proves the submission count is `len(OUTPUT_LANGUAGES)`, never a function of Cluster volume.
  - [x] No additional dedup-union test added — `briefing_matrix.py`'s own `dedupe_union` tests from Story 3.5 already cover the no-duplicate-summarization claim; no genuine end-to-end gap was found that would justify duplicating that coverage here.

- [x] **Task 3: Add the Epic-4 tripwire for AC3 (the reader's path)** (AC3)
  - [x] Extended `scripts/check-boundary.sh` with a 4th check, in the same grep-and-report style as its existing 3: fails if any file under `site/` matches `anthropic|cohere_?embed|ANTHROPIC_API_KEY|COHERE_API_KEY|gdelt|newsapi` (case-insensitive). Read the script in full before editing; matched its existing style exactly rather than introducing a second check mechanism.
  - [x] Added `tests/test_boundary_check.py::test_catches_site_referencing_an_ai_provider` (planted-violation proof) and `test_a_clean_site_with_only_briefings_json_references_passes` (regression guard: reading `data/briefings/` must never trip this check).
  - [x] Deliberately narrow provider list, matching this task's own stated scope — a tripwire for Epic 4's first violation, not an exhaustive taxonomy.

- [x] **Task 4: Document the story's own conclusion in its Dev Notes/Completion Notes** (all ACs)
  - [x] Stated explicitly below and in Dev Notes above: all three ACs were already true by construction (Stories 3.1/3.4/3.5); this story's sole contribution is the regression tests/tripwire proving each claim.

## Dev Notes

### Why no cost/token measurement mechanism is being built here

The user made this decision explicitly before the story was scoped: AC3's literal text ("when its cost is measured") could be read as requiring a real token/dollar tracking mechanism reading the Batch API's own usage data. This story deliberately does not build one. Reasons: (1) no such mechanism exists anywhere in this codebase today, and adding one would be new observability infrastructure the architecture spine never named as a requirement; (2) the pipeline has never run a real production cycle yet (the Build Order's inspection window depends on `COHERE_API_KEY` being added as a repository secret, still an outstanding manual step per Story 2.1's Completion Notes) — there is no real data to validate a cost-tracking mechanism against yet; (3) the *architectural* guarantee (3 batches per cycle, never per-Zone or per-reader) is what actually keeps cost bounded, and that guarantee is what this story tests — a token counter would observe the same fixed shape, not prove anything a fixed-batch-count test doesn't already prove more cheaply. If real cost data becomes actionable after real cycles accumulate, that is a future, separately-scoped story.

### Why AC2 is "vacuously true" and what this story's tripwire actually buys

Epic 4 (the only place a reader-facing call could exist) has not been built — `site/` is still Story 1.1's static placeholder scaffold. This means AC2 cannot be *demonstrated* against real reader-facing logic yet, only *guarded against a future violation*. The tripwire this story adds (Task 3) is deliberately narrow and will need to be revisited/expanded once Epic 4 stories actually build the mad-libs page — it is not meant to be the final word on this invariant, only the first automated check that exists for it.

### Previous Story Intelligence

- Story 3.1's Dev Notes explicitly named this story ("Story 3.6's NFR-2 cost-independence requirement, three stories ahead") when explaining why the Batch API was chosen over the synchronous Messages API — confirming AC1's mechanism was always meant to land in 3.1, not 3.6.
- Story 3.5's own scope decision (one summarize batch per Output Language, shared across all Zones/Periods via a deduplicated Cluster union) explicitly cites this story by name as the goal it serves "one story early." Read Story 3.5's "Scope, decided explicitly before this story was written" section before starting.
- Single-layer adversarial review (Blind Hunter only) remains the process for this story, per the user's standing cost-reduction decision.

### Project Structure Notes

Files this story likely modifies (no new pipeline stage, no new production mechanism):
- `tests/test_claude_adapter.py` or a new `tests/test_batch_api_boundary.py` (Task 1)
- `tests/test_cycle.py` (Task 2)
- `scripts/check-boundary.sh` (Task 3) — read its current content in full before editing
- This story file itself (Task 4)

### References

- [Source: epics.md#Story 3.6] — acceptance criteria origin (verbatim AC text reproduced above)
- [Source: ARCHITECTURE-SPINE.md#AD-1] — "no AI, embedding, ingestion, or third-party API call at build time or request time" on the site side (exact wording to be confirmed against the spine directly when implementing)
- [Source: pipeline/adapters/claude.py] — `submit_batch`/`collect_batch`'s exclusive use of the Batch API, built in Stories 3.1/3.4
- [Source: pipeline/stages/cycle.py] — the fixed `for language in OUTPUT_LANGUAGES` submission loop, built in Story 3.5
- [Source: pipeline/stages/briefing_matrix.py] — `dedupe_union`, the mechanism keeping the submitted Cluster union bounded by distinct-Cluster count, not Zone count
- [Source: site/astro.config.mjs, site/src/pages/index.astro] — the existing AD-1 comments and static-output configuration
- [Source: scripts/check-boundary.sh] — the existing site/pipeline import-boundary check this story extends
- [Source: _bmad-output/implementation-artifacts/3-1-summarize-selected-clusters-in-one-language.md] — explicitly names this story and NFR-2 when justifying the Batch API choice
- [Source: _bmad-output/implementation-artifacts/3-5-publish-atomically-and-survive-a-failed-cycle.md] — explicitly names this story's goal as being served "one story early" by the fan-out decision

## Dev Agent Record

### Context Reference

_To be filled by dev-story._

### Debug Log

- No implementation bugs surfaced by this story — every test written passed on first run (GREEN immediately after RED-confirming each new test file/function against a codebase that already satisfies the claim), consistent with this story's premise that all three ACs were already true by construction before it started.

### Completion Notes

All 4 tasks complete. This story built zero new production mechanisms — it added regression tests and a static tripwire proving three claims that Stories 3.1, 3.4, and 3.5 already made true architecturally:

**Task 1 (AC1):** `tests/test_batch_api_boundary.py` proves, repository-wide via AST parsing (not per-function), that no call site in `pipeline/` ever reaches for the synchronous `client.messages.create(...)` instead of `client.messages.batches.create(...)`. This is strictly stronger than the existing per-function tests in `test_claude_adapter.py`, which only prove `submit_batch`/`collect_batch` behave correctly in isolation.

**Task 2 (AC2/AC3):** `tests/test_cycle.py::test_summarize_submission_count_stays_fixed_regardless_of_cluster_volume` empirically varies Cluster volume (1 vs. 50 qualifying Clusters) across two cycles and confirms the summarize submission count never moves off 3 — proving cost is a function of `len(OUTPUT_LANGUAGES)`, never of Cluster/Zone/reader volume.

**Task 3 (AC3, the reader's path):** Extended `scripts/check-boundary.sh` with a 4th check (matching its existing 3 in style) that fails if `site/` ever references an AI/embedding/ingestion provider by name. Since Epic 4 doesn't exist yet, this fires on nothing today — it is a tripwire for the first violation a future Epic 4 story could introduce, not a demonstration against real reader-facing logic. Proved the detector works via a planted-violation test, matching `test_boundary_check.py`'s own established discipline.

**Task 4:** This story's own conclusion — all three ACs were already true by construction (Stories 3.1/3.4/3.5 did the actual work); this story's contribution is exclusively the tests/tripwire proving it, and no cost/token measurement mechanism was built (an explicit, pre-scoped user decision — see Change Log).

**Not built in this story, by explicit design (confirmed with the user before story creation):** any token/dollar cost-tracking mechanism. No such mechanism exists anywhere in this codebase, and the pipeline has never run a real production cycle to validate one against (the Build Order's inspection window is still gated on a `COHERE_API_KEY` repository secret, an outstanding manual step since Story 2.1). If real cost data becomes actionable later, that is a future, separately-scoped story.

### File List

**New:**
- `tests/test_batch_api_boundary.py`

**Modified:**
- `scripts/check-boundary.sh` (added the 4th AI-provider-reference check; post-review: simplified the regex to bare provider names — `anthropic|cohere|gdelt|newsapi` — since a narrower pattern like `cohere_?embed` missed real-world variants such as `cohere-embed`)
- `tests/test_boundary_check.py` (added 2 tests for the new check; post-review: added a parametrized test exercising all 4 provider tokens individually, including the hyphenated `cohere-embed-v3` case the original regex would have missed)
- `tests/test_cycle.py` (added the fixed-submission-count regression test; post-review: added an n=0 case — a day with zero qualifying Clusters must still submit exactly 3 batches, not short-circuit)
- `tests/test_batch_api_boundary.py` (post-review: clarified the docstring's scope claim from "repository-wide" to "under `pipeline/`" — matching what the check actually scans; added a test proving an aliased import is still caught, and a test documenting the known, accepted blind spot where an intermediate variable evades detection)

## Change Log

- 2026-08-12: Story created via bmad-create-story. Research confirmed all three ACs are already true by construction (Batch API from Stories 3.1/3.4; fixed 3-batch-per-cycle submission from Story 3.5's fan-out decision; vacuous AC2 truth since Epic 4 doesn't exist yet). User explicitly decided this story's scope is regression tests/a tripwire proving each claim, not a new cost-measurement mechanism — no token/dollar tracking will be built, since none exists today and the pipeline has never run a real production cycle to validate one against.
- 2026-08-12: Implemented via bmad-dev-story. All 4 tasks complete. Built zero new production mechanisms, as scoped — added `test_batch_api_boundary.py` (AST-based `pipeline/`-scoped Batch API check), a fixed-submission-count test in `test_cycle.py`, and a 4th check in `check-boundary.sh` (plus its proof tests) as an Epic-4 tripwire for AD-1. 303/303 tests passing. Status set to review.
- 2026-08-12: Reviewed via bmad-code-review (single-layer Blind Hunter). Found and fixed a real regex-coverage gap (the AI-provider check would have missed a hyphenated real-world reference like `cohere-embed`) and a real test-coverage gap (the fixed-submission-count claim was untested at n=0, a real case — a day with no qualifying Clusters). Corrected a docstring's overstated "repository-wide" scope claim to match what the check actually scans. Added tests for an aliased-import case (still caught) and documented, rather than silently left undiscovered, a known blind spot (an intermediate variable evades the AST check) — accepted as proportionate for a tripwire, not "fixed" with disproportionate data-flow machinery. Rejected 5 findings as non-issues (a dynamic-dispatch bypass no realistic code in this style would produce; test-infrastructure deduplication opportunities; cross-check regression coverage) consistent with this story's own scope decision to add tests, not new production complexity. 310/310 tests passing. Status set to done.
