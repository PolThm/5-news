---
baseline_commit: ca54aa1
---

# Story 6.1: Give every item a generated headline

Status: done

## Story

As a reader scanning five items,
I want each item to open with a headline stating what happened,
So that I can choose what to read without reading every Summary in full.

## Scope, decided explicitly before this story was written

**This story reverses a documented decision, and the reason it can is that the decision was never a product judgement.** The UX design originally specified `h2` + summary paragraph per item. It was removed during Story 4.1 spec prep, and the `.memlog.md` entry recording that removal states its own reason plainly: *"pipeline/domain/__init__.py's BriefingRecord schema has no such field... Corrected both spine files and both HTML mockups to match the real data contract rather than inventing a field."* The design intent survived; only the schema blocked it. This story makes the field exist. Confirmation that the intent survived is on disk: the pre-correction mockups in `.working/` were never reverted and still show the exact `h2` + summary structure, at ~70 characters per headline.

**FR-13's non-fabrication rule did not cover a headline, and that was the single real gap.** Its wording is scoped to *"A Summary states nothing that is not present in at least two concordant Articles."* A `headline` field is not a Summary, so the rule as written would not have applied to the most exposed generated text on the page — short, prominent, and rendered directly above the outlet name FR-14 forbids attributing a synthesized statement to. The user decided to extend FR-13 rather than add a sibling FR, so the headline inherits both the corroboration rule and the attribution prohibition. PRD §7's register constraint ("no urgency, no teasers, no 'breaking'") is restated in the prompt itself, because a generated headline is precisely where clickbait would enter this product if nothing forbade it.

**One batch call, not two.** The Batches API supports every Messages API feature, so `output_config.format` with a `json_schema` constrains the existing per-Cluster call to return `{headline, summary}` instead of a free-text paragraph. Cost is essentially unchanged: the same Articles go in, roughly 20 more tokens come out. The rejected alternatives were two separate calls (doubles batch requests and the input tokens, and turns `cycle.json`'s 3 tracked batch IDs into 6) and deriving the headline from the Article title without a model call (zero cost, but the title is in the source Article's language, which would put an English or Portuguese headline on the Spanish page — recreating the exact bug the user had just reported).

**The ~260-character one-breath budget covers the Summary alone; the headline is added on top.** The user chose this over shrinking Summaries to ~190 characters to absorb the headline. Each item grows by roughly 25%, matching the ratio the `.working/` mockups already showed.

**No data migration exists to do.** `data/briefings/` contained only `.gitkeep` when this story was written — no real Briefing had ever been published, and the 135 files under `site/public/briefings/` are regenerated from fixtures at every build and are not tracked. The schema bump is therefore free of migration work. It is still a bump, per the spine's absolute rule, and the field is additive: the site treats a missing `headline` exactly as it treats a missing `summary`, so a `schema_version` 1 file renders without headings rather than failing.

## Acceptance Criteria

1. **Given** a Cluster selected for a Briefing, **when** the summarize stage runs, **then** it receives both a Headline and a Summary from the same batch call, each in that Briefing's Output Language, **and** the response shape is constrained rather than parsed out of free text (FR-11).
2. **Given** a generated Headline, **when** it is checked against its Cluster, **then** it states nothing absent from at least two concordant Articles, **and** carries no urgency, teaser, or "breaking" framing (FR-13 as extended by this story, FR-14, PRD §7).
3. **Given** generation fails or returns a malformed response for one Cluster, **when** the Briefing is assembled, **then** that item degrades to its Article title for both fields, the degrade is counted, and the Briefing still publishes (AD-6, AD-10), **and** the two fields never degrade independently.
4. **Given** a published Briefing, **when** it is written to disk, **then** each Cluster carries a `headline` alongside its `summary`, **and** the schema version is bumped rather than the field added silently (spine, Consistency Conventions).
5. **Given** the page renders, **when** its document outline is inspected, **then** each item's headline is a real `<h2>` beneath the mad-libs `<h1>` with no skipped levels, **and** an item with no headline renders no heading rather than an empty one (NFR-4).
6. **Given** a Briefing published before this story, **when** the page renders it, **then** it renders without headings rather than failing.

## Tasks / Subtasks

- [x] **Task 1: Constrain the batch response to `{headline, summary}`** (AC1)
  - [x] `_SUMMARY_SCHEMA` in `claude.py`: both fields `required`, `additionalProperties: false` — the shape is a guarantee, not a request.
  - [x] `output_config.format` passed in `submit_batch`'s `MessageCreateParamsNonStreaming`.
  - [x] `_prompt_for` asks for both fields; `_HEADLINE_INSTRUCTION` carries the register constraints verbatim from PRD §7.
  - [x] Confirmed `MAX_TOKENS = 512` needs no change: measured fixture summaries at ~70 tokens, headline adds ~20.

- [x] **Task 2: Parse the structured response, degrading on every malformed shape** (AC1, AC3)
  - [x] New `ClusterText` dataclass rather than `tuple[str, str]` — two short strings would otherwise be silently swappable.
  - [x] `_parse_cluster_text` returns `(text, None)` or `(None, failure)`, never a half-populated result and never raising.
  - [x] Rejects non-JSON (truncated `max_tokens` response, safety refusal), non-object payloads, and empty-after-strip fields — an empty string satisfies `{"type": "string"}` and would render as a blank heading.
  - [x] `BatchCollectResult.summaries: dict[str, str]` became `texts: dict[str, ClusterText]`.

- [x] **Task 3: Attach the headline through summarize and publish** (AC3, AC4)
  - [x] `collect_summarize` writes `headline` alongside `summary`; one degrade decision covers both fields, so an item can never carry a real headline beside a fallback summary.
  - [x] Degrade text for both fields is `_degrade_title`'s representative Article title — exactly what AD-6 prescribes, at the documented cost of being in the Article's own language.
  - [x] **Added `"headline"` to `publish.py`'s `_SUMMARIZE_OWNED_FIELDS`.** This is the story's one silent-failure trap: `_attach_summary` filters on `if field in summarized`, so a field missing from that tuple is dropped at publish with no error and no failing test.
  - [x] Bumped `_BRIEFING_RECORD_SCHEMA_VERSION` 1 → 2.

- [x] **Task 4: Render the headline as an `<h2>`** (AC5, AC6)
  - [x] `briefing.ts`'s `Cluster` and `period-switcher.ts`'s `ClusterLike` both gain optional `headline` (hand-mirrored, per this codebase's established duplication convention).
  - [x] `BriefingPage.astro` and `renderItemListHtml` both render `<h2 class="headline">` before the summary — the two renderers must stay identical.
  - [x] Absent rather than empty when there is no headline: an empty heading announces nothing.
  - [x] CSS: headline at DESIGN.md's existing, until-now-unused `headline-md` token (24px Source Serif 4). Summary moves to IBM Plex Sans 16px — the split DESIGN.md's Typography section already prescribed, and which two stacked serif blocks would otherwise blur into one paragraph.
  - [x] All 13 clusters across the 5 fixtures gained a headline, hand-written at 64–69 characters.

- [x] **Task 5: Tests**
  - [x] Prompt asks for a headline and keeps the non-fabrication instruction; schema pins `required` + `additionalProperties`.
  - [x] Parsing: truncated JSON, empty headline, whitespace stripping — each degrades one Cluster, never the batch.
  - [x] Degradation: both fields degrade together; metadata counts it.
  - [x] **Two publish tests pinning the whitelist trap**, one of which derives its assertions from `_SUMMARIZE_OWNED_FIELDS` itself so the tuple and the copy loop cannot drift.
  - [x] Rendering: `<h2>` precedes the summary, absent when there is no headline, HTML-escaped like the summary.
  - [x] Build output: exactly one `<h1>`, one `<h2>` per item, no `<h3>`, correct fonts on both levels.
  - [x] Closed a pre-existing gap: the Story 4.4 end-of-page check forbade `h1` after the End Screen but not `h2`.

- [x] **Task 6: Update the planning artifacts this story contradicts**
  - [x] `DESIGN.md`: Brand & Style, Typography, Components (new `item-headline` entry), Do's and Don'ts (anti-clickbait rule).
  - [x] `EXPERIENCE.md`: Information Architecture, Voice and Tone, Component Patterns, State Patterns, Interaction Primitives, and a heading-hierarchy rule the Accessibility Floor never had.
  - [x] Both `mockups/*.html`: un-concatenated the `h2` back out of the summary paragraph, updated CSS and header comments.
  - [x] `prd.md`: new `Headline` Glossary entry, FR-13 extended.
  - [x] `ARCHITECTURE-SPINE.md`: AD-12's ownership clause, AD-6 (with a note on why this is not the "while you're there" prompt addition it warns about), domain vocabulary table.
  - [x] `.memlog.md`: an `(override)` entry reversing the original removal.

## Dev Notes

### Why the headline is not the AD-6 violation it looks like

AD-6 explicitly warns against "model output leaking into selection, ordering, or counts through a 'while you're there' prompt addition" — and adding a second generated field to the same prompt is exactly that shape. The distinction is what the clause protects: selection, ordering, and counts are ranking's decisions, and a headline is none of them. It is display text for a Cluster already selected and already counted, produced by the same call, under the same corroboration rule, degrading by the same path. The AD's own note now states this so the next reader does not have to re-derive it.

### Why both fields degrade together

The adapter never returns a half-populated `ClusterText`, so `collect_summarize` makes one degrade decision covering both fields. The alternative — deciding independently — would let an item carry a real headline beside a fallback summary, which is invisible in the metadata because one counter covers both. The failure would look like working output.

### Why the Summary moved to the grotesque

DESIGN.md's Typography section already assigned Summaries to IBM Plex Sans (line 150) while also assigning them the serif (line 149) — a pre-existing internal contradiction that never mattered while the Summary was the only text in an item. With a serif headline above it, it matters: two stacked serif blocks read as one run-on paragraph, and the face change is what makes the headline scannable. Resolved in favour of line 150, which is also what the pre-correction `.working/` mockups showed.

### Previous Story Intelligence

- Story 5.4's Blind Hunter review caught a whitelist-style silent-drop bug of exactly this shape. That precedent is why `_SUMMARIZE_OWNED_FIELDS` got two dedicated tests rather than being trusted to the generic pass-through assertions, which only cover *cluster* fields and would never have touched a summarize-owned one.
- Every build-dependent `describe` block in `no-js-readable.test.ts` runs its own `astro build`, per Stories 5.1/5.2's own Blind Hunter-caught precedent. The new block follows it.
- Astro rewrites scoped selectors (`.item h2.headline` compiles to `.item[data-astro-cid-x] h2[data-astro-cid-x].headline`) and appends the attribute to tags, so build-output assertions must match tolerantly rather than pinning literal markup — the same class of quote/shape mismatch Epic 4 and Story 5.4 both hit.

### Project Structure Notes

Files this story creates or modifies:
- `pipeline/adapters/claude.py` (modified) — schema, prompt, `ClusterText`, structured parsing
- `pipeline/stages/summarize.py` (modified) — attaches `headline`, degrades both fields together
- `pipeline/stages/publish.py` (modified) — `_SUMMARIZE_OWNED_FIELDS`
- `pipeline/domain/__init__.py` (modified) — schema version bump
- `site/src/lib/briefing.ts`, `site/src/islands/period-switcher.ts` (modified) — optional `headline`
- `site/src/components/BriefingPage.astro` (modified) — `<h2>` markup and CSS
- `site/src/fixtures/*.json` (modified, 5 files) — 13 headlines
- Tests: `tests/test_claude_adapter.py`, `tests/test_summarize_stage.py`, `tests/test_publish_stage.py`, `tests/test_briefing_record.py`, `site/src/islands/__tests__/period-switcher.test.ts`, `site/e2e/no-js-readable.test.ts`
- Planning artifacts: `epics.md`, `prd.md`, `ARCHITECTURE-SPINE.md`, `DESIGN.md`, `EXPERIENCE.md`, `.memlog.md`, both `mockups/*.html`

### References

- [Source: epics.md#Story 6.1] — acceptance criteria origin
- [Source: ux-designs/.../.memlog.md] — the `(override)` entry this story reverses, and its stated reason
- [Source: ux-designs/.../.working/key-briefing-world-day.html] — the un-reverted pre-correction structure, showing intended headline length and register
- [Source: ARCHITECTURE-SPINE.md#AD-6, AD-12, Consistency Conventions] — text-only AI stage, single field ownership, "a schema change is a version bump, never a silent field edit"
- [Source: prd.md#FR-13, FR-14, §7] — corroboration, attribution, and the register rule the headline inherits
- [Source: pipeline/stages/publish.py:98] — the `_SUMMARIZE_OWNED_FIELDS` whitelist and its `if field in summarized` filter

## Dev Agent Record

### Context Reference

Story spec + a full pre-writing research pass over the planning artifacts (which established that the headline's removal was a data-contract concession rather than a product judgement, and that FR-13 would not have covered the new field) + direct reading of the summarize/publish/domain call chain, the two TypeScript renderers, and the existing test suites.

### Debug Log

- Initially assumed `_cluster()` in `test_publish_stage.py` took a `rank=` argument; it does not. Read the signature rather than continuing to guess.
- A scripted insertion of `_MERGE_DIAGNOSTIC_FLOOR` landed the constant *inside* an import statement, breaking the module. Repaired immediately, and the lesson is recorded here rather than hidden: edit structurally rather than scripting blind text insertion.
- The first build-output assertions failed on Astro's scoping attribute (`<h2 class="headline">` is never literal in the output, and `.item h2.headline` is not the compiled selector). Inspected the real `dist/` output and matched tolerantly.
- The end-of-page assertion initially sliced from the document's *first* `</p>`, which lands inside the first item's summary — item headlines legitimately follow it. Anchored on the End Screen itself.

### Completion Notes

- All six ACs are satisfied. AC2's register constraint is enforced at the prompt level and asserted in tests; it is not, and cannot be, mechanically verified against real model output without a live cycle — see the flagged gap below.
- The `_SUMMARIZE_OWNED_FIELDS` trap is the single most dangerous part of this change and is now covered by two tests, one of which cannot drift because it derives its assertions from the tuple.
- **Known, explicitly-flagged gap: no real headline has been generated yet.** Three cycles were run after this story shipped and none reached the summarize stage — see the Post-Story Findings section. Everything verified here is verified against fixtures, unit tests, and real build output; the model's actual headline quality, and the structured-output call against the live Batches API, remain unexercised.

### File List

- `pipeline/adapters/claude.py` (modified)
- `pipeline/stages/summarize.py` (modified)
- `pipeline/stages/publish.py` (modified)
- `pipeline/domain/__init__.py` (modified)
- `site/src/lib/briefing.ts` (modified)
- `site/src/islands/period-switcher.ts` (modified)
- `site/src/components/BriefingPage.astro` (modified)
- `site/src/fixtures/day.json`, `week.json`, `month.json`, `fallback-example.json`, `single-item-example.json` (modified)
- `tests/test_claude_adapter.py`, `tests/test_summarize_stage.py`, `tests/test_publish_stage.py`, `tests/test_briefing_record.py` (modified)
- `site/src/islands/__tests__/period-switcher.test.ts`, `site/e2e/no-js-readable.test.ts` (modified)
- `_bmad-output/planning-artifacts/epics.md`, `prds/.../prd.md`, `architecture/.../ARCHITECTURE-SPINE.md`, `ux-designs/.../DESIGN.md`, `ux-designs/.../EXPERIENCE.md`, `ux-designs/.../.memlog.md`, `ux-designs/.../mockups/*.html` (modified)

## Post-Story Findings: three bugs the first real cycles exposed

This story shipped before any real cycle had ever succeeded. Running one immediately exposed three defects, **none of them caused by this story** — all three predate it and were only reachable once a cycle got far enough to matter. Recorded here because this story is what surfaced them.

1. **`ANTHROPIC_API_KEY` was never injected into the cycle step.** The secret existed in the repository, but `collect.yml` passed only `COHERE_API_KEY`. Summarize degraded with "ANTHROPIC_API_KEY is not set" in all three languages and nothing was ever published. Fixed in `ab6e89b`.
2. **The shipped GDELT query was not parenthesized.** GDELT rejects `a OR b OR c` with *"Queries containing OR'd terms must be surrounded by ()."* — and returns that rejection as **HTTP 200 carrying an error string**, so the entire GDELT half of collection returned nothing while the run reported success. Every existing test in `test_gdelt_adapter.py` uses a single-term query with no `OR`, so nothing covered the one query the pipeline actually ships. Fixed in `ab6e89b`, with a regression test.
3. **A merged-nothing cycle was indistinguishable from a healthy one.** Both real cycles produced 358 dedupe groups → 358 Clusters, exactly 1:1. Nothing merged across sources, so no Cluster reached the 2-Independent-Source floor, zero were selected, and the cycle published nothing while still reporting success. The existing `degraded` flag only fires when the embedding call *errors*; an embedding call that succeeds and merges nothing produced the same barren outcome with no signal. The three "summarize submission failed" entries in `cycle.json` were a red herring — `submit_batch` returns `batch_id=None` for an empty Cluster list, which `cycle.py` cannot distinguish from a real failure. An explicit diagnostic was added in `ec14ed4`, gated on a real corpus size so small cycles and test fixtures are not false positives.

**Still open:** whether the 1:1 ratio is caused by a thin RSS-only corpus (GDELT was throttling with HTTP 429 on all three windows during these runs) or by a second defect in the clustering stage. The next cycle with a full GDELT corpus will distinguish the two.

## Change Log

- 2026-08-13: Story implemented, verified, and committed (`9aa1659`). 327 pytest, 196 vitest, tsc/astro check clean, ruff clean, boundary check passing. Two decisions taken with the user before implementation: FR-13 extended to cover headlines (rather than a sibling FR), and the ~260-character budget covering the Summary alone with the headline added on top.
- 2026-08-13: Three pre-existing bugs found by the first real cycles and fixed (`ab6e89b`, `ec14ed4`) — see Post-Story Findings. None caused by this story.
- 2026-08-13: Planning artifacts brought in line (`epics.md`, `prd.md`, `ARCHITECTURE-SPINE.md`, `DESIGN.md`, `EXPERIENCE.md`, `.memlog.md`, both mockups). Status set to `done`, with the no-real-headline-yet gap explicitly flagged rather than closed.
