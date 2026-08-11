---
baseline_commit: 4e30c1c
---

# Story 2.2: Rank Clusters deterministically

Status: done

## Story

As the developer,
I want Qualifying Clusters ordered by Consensus Score with no AI involved,
so that the product's central judgment is reproducible and defensible.

## Acceptance Criteria

1. **Qualifying floor.** The rank stage reads the cluster stage's output (`clusters.jsonl`) and considers only Clusters meeting the Qualifying Cluster floor: at least 2 Independent Sources from at least 2 distinct countries (PRD Glossary, PRD line 70). A Cluster below the floor is excluded from ranking and counted toward Discarded Volume — it is never displayed and never counted toward item totals (FR-4).

2. **Deterministic ordering (AD-4).** Qualifying Clusters are ordered by Independent Source count descending, then country count descending, then a stable tiebreak on cluster identity (the `cluster_id` string, ascending — already deterministic per Story 2.1). No model call, no randomness, no wall-clock read, no map/set/dict-iteration-order dependence anywhere in the ranking logic.

3. **Byte-identical reruns.** Running the rank stage twice on identical input produces byte-identical output (sorted keys, atomic write, trailing newline — the existing `write_jsonl`/`write_atomically` contract).

4. **At most 5, never padded.** If more than 5 Clusters qualify, only the top 5 (by the Acceptance Criterion 2 ordering) are selected; the rest count toward Discarded Volume. If between 2 and 4 Clusters qualify, exactly that many are selected — never padded with a non-qualifying Cluster to reach 5 (FR-4). If fewer than 2 qualify, zero are selected (FR-16's Continent fallback is Story 2.5's job, not this stage's — this stage simply reports zero-selected honestly).

5. **The stage runs alone, on cluster's output.** `python -m pipeline.stages.rank --input <cluster-clusters-path> --cycle-id <id>` reads `clusters.jsonl` and writes ranked output to `data/intermediate/rank/<cycle-id>/ranked.jsonl`, following the same CLI and stage-contract conventions as every prior stage.

6. **Discarded Volume is counted, not just implied.** The rank stage's own metadata output (`{stage}.json`, following the `collect.py`/`dedupe.py`/`cluster.py` pattern) records: total Clusters in, Clusters qualifying, Clusters selected (≤5), and Clusters discarded (qualifying but ranked 6th or below, plus non-qualifying). This is the input FR-8's Discarded Volume display will read from later — this story only has to produce the honest count, not render it.

## Tasks / Subtasks

- [x] **Task 1: Qualifying floor** (AC: 1)
  - [x] `pipeline/stages/rank.py`: read `clusters.jsonl` from `--input` (cluster stage's output format — see Dev Notes → Cluster output shape)
  - [x] A Cluster qualifies iff `independent_source_count >= 2 AND country_count >= 2` — read these values directly from cluster's output; do not recompute them (AD-5, AD-12: dedupe/cluster own these numbers, rank only consumes them)
  - [x] Add the qualifying-floor constants (`MIN_INDEPENDENT_SOURCES = 2`, `MIN_COUNTRIES = 2`) to `pipeline/config/__init__.py` if not already present — check first: these were deliberately *removed* from config during Story 1.1's code review as premature (scope belonged to this story). Add them now, in `pipeline/config/`, not hardcoded in `rank.py` — the qualifying floor is a product-level constant future stories (2.5, 2.6) will also read.

- [x] **Task 2: Deterministic ordering** (AC: 2, 3)
  - [x] Sort qualifying Clusters with a pure Python `sorted(..., key=...)` call: `key=lambda c: (-c["independent_source_count"], -c["country_count"], c["cluster_id"])` — negating the two count fields achieves descending order while keeping the tiebreak ascending, all within one stable sort call
  - [x] No use of `set`, unordered `dict` iteration for anything that affects output order, `random`, `datetime.now()`/`time.time()`, or any external call anywhere in the ranking path
  - [x] Write output with `write_jsonl` (sorted-keys, atomic — reuse, do not reimplement)

- [x] **Task 3: Selection cap** (AC: 4)
  - [x] After sorting, select `ranked[:5]` — Python slicing past the list length is safe and naturally yields fewer than 5 when fewer qualify; no padding logic needed or wanted
  - [x] Each selected Cluster's output row carries its rank position (1-indexed) alongside its existing fields — downstream stages (summarize, publish) will need to know "this is item 3 of 5", not just an implicit list position

- [x] **Task 4: Discarded Volume accounting** (AC: 6)
  - [x] Metadata output records: `clusters_in` (total read), `clusters_qualifying` (met the floor), `clusters_selected` (min(qualifying, 5)), `clusters_discarded` (`clusters_in - clusters_selected`) — note this definition discards BOTH non-qualifying Clusters AND qualifying-but-unranked (6th+) Clusters, consistent with the PRD's Discarded Volume definition ("Articles ingested... minus those in its published Clusters" extended one level: Clusters considered minus Clusters selected)
  - [x] Write via `write_atomically`, matching the exact `{stage}.json` shape used by `collect.py`/`dedupe.py`/`cluster.py`

- [x] **Task 5: Cycle wiring**
  - [x] Wire `run_cycle` (`pipeline/stages/cycle.py`) to call the rank stage after cluster, following the exact same independently-guarded try/except pattern as collect/dedupe/cluster — the cycle must still write `cycle.json` if ranking crashes, not just if it degrades
  - [x] Add `clusters_ranked`/`clusters_selected` (however you choose to name the new field — be consistent with the existing `articles_collected`/`groups_after_dedupe`/`clusters_after_grouping` naming pattern) to `CycleResult` and `cycle.json`
  - [x] Unlike cluster's embedding call, rank has no external dependency and cannot "degrade" in the AD-10 sense — an exception here is a real bug, not a vendor outage. Guard it anyway, for the same reason dedupe and cluster are guarded: `cycle.json` must survive any crash, of any origin, in any stage (this was Epic 1's own review finding, don't reintroduce the gap it fixed).

- [x] **Task 6: Tests**
  - [x] Unit test the qualifying floor: a Cluster with 1 Independent Source is excluded; a Cluster with 2 Independent Sources but only 1 country is excluded; a Cluster with 2 Independent Sources across 2 countries qualifies
  - [x] Unit test ordering: Independent Source count is the primary sort key (a 5-source/2-country Cluster ranks above a 3-source/4-country Cluster — FR-6's explicit choice, not the "obviously fairer" country-first ordering)
  - [x] Unit test the country-count tiebreak: two Clusters with equal Independent Source counts are ordered by country count descending
  - [x] Unit test the stable tiebreak: two Clusters with identical source AND country counts are ordered by `cluster_id` ascending, deterministically, regardless of input order
  - [x] Unit test the cap: 7 qualifying Clusters in, exactly 5 out, ranked 6-7 counted in `clusters_discarded`
  - [x] Unit test no-padding: 3 qualifying Clusters in, exactly 3 out (not padded to 5)
  - [x] Unit test zero qualifying: 0 Clusters meet the floor, 0 selected, cycle still completes normally
  - [x] Test determinism: identical input, run twice, byte-identical output file
  - [x] Test the cycle integration: rank runs after cluster in `run_cycle`; a crash in rank still leaves `cycle.json` written (mirror the existing `test_cluster_crashing_still_leaves_a_cycle_record` pattern in `tests/test_cycle.py`)

## Dev Notes

### FR-6's explicit, non-obvious ordering choice

The PRD is explicit and this was a deliberate user decision against the PM's own recommendation during PRD creation: **Independent Source count leads, country count only breaks ties.** A Cluster with 10 sources from 2 countries ranks above a Cluster with 3 sources from 3 countries. This can look wrong at a glance — "shouldn't wider geographic spread count for more?" — but it is the specified behavior (PRD line 142, epics.md Story 2.2 AC2 "ordering is by Independent Source count descending, then country count descending"). Do not "fix" this into a weighted or country-first scheme. If a future story wants that changed, it needs an explicit new FR, not a quiet fix inside this one.

### Qualifying Cluster floor — exact PRD wording

PRD Glossary (line 70): "a Cluster eligible for inclusion in a Briefing: it has **at least 2 Independent Sources from at least 2 distinct countries** within the Briefing's Period and Zone. Clusters below this floor are never displayed and never counted toward item totals." Both conditions are `>=`, and both must hold — a Cluster with 5 sources all from the same country does NOT qualify (fails the 2-country floor) despite easily clearing the source-count floor. Test this exact edge case explicitly (Task 6).

### Cluster output shape (what this stage reads)

From `pipeline/stages/cluster.py`'s `run_cluster`, `clusters.jsonl` (one dict per line) has these keys, per the `clusters_out.append({...})` block: `cluster_id` (16-hex-char stable ID), `member_titles` (sorted list of normalized dedupe-group titles), `independent_source_count` (int), `country_count` (int). Read with `pipeline.stages.read_jsonl`. There is currently no Period/Zone dimension on this data — Story 2.1 and this story both operate on a single "World / day" cycle's worth of Clusters, consistent with the Build Order's incremental approach. Zone/Period-scoped ranking (multiple Briefings per cycle) is out of scope here; do not add it speculatively.

### Why the qualifying-floor constants were removed from config, and now come back

During Story 1.1's code review, `pipeline/config/__init__.py` briefly held ranking threshold constants that were removed because Task 3 of that story never asked for them — they were scope creep at that point, with no rank stage yet to consume them. That reasoning no longer applies: this story is exactly the consumer. Add them now, as real config-level constants (not hardcoded literals in `rank.py`), because Story 2.5 (Continent fallback) and Story 2.6 (anti-concentration cap) will both need the same floor value and must not each define their own copy.

### Cycle wiring (AD-10, and Epic 1's hardened guard pattern)

`pipeline/stages/cycle.py`'s `run_cycle` now guards three sequential steps (`write_collection`, `run_dedupe`, `run_cluster`), each in its own try/except, each capable of setting `completed = False` on failure, with `cycle.json` written unconditionally at the end regardless of where a crash occurred. This pattern was hardened during the Epic 1 review specifically because an earlier version left `cycle.json` unwritten on a dedupe crash — the only tracked file, meaning a bad day left nothing in git at all. Add rank as a fourth guarded step, following the identical structure. Read the current `run_cycle` in full before touching it (it is short, under 100 lines) and copy the pattern exactly — do not invent a variant.

Note the distinction Task 5 draws: cluster's embedding call can legitimately fail for reasons outside this codebase's control (a Cohere outage) and "degrades" gracefully. Rank has no such external dependency — every input to it is already on disk, already validated. An exception inside rank's logic is a real bug in this codebase, not a degraded-but-expected outcome. Guard it for the same "cycle.json must always get written" reason, but do not design a "degrade" story for rank the way Story 2.1 did for embedding — there is nothing external to degrade from.

### Project Structure Notes

New files this story creates:
- `pipeline/stages/rank.py`
- `tests/test_rank_stage.py`

Files this story modifies:
- `pipeline/config/__init__.py` (add qualifying-floor constants)
- `pipeline/stages/cycle.py` (add the guarded rank step, new `CycleResult` field)
- `tests/test_cycle.py` (add rank-stage integration tests, following the pattern of the existing cluster-stage integration tests added in Story 2.1)

### Previous Story Intelligence (Story 2.1 and its review)

- Story 2.1's code review caught two high-severity bugs both rooted in the same mistake: trusting a library's internal heuristic (HDBSCAN's density criterion, then its single-linkage epsilon) to do something simpler and more explicit could do more reliably. This story has no such risk — it is pure Python sorting and filtering, no library heuristics involved — but the lesson generalizes: prefer the simplest correct mechanism (a `sorted()` call with an explicit tuple key) over anything that could have hidden non-determinism.
- The guard-every-stage pattern in `cycle.py` has now been applied three times (collect, dedupe, cluster) and caught a real bug each of the first two times it was added. Follow it exactly a fourth time; do not assume rank is simple enough to skip the guard.
- `write_jsonl`/`write_atomically` (from `pipeline.stages`) are the established, tested primitives for all stage output — Story 1.1 through 2.1 all reuse them unmodified. Do not write output any other way.

### References

- [Source: architecture/architecture-5-news-2026-08-10/ARCHITECTURE-SPINE.md#AD-4] — rank stage determinism contract, exact ordering rule
- [Source: architecture/architecture-5-news-2026-08-10/ARCHITECTURE-SPINE.md#AD-5, AD-12] — counts owned by dedupe/cluster, rank only consumes
- [Source: prd.md line 70] — Qualifying Cluster exact definition
- [Source: prd.md line 142, 147-149] — ranking mechanism, FR-6 exact ordering, Discarded Volume
- [Source: epics.md#Story 2.2] — acceptance criteria origin
- [Source: pipeline/stages/cluster.py] — output shape this stage reads
- [Source: pipeline/stages/cycle.py] — guard pattern to replicate for the rank step

## Dev Agent Record

### Context Reference

_To be filled by dev-story._

### Debug Log

_To be filled by dev-story._

### Completion Notes

All 6 tasks complete. 18 new tests added (14 rank-stage unit tests, 2 rank-specific cycle integration tests, plus 2 existing test-count increases from full-suite verification); full suite is 152 tests, all green. `ruff check` and `ruff format --check` both pass. Boundary check passes.

No implementation surprises this time — unlike Story 2.1's HDBSCAN detour, ranking is a plain Python `sorted()` call on integer fields already computed by earlier stages, so there was no library heuristic to discover was wrong. The one deliberate deviation from a literal reading of the story: `qualifies()` and `rank_clusters()` are exposed as standalone functions (not folded into `run_rank`) specifically so tests could exercise ordering logic directly against hand-built dicts without going through file I/O — this wasn't explicitly requested but follows the same testability pattern established by `cluster_vectors`/`assign_cluster_ids` in Story 2.1.

Key implementation notes for future stories:
- `MIN_INDEPENDENT_SOURCES`, `MIN_COUNTRIES`, `MAX_SELECTED_CLUSTERS` now live in `pipeline/config/__init__.py` — Story 2.5 (Continent fallback) and 2.6 (anti-concentration cap) should read these, not redefine them.
- Rank is the fourth stage guarded in `run_cycle`'s try/except-per-stage pattern. Verified via test that a crash inside `run_rank` still leaves `cycle.json` written with `completed: false`.
- Verified a real end-to-end case in `test_runs_rank_after_cluster`: two distinct single-source dispatches each become their own singleton Cluster (Story 2.1's behavior) and correctly select 0 items, since neither meets the 2-source/2-country floor alone — this is the expected, honest result of a quiet news day feeding through the full pipeline, not a bug.

### File List

**New:**
- `pipeline/stages/rank.py`
- `tests/test_rank_stage.py`

**Modified:**
- `pipeline/config/__init__.py` (added `MIN_INDEPENDENT_SOURCES`, `MIN_COUNTRIES`, `MAX_SELECTED_CLUSTERS`)
- `pipeline/stages/cycle.py` (added guarded rank step, `clusters_selected` field, `rank_path`)
- `tests/test_cycle.py` (added rank-integration tests)

## Post-Review Fixes (bmad-code-review, 3-layer adversarial pass)

The Acceptance Auditor found zero AC violations — all 6 ACs verified against code and passing, full test suite run locally. The Blind Hunter and Edge Case Hunter both explicitly confirmed the core determinism mechanism (`rank_clusters`'s pure `sorted()` call, no dict/set-iteration dependence, FR-6's source-before-country precedence) is correct — this story's central risk was checked hardest and found sound.

**Fixed (real, pre-existing bug, independently flagged by both Blind Hunter and Edge Case Hunter):** `dedupe_path`/`cluster_path`/`rank_path` on `CycleResult` were pre-initialized to their *expected* output path before each stage ran, so a crashed (or never-reached) stage left the field pointing at a file that was never actually written — a caller checking `result.rank_path.exists()` after a failed cycle got a false negative instead of an explicit signal. This pattern existed since Story 2.1 (`cluster_path`) but was never caught until two independent reviewers flagged it on the same story. Fixed by typing these three fields `Path | None`, defaulting to `None`, and only assigning the real path on that stage's actual success. Added assertions to all three existing crash tests (`test_dedupe_crashing_still_leaves_a_cycle_record`, `test_cluster_crashing_still_leaves_a_cycle_record`, `test_rank_crashing_still_leaves_a_cycle_record`) confirming the crashed stage's path (and every downstream stage's path) is `None`.

**Bonus catch while fixing the above:** `test_dedupe_crashing_still_leaves_a_cycle_record` no longer actually triggered a dedupe crash — it relied on a truncated `articles.jsonl` written directly to disk, but `write_collection` now overwrites that file with a valid empty one before dedupe ever reads it, so the test was silently passing for the wrong reason (`completed` was `True`, not `False` as its own name implied). Rewrote it to monkey-patch `run_dedupe` directly, matching the pattern already used for the cluster and rank crash tests.

**Fixed (minor, Blind Hunter):** `MIN_INDEPENDENT_SOURCES`, `MIN_COUNTRIES`, `MAX_SELECTED_CLUSTERS` are now `Final[int]`, consistent with AD-12's "one owner per value" — a plain mutable module-level `int` left the door open for accidental mutation across a shared test run.

**Fixed (minor, Blind Hunter):** added a test verifying rank produces byte-identical output when re-run into the *same* output path (overwriting prior output), not just into two different directories — the more realistic production scenario of a cycle re-run.

**Deferred, not fixed (legitimate but low-priority given current guarantees):** no explicit type/key validation on cluster dicts read from disk (`qualifies()`/`rank_clusters()` trust `cluster_id`/`independent_source_count`/`country_count` are present and correctly typed) — a malformed record raises a raw `KeyError`/`TypeError` rather than a stage-specific error, though it's still caught by `cycle.py`'s guard and doesn't crash the cycle. No explicit handling of duplicate `cluster_id` — `cluster.py`'s ID derivation makes duplicates structurally near-impossible today (SHA-256 of sorted member indices), so this is a defense-in-depth gap rather than a reachable bug. Both are the kind of input-trust assumption already made throughout this pipeline (e.g. `coverage_for_cluster` trusts `g["source_country"]` exists) — worth hardening if a future stage's data ever gets less trustworthy, not urgent now.

After fixes: 153 tests passing (up from 152).

## Change Log

- 2026-08-11: Story created via bmad-create-story, second story of Epic 2.
- 2026-08-11: Implemented via bmad-dev-story. All tasks complete, 152/152 tests passing. Status set to review.
- 2026-08-11: Reviewed via bmad-code-review (3-layer adversarial). Zero AC violations. Fixed a real pre-existing bug (crashed-stage paths reporting a never-written file, present since Story 2.1) plus one bonus catch (a crash test that no longer actually crashed). 153/153 tests passing. Status set to done.
