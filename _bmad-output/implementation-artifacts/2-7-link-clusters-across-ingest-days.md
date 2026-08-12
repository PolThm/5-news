---
baseline_commit: ea07a4b
---

# Story 2.7: Link Clusters across ingest days

Status: done

## Story

As a reader choosing week or month,
I want an ongoing story to appear once rather than once per day,
so that a week's Briefing is five events, not the same event five times.

## A deliberate deviation from the architecture spine's own deferral — read before implementing

The architecture spine explicitly defers this decision: *"Cluster identity across cycles... deliberately not fixed here, because the inspection window should inform it."* No inspection window has happened yet (Story 2.4 already made and documented the same deviation for its threshold; this story makes the analogous deviation for its mechanism). **Decided explicitly, not by default:** implement now, with a mechanism and thresholds reasoned from the pipeline's existing embedding infrastructure rather than observed cross-day data, documented clearly as provisional. Revisit at the first opportunity once several real weeks of `data/history/` output exist to inspect.

## The real architectural problem this story has to solve first

**Cluster identity does not currently survive a cycle.** Every stage's output under `data/intermediate/<stage>/<cycle-id>/` is gitignored except `cycle.json` (see `.gitignore`'s three-line pattern, Story 1.1). A GitHub Actions run is a fresh, ephemeral runner — nothing from yesterday's `clusters.jsonl` exists when today's cycle starts unless it was explicitly committed. Before any "same Event across days" logic can run, there has to be *something on disk, in git* for today's cycle to compare against. This story therefore has two parts, in order: **(1) persist a minimal cross-day record, (2) use it to link.** Skipping straight to part 2 is not possible — there would be nothing to link against.

**What gets persisted, and why it's small.** `data/history/clusters.jsonl` — one line per Cluster per day it was selected by the rank stage (i.e., appeared in a Briefing), committed like `cycle.json` is. Each line carries only what a future day's linking decision needs: `cycle_id` (the day), `cluster_id`, the Cluster's representative title's **embedding vector** (reused from the cluster stage's own Cohere call — never re-embedded), and its `independent_source_count`/`country_count`/`countries`/`origin_country`. This is deliberately NOT the full `clusters.jsonl` (member titles, full article lists) — only enough to (a) recognize a future day's Cluster as the same Event via embedding similarity, and (b) aggregate the Consensus Score across linked days. A 30-day retention is enough for a month Period; do not build unbounded retention or an archival system — that is out of scope (see PRD Open Question 2, explicitly deferred).

## Acceptance Criteria

1. **An Event covered on three consecutive ingest days appears once in a week Briefing, with an aggregated Consensus Score.** When the same real-world Event produced a selected Cluster on each of three consecutive days, the week Briefing shows it as one item, and its Independent Source count is the union across all three days' Independent Sources — not the count from any single day, and not a naive sum (a Source covering the Event on both day 1 and day 2 is still one Independent Source, matching the "one dispatch, one source" principle every dedupe layer in this epic already follows).

2. **A month Briefing never contains two items describing the same Event.** The linking mechanism from AC1 applies at month scope too, over the month's full window.

3. **Day Briefings are completely unaffected.** Cross-day linking does not run for the day Period — its window is a single ingest day, exactly as before this story. This must be true by construction (the linking code is not invoked for day-scoped ranking), not by coincidence of thresholds.

4. **Cross-day identity is a corroborating-evidence match, not identity alone.** Following the pattern every prior Syndication Detection layer in this epic settled on (Story 2.1, 2.3, 2.4): two Clusters from different days are the same Event only if their representative embeddings are close enough — reuse the clique-merge discipline (`pipeline/stages/dedupe.py`'s `_clique_merge`, generalized or reused, not reimplemented) so that transitive chaining across a week's worth of daily Clusters cannot silently fold unrelated Events together.

5. **The persisted history is inspectable and bounded.** `data/history/clusters.jsonl` is a plain JSON Lines file, sorted/atomic-written like every other stage output, retained for a fixed window (30 days) with older entries pruned — not growing without bound.

## Tasks / Subtasks

- [x] **Task 1: Persist a minimal cross-day Cluster history** (AC: 5)
  - [x] Add `pipeline/stages/history.py` (a new small stage, not folded into `rank.py` — it has its own single responsibility: append this cycle's selected Clusters to `data/history/clusters.jsonl` and prune entries older than the retention window)
  - [x] Each history record: `cycle_id`, `cluster_id`, `embedding` (the representative title's vector — thread it through from the cluster stage's existing `embed_titles` call rather than re-embedding; check whether `cluster.py`'s `run_cluster` needs to expose the per-cluster vector it already computed, since today it only keeps the clustering *labels*, not the vectors themselves, past the point of use)
  - [x] `independent_source_count`, `country_count`, `countries`, `origin_country` — the same `Coverage` fields `cluster.py` already produces; do not recompute, pass through
  - [x] Retention: 30 days, pruned on every write (drop any record whose `cycle_id` parses to a date older than 30 days from the current cycle's date)
  - [x] Write via `write_jsonl`/`write_atomically`, matching every other stage's output convention
  - [x] Add `data/history/` to the git-tracked (NOT gitignored) paths — update `.gitignore` if needed, following the exact reasoning already documented there for `cycle.json`'s exception (this file must survive between ephemeral runner instances)

- [x] **Task 2: Cross-day linking for week/month ranking** (AC: 1, 2, 3, 4)
  - [x] Add a `link_across_days` function (co-locate with `pipeline/stages/rank.py`, since this is fundamentally a ranking-time concern — week/month Briefings need linked Clusters before `rank_clusters` runs, not a permanent change to Cluster identity elsewhere in the pipeline)
  - [x] Input: today's selected Clusters (from `cluster.py`'s output) plus `data/history/clusters.jsonl`'s entries within the requested Period's window (7 days for week, 30 for month, computed from the Briefing's reference date)
  - [x] Generalize or directly reuse `dedupe.py`'s `_clique_merge` — do not write a second, subtly-different implementation of the same clique discipline this epic has now built three times (Stories 2.1, 2.3, 2.4). If reuse across modules is awkward (`_clique_merge` currently lives in `pipeline/stages/dedupe.py` and operates on `ArticleGroup`), extract a stage-agnostic version into a shared location (`pipeline/stages/__init__.py` or a new small module) parameterized purely on index-pairs and a qualification predicate, as the existing implementation already mostly is
  - [x] Merged Consensus Score: union of Independent Sources across all linked days' Clusters (not a sum — two days both covering the Event via the same Source is still one Independent Source). This mirrors `cluster.py`'s own `coverage_for_cluster` union logic one level up; do not invent different arithmetic
  - [x] **Do not invoke this function for the day Period at all** (AC3) — wire it only into whatever future orchestration builds week/month Briefings, gated explicitly on `period != Period.DAY`

- [x] **Task 3: Threshold, configurable and documented as provisional** (consistent with Story 2.4's precedent)
  - [x] Add `CROSS_DAY_SIMILARITY_FLOOR` to `pipeline/config/__init__.py`, alongside `REWRITE_SIMILARITY_FLOOR` — same cosine-distance-on-unit-vectors convention
  - [x] Reason about, do not copy, the value: this threshold answers "is this the same ongoing Event, one or more days later" — a looser question than `REWRITE_SIMILARITY_FLOOR`'s "same dispatch, reworded" (an ongoing Event's coverage drifts further in wording over days than a same-day rewrite does) but should still be meaningfully stricter than `cluster.py`'s `_SAME_EVENT_DISTANCE` (which links same-day coverage, where drift is minimal). A reasoned starting value sits between the two existing constants — document the exact reasoning inline, citing this story's own deviation note
  - [x] Cite the deviation note in the constant's comment, exactly as `REWRITE_SIMILARITY_FLOOR` does

- [x] **Task 4: Wire history-writing into the cycle**
  - [x] `pipeline/stages/cycle.py`: add history-writing as a fifth guarded stage, after rank, following the exact established pattern (own try/except, cycle.json written unconditionally regardless) — this is now the fourth time this guard pattern is applied; copy it exactly, do not vary it
  - [x] History writing only records Clusters that were actually *selected* by rank (appeared in a Briefing) — not every Cluster the cluster stage produced. Confirm this against `rank.py`'s output shape before wiring

- [x] **Task 5: Tests**
  - [x] Unit test AC1: three same-Event Clusters across three consecutive `cycle_id`s (constructed embeddings within `CROSS_DAY_SIMILARITY_FLOOR`) link into one, with a unioned Independent Source count
  - [x] Unit test AC2: a month-window linking case with more than 2 days involved
  - [x] Unit test AC3 directly: verify day-Period ranking never calls `link_across_days` (do not just test that thresholds happen to prevent merging — prove the function is never invoked for that path)
  - [x] Unit test AC4's transitive-chaining guard: a non-clique 3-day case (day 1 and day 3 both close to day 2 but not to each other) does not fold all three together — mirror the exact test pattern `test_dedupe_stage.py` already established for this
  - [x] Unit test AC5: retention pruning drops entries older than 30 days; the file stays sorted/atomic-written
  - [x] Unit test the history stage's guard in `cycle.py`: a crash writing history still leaves `cycle.json` written

## Dev Notes

### Why this needs a new persisted artifact, not just new logic

Every previous Epic 2 story added logic that operated entirely within one cycle's data. This is the first story in the epic where the fundamental problem is that the *input data does not exist yet* — a cycle has no way to know what happened on prior days unless something was saved. Do not attempt to solve this by widening the collection window (re-fetching a week of GDELT data every cycle) — the PRD note explicitly rules this out: *"Clusters built per ingest day do not merge on their own... this is real design work, not a wider query window."* The fix is linking already-computed daily Clusters via a small persisted record, not re-deriving them from a larger raw window.

### Reuse the clique discipline — do not reinvent it a fourth time

This epic has now independently discovered, three separate times (Stories 2.1's cluster stage, 2.3's `merge_by_agency`, 2.4's `merge_by_rewrite_detection`), that a coarse similarity signal chains transitively unless every pair in a merged group is required to directly qualify. `dedupe.py`'s `_clique_merge` already generalizes this correctly. Read it before writing anything for this story. If it cannot be reused directly because of the `ArticleGroup`-specific typing, extract the generic part (it already takes `eligible`/`directly_qualifies`/`similarity` as callables — the mechanism has almost no `ArticleGroup`-specific code left in it) rather than copy-pasting the loop body a fourth time.

### Where does `link_across_days` actually get called from?

Note carefully: no orchestration exists yet that builds a real week/month Briefing end-to-end — `rank.py`'s `rank_for_zone` currently takes a flat list of Clusters and has no Period parameter at all (it is designed to be called once per Zone within an already-Period-scoped context, per Story 2.5's Dev Notes). This story adds the *mechanism* (`link_across_days`, the history stage) but should not invent the Period-scoped orchestration loop that doesn't exist yet — that is Epic 3/4 territory (summarize/publish), consistent with how Story 2.5 deliberately deferred wiring `rank_for_zone` into a real per-cycle loop. Wire `link_across_days` so that a future orchestration story can call it (`period != Period.DAY` before ranking), and test it directly as a unit, without inventing the orchestration loop that calls it in production.

### Project Structure Notes

New files:
- `pipeline/stages/history.py`
- `tests/test_history_stage.py`

Files this story modifies:
- `pipeline/stages/cluster.py` (expose per-cluster embedding vectors if not already retained past clustering — check current code before assuming a change is needed)
- `pipeline/stages/rank.py` (add `link_across_days`)
- `pipeline/config/__init__.py` (add `CROSS_DAY_SIMILARITY_FLOOR`)
- `pipeline/stages/cycle.py` (add the guarded history-writing step)
- `pipeline/stages/dedupe.py` (if `_clique_merge` is extracted to a shared location, update its import here)
- `.gitignore` (track `data/history/`)
- `tests/test_rank_stage.py` (new linking tests)

### Previous Story Intelligence

- Every guard added to `cycle.py` so far (dedupe, cluster, rank) has been copied from the previous one without variation, and this discipline has caught a real bug in at least one prior instance. Do the same here — do not "simplify" the pattern for the fifth stage.
- Story 2.4 already established the precedent and the exact language for "deliberate deviation from a documented sequencing intent" — this story's deviation note follows that template directly.
- Story 2.6's review found two independently-reproduced bugs from ordering assumptions (cap-before-slice, fallback-before-cap). Before wiring `link_across_days` anywhere, think through exactly when it needs to run relative to `qualifies()`/`rank_clusters()`/`apply_anti_concentration_cap` — linking changes a Cluster's `independent_source_count`, which is an input to all three.

### References

- [Source: epics.md#Story 2.7] — acceptance criteria origin
- [Source: prd.md FR-18] — cross-day continuity requirement, explicit note that this is "real design work, not a wider query window"
- [Source: ARCHITECTURE-SPINE.md#Deferred — Cluster identity across cycles] — the deferred decision this story now makes, and its own reasoning for having deferred it
- [Source: pipeline/stages/dedupe.py#_clique_merge] — the clique discipline to reuse a fourth time, not reinvent
- [Source: pipeline/stages/cluster.py#Coverage, coverage_for_cluster] — the union arithmetic this story's cross-day aggregation must match exactly
- [Source: _bmad-output/implementation-artifacts/2-4-detect-locally-rewritten-dispatches.md] — the deviation-from-architecture-intent precedent and its documentation template

## Dev Agent Record

### Context Reference

_To be filled by dev-story._

### Debug Log

_To be filled by dev-story._

### Completion Notes

All 5 tasks complete. `pipeline/stages/history.py` (new stage) persists a minimal per-selected-Cluster record to the newly-tracked `data/history/clusters.jsonl` every cycle, with 30-day retention pruning. `link_across_days` in `pipeline/stages/rank.py` merges today's Clusters with historical entries via cosine-distance-on-embeddings, reusing a newly-extracted `clique_partition` helper (moved from `dedupe.py`'s private `_clique_merge` into `pipeline/stages/__init__.py`) — this is now the third and fourth call sites of the same clique discipline this epic has needed (Stories 2.1's cluster stage informally, 2.3's agency matching, 2.4's rewrite detection, now this).

**Scope boundary, explicit:** following Story 2.5's precedent (`rank_for_zone` was built and tested standalone without a real per-cycle Zone-loop orchestration, since summarize/publish don't exist yet to consume it), this story delivers `link_across_days` and `read_history` as tested, standalone mechanisms — neither is wired into `cycle.py`'s actual pipeline flow, since no Period-scoped Briefing orchestration exists yet to call them from. `cycle.py` only gained the history-*writing* step (Task 4); history-*reading*-and-linking is Epic 3/4 territory once week/month Briefing assembly is real. This was already stated as the design intent in the Dev Notes ("Where does link_across_days actually get called from?") before implementation started, not a gap discovered after the fact.

**Post-review fixes (single-layer adversarial pass — Blind Hunter only, per user's cost-reduction decision after Story 2.6's three-layer pass):**

Confirmed correct on inspection, no fix needed: the `_clique_merge` → `clique_partition` extraction is a byte-for-byte faithful, behavior-preserving refactor (diffed directly against the pre-extraction version); the "max, not sum" Independent Source aggregation is implemented exactly as documented with no off-by-one.

**Fixed (real bug): a clique formed entirely from historical entries (no "today" cluster) produced a merged record silently missing `member_titles`.** `history.py`'s persisted records never carry `member_titles` (by design — history stores only the minimal Coverage fields), and `link_across_days` picked `members[0]` as the anchor regardless of shape. A month Briefing where a tracked Event goes uncovered for a day (an entirely ordinary occurrence, not an edge case) would produce exactly this. Fixed by preferring a member that actually carries `member_titles` as anchor, with an explicit empty-list fallback so the field is always present in the output regardless of clique composition.

**Fixed (real risk, not yet reachable in production but latent): `cosine_distance` used `zip(..., strict=True)`, which raises on any dimension mismatch between two embedding vectors.** Since `data/history/clusters.jsonl` is long-lived (30-day retention) and Cohere's model/dimensionality isn't contractually pinned by this codebase, a future vendor model change could leave mismatched-dimension vectors in `embedding_by_id`. Every other embedding boundary in this pipeline (`cluster.py`, `dedupe.py`) degrades rather than crashes on a malformed vector; `link_across_days` had no equivalent guard. Fixed by treating a dimension mismatch as maximal distance (never merges) rather than raising — the same one-sided-error preference (missed link costs less than a crash) every other layer here already follows.

**Fixed (real gap): `_cycle_date` had no error handling around `datetime.strptime`, and `read_history` — which has no caller yet, and therefore no guard around it either — would propagate a raw `ValueError` from a single malformed row into a total read failure.** `data/history/clusters.jsonl` is a long-lived, hand-editable, committed file with no schema enforcement past this module. Fixed by having `_cycle_date` return `None` on anything unparseable rather than raising, with both `read_history` and `append_history`'s retention-pruning loop treating an undatable row as "cannot keep/include," and `append_history` skipping retention entirely (while still appending new records) if the *current* cycle's own `cycle_id` is itself malformed — reachable via the free-form `--cycle-id` CLI argument on a manual/backfill invocation.

**Deferred, not fixed (legitimate, lower priority — noted for whoever wires the orchestration later):** the "max, not sum" aggregation is a deliberately lossy tradeoff, already documented in the docstring, that can make a linked Event's Consensus Score read lower than a single day's standalone coverage would have — worth confirming future display logic doesn't do something surprising with that. `clique_partition`'s anchor-selection (lowest index wins) makes today's-clusters-preferred-over-history an implicit consequence of list ordering (`[*today_clusters, *history_entries]`) rather than an asserted rule — this story's own fix (prefer `member_titles`-carrying members) is now the actual guarantee, making this ordering dependency moot, but it's still worth noting for a future caller of `clique_partition` elsewhere. Retention pruning rewrites the entire history file every cycle even on a no-op day — harmless at current scale, mentioned only because this codebase's stage docstrings elsewhere say intermediate output is "diffed by hand," and a no-op day still producing a commit is a minor departure from that ideal.

After fixes: 220 tests passing (up from 216).

### File List

**New:**
- `pipeline/stages/history.py`
- `tests/test_history_stage.py`

**Modified:**
- `pipeline/stages/__init__.py` (extracted `clique_partition` from `dedupe.py`'s private `_clique_merge`)
- `pipeline/stages/dedupe.py` (`_clique_merge` now delegates to the shared `clique_partition`; no behavior change)
- `pipeline/stages/rank.py` (added `link_across_days`)
- `pipeline/config/__init__.py` (added `CROSS_DAY_SIMILARITY_FLOOR`)
- `pipeline/stages/cycle.py` (added guarded history-writing step, fifth stage)
- `.gitignore` (explicit note on why `data/history/` is intentionally tracked)
- `data/history/.gitkeep` (new, so the directory survives a fresh clone)
- `tests/test_rank_stage.py`, `tests/test_cycle.py` (new tests)

## Change Log

- 2026-08-12: Story created via bmad-create-story, seventh and final story of Epic 2. User explicitly decided to implement cross-day Cluster identity now, with a reasoned (not observed-data-calibrated) mechanism and threshold, following the same deviation pattern Story 2.4 established for the same underlying reason (no real cycle history exists yet to calibrate against).
- 2026-08-12: Implemented via bmad-dev-story. All tasks complete, 216/216 tests passing. Status set to review.
- 2026-08-12: Reviewed via bmad-code-review (single-layer adversarial pass, per user's explicit cost-reduction decision). Confirmed the `clique_partition` extraction and the "max, not sum" aggregation both correct. Fixed 3 real findings: missing `member_titles` on a history-only clique, an uncaught dimension-mismatch crash risk, and no error handling around cycle-id parsing for a long-lived, hand-editable data file. 220/220 tests passing. Status set to done.
