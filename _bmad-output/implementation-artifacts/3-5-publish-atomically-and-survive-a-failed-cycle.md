---
baseline_commit: 38c9f87
---

# Story 3.5: Publish atomically and survive a failed cycle

Status: done

## Story

As a reader,
I want the site to keep working when a generation cycle fails,
So that I never meet an error page or a half-written Briefing.

## Scope, decided explicitly before this story was written

This is the story every prior Epic 3 story (3.1, 3.2, 3.4) has explicitly deferred to: the 15 Zone × 3 Period × 3 Output Language assembly loop finally gets built here, because this is the first story where `publish` exists to consume its output and decide where the 135 files actually land on disk (per Stories 3.2's and 3.4's own Dev Notes, and the architecture spine's Structural Seed, which names `data/briefings/` as `publish`'s output — not `summarize`'s).

**Fan-out decision, made explicitly with the user before this story was written:** summarize does **not** run once per (Zone, Period, Language) combination — that would mean up to 135 separate Batch API submissions per cycle, many summarizing the same Cluster redundantly (a Cluster visible in both "france" and "europe" would be summarized twice), and would make `cycle.json`'s resumable state explode from one pending batch to as many as 135. Instead: **summarize runs once per Output Language (3 batches per cycle total), on the union of every qualifying Cluster across all 15 Zones × 3 Periods, deduplicated by `cluster_id`.** `publish` then assembles each of the 135 Briefings by looking up each Zone×Period's selected Clusters' Summaries from that shared, already-computed pool. This keeps AI cost bounded by the number of *distinct* Clusters considered per cycle, not by the number of Zones — directly serving Story 3.6's "cost independent of readership/Zone-count" goal one story early, and keeps the two-phase resume state Story 3.4 built at exactly 3 pending batches (one per language), not 135.

## The two mechanisms this story must wire together

**1. The Zone × Period ranking loop.** `pipeline/stages/rank.py`'s `rank_for_zone(clusters, zone) -> ZoneRanking` already exists, is fully unit-tested, and explicitly says in its own docstring: *"Wiring it into a per-cycle loop that runs it for all 15 Zones and decides where that output lives is later Epic 3/4 work."* This story is that later work. For the `day` Period, `rank_for_zone` runs directly against this cycle's own qualifying Clusters (the output of `run_cluster`, before the flat `run_rank` — see Dev Notes on why the input differs from `cycle.py`'s existing flat rank call). For `week`/`month`, `rank.py`'s `link_across_days(today_clusters, history_entries, embedding_by_id)` must first merge today's Clusters with `pipeline.stages.history.read_history(...)` entries from the appropriate window (7 days / 30 days) before `rank_for_zone` runs on the merged set — `link_across_days` is unit-tested in isolation but has never been called from any stage; this story is the first real wiring.

**2. The publish stage itself.** A new `pipeline/stages/publish.py` that takes the assembled Zone×Period×Language matrix (135 `Briefing`-shaped records, each already carrying its selected Clusters' Summaries from the shared per-language summarize pool) and writes it to `data/briefings/<lang>/<zone>/<period>.json` — the whole set atomically: **all 135 files land, or none do** (AD-7). A cycle that fails at any point before publish completes must leave the previous `data/briefings/` tree completely untouched.

## Acceptance Criteria

1. **A complete cycle produces all 135 Briefings and publishes them atomically, or publishes nothing.** Given a cycle that successfully collects, dedupes, clusters, and (per-language) summarizes, when publish runs, it writes one JSON file per (Output Language, Zone, Period) combination — 135 files total — to `data/briefings/<lang>/<zone>/<period>.json`, and either every file lands or the previous complete set remains exactly as it was (AD-7). Partial writes are never observable to a reader of `data/briefings/` at any point in time, including mid-write.

2. **Every published Briefing carries the generation timestamp of the cycle that produced it (FR-19).** Given a Briefing is published, when its JSON is inspected, it carries a `generated_at` value equal to the cycle's `started_at` (the timestamp already recorded in `cycle.json` by Story 1.5) — not the wall-clock time publish itself happened to run, since a resumed (phase-two) cycle's publish step can run meaningfully later than collection did, and the generation the reader is being told about is the *cycle's*, not this particular process invocation's.

3. **A cycle that fails at any stage before publish completes leaves the previous Briefing set completely unmodified.** Given a cycle whose collect, dedupe, cluster, rank, or summarize step fails (any of the existing guarded failure paths in `run_cycle`, or a summarize batch that is still pending), when the site is served, every file under `data/briefings/` is byte-identical to what the last successful cycle wrote — no partial Zone, no partial language, no stale-but-touched file, nothing.

4. **A day Period's Briefings are regenerated at least once per day.** Given cycles run on the project's actual schedule (the existing GitHub Actions workflow, Story 1.5), when a day passes, every `data/briefings/<lang>/<zone>/day.json` file has a `generated_at` from within that day. (This AC is satisfied by the mechanism, not by a new test asserting real wall-clock behavior — verified by confirming the scheduled workflow's cadence already meets this, and that nothing in this story's changes could cause a cycle to skip publishing on success.)

5. **Summarize runs once per Output Language per cycle, not once per Zone×Period×Language.** Given a cycle's phase-one run, when it reaches the summarize-submit step, it submits exactly 3 batches (one per `OutputLanguage`), each over the deduplicated union of every qualifying Cluster across all 15 Zones × 3 Periods for that cycle — never 135 separate submissions, and never the same `cluster_id` submitted twice within one language's batch.

## Tasks / Subtasks

- [x] **Task 1: Build the per-cycle, per-Period Cluster pool that Zone ranking reads from** (AC1, AC5)
  - [x] New module `pipeline/stages/briefing_matrix.py` — mirrors this codebase's "one mechanism, one file" convention (`rank.py`, `history.py`): the Period-pool-building and 15-Zone ranking loop is its own tested mechanism, called from `cycle.py` rather than inlined into it. `cycle.py` stays the orchestrator that calls `briefing_matrix`, then `summarize`, then `publish`, in order.
  - [x] In `briefing_matrix.py`, build the qualifying-Cluster pool for each `Period`, fed by `cycle.py`'s already-produced `clusters.jsonl` (not the existing flat `run_rank` call — see Dev Notes on why):
    - `day`: the cycle's own `clusters.jsonl` output (`run_cluster`'s result), used as-is.
    - `week`/`month`: `link_across_days(today_clusters, history_entries, embedding_by_id)` where `history_entries` is passed in by the caller (built from `read_history`) and `embedding_by_id` is built by embedding today's Clusters' representative titles plus reading each history entry's own already-stored `embedding` field (Story 2.7 stored these — no re-embedding of historical entries needed)
  - [x] For each of the 3 Period pools, run `rank_for_zone(pool, zone)` for all 15 `ZONES` (from `pipeline.config`), producing 45 `ZoneRanking` results (15 Zones × 3 Periods) — this is the loop `rank_for_zone`'s own docstring names as deferred work
  - [x] Collect the deduplicated union of every `ZoneRanking.ranked_clusters` cluster (by `cluster_id`) across all 45 results — this union, not the flat `ranked.jsonl` list, is what gets submitted to summarize (AC5). A Cluster selected into multiple Zone/Period Briefings is summarized once.
  - [ ] Decide what happens to the existing flat `run_rank` call: it currently produces `ranked.jsonl`, which Story 3.4's `submit_summarize_fn`/`_resume_cycle` reads via the `ranked_path` recorded in `cycle.json`. This story either repurposes that mechanism to record the *deduplicated union* (writing the union to the same `ranked.jsonl` path, so Story 3.4's resume logic needs no changes) or introduces a parallel path — prefer repurposing; do not build a second resume-state mechanism alongside Story 3.4's existing one. Do not remove `qualifies()`/`rank_clusters()`, which `rank_for_zone` still calls internally — only the *flat, single-Zone* call site in `cycle.py` changes. **(Wired into `cycle.py` as part of Task 2/4 below, since it's inseparable from the per-language submit loop.)**

- [x] **Task 2: Submit and collect summarize per Language, not per combination** (AC5)
  - [x] `run_cycle`'s `language` parameter (singular, Story 3.4) is gone — replaced by a loop over all three `OUTPUT_LANGUAGES` (`pipeline.config`): three separate `submit_summarize_fn` calls per cycle, each against the same deduplicated Cluster union from Task 1, each producing its own batch ID.
  - [x] `cycle.json`'s `summarize_batch` section (single dict, Story 3.4) is now `summarize_batches`, a mapping keyed by language (`{"fr": {...}, "en": {...}, "es": {...}}`). Every language's batch is independently pending/resolved; `_resume_cycle` checks whichever languages remain in the mapping and deletes an entry once its batch collects — an already-resolved language is never re-checked.
  - [x] `_resume_cycle` runs its per-language check in a loop, and only calls `assemble_briefings`/`publish_briefings` once `remaining_batches` is empty (every language resolved) — a partially-resolved cycle returns with `published=False` and is resumed again later.
  - [x] `collect_summarize`'s `clusters` argument is the same deduplicated union every language was submitted with, re-read from the shared `ranked.jsonl` path recorded per-language in `cycle.json` (all three languages point at the identical file).

- [x] **Task 3: Build `pipeline/stages/publish.py`** (AC1, AC2, AC3)
  - [x] `assemble_briefings(zone_rankings, summaries_by_language, generated_at) -> list[BriefingRecord]` — for each of the 135 (language, zone, period) combinations from `pipeline.config.briefing_combinations()`, looks up that Period's `ZoneRanking` for that Zone, attaches each Cluster's per-language `summary` from the shared deduplicated pool, and stamps `generated_at`. Built a new `BriefingRecord` type in `pipeline/domain/__init__.py` (distinct from the existing conceptual `Briefing` dataclass, which names `QualifyingCluster`/`Cluster`/`Event`/`Article` — objects this pipeline has never materialized anywhere; `BriefingRecord` works on the plain dicts every real stage actually produces) with `to_dict`/`from_dict` and a `schema_version` field, mirroring `ArticleRecord`'s existing on-disk-shape pattern.
  - [x] `publish_briefings(briefings, data_root=DEFAULT_DATA_ROOT) -> WrittenPublish` — writes each Briefing to `data/briefings/<lang>/<zone>/<period>.json`, all atomically as one set, via a staging-directory-then-rename pattern: build the complete new tree under `data_root / f".briefings.staging-{uuid}"`, then `Path.rename()` it onto `data/briefings/` only once every file is written — a same-filesystem directory rename, atomic on POSIX. A crash during staging removes the staging directory and re-raises, leaving the live tree untouched; verified directly by a test that raises partway through serialization and confirms the previous published tree survives byte-identical.
  - [x] A crash or exception at any point during staging leaves `data/briefings/` (the live tree) completely untouched — verified by test, not just by inspection.
  - [x] `main()` documents the deviation from the `stage_arg_parser` convention (publish's real input is structured, not a single `--input` file) rather than forcing a mismatched CLI shape.

- [x] **Task 4: Wire publish into `cycle.py`'s resume path** (AC1, AC2, AC3, AC4)
  - [x] `_resume_cycle`, once `remaining_batches` is empty (every language's batch has collected), calls `assemble_briefings` + `publish_briefings` and records `"phase": "published"`, `"published": true` — the terminal state; a fresh `_should_resume` check on the next invocation returns `False` once `published` is `true`.
  - [x] If publish itself fails, the failure degrades per AD-10: a `Failure` is recorded, `record["phase"] = "publish_failed"`, and — critically — `_should_resume` is keyed on `published`, not on whether `summarize_batches` is empty, so a cycle whose batches all resolved but whose publish crashed still resumes on the next invocation, straight to retrying publish, never re-submitting or re-collecting any language's already-resolved batch. Verified by a dedicated regression test (`test_a_publish_failure_is_retried_on_the_next_resume_without_resubmitting`) using a `submit_summarize_fn`/`collect_summarize_fn` that raise `AssertionError` if called on the retry.
  - [x] `CycleResult` gained `published: bool` and `briefings_path: Path | None`, following the existing `summarize_phase: str | None` precedent from Story 3.4.

- [x] **Task 5: Tests**
  - [x] `rank_for_zone`/`link_across_days` integration is exercised end-to-end through `briefing_matrix.py`'s own tests (`build_period_pools` feeding `rank_all_zones`) — no additional `test_rank_stage.py` gap found; both functions' existing isolated tests remain the authority on their own behavior.
  - [x] `tests/test_cycle.py`: a fresh cycle submits exactly 3 batches (one per language, `test_a_fresh_cycle_submits_three_batches_and_stops_without_waiting`), over the same deduplicated Cluster union (`briefing_matrix.dedupe_union`'s own tests cover the no-duplicate-`cluster_id` guarantee directly).
  - [x] `tests/test_cycle.py`: `test_a_partially_resolved_cycle_does_not_publish` — 1 of 3 languages resolved does not publish; `test_a_second_resume_does_not_recheck_an_already_resolved_language` — an already-resolved language's `collect_summarize_fn` is never called again.
  - [x] `tests/test_cycle.py`: `test_a_cycle_where_all_three_languages_collect_publishes` — all 3 resolved reaches the terminal `"published"` phase and writes real files under `data/briefings/`.
  - [x] `tests/test_publish_stage.py`: `test_assembles_exactly_135_briefings`, `test_every_briefing_carries_the_cycles_generated_at_not_wall_clock`, `test_a_cluster_present_in_multiple_zones_is_not_summarized_twice_but_appears_in_both`.
  - [x] `tests/test_publish_stage.py`: `test_a_failure_partway_through_staging_leaves_the_live_tree_untouched` (byte-identical assertion), `test_a_failed_publish_leaves_no_partial_staging_directory_live`.
  - [x] `tests/test_publish_stage.py`: `test_a_second_successful_publish_fully_replaces_the_first`, `test_a_second_publish_removes_a_file_the_new_set_no_longer_needs`.
  - [x] Full-suite regression: `test_cycle.py` fully rewritten for the language-keyed `summarize_batches` schema (mirroring Story 3.4's own precedent of updating every existing call site deliberately). 293/293 tests passing after every change in this story, including a new regression test (`test_a_cluster_missing_from_embedding_by_id_degrades_to_unlinked_not_a_crash`) for a real bug this story's own implementation surfaced: an upstream Cohere embedding failure left a Cluster with no entry in `embedding_by_id`, which crashed `link_across_days` with a `KeyError` instead of degrading (AD-10) — fixed in `briefing_matrix.build_period_pools` by passing such Clusters through unlinked rather than into the linking comparison.

## Dev Notes

### Why the Zone/Period ranking loop reads from `run_cluster`'s output, not the existing flat `run_rank`

`cycle.py` currently (Story 1.5 through 3.4) calls `run_rank(cluster_path, ...)` once, producing a single flat `ranked.jsonl` — this predates any Zone-awareness and was always understood to be a placeholder the real per-Zone loop would replace (see `rank_for_zone`'s own docstring, and Story 2.5's Dev Notes, both cited above). `rank_for_zone` needs the *qualifying* Clusters (it calls `qualifies()`/`_is_relevant_to()` internally per Zone) — it does not want Clusters pre-filtered or pre-capped by a flat, Zone-unaware `run_rank` call, since a Cluster the flat call's top-5 slice would have dropped might still be exactly what a thin Country Zone needs. Feed `rank_for_zone` the cluster stage's full output (before any ranking/selection), one call per Zone per Period pool.

### Why summarize's dedup union, and where it lives

The union across 45 `ZoneRanking.ranked_clusters` results, deduplicated by `cluster_id`, is likely close in size to (but not identical to) what the old flat `run_rank` produced — but is not the same set: a Cluster too thin to make a Zone-agnostic top-5 might still be selected into a specific Country's Briefing, and a Cluster that would have topped the flat ranking might not be relevant to every Zone at all. Do not assume the union equals the flat list; compute it explicitly from the 45 `ZoneRanking`s.

### Why `cycle.json`'s summarize state must become language-keyed, not a bigger single dict

Story 3.4 built `cycle.json`'s `summarize_batch` as one dict because exactly one language was ever submitted. Now three batches exist independently, each potentially resolving at a different time (Claude's Batch API does not guarantee simultaneous completion across separately-submitted batches) — the schema must let one language be `"ended"` while the other two are still `"pending"` in the same `cycle.json`, checked and updated independently on each resumed invocation, without disturbing already-resolved languages' recorded results.

### Why the set-level atomic publish needs a staging-directory swap, not a per-file `write_atomically` loop

Writing 135 files with `write_atomically` one at a time is atomic *per file*, not atomic *across the set* — a crash after file 80 of 135 leaves a `data/briefings/` tree that is neither the old set nor the new one, violating AD-7 directly ("writes the whole set or writes nothing"). The staging-then-swap pattern is the standard fix: nothing under the live `data/briefings/` path is touched until the entire new tree is confirmed complete, at which point one directory-level rename makes the swap atomic (on the same filesystem, which `data_root`-relative staging guarantees).

### Previous Story Intelligence

- Stories 3.2 and 3.4 both contain explicit "this story does not build the assembly loop, that's Story 3.5's job" sections — read both in full before starting; they document exactly which shortcuts were taken (single flat rank call, single hardcoded language) that this story now replaces.
- Story 3.4's `_resume_cycle` function and `cycle.json`'s schema are the direct foundation this story extends to three languages — read `pipeline/stages/cycle.py` in its current (post-3.4) state completely before touching it; do not re-derive the resume mechanism from scratch.
- Single-layer adversarial review (Blind Hunter only) remains the process for this story, per the user's standing cost-reduction decision.

### Project Structure Notes

Files this story creates or modifies:
- `pipeline/stages/briefing_matrix.py` (new) — per-Period Cluster pool building (day vs week/month via `link_across_days`+history), the 15-Zone `rank_for_zone` loop, and the deduplicated-by-`cluster_id` union used for summarize submission
- `pipeline/stages/publish.py` (new) — `assemble_briefings`, `publish_briefings`, `WrittenPublish`, `main()`
- `pipeline/domain/__init__.py` (modified) — a versioned JSON serializer for `Briefing` (`to_dict`/`from_dict` or equivalent, following `ArticleRecord`'s existing pattern)
- `pipeline/stages/cycle.py` (modified) — the Zone×Period pool-building loop after `run_cluster`; the per-language submit/collect loop replacing Story 3.4's single-language calls; `_resume_cycle`'s per-language check and terminal publish call; `cycle.json`'s `summarize_batch` schema becomes language-keyed
- `tests/test_publish_stage.py` (new)
- `tests/test_cycle.py` (modified — language-keyed schema breaks existing Story 3.4 assertions; new tests for partial-language-resume and terminal-publish)
- Possibly `tests/test_rank.py` (only if a real integration gap is found between `link_across_days` and `rank_for_zone`)

### References

- [Source: epics.md#Story 3.5] — acceptance criteria origin (verbatim AC text reproduced above)
- [Source: ARCHITECTURE-SPINE.md#AD-7] — "The publish stage writes a complete Briefing set or writes nothing... Every Briefing carries the generation timestamp of the cycle that produced it," quoted in full above
- [Source: ARCHITECTURE-SPINE.md#AD-12] — publish owns the generation timestamp and cycle identifier; every other field is copied through unchanged
- [Source: ARCHITECTURE-SPINE.md#Structural Seed] — `data/briefings/`, committed; `data/intermediate/`, gitignored; confirms publish (not summarize) is where 135 files land
- [Source: ARCHITECTURE-SPINE.md#Consistency Conventions] — `data/briefings/<lang>/<zone>/<period>.json`, one file per Briefing, schema versioned in `pipeline/domain/`
- [Source: pipeline/stages/rank.py#rank_for_zone] — "Wiring it into a per-cycle loop that runs it for all 15 Zones... is later Epic 3/4 work" — this story is that work
- [Source: pipeline/stages/rank.py#link_across_days] — the week/month cross-day merge, unit-tested but never wired into a stage
- [Source: pipeline/stages/history.py#read_history] — the history-window read this story's week/month pool-building depends on
- [Source: pipeline/config/__init__.py#briefing_combinations] — the exact 135-combination iterator publish's assembly loop should drive from
- [Source: _bmad-output/implementation-artifacts/3-4-split-the-cycle-into-two-resumable-phases.md] — the two-phase resume mechanism this story extends to 3 languages
- [Source: _bmad-output/implementation-artifacts/3-2-generate-every-briefing-in-all-three-output-languages.md] — first story to explicitly defer the assembly loop to 3.5

## Dev Agent Record

### Context Reference

_To be filled by dev-story._

### Debug Log

- Design decision made explicitly with the user before implementation: summarize submits one batch per Output Language (3 per cycle), shared across all 15 Zones × 3 Periods via a deduplicated Cluster union — not one batch per (Zone, Period, Language) combination (which would mean up to 135 submissions and redundant summarization of Clusters selected into multiple Zones).
- Design decision made explicitly with the user: the Zone×Period pool-building and 15-Zone ranking loop live in a new dedicated module (`pipeline/stages/briefing_matrix.py`), not inlined into `cycle.py`, mirroring the existing "one mechanism, one file" convention (`rank.py`, `history.py`).
- Design decision made explicitly with the user: the on-disk `BriefingRecord` serializer works on the plain Cluster dicts every real pipeline stage actually produces, not on the conceptual `Briefing` dataclass's `QualifyingCluster`/`Cluster`/`Event`/`Article` fields — this pipeline has never materialized those richer domain objects anywhere, and building a conversion layer for them would be new complexity with no real consumer.
- Real bug caught by this story's own test suite, not by inspection: an upstream Cohere embedding failure leaves `cluster.py`'s output degraded but present (per AD-10) — such a Cluster has no entry in `embedding_by_id`. `link_across_days` requires every `today_cluster` it receives to have one, and crashed with a `KeyError` instead of degrading. Fixed in `briefing_matrix.build_period_pools` by splitting `today_clusters` into linkable/unlinkable before calling `link_across_days`, passing the unlinkable ones through untouched in every Period's pool.
- Real bug caught before code review, by re-reading my own `_resume_cycle` logic: a publish failure (exception during staging) left `summarize_batches` empty (every language had already resolved), and the original `_read_pending_batches` treated "no pending batches" as "nothing to resume" — meaning a publish crash would silently fall through to a *fresh* cycle on the next invocation, re-submitting and re-collecting batches for data that was already sitting on disk, undoing all prior work instead of simply retrying publish. Fixed by replacing the pending-batches check with `_should_resume`, keyed on `published` rather than on whether `summarize_batches` is empty — a cycle whose batches all resolved but whose publish failed now resumes straight to retrying publish. Covered by `test_a_publish_failure_is_retried_on_the_next_resume_without_resubmitting`, which fails loudly (`AssertionError`) if either `submit_summarize_fn` or `collect_summarize_fn` is called on the retry.

### Completion Notes

All 5 tasks complete, TDD throughout (RED confirmed via `ModuleNotFoundError`/`ImportError`/failing assertions before every new module and every behavior change). 293/293 tests passing (up from 264 at story start).

**Task 1:** New `pipeline/stages/briefing_matrix.py` — `build_period_pools` (day pool unchanged; week/month pools merge today's Clusters with the relevant history window via `link_across_days`, degrading a Cluster with no embedding to "unlinked" rather than crashing), `rank_all_zones` (one `rank_for_zone` call per of the 15 `ZONES`), `dedupe_union` (first-seen-wins collapse by `cluster_id` across all 45 Zone×Period rankings). `cycle.py` now builds this pool/ranking/union once per cycle and writes the union to the existing `ranked.jsonl` path (Story 3.4's resume mechanism needed no schema change there) plus a new `zone_rankings.json` (the per-Zone detail publish needs at assembly time, since the flat union alone can't reconstruct which Clusters belong to which Zone's Briefing).

**Task 2:** `run_cycle` submits 3 batches per cycle (one per `OUTPUT_LANGUAGE`), all against the same deduplicated union. `cycle.json`'s `summarize_batch` (singular, Story 3.4) becomes `summarize_batches` (a language-keyed mapping). `_resume_cycle` checks every still-pending language in a loop, deleting an entry from the mapping once its batch collects; an already-resolved language is never rechecked.

**Task 3:** New `pipeline/stages/publish.py` — `assemble_briefings` builds the 135 `BriefingRecord`s (one per `pipeline.config.briefing_combinations()` triple) by looking up each Period's `ZoneRanking` for that Zone and attaching the Zone-agnostic per-language summary pool. `publish_briefings` writes the whole set atomically via a staging-directory-then-rename pattern: the new tree is built completely under `data_root / f".briefings.staging-{uuid}"`, and only `Path.rename()`d onto the live `data/briefings/` path once every file is confirmed written — a same-filesystem directory rename, atomic on POSIX. A crash during staging removes the staging directory and re-raises, leaving the live tree byte-identical to the previous publish (verified directly by test, not just by inspection). New `BriefingRecord` type in `pipeline/domain/__init__.py`, distinct from the existing `Briefing` dataclass, with `to_dict`/`from_dict` and a `schema_version` field.

**Task 4:** `_resume_cycle` calls `assemble_briefings`+`publish_briefings` once every language's batch has resolved, reaching a terminal `"published"` phase. A publish failure degrades (records a `Failure`, sets `"phase": "publish_failed"`) without discarding the already-collected summaries — the next invocation resumes straight to retrying publish, never re-submitting or re-collecting any language's batch (see Debug Log for the bug this required fixing). `CycleResult` gained `published: bool` and `briefings_path: Path | None`.

**Task 5:** New `tests/test_briefing_matrix.py` (11 tests), `tests/test_briefing_record.py` (5 tests), `tests/test_publish_stage.py` (11 tests). `tests/test_cycle.py` fully rewritten for the language-keyed schema (28 tests, including the publish-retry regression test and the embedding-degrades-to-unlinked regression test).

**Not built in this story:** nothing was deferred — this story completes Epic 3's originally-deferred assembly loop in full, per every prior story's explicit "deferred to 3.5" notes.

### File List

**New:**
- `pipeline/stages/briefing_matrix.py`
- `pipeline/stages/publish.py`
- `tests/test_briefing_matrix.py`
- `tests/test_briefing_record.py`
- `tests/test_publish_stage.py`

**Modified:**
- `pipeline/domain/__init__.py` (added `BriefingRecord`, `_BRIEFING_RECORD_SCHEMA_VERSION`, `_zone_from_dict`; post-review: documented why `discarded_ingested`/`discarded_kept` default to 0)
- `pipeline/stages/cycle.py` (Zone×Period pool-building via `briefing_matrix`; per-language submit/collect loop; `_resume_cycle`'s per-language check, terminal publish call, and publish-retry-safe `_should_resume`; `CycleResult` gained `published`/`briefings_path`; `cycle.json` schema gained `summarize_batches` (renamed from `summarize_batch`), `published`, `briefings_path`; post-review: `_summaries_from_output` now carries whole Cluster dicts, not just `summary`; fixed the fragile `ranked_path` loop variable)
- `pipeline/stages/publish.py` (post-review: `_attach_summary` merges `outbound_url`/`outbound_source` too; removed dead `_ZONE_BY_SLUG`; `WrittenPublish` converted to a frozen dataclass)
- `pipeline/stages/briefing_matrix.py` (post-review: `dedupe_union`'s docstring documents the first-seen-across-Periods trade-off; `_within_window` uses `history.cycle_date` instead of reaching into a private name)
- `pipeline/stages/history.py` (post-review: `_cycle_date` renamed to public `cycle_date`, no behavior change)
- `tests/test_cycle.py` (fully rewritten for the language-keyed schema and the publish step; post-review: added an end-to-end outbound-link regression test)
- `tests/test_publish_stage.py` (post-review: fixture no longer bakes outbound fields into the input, exercising the real merge path; added outbound-link and `main()` regression tests)
- `tests/test_briefing_matrix.py` (post-review: added a test pinning `dedupe_union`'s cross-Period first-seen behavior)
- `tests/test_history_stage.py` (post-review: docstring reference to `_cycle_date` updated to `cycle_date`)

## Post-Review Fixes

Single-layer adversarial review (Blind Hunter) found 10 issues; 6 were genuine defects or worth hardening, fixed here. The rest were accepted trade-offs already deliberate in the design, or out-of-scope.

- **Critical: every published Briefing silently lost its outbound link.** `cycle.py`'s `_summaries_from_output` extracted only `{cluster_id: summary_text}` from a collected `summarized.jsonl`, discarding the `outbound_url`/`outbound_source` fields Story 3.3 attaches per Cluster (FR-14: "a reader always has a genuine Article to click through to"). `publish.py`'s `_attach_summary` then only ever merged a bare `summary` string back onto the ranked-Cluster dict — never the outbound link — so every real Briefing this pipeline could ever publish would have no outbound link at all, defeating FR-14 outright. Masked in the original tests because `test_publish_stage.py`'s Cluster fixture baked `outbound_url`/`outbound_source` directly into the input rather than exercising the summarize-collect merge path. Fixed by changing `_summaries_from_output`/`summaries_by_language` to carry the whole collected-Cluster dict (not just the summary string), and `_attach_summary` to merge every summarize-owned field (`summary`, `outbound_url`, `outbound_source`) explicitly. Regression tests: `test_a_clusters_outbound_link_survives_into_the_published_briefing` (unit, in `test_publish_stage.py`) and `test_a_published_briefing_carries_its_clusters_outbound_link` (end-to-end through `run_cycle`, in `test_cycle.py`).
- **`_resume_cycle`'s `ranked_path` was a fragile shared mutable variable**, reassigned on every loop iteration from whichever language happened to be checked, with the final value returned in `CycleResult.rank_path` by coincidence rather than by design (only correct today because every language shares the same path). Fixed by renaming the loop-local reassignment to `batch_ranked_path`, leaving the outer `ranked_path` (used for the `CycleResult` fallback) untouched by the loop.
- **Dead code removed:** `_ZONE_BY_SLUG` in `publish.py` was defined and never referenced.
- **Style inconsistency fixed:** `WrittenPublish` was a hand-written plain class with a manual `__init__`; every other structured-result type this story touches (`BriefingRecord`, `ZoneRanking`, `CycleResult`, `WrittenRank`, `WrittenSubmission`, `WrittenSummarize`) is a frozen `@dataclass(slots=True)`. Converted for consistency.
- **Layering cleanup:** `briefing_matrix.py`'s `_within_window` reached into `history.py`'s underscore-prefixed `_cycle_date` directly. Renamed to a public `cycle_date` in `history.py` (no behavior change) and imported normally.
- **`main()` in `publish.py` had zero test coverage**, unlike every other stage's CLI entry point. Added `test_main_exits_nonzero_and_explains_it_has_no_standalone_cli_input`.
- **Documented, not "fixed" (deliberate, accepted trade-offs):** `dedupe_union`'s first-seen-wins collapse can keep either an unlinked (day) or linked (week/month) occurrence of the same Cluster depending on iteration order, which can display slightly different counts than the summary text was generated against — expanded `dedupe_union`'s docstring to state this explicitly and added `test_dedupe_union_keeps_the_first_seen_occurrence_across_periods` to pin the current, deterministic behavior rather than leave it an undocumented surprise. `BriefingRecord.discarded_ingested`/`discarded_kept` are never populated by this story (FR-8/Discarded Volume is explicitly Epic 4's display responsibility per the epics doc, not Epic 3's) — documented in the dataclass's own comment so a `0`/`0` default is never mistaken for "nothing was filtered."
- **Rejected as non-issues:** `_embed_for_linking`'s all-or-nothing degrade on an embedding failure mirrors the exact guard pattern already used in `cluster.py`/`history.py` elsewhere in this codebase, not a new gap; lack of concurrency protection on `publish_briefings` against two simultaneous cycle runs, since the architecture is single-writer (one scheduled job) by design, not a redress-worthy gap this story introduced.

297/297 tests passing after fixes (up from 293).

## Change Log

- 2026-08-12: Story created via bmad-create-story. User explicitly decided the summarize fan-out is one batch per Output Language (3 per cycle), shared across all 15 Zones × 3 Periods via a deduplicated Cluster union — not one batch per (Zone, Period, Language) combination — to keep AI cost bounded by distinct-Cluster count rather than Zone count, and to keep the two-phase resumable state at 3 pending batches instead of up to 135.
- 2026-08-12: Implemented via bmad-dev-story. User confirmed two further design decisions mid-implementation: a dedicated `briefing_matrix.py` module for the Zone×Period mechanism (rather than inlining into `cycle.py`), and a dict-based `BriefingRecord` serializer (rather than forcing a conversion into the richer, never-materialized `Briefing`/`QualifyingCluster` domain objects). All 5 tasks complete, TDD throughout. Fixed two real bugs surfaced by this story's own implementation: an embedding-failure `KeyError` crash in the new Zone×Period ranking loop, and a publish-failure resume path that would have silently discarded already-collected summarize work. 293/293 tests passing (up from 264). Status set to review.
- 2026-08-12: Reviewed via bmad-code-review (single-layer Blind Hunter). Found and fixed a critical defect (every published Briefing silently losing its FR-14 outbound link) plus 5 lesser issues (a fragile shared variable, dead code, a style inconsistency, a layering violation, missing CLI test coverage); documented 2 deliberate trade-offs rather than "fixing" them; rejected 2 findings as non-issues consistent with existing codebase patterns. 297/297 tests passing. Status set to done.

- 2026-08-12: Story created via bmad-create-story. User explicitly decided the summarize fan-out is one batch per Output Language (3 per cycle), shared across all 15 Zones × 3 Periods via a deduplicated Cluster union — not one batch per (Zone, Period, Language) combination — to keep AI cost bounded by distinct-Cluster count rather than Zone count, and to keep the two-phase resumable state at 3 pending batches instead of up to 135.
