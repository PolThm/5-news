---
baseline_commit: 3951028
---

# Story 2.4: Detect locally rewritten dispatches

Status: done

## Story

As the developer,
I want a rewritten dispatch recognized as the same underlying report,
so that the displayed Consensus Score reflects independent reporting rather than syndication.

## A deliberate deviation from the Build Order — read before implementing

PRD §4.2 and the Build Order (§10) are explicit: rewrite detection is "the third and hardest Syndication Detection layer," and the brief calls for **inspecting real pipeline output after layer 1 before building layer 3** — the intent being that this layer's similarity threshold should be calibrated against observed data, not guessed.

**No real cycle has run yet.** The scheduled GitHub Actions workflow (`collect.yml`) has not fired against production data at the time this story is written — Epic 1 and Epic 2's stories were all built and reviewed against constructed test fixtures, not observed daily output. Building this layer now means choosing a similarity threshold from reasoning alone, exactly what the Build Order's sequencing was meant to avoid.

**Decided explicitly (not a default, not an oversight):** proceed anyway, with a threshold chosen from reasoning about the embedding space rather than observed data, and documented clearly as provisional. This is a deliberate acceptance of the risk the Build Order was written to prevent — revisit this threshold against real cycle output at the first opportunity (recommended: as part of Story 2.7 or a dedicated calibration pass once several days of real `data/intermediate/dedupe/` output exist to inspect). Do not treat the threshold chosen here as validated; treat it as a starting hypothesis.

## Why this layer is more dangerous than the ones before it

Layer 1 (Story 1.4, title normalization) and layer 2 (Story 2.3, agency attribution) both require a second corroborating signal beyond similarity before merging — layer 2 explicitly learned this lesson the hard way (three independent adversarial reviewers converged on the same transitive-chaining bug when title similarity was the only signal available for edge cases). **This layer has no second signal.** Two Articles that rewrite the same dispatch under different wording, by definition, share no exact title, no shared normalized title, and (unless the same outlet also happens to expose wire attribution, which a locally-rewritten piece by definition does not) no `wire_agency` either. Semantic similarity via embeddings is the *only* signal this layer has to work with, which makes the threshold choice higher-stakes here than in either prior layer, not lower.

This asymmetry shapes the whole design: **the threshold must be strict enough that a false merge (collapsing two genuinely independent reports into one) is much rarer than a missed merge (leaving a real rewrite pair uncollapsed).** The layer explicitly errs toward under-collapsing, exactly as dedupe's module docstring already states as this stage's standing philosophy. A rewrite pair left uncollapsed costs one inflated count on one Cluster on one day; a false merge of independent reporting corrupts the exact number the whole product exists to make trustworthy.

## Acceptance Criteria

1. **Two rewritten-dispatch Articles contribute 1 to the Independent Source count, not 2.** When two Articles land in different dedupe groups (title normalization did not merge them) but their titles are semantically close enough — per the embedding-based check this story adds — to plausibly rewrite the same underlying dispatch, they are merged into one group, matching Story 1.4/2.3's existing "one dispatch, one source" semantics.

2. **Two independently-reported Articles about the same Event are NOT collapsed.** Two Articles that are both genuinely original reporting of the same real-world Event (the case Story 2.1's cluster stage exists to recognize as one Event while still counting each as an Independent Source) must not be merged by this layer — that would incorrectly zero out real, independent coverage. This is the central risk this story exists to manage; the acceptance test for this AC must include a constructed near-miss case, not just an obviously-unrelated pair.

3. **Thresholds are configurable, not hardcoded.** The similarity threshold(s) this layer uses live in `pipeline/config/`, alongside `MIN_INDEPENDENT_SOURCES`/`MIN_COUNTRIES`/`MAX_SELECTED_CLUSTERS` (Story 2.2), so a future recalibration against real observed data (per the deviation note above) is a config edit, not a code change.

4. **The embedding call is isolated and degrades gracefully.** This layer reuses the existing Cohere adapter (`pipeline/adapters/cohere_embed.py`, Story 2.1) rather than adding a second vendor integration. On an embedding failure, this layer's merge is skipped for that cycle (falls back to layer 1+2's output unchanged) rather than crashing the cycle — consistent with the cluster stage's existing degrade behavior (AD-10).

5. **The change is inspectable, following the Story 2.3 pattern.** A group formed by this layer's rewrite-detection merge carries a distinguishable `formed_by` value (`"rewrite"`) alongside the existing `"title"`/`"agency"` values, so its effect on `groups.jsonl` is diffable against a cycle that predates this story.

## Tasks / Subtasks

- [x] **Task 1: Configurable threshold** (AC: 3)
  - [x] Add `REWRITE_SIMILARITY_FLOOR` to `pipeline/config/__init__.py`, alongside the Story 2.2 ranking thresholds — a cosine-distance-on-unit-vectors value, following the same convention as `pipeline/stages/cluster.py`'s `_SAME_EVENT_DISTANCE`
  - [x] Set it **stricter** (a smaller distance / higher required similarity) than `cluster.py`'s `_SAME_EVENT_DISTANCE = 0.4` — that constant answers "is this plausibly the same real-world Event" (a looser question layer 3 must not reuse), while this layer answers "is this plausibly the same *dispatch*, reworded" (a narrower claim). Reasoned starting value: `0.25` (cosine similarity ≈ 0.97 via the same d² = 2 - 2c relationship documented in `cluster.py`) — document the reasoning inline as provisional per this story's deviation note, not as a validated constant
  - [x] Add a code comment at the constant's definition citing this story's "deviation from the Build Order" note, so a future reader immediately understands this value needs recalibration against real data, not just a passing familiarity with the code

- [x] **Task 2: Rewrite-detection merge in dedupe** (AC: 1, 2, 5)
  - [x] `pipeline/stages/dedupe.py`: add a `merge_by_rewrite_detection` function, structurally parallel to Story 2.3's `merge_by_agency` — same clique-based merge discipline (every pair in a merged group must directly satisfy the threshold; no fixed-anchor or connected-components chaining, per the lesson Story 2.3's review took three independent reviewers to establish)
  - [x] This layer runs on groups that survived layers 1 and 2 unmerged (chain it after `merge_by_agency` in `run_dedupe`, mirroring how `merge_by_agency` runs after `group_by_title`)
  - [x] The comparison signal is **cosine distance between Cohere embeddings of each group's representative title** — reuse `pipeline.adapters.cohere_embed.embed_titles`, exactly as `pipeline/stages/cluster.py` does; do not add a second embedding pathway
  - [x] Apply the same title-length floor discipline Story 2.3 established (`_AGENCY_MERGE_MIN_TITLE_LENGTH`, or a layer-appropriate equivalent) if short-title instability is a plausible risk for this signal too — verify empirically before deciding whether it applies here (embedding-based semantic similarity may or may not share `SequenceMatcher`'s specific short-string weakness; do not assume it does without checking)
  - [x] Groups already merged by `merge_by_agency` (`formed_by == "agency"`) are still eligible to merge further via rewrite detection with an unattributed group — the layers compose, they do not each only see their own untouched output

- [x] **Task 3: Failure handling** (AC: 4)
  - [x] If `embed_titles` returns any failures, this layer's merge pass is skipped entirely for the cycle — output is layers 1+2's result, unchanged, with the shortfall recorded in dedupe's existing metadata output (extend the `{stage}.json` shape, following `cluster.py`'s degrade-recording pattern)
  - [x] This does not change `run_dedupe`'s signature in a way that breaks `run_cycle`'s existing call site if avoidable — check `pipeline/stages/cycle.py`'s guard pattern before deciding whether `run_dedupe` needs a new `embed` parameter (cluster.py's `run_cluster` already takes one; dedupe.py currently does not)

- [x] **Task 4: Tests**
  - [x] Unit test AC1: two Articles with different titles, embeddings within the configured threshold, merge into one group
  - [x] Unit test AC2 with a genuine near-miss case: two Articles independently covering the same real-world Event (both original reporting, not a rewrite of one dispatch) whose titles are topically related but not a rewrite of each other — verify they do NOT merge. This is the story's central risk; do not skip or weaken this test to make it pass easily
  - [x] Unit test the clique discipline: construct a 3-group non-clique case (mirroring Story 2.3's `test_transitive_chaining_does_not_fold_a_non_clique_triple_together`, mocking the embedding/distance function directly rather than hunting for real text with the right property) and confirm no false chaining
  - [x] Unit test AC4: an embedding failure leaves dedupe's output as layers 1+2 produced it, with no crash and the shortfall recorded
  - [x] Unit test AC5: a group formed by this layer carries `formed_by == "rewrite"`
  - [x] Unit test composition: a group already merged by `merge_by_agency` can still merge further via this layer

## Dev Notes

### Reusing Story 2.1's Cohere infrastructure, not duplicating it

`pipeline/adapters/cohere_embed.py`'s `embed_titles` and `pipeline/stages/cluster.py`'s cosine-distance-via-L2-normalization pattern already exist and are tested. This story's implementation should read `cluster.py` in full before writing anything — the `_vectors_are_well_formed` guard, the `normalize(..., copy=True)` + `pdist`/`squareform` pattern, and the connected-components-was-insufficient lesson (Story 2.1's own review found single-linkage chaining there too, fixed the same way Story 2.3 later had to fix it again) are all directly relevant prior art. Do not re-derive any of this independently.

### Why this threshold must be stricter than cluster.py's

`cluster.py`'s `_SAME_EVENT_DISTANCE = 0.4` (cosine similarity ≈ 0.92) answers "are these two dedupe groups' representative titles describing the same real-world happening" — a question where two genuinely different Independent Sources covering the same Event is the *desired* outcome (that is what Consensus Score measures). This story's threshold answers a narrower question: "is this the same *dispatch*, merely reworded" — where the desired outcome is the opposite: two genuinely different Sources' independent original reporting on the same Event must NOT collapse, even though their titles will often be quite similar precisely because they describe the same happening. Reusing `_SAME_EVENT_DISTANCE` here would be a real bug, not a simplification — it would answer the wrong question and systematically undercounts genuine multi-source coverage. This is exactly the danger the "more dangerous than the layers before it" section above is about.

### Threshold value is a hypothesis, not a fact — say so in the code

Per this story's central deviation from the Build Order, `REWRITE_SIMILARITY_FLOOR`'s value is reasoned, not measured. Write the config comment and this story's Completion Notes to make that unmistakable to whoever reads them next — including future-you. If a future cycle's inspection shows this threshold merging things it shouldn't (or missing things it should catch), that is not evidence the implementation is buggy; it is the expected, foreseen outcome of building this layer before the Build Order's prescribed inspection window closed, and the fix is a config value change, not a re-architecture.

### Project Structure Notes

New: nothing — no new files. Additive to existing modules, following Story 2.3's shape exactly.

Files this story modifies:
- `pipeline/config/__init__.py` (add `REWRITE_SIMILARITY_FLOOR`)
- `pipeline/stages/dedupe.py` (add `merge_by_rewrite_detection`, wire into `run_dedupe`, possibly add an `embed` parameter to `run_dedupe`/`run_cluster`'s call site in `cycle.py`)
- `pipeline/stages/cycle.py` (if `run_dedupe` gains an `embed` parameter, thread it through from the same `embed` parameter `run_cycle` already accepts for the cluster stage — do not add a second, separately-injected embedding function)
- `tests/test_dedupe_stage.py` (new tests, following Story 2.3's patterns directly)

### Previous Story Intelligence (Stories 2.1 and 2.3)

- Every Epic 2 story so far has had its most serious bug caught by adversarial review, not by the implementer, and the pattern has been remarkably consistent: a coarse similarity signal, given the chance, will chain transitively and merge things it shouldn't, unless the merge discipline explicitly requires every pair (not just adjacent ones) to independently qualify. Build the clique discipline into this story's `merge_by_rewrite_detection` from the start — do not write the naive fixed-anchor version first and wait for a reviewer to catch it a fourth time.
- Story 2.1's `_vectors_are_well_formed` guard (ragged vectors, NaN/Inf, all-zero) is directly relevant if this layer calls `embed_titles` on titles that could plausibly repeat this failure mode — check whether it's already sufficient or needs a story-2.4-specific variant.
- `write_jsonl`/`write_atomically` remain the only sanctioned way to write stage output.

### References

- [Source: epics.md#Story 2.4] — acceptance criteria origin
- [Source: prd.md §4.2, §10] — Build Order sequencing intent (deliberately deviated from here — see top of this document)
- [Source: pipeline/stages/cluster.py] — embedding/distance pattern this story reuses
- [Source: pipeline/adapters/cohere_embed.py] — the adapter this story calls, not duplicates
- [Source: _bmad-output/implementation-artifacts/2-3-detect-wire-copy-by-attribution-metadata.md] — the clique-merge discipline this story must replicate from the start, and the false-merge lesson three independent reviewers took to establish there

## Dev Agent Record

### Context Reference

_To be filled by dev-story._

### Debug Log

_To be filled by dev-story._

### Completion Notes

All 4 tasks complete. 5 new tests added for rewrite detection (close-embedding merge, independent-reporting non-merge, layer composition with a prior agency merge, embedding-failure degrade, and a mocked non-clique triple); full suite is 178 tests, all green. `ruff check` and `ruff format --check` both pass. Boundary check passes.

**Refactoring beyond the story's literal scope, done deliberately:** extracted `_clique_merge` as a shared function used by both `merge_by_agency` (Story 2.3) and this story's `merge_by_rewrite_detection`, rather than duplicating the clique-construction logic a second time. The clique discipline itself — every pair in a merged group must directly qualify, never inferred transitively — took three independent adversarial reviewers to establish correctly for Story 2.3; duplicating that logic by hand for this story risked reintroducing a subtly different (and possibly buggy) variant. Verified the refactor didn't change `merge_by_agency`'s behavior by running its existing test suite unmodified before writing any new code.

**Short-title floor decision:** the story's Task 2 asked to verify empirically whether `SequenceMatcher`'s short-string instability (found during Story 2.3's review: `"un dead"` vs. `"un lead"` scoring 0.857) also applies to embedding-based cosine similarity, rather than assuming it does. No live Cohere call is available in this environment to test directly, so this is a reasoned decision, documented as such: `SequenceMatcher` is a character-overlap algorithm, and its short-string weakness is structural to comparing character sequences — semantic embeddings are not built the same way and are not expected to share that specific failure mode. No length floor was added to `merge_by_rewrite_detection`. This reasoning should be revisited against real embedding output at the same time the threshold itself gets recalibrated (see the story's own deviation note).

**`run_dedupe` gained an `embed` parameter**, defaulting to the real `embed_titles` (matching the existing pattern for `collect`/`cluster`). All pre-existing dedupe tests (Story 1.4, Story 2.3) were updated to pass a stub that always reports failure — cheap, no network attempt, and correct for tests that only exercise layers 1-2. `pipeline/stages/cycle.py`'s `run_cycle` threads its existing `embed` parameter through to `run_dedupe` as well as `run_cluster`, so both embedding-consuming stages share one injection point rather than each taking their own.

### File List

**Modified (no new files):**
- `pipeline/config/__init__.py` (added `REWRITE_SIMILARITY_FLOOR`)
- `pipeline/stages/dedupe.py` (extracted `_clique_merge`, refactored `merge_by_agency` onto it, added `_vectors_are_well_formed`, `merge_by_rewrite_detection`; `run_dedupe` gained an `embed` parameter and now chains all three layers)
- `pipeline/stages/cycle.py` (threaded the existing `embed` parameter through to `run_dedupe`)
- `pyproject.toml`, `uv.lock` (declared `scipy` explicitly — was already a transitive dependency via scikit-learn, used directly by both `cluster.py` and now `dedupe.py`)
- `tests/test_dedupe_stage.py` (added a `_no_embed` stub to every pre-existing `run_dedupe` call; new rewrite-detection tests)

## Post-Review Fixes (bmad-code-review, 3-layer adversarial pass)

**Fixed (high severity, Blind Hunter + Acceptance Auditor independently): the test meant to prove the anti-chaining fix worked did not actually test chaining.** `test_transitive_chaining_does_not_fold_a_non_clique_triple_together_via_embeddings` used vectors where only one of three pairs (A-B) qualified at all — B-C and A-C both sat at cosine distance ~1.0, nowhere near the 0.25 floor. There was no chain to exploit, so the test would have passed identically against the old, buggy fixed-anchor algorithm the clique discipline exists to replace. This is precisely the "reviewer must construct a genuine chain, not just claim to" lesson Story 2.3 took three independent reviewers to establish, and it slipped through here in the analogous test for this story's own independent call site into `_clique_merge`. **Fixed** by reconstructing the vectors at controlled angular separation (0°, 35°, 70° on the unit circle), producing real cosine distances of A-B ≈ 0.18, B-C ≈ 0.18 (both under the 0.25 floor), A-C ≈ 0.66 (over it) — a genuine non-clique chain. Verified this scenario would in fact expose a connected-components-style bug (A-B and B-C edges alone would incorrectly connect all three) while the clique-based implementation correctly produces `{A,B}, {C}`.

**Fixed (medium, Blind Hunter): a bare `rewrite_detection_degraded: bool` collapsed three distinct failure modes into one flag**, losing the detail `cluster.py` already records for the same cases (embed call failure vs. malformed response vs. vector-count mismatch). Given this is the layer the story itself calls out as most in need of scrutiny, losing that detail was a real observability regression. Changed `merge_by_rewrite_detection`'s `return_degraded` output from `bool` to `str | None` — `None` when layer 3 ran normally, otherwise the specific reason. `run_dedupe`'s metadata field is now `rewrite_detection_degraded: str | None` instead of a boolean.

**Fixed (minor, Blind Hunter): `directly_qualifies` recomputed the same pair's cosine distance a second, independent way** rather than reusing the value `cosine_similarity` already computed — inconsistent with `merge_by_agency`'s pattern and needlessly doubling the distance computations. Factored out a shared `cosine_distance` helper both closures now call.

**Fixed (minor, Edge Case Hunter + Blind Hunter, defensive not evidence-based): no title-length floor for rewrite detection**, unlike `merge_by_agency`'s established floor. The story's own Dev Notes reasoned this was probably unnecessary (embeddings aren't character-overlap algorithms), but that reasoning was never verified against real embedding output. Given this layer has zero corroborating signal, added `_REWRITE_MERGE_MIN_TITLE_LENGTH` (reusing the same 20-character value as layer 2) as a zero-cost precaution, documented explicitly as defensive rather than evidence-based.

**Fixed (minor, Blind Hunter): `scipy` was an undeclared transitive dependency** (riding in via scikit-learn), used directly by both `cluster.py` (pre-existing) and now `dedupe.py`. Declared explicitly in `pyproject.toml` and regenerated `uv.lock`.

**Fixed (test coverage gaps, all three reviewers): added tests for** a single-group input (no pairs to compare, embed still called), the exact `REWRITE_SIMILARITY_FLOOR` boundary (confirmed `<=` is inclusive, verified via a vector pair constructed at exactly that cosine distance), and a true end-to-end `run_dedupe` call producing a `formed_by == "rewrite"` group written to `groups.jsonl` on disk (the prior test suite only ever exercised `merge_by_rewrite_detection` directly or used an always-failing embed stub through `run_dedupe`, so AC5's literal on-disk-inspectability claim was previously unverified).

**Deferred, not fixed (legitimate, lower priority):** `formed_by` provenance is lossy across a 3-layer chain — a group tagged `"agency"` that later merges again via rewrite detection becomes `"rewrite"`, losing the intermediate agency evidence from the on-disk record. AC5 only requires a distinguishable value for the layer that formed the *final* group, which this satisfies, but a future story wanting full provenance history would need a different data shape (e.g. a list of contributing mechanisms rather than one string). `_vectors_are_well_formed` remains duplicated between `cluster.py` and `dedupe.py` rather than sharing one definition — the layering rationale (cluster runs after dedupe; importing forward would invert stage order) is sound, but there is still no automated check keeping the two copies in sync; noted explicitly in both docstrings for now.

After fixes: 182 tests passing (up from 178).

## Change Log

- 2026-08-12: Story created via bmad-create-story, fourth story of Epic 2. User explicitly decided to proceed with a reasoned-not-measured threshold rather than defer this story until real cycle output exists to calibrate against, accepting the risk the Build Order's sequencing was designed to avoid — see top-of-document deviation note.
- 2026-08-12: Implemented via bmad-dev-story. All tasks complete, 178/178 tests passing. Status set to review.
- 2026-08-12: Reviewed via bmad-code-review (3-layer adversarial). Critical finding: the anti-chaining test didn't test chaining — reconstructed with a genuine non-clique scenario and verified it would catch a connected-components-style regression. Four additional findings fixed (lossy degrade detail, redundant distance computation, missing length floor, undeclared scipy dependency). 182/182 tests passing. Status set to done.
