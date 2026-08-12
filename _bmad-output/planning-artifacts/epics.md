---
stepsCompleted: ['step-01-validate-prerequisites', 'step-02-design-epics', 'step-03-create-stories', 'step-04-final-validation']
inputDocuments:
  - "_bmad-output/planning-artifacts/prds/prd-5-news-2026-08-10/prd.md"
  - "_bmad-output/planning-artifacts/architecture/architecture-5-news-2026-08-10/ARCHITECTURE-SPINE.md"
  - "_bmad-output/planning-artifacts/ux-designs/ux-5-news-2026-08-12/DESIGN.md"
  - "_bmad-output/planning-artifacts/ux-designs/ux-5-news-2026-08-12/EXPERIENCE.md"
---

# 5 News - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for 5 News, decomposing the requirements from the PRD and Architecture spine into implementable stories.

`bmad-ux` has run (2026-08-12), consistent with the PRD's Build Order placing the page fifth of six. The UX design contract (`DESIGN.md` + `EXPERIENCE.md`, "Wire & Ledger") is now a first-class input; Epic 4's stories were updated in place to reflect its decisions — the PRD's `[ASSUMPTION]` tags on the reading surface are resolved, not merely flagged.

## Requirements Inventory

### Functional Requirements

FR-1: Any visitor sees the World / day Briefing rendered on arrival, without authentication, configuration, or interaction.
FR-2: A reader can change the Period by clicking the period words in the title sentence, cycling day → week → month.
FR-3: A reader can change the Zone by clicking the zone words in the title sentence, selecting World, a Continent, or a supported Country (15 Zones in v1).
FR-4: A Briefing contains between 2 and 5 items, reflecting how many Events met the ranking threshold, never padded to a fixed count.
FR-5: After the last item of every Briefing, the reader sees an explicit statement that the Briefing is complete.
FR-6: The system orders Qualifying Clusters by Consensus Score and selects up to 5 for a Briefing. Deterministic, no AI. Independent Source volume leads; country count breaks ties.
FR-7: Each item displays the count of Independent Sources and the count of distinct countries that covered its Event.
FR-8: Each Briefing displays how many Articles were ingested and how many were kept (Discarded Volume).
FR-9: A reader can see which Sources and which countries make up an item's Consensus Score.
FR-10: The system counts republished agency dispatches once, so Consensus Scores reflect independent coverage. Three layers, v1 requirement.
FR-11: Every Briefing is generated in each supported Output Language, with Summaries written in that language irrespective of the languages of the underlying Articles.
FR-12: A reader receives a Briefing in one of the supported Output Languages, and can change it.
FR-13: A Summary states nothing that is not present in at least two concordant Articles within its Cluster.
FR-14: Every item displays visible attribution and a prominent outbound link to an original Article.
FR-15: The system generates all Briefings on a schedule and serves reader requests from the generated set (135 per cycle).
FR-16: When a Zone has too few Qualifying Clusters, the system serves the containing Continent's Briefing and states the substitution.
FR-17: A Continent Briefing contains at most 2 items from the same country.
FR-18: For week and month Periods, Articles describing the same ongoing Event across multiple ingest days belong to one Cluster.
FR-19: A served Briefing reflects a generation cycle recent enough for its Period, and survives a failed cycle.
FR-20: A reader can install 5 News to their device home screen and launch it as a standalone application.
FR-21: A reader with a working connection always sees the current Briefing, never a cached earlier one.

### NonFunctional Requirements

NFR-1: A Briefing reaches first contentful paint within 1 second at the 95th percentile on a typical mobile connection. No reader-facing path includes an AI, embedding, or third-party API call. `[ASSUMPTION: 1s p95 target]`
NFR-2: Generation cost scales with the number of Briefings, not the number of readers.
NFR-3: A failure or rate-limit block from any single upstream feed degrades coverage for the affected cycle without failing the pipeline or the served Briefings.
NFR-4: The page is readable and navigable without JavaScript for its core content, and meets WCAG 2.1 AA for contrast and keyboard navigation. `[ASSUMPTION: AA target]`
NFR-5: Content is acquired only via public APIs and published RSS feeds. No scraping.
NFR-6: Only the application shell and at most the reader's last-viewed Briefing are retained offline — never the full 135-Briefing matrix.

### Additional Requirements

Extracted from the Architecture spine. Each is an invariant that constrains how stories may be implemented, not a feature.

**Starter template:** none prescribed. The spine fixes Astro 7.2.0 as the site framework and gives a directory seed (`pipeline/`, `data/`, `site/`, `.github/workflows/`), but specifies no scaffold to clone. Epic 1 Story 1 is therefore repository and pipeline skeleton setup, not starter instantiation. The static hosting target is deliberately deferred (spine §Deferred) and is not a v1 blocker.

- **AD-1 / AD-2 — Two-half separation.** No code under `site/` may call an AI, embedding, ingestion, or third-party API at build or request time. The only interface between pipeline and site is JSON files under `data/briefings/`. Neither half imports the other.
- **AD-3 — Stage independence.** Each pipeline stage reads its input from disk and writes output to `data/intermediate/<stage>/`, and is invocable alone against a saved input. This is what makes the Build Order's inspection window possible.
- **AD-4 — Deterministic ranking.** No model call, no randomness, no wall-clock read, no map-iteration-order dependence. Re-running on identical input produces byte-identical output.
- **AD-5 — Count once, before ranking.** The dedupe stage is the only place that decides what counts as an Independent Source, and it runs before clustering. The count written into a Briefing is the count ranking used.
- **AD-6 — AI stage is text-only.** Its input is an already-ordered, already-counted Briefing. It may not add, remove, reorder, or renumber. A per-Cluster failure degrades that item to title + link; it never fails the Briefing.
- **AD-7 — Atomic publication.** The publish stage writes a complete Briefing set or nothing. A failed cycle leaves the previous set untouched.
- **AD-8 / AD-9 — Cache precedence and invalidation.** Briefings network-first with short timeout, assets cache-first, stale-while-revalidate forbidden on Briefing content. Each cycle stamps a build identifier into the service worker so its bytes change; old caches are deleted by name, with `skipWaiting` + `clients.claim`.
- **AD-10 — Partial-failure tolerance.** Every external adapter returns partial results plus a failure record. Only total ingestion failure aborts the cycle.
- **AD-11 — Two-phase resumable cycle.** The Batch API is asynchronous (up to 24h) and a scheduled job must exit. Phase one submits and exits; phase two polls, collects, and publishes. Neither phase blocks on an external service.
- **AD-12 — Single field ownership.** Every published field has exactly one producing stage: dedupe owns counts, cluster owns membership, rank owns ordering, summarize owns text, publish owns timestamps. Recomputing another stage's value is a defect even when the result matches.
- **AD-13 — Adapter boundary.** Stages depend on adapter interfaces in domain terms, never on a vendor SDK type. Rate limiting, retry, pagination, and batching live inside the adapter.
- **Stack (verified 2026-08-10):** Astro 7.2.0; GitHub Actions scheduled workflow; GDELT DOC 2.0 (no key, MAXRECORDS 250, ~1 req/5s); Cohere `embed-v4`; Claude `claude-haiku-4-5` via Batch API; HDBSCAN via scikit-learn ≥ 1.3.
- **Deliberately excluded:** `@vite-pwa/astro` (abandoned), Workbox, NewsAPI.org, any database. Prompt caching is unavailable on this workload (Haiku 4.5 needs a 4096-token minimum prefix; the summarization prompt is far shorter and would silently not cache).
- **Deferred by the spine, not to be invented in stories:** cross-cycle Cluster identity, deduplication layer internals and thresholds, intermediate-data retention, static hosting target, observability, archive/SEO surface.

### UX Design Requirements

`bmad-ux` has run. UX design contract: `{planning_artifacts}/ux-designs/ux-5-news-2026-08-12/DESIGN.md` + `EXPERIENCE.md` ("Wire & Ledger" — editorial-restraint register; single-page IA addressed by Language/Zone/Period). Every PRD-level `[ASSUMPTION]` affecting Epic 4 is now a settled decision, reflected directly in each story below:

- UX-DR1: Summary length target set to ~260 characters (midpoint of the PRD's 240–320 range) — "readable in one breath."
- UX-DR2: Output Language control placed top-right of the page header, outside and above the mad-libs sentence, rendered as `label-caps` text options (e.g. "FR · EN · ES") — keeps the sentence at exactly two blanks (Zone, Period).
- UX-DR3: Freshness timestamp rendered as literal text "Mis à jour à HH:MM" (in the reader's chosen Output Language, local time convention) — always real text content, never an icon-only tooltip (accessibility floor).
- UX-DR4: WCAG 2.1 AA confirmed as the accessibility floor — 4.5:1 minimum contrast for body text, 3:1 for the monospace Consensus figures, visible focus ring on every interactive element, `aria-live` announcement on mad-libs word change, `aria-expanded` on the Consensus chip.
- UX-DR5: Mad-libs word component — dotted underline in the `primary` accent color (the *only* interactive color on the page); click/`Enter`/`Space` cycles to the next value (Zone: World → 6 Continents → 8 Countries → World; Period: day → week → month → day); no-JS fallback renders as a plain link to the equivalent static route.
- UX-DR6: Consensus chip component — collapsed by default in `numeral` (monospace) typography on a `surface-container` background; expands inline (never a modal) on click/`Enter` to list contributing Sources and their countries; the listed count must always equal the displayed number.
- UX-DR7: Continent-fallback notice — a single `secondary`-colored (muted brick red) inline sentence directly beneath the mad-libs title, never a dismissible banner or toast; this is the *only* use of the secondary accent anywhere on the page.
- UX-DR8: End Screen component — a full-width hairline rule in `outline-variant` followed by a `label-caps` completion statement; nothing renders below it (no related content, no infinite scroll trigger).
- UX-DR9: Attribution — outlet name as visible plain text immediately followed by a solid-underlined outbound link, present on initial render, never behind hover/menu/disclosure.
- UX-DR10: Single-column editorial stack at every viewport (mobile-first, ~680px max content width on desktop via wider margins, never additional columns) — no dashboard-style multi-column grid.
- UX-DR11: Voice and tone — declarative, unapologetic sentences (see EXPERIENCE.md's Do/Don't table); never frames a thin Discarded Volume or a Continent fallback as a failure or an apology.

Superseded by this UX contract, no longer open: the 2–3 second network-timeout-before-cache-fallback assumption (PRD §4.5) — moot under this architecture, since every Briefing is a pre-generated static file with no client-side network fetch on the happy path (AD-1/AD-2); a genuinely offline reader's experience is Epic 5's PWA-caching scope, not Epic 4's.

### FR Coverage Map

Every FR maps to exactly one owning epic. Where an FR is delivered incrementally across two epics, the split is stated.

| FR | Epic | Delivered as |
| --- | --- | --- |
| FR-1 | Epic 4 | World / day Briefing rendered on arrival, no configuration |
| FR-2 | Epic 4 | Inline Period selector in the title sentence |
| FR-3 | Epic 4 | Inline Zone selector, 15 Zones |
| FR-4 | Epic 2 (rule) → Epic 4 (display) | Rank emits 2–5 items; the page renders however many it receives |
| FR-5 | Epic 4 | End Screen after the last item |
| FR-6 | Epic 2 | Deterministic ranking and selection |
| FR-7 | Epic 4 | Per-item Consensus Score display |
| FR-8 | Epic 4 | Discarded Volume display |
| FR-9 | Epic 4 | Source inspection |
| FR-10 | Epic 1 (layer 1) → Epic 2 (layers 2–3) | Syndication Detection, built in the order the PRD sequences |
| FR-11 | Epic 3 | Multilingual Summary generation |
| FR-12 | Epic 4 | Output Language selection |
| FR-13 | Epic 3 | Two-source corroboration |
| FR-14 | Epic 3 (data) → Epic 4 (display) | Attribution captured at summarize, rendered on the page |
| FR-15 | Epic 1 (collection) → Epic 3 (full cycle) | Scheduled precomputation, completed once summarize and publish exist |
| FR-16 | Epic 2 | Insufficient-coverage fallback to Continent |
| FR-17 | Epic 2 | Anti-concentration cap |
| FR-18 | Epic 2 | Cross-day Cluster continuity |
| FR-19 | Epic 3 | Briefing freshness and failed-cycle survival |
| FR-20 | Epic 5 | Installable application |
| FR-21 | Epic 5 | Freshness outranks the offline cache |

NFR coverage: NFR-2, NFR-3, NFR-5 are enforced in Epics 1–3 (pipeline). NFR-1 and NFR-4 in Epic 4 (page). NFR-6 in Epic 5 (offline).

## Epic List

Ordered by the PRD's §10 Build Order, not by §4 feature order. Each epic stands alone and enables the next without depending on it.

### Epic 1: A raw news stream you can look at

Ingestion runs on a schedule and writes what it collected to disk, with verbatim reprints already collapsed. The author can open the output and see what the world published — the first thing that has to be true before any judgment about importance means anything.

**FRs covered:** FR-10 (layer 1: near-duplicate title collapse), FR-15 (collection half)
**Enables:** everything. Nothing downstream can be evaluated without real ingested data.
**Standalone value:** the author can inspect real coverage volume and source diversity, and judge whether the upstream data supports the product's central claim at all.

### Epic 2: A top 5 that holds up

Clusters are formed, ranked deterministically by Consensus Score, and bounded by the product's edge rules. The remaining Syndication Detection layers land here, where their effect on ranking is visible.

**FRs covered:** FR-6, FR-10 (layers 2–3: wire metadata, rewrite detection), FR-16, FR-17, FR-18, FR-4 (the 2–5 rule)
**Depends on:** Epic 1's output.
**Standalone value:** the product's actual thesis, testable. A ranked list of Article titles with links is already useful — the brief says so explicitly.
**Gate:** SM-1 sits at the end of this epic. The interface is built only once the filter is credible.

### Epic 3: Complete Briefings, in three languages, published reliably

Selected Clusters become Summaries in French, English, and Spanish. The cycle becomes two-phase and resumable so the asynchronous Batch API cannot hang or lose a run, and publication becomes atomic so a failed cycle never destroys the last good output.

**FRs covered:** FR-11, FR-13, FR-14 (data), FR-15 (full cycle), FR-19
**Depends on:** Epic 2's ranked output.
**Standalone value:** 135 complete Briefings exist as files, regenerated daily and survivable. Everything the product promises exists — it just has no reader-facing surface yet.

### Epic 4: The mad-libs page

The reading surface. A visitor arrives and the day's Briefing is already there; two clickable words in the title sentence change what they see; the numbers that justify each item are on screen; the page ends.

**FRs covered:** FR-1, FR-2, FR-3, FR-4 (display), FR-5, FR-7, FR-8, FR-9, FR-12, FR-14 (display)
**Depends on:** Epic 3's published files.
**Standalone value:** the product, usable. This is where it becomes something the author can open every morning — the second success criterion.
**Note:** carries the PRD's open UX assumptions. Running `bmad-ux` before this epic would replace them with decisions.

### Epic 5: Installable, and safe offline

5 News installs to the home screen and survives a lost connection without ever showing yesterday's news as though it were today's.

**FRs covered:** FR-20, FR-21
**Depends on:** Epic 4's page and Epic 3's real published cycles — FR-21's freshness rule can only be tested against actual cycle boundaries.
**Standalone value:** the daily ritual gets an icon, and the commuter with no signal is served honestly rather than silently stale.

---

## Epic 1: A raw news stream you can look at

Ingestion runs on a schedule and writes what it collected to disk, with verbatim reprints already collapsed. The author can open the output and see what the world published. Nothing downstream can be judged before this is real.

### Story 1.1: Repository and pipeline skeleton

As the developer,
I want a repository whose structure enforces the pipeline/site separation from the first commit,
So that the two halves cannot accidentally couple as the code grows.

**Acceptance Criteria:**

**Given** an empty repository
**When** the skeleton is created
**Then** `pipeline/domain/`, `pipeline/adapters/`, `pipeline/stages/`, `pipeline/config/`, `data/briefings/`, `data/intermediate/`, and `site/` exist
**And** `data/intermediate/` is gitignored while `data/briefings/` is committed
**And** `pipeline/config/` declares the 15 Zones, 3 Periods, and 3 Output Languages as data, so adding a Zone is a config edit (AD-13, spine conventions)

**Given** the skeleton exists
**When** any module under `site/` imports from `pipeline/`, or any module under `pipeline/` imports from `site/`
**Then** a check fails in CI (AD-2)

**Given** a stage needs to run
**When** it is invoked from the command line with an input path
**Then** it runs alone, without any other stage present (AD-3)

### Story 1.2: Collect Articles from GDELT

As the developer,
I want ingested Articles written to disk as JSON Lines,
So that I can see what the world actually published before any judgment is applied to it.

**Acceptance Criteria:**

**Given** a Zone and a Period
**When** the collect stage runs
**Then** it writes one JSON Line per Article to `data/intermediate/collect/<cycle-id>/`
**And** each record carries title, publication timestamp, Source, Source country, and language, using Glossary field names

**Given** GDELT's constraints
**When** the adapter queries it
**Then** it respects `MAXRECORDS` 250 per query and paginates beyond it
**And** it rate-limits to no more than one request per 5 seconds (spine Stack)
**And** no vendor response shape appears outside `pipeline/adapters/` (AD-13)

**Given** GDELT returns an error or rate-limits mid-collection
**When** the stage completes
**Then** it writes the Articles it did retrieve plus a failure record naming what failed
**And** the stage exits successfully (AD-10, NFR-3)

### Story 1.3: Supplement collection with RSS feeds

As the developer,
I want major outlets' RSS feeds ingested alongside GDELT,
So that coverage does not depend on a single upstream whose limits I do not control.

**Acceptance Criteria:**

**Given** a configured list of feed URLs
**When** the collect stage runs
**Then** RSS Articles are written to the same JSON Lines output in the same shape as GDELT Articles
**And** each Article records which adapter produced it

**Given** one feed is unreachable or malformed
**When** collection completes
**Then** the other feeds' Articles are still written, and the failure is recorded (AD-10)

**Given** acquisition is running
**When** any adapter fetches content
**Then** it uses only public APIs and published feeds — no scraping (NFR-5)

### Story 1.4: Collapse verbatim reprints

As the developer,
I want Articles whose titles are near-identical collapsed to one Independent Source,
So that the cheapest and largest slice of wire-copy inflation is removed before I judge anything.

**Acceptance Criteria:**

**Given** two Articles from different Sources with near-identical titles
**When** the dedupe stage runs
**Then** they contribute 1 to the Independent Source count, not 2 (FR-10 layer 1)

**Given** the dedupe stage has run
**When** its output is inspected
**Then** each surviving record carries its Independent Source count and the distinct-country count
**And** those counts are the only counts any later stage will use (AD-5, AD-12)

**Given** an identical input file
**When** the stage is re-run
**Then** the output is byte-identical

### Story 1.5: Run the collection on a schedule

As the developer,
I want collection and deduplication to run daily without me starting it,
So that I accumulate real days of output to inspect rather than one-off samples.

**Acceptance Criteria:**

**Given** a scheduled GitHub Actions workflow
**When** the cycle fires
**Then** collect and dedupe run for World / day and commit their output
**And** the run's cycle identifier is derived from its UTC start instant (spine conventions)

**Given** a cycle fails
**When** the next cycle fires
**Then** it runs independently of the failed one, leaving previously committed output untouched

**Given** several days of cycles have run
**When** the author inspects the committed output
**Then** coverage volume and source diversity are readable without running any code

---

## Epic 2: A top 5 that holds up

Clusters are formed, ranked deterministically, and bounded by the product's edge rules. This is where the thesis becomes testable — and where SM-1 gates everything that follows.

### Story 2.1: Group Articles describing the same Event

As the developer,
I want Articles about one Event grouped into one Cluster across languages,
So that a Japanese and a French Article about the same event count as one story, not two.

**Acceptance Criteria:**

**Given** deduplicated Articles for a Zone and Period
**When** the cluster stage runs
**Then** it writes Clusters to `data/intermediate/cluster/<cycle-id>/`, each carrying its member Article identifiers
**And** Articles in different languages describing the same Event land in the same Cluster

**Given** the embedding adapter is used
**When** titles are embedded
**Then** the vendor client appears only inside `pipeline/adapters/` (AD-13)

**Given** clustering has run
**When** Independent Source counts are read
**Then** they come from the dedupe stage unchanged — the cluster stage does not recount (AD-12)

### Story 2.2: Rank Clusters deterministically

As the developer,
I want Qualifying Clusters ordered by Consensus Score with no AI involved,
So that the product's central judgment is reproducible and defensible.

**Acceptance Criteria:**

**Given** a set of Clusters
**When** the rank stage runs
**Then** only Qualifying Clusters are considered — at least 2 Independent Sources from at least 2 distinct countries
**And** ordering is by Independent Source count descending, then country count descending, then a stable tiebreak (FR-6)

**Given** identical input
**When** ranking is re-run
**Then** the output is byte-identical — no model call, no randomness, no wall-clock read, no map-iteration-order dependence (AD-4)

**Given** more than 5 Qualifying Clusters
**When** ranking completes
**Then** at most 5 are selected and the rest are counted toward Discarded Volume

**Given** fewer than 5 but at least 2 Qualifying Clusters
**When** ranking completes
**Then** exactly that many are selected, never padded (FR-4)

### Story 2.3: Detect wire copy by attribution metadata

As the developer,
I want agency dispatches identified by their attribution where the Source exposes it,
So that a Reuters dispatch republished under different headlines still counts once.

**Acceptance Criteria:**

**Given** Articles carrying wire-attribution metadata
**When** the dedupe stage runs
**Then** Articles attributed to the same agency dispatch within a Cluster contribute 1 to the Independent Source count (FR-10 layer 2)

**Given** a Source that exposes no attribution metadata
**When** the stage runs
**Then** that Article is treated as independent and the stage does not fail

**Given** this layer is added
**When** ranking runs on the same corpus as before
**Then** the change in ordering is inspectable against the previous cycle's output

### Story 2.4: Detect locally rewritten dispatches

As the developer,
I want a rewritten dispatch recognized as the same underlying report,
So that the displayed Consensus Score reflects independent reporting rather than syndication.

**Acceptance Criteria:**

**Given** two Articles that rewrite the same dispatch under different wording
**When** the dedupe stage runs
**Then** they contribute 1 to the Independent Source count, not 2 (FR-10 layer 3)

**Given** two Articles independently reporting the same Event
**When** the stage runs
**Then** they contribute 2 — the layer must not collapse genuine independent coverage

**Given** thresholds are involved
**When** they are chosen
**Then** they live in `pipeline/config/` and are tunable without a code change

### Story 2.5: Fall back to the Continent when a Country is too thin

As a reader who picks a small country,
I want to be shown the continent instead of an empty page,
So that a thin Zone degrades honestly rather than looking broken.

**Acceptance Criteria:**

**Given** a Country Zone with fewer than 2 Qualifying Clusters
**When** the Briefing is assembled
**Then** the containing Continent's Briefing is used instead (FR-16)
**And** the substitution is recorded in the Briefing data so the page can state it

**Given** a substitution occurred
**When** the Briefing is read
**Then** both the requested Zone and the served Zone are present — the substitution is never silent

### Story 2.6: Cap per-country concentration in Continent Briefings

As a reader selecting a continent,
I want no single country to dominate the list,
So that "Africa" does not mean "Nigeria" and the continental selector keeps its meaning.

**Acceptance Criteria:**

**Given** a Continent Briefing with more than 2 Qualifying Clusters from one country
**When** ranking completes
**Then** at most 2 from that country are included, and the next-ranked Clusters from other countries take the remaining places (FR-17)

**Given** a World Briefing
**When** ranking completes
**Then** the cap is not applied (PRD Open Question 5 — watch this during the inspection window)

### Story 2.7: Link Clusters across ingest days

As a reader choosing week or month,
I want an ongoing story to appear once rather than once per day,
So that a week's Briefing is five events, not the same event five times.

**Acceptance Criteria:**

**Given** an Event covered on three consecutive ingest days
**When** a week Briefing is assembled
**Then** it appears once, with a Consensus Score aggregating all three days' Independent Sources (FR-18)

**Given** a month Briefing
**When** it is assembled
**Then** no two items describe the same Event

**Given** a day Briefing
**When** it is assembled
**Then** cross-day linking does not apply — its window is a single ingest day

---

## Epic 3: Complete Briefings, in three languages, published reliably

Selected Clusters become Summaries in French, English, and Spanish. The cycle becomes two-phase so an asynchronous batch cannot hang it, and publication becomes atomic so a failure never destroys the last good output.

### Story 3.1: Summarize selected Clusters in one language

As a reader,
I want each item written as readable prose rather than a bare headline,
So that I understand what happened without opening the source.

**Acceptance Criteria:**

**Given** a ranked Briefing
**When** the summarize stage runs
**Then** each Cluster receives Summary text keyed to its identity (FR-11)
**And** the stage adds, removes, reorders, and renumbers nothing (AD-6)

**Given** a Summary is generated
**When** it is checked against its Cluster
**Then** it states nothing absent from at least two concordant Articles in that Cluster (FR-13)
**And** no synthesized statement is attributed to a named outlet

**Given** summarization fails for one Cluster
**When** the Briefing is assembled
**Then** that item degrades to its Article title and outbound link, and the Briefing still publishes (AD-6)

### Story 3.2: Generate every Briefing in all three Output Languages

As a reader,
I want the Japanese press's account in my own language,
So that I can read what a country's press converged on without reading that language.

**Acceptance Criteria:**

**Given** a ranked Briefing whose Articles are in any languages
**When** summarization runs
**Then** Summaries are produced in French, English, and Spanish (FR-11)
**And** a Cluster composed entirely of Japanese Articles yields a French Summary in the French Briefing

**Given** the full matrix
**When** a cycle completes
**Then** 135 Briefings exist: 15 Zones × 3 Periods × 3 Output Languages (FR-15)

### Story 3.3: Capture attribution and outbound links

As a reader,
I want to see who reported this and reach the original in one click,
So that the Summary is a trailer rather than a substitute.

**Acceptance Criteria:**

**Given** a Briefing item
**When** it is written to disk
**Then** it carries at least one outbound link to an original Article, with its Source name (FR-14)

**Given** the Consensus Score is recorded
**When** the item is written
**Then** the contributing Independent Sources and their countries are recorded, so the page can show them (supports FR-9)

### Story 3.4: Split the cycle into two resumable phases

As the developer,
I want the batch submission and its collection to be separate runs,
So that an asynchronous batch can never hang a job or lose a cycle.

**Acceptance Criteria:**

**Given** phase one runs
**When** it reaches summarization
**Then** it submits the batch, writes the batch identifier to `data/intermediate/<cycle-id>/cycle.json`, and exits (AD-11)

**Given** phase two runs and finds a pending batch identifier
**When** the batch has completed
**Then** it collects the results, assembles Briefings, and publishes

**Given** phase two runs and the batch is not yet complete
**When** it checks
**Then** it exits without publishing, leaving the previous Briefing set in place, and a later run resumes the same batch

**Given** any phase
**When** it runs
**Then** it never blocks a process waiting on an external service

### Story 3.5: Publish atomically and survive a failed cycle

As a reader,
I want the site to keep working when a generation cycle fails,
So that I never meet an error page or a half-written Briefing.

**Acceptance Criteria:**

**Given** a complete set of assembled Briefings
**When** the publish stage runs
**Then** it writes the whole set or writes nothing (AD-7)
**And** each Briefing carries the generation timestamp of its cycle (FR-19)

**Given** a cycle fails at any stage
**When** the site is served
**Then** the previous Briefing set is still present and unmodified (FR-19, NFR-3)

**Given** a day Period
**When** cycles run
**Then** its Briefings are regenerated at least once per day

### Story 3.6: Keep generation cost independent of readership

As the developer,
I want AI cost bounded by the Briefing matrix rather than by traffic,
So that the product cannot become expensive by becoming popular.

**Acceptance Criteria:**

**Given** a generation cycle
**When** summarization runs
**Then** requests are submitted through the Batch API (NFR-2)

**Given** any number of readers
**When** they request Briefings
**Then** no AI, embedding, or ingestion call occurs in the reader's path (NFR-2, AD-1)

**Given** a cycle completes
**When** its cost is measured
**Then** it scales with the number of Briefings generated, not with traffic

---

## Epic 4: The mad-libs page

The reading surface. A visitor arrives and the Briefing is already there; two clickable words change what they see; the numbers that justify each item are on screen; the page ends.

*UX design contract: `{planning_artifacts}/ux-designs/ux-5-news-2026-08-12/DESIGN.md` + `EXPERIENCE.md` ("Wire & Ledger"). Every acceptance criterion below reflects a settled decision from that contract, not a PRD assumption — see the UX Design Requirements (UX-DR1–11) above for the full list and rationale. Mockups: `mockups/briefing-world-day.html`, `mockups/briefing-fallback.html`.*

### Story 4.1: Render the World / day Briefing on arrival

As a first-time visitor,
I want the day's news already on screen when the page loads,
So that I get value before doing any work.

**Acceptance Criteria:**

**Given** any visitor with no prior state
**When** the page loads
**Then** the World / day Briefing is present in the initial response, with no client-side fetch required (FR-1)
**And** no onboarding, cookie wall, or preference prompt precedes it

**Given** the page is built
**When** the build runs
**Then** it reads only `data/briefings/*.json` and calls no external service (AD-1, AD-2)

**Given** a typical mobile connection
**When** the page loads
**Then** first contentful paint occurs within 1 second at the 95th percentile (NFR-1)

**Given** JavaScript is unavailable
**When** the page loads
**Then** the Briefing content is readable, and the mad-libs words render as plain links to the equivalent static route for their next cycle value (NFR-4, EXPERIENCE.md State Patterns: "Cold load")

**Given** the page renders in any supported Output Language
**When** the layout is composed
**Then** it follows the single-column editorial stack (UX-DR10): header, mad-libs sentence, item list, Discarded Volume, End Screen, in that fixed order, never a multi-column grid at any viewport

### Story 4.2: Change the Period by clicking a word

As a returning reader,
I want to switch between day, week, and month by clicking the sentence,
So that the control explains itself without labels or a submit button.

**Acceptance Criteria:**

**Given** a rendered Briefing
**When** the reader clicks the period word in the title sentence
**Then** the Period cycles day → week → month → day and the Briefing is replaced (FR-2)
**And** the sentence text updates to match

**Given** the mad-libs word component (UX-DR5)
**When** it renders
**Then** it shows a dotted underline in the `primary` accent color — the only interactive color on the page — visually distinct from the solid-underlined attribution links (DESIGN.md Components)

**Given** a Period is selected
**When** the URL is read
**Then** it reflects the selection, so a Briefing can be linked directly

**Given** the reader changes Period
**When** the new Briefing renders
**Then** it renders within the same latency bound as first load (NFR-1), and the sentence/item-list swap in place without a full navigation flash when JavaScript is present (EXPERIENCE.md State Patterns: "Zone/Period change (JS present)")

### Story 4.3: Change the Zone by clicking a word

As an expatriate reader,
I want to switch between World, a continent, and a country the same way,
So that following two places costs two clicks.

**Acceptance Criteria:**

**Given** a rendered Briefing
**When** the reader clicks the zone word
**Then** they can cycle through World, the 6 Continents, and the 8 supported Countries — 15 Zones (FR-3)
**And** the Briefing is replaced and the URL reflects the selection

**Given** a Country Zone that fell back to its Continent
**When** the Briefing renders
**Then** the page states the substitution via the Continent-fallback notice (FR-16, UX-DR7): a single `secondary`-colored (muted brick red) inline sentence directly beneath the mad-libs title, never a dismissible banner or toast — this is the only use of that accent color anywhere on the page

### Story 4.4: Show a variable number of items and end the page

As an anxious reader,
I want the page to end and tell me so,
So that I know I am finished rather than wondering what is below.

**Acceptance Criteria:**

**Given** a Briefing with 3 items
**When** it renders
**Then** 3 items appear with no placeholders (FR-4)

**Given** any Briefing
**When** the last item has rendered
**Then** an explicit End Screen (UX-DR8) states the Briefing is complete (FR-5): a full-width hairline rule in `outline-variant` followed by a `label-caps` completion statement
**And** no further content, recommendation, related item, or infinite-scroll trigger appears below it

**Given** a Briefing with a single dominating item
**When** it renders
**Then** that item's block takes whatever vertical space its content needs (content-driven height) rather than being capped to look like a multi-item layout

**Given** a Briefing on a standard mobile viewport
**When** it renders
**Then** each Summary targets ~260 characters (UX-DR1, the midpoint of the PRD's suggested range) so items fit with minimal scrolling, each readable in one breath

### Story 4.5: Show why each item is here

As a sceptical reader,
I want the criterion stated as a number I can inspect,
So that I can disagree with it rather than having to trust it.

**Acceptance Criteria:**

**Given** a Briefing item
**When** it renders
**Then** it shows the Independent Source count and the distinct-country count as a Consensus chip (UX-DR6) in the form *N independent sources · M countries*, set in the reserved monospace `numeral` typography token (FR-7)
**And** those are the counts the ranking used, not raw Article counts (AD-5, AD-12)

**Given** a Briefing
**When** it renders
**Then** the Discarded Volume appears once, at the foot of the item list, in plain text with two numeral-styled counts ("1,247 ingested → 5 kept") (FR-8)

**Given** a reader clicks or presses Enter on the Consensus chip
**When** it expands
**Then** it expands inline — never a modal — listing the contributing Sources and their countries, and their number equals the displayed count exactly; this is a hard rendering guarantee, not a best-effort display (FR-9, UX-DR6)

### Story 4.6: Attribute every item and link out

As a publisher whose reporting is summarized,
I want visible attribution and a prominent link to my article,
So that the Summary sends readers to the original rather than replacing it.

**Acceptance Criteria:**

**Given** a Briefing item
**When** it renders
**Then** the outlet name is visible as plain text immediately followed by a solid-underlined outbound link to an original Article, present on initial render — not behind a menu, hover state, or the Consensus chip's expansion (FR-14, UX-DR9)

**Given** a Summary
**When** it is read
**Then** no synthesized statement is attributed to a named outlet

### Story 4.7: Choose the reading language

As a reader whose language is not the site default,
I want the Briefing in my language,
So that the foreign-press promise actually reaches me.

**Acceptance Criteria:**

**Given** a first arrival
**When** the page loads
**Then** the Output Language is chosen from the browser's language preference, falling back to English when none of the three matches (FR-12)

**Given** a reader changes the Output Language
**When** the Briefing re-renders
**Then** it is in that language, and the URL reflects it — the URL segment is the only persistence mechanism in v1, so a bookmarked or shared link always reproduces the same language regardless of the visiting browser's preference (EXPERIENCE.md State Patterns: "Language explicitly chosen")

**Given** the mad-libs sentence
**When** the language control is placed
**Then** it sits top-right of the page header, outside and above the sentence, rendered as `label-caps` text options (e.g. "FR · EN · ES") with the active one in the `primary` accent color — keeping the sentence at exactly two blanks (UX-DR2)

### Story 4.8: Meet the accessibility target

As a reader using assistive technology,
I want the page navigable and legible,
So that the product is usable beyond its default reader.

**Acceptance Criteria:**

**Given** the rendered page
**When** it is audited
**Then** contrast and keyboard navigation meet WCAG 2.1 AA (UX-DR4, NFR-4): 4.5:1 minimum contrast for body text, 3:1 for the monospace Consensus figures at minimum rendered size, a visible focus ring (never `outline: none`) on every interactive element

**Given** the mad-libs selectors
**When** navigated by keyboard
**Then** each is reachable, operable via Enter/Space, and announces its role and current value via `aria-live` on change (e.g. "Zone, World, button, cycles to Europe") — not just its visible text

**Given** the Consensus chip
**When** it expands or collapses
**Then** the state change is announced via `aria-expanded`, and the newly revealed source list is reachable in the same tab sequence, never skipped

**Given** the freshness timestamp
**When** it renders
**Then** the reader can see when the Briefing was generated, as literal text "Mis à jour à HH:MM" (or the equivalent in the active Output Language) — never an icon-only tooltip (UX-DR3, FR-19)

---

## Epic 5: Installable, and safe offline

5 News installs to the home screen and survives a lost connection without ever presenting yesterday's news as today's.

### Story 5.1: Make the application installable

As a daily reader,
I want 5 News on my home screen,
So that opening it is a gesture rather than a search.

**Acceptance Criteria:**

**Given** the site is served over HTTPS
**When** a supporting browser loads it
**Then** a web application manifest is served with name, icons, theme colour, and standalone display mode (FR-20)
**And** installation is offered without further configuration

**Given** the installed application
**When** it is launched
**Then** it opens the World / day Briefing in the reader's Output Language, identically to a browser visit (FR-1)

**Given** installation
**When** it completes
**Then** no notification permission is requested and nothing is sent (PRD §9.2)

### Story 5.2: Serve fresh content first, cache only as a fallback

As a reader opening the app in the morning,
I want today's Briefing, not yesterday's from cache,
So that the product's central promise is not silently broken.

**Acceptance Criteria:**

**Given** a working connection
**When** the reader opens the application
**Then** Briefing content is fetched from the network first, and the cache is used only after the network fails or exceeds a short timeout `[ASSUMPTION: 2–3s — tune against real mobile conditions]` (FR-21, AD-8)

**Given** a new cycle has published
**When** a returning reader opens the application
**Then** they see that cycle's Briefing, not the previous one

**Given** hashed assets
**When** they are requested
**Then** they are served cache-first (AD-8)

**Given** any implementation
**When** the caching strategy is reviewed
**Then** stale-while-revalidate is not used for Briefing content — it would guarantee the first paint is yesterday's (AD-8)

### Story 5.3: Invalidate the cache on every published cycle

As a reader,
I want a new cycle to take effect on the visit that discovers it,
So that I am never one visit behind.

**Acceptance Criteria:**

**Given** a published cycle
**When** the service worker is generated
**Then** the cycle's build identifier is stamped into it, so its bytes differ from the previous cycle's (AD-9)

**Given** a new service worker is discovered
**When** it activates
**Then** caches whose name does not carry the current identifier are deleted
**And** `skipWaiting` and `clients.claim` are used so the update lands on the current visit, not the next one (AD-9)

### Story 5.4: Serve an honest offline experience

As a commuter in a tunnel,
I want to know that what I am reading is from an earlier cycle,
So that I am not misled about what is current.

**Acceptance Criteria:**

**Given** no connection
**When** the reader opens the application
**Then** the last-viewed Briefing is served from cache
**And** the page states that it is from an earlier cycle, with its generation timestamp (FR-21, FR-19)

**Given** the offline cache
**When** its contents are inspected
**Then** it holds the application shell and at most the reader's last-viewed Briefing — never the full 135-Briefing matrix (NFR-6)

**Given** no connection and no cached Briefing
**When** the reader opens the application
**Then** they see a stated offline condition rather than a blank page or a browser error
