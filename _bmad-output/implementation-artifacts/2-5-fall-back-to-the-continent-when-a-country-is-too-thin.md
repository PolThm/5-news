---
baseline_commit: 9897292
---

# Story 2.5: Fall back to the Continent when a Country is too thin

Status: done

## Story

As a reader who picks a small country,
I want to be shown the continent instead of an empty page,
so that a thin Zone degrades honestly rather than looking broken.

## Scope reality check — read before implementing

**No stage in this pipeline has a notion of Zone today.** `pipeline/stages/rank.py` operates on a single, ungrouped pool of Clusters — there is no per-country or per-continent filtering anywhere, and the 135-combination (15 Zones × 3 Periods × 3 Output Languages) Briefing matrix described in the PRD does not exist yet as generated output. That matrix is explicitly a later Build Order stage (§10 step 5, "The page") — building it now would be a large, premature scope expansion.

**This story's actual, minimal scope: give `rank` stage the ability to select and rank Clusters for one target Zone, with Continent fallback, when asked to.** It does not build the loop that generates all 15 Zones' worth of output per cycle — that loop is Epic 3/4's job once summarization and publishing exist to consume its output. This story adds the *mechanism* (a Zone-scoped ranking function with fallback), proven correct in isolation, not the *orchestration* that would call it 15 times per cycle.

This mirrors how Story 2.2 built ranking as a pure function operating on whatever Clusters it's given, before any notion of "which Clusters for which Briefing" existed — this story extends that same function to accept a target Zone and apply FR-16's fallback rule, without yet wiring up the full per-Zone cycle loop.

## A prerequisite schema gap this story must close first

Every Cluster currently carries only a `country_count` (an integer) — never the actual list of countries. Filtering by Zone requires knowing *which* countries a Cluster's coverage spans, not just how many. This story must extend `pipeline/stages/cluster.py`'s `Coverage` and its `clusters.jsonl` output to include a `countries: list[str]` field (sorted, following the existing convention in `dedupe.py`'s `ArticleGroup.to_dict()`), alongside the existing `country_count` — do not replace `country_count`; downstream code (Story 2.2's rank stage) already depends on it, and it remains the correct field for the existing qualifying-floor and ordering logic. `country_count` is `len(countries)`; keep both because `country_count` is the number Story 2.2 already sorts and filters on, and duplicating that arithmetic from the list in two places would violate AD-12 (one stage owns a value; don't make callers re-derive it).

## Acceptance Criteria

1. **A Country Zone with fewer than 2 Qualifying Clusters falls back to its Continent.** Given a target Country Zone and a pool of Clusters, if fewer than `MIN_QUALIFYING_FOR_ZONE` (see Dev Notes — this is a distinct concept from the existing per-Cluster `MIN_INDEPENDENT_SOURCES`/`MIN_COUNTRIES` floor) Clusters both qualify (Story 2.2's existing floor) AND are relevant to that Country (their `countries` list includes it), ranking is redone against the containing Continent's relevant Clusters instead (FR-16).

2. **The substitution is recorded, never silent.** When a fallback occurs, the ranking output records both the originally-requested Zone and the Zone actually served — matching FR-16's explicit requirement and this story's own title ("recorded... so the page can state it").

3. **A Continent Zone or a well-served Country Zone needs no fallback and reports none.** When the requested Zone already has enough qualifying, relevant Clusters, the served Zone equals the requested Zone, and this is likewise recorded (not just absence of a fallback field — an explicit "no substitution occurred" is part of the same inspectable record, matching Story 2.3/2.4's `formed_by`-style inspectability precedent).

4. **Zone relevance is derived from existing data, not a new signal.** "Relevant to a Country" means the Cluster's `countries` list (Task above) includes that country's slug. "Relevant to a Continent" means relevant to any country belonging to that continent (using `pipeline.config.zone_by_slug`/`continent_for`, which already model the Country→Continent relationship — Story 1.1 built this specifically so FR-16 would have it available).

## Tasks / Subtasks

- [x] **Task 1: Extend Cluster's Coverage with the actual country list** (AC: 4, and the prerequisite scope gap above)
  - [x] `pipeline/stages/cluster.py`: add `countries: frozenset[str]` (or `tuple[str, ...]`, sorted for determinism — follow `ArticleGroup.countries`'s existing `frozenset` convention in `dedupe.py` if reusing that shape is natural) to the `Coverage` dataclass
  - [x] `coverage_for_cluster`: populate it as `{g["source_country"] for g in groups}` — the same set `country_count` is already derived from; do not compute it twice
  - [x] `clusters_out.append({...})` in `run_cluster`: add a sorted `"countries"` list to each Cluster's output dict, alongside the existing `"country_count"`
  - [x] Verify: `len(cluster["countries"]) == cluster["country_count"]` holds for every Cluster in every existing test fixture — add this as an explicit invariant test

- [x] **Task 2: Zone-scoped ranking function** (AC: 1, 2, 3, 4)
  - [x] `pipeline/stages/rank.py`: add a new function `rank_for_zone(clusters: list[dict], zone: Zone) -> ZoneRanking` (or similar — name for clarity, not required to match this exactly) that: (a) filters `clusters` to those relevant to `zone` per AC4's rule, (b) runs the existing `qualifies`/`rank_clusters`/selection-cap logic (do not reimplement Story 2.2's ranking — call into it), (c) if the qualifying, relevant count is below the fallback threshold AND `zone` is a Country (has a `continent`), recurse with `continent_for(zone)` instead
  - [x] Do not modify `run_rank`'s existing signature or behavior — the existing single-pool ranking (no Zone parameter) stays exactly as Story 2.2 left it, since nothing yet calls `rank_for_zone` from a real cycle (per the Scope reality check above, that orchestration is a later story). This story proves the mechanism works in isolation, callable and testable, without wiring it into `run_cycle` yet
  - [x] Add `MIN_QUALIFYING_FOR_ZONE` to `pipeline/config/__init__.py`, alongside the other Story 2.2 thresholds — a distinct constant from `MIN_INDEPENDENT_SOURCES`/`MIN_COUNTRIES` (which gate whether one Cluster qualifies at all) — this one gates whether a Zone has *enough* qualifying Clusters to serve on its own. Read the PRD's exact wording (Dev Notes below) before picking a value — do not guess without checking it's already specified

- [x] **Task 3: Result type carries both Zones** (AC: 2, 3)
  - [x] Define a small result type (dataclass) carrying: `requested_zone`, `served_zone`, `ranked_clusters` (the Story 2.2-shaped output), and enough to answer "did a substitution occur" without the caller needing to compare the two zone objects itself (an explicit `bool` property or field is clearer than making every caller write `requested_zone != served_zone`)
  - [x] This mirrors `pipeline.domain.Briefing`'s existing `zone`/`served_zone` fields (already defined in `pipeline/domain/__init__.py` — check them before inventing a new shape; this story may just need to populate fields that already exist rather than adding new ones)

- [x] **Task 4: Tests**
  - [x] Unit test AC1: a Country Zone with 1 qualifying-and-relevant Cluster and its Continent with 3 qualifying-and-relevant Clusters (including that Country's 1) — requesting the Country returns the Continent's ranking, `served_zone` is the Continent
  - [x] Unit test AC3 (no fallback needed): a Country Zone with enough qualifying, relevant Clusters — `served_zone == requested_zone`, explicitly recorded as no-substitution
  - [x] Unit test AC3 for a Continent Zone directly requested (no parent to fall back to) — confirm no crash and no fallback attempted regardless of count (a Continent has nowhere further to fall back to; a World Zone even more so)
  - [x] Unit test AC4's relevance filter: a Cluster whose `countries` includes "france" is relevant to a `france` Zone request and to `europe` (france's continent), but not to `japan` or `asia`
  - [x] Unit test the `countries`/`country_count` invariant added in Task 1
  - [x] Test that `run_rank`'s existing (non-Zone-scoped) behavior and all of Story 2.2's existing tests are unaffected — this is a purely additive story

## Dev Notes

### Check the PRD before guessing `MIN_QUALIFYING_FOR_ZONE`'s value

AC1 says "fewer than 2 Qualifying Clusters" — the PRD Glossary (§4.4, FR-16 area) and epics.md AC1 both use the literal number 2 here, matching `MIN_INDEPENDENT_SOURCES`'s value coincidentally but conceptually distinct (one counts sources within a Cluster; this counts Clusters within a Zone). Read the exact PRD FR-16 wording before implementing — if it says "fewer than 2," use `2`, not a re-derivation of `MIN_INDEPENDENT_SOURCES`. Name the constant separately regardless, even if its initial value happens to match another constant's value, because they answer different questions and a future change to one must not accidentally change the other (AD-12 spirit, applied to config values too).

### Reuse `Zone`/`continent_for`, do not reinvent Zone relationships

`pipeline/config/__init__.py` already has `ZONES` (all 15, with each Country's `continent` field set), `zone_by_slug`, and `continent_for` — built in Story 1.1 specifically so this exact fallback logic would have what it needs later. Use them. Do not write a new country→continent mapping.

### Check `pipeline.domain.Briefing` before adding new fields

`pipeline/domain/__init__.py`'s `Briefing` dataclass already has `zone` and `served_zone: Zone | None = None` fields, with a docstring stating "`served_zone` differs from `zone` when FR-16's Continent fallback applied, and the difference is never silent — the page states it." This was anticipated during Story 1.1's domain-type design. This story's Task 3 result type should very likely populate these existing fields rather than invent parallel ones — read that dataclass in full before designing a new shape.

### Why this story stops short of the full per-Zone cycle loop

Wiring `rank_for_zone` into `run_cycle` so that it actually runs 15 times per cycle (once per Zone) and produces 15 sets of ranked output requires deciding how that output is stored (`data/intermediate/rank/<cycle-id>/<zone>.jsonl`? one file with a zone key per line? something else), which in turn depends on what the summarize and publish stages (Epic 3) will expect to read — deciding that now, without those stages existing yet to validate the choice against, risks locking in a shape that turns out wrong. The Build Order's own step 5 ("The page") comes after step 4 (Summarization) for exactly this reason: don't build the fan-out before the thing it feeds into exists. This story proves the ranking-with-fallback *logic* is correct in isolation; the orchestration is deliberately deferred.

### Project Structure Notes

Files this story modifies:
- `pipeline/stages/cluster.py` (add `countries` to `Coverage` and cluster output)
- `pipeline/stages/rank.py` (add `rank_for_zone` and its result type)
- `pipeline/config/__init__.py` (add `MIN_QUALIFYING_FOR_ZONE`)
- `tests/test_cluster_stage.py`, `tests/test_rank_stage.py` (new tests)

No new files.

### Previous Story Intelligence

- Every Epic 2 story's most serious defects have been in merge/matching logic making the wrong thing "equal" to another thing (Story 2.1's cluster false-merges, Story 2.3/2.4's clique-chaining). This story's central correctness risk is the opposite shape of bug: a *filtering* bug — a Cluster being wrongly included or excluded from a Zone's relevant set. Test the boundary explicitly (a Cluster relevant to exactly one of several countries in a continent; a Cluster relevant to zero countries the target Zone contains).
- `write_jsonl`/`write_atomically` remain the only sanctioned way to write stage output, when this story's function eventually gets wired into disk output (it may not need to yet, if `rank_for_zone` is only exercised by tests calling it directly against in-memory data per this story's own deferred-orchestration scope).

### References

- [Source: prd.md FR-16] — the exact fallback rule this story implements
- [Source: epics.md#Story 2.5] — acceptance criteria origin
- [Source: pipeline/config/__init__.py] — `ZONES`, `zone_by_slug`, `continent_for` — built in Story 1.1 for this
- [Source: pipeline/domain/__init__.py#Briefing] — `zone`/`served_zone` fields already anticipating this story
- [Source: pipeline/stages/rank.py] — Story 2.2's existing ranking logic this story extends, not replaces
- [Source: prd.md §10 Build Order] — why the full per-Zone loop is deliberately out of scope here

## Dev Agent Record

### Context Reference

_To be filled by dev-story._

### Debug Log

_To be filled by dev-story._

### Completion Notes

All 4 tasks complete. 12 new tests added (5 Coverage/countries invariant tests, 7 Zone-scoped ranking tests); full suite is 190 tests, all green. `ruff check` and `ruff format --check` both pass. Boundary check passes.

**Self-caught bug during implementation, not by a reviewer:** `_is_relevant_to`'s Continent branch (`{z.slug for z in ZONES if z.continent == zone.slug}`) silently returns an empty set for a World Zone, since no country's `continent` field ever equals `"world"` — meaning every Cluster would have been wrongly excluded from a World request. Caught by reasoning through the World case explicitly (not initially covered by any AC or task, since the story's ACs only discuss Country→Continent fallback) before writing this note, and fixed with an explicit `ZoneKind.WORLD` early-return. Added two tests (`test_world_zone_is_relevant_to_every_cluster`, `test_world_zone_never_falls_back`) neither the story's tasks nor its ACs explicitly required, since World's behavior wasn't the story's stated focus but a real correctness gap in the mechanism this story builds.

Key implementation notes:
- `rank_for_zone`'s recursion (`_rank_for_zone` helper) keeps `requested_zone` fixed across fallback hops while `serving_zone` walks up the Continent chain — an earlier draft recursed by calling `rank_for_zone(clusters, parent)` directly, which would have silently lost the original request and reported the Continent as both requested and served after a fallback, violating AC2's "both Zones present" requirement. Caught before writing any tests, by re-reading AC2's exact wording against the draft signature.
- `ZoneRanking.substituted` is a computed property (`served_zone != requested_zone`), not a stored field — matches AC3's "no fallback and reports none" requirement automatically rather than requiring every call site to set it correctly.
- Deliberately did **not** wire `rank_for_zone` into `run_cycle` or any disk-writing path — per this story's own Scope reality check, the per-Zone orchestration loop (which of the 15 Zones to run, where the output for each lands) is explicitly later Epic 3/4 work once summarize/publish exist to validate the shape against. `run_rank`'s existing behavior (Story 2.2) is completely unmodified.

### File List

**Modified (no new files):**
- `pipeline/stages/cluster.py` (added `countries` to `Coverage` and cluster output)
- `pipeline/stages/rank.py` (added `_is_relevant_to`, `ZoneRanking`, `rank_for_zone`, `_rank_for_zone`, a cycle-detection guard on the recursion)
- `pipeline/config/__init__.py` (added `MIN_QUALIFYING_FOR_ZONE`, plus an import-time assertion that it never exceeds `MAX_SELECTED_CLUSTERS`)
- `tests/test_cluster_stage.py`, `tests/test_rank_stage.py` (new tests)

## Post-Review Fixes (bmad-code-review, 3-layer adversarial pass)

All three reviewers agreed: no hard Acceptance Criteria violations. Findings were test-coverage gaps and defense-in-depth suggestions rather than functional defects — a different shape of outcome than Stories 2.1-2.4, where each review round caught a real, live bug.

**Fixed (defense-in-depth, Blind Hunter): the fallback recursion had no cycle guard.** `_rank_for_zone` recurses via `continent_for`, safe today only because `ZONES` happens to be a strict two-level hierarchy with nothing in the type system enforcing that. Added a `visited: frozenset[str]` parameter that raises a clear `ValueError` if a Zone is ever revisited, rather than hanging — cheap insurance against a future `pipeline.config.ZONES` edit introducing a cycle.

**Fixed (defense-in-depth, Edge Case Hunter): `MIN_QUALIFYING_FOR_ZONE` and `MAX_SELECTED_CLUSTERS` had no enforced relationship.** Since the fallback decision checks the qualifying-relevant count *before* the 5-item cap is applied, raising `MIN_QUALIFYING_FOR_ZONE` above `MAX_SELECTED_CLUSTERS` in a future config edit would silently make every Zone fall back regardless of real coverage. Added an `assert` in `pipeline/config/__init__.py`, checked at import time, so a violation surfaces immediately and clearly rather than as a confusing runtime symptom later.

**Fixed (test coverage, all three reviewers): several real scenarios were unexercised.** Added tests for: a Continent itself below the qualifying floor (confirmed it still serves itself rather than crashing or attempting further fallback — there is nowhere further to go); a Cluster whose countries span two different continents (confirmed it counts as relevant to both, per the stated relevance rule); the `MAX_SELECTED_CLUSTERS` cap applying correctly at the zone that ends up actually serving a fallback request, not the originally-requested one; and a true end-to-end integration test running real `cluster.py` output through `rank_for_zone` (the prior test suite only exercised `rank_for_zone` against hand-built dicts, never dicts that had actually round-tripped through `run_cluster`'s JSON serialization).

**Deferred, not fixed (legitimate, lower priority):** `qualifies()` (Story 2.2) checks a Cluster's *global* `country_count`/`independent_source_count`, not counts restricted to the Zone being evaluated — a Cluster relevant to a Continent because one of its several countries happens to lie within it still qualifies using its full global counts. The Blind Hunter flagged this as worth confirming against PRD intent; AC1 explicitly says to reuse "Story 2.2's existing floor" unchanged, so this is arguably in-spec as written, but it's a real interaction worth another look once real data exists to observe whether it produces surprising results. `ZoneRanking` is a new dataclass rather than populating `pipeline.domain.Briefing`'s existing `zone`/`served_zone` fields, which the Dev Notes suggested checking first — `Briefing` also carries `Summary`/`generated_at` fields this story has no data for yet, so constructing a real `Briefing` felt premature; `ZoneRanking` is intentionally narrow and can be adapted into `Briefing` once summarization exists to populate the rest of it.

After fixes: 194 tests passing (up from 190).

## Change Log

- 2026-08-12: Story created via bmad-create-story, fifth story of Epic 2. Scope narrowed after discovering no pipeline stage has a Zone concept yet — user decided to implement the minimal Zone-scoped ranking mechanism now rather than defer the story or build the full 135-combination generation loop prematurely.
- 2026-08-12: Implemented via bmad-dev-story. All tasks complete, 190/190 tests passing. Self-caught a World-Zone relevance bug during implementation (fixed before review). Status set to review.
- 2026-08-12: Reviewed via bmad-code-review (3-layer adversarial). No hard AC violations found — the first story in Epic 2 where all three reviewers agreed the implementation was correct as written. Added a recursion cycle guard and a config-level invariant assertion as defense-in-depth, plus test coverage for a thin-Continent case, a multi-continent-spanning Cluster, and a true cluster.py-to-rank.py integration test. 194/194 tests passing. Status set to done.
