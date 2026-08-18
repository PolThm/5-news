---
baseline_commit: 07b3d25
---

# Story 6.2: Collect from GDELT's raw files instead of its search API

Status: ready-for-dev

## Story

As a reader,
I want the five items chosen from the whole world's coverage rather than eleven feeds,
So that "the most corroborated story today" means something.

## Scope, decided explicitly before this story was written

**The DOC 2.0 API has never once succeeded in production, and it is the wrong tool by GDELT's own account.** Across all eight recorded cycles (2026-08-13 through 2026-08-17) every single one carries a GDELT failure — HTTP 429 or a timeout — and the article count never moves off the RSS ceiling (360–371). Measured directly on 2026-08-18: roughly **one request in six** succeeds even at a 6-second interval, the throttle is per-IP and sticky, the cooldown runs about a minute, and there is **no `Retry-After` header** for a backoff to key on. GDELT's own 429 body names the fix: *"All high-traffic users should switch to our ngrams dataset."* The DOC API is an interactive search endpoint; this pipeline uses it as an ingestion channel, which is the mismatch.

**GDELT itself is healthy — only our channel is wrong.** The blog posted on 2026-08-13, `lastupdate.txt` serves files minutes old, and the 15-minute pipeline runs normally. This story does not replace the data source; it replaces how we read it.

**The raw files carry everything the pipeline needs, including the title — but not where the column list suggests.** The GKG has 27 tab-separated columns and **no title column**. The title lives inside `Extras` (column 27) as `<PAGE_TITLE>…</PAGE_TITLE>`, present on **100% of rows** in both files sampled. `ArticleRecord.title` is required, so this detail is load-bearing: miss it and the migration cannot work at all. Titles are in the article's own language and carry numeric HTML entities (`&#xE9;`) that must be decoded.

**Two files per slot, not one.** `.gkg.csv.zip` is English-only (913 rows in the sampled slot, 187 distinct sources). `.translation.gkg.csv.zip` is the multilingual companion (3,442 rows) and is where French and Spanish coverage lives — 140 `fra` and 256 `spa` in that one slot. A product publishing in three languages needs both.

**Volume forces a sampling decision, and the user made it.** All 96 slots of a day would be ~418,000 articles and ~1.7 GB — a thousandfold increase over today's ~365, and impossible inside a 30-minute job. **Decision: fetch 8 slots spaced 3 hours apart.** Measured cost: 2.25s and 17 MB per slot, so ~18s and ~136 MB for eight — comfortably inside `MAX_COLLECTION_SECONDS`. The tradeoff, stated rather than hidden: an event breaking between two sampled slots is seen by fewer outlets than it would be with full coverage, so its Consensus Score understates reality. Sampling evenly across the day is what keeps that bias from favouring one timezone.

**RSS is removed entirely, on the user's explicit decision, and this carries a real risk worth recording.** RSS has succeeded in 8 of 8 cycles while GDELT failed in 8 of 8; the product currently runs *only* because of RSS. Removing it means a GDELT outage publishes nothing at all (the previous Briefing set stays in place per AD-7, so readers see stale-but-honest content rather than an empty page). The user was shown this and chose replacement anyway — the new channel is static files rather than a throttled API, and measured 8/8 slot availability. Recorded here so the decision is traceable if it needs revisiting.

**Out of scope:** the Discarded Volume bug found while investigating (published Briefings show `discarded_ingested: 0` / `discarded_kept: 0` despite 366 articles reviewed for 5 kept — FR-8 is a core evidence claim and is currently reporting nothing). It predates this story and deserves its own. Also out of scope: the `query error` misclassification of valid JSON in the DOC adapter, which becomes moot once the DOC path is gone.

## Acceptance Criteria

1. **Given** a scheduled cycle, **when** collection runs, **then** it fetches GDELT's raw 15-minute files rather than calling the DOC 2.0 API, **and** no request in the cycle is subject to the DOC API's per-IP throttle.
2. **Given** the raw files, **when** they are parsed, **then** each Article carries a real title extracted from `Extras`' `<PAGE_TITLE>` with HTML entities decoded, **and** a row without a usable title is skipped rather than admitted with a placeholder.
3. **Given** a day's collection, **when** slots are chosen, **then** 8 slots evenly spaced across the preceding 24 hours are fetched, from both the English and the translingual file, **and** the whole collection stays within `MAX_COLLECTION_SECONDS`.
4. **Given** a slot file that is missing, malformed, or times out, **when** collection runs, **then** that slot degrades with a recorded failure and the remaining slots still contribute (AD-10), **and** only a total failure to fetch any slot aborts the cycle.
5. **Given** the collected Articles, **when** they reach dedupe, **then** they carry the same `ArticleRecord` shape as before — title, url, published_at, source, source_country, language, collected_by — so no downstream stage changes (AD-13).
6. **Given** the RSS adapter is removed, **when** the cycle runs, **then** `collect_all` sources exclusively from GDELT, **and** no dead RSS code, config, or test remains.

## Tasks / Subtasks

- [ ] **Task 1: Fetch and parse one raw slot** (AC1, AC2)
  - [ ] New fetch path for `data.gdeltproject.org/gdeltv2/<timestamp>.gkg.csv.zip` and `.translation.gkg.csv.zip`; unzip in memory rather than to disk.
  - [ ] Parse as TSV with `csv.field_size_limit` raised — rows carry very large fields (GCAM, V2Themes) and the default limit raises.
  - [ ] Extract title from column 27 (`Extras`) via `<PAGE_TITLE>`; decode HTML entities; skip the row if absent or empty after stripping.
  - [ ] Map to `ArticleRecord`: `DocumentIdentifier`→url, `SourceCommonName`→source, `DATE`→published_at (UTC), language from `TranslationInfo`'s `srclc:` (absent ⇒ English), `collected_by="gdelt"`.
  - [ ] Derive `source_country` — check what the existing RSS `Feed` table and `_slugify_country` already do so the slug vocabulary stays identical; `V2Locations` is a candidate but verify rather than assume.

- [ ] **Task 2: Slot selection across 24 hours** (AC3)
  - [ ] 8 slots at 3-hour spacing, each rounded down to the nearest 15 minutes (the only valid timestamps).
  - [ ] Named constant with the measured basis in its comment (2.25s / 17 MB per slot), not a bare literal.
  - [ ] Keep the existing wall-clock deadline honoured across the whole collection.

- [ ] **Task 3: Per-slot degradation** (AC4)
  - [ ] A 404 (slot not yet published), a bad zip, a short read, or a timeout degrades that slot only, with a `Failure` naming which slot and why.
  - [ ] Deduplicate on URL across slots and across the two files — the same article legitimately appears in more than one slot.

- [ ] **Task 4: Remove RSS** (AC6)
  - [ ] Delete `pipeline/adapters/rss.py`, its tests, and the `RssClient` call in `collect_all`.
  - [ ] Update `collect_all`'s docstring, which currently explains why there are *two* independent adapters — that rationale changes and must not be left stale.
  - [ ] Grep for every remaining reference (`FEEDS`, `RssClient`, `collected_by="rss"`) including in planning artifacts.

- [ ] **Task 5: Retire the DOC 2.0 path** (AC1)
  - [ ] Remove `collect_world_day`, the bisection/saturation machinery, and the retry/backoff built for the throttle. Keep `parse_seendate`, `_slugify_country`, and `_language_code` if the new parser reuses them.
  - [ ] `MIN_WINDOW`, `MAX_REQUESTS_PER_COLLECTION`, and the 429 handling exist only for the DOC API; delete what no longer has a caller rather than leaving it dormant.
  - [ ] Keep `MAX_COLLECTION_SECONDS` — it still bounds the new path.

- [ ] **Task 6: Tests**
  - [ ] Fixture-driven parsing: a real trimmed slice of both file types, committed, so tests never touch the network (the existing adapter tests' own convention).
  - [ ] Title extraction: present, absent, entity-encoded, empty-after-strip.
  - [ ] Language mapping: native English (no `TranslationInfo`) and a translated row.
  - [ ] Degradation: 404, corrupt zip, timeout — each degrades one slot, never the cycle.
  - [ ] Cross-slot URL deduplication.
  - [ ] Full verification: `ruff check` / `ruff format --check` / `pytest` / `check-boundary.sh`, plus the site suite unchanged (this story touches no site code).

- [ ] **Task 7: Update the artifacts this story contradicts**
  - [ ] `ARCHITECTURE-SPINE.md` Stack line names "GDELT DOC 2.0 (no key, MAXRECORDS 250, ~1 req/5s)" — replace with the raw-file channel.
  - [ ] `epics.md` Story 1.2 ("Collect articles from GDELT") and Story 1.3 ("Supplement collection with RSS feeds") both describe the retired design; note the supersession rather than rewriting shipped history.
  - [ ] `README.md` says "GDELT + 11 RSS feeds" in the architecture diagram and mentions the 429s in Status.

## Dev Notes

### Why the title hides in `Extras`

The GKG's documented column list has no title field, so the obvious read of the schema says this migration is impossible — that was my own first conclusion. It is wrong: `Extras` carries `<PAGE_TITLE>`, populated on 100% of rows in both sampled files. Verify this holds on the fixtures you commit rather than trusting the sample.

### Why both files, not just the English one

`.gkg.csv.zip` is English-only. Every French and Spanish article comes from `.translation.gkg.csv.zip`. Fetching only the first would produce a product whose French and Spanish Briefings are assembled entirely from English-language coverage — the exact defect the user reported on 2026-08-13.

### Why sampling is a product decision, not a technical one

Eight slots is a coverage/cost tradeoff the user chose after seeing the numbers, not a tuning constant. An event breaking between sampled slots gets a lower Consensus Score than full coverage would give it. If coverage later looks wrong, revisit the slot count deliberately — don't nudge it.

### Previous Story Intelligence

- Story 6.1's cycles exposed five bugs in sequence, each hidden by the previous one, two of them introduced by the fixes themselves. The lesson that generalises: after changing collection, verify the *whole* chain to a published Briefing rather than the stage you touched.
- Three files a resumed cycle re-reads (`ranked.jsonl`, `zone_rankings.json`, `summarized.jsonl`) are committed exceptions in `.gitignore`. A collection change that alters intermediate paths must not break them.
- GDELT returns errors as **HTTP 200 with a text body**. The raw-file channel should not inherit that assumption, but do check what a missing slot actually returns rather than assuming 404.

### Project Structure Notes

- `pipeline/adapters/gdelt.py` (heavily modified) — raw-file fetch/parse replaces the DOC API client
- `pipeline/adapters/rss.py` (deleted)
- `pipeline/stages/collect.py` (modified) — single adapter
- `tests/test_gdelt_adapter.py` (rewritten), `tests/test_rss_adapter.py` (deleted)
- `tests/fixtures/` (new) — trimmed real slices of both GKG file types
- Planning artifacts per Task 7

No changes to `site/`.

### References

- [Source: measured 2026-08-18] — 913 English + 3,442 translingual rows/slot; 100% title coverage; 187 sources; 2.25s and 17 MB per slot; 8/8 slots available
- [Source: measured 2026-08-18] — DOC API: ~1 request in 6 succeeds at 6s spacing, ~1 min sticky per-IP cooldown, no `Retry-After`
- [Source: GDELT 429 response body] — "All high-traffic users should switch to our ngrams dataset"
- [Source: data/intermediate/*/cycle.json, 8 cycles] — GDELT failed in every one; article count pinned to the RSS ceiling
- [Source: ARCHITECTURE-SPINE.md#AD-10, AD-13] — partial-failure tolerance; adapters expose domain types, never vendor shapes

## Dev Agent Record

### Context Reference

_To be filled by the dev agent._

### Debug Log

_To be filled by the dev agent._

### Completion Notes

_To be filled by the dev agent._

### File List

_To be filled by the dev agent._

## Change Log

- 2026-08-18: Story created. Investigated GDELT's health before assuming the API was at fault: the project is actively maintained and its raw pipeline is current — only our channel was wrong. Verified the raw file format hands-on, including the non-obvious fact that the title lives in `Extras` rather than a column of its own, and that French/Spanish coverage requires the separate translingual file. Two decisions taken with the user: 8 slots at 3-hour spacing (from measured per-slot cost), and full removal of RSS despite its 8-of-8 reliability record against GDELT's 0-of-8 — recorded with its risk rather than presented as free.
