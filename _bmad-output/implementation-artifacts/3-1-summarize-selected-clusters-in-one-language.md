---
baseline_commit: bf3a0f0
---

# Story 3.1: Summarize selected Clusters in one language

Status: done

## Story

As a reader,
I want each item written as readable prose rather than a bare headline,
So that I understand what happened without opening the source.

## A real gap this story must close before it can write anything

**The ranked Cluster shape currently carries no article-level data — no URL, no Source name, no per-member language.** Trace it: `dedupe.py`'s `ArticleGroup.to_dict()` writes the representative's full `ArticleRecord` fields (`title`, `url`, `source`, `source_country`, `language`, `published_at`, `collected_by`) plus `normalized_title`/`sources`/`countries`/`article_count` — all of that is on disk in `data/intermediate/dedupe/<cycle-id>/groups.jsonl`. But `cluster.py`'s `run_cluster` (`pipeline/stages/cluster.py:290-302`) reads those full dicts and keeps only `sorted(m["normalized_title"] for m in members)` as `member_titles` when it writes `clusters.jsonl` — every other field on each member dict is discarded at that boundary. By the time a Cluster reaches `rank.py` and then this story's `ranked.jsonl`, there is no URL to link out to and no Source name to attribute, and no way to recover them (`cluster_id` is a hash of member *indices* within that one run, not a foreign key back to dedupe's output).

This is a real requirement, not an implicit nice-to-have: AC2 below requires checking a Summary against "at least two concordant Articles," which needs the Articles' actual text, and Story 3.3 (next in this epic) requires an outbound link and Source name per item. Both are unreachable without this fix. It is required **now**, in this story, because summarize is the first stage that needs member-level data — deferring it would mean writing the summarize stage against a shape that has to change again immediately after.

**The fix, and why it belongs in `cluster.py`, not here:** per AD-12 ("a stage that needs a value it does not own reads it from its input and passes it through unchanged"), `cluster.py` already has every member's full dict in hand (it reads them from `dedupe.py`'s output) — it is simply dropping fields it doesn't currently use. Change `member_titles: list[str]` to `members: list[dict]`, where each member dict carries `title`, `url`, `source`, `source_country`, `language` (drop `normalized_title`, `published_at`, `collected_by`, and dedupe-internal fields that summarize/rank have no use for — a member here is "what a Summary can cite," not a full `ArticleGroup.to_dict()` echo). Do **not** rename this to anything but `members` — `member_titles` was always a member-title projection standing in for a fuller shape that didn't exist yet; this story is what finally needs the fuller one.

**Everywhere `member_titles` is read today must be updated to the new shape**, not left as a second, parallel field:
- `pipeline/stages/rank.py`'s `link_across_days` (`anchor.get("member_titles", [])`, the `"member_titles" in m` anchor-preference check) — Story 2.7's cross-day linking. Update to `members`/`"members" in m`, with the same empty-list fallback for history-only clique members (`history.py` still persists no member-level data at all — that is correct and unchanged; see Task 3 below).
- `pipeline/stages/history.py` — persists Coverage fields only, never `member_titles`, so no change needed there, but its docstrings/comments that reference `member_titles`'s absence should be re-read against the renamed field (a grep, not a rewrite, if none exist).
- Every test asserting on `member_titles` (`tests/test_cluster_stage.py`, `tests/test_rank_stage.py`) must be updated to the new shape — do not leave a duplicate assertion checking a field that no longer exists.

This is a **narrow, mechanical extension** of an existing stage's output, not new architecture: `cluster.py` keeps its existing responsibility (grouping into Clusters) and its existing AD-12 ownership boundary; it now just passes through three more fields per member instead of collapsing them to a bare title. `rank.py` and `history.py` are otherwise unaffected — Coverage fields (`independent_source_count`, `country_count`, `countries`, `origin_country`) are computed exactly as before, from the same union arithmetic, over the same member list.

## Acceptance Criteria

1. **A ranked Briefing's Clusters each receive Summary text keyed to Cluster identity, and nothing else about the Briefing changes.** Given a list of ranked Clusters (the `ranked.jsonl` shape `run_rank` already produces, now carrying full `members` per Task 0), when the summarize stage runs, each Cluster gets a `summary` field containing prose text, and the stage adds, removes, reorders, or renumbers nothing — the same Clusters, in the same order, with the same `rank`/`cluster_id`/Coverage fields, plus one new field (AD-6, FR-11).

2. **A Summary states nothing that isn't grounded in at least two of the Cluster's member Articles, and never attributes a synthesized statement to a named outlet.** The prompt sent to Claude enforces this by construction (a no-fabrication instruction plus the actual member titles/sources as the only input), and is verified in tests via prompt content assertions, not by inspecting live model output (FR-13). A Cluster with fewer than two members (a legitimate, singleton-Cluster case per `cluster.py`'s own docstring) cannot satisfy "at least two concordant Articles" — see Task 2 for how the prompt and degrade logic both handle this without treating it as an error.

3. **A summarize failure for one Cluster degrades that item to its title and outbound link; it never fails the whole Briefing.** Given the Claude Batch API returns an error result for one Cluster's request (or the whole submit/poll/collect flow raises), when the Briefing is assembled, that Cluster's `summary` field is set to a degrade marker (its representative title, established by the same earliest-published-then-url convention `dedupe.py`/`cluster.py` already use) rather than aborting, and every other Cluster in the same call still gets its real Summary (AD-6, mirroring AD-10's "one failure degrades, never aborts" pattern already used by `cohere_embed.py` and every guarded step in `cycle.py`).

4. **The whole summarize call for one language goes through the Batch API, submitted and awaited within one function call — not the synchronous Messages API, and not yet the two-phase submit-then-exit split.** Per the user's explicit decision for this story: build the mechanism (Batch API request construction, submission, poll loop, result collection, one language) now; Story 3.4 replaces the blocking poll loop with the real submit-and-exit / resume-later split (AD-11). This story's `run_summarize` may block on `batches.retrieve(...)` in a loop — that is the deliberately deferred simplification, not a bug to fix here.

## Tasks / Subtasks

- [x] **Task 0: Extend `cluster.py`'s output to carry member-level article data** (prerequisite for AC1, AC2; described in full above)
  - [x] In `pipeline/stages/cluster.py`'s `run_cluster`, replace `"member_titles": sorted(m["normalized_title"] for m in members)` with `"members": sorted(({"title": m["title"], "url": m["url"], "source": m["source"], "source_country": m["source_country"], "language": m["language"]} for m in members), key=lambda mem: mem["title"])` — sorted by `title` to preserve the existing deterministic-output guarantee `member_titles`'s `sorted()` call provided
  - [x] Update `pipeline/stages/rank.py`'s `link_across_days`: rename the `member_titles` anchor-preference check and field to `members` (`next((m for m in members if "members" in m), members[0])`, `anchor.get("members", [])`)
  - [x] Update `tests/test_cluster_stage.py`'s two assertions on `member_titles` (`len(by_size[0]["member_titles"]) == 1`, etc.) to read `members` and assert on the dict shape, not just a count — confirm at least one test checks that `url`/`source`/`source_country`/`language` actually round-trip
  - [x] Update `tests/test_rank_stage.py`'s existing `member_titles`-shaped fixtures (Story 2.7's linking tests) to the new `members` shape
  - [x] Run the full existing suite before writing any new code for this story — a rename this central must not silently break Epic 2's tests

- [x] **Task 1: Add the `claude` adapter** (AC1, AC3, AC4; AD-13)
  - [x] New `pipeline/adapters/claude.py`, following `cohere_embed.py`'s exact shape: injectable `client: Client | None = None` parameter, a narrow `Protocol` describing only the SDK surface this adapter calls (not the full `anthropic.Anthropic` type), `ADAPTER = "claude"` constant, never raises past its own boundary (AD-10/AD-13)
  - [x] Read the API key from `os.environ.get("ANTHROPIC_API_KEY")` inside the adapter when no client is injected — same pattern as `cohere_embed.py`'s `COHERE_API_KEY` check, same degrade-with-`Failure`-not-raise if unset
  - [x] Model: `claude-haiku-4-5` — this is the model the architecture spine's own Tooling table names for summarization, chosen for its Batch API discount and low per-token cost against this workload's simple, bounded task (write one short paragraph from a handful of headlines); this story does not revisit that choice, only implements against it
  - [x] Batch construction: one request per Cluster being summarized this call, `custom_id` set to the Cluster's `cluster_id` (Batch API results return in arbitrary order — see the Dev Notes' Batch API section below — so `custom_id` is the only correct way to reassociate a result with its Cluster; do not assume request/result ordering is preserved)
  - [x] Submit via `client.messages.batches.create(requests=[...])`, then poll `client.messages.batches.retrieve(batch_id)` in a loop until `processing_status == "ended"` (a fixed short sleep between polls, e.g. 2 seconds, is fine — this whole function is the thing Story 3.4 replaces with a non-blocking split; do not over-engineer backoff here), then stream `client.messages.batches.results(batch_id)` and build a `dict[cluster_id, result]` — never assume list-index alignment with the submitted requests
  - [x] Per-Cluster prompt: give Claude the Cluster's `members` (title/source/source_country/language per member) and ask for one short paragraph in the target `OutputLanguage`, with an explicit no-fabrication instruction (AC2) and an explicit instruction never to attribute a synthesized claim to a named outlet
  - [x] A `custom_id` whose batch result is `errored`/`canceled`/`expired`, or a `custom_id` missing from the results stream entirely (should not happen per the Batch API contract, but the adapter must not crash if it does), is reported as a `Failure` for that Cluster — not raised, and not silently dropped; the caller (the summarize stage) uses this to trigger the degrade path in AC3

- [x] **Task 2: Add the `summarize` stage** (AC1, AC2, AC3; AD-6, AD-12)
  - [x] New `pipeline/stages/summarize.py`, one language per call (this story's explicit scope — Story 3.2 calls it three times, once per `OutputLanguage`, not something this story builds)
  - [x] `run_summarize(clusters: list[dict], language: OutputLanguage, cycle_id, data_root=DEFAULT_DATA_ROOT, summarize_fn=...) -> WrittenSummarize`, mirroring every other stage's `run_<stage>` signature and `Written<Stage>` return dataclass shape
  - [x] Input is the `ranked.jsonl` list exactly as `run_rank` wrote it (AD-6: "input is a Briefing that is already ordered and counted") — do not re-sort, re-filter, re-slice, or touch `rank`/Coverage fields. The stage's only job is to attach a `summary` string to each dict and pass every other field through unchanged (verify this with a test that diffs the output against the input, field-by-field, minus the added key)
  - [x] A Cluster with fewer than 2 `members` (singleton Cluster — legitimate per `cluster.py`'s own docstring, and reachable in real data whenever a Zone's Continent fallback pulls in a thinly-covered Event) still gets summarized, but the prompt for it cannot claim "at least two concordant Articles" — write the prompt to describe what is actually known (one Article) rather than fabricating a second source; AC2's no-fabrication requirement is about not inventing facts, not about requiring every Cluster to have 2+ members (Qualifying Cluster's own floor, `MIN_INDEPENDENT_SOURCES = 2`, already guarantees at least 2 *Independent Sources* reached the rank stage — but Independent Source and member-article count are not the same number when Continent fallback or cross-day linking is involved; do not assume they always match)
  - [x] Degrade path (AC3): for any Cluster whose `custom_id` came back as a `Failure` from the adapter, set `summary` to that Cluster's representative title (the same earliest-published-then-url tiebreak `dedupe.py`/`cluster.py` already use — Task 0's `members` list is sorted by title, not by publish order, so recompute the earliest-published member here rather than assuming `members[0]` is it) rather than raising or dropping the Cluster from the Briefing
  - [x] Write output alongside every other stage's convention: `data/intermediate/summarize/<cycle-id>/<language>/summarized.jsonl` (language-scoped subdirectory, since Story 3.2 calls this three times per cycle and each call's output must not overwrite the others) plus a `summarize.json` metadata file recording `clusters_in`, `clusters_summarized`, `clusters_degraded`, and the list of degraded `cluster_id`s (mirroring `cluster.py`'s `metadata` dict shape)

- [x] **Task 3: Tests**
  - [x] Adapter tests (`tests/test_claude_adapter.py`, mirroring `tests/test_cohere_adapter.py`'s fake-client pattern exactly): batch submission carries one request per Cluster with the correct `custom_id`; results are reassociated by `custom_id` regardless of the fake client returning them out of order; an `errored` result for one `custom_id` is reported as a `Failure` scoped to that Cluster, not raised; a missing `ANTHROPIC_API_KEY` with no injected client degrades to a `Failure` rather than raising (same pattern as `cohere_embed.py`'s `COHERE_API_KEY` check)
  - [x] Stage tests (`tests/test_summarize_stage.py`): AC1 — output has the same Cluster count, same order, same `rank`/`cluster_id`/Coverage fields as input, plus `summary`; AC2 — prompt construction includes both member titles/sources and an explicit no-fabrication instruction (assert on prompt content, not live model behavior); AC3 — one Cluster's adapter failure degrades only that Cluster to its representative title while every other Cluster in the same call keeps its real summary; a singleton-member Cluster is summarized without the prompt claiming two sources
  - [x] Task 0 regression tests: `cluster.py`'s `members` field carries the right shape (title/url/source/source_country/language) and stays sorted by title; `rank.py`'s `link_across_days` anchor-preference and empty-fallback logic still works under the renamed field

## Dev Notes

### Batch API — what actually changed, and what didn't

Checked directly against the current Anthropic Python SDK: the model ID is unchanged (`claude-haiku-4-5`, still $1/$5 per MTok input/output, 200K context) and the Batch API shape used here is unchanged from what the architecture spine's Tooling table assumes — `client.messages.batches.create(requests=[Request(custom_id=..., params=MessageCreateParamsNonStreaming(...))])`, poll via `client.messages.batches.retrieve(batch_id).processing_status` until `"ended"`, then iterate `client.messages.batches.results(batch_id)` and switch on each result's `.result.type` (`succeeded`/`errored`/`canceled`/`expired`). **Results arrive in arbitrary order — always key by `custom_id`, never by position.** No beta header is required for the Batches API. 50% cost reduction applies automatically; no separate configuration.

Do not use `thinking`/adaptive thinking or an `effort` parameter for this call — Haiku 4.5 does not support `effort` (it errors), and this is a short, bounded, low-reasoning task (write one paragraph from a handful of headlines) that does not benefit from extended thinking regardless.

Prompt caching is **not** viable for this workload (a separate, already-settled decision — do not revisit it in this story): Haiku 4.5's minimum cacheable prefix is 4096 tokens, and the summarization system prompt is shorter than that, so a `cache_control` marker would silently never activate. The Batch API's own 50% discount is the cost lever for this workload (ties to Story 3.6's NFR-2 cost-independence requirement, three stories ahead).

### Why this story does not build AD-11's two-phase split

The architecture spine frames the two-phase resumable cycle (submit-then-exit, resume-and-collect-later) as the production mechanism for exactly this Batch API call. This story deliberately builds a blocking version instead — submit, then poll in a loop within the same function call, same process — per the user's explicit decision when this story was scoped. This mirrors the precedent Stories 2.4 and 2.7 both set for a different kind of deferral (a threshold reasoned rather than measured): here, the deferral is of an *orchestration* concern, not a data question, and Story 3.4 is the story that resolves it, three stories ahead in this same epic, once 3.2 and 3.3 have also landed and there's a real multi-language, multi-Zone call site to split. Building the two-phase split now, before that real call site exists, would mean guessing at its shape twice.

### Where does this get called from?

No orchestration exists yet that calls `run_summarize` once per Zone/Period/Language combination — that is Story 3.2's job (the 135-Briefing matrix) and, per AD-11, Story 3.4's job to split into two phases. This story delivers `run_summarize` and the `claude` adapter as a tested, standalone mechanism, exactly as Story 2.5's `rank_for_zone` and Story 2.7's `link_across_days` were each delivered standalone before their consuming orchestration existed. Do not wire this into `cycle.py` in this story — `cycle.py` currently ends at the history-write step (Story 2.7), and it stays there until Epic 3's later stories (and Story 3.4 specifically) define what the two-phase cycle actually looks like.

### AD-6's exact boundary — read this before writing `run_summarize`

> "The summarize stage's input is a Briefing that is already ordered and counted. Its output is Summary text keyed to Cluster identity. It may not add, remove, reorder, or renumber anything. A summarize failure for one Cluster degrades that item to its Article title and outbound link; it never fails the Briefing."

Two things this rules out, both worth stating explicitly because they are easy mistakes to make while writing a summarization prompt: (1) do not let the model's response influence which Clusters appear or their order — the model only ever writes into a `summary` field on a dict that already exists with every other field set; (2) "outbound link" in the AD-6 text is Story 3.3's job (this story does not yet write a link field — Task 0 makes `url` available per member, but attaching a chosen outbound link to the Cluster itself, plus the Source name display Story 3.3's ACs describe, is explicitly next). This story's degrade path only needs the *title*, per this story's own AC3 — do not build Story 3.3's link-selection logic early.

### AD-12's ownership line for this story

`summarize` owns Summary text only (the spine's own words, in the Consistency Table: `"summarize owns Summary text only"`). Every other field on a ranked Cluster dict — `cluster_id`, `rank`, `independent_source_count`, `country_count`, `countries`, `origin_country`, and now `members` — is owned by an earlier stage and must be copied through unchanged, never recomputed. The Task 1 test that diffs output against input field-by-field exists specifically to catch a violation of this rule.

### Project Structure Notes

New files:
- `pipeline/adapters/claude.py`
- `pipeline/stages/summarize.py`
- `tests/test_claude_adapter.py`
- `tests/test_summarize_stage.py`

Files this story modifies:
- `pipeline/stages/cluster.py` (Task 0: `member_titles` → `members`, carrying full per-member article fields)
- `pipeline/stages/rank.py` (Task 0: update `link_across_days`'s `member_titles` references to `members`)
- `tests/test_cluster_stage.py` (Task 0: update `member_titles` assertions)
- `tests/test_rank_stage.py` (Task 0: update `member_titles` fixtures)
- `pyproject.toml` / dependency manifest (add `anthropic` SDK — check current dependency file before assuming `pip`/`uv` conventions; `cohere` is already a dependency per `cohere_embed.py`, so this project already has a precedent for a vendor SDK as a direct dependency rather than vendored)

### Previous Story Intelligence

- Every new adapter in this codebase (`gdelt.py`, `cohere_embed.py`) follows the exact same shape: injectable client/fetch parameter defaulting to a real implementation, a narrow `Protocol` for the vendor surface actually used, an `ADAPTER` name constant, and a hard rule of never raising past the adapter's own boundary. `claude.py` must follow this without variation — it is not an opportunity to introduce a different pattern for "the AI one."
- Story 2.7's review (single-layer Blind Hunter pass, per the user's cost-reduction decision, which remains in effect for this story) found real bugs specifically at the boundary between "what a field's producer intended" and "what a consumer assumed" — the missing `member_titles` on a history-only clique, the uncaught dimension mismatch. This story's Task 0 rename is exactly that kind of boundary; the review for this story should look hard at every remaining reference to the old `member_titles` key, not just the ones already listed above (a grep for the literal string, not just the file list here, is the way to be sure nothing was missed).
- Story 2.6's review found two independently-reproduced ordering bugs (cap-before-slice, fallback-before-cap) — both were about assuming an invariant held at a point in the pipeline where it had actually already been violated one step earlier. This story's degrade path (AC3) has the same shape of risk: confirm the "earliest published" tiebreak is computed from `members`' actual `published_at`-equivalent ordering, not assumed from list position, since Task 0's `members` list is explicitly sorted by title, not by publish time.
- The single-layer adversarial review (Blind Hunter only) remains the process for this story, per the user's standing cost-reduction decision after Story 2.6.

### References

- [Source: epics.md#Story 3.1] — acceptance criteria origin (verbatim AC text reproduced above)
- [Source: ARCHITECTURE-SPINE.md#AD-6] — summarize stage's exact input/output contract, quoted in full above
- [Source: ARCHITECTURE-SPINE.md#AD-11] — the two-phase resumable cycle this story deliberately does not yet build
- [Source: ARCHITECTURE-SPINE.md#AD-12] — one-owner-per-field rule this stage must respect
- [Source: ARCHITECTURE-SPINE.md#AD-13] — adapter isolation rule `claude.py` follows
- [Source: ARCHITECTURE-SPINE.md#Consistency Conventions, Tooling] — `claude-haiku-4-5` model choice, Batch API discount, prompt-caching-not-viable note
- [Source: pipeline/stages/cluster.py:290-302] — the exact line `member_titles` is written, and what full data is available but currently discarded
- [Source: pipeline/stages/dedupe.py#ArticleGroup.to_dict] — confirms `url`/`source`/`source_country`/`language` are present on every member dict `cluster.py` already reads, before this story's fix
- [Source: pipeline/adapters/cohere_embed.py] — the adapter shape `claude.py` must mirror exactly
- [Source: _bmad-output/implementation-artifacts/2-7-link-clusters-across-ingest-days.md] — precedent for delivering a stage's mechanism standalone before its orchestration exists, and for a single-layer adversarial review

## Dev Agent Record

### Context Reference

_To be filled by dev-story._

### Debug Log

- Task 0's rename (`member_titles` → `members`) initially left one live consumer unaccounted for: `pipeline/stages/history.py:101` read `cluster["member_titles"][0]` to embed the representative title for cross-day history. A full-repo grep after the rename caught it (the story's own instruction to grep the literal string, not just the pre-listed file set). Fixed to `cluster["members"][0]["title"]`, with its two test fixtures in `test_history_stage.py` updated to the new dict shape.
- `anthropic` SDK's `Request`/`MessageCreateParamsNonStreaming` are runtime `TypedDict`s (plain dicts), not attribute-access objects — confirmed directly against the installed `anthropic==0.121.0` before writing adapter tests. Two initial test assertions used dot notation (`r.custom_id`, `submitted[0].params`) and failed with `AttributeError`; fixed to subscript access (`r["custom_id"]`, `submitted[0]["params"]`). The adapter implementation itself was correct from the start — this was a test-only bug.

### Completion Notes

All 4 tasks complete, TDD throughout (RED confirmed before each implementation). 235/235 tests passing (up from 222 at story start: +1 net on Task 0's cluster/rank/history test updates, +8 new adapter tests, +5 new summarize stage tests — 13 new tests total, with the balance of the +13 delta absorbed by in-place assertion rewrites rather than new test functions on the Task 0 files).

**Task 0 (prerequisite, not in the original AC list but required to satisfy AC2/AC3 and Story 3.3's next-story needs):** `pipeline/stages/cluster.py`'s `run_cluster` previously collapsed every dedupe-group member to a bare `normalized_title` string in a `member_titles` list, discarding `url`/`source`/`source_country`/`language` that were present on the dicts it already had in hand. Replaced with a `members` list of dicts carrying those five fields, sorted by `title` (preserving the prior list's determinism guarantee). Propagated the rename through `rank.py`'s `link_across_days` (Story 2.7's anchor-preference logic) and `history.py`'s title-embedding call (Debug Log above), plus every test fixture that constructed the old shape.

**Task 1:** `pipeline/adapters/claude.py` — new adapter, mirrors `cohere_embed.py`'s shape exactly (injectable `client`, narrow `Protocol`, `ADAPTER` constant, never raises past its boundary). `summarize_clusters()` submits one Batch API request per Cluster (`custom_id` = `cluster_id`), blocks in a poll loop on `batches.retrieve(...).processing_status` until `"ended"` (the deliberately deferred simplification AD-11/Story 3.4 will replace), then reassociates results by `custom_id` — never by position, since the fake client's test deliberately returns results in reversed insertion order to prove this. An `errored` result or a `custom_id` absent from `results()` entirely both degrade to a scoped `Failure`, never a raise. Model is `claude-haiku-4-5` per the architecture spine's Tooling table (unchanged in the current SDK — confirmed no drift before writing code). Added `anthropic` as a project dependency via `uv add` (already anticipated in the story's own Project Structure Notes).

**Task 2:** `pipeline/stages/summarize.py` — `run_summarize()` follows AD-6 exactly: takes `run_rank`'s output list unchanged, attaches one `summary` string per Cluster, and copies every other field through verbatim (a dedicated test diffs input against output field-by-field to enforce this). A Cluster whose `custom_id` didn't come back with a real summary degrades to its earliest-published member's title (recomputed from `members`' `published_at`, since `members` is sorted by title, not publish order — Task 0's Dev Notes explicitly flagged this as a risk to check). Singleton-member Clusters (legitimate — Continent fallback and cross-day linking can produce a ranked Cluster with fewer members than Independent Sources) get a prompt that describes the one available Article rather than fabricating a second source. Output lands at `data/intermediate/summarize/<cycle-id>/<language>/summarized.jsonl`, language-scoped so Story 3.2's three-call-per-cycle usage won't collide.

**Not built in this story, by explicit design (confirmed with the user before story creation):** AD-11's real two-phase submit-then-exit split (Story 3.4); wiring `run_summarize` into `cycle.py`'s orchestration (no per-Zone/Period/Language loop exists yet — Story 3.2's job); Story 3.3's outbound-link/Source-name display logic (this story's degrade path only needs a title, per its own AC3 — `members[*].url` is now available for 3.3 to use, but selecting and attaching a link is explicitly deferred).

**Post-review fixes (single-layer adversarial pass — Blind Hunter only, per the user's standing cost-reduction decision):**

Blind Hunter returned 12 findings. Two were dismissed on triage as stylistic nitpicks, not defects (a minor inefficiency in the adapter's failure-accumulation loop; two files independently checking "did this cluster get a result" with no shared helper). One ("this story's summarize/claude.py is unwired, so calling it 'implemented' is generous") was a misreading of the story's own explicitly user-approved scope — mirroring Story 2.5/2.7's precedent of shipping a standalone, tested mechanism before its orchestration exists — and was addressed by tightening a docstring, not by adding orchestration this story never intended to build.

**Fixed (real bug): `history.py`'s title-embedding call would raise `IndexError` on any Cluster with an empty `members` list.** `rank.py`'s `link_across_days` (Story 2.7) legitimately produces `"members": []` for a clique formed entirely from historical entries — its own comment calls this "a completely ordinary case," not an edge case — and `history.py`'s `cluster["members"][0]["title"]` had no guard against it. Not reachable today only because `cycle.py` doesn't wire `link_across_days` into a real cycle yet, but it would have been the very first thing to break once it is. Fixed by filtering to Clusters with a non-empty `members` list before embedding; a Cluster with none is skipped (matching AD-10's degrade pattern) rather than crashing the whole `append_history` call for every other Cluster in the same cycle.

**Fixed (real bug): the degrade path's tiebreak used `title` instead of `url`, contradicting its own docstring's claim of matching `cluster.py`'s convention.** `coverage_for_cluster` and `dedupe.py`'s `ArticleGroup.representative` both tiebreak earliest-published members on `(published_at, url)` — never `title`, since titles aren't guaranteed unique the way URLs are. `_earliest_member_title` used `(published_at, title)`, silently diverging from the convention it claimed to follow. Fixed to tiebreak on `url`; added a regression test with two members sharing a `published_at` where title-order and url-order disagree, which fails against the old tiebreak.

**Fixed (real bug): a transient failure while iterating the Batch API's `results()` discarded every summary already collected in that same call.** The original code wrapped batch submission, polling, *and* result collection in one `try/except Exception`, so an exception raised partway through iterating results (e.g. a network blip) reverted every already-succeeded Cluster to a total-failure `SummarizeResult`, contradicting the module's own stated guarantee that a failure degrades only the affected Cluster. Fixed by separating submission/polling's `try/except` from result-collection's: a mid-iteration exception now only fails the Clusters not yet reached, keeping every summary already collected.

**Fixed (real risk): the poll loop had no maximum attempt count, so a stuck or permanently-wedged batch would block the call — and the whole cycle, since nothing else runs concurrently — forever.** Added `max_poll_attempts` (default 300, i.e. 10 minutes at the default 2-second interval); exceeding it degrades every Cluster in the call to a `Failure` rather than hanging. This is still the deliberately simplified, blocking version of AD-11's two-phase split (Story 3.4 replaces the whole poll loop) — the cap only prevents an unbounded hang within it, not a redesign of the deferred mechanism.

**Fixed (real gap): titles concatenated into the prompt had no escaping.** Article titles come from many uncontrolled international sources (RSS, GDELT) and were interpolated directly between literal double-quotes in `_member_lines`; a title containing its own double-quote could prematurely close that delimiter and blend into the surrounding instruction text. Fixed by escaping embedded quotes before interpolation. (General prompt-injection resistance — a title actively containing adversarial instructions — is a model-behavior concern outside this story's scope; this fix only closes the cheap, structural delimiter-breakout case.)

**Fixed (real defect, test-only): a tautological assertion in the singleton-member prompt test could never fail.** `assert "confirmed" not in prompt.lower() or "do not imply" in prompt.lower()` was always true given the fixed corroboration-note string for the under-2-members branch, regardless of what the word "confirmed" actually did. Replaced with assertions that check the two-source instruction text is genuinely absent and the correct singleton-specific instruction is genuinely present.

**Fixed (comment clarity, not code): the module docstring quoted AD-6's full text, which names an "outbound link" as part of a degraded item — read on its own, this could look like an unmet claim.** Added one sentence clarifying that attaching a link is explicitly Story 3.3's job (each member's `url` is available for it to use), and this story's degrade path adds only the title field, per this story's own AC3.

**Also fixed (zero-risk consistency, not flagged as a bug but caught while addressing the finding above): three `member_titles`-shaped test fixtures in `test_rank_stage.py`** (`_cluster`, `_zone_cluster`, `_origin_cluster`) were leftover from before Story 3.1's Task 0 rename. None of them exercise `link_across_days` (the only function that reads that key), so they were functionally inert — but left as-is they would mislead a future reader into thinking `rank.py`'s other functions care about the old field name. Renamed to `members` for consistency with every other fixture this story touched.

After fixes: 240 tests passing (up from 235 immediately post-implementation; +5 net from 2 new regression tests plus 1 rewritten tautological assertion, with the balance absorbed by fixture-only renames).

### File List

**New:**
- `pipeline/adapters/claude.py`
- `pipeline/stages/summarize.py`
- `tests/test_claude_adapter.py`
- `tests/test_summarize_stage.py`

**Modified:**
- `pipeline/stages/cluster.py` (Task 0: `member_titles` → `members`, carrying full per-member article fields)
- `pipeline/stages/rank.py` (Task 0: `link_across_days`'s anchor-preference logic updated to `members`)
- `pipeline/stages/history.py` (Task 0 follow-through: title-embedding call updated to read `members[0]["title"]`; post-review fix: skip Clusters with an empty `members` list rather than crash)
- `pipeline/adapters/claude.py` (post-review fixes: separated submission/polling's exception handling from result-collection's so a mid-iteration failure doesn't discard already-collected summaries; added `max_poll_attempts` cap; escaped quotes in interpolated titles)
- `pipeline/stages/summarize.py` (post-review fixes: degrade tiebreak corrected to `(published_at, url)`, matching `cluster.py`'s actual convention; docstring clarified re: AD-6's outbound-link text)
- `tests/test_cluster_stage.py` (Task 0: updated assertions to `members`, added round-trip checks for `url`/`source`/`source_country`/`language`)
- `tests/test_rank_stage.py` (Task 0: `_today_cluster` fixture and the history-only-clique test updated to `members`; post-review: `_cluster`/`_zone_cluster`/`_origin_cluster` fixtures also renamed for consistency)
- `tests/test_history_stage.py` (Task 0 follow-through: two fixtures updated to the `members` dict shape; post-review: new empty-`members` regression test)
- `tests/test_claude_adapter.py` (post-review: new regression tests for mid-iteration-failure and poll-timeout)
- `tests/test_summarize_stage.py` (post-review: new tiebreak-mismatch regression test, quote-escaping regression test, fixed tautological assertion)
- `pyproject.toml` / `uv.lock` (added `anthropic` dependency via `uv add`)

## Change Log

- 2026-08-12: Story created via bmad-create-story, first story of Epic 3. User explicitly decided the Batch API call should be blocking (submit-and-poll within one function call) for this story, deferring AD-11's real two-phase submit-then-exit split to Story 3.4. Story creation also surfaced and scoped a real prerequisite gap: `cluster.py`'s output currently discards all per-member article data (URL, Source, language) needed by this story's AC2 and by Story 3.3 — folded into this story as Task 0 rather than filed separately, since summarize cannot be written correctly without it.
- 2026-08-12: Implemented via bmad-dev-story. All 4 tasks complete, TDD throughout. Task 0's grep-for-the-literal-string instruction caught a real remaining `member_titles` consumer in `history.py` that wasn't in the story's pre-listed file set. 235/235 tests passing (up from 222). Status set to review.
- 2026-08-12: Reviewed via bmad-code-review (single-layer adversarial pass, per the standing cost-reduction decision). Fixed 6 real findings: an IndexError on empty `members` in `history.py` (reachable once cross-day linking is wired into a real cycle), a tiebreak-key mismatch in the degrade path, a blanket exception in the Claude adapter that discarded already-collected summaries on a mid-iteration failure, an unbounded poll loop with no timeout, unescaped quotes in interpolated titles, and a tautological test assertion. One finding was a misreading of this story's explicitly user-approved scope (unwired orchestration, deferred to Story 3.2/3.4), addressed via a docstring clarification. 240/240 tests passing. Status set to done.
