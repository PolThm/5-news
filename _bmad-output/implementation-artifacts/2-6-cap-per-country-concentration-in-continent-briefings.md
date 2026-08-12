---
baseline_commit: e83a135
---

# Story 2.6: Cap per-country concentration in Continent Briefings

Status: done

## Story

As a reader selecting a continent,
I want no single country to dominate the list,
so that "Africa" does not mean "Nigeria" and the continental selector keeps its meaning.

## A definition this story must settle first: what is a Cluster's "origin country"?

FR-17's exact wording: "Where more than 2 Qualifying Clusters for a Continent **originate in one country**, only the 2 highest-ranked are included." A Cluster (Story 2.1) can span multiple countries — Story 2.5 added a `countries` list precisely because cross-language merging means one Cluster's coverage can genuinely touch several countries at once (e.g. `countries: ["france", "germany"]`).

**Decided explicitly (user confirmed):** a Cluster's origin country is the `source_country` of its earliest-published constituent dedupe group — the same "earliest publisher defines origin" principle already established at the dedupe-group level (`ArticleGroup.origin_country`, Story 1.4/2.1: "where this dispatch originated: the earliest publisher's country"). Applied one level up: a Cluster's origin is where the Event was *first reported*, regardless of how many other countries later covered it. This keeps "origin" a single, well-defined value per Cluster (never a set), which is what a per-country *cap* needs — capping against a set of origins per Cluster would let one Cluster consume multiple countries' quotas simultaneously, which is not what "at most 2 items from the same country" means to a reader looking at a list.

This is a new concept, distinct from Story 2.5's `countries` (everywhere a Cluster's coverage touches, used for Zone *relevance*) and distinct from `country_count` (Story 1.4's coverage-breadth measure, used for the *qualifying floor*). Do not conflate the three — each answers a different question and this epic has twice already paid the cost of conflating similar-sounding country concepts.

## Acceptance Criteria

1. **A Continent Briefing includes at most 2 Clusters originating in the same country.** Given a target Continent Zone with more than 2 qualifying, relevant Clusters originating in one country, only the 2 highest-ranked (by Story 2.2's existing ordering) from that country are included; Clusters ranked lower from that same country are excluded and the next-ranked qualifying Clusters from *other* countries take the freed places instead — the total selected count (up to `MAX_SELECTED_CLUSTERS`) is unaffected by the cap, only *which* Clusters fill it.

2. **A World Briefing is not subject to this cap.** Per FR-17's explicit consequence and the PRD's Open Question 5 (flagged as unresolved and to be watched during the inspection window) — implement the World exemption as written now; do not attempt to resolve the open question itself, and do not apply the cap speculatively to World "just in case."

3. **The cap only ever removes Clusters that were already going to be included; it never adds padding.** If fewer than `MAX_SELECTED_CLUSTERS` Clusters qualify in total, the cap can only shrink the list further (by excluding an over-represented country's excess), never pad it back up — consistent with FR-4's existing never-pad rule.

## Tasks / Subtasks

- [x] **Task 1: Cluster-level `origin_country`** (the definition above)
  - [x] `pipeline/stages/cluster.py`: add `origin_country: str` to `Coverage`, computed as the `source_country` of the member group with the earliest `published_at` (parse and compare, following the same tiebreak convention `dedupe.py`'s `ArticleGroup.representative` already uses — earliest `published_at`, then `url` for a stable tiebreak, if two groups within a Cluster ever share an identical timestamp)
  - [x] Add `"origin_country"` to each Cluster's `clusters_out.append({...})` output dict in `run_cluster`, alongside the existing `countries`/`country_count`
  - [x] Verify: a Cluster's `origin_country` is always a member of its own `countries` list (it cannot be a country the Cluster has no coverage from)

- [x] **Task 2: The cap itself** (AC: 1, 3)
  - [x] `pipeline/stages/rank.py`: add a function (e.g. `apply_anti_concentration_cap(ranked: list[dict]) -> list[dict]`) that, given an already-ordered list of qualifying Clusters, walks it in rank order and keeps at most `MAX_PER_COUNTRY` (new config constant, see Task 3) Clusters per `origin_country`, dropping any beyond that per-country limit while preserving the relative order of everything kept
  - [x] Apply this cap **before** the `MAX_SELECTED_CLUSTERS` top-5 slice in `_rank_for_zone` (Story 2.5), and only when `serving_zone.kind == ZoneKind.CONTINENT` — capping before the final slice is what lets a 6th-ranked Cluster from an under-represented country take a freed slot (AC1); capping after the slice would just shrink the Briefing below 5 items without backfilling, which is not what "the next-ranked Clusters... take the remaining places" describes
  - [x] Do **not** apply the cap when `serving_zone.kind` is `WORLD` or `COUNTRY` (AC2 — World is explicit; a Country Zone's own Briefing was never in scope for this cap either, since the rule is stated as "a Continent Briefing," not implicitly extended to Countries)

- [x] **Task 3: Configurable cap value**
  - [x] Add `MAX_PER_COUNTRY` to `pipeline/config/__init__.py` alongside the other Story 2.2/2.5 thresholds, value `2` per FR-17's literal "at most 2 items from the same country"

- [x] **Task 4: Tests**
  - [x] Unit test `origin_country`: a Cluster whose earliest member is French and whose later member is German gets `origin_country == "france"`, even though `countries` includes both
  - [x] Unit test the invariant: `origin_country` is always in `countries`
  - [x] Unit test AC1 directly: 4 qualifying, relevant Clusters for a Continent, 3 from the same country ranked 1st/2nd/3rd and 1 from another country ranked 4th — after the cap, the 3rd-ranked (excess) Cluster from the over-represented country is dropped and the 4th-ranked Cluster from the other country is included instead, filling the freed slot
  - [x] Unit test AC2: the identical over-concentrated scenario, requested against `world` instead of a Continent — the cap does not apply, all qualifying Clusters (up to `MAX_SELECTED_CLUSTERS`) are included regardless of country concentration
  - [x] Unit test AC3: fewer than 5 total qualifying Clusters, with an over-represented country among them — confirm the cap only removes the excess, never pads the result back toward 5
  - [x] Unit test the cap-before-cap-slice ordering explicitly: construct a case where, without backfilling, the Briefing would end up with fewer than 5 items even though a 6th-ranked Cluster from another country exists and should fill the freed slot
  - [x] Test that a Country Zone request (already covered structurally by Story 2.5, but confirm explicitly) is never subject to this cap

## Dev Notes

### Why cap-then-slice, not slice-then-cap

Capping after the top-5 slice would be the "obvious" but wrong order: given 3 Clusters from France ranked 1-2-3 and 2 Clusters from Germany ranked 4-5, slicing to 5 first and *then* capping France to 2 would just remove the 3rd-place French Cluster and leave a 4-item Briefing — silently violating FR-4's "never padded" framing in the opposite direction (a Briefing that could have had 5 items ends up with 4 for no reason the reader can see). FR-17's own wording is explicit that excluded Clusters' places are backfilled by "the next-ranked Clusters from other countries" — that backfill is only possible if the cap runs on the full ranked list before the final selection-count slice, not after it.

### Reuse Story 2.5's Zone-kind branching, do not duplicate it

`pipeline/stages/rank.py`'s `_rank_for_zone` already branches on `serving_zone.kind` for World's relevance rule (Story 2.5). Add the cap's `kind == ZoneKind.CONTINENT` check in the same function, near the existing `MAX_SELECTED_CLUSTERS` slice — do not create a second, parallel Zone-kind dispatch elsewhere.

### `origin_country` vs `countries` vs `country_count` — do not conflate

This epic has a real, demonstrated failure pattern (three near-identical-sounding metrics computed slightly differently in different stages, most memorably Story 1.4's two-round country-count correction and Story 2.1's `origin_country`-at-the-dedupe-group-level naming). Before writing any code, be explicit about which of the three concepts a given piece of logic needs:
- `country_count` (Story 1.4/2.1): how many distinct countries covered this Cluster — feeds the qualifying floor and FR-6's tiebreak.
- `countries` (Story 2.5): the actual set of countries covered — feeds Zone *relevance* (is this Cluster part of this Zone's Briefing at all).
- `origin_country` (this story): the single country where the Cluster's coverage *began* — feeds the anti-concentration *cap* (how many Briefing slots can one country's stories consume).

### Project Structure Notes

Files this story modifies:
- `pipeline/stages/cluster.py` (add `origin_country` to `Coverage` and cluster output)
- `pipeline/stages/rank.py` (add `apply_anti_concentration_cap`, wire it into `_rank_for_zone`)
- `pipeline/config/__init__.py` (add `MAX_PER_COUNTRY`)
- `tests/test_cluster_stage.py`, `tests/test_rank_stage.py` (new tests)

No new files.

### Previous Story Intelligence

- Story 2.5 was the first story in this epic where a 3-layer adversarial review found no hard AC violations — its `_rank_for_zone`/`_is_relevant_to`/`ZoneRanking` shapes are the direct foundation this story builds on. Read that story's final code in full before starting; do not reintroduce a parallel Zone-scoping mechanism.
- The recurring epic-wide lesson (Stories 2.1, 2.3, 2.4) is that a merge/filter operating on a coarse or ambiguous signal produces silent, hard-to-notice correctness bugs. This story's central risk is the opposite shape again: an *exclusion* bug (wrongly dropping a Cluster that should have counted toward a different country's quota, or wrongly keeping one that should have been capped) rather than a false merge — but the lesson to test the boundary explicitly still applies.

### References

- [Source: prd.md FR-17] — the exact cap rule and the World-exemption assumption tag
- [Source: prd.md Open Question 5] — the unresolved question about extending the cap to World (out of scope to resolve here)
- [Source: epics.md#Story 2.6] — acceptance criteria origin
- [Source: pipeline/stages/dedupe.py#ArticleGroup.origin_country] — the earliest-publisher-defines-origin principle this story applies one level up
- [Source: pipeline/stages/rank.py] — Story 2.5's `_rank_for_zone`, `ZoneKind` branching this story extends

## Dev Agent Record

### Context Reference

_To be filled by dev-story._

### Debug Log

_To be filled by dev-story._

### Completion Notes

All 4 tasks complete. 14 new tests added (2 `origin_country` tests on `Coverage`, 12 anti-concentration cap tests including full end-to-end Continent/World/Country scenarios); full suite is 202 tests, all green. `ruff check` and `ruff format --check` both pass. Boundary check passes.

Key implementation notes:
- `apply_anti_concentration_cap` is a plain single-pass filter (walk the already-ranked list, keep at most `MAX_PER_COUNTRY` per `origin_country`, preserve relative order) — no library heuristic, no multi-pass logic, following the same "simplest correct mechanism" precedent Story 2.2's `rank_clusters` set for this stage.
- Wired into `_rank_for_zone` between `rank_clusters` and the `MAX_SELECTED_CLUSTERS` slice, gated on `serving_zone.kind == ZoneKind.CONTINENT` — verified explicitly via dedicated tests that World and Country requests are never subject to it.
- Story 2.5's pre-existing `_zone_cluster` test helper needed an `origin_country` field added retroactively (its tests predate this story and don't care which country is "origin," only that the field exists so the cap's lookup doesn't `KeyError`). One Story 2.5 test (`test_fallback_still_respects_the_five_item_cap`) needed its fixture reworked once the cap was wired in — its original 6-cluster fixture all shared one `origin_country`, so the new per-country cap (not a bug in either story) reduced the result from 5 to 2 for a reason the test wasn't checking; rebuilt the fixture to spread origins across the three configured European countries so the test continues to isolate the 5-item cap specifically.

### File List

**Modified (no new files):**
- `pipeline/stages/cluster.py` (added `origin_country` to `Coverage` and cluster output; datetime-parsed tiebreak, see Post-Review Fixes)
- `pipeline/stages/rank.py` (added `apply_anti_concentration_cap`, wired into `_rank_for_zone`; reordered relative to the fallback-floor check, see Post-Review Fixes)
- `pipeline/config/__init__.py` (added `MAX_PER_COUNTRY`)
- `tests/test_cluster_stage.py`, `tests/test_rank_stage.py` (new tests; one Story 2.5 fixture/test reworked per the note above; a genuine >5-candidate backfill test added post-review)

## Post-Review Fixes (bmad-code-review, 3-layer adversarial pass)

**Fixed (high severity, independently found and reproduced by both Blind Hunter and Edge Case Hunter): the `MIN_QUALIFYING_FOR_ZONE` fallback decision was made on the pre-cap count, never re-checked after the cap ran.** `_rank_for_zone` computed `qualifying_relevant`, decided whether to fall back to the parent Zone based on that count, and only applied `apply_anti_concentration_cap` afterward. Both reviewers independently constructed and executed the same failing scenario: a Continent with, say, 3 qualifying-relevant Clusters all sharing one `origin_country` passes the pre-cap floor (3 ≥ 2), then the cap silently reduces it to 2 with no re-check and, for a Continent, nowhere further to fall back to — serving a thinner Briefing than the floor was meant to guarantee, with no signal that anything unusual happened. **Fixed** by reordering `_rank_for_zone`: the cap now runs before the fallback-floor check, so the floor is evaluated against what the Zone can actually deliver post-cap, not an inflated pre-cap count. Verified against the reviewers' exact reproduction case (3 same-origin Clusters at a Continent with no parent — now correctly serves 2 with `substituted=False`, honest about not having anywhere else to go) and a new case forcing an actual fallback via the corrected logic (1 relevant Cluster at a Country forces fallback; the Continent's pool is itself concentrated; the cap-then-floor order correctly detects this and the Country Zone falls through as intended).

**Fixed (medium, independently found by both Blind Hunter and Edge Case Hunter): `origin_country`'s earliest-published tiebreak compared `published_at` as raw strings, not parsed datetimes.** Lexicographic string comparison of ISO-8601 timestamps is only safe when every timestamp shares an identical, fixed-width UTC offset format — true today by convention, enforced nowhere. Constructed and verified a genuine disagreement: `"2026-08-10T23:00:00-05:00"` (real time: 2026-08-11T04:00 UTC) sorts lexicographically *before* `"2026-08-11T01:00:00+00:00"` (real time: 2026-08-11T01:00 UTC, genuinely earlier) — a string-comparing implementation picks the wrong group as origin. **Fixed** by parsing both values to `datetime` before comparing, matching `dedupe.py`'s `ArticleRecord.representative` convention (which compares real `datetime` objects) exactly rather than approximating it one representation-layer lower.

**Fixed (test-quality gap, found by Acceptance Auditor): the story's own "cap-before-slice" backfill test never actually exercised that ordering.** `test_continent_briefing_applies_the_cap_with_backfill` used only 4 total candidate Clusters — since `MAX_SELECTED_CLUSTERS` is 5, slicing before or after capping produced byte-identical output on that fixture, so the test would not have failed against a reverted, incorrectly-ordered implementation. Added `test_cap_before_slice_backfills_from_beyond_the_top_five`: 6 total candidates, where the 6th-ranked Cluster only reaches the final output if the cap runs *before* the top-5 slice frees a slot — this is the actual regression the Dev Notes' "why cap-then-slice, not slice-then-cap" reasoning describes, now genuinely locked down. (Two iterations were needed to build a correct fixture — the first two attempts used a country not in `pipeline.config.ZONES`, and then a country with only one member in its `countries` list, both of which caused the backfill candidate to be excluded for reasons unrelated to the cap; the fixture now uses a real configured country with two-country coverage so it clears the qualifying floor and the relevance filter cleanly.)

**Deferred, not fixed (legitimate, lower priority):** `apply_anti_concentration_cap` does a bare `cluster["origin_country"]` lookup with no `.get()` fallback — every real call site guarantees the key today, but a future test fixture that forgets to add it gets a bare `KeyError` with no context. `origin_country ∈ countries` is an invariant enforced only by both fields being computed from the same 6 lines in `coverage_for_cluster`, with no runtime assertion (unlike `MIN_QUALIFYING_FOR_ZONE <= MAX_SELECTED_CLUSTERS`'s explicit assert) that would catch a future regression. No test exercises `MAX_PER_COUNTRY` and `MIN_QUALIFYING_FOR_ZONE` at different relative values, or a Country-Zone-falls-back-to-an-over-concentrated-Continent scenario specifically (the general mechanism is now correct per the high-severity fix above, but that exact composed path isn't independently pinned by a test).

After fixes: 204 tests passing (up from 202).

## Change Log

- 2026-08-12: Story created via bmad-create-story, sixth story of Epic 2. User decided a Cluster's "origin country" (for the cap) is its earliest-published member's country, distinct from the `countries` set (Zone relevance) and `country_count` (qualifying floor) that already exist.
- 2026-08-12: Implemented via bmad-dev-story. All tasks complete, 202/202 tests passing. Status set to review.
- 2026-08-12: Reviewed via bmad-code-review (3-layer adversarial). Both Blind Hunter and Edge Case Hunter independently reproduced the same high-severity bug (fallback decided on pre-cap count) and the same medium bug (string-compared timestamps); Acceptance Auditor found the backfill test didn't test backfill. All three fixed. 204/204 tests passing. Status set to done.
- 2026-08-12: Implemented via bmad-dev-story. All tasks complete, 202/202 tests passing. Status set to review.
