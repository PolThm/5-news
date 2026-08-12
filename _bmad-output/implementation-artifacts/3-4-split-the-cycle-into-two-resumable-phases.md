---
baseline_commit: b3dae52
---

# Story 3.4: Split the cycle into two resumable phases

Status: done

## Story

As the developer,
I want the batch submission and its collection to be separate runs,
So that an asynchronous batch can never hang a job or lose a cycle.

## Scope, decided explicitly before this story was written

**This story does not build the 15 Zone × 3 Period assembly loop.** That orchestration still does not exist — `cycle.py` ends after `append_history` (Story 2.7); no story has yet called `run_summarize` from `cycle.py` at all. Per the user's explicit decision when this story was scoped, mirroring the precedent Stories 3.2 and 3.3 both already set: **this story builds the two-phase split mechanism itself — the Claude adapter's submit/poll separation, and `cycle.py`'s phase-aware resume logic — operating on the flat list of ranked Clusters `run_rank` already produces, exactly as Stories 3.1–3.3 have all done.** The Zone/Period/Language matrix loop remains deferred to Story 3.5 (publish), which is where `data/briefings/` output actually lands per the architecture spine's Structural Seed, and where a real per-combination call site will finally exist to wire the two-phase mechanism into.

## The real mechanism this story replaces

Every story since 3.1 has flagged this explicitly: `pipeline/adapters/claude.py`'s `summarize_clusters` submits a batch and then **blocks in a `while` loop, sleeping and polling `client.messages.batches.retrieve(...)` until the batch reports `"ended"`**, all within one function call. This was the deliberately simplified version of AD-11, built because no real two-phase call site existed yet to wrap. That call site still doesn't exist (per the scope decision above), but AD-11's actual requirement — *"Neither phase holds a process open waiting on an external service"* — is violated by this poll loop regardless of what calls it, and this story is the one the epic has always named as the fix.

**AD-11's exact rule, quoted from the architecture spine:**

> A cycle runs in two phases with durable state between them. Phase one runs collect through summarize-submit and writes the batch identifier into the cycle's metadata; the job then exits. Phase two polls for that batch, and on completion runs summarize-collect and publish. Neither phase holds a process open waiting on an external service. A cycle whose batch has not completed leaves the previous Briefing set in place (AD-7) and is retried by the next scheduled run, which finds the pending batch identifier and resumes rather than starting over.

Two words matter most: phase two **"polls"** (checks once, does not wait) and phase one/two are separate **runs** (separate process invocations, coordinated only through `cycle.json`, not through anything held in memory).

## Acceptance Criteria

1. **Phase one runs collect through summarize-submit, writes the batch identifier to `data/intermediate/<cycle-id>/cycle.json`, and exits.** Given a cycle invocation with no pending batch recorded, when it runs, it performs collect → dedupe → cluster → rank → history (exactly as `run_cycle` already does) and then submits a Batch API request for the ranked Clusters, writing the returned batch ID (plus enough state to resume: the cycle's ranked Cluster data, so phase two does not need to re-run rank) into `cycle.json`, and the process exits without waiting for the batch (AD-11).

2. **Phase two runs and finds a pending batch identifier; when the batch has completed, it collects the results and the cycle is done (summarize-only in this story's scope — no publish step exists yet).** Given a subsequent invocation finds `cycle.json` carrying a pending batch ID, when it checks the batch's status and finds it `"ended"`, it collects the results via the Batch API (never polling — one check, one API call to fetch results if ready) and writes the summarized output, without re-running collect/dedupe/cluster/rank.

3. **Phase two runs and the batch is not yet complete; it exits without collecting, leaving the pending state in place for a later run to resume.** Given the batch's status is not `"ended"`, when phase two checks, it exits — recording that the check happened (for observability) but not overwriting the pending batch ID — so a later invocation of the same cycle finds the same pending batch and checks again, rather than starting a new one.

4. **No invocation of the cycle ever blocks a process waiting on an external service.** Neither the submit call nor the status check call retries in a loop with a sleep — each is a single, bounded API call. This is verified directly: no code path introduced by this story contains a `while`/`sleep` pair waiting on the Batch API's own completion (the existing `summarize_clusters` poll loop is removed, not merely bypassed).

## Tasks / Subtasks

- [x] **Task 1: Split the Claude adapter into submit and collect** (AC1, AC2, AC4)
  - [x] Replace `summarize_clusters` in `pipeline/adapters/claude.py` with two functions: `submit_batch(clusters: list[dict], language: OutputLanguage, client: Client | None = None) -> BatchSubmission` (constructs and submits the Batch API request exactly as the removed function's first half did, returns the batch ID plus enough failure information to degrade if submission itself failed) and `collect_batch(batch_id: str, clusters: list[dict], client: Client | None = None) -> BatchCollectResult` (a single `client.messages.batches.retrieve(batch_id)` call — no loop, no sleep — returning a tri-state: not-yet-ended, ended-with-results, or ended-but-errored)
  - [x] `collect_batch`'s "not yet ended" case must be distinguishable from its "ended, results collected" case by the caller — do not collapse both into `SummarizeResult`'s existing shape, which has no way to represent "check again later" versus "here are your (possibly degraded) results"; a small wrapper type (e.g. `BatchCollectResult` with a `status` field, or an `Outcome` enum) is warranted here, following this pipeline's established pattern of a dedicated result type per adapter operation (`EmbeddingResult`, `CollectionResult`, `SummarizeResult`)
  - [x] Move the existing result-collection loop (reassociate by `custom_id`, degrade per-Cluster on `errored`/missing, the mid-iteration-failure-preserves-already-collected-summaries fix from Story 3.1's review) into `collect_batch` verbatim — this logic does not change, only which function it lives in
  - [x] Remove the `while`/`time.sleep`/`max_poll_attempts` poll loop entirely — not commented out, not left dead — along with `poll_interval_seconds`/`max_poll_attempts` parameters that existed only to bound it
  - [x] Update `pipeline/stages/summarize.py`'s `SummarizeFn` type alias and any code that called the removed `summarize_clusters` — there is no drop-in replacement signature; `run_summarize` itself is restructured in Task 2, not patched to call a differently-shaped single function

- [x] **Task 2: Make `run_summarize` phase-aware** (AC1, AC2, AC3)
  - [x] `pipeline/stages/summarize.py` needs two entry points now, not one: something like `submit_summarize(clusters, language, cycle_id, data_root, submit_fn=submit_batch) -> WrittenSubmission` (writes the batch ID to disk, does not wait) and `collect_summarize(batch_id, clusters, language, cycle_id, data_root, collect_fn=collect_batch) -> WrittenSummarize | None` (returns `None` if the batch is not yet ended, meaning "nothing to write yet"; returns the existing `WrittenSummarize` shape, with the existing degrade-per-Cluster/attribution logic from Stories 3.1–3.3 unchanged, once it can)
  - [x] The degrade-per-Cluster logic (title fallback, `outbound_url`/`outbound_source` selection, metadata's `degraded_cluster_ids`/`clusters_without_outbound_link_ids`) moves into `collect_summarize` verbatim — it was already written against "the completed batch's results," which is exactly what `collect_summarize` has once the batch is ended; no behavioral change to that logic
  - [x] Where should `clusters` (the full ranked Cluster list, needed by `collect_summarize` to build the final output) live between phase one and phase two? Per AD-11, the durable state is `cycle.json` — write the ranked Cluster list (or a path to it — `rank.py`'s own `ranked.jsonl` output already persists this) alongside the batch ID, so phase two can reconstruct exactly what phase one submitted without re-running rank. Reusing the already-written `ranked.jsonl` path is simpler than duplicating the data into `cycle.json` itself — prefer that if it doesn't complicate the resume logic

- [x] **Task 3: Wire two-phase resume logic into `cycle.py`** (AC1, AC2, AC3, AC4)
  - [x] `run_cycle` currently ends after `append_history` and writes `cycle.json` with `"phase": "collected"` unconditionally. This story adds the summarize phase: **if no pending batch is recorded**, run `submit_summarize` after history-writing and record `"phase": "summarize_submitted"` plus the batch ID (and the language this story submits for — Story 3.2's multi-language loop is Story 3.5's job, so this story submits for exactly one language, following the same single-language precedent Stories 3.1–3.3 all set) in `cycle.json`, then return/exit without waiting
  - [x] **If `cycle.json` already carries a pending batch ID for this same `cycle_id`** (the resume case), do not re-run collect/dedupe/cluster/rank/history at all — call `collect_summarize` directly with the recorded batch ID and ranked-Clusters path. If it returns `None` (not yet ended), update `cycle.json` only to record that a check happened (e.g. a `last_checked_at` timestamp) — the pending batch ID itself is untouched, so the *next* run resumes the same wait, per AD-11's exact words ("is retried by the next scheduled run, which finds the pending batch identifier and resumes"). If it returns real results, write them and mark `"phase": "summarize_collected"`
  - [x] This is new branching logic in `run_cycle`, not a new function replacing it — the existing collect→dedupe→cluster→rank→history guard chain (Story 1.5 through 2.7) is unchanged for a fresh cycle; the new logic only decides what happens *after* history, and only when resuming does it skip straight to the summarize-collect check
  - [x] `main()`'s CLI entry point needs no new flags — resumability is driven entirely by what `cycle.json` already contains for a given `--cycle-id`, not by a mode flag the caller has to remember to pass (a scheduled job invokes the same command every time; the *file on disk* is what decides which phase runs)

- [x] **Task 4: Tests**
  - [x] `tests/test_claude_adapter.py`: `submit_batch` submits correctly and returns a batch ID without ever calling `retrieve()` or `results()` — a fake client that raises if either is called during `submit_batch` proves no polling happens inside submission
  - [x] `tests/test_claude_adapter.py`: `collect_batch` on a not-yet-`"ended"` batch makes exactly one `retrieve()` call and returns the "not ready" outcome — never calls `results()`, never sleeps (a fake client with no `time.sleep` available, or a monkeypatched `time.sleep` that raises if called, proves this)
  - [x] `tests/test_claude_adapter.py`: `collect_batch` on an `"ended"` batch collects and degrades exactly as the removed `summarize_clusters`'s second half did — re-run the existing Story 3.1 regression tests (custom_id reassociation out of order, errored-result-scoped-failure, missing-custom_id-degrade, mid-iteration-failure-preserves-collected-summaries) against `collect_batch` instead
  - [x] `tests/test_summarize_stage.py`: `submit_summarize` writes a batch ID to `cycle.json`-adjacent state without producing `summarized.jsonl`; `collect_summarize` given a not-yet-ended batch returns `None` and writes nothing; `collect_summarize` given an ended batch produces the same `summarized.jsonl` shape (summary/outbound_url/outbound_source/degrade metadata) Stories 3.1–3.3 already established, unchanged
  - [x] `tests/test_cycle.py`: a fresh cycle (no pending batch) runs history-writing then submits a batch and stops, without ever calling anything that waits; a resumed cycle (pending batch recorded, not yet ended) skips collect/dedupe/cluster/rank/history entirely and only checks the batch, leaving the pending ID unchanged; a resumed cycle whose batch is now ended collects and writes final output, updating `cycle.json`'s phase
  - [x] `tests/test_cycle.py`: explicitly assert that no test in this file's new coverage ever calls `time.sleep` — inject a `time.sleep` that raises `AssertionError` if invoked, proving AC4 by construction rather than by inspection

## Dev Notes

### Why a new result type for `collect_batch`, not a reused one

`SummarizeResult` (Story 3.1) has exactly two states: some summaries succeeded, some failed — both are always meaningful together, because the batch was always known to be complete when that type was constructed. `collect_batch` has a third state this pipeline has never needed before: *the batch hasn't finished yet, and there is nothing to report at all* — not a Cluster-scoped failure, a whole-call "check again later." Collapsing this into `SummarizeResult(failures=[...])` would make "batch not done" indistinguishable from "batch done, but every Cluster individually failed" — two states with completely different resume implications (one retries the same batch, the other should probably alert on a genuinely broken batch). Keep them separate.

### Why `run_cycle`'s existing guard chain is untouched

Every guarded step in `run_cycle` (write_collection, run_dedupe, run_cluster, run_rank, append_history) exists because a crash anywhere must still leave `cycle.json` written (Story 1.5's original reasoning, reaffirmed at every subsequent stage addition). This story's two-phase logic is additive — a fresh cycle still runs every one of those steps in order, exactly as before; only what happens *after* `append_history` branches on whether a batch is already pending. Do not restructure the existing chain to "support" resumability generically — the resumability this story needs is specific to the summarize phase, not a generic checkpoint-every-stage mechanism the PRD never asked for.

### What "the batch ID plus enough state to resume" means concretely

Phase two needs three things to call `collect_batch` correctly: the batch ID, the language it was submitted in (so the eventual `collect_summarize` writes to the right language-scoped path, per Story 3.2), and the same `clusters` list that was submitted (so results can be reassociated by `custom_id` and the final output can be built with every pass-through field Stories 3.1–3.3 established). The first two are trivially small strings for `cycle.json`. The third is not — do not duplicate the full ranked-Cluster list into `cycle.json` itself; `rank.py`'s `ranked.jsonl` already persists it at a known path (`output_dir_for("rank", cycle_id, data_root) / "ranked.jsonl"`, derivable from `cycle_id` alone). Record the batch ID and language in `cycle.json`; re-read `ranked.jsonl` from disk when resuming.

### Project Structure Notes

No new files. Files this story modifies:
- `pipeline/adapters/claude.py` (remove `summarize_clusters`; add `submit_batch`, `collect_batch`, and a new result type for `collect_batch`'s tri-state outcome)
- `pipeline/stages/summarize.py` (remove or restructure `run_summarize`; add `submit_summarize`, `collect_summarize`; move the existing degrade/attribution logic into `collect_summarize` unchanged)
- `pipeline/stages/cycle.py` (add the phase-branch logic after `append_history`; `cycle.json`'s schema gains a pending-batch section)
- `tests/test_claude_adapter.py` (split existing tests across `submit_batch`/`collect_batch`; add no-polling proof tests)
- `tests/test_summarize_stage.py` (split existing tests across `submit_summarize`/`collect_summarize`)
- `tests/test_cycle.py` (new fresh-cycle-submits, resume-not-ready, resume-collects test cases)

### Previous Story Intelligence

- Stories 3.1, 3.2, and 3.3 have each explicitly named this story as the one that removes the poll loop — read all three stories' "Why this story does not build AD-11's two-phase split" sections (3.1) and their "Not built in this story" notes (3.2, 3.3) before starting; they document exactly which simplification this story is now expected to undo.
- Story 3.1's adversarial review found and fixed a real bug in the poll-loop version: a blanket exception around the whole submit+poll+collect sequence discarded already-collected summaries on a late failure. That fix's *logic* (separate exception scopes for submission versus collection) must survive the split into `submit_batch`/`collect_batch` — it's naturally easier to get right once collection is its own function with its own boundary, but verify the fix's actual behavior (a mid-`results()`-iteration failure still preserves earlier successes) still holds after the split, via the carried-over regression test.
- Single-layer adversarial review (Blind Hunter only) remains the process for this story, per the user's standing cost-reduction decision.

### References

- [Source: epics.md#Story 3.4] — acceptance criteria origin (verbatim AC text reproduced above)
- [Source: ARCHITECTURE-SPINE.md#AD-11] — the exact two-phase rule this story implements, quoted in full above
- [Source: ARCHITECTURE-SPINE.md#AD-7] — "a cycle whose batch has not completed leaves the previous Briefing set in place," referenced by AD-11's own text (this story does not yet touch publish/Briefing sets — noted for Story 3.5, not acted on here)
- [Source: pipeline/adapters/claude.py#summarize_clusters] — the exact function this story splits, and the poll loop being removed
- [Source: pipeline/stages/cycle.py#run_cycle] — the existing guard-chain pattern this story extends, not replaces
- [Source: _bmad-output/implementation-artifacts/3-1-summarize-selected-clusters-in-one-language.md] — names this story as the one that replaces the poll loop; documents the mid-iteration-failure fix that must survive the split

## Dev Agent Record

### Context Reference

_To be filled by dev-story._

### Debug Log

- Initial design mistake caught before it caused test drift: `run_cycle`'s injection points were first typed against `claude.py`'s low-level `SubmitFn`/`CollectFn` (the `submit_batch`/`collect_batch` shape) while the actual call sites invoked stage-level wrapper functions (`submit_summarize`/`collect_summarize`) with a different keyword signature. Caught by re-reading my own code before writing tests, not by a test failure — fixed by renaming the parameters to `submit_summarize_fn`/`collect_summarize_fn` and typing them against the stage-level functions' real signatures directly.
- 3 pre-existing Story 1.5–2.7 tests in `test_cycle.py` failed after wiring in real `submit_summarize` as the default: they run with no `ANTHROPIC_API_KEY` in the test environment, so real submission now correctly degrades the cycle with a new failure — exactly the AD-10 behavior this pipeline is built around, but not what those tests were asserting before this story existed. Fixed by adding a `_no_op_submit_summarize` stub (mirroring the file's existing `_no_op_embed` convention) and threading it through all 20 existing `run_cycle` call sites via a scripted bulk edit, verified against the full diff before running tests.

### Completion Notes

All 4 tasks complete, TDD throughout. 261/261 tests passing (up from 256 at story start: +5 new adapter tests, +6 new stage tests net of restructuring, +5 new cycle tests, plus 20 existing cycle tests updated to inject the new stub).

**Task 1:** `pipeline/adapters/claude.py`'s `summarize_clusters` (submit + poll-loop + collect, all one blocking call) is gone entirely — replaced by `submit_batch` (one `create()` call, returns immediately) and `collect_batch` (one `retrieve()` call; only calls `results()` if `processing_status == "ended"`). Added `BatchSubmission` and `BatchCollectResult` as dedicated result types — `SummarizeResult` is retired since neither new function's outcome fits its two-state shape (`BatchCollectResult` needs a third "pending" state `SummarizeResult` had no way to represent). The mid-iteration-failure-preserves-collected-summaries fix from Story 3.1's review moved into `collect_batch` unchanged, confirmed by carrying its exact regression test over.

**Task 2:** `pipeline/stages/summarize.py`'s `run_summarize` split into `submit_summarize` (writes a small `submitting.json` marker, no `summarized.jsonl` yet) and `collect_summarize` (returns `None` — writes nothing — if the batch is still pending; otherwise runs the exact same degrade/attribution/metadata logic Stories 3.1–3.3 built, unchanged). `collect_summarize` takes the same `clusters` list `submit_summarize` was called with, per the story's own Dev Notes — `cycle.py` is responsible for handing it the same list both times, via `ranked.jsonl`'s path.

**Task 3:** `run_cycle` now checks `cycle.json` for a pending `summarize_batch` before doing anything else. Fresh cycle: runs the existing collect→dedupe→cluster→rank→history chain completely unchanged, then submits a batch and returns — `summarize_phase="summarize_submitted"`. Resumed cycle (pending batch found): skips straight to `_resume_cycle`, which re-reads `cycle.json` and `ranked.jsonl` from disk (never anything held in memory across invocations, per AD-11's own framing) and calls `collect_summarize` once. Not yet ended: records a `last_checked_at` timestamp, leaves the pending batch ID untouched. Ended: writes `summarize_collected` and clears the pending state. `main()`'s CLI needed zero new flags — the file on disk is what decides which phase runs, exactly as the story required.

**Task 4:** New tests for both adapter functions (including a monkeypatched `time.sleep` that raises if called, at both the adapter and cycle level) and both stage functions, plus 5 new `test_cycle.py` tests covering the fresh-submit, resume-skips-everything, resume-not-ready-leaves-id-unchanged, and resume-collects cases. Verified AC4 by construction, not just by test: grepped the three touched files directly and confirmed zero occurrences of `time.sleep`, `import time`, or a `while ... processing_status` loop anywhere in the two-phase code path.

**Not built in this story, by explicit design (confirmed with the user before story creation):** the 15 Zone × 3 Period assembly loop — `cycle.py` still submits/collects for exactly one language (`OutputLanguage.FR` by default, injectable), operating on the flat `ranked.jsonl` list, following the same single-language precedent every Epic 3 story so far has set. That loop, and Story 3.5's publish step, remain deferred to Story 3.5.

### File List

**Modified:**
- `pipeline/adapters/claude.py` (removed `summarize_clusters`/`SummarizeResult`; added `submit_batch`, `collect_batch`, `BatchSubmission`, `BatchCollectResult`, shared `_client_or_degrade` helper)
- `pipeline/stages/summarize.py` (removed `run_summarize`/`SummarizeFn`; added `submit_summarize`, `collect_summarize`, `WrittenSubmission`, `SubmitFn`, `CollectFn`; degrade/attribution logic moved into `collect_summarize` unchanged; `main()` gained a `--batch-id` flag for manual collection; post-review: `WrittenSummarize` gained a `failures` field, `main()` now surfaces both submit and collect failures)
- `pipeline/stages/cycle.py` (added `_read_pending_batch`, `_resume_cycle`; `run_cycle` gained `language`/`submit_summarize_fn`/`collect_summarize_fn` parameters and the phase-branch logic after history-writing; `CycleResult` gained `summarize_phase`; `cycle.json` gained a `summarize_batch` section; post-review: `_resume_cycle` now guards `collect_summarize_fn` against exceptions and folds a collected batch's `Failure`s into `cycle.json`; removed a redundant second read of `ranked.jsonl`)
- `tests/test_claude_adapter.py` (rewritten: every `summarize_clusters` test split across `submit_batch`/`collect_batch`; added no-polling proof tests for both)
- `tests/test_summarize_stage.py` (rewritten: every `run_summarize` test split across `submit_summarize`/`collect_summarize`, mostly unchanged assertions; post-review: added a `main()` submission-failure-surfacing test)
- `tests/test_cycle.py` (added `_no_op_submit_summarize` stub, threaded through all 20 existing call sites; added 5 new tests for the two-phase split; post-review: added 2 tests for resume-crash-degrades and collected-failures-fold-into-cycle.json)

## Post-Review Fixes

Single-layer adversarial review (Blind Hunter) found 11 issues; 5 were genuine defects, fixed here. The rest were out-of-scope (the deferred multi-language assembly loop, already a user-approved decision) or stylistic nitpicks not worth the churn.

- **`_resume_cycle` had no exception guard around `collect_summarize_fn`, unlike every other guarded step in `run_cycle`.** A transient failure while checking a batch (network blip, a truncated `ranked.jsonl`) used to crash `run_cycle` entirely instead of degrading, directly contradicting AD-10 and the surrounding module's own established pattern. Fixed by wrapping the read-and-check in `try/except Exception`, recording a `Failure` and marking `cycle.json` degraded on the resume path too. Regression test: `test_a_resume_check_that_raises_degrades_the_cycle_instead_of_crashing`.
- **A collected batch's own `Failure`s never reached `cycle.json`.** `collect_summarize`'s `WrittenSummarize` computed per-Cluster failures but `_resume_cycle` discarded them entirely — `cycle.json`'s `degraded` flag could read `false` even after every Cluster in a batch failed to summarize. Fixed by adding a `failures` field to `WrittenSummarize` and folding it into `_resume_cycle`'s failure list before writing `cycle.json`. Regression test: `test_a_collected_batchs_failures_are_folded_into_the_cycle_record`.
- **`summarize.py`'s `main()` silently printed `"submitted batch None"` on a submission failure**, with exit code 0 and no indication anything went wrong — unlike `cycle.py`'s own `main()`, which already surfaces failures on stderr. Fixed by checking `submitted.batch_id`/printing collect-side failures to stderr in both CLI branches. Regression test: `test_main_reports_a_submission_failure_on_stderr_instead_of_printing_none`.
- **Misleading comment**: the "this cycle_id is retried from the top on the next scheduled run" comment overstated what actually happens — a submit-failure cycle is never revisited; the *next* cycle_id starts over from collect with fresh data (AD-7), it doesn't resume this one. Reworded for accuracy; no behavior change.
- **`ranked.jsonl` was read twice in `run_cycle`** (once for `append_history`, again for the summarize submission) — same file, same guard expression, no stated reason for the duplication. Reused the `selected` list already produced for `append_history` instead.

Not changed (rejected as out-of-scope or non-issues): `run_cycle`'s lack of a `client` injection point (the existing `submit_summarize_fn`/`collect_summarize_fn` injection already covers this); `cycle.json`'s single-pending-batch schema and hardcoded default language (explicitly deferred to Story 3.5 per the user's own scope decision); repeating the same stale failures list on every "still pending" poll (bounded, harmless noise); lack of a runtime assertion that `collect_summarize`'s `clusters` argument matches what was submitted (defense-in-depth, no concrete failure path in the current call graph).

264/264 tests passing after fixes (up from 261). Lint and format clean.

## Change Log

- 2026-08-12: Story created via bmad-create-story. User explicitly decided this story stays scoped to the two-phase split mechanism itself (adapter submit/collect separation, cycle.py resume logic), operating on the flat ranked-Cluster list, deferring the 15 Zone × 3 Period assembly loop to Story 3.5 — mirroring the precedent every Epic 3 story so far has set.
- 2026-08-12: Implemented via bmad-dev-story. All 4 tasks complete, TDD throughout. Caught and fixed an internal design mismatch (injection points typed against the wrong function signatures) before it reached any test. 261/261 tests passing (up from 256). Status set to review.
- 2026-08-12: Reviewed via bmad-code-review (single-layer Blind Hunter). 5 genuine defects fixed (resume-phase crash-instead-of-degrade, dropped collect-side failures, silent CLI submission failure, a misleading comment, a redundant file read); 6 findings rejected as out-of-scope or non-issues. 264/264 tests passing. Status set to done.
