---
baseline_commit: 5d03b2d
---

# Story 3.3: Capture attribution and outbound links

Status: done

## Story

As a reader,
I want to see who reported this and reach the original in one click,
So that the Summary is a trailer rather than a substitute.

## What already exists, and the one real gap this story closes

Most of this story's raw material already exists on a summarized Cluster dict, built up across Stories 2.1–3.2: `countries` (the actual list, not just a count — Story 2.5), `independent_source_count`/`country_count` (Coverage, Story 2.2), and `origin_country` (Story 2.6). **The Consensus Score half of this story's AC is therefore already satisfied by pass-through — nothing new to compute, only to confirm nothing drops it.**

**What's missing:** a single outbound link and Source name for display. `members` (Story 3.1's Task 0) carries every member Article's `url`/`source`, but nothing has ever selected *one* to show as "here's where to read more" — every prior consumer of `members` picked its own single representative for its own purpose (`_earliest_member_title`'s degrade text, `coverage_for_cluster`'s `origin_country`), and none of those selections were ever written back onto the Cluster dict as a first-class field. This story adds exactly that: an explicit `outbound_url` and `outbound_source` field, selected once, by the same `(published_at, url)`-earliest convention this pipeline has now used three times (dedupe's `ArticleGroup.representative`, cluster's `coverage_for_cluster`, summarize's `_earliest_member_title`) — not a new convention, the same one, applied to a new purpose.

## Acceptance Criteria

1. **A Briefing item carries at least one outbound link to an original Article, with its Source name.** Given a summarized Cluster (Story 3.1/3.2's output), when it is written to disk, it carries `outbound_url` and `outbound_source` fields selected from its `members` by the earliest-published-then-url convention — the same member `_earliest_member_title` already selects for the degrade path, applied here for the non-degraded case too, so a reader always sees a genuine link regardless of whether summarization succeeded or degraded (FR-14).

2. **The Consensus Score's contributing Independent Sources and their countries are recorded on the item exactly as computed upstream.** `independent_source_count`, `country_count`, and `countries` pass through this story's stage unchanged — confirmed by test, not just by inspection, since AD-12 forbids recomputing a value another stage owns (supports FR-9).

## Tasks / Subtasks

- [x] **Task 1: Select and attach one outbound link + Source name per Cluster** (AC1)
  - [x] Add `_select_outbound_link(cluster: dict) -> tuple[str, str]` to `pipeline/stages/summarize.py` — returns `(url, source)` from the same `(published_at, url)`-earliest member `_earliest_member_title` already selects; do not write a second, subtly-different selection function (extract the shared selection logic if that keeps the two functions from silently drifting apart, following the same "de-duplicate the discipline, don't reimplement it" precedent `pipeline.stages.clique_partition` set in Story 2.7)
  - [x] In `run_summarize`, attach `outbound_url` and `outbound_source` to every output Cluster dict (degraded or not) — this is a new field this stage now owns per AD-12, alongside its existing `summary` ownership; every other field continues to pass through unchanged exactly as Story 3.1 established
  - [x] A Cluster with zero members (the `link_across_days` history-only-clique edge case Story 3.1's Task 0 already guarded in `history.py`) has no Article to link to — `outbound_url`/`outbound_source` must degrade to `None` rather than crash or fabricate a link, matching every other Cluster-with-no-members guard already in this pipeline

- [x] **Task 2: Confirm the Consensus Score fields pass through unchanged** (AC2)
  - [x] No production code change expected here (verification task) — extend the existing AD-6 pass-through test (Story 3.1's `test_every_cluster_receives_a_summary_field_and_nothing_else_changes`) to also assert `independent_source_count`, `country_count`, and `countries` are byte-identical between input and output, now that this story adds new fields alongside `summary` — the pass-through guarantee must hold for every field this stage does not itself own

- [x] **Task 3: Tests**
  - [x] `tests/test_summarize_stage.py`: a non-degraded Cluster's `outbound_url`/`outbound_source` match its earliest-published-then-url member, using the same tied-publish-time construction Story 3.1's tiebreak regression test already established (title-order and url-order deliberately disagreeing, to prove the tiebreak key is really `url`)
  - [x] `tests/test_summarize_stage.py`: a degraded Cluster (summarization failed) still carries a correct `outbound_url`/`outbound_source` — the degrade path only replaces `summary`, never the attribution fields, so a reader always has somewhere to click through regardless of whether the AI text is real or a fallback title
  - [x] `tests/test_summarize_stage.py`: a Cluster with zero members produces `outbound_url=None`, `outbound_source=None` rather than raising
  - [x] `tests/test_summarize_stage.py`: extend the AD-6 pass-through test to assert `independent_source_count`/`country_count`/`countries` are unchanged, confirming this story's new fields are additive, not replacements for anything upstream owns

## Dev Notes

### Why this belongs in `summarize.py`, not a new stage

AD-6 already establishes `summarize` as the stage that turns a ranked-but-bare Cluster into something display-ready; this story's two new fields are exactly that kind of display-preparation work, not a new pipeline responsibility. Adding a `publish`-adjacent "attribution" stage would split one Cluster's display-ready shape across two stages for no reason — `summarize` already reads `members` to build the degrade-path title (Story 3.1), so it already has everything this story needs in hand.

### Why the selection convention must be `_earliest_member_title`'s, not a new one

This pipeline has now settled on `(published_at, url)`-earliest three separate times (dedupe's `representative`, cluster's `coverage_for_cluster`, summarize's own `_earliest_member_title`) specifically because titles are not guaranteed unique the way URLs are — a fourth, subtly different selection (e.g., picking by `url` alone, or re-introducing a `title`-based tiebreak) would silently disagree with the other three about which Article is "the" representative one for a Cluster on a given day. Reuse the exact tiebreak; do not invent a "best for outbound linking" heuristic distinct from "best for degrade text" — a reader clicking through should land on the same Article this pipeline already treats as that Cluster's representative everywhere else.

### The zero-members case is not hypothetical

Story 3.1's Task 0 found and fixed a real `IndexError` in `history.py` on an empty `members` list, produced by `rank.py`'s `link_across_days` for a clique formed entirely from historical entries — "a completely ordinary case," per that function's own comment. `_select_outbound_link` must handle the same shape the same way: degrade to `None`, not crash, and not fabricate a plausible-looking link to nowhere.

### Project Structure Notes

No new files. Files this story modifies:
- `pipeline/stages/summarize.py` (add `_select_outbound_link`; attach `outbound_url`/`outbound_source` in `run_summarize`)
- `tests/test_summarize_stage.py` (new tests per Task 3; extended pass-through assertions)

### Previous Story Intelligence

- Story 3.1's `_earliest_member_title` already implements the exact selection this story needs, one field over (`summary`'s degrade text, not a dedicated link field) — read it before writing `_select_outbound_link`; the two are close enough that a shared helper is worth extracting if it doesn't complicate either call site's error handling.
- Story 3.2's Blind Hunter review flagged two independently-maintained enumerations (`OUTPUT_LANGUAGES` vs `_LANGUAGE_NAMES`) as a legitimate-but-deferred future concern. This story does not introduce an analogous risk — there is exactly one selection convention, reused, not two.
- Single-layer adversarial review (Blind Hunter only) remains the process for this story, per the user's standing cost-reduction decision.

### References

- [Source: epics.md#Story 3.3] — acceptance criteria origin (verbatim AC text reproduced above)
- [Source: pipeline/stages/summarize.py#_earliest_member_title] — the exact selection convention this story reuses
- [Source: ARCHITECTURE-SPINE.md#AD-6] — summarize's display-preparation ownership, extended by this story's two new fields
- [Source: ARCHITECTURE-SPINE.md#AD-12] — one-owner-per-field rule; `outbound_url`/`outbound_source` become fields `summarize` owns
- [Source: _bmad-output/implementation-artifacts/3-1-summarize-selected-clusters-in-one-language.md] — the story whose Task 0 (`members`) and degrade-path tiebreak this story directly extends

## Dev Agent Record

### Context Reference

_To be filled by dev-story._

### Debug Log

- Verified before writing any code that the Consensus Score fields (`independent_source_count`, `country_count`, `countries`) already pass through `run_summarize` unchanged — Story 3.1's existing `test_every_cluster_receives_a_summary_field_and_nothing_else_changes` test already covers this generically (it loops every original field and asserts it survives). Task 2 added no production code; only named the AC's specific fields explicitly in that same test.

### Completion Notes

Both tasks complete, TDD throughout. 247/247 tests passing (up from 244 at story start: +3 new tests for outbound-link selection, degrade-path attribution, and the zero-members case).

**Task 1:** Extracted `_representative_member(cluster) -> dict | None` from Story 3.1's `_earliest_member_title`, which now delegates to it — the single `(published_at, url)`-earliest selection convention this pipeline has used four times now (dedupe's `representative`, cluster's `coverage_for_cluster`, summarize's degrade text, and now this story's outbound link), not a fifth, subtly-different reimplementation. `_select_outbound_link(cluster) -> tuple[str | None, str | None]` returns `(None, None)` for a Cluster with no members, matching `_representative_member`'s own degrade. `run_summarize` attaches `outbound_url`/`outbound_source` to every output Cluster regardless of whether that Cluster's summary degraded — attribution and summary-text quality are independent concerns, so a reader always has a real Article to click through to.

**Task 2 (verification, no production code):** Confirmed the Consensus Score fields already pass through unchanged; added explicit assertions naming them, on top of the pre-existing generic pass-through loop.

**Post-review fixes (single-layer adversarial pass — Blind Hunter only, per the standing cost-reduction decision):**

Blind Hunter returned 11 findings. Four were dismissed on triage: a pre-existing (not introduced by this diff) latent risk in `_representative_member`'s `published_at`-defaults-to-empty-string tiebreak, out of this story's scope to fix; the lack of a cross-file enforcement that all four `(published_at, url)` tiebreak sites (dedupe, cluster, summarize's degrade text, this story's link) stay in sync — a legitimate future concern, same shape as Story 3.2's deferred `OUTPUT_LANGUAGES`/`_LANGUAGE_NAMES` finding, not a bug today; no runtime assertion guarding against a hypothetical future upstream stage writing a pre-existing `outbound_url` key — over-engineering against a scenario this codebase has never had; and near-duplicate (not parameterized) test fixtures — a style preference, not a defect, consistent with every other test file in this project.

**Fixed (real bug): `_select_outbound_link` used a bare `representative["source"]` subscript, so a member missing `source` raised `KeyError` deep in the loop — crashing the entire summarize call for every Cluster, not just the malformed one.** This directly contradicted AD-10's degrade-not-abort principle this same module's docstring invokes. Fixed with `.get()`-based access; added a regression test with a member missing `source` entirely, confirming only that Cluster's link degrades while every other Cluster keeps its real one.

**Fixed (real gap): a present-but-empty `url` or `source` string passed through unchanged rather than degrading, which would have rendered as a broken, empty href on the eventual display side.** Fixed by treating an empty string the same as a missing key (`representative.get("url") or None`); added a regression test.

**Fixed (real gap): the zero-members case and a failed-summarize case were never exercised together, despite being the most degraded state a Cluster can reach.** Added a regression test confirming `_degrade_title`'s cluster-id fallback and `_select_outbound_link`'s `(None, None)` both hold simultaneously for a no-members, summarize-failed Cluster.

**Fixed (real gap): the per-cycle metadata tracked summary-text degrades (`degraded_cluster_ids`) but nothing about outbound-link degrades — a reader-facing shortfall this file's own AD-6/AD-10 philosophy says should never pass silently.** Added `clusters_without_outbound_link`/`clusters_without_outbound_link_ids` to the metadata dict, mirroring the existing `degraded_cluster_ids` shape; added a regression test.

**Fixed (real inefficiency): `_earliest_member_title`'s degrade path and `_select_outbound_link` each independently called `_representative_member`, so a degraded Cluster paid for the same `min()` scan over `members` twice.** Refactored: `run_summarize` now calls `_representative_member` once per Cluster and passes the result to both the (renamed) `_degrade_title` and `_select_outbound_link`, which now take the representative directly rather than the Cluster.

**Fixed (doc hygiene): the module docstring's "Story 3.3 attaches them" read oddly from inside the module Story 3.3 itself wrote.** Reworded to describe current-state behavior without the self-referential story citation.

After fixes: 251 tests passing (up from 247 immediately post-implementation; +4 net from new regression tests).

### File List

**Modified:**
- `pipeline/stages/summarize.py` (extracted `_representative_member`; added `_select_outbound_link`; `run_summarize` attaches `outbound_url`/`outbound_source`; module docstring and AD-6 comments updated to reflect the stage's expanded field ownership; post-review: `.get()`-based defensive access, empty-string guard, single shared `_representative_member` call per Cluster via renamed `_degrade_title`, new metadata fields for unlinked Clusters, docstring self-reference fix)
- `tests/test_summarize_stage.py` (added 3 new tests for outbound-link selection, degrade-path attribution independence, and the zero-members case; extended the existing AD-6 pass-through test with explicit Consensus Score field assertions including `origin_country`; post-review: 4 new regression tests for the missing-`source` crash, empty-string degrade, combined double-degrade case, and metadata's unlinked-Cluster count)

## Change Log

- 2026-08-12: Story created via bmad-create-story. Confirmed most of this story's AC (the Consensus Score fields) is already satisfied by pass-through from Stories 2.2/2.5/2.6; the one real gap is a selected outbound link + Source name, which this story adds via the same `(published_at, url)`-earliest convention Story 3.1's degrade path already established, applied to a new purpose rather than reinvented.
- 2026-08-12: Implemented via bmad-dev-story. Both tasks complete, TDD throughout. Extracted the shared `_representative_member` selection helper rather than reimplementing the tiebreak a fourth time. 247/247 tests passing (up from 244). Status set to review.
- 2026-08-12: Reviewed via bmad-code-review (single-layer adversarial pass, per the standing cost-reduction decision). Fixed 6 real findings: a `KeyError` crash on a member missing `source` that would have aborted the whole summarize call instead of degrading one Cluster, an empty-string url/source passing through as a broken link, the zero-members-plus-failed-summarize case never tested together, no metadata visibility for Clusters lacking an outbound link, a redundant duplicate `_representative_member` call per degraded Cluster, and an awkward self-referential docstring sentence. 251/251 tests passing. Status set to done.
