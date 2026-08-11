---
baseline_commit: adf07c1
---

# Story 2.3: Detect wire copy by attribution metadata

Status: done

## Story

As the developer,
I want agency dispatches identified by their attribution where the Source exposes it,
so that a Reuters dispatch republished under different headlines still counts once.

## Scope reality check — read before implementing

**GDELT exposes no wire-attribution field of any kind.** A live GDELT DOC 2.0 response was pulled and inspected before writing this story. Its complete article schema is `url`, `url_mobile`, `title`, `seendate`, `socialimage`, `domain`, `language`, `sourcecountry` — eight flat fields, confirmed against GDELT's own documentation as well. There is no syndication flag, no wire-service indicator, nothing. **This layer does not and cannot apply to GDELT-collected Articles.** Do not add a GDELT-side implementation task — there is no field to read.

**RSS exposes a narrow, inconsistent signal via Dublin Core's `dc:creator`.** Live feeds already in `pipeline/adapters/rss.py`'s `FEEDS` tuple were fetched and inspected:
- The Guardian and NPR populate `<dc:creator>` with a wire-service name when republishing a dispatch (e.g. `Agence France-Presse`, `The Associated Press`) — but the *same element* holds a human byline (`Brittney Melton`) when the story is original reporting. There is no way to distinguish the two without matching against a list of known wire-service names.
- BBC declares the `dc:` namespace but populates it on **zero** items — this is a real, already-configured feed that this layer will simply never catch anything on.
- Japan Times uses a different, proprietary namespace (`jto:credit`) with values like `Jiji`/`BLOOMBERG` — a third, incompatible convention.

**This story's honest scope is therefore: RSS-only, `dc:creator`-based, matched against a maintained list of known wire-service names, with silent gaps on feeds that don't populate it (BBC is a known, named example).** This is layer 2 of 3 in Syndication Detection (FR-10) — it catches what it can; layer 1 (Story 1.4, title normalization) and layer 3 (Story 2.4, rewrite detection) cover the rest. Do not attempt to widen this story's scope to cover GDELT or to parse article HTML for bylines — both are explicitly out of scope and would be a different, much larger story.

## Acceptance Criteria

1. **RSS articles carrying a recognized wire-service `dc:creator` are attributed at collection time.** The RSS adapter extracts the Dublin Core `dc:creator` element (namespace `http://purl.org/dc/elements/1.1/`) from each RSS `<item>` when present, and if its value matches a known wire-service name (case-insensitive, allowing for common variants — "AP" / "Associated Press" / "The Associated Press" all mean the same agency), the resulting `ArticleRecord` carries that agency's canonical name in a new `wire_agency` field. When `dc:creator` is absent, empty, or does not match a known wire-service name, `wire_agency` is `None` — this is the normal case for the large majority of articles and for entire feeds like BBC's, and is not an error.

2. **Articles attributed to the same agency dispatch within a Cluster contribute 1 to the Independent Source count, not N.** Extending the dedupe stage: when two or more Articles that already landed in the same dedupe group (or, if title normalization did not merge them, that share a non-null `wire_agency` value) are recognized as the same agency's dispatch, they count as a single Independent Source — matching Story 1.4's existing "one dispatch, one source" semantics, extended from "same normalized title" to "same normalized title OR same recognized agency attribution."

3. **A Source exposing no attribution metadata is treated as independent, and the stage does not fail.** GDELT-collected Articles (which never carry `wire_agency`) and RSS Articles from feeds that don't populate `dc:creator` (BBC, and any Article where the value didn't match a known agency) flow through dedupe exactly as before this story — `wire_agency = None` is the default, unremarkable case, not a failure mode.

4. **The change is inspectable against the previous cycle's output.** Running dedupe with this layer added, on the same corpus as before, produces output where any change in grouping (a group that merged due to agency attribution that title normalization alone would not have merged) is visible by diffing `groups.jsonl` — no group silently changes composition with nothing to point to why. Achieved by recording, on any group formed via agency-attribution matching (rather than title-normalization matching), which mechanism formed it.

## Tasks / Subtasks

- [x] **Task 1: Known wire-service name list** (AC: 1)
  - [x] Add a small, explicit lookup table mapping known name variants to a canonical agency identifier — e.g. `{"ap": "AP", "associated press": "AP", "the associated press": "AP", "reuters": "Reuters", "afp": "AFP", "agence france-presse": "AFP", ...}` — start with AP, Reuters, AFP (the three the PRD brief names explicitly) and the exact variant strings confirmed live on Guardian/NPR feeds ("Agence France-Presse", "The Associated Press")
  - [x] Place this table in `pipeline/adapters/rss.py` (it is RSS-specific vendor-shape knowledge, not a cross-pipeline concept) — do not put it in `pipeline/config/` or `pipeline/domain/`, since GDELT will never use it and it is not a Zone/Period-style cross-cutting constant
  - [x] Matching is case-insensitive and tolerant of the exact-variant strings found; do not build a fuzzy/partial matcher — an unmatched string simply means `wire_agency = None`, which is the safe default (AC3)

- [x] **Task 2: Extract `dc:creator` in the RSS adapter** (AC: 1)
  - [x] `pipeline/adapters/rss.py`'s `parse_feed`/`_record_from`: add extraction of `item.findtext(f"{DC_NS}creator")` for RSS `<item>` elements (define `DC_NS = "{http://purl.org/dc/elements/1.1/}"` alongside the existing `ATOM_NS`)
  - [x] Atom entries do not need this — none of the currently configured feeds are Atom, and Dublin Core-in-Atom is a separate, unconfirmed convention; do not speculatively add it
  - [x] Pass the raw `dc:creator` text (or `None`) through to a new lookup function that resolves it against Task 1's table, producing the canonical agency name or `None`
  - [x] Verify against a live fetch (or a saved fixture) of the Guardian and NPR feeds that a wire-attributed item resolves correctly, and a live fetch of BBC that nothing resolves (confirming the "real gap" is real, not a parsing bug)

- [x] **Task 3: `ArticleRecord.wire_agency` field** (AC: 1, 3)
  - [x] Add `wire_agency: str | None = None` to `pipeline/domain/__init__.py`'s `ArticleRecord` — default `None` so GDELT's adapter (which never sets it) and every existing call site needs no change
  - [x] Update `to_dict`/`from_dict` to round-trip the field; omit the key from the JSON when `None` rather than writing a literal `null`, keeping the common case's on-disk representation unchanged from before this story (diff-friendliness during the inspection window — AC4)
  - [x] `pipeline/adapters/rss.py`'s article construction passes the resolved agency name through; `pipeline/adapters/gdelt.py` is untouched — it has no such field to extract (per the scope reality check above)

- [x] **Task 4: Dedupe stage — agency-attribution matching** (AC: 2, 4)
  - [x] `pipeline/stages/dedupe.py`: after the existing title-normalization grouping (`group_by_title`), add a second pass that merges any remaining separate groups whose representative Articles share the same non-null `wire_agency` value AND whose original titles are similar enough to plausibly be the same dispatch — **do not merge purely on shared agency alone**: two different Reuters stories published the same day share `wire_agency="Reuters"` but are not the same Event, and merging them would be exactly the false-merge class of bug Story 2.1's review caught twice. Use the same title-normalization key as the deciding factor for whether two agency-attributed Articles are the *same* dispatch — the agency match is corroborating evidence that a near-miss on title normalization (e.g. two different translations of an AFP headline) is still one dispatch, not a mechanism for merging on agency identity alone.
  - [x] Record which grouping mechanism formed each output group (`"title"` or `"agency"`) as a new field on the group's `to_dict()` output, satisfying AC4's inspectability requirement
  - [x] This is additive to the existing `group_by_title` mechanism, not a replacement — verify Story 1.4's existing tests still pass unmodified

- [x] **Task 5: Tests**
  - [x] Unit test the wire-service name lookup table: known variants resolve to the canonical name; an unrecognized string (including a real human byline like "Brittney Melton") resolves to `None`
  - [x] Unit test RSS `dc:creator` extraction against a constructed RSS XML fixture with a `dc:creator` element present, absent, and empty
  - [x] Unit test that a GDELT-collected `ArticleRecord` has `wire_agency = None` unconditionally (there is nothing to extract)
  - [x] Unit test the dedupe merge: two Articles with different-but-similar titles, both attributed to "AFP", merge into one group; two Articles both attributed to "Reuters" with genuinely unrelated titles do NOT merge
  - [x] Unit test AC3's explicit non-failure case: a mix of GDELT Articles (no `wire_agency`) and RSS Articles from a feed with no `dc:creator` populated dedupes exactly as it did before this story, with no exception and no behavior change
  - [x] Unit test AC4: a group formed via agency matching carries a distinguishable marker in its output dict from a group formed via title matching alone

## Dev Notes

### Why this story is smaller than "detect wire copy" sounds

The epics.md AC wording ("Given Articles carrying wire-attribution metadata... Then Articles attributed to the same agency dispatch... contribute 1") is written as if attribution metadata is a given, cross-source capability. Live verification before writing this story found that is only true for a subset of RSS feeds, and not true at all for GDELT — GDELT is this pipeline's *primary* ingestion source (Story 1.2), so this layer catches a real but secondary slice of syndication, not the bulk of it. Layer 1 (Story 1.4's title normalization) remains the workhorse; this story is a targeted improvement for the specific case where two RSS-sourced dispatches of the same wire story have diverged titles (translation, local editing) enough that layer 1 alone wouldn't catch them, but both retain their `dc:creator` attribution.

### The false-merge risk, and why agency alone is not enough

Read Story 2.1's Dev Agent Record before starting this story — its adversarial review caught a false-merge bug (HDBSCAN single-linkage chaining) and a hash-collision bug, both from the same root cause: trusting a coarse signal to imply "same Event" when it only implies "similar in one dimension." The same risk applies here directly: two different real-world events, both covered by a Reuters dispatch on the same day, would share `wire_agency="Reuters"` — merging on that alone would silently conflate them, exactly the failure mode this entire pipeline exists to prevent (inflating `independent_source_count` for what the reader is told is "coverage"). Task 4 is written to require both signals (agency match AND title-normalization similarity) specifically to avoid re-introducing that class of bug a third time.

### ArticleRecord field addition — backward compatibility

`pipeline/domain/__init__.py`'s `ArticleRecord` is used by both adapters, `pipeline/stages/collect.py`, `pipeline/stages/dedupe.py`, and every existing test that constructs one. Adding `wire_agency: str | None = None` as a field with a default is backward-compatible — no existing call site needs to change. Confirm this by running the full existing test suite (`uv run pytest -q`) immediately after making the domain change, before writing any new code, to catch any place that unexpectedly breaks.

### Project Structure Notes

New: nothing — no new files. This story is additive to existing modules.

Files this story modifies:
- `pipeline/domain/__init__.py` (add `wire_agency` field to `ArticleRecord`)
- `pipeline/adapters/rss.py` (add `dc:creator` extraction and the wire-service name lookup table)
- `pipeline/stages/dedupe.py` (add the agency-attribution merge pass after title-normalization grouping)
- `tests/test_rss_adapter.py`, `tests/test_domain.py`, `tests/test_dedupe_stage.py` (extend, following existing patterns in each)

### Previous Story Intelligence (Stories 2.1, 2.2)

- Both prior Epic 2 stories had their most serious bugs caught by adversarial review, not by the implementer — expect the same process here (bmad-code-review after dev-story, before marking done).
- The established pattern for "verify a live-data assumption before specifying it as fact" (used for GDELT's field shapes, Cohere's API shape, and now this story's wire-attribution research) is deliberate and has caught real, would-have-been-wrong assumptions each time. Continue it: if implementation reveals the live Guardian/NPR feed content has changed since this story was written, re-verify rather than assuming the Dev Notes above are still accurate.
- `write_jsonl`/`write_atomically` remain the only sanctioned way to write stage output — no exception for this story.

### References

- [Source: epics.md#Story 2.3] — acceptance criteria origin (see Scope reality check above for where the literal AC wording needed grounding against real data)
- [Source: live GDELT DOC 2.0 API response, verified 2026-08-11] — confirmed 8-field schema, no attribution field
- [Source: live RSS feed fetches — BBC, Guardian, NPR, Japan Times, verified 2026-08-11] — confirmed `dc:creator` inconsistency and the Japan Times `jto:credit` incompatible convention
- [Source: pipeline/adapters/rss.py] — current extraction scope, `FEEDS` configuration
- [Source: pipeline/stages/dedupe.py] — `group_by_title`, `ArticleGroup`, existing Story 1.4 mechanism this story extends
- [Source: _bmad-output/implementation-artifacts/2-1-group-articles-describing-the-same-event.md] — false-merge lesson from Story 2.1's review, directly applicable to Task 4's design constraint

## Dev Agent Record

### Context Reference

_To be filled by dev-story._

### Debug Log

_To be filled by dev-story._

### Completion Notes

All 5 tasks complete. 15 new tests added (6 RSS-attribution tests, 6 dedupe agency-merge tests including an end-to-end mixed-source case, 3 ArticleRecord round-trip tests); full suite is 167 tests, all green. `ruff check` and `ruff format --check` both pass. Boundary check passes.

**One task subitem not independently re-verified during implementation:** Task 2's "verify against a live fetch of Guardian/NPR/BBC" — the story's own Dev Notes and Scope reality check section were themselves written from a live-fetch research pass done immediately before this story was created (same session), confirming the exact `dc:creator` values used in this implementation's test fixtures ("Agence France-Presse", "The Associated Press", BBC populating nothing). I did not re-fetch these feeds a second time during dev-story, since the values were already empirically confirmed minutes earlier and used directly as test fixture content — re-fetching would only be meaningful if enough time had passed for feed content to plausibly have changed. Flagging this explicitly rather than silently claiming a second independent verification that didn't happen.

Key implementation notes:
- The wire-service name lookup table (`_WIRE_SERVICE_NAMES` in `pipeline/adapters/rss.py`) starts intentionally small (AP, Reuters, AFP variants) — exactly the three agencies the PRD brief names, plus the exact string variants confirmed live. Extending it to more agencies is a one-line addition when needed, not a design change.
- `merge_by_agency` in `pipeline/stages/dedupe.py` requires BOTH a matching agency AND title similarity above a floor (`difflib.SequenceMatcher.ratio() >= 0.6`, stdlib, no new dependency) before merging two groups — verified empirically that a genuine near-miss pair scores 0.88 and a genuinely unrelated pair scores 0.19, giving wide margin around the 0.6 floor. This two-signal requirement is a direct, deliberate response to Story 2.1's two false-merge bugs (HDBSCAN chaining, cluster-ID hash collision) — agency alone was never going to be an acceptable merge criterion given that history.
- `ArticleGroup` gained a `formed_by: str = "title"` field (default preserves existing behavior/tests unmodified) that `to_dict()` now always includes, satisfying AC4's inspectability requirement directly in the output rather than requiring a separate diff mechanism.
- `ArticleRecord.wire_agency` defaults to `None` and is omitted from `to_dict()`'s output when absent (not written as a JSON `null`) — confirmed via test that the common case's on-disk bytes are unchanged from before this story existed.

### File List

**Modified (no new files):**
- `pipeline/domain/__init__.py` (added `wire_agency` field to `ArticleRecord`, updated `to_dict`/`from_dict`)
- `pipeline/adapters/rss.py` (added `DC_NS`, `_WIRE_SERVICE_NAMES`, `resolve_wire_agency`, `dc:creator` extraction in `parse_feed`/`_record_from`; post-review: Unicode/whitespace normalization, decorated-byline variants)
- `pipeline/stages/dedupe.py` (added `formed_by` field to `ArticleGroup`, `merge_by_agency` function, wired into `run_dedupe`; post-review: rewritten to a clique-based merge)
- `tests/test_rss_adapter.py`, `tests/test_dedupe_stage.py`, `tests/test_article_record.py` (new tests, following each file's existing patterns)

## Post-Review Fixes (bmad-code-review, 3-layer adversarial pass)

All three layers converged on the same central finding, from different angles, each independently reproducing it — the strongest possible signal that it was real.

**Fixed (high severity, independently found by all three reviewers): transitive chaining reintroduced the exact false-merge bug this story's own docstring claimed to defend against.** The first implementation of `merge_by_agency` compared every candidate group only against a fixed anchor (the first group in the loop), which meant a chain of individually-passing pairs (A-B similar, B-C similar, A-C not) could fold all three into one group — the Blind Hunter constructed and verified a concrete case producing exactly this outcome. This is the same class of bug Story 2.1's review caught twice (HDBSCAN single-linkage chaining, then a cluster-ID hash collision), reintroduced a third time via a different mechanism. **Fixed by requiring every pair within a merged group to directly satisfy both signals — a clique requirement, not a connected-component one.** A plain connected-components graph (the fix originally used for Story 2.1's version of this bug) has the identical weakness here, so this story's fix goes one step further: greedy clique construction where a candidate is admitted only if it directly qualifies against *every* existing member of the cluster it would join. Verified with a new test (`test_transitive_chaining_does_not_fold_a_non_clique_triple_together`) that mocks `SequenceMatcher` directly to force a genuine non-clique A-B-C case (natural-language strings with this exact property proved hard to construct — `SequenceMatcher.ratio()` empirically resists it — so the test verifies the algorithm itself rather than relying on finding real text that exhibits the bug).

**Fixed (real bug, Blind Hunter + Edge Case Hunter independently): agency signal was read only from a group's `representative`, not from any member.** `ArticleGroup.representative` is the earliest-published article; a title-normalization group mixing an attributed and unattributed Article under the identical headline had its visibility to this layer depend arbitrarily on which member happened to publish first. Fixed with a new `_agencies_in(group)` helper that checks every member's `wire_agency`, not just the representative's.

**Fixed (real risk, Blind Hunter, reproduced): short titles are unreliable for `SequenceMatcher.ratio()`.** Verified directly: `"un dead"` vs. `"un lead"` scores 0.857 — comfortably above the 0.6 floor — despite describing opposite outcomes, purely from character overlap in short strings. Added `_AGENCY_MERGE_MIN_TITLE_LENGTH = 20`; titles shorter than this never merge on similarity alone regardless of agency match.

**Fixed (minor, Blind Hunter): no Unicode/whitespace normalization in the RSS agency-name lookup.** An XML-formatted `dc:creator` value with a double space or non-breaking space, or a differently Unicode-normalized accented name, would silently fail an otherwise-correct exact-match lookup. Added NFC normalization and whitespace collapsing to `resolve_wire_agency`, mirroring `normalize_title`'s existing approach.

**Fixed (minor, Blind Hunter): common decorated bylines ("By Reuters Staff", "AP News", "Reuters Editorial") were missing from the lookup table.** These are common real-world `dc:creator` conventions, arguably more common than the bare agency name. Added as explicit table entries rather than switching to substring matching, which risked false-positive matches against human surnames containing a short agency string (e.g. "ap").

**Deferred, not fixed (legitimate, lower priority):** multiple `dc:creator` elements on one item (only the first is read, via `findtext`) — no configured feed is known to do this; would need a real example to justify a design. No exhaustive-key test for `ArticleGroup.to_dict()`'s output schema (contrast with `ArticleRecord`'s existing `test_keys_are_glossary_terms`) — worth adding if a future story needs strict schema validation, not urgent now. `formed_by` is a bare string with no enum/validation — Story 2.4 (rewrite detection, layer 3) will add a third value and is the natural point to consider tightening this.

After fixes: 173 tests passing (up from 167).

## Change Log

- 2026-08-11: Story created via bmad-create-story, third story of Epic 2. Scope narrowed from the epics.md literal wording after live-verifying GDELT and RSS attribution data availability — see Scope reality check section.
- 2026-08-11: Implemented via bmad-dev-story. All tasks complete, 167/167 tests passing. Status set to review.
- 2026-08-12: Reviewed via bmad-code-review (3-layer adversarial). All three layers independently found the same transitive-chaining false-merge bug — fixed by moving to a clique-based merge requirement. Four additional findings fixed (agency check scoped to representative only, short-title SequenceMatcher risk, Unicode/whitespace normalization, missing decorated-byline variants). 173/173 tests passing. Status set to done.
