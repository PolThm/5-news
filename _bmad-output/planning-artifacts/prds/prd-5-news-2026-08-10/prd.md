---
title: 5 News
status: final
created: 2026-08-10
updated: 2026-08-10
---

# PRD: 5 News
*Working title — confirm. Candidates and rationale in the brief addendum.*

## 0. Document Purpose

This PRD is for the author, who is also the sole developer, and for the downstream UX, architecture, and epic workflows that will consume it. It builds on `_bmad-output/planning-artifacts/briefs/brief-5-news-2026-08-10/brief.md` and its addendum, which hold the product rationale, the source-landscape research, the full personas, and the rejected-alternative record. This document does not repeat them; it converts settled decisions into testable requirements. Implementation choices stay in the addendum.

Structure: Glossary-anchored vocabulary, features grouped with globally numbered FRs nested beneath them, assumptions tagged inline and indexed at the end. **§10 Build Order overrides the section order of §4.**

## 1. Vision

5 News shows two to five Events per day, chosen because the world's press converged on them, summarized in the reader's language. Then the page ends.

The product is the filter, not the Summary. A ranked list of five raw Article titles with links is already useful; five AI Summaries of arbitrarily chosen stories are worthless. The engineering effort goes into clustering Articles that describe the same Event and ranking those Clusters by how much of the world's press covered them. The AI runs last, on Clusters a deterministic pipeline has already selected, so the product's central judgment has no hallucination surface.

Importance is measured, not judged. An Event ranks because 34 Independent Sources across 12 countries covered it, and that Consensus Score is displayed on every item. This answers the question the product cannot dodge — *who decides what is important?* — with an inspectable number rather than an editorial claim.

## 2. Target User

### 2.1 Jobs To Be Done

- **Functional** — know what happened in the world today, in under two minutes, without deciding what to read.
- **Emotional** — be up to date without the anxiety and guilt that news feeds produce. The benefit is calm, not information.
- **Social** — not be caught out in a conversation or a meeting.
- **Contextual** — recover after an absence (a trip, burnout, a month offline) without scrolling backwards through a feed.
- **Builder's** — the author wants this to exist for himself. If he does not open it every morning, it has failed.

### 2.2 Non-Users (v1)

- Readers who want depth on a single story. 5 News points at the original and gets out of the way.
- News professionals monitoring a beat. The product deliberately shows less.
- Readers wanting personalized or topical feeds. Importance here is collective, not individual.

### 2.3 Key User Journeys

- **UJ-1. Claire opens the page and is done in ninety seconds.**
  Claire, 34, deleted her news apps a year ago and still feels guilty about it. Unauthenticated, first visit of the day, desktop browser. She lands on the page and the Briefing is already there — no configuration, no onboarding. Four items today, not five. She reads them top to bottom without scrolling. Below the last one: *That's all. Come back tomorrow.* She reaches the end of the news and the page confirms she is finished — the thing no feed has ever told her — then closes the tab, informed and not anxious.
  *Edge case:* on a day with one dominating Event she sees a single item filling the screen, and understands that today had one story rather than that the page failed to load.

- **UJ-2. Rémi changes two words and reads the Japanese press in French.**
  Rémi, French, living in Singapore for three years, follows both his home country and the region he lives in. Unauthenticated, arrives on the World / day default. He clicks *in the world* and cycles the Zone to *Japan*; the Briefing refreshes instantly from cache. The Summaries are in French though every Source behind them is Japanese — he reads what the Japanese press collectively decided mattered, in his own language. He then clicks *of the day* to *of the month*, catching up on the four weeks he spent travelling.
  *Edge case:* he tries a small country with too few Independent Sources; the page serves the Continent instead and says so explicitly.

- **UJ-3. Malik checks whether he is being manipulated.**
  Malik, 45, reads news critically and assumes every ranking hides an agenda. He arrives on World / day and reads the numbers before the Summaries. Under item one: *covered by 34 independent sources across 12 countries*. At the foot of the Briefing: *1,247 articles read, 5 kept*. He clicks the Source count to see which Sources and which countries. The criterion is stated, countable, and arguable — he can disagree with it, which is what makes it trustworthy. He follows an outbound link to an original Article and leaves to read it in full.

- **UJ-4. Sofia scans the Briefing in the seven minutes of her commute.**
  Sofia, consultant, has a client meeting at nine and does not want to be the person who missed the news. She installed 5 News to her home screen last week and now opens it from the icon rather than a bookmark. Standing on the metro, one hand. The World / day Briefing is already rendered — no spinner, no AI wait. Five items fit the screen with minimal scrolling, each readable in one breath. She arrives at her stop knowing what the day holds, without having made a single choice about what to read.
  *Edge case:* the tunnel kills her connection before the page loads. She sees yesterday's Briefing, labelled as yesterday's with its timestamp — not today's news silently missing, and not a blank page.

## 3. Glossary

Downstream workflows and readers use these terms exactly. Use the defined term everywhere — never a synonym.

- **Article** — a single news item published by one Source, retrieved through ingestion. Has a title, a publication timestamp, a Source, and a language.
- **Source** — a news outlet that publishes Articles. Has a country of origin and a language.
- **Independent Source** — a Source whose Article is not a republication of another Source's dispatch, as determined by Syndication Detection. Only Independent Sources count toward the Consensus Score.
- **Wire Copy** — an Article republished from a news agency dispatch (AP, Reuters, AFP) rather than independently reported. Excluded from Independent Source counts.
- **Syndication Detection** — the pipeline stage that identifies Wire Copy and collapses republications so they count once.
- **Event** — a real-world occurrence that multiple Articles describe.
- **Cluster** — the set of Articles the pipeline has grouped as describing the same Event. One Cluster represents one Event.
- **Consensus Score** — the ranking measure of a Cluster: the count of Independent Sources and the count of distinct countries among them. Both numbers are displayed to the reader. Their combination into a single order is specified by FR-6.
- **Qualifying Cluster** — a Cluster eligible for inclusion in a Briefing: it has at least 2 Independent Sources from at least 2 distinct countries within the Briefing's Period and Zone. Clusters below this floor are never displayed and never counted toward item totals.
- **Zone** — a geographic scope for a Briefing. Exactly one of: World, a Continent, or a Country from the supported list.
- **Period** — a time window for a Briefing. Exactly one of: day, week, month.
- **Briefing** — the ordered list of 2 to 5 Clusters for one Zone × Period × Output Language combination, with their Summaries. The unit that is precomputed, cached, and served.
- **Summary** — the AI-generated text for one Cluster within a Briefing, written in the Output Language.
- **Output Language** — the language a Briefing is generated in. v1 supports French, English, Spanish.
- **Discarded Volume** — the count of Articles ingested for a Briefing minus those in its published Clusters. Displayed as the ratio that makes the filtering visible.
- **End Screen** — the explicit terminal element after the last item of a Briefing, stating that the Briefing is complete.

## 4. Features

### 4.1 The Mad-Libs Briefing Page

**Description:** The reader arrives and a Briefing is already on screen — World / day by default, no configuration required before value is shown. The page title is a fill-in-the-blank sentence whose blank words are the controls: *The 5 most important news **[of the day]** **[in the world]***. Clicking a blank word cycles its value and the Briefing refreshes from cache. This one sentence serves as page title, form labels, and submit button at once. Realizes UJ-1, UJ-2, UJ-4.

**Functional Requirements:**

#### FR-1: Immediate default Briefing

Any visitor sees the World / day Briefing rendered on arrival, without authentication, configuration, or interaction. Realizes UJ-1, UJ-4.

**Consequences (testable):**
- The Briefing content is present in the initial page response; no client-side fetch is required to display it.
- No onboarding, cookie wall, or preference prompt precedes the Briefing.
- Time to first rendered Briefing is governed by NFR-1.

#### FR-2: Inline Period selector

A reader can change the Period by clicking the period words in the title sentence, cycling day → week → month. Realizes UJ-2.

**Consequences (testable):**
- Clicking the Period control replaces the displayed Briefing with the one for the new Period and the current Zone.
- The title sentence text updates to match the selected Period.
- The selection is reflected in the URL so a Briefing can be linked directly.

#### FR-3: Inline Zone selector

A reader can change the Zone by clicking the zone words in the title sentence, selecting World, a Continent, or a supported Country. Realizes UJ-2.

**Consequences (testable):**
- v1 supports 15 Zones: World; the continents Europe, North America, South America, Asia, Africa, Oceania; and the countries France, United Kingdom, Germany, United States, Japan, China, India, Brazil.
- Selecting a Zone replaces the displayed Briefing with the one for the new Zone and the current Period.
- The selection is reflected in the URL.

#### FR-4: Variable item count

A Briefing contains between 2 and 5 items, reflecting how many Events met the ranking threshold, never padded to a fixed count. Realizes UJ-1.

**Consequences (testable):**
- A Briefing with 3 Qualifying Clusters displays 3 items and no placeholders.
- A Briefing where one Cluster's Consensus Score dominates displays that single item at full width.
- A Briefing with fewer than 2 Qualifying Clusters is governed by FR-16.

#### FR-5: End Screen

After the last item of every Briefing, the reader sees an explicit statement that the Briefing is complete. Realizes UJ-1.

**Consequences (testable):**
- The End Screen renders after the final item in every Briefing, including single-item Briefings.
- No further content, recommendations, related items, or infinite-scroll trigger appears below the End Screen.

**Feature-specific NFRs:**
- A 5-item Briefing fits a standard mobile viewport with minimal scrolling; each item is readable in one breath. `[ASSUMPTION: interpreted as a summary of roughly 240–320 characters — confirm during UX.]`

### 4.2 Consensus Ranking and Transparency

**Description:** Every item states why it is in the Briefing, and the Briefing states how much was discarded to produce it. The Consensus Score is simultaneously the ranking mechanism and the trust artifact, which is why its integrity is a v1 requirement rather than a refinement. Realizes UJ-3.

**Functional Requirements:**

#### FR-6: Cluster ranking and selection

The system orders Qualifying Clusters by Consensus Score and selects up to 5 for a Briefing — however many qualify, between 2 and 5, never padded to a fixed count (FR-4). This is the product's central judgment, and it is fully deterministic: no AI participates in it.

**Consequences (testable):**
- Independent Source volume takes precedence over country diversity: a Cluster covered by 30 Independent Sources across 4 countries ranks above one covered by 12 Independent Sources across 11 countries. Thirty newsrooms independently judging a story worth covering is the most direct consensus signal available.
- Where Independent Source counts tie, the higher country count ranks first.
- Country count is never discarded: it is displayed alongside the Independent Source count (FR-7) and gates eligibility through Qualifying Cluster and FR-17.
- At most 5 Qualifying Clusters appear in any Briefing; those ranked 6th and below are excluded and counted in Discarded Volume.
- Ranking runs on Qualifying Clusters only, after Syndication Detection (FR-10) has resolved Independent Source counts.
- Re-running ranking on identical input produces identical output.

#### FR-7: Per-item Consensus Score display

Each item in a Briefing displays the count of Independent Sources and the count of distinct countries that covered its Event. Realizes UJ-3.

**Consequences (testable):**
- Every item shows both counts, in the form *covered by N independent sources across M countries*.
- The displayed counts are Independent Source counts as produced by FR-10, never raw Article counts.

#### FR-8: Discarded Volume display

Each Briefing displays how many Articles were ingested and how many were kept. Realizes UJ-3.

**Consequences (testable):**
- The figure appears once per Briefing, at the foot of the item list.
- The ingested count reflects Articles retrieved for that Zone × Period, and the kept count equals the number of items displayed.

#### FR-9: Source inspection

A reader can see which Sources and which countries make up an item's Consensus Score. Realizes UJ-3.

**Consequences (testable):**
- Interacting with the Consensus Score reveals the list of contributing Independent Sources with their countries.
- The number of Sources listed equals the displayed Independent Source count.

#### FR-10: Syndication Detection

The system counts republished agency dispatches once, so that Consensus Scores reflect independent coverage. This is a v1 requirement.

**Consequences (testable):**
- Two Articles with near-identical titles from different Sources contribute 1 to the Independent Source count, not 2.
- Where a Source exposes wire-attribution metadata, Articles marked as agency dispatches from the same agency within a Cluster contribute 1.
- A locally rewritten dispatch covering the same underlying report contributes 1, not 2. `[ASSUMPTION: rewrite detection is the third and hardest layer — the brief sequences it last and calls for inspecting output after layer 1.]`

**Notes:** `[NOTE FOR PM]` The three layers ship in order — near-duplicate title collapse, then wire metadata, then rewrite detection — with pipeline output inspected after the first layer, not the third. §10 stages this; treat it as binding.

### 4.3 Summaries and Attribution

**Description:** Each item carries an AI-generated Summary in the reader's Output Language, regardless of the Source languages behind it. The Summary is a trailer, not a substitute: it exists to make the reader want the original, and it never stands between the reader and the Source. Realizes UJ-2, UJ-3.

**Functional Requirements:**

#### FR-11: Multilingual Summary generation

Every Briefing is generated in each supported Output Language, with Summaries written in that language irrespective of the languages of the underlying Articles. Realizes UJ-2.

**Consequences (testable):**
- v1 generates every Zone × Period Briefing in French, English, and Spanish.
- A Cluster composed entirely of Japanese-language Articles yields a French Summary in the French Briefing.
- The reader's Output Language is reflected in the URL.

#### FR-12: Output Language selection

A reader receives a Briefing in one of the supported Output Languages, and can change it. Realizes UJ-2.

**Consequences (testable):**
- On first arrival the Output Language is chosen from the browser's language preference, falling back to English when it matches none of the supported languages.
- A reader can change the Output Language and the Briefing re-renders in that language.
- The Output Language is reflected in the URL, so a Briefing in a specific language can be linked directly.
- The Output Language control sits outside the mad-libs sentence, which has exactly two blanks — Period and Zone. `[ASSUMPTION: adding a third blank would dilute the sentence; placement is a UX decision, flagged for bmad-ux.]`

#### FR-13: Two-source corroboration

A Summary states nothing that is not present in at least two concordant Articles within its Cluster.

**Consequences (testable):**
- A claim appearing in exactly one Article of a Cluster does not appear in the Summary.
- Clusters with fewer than 2 Independent Sources do not qualify for a Briefing (see FR-16).

#### FR-14: Attribution and outbound link

Every item displays visible attribution and a prominent outbound link to an original Article. Realizes UJ-3.

**Consequences (testable):**
- Each item carries at least one outbound link to a Source's original Article.
- The outbound link is visible without interaction — not hidden behind a menu or a hover state.
- No synthesized statement in a Summary is attributed to a named outlet.

### 4.4 Precomputed Briefing Pipeline

**Description:** Every Briefing is generated ahead of time by a scheduled job and served from cache. No AI call ever happens in a reader's request path — an ~8 second wait at click time would kill the ritual the product is built around. The pipeline runs three deterministic stages (collect; deduplicate and cluster; rank) followed by one AI stage (summarize the survivors).

**Functional Requirements:**

#### FR-15: Scheduled precomputation

The system generates all Briefings on a schedule and serves reader requests from the generated set.

**Consequences (testable):**
- v1 generates 135 Briefings per cycle: 15 Zones × 3 Periods × 3 Output Languages.
- No reader-initiated request triggers an AI call, an embedding call, or an ingestion call.
- A reader request for any supported Zone × Period × Output Language combination is served from precomputed content.

#### FR-16: Insufficient-coverage handling

When a Zone has too few Qualifying Clusters to form a Briefing, the system serves the containing Continent's Briefing and states the substitution to the reader. Realizes UJ-2.

**Consequences (testable):**
- A Country Zone yielding fewer than 2 Qualifying Clusters serves its Continent's Briefing.
- The page states explicitly that it is showing the Continent rather than the requested Country.
- The substitution is never silent.

#### FR-17: Anti-concentration rule

A Continent Briefing contains at most 2 items from the same country.

**Consequences (testable):**
- Where more than 2 Qualifying Clusters for a Continent originate in one country, only the 2 highest-ranked are included and the next-ranked Clusters from other countries take the remaining places.
- A World Briefing is not subject to this cap. `[ASSUMPTION: the brief scopes the rule to continental tops; confirm whether World should also be capped.]`

#### FR-18: Cross-day Cluster continuity

For week and month Periods, Articles describing the same ongoing Event across multiple ingest days belong to one Cluster, not one per day. Realizes UJ-2.

**Consequences (testable):**
- An Event covered on three consecutive days appears once in a week Briefing, with a Consensus Score aggregating all three days' Independent Sources.
- A month Briefing does not contain multiple items describing the same Event.
- Day Briefings are unaffected — their window is a single ingest day.

**Notes:** `[NOTE FOR PM]` Cross-day continuity is real design work, not a wider query window: Clusters built per ingest day do not merge on their own, so week and month cost meaningfully more than day. Hence *day* as the v1 default. Week and month are not FR-2 parameter changes — an epic generator must size them separately.

#### FR-19: Briefing freshness

A served Briefing reflects a generation cycle recent enough for its Period.

**Consequences (testable):**
- A day Briefing is regenerated at least once per day.
- The generation timestamp is available to the reader. `[ASSUMPTION: displayed as "updated at HH:MM" — confirm form during UX.]`
- If a generation cycle fails, the previously generated Briefing continues to be served rather than an error or an empty page.

### 4.5 Installability and Offline Behaviour

**Description:** 5 News is installable to the home screen and survives a lost connection. This serves the ritual directly — the commuter who opens it on the metro is the reader most likely to have no signal, and an icon on the home screen is what makes a daily habit a habit. It also introduces the product's most dangerous failure mode, which FR-21 exists to prevent. Realizes UJ-4.

**Functional Requirements:**

#### FR-20: Installable application

A reader can install 5 News to their device home screen and launch it as a standalone application.

**Consequences (testable):**
- The site serves a web application manifest with name, icons, theme colour, and standalone display mode.
- A supporting browser offers installation without further configuration.
- Launching the installed application opens the World / day Briefing in the reader's Output Language, identically to a browser visit (FR-1).

#### FR-21: Freshness outranks the offline cache

A reader with a working connection always sees the current Briefing, never a cached earlier one.

**Consequences (testable):**
- Briefing content is fetched from the network first; the cache is used only after the network fails or does not answer within a short timeout. `[ASSUMPTION: 2–3 second timeout — tune against real mobile conditions.]`
- A reader who opens the application the morning after a generation cycle sees that cycle's Briefing, not the previous day's, whenever the network is available.
- A published cycle invalidates any previously cached Briefing content, and the invalidation takes effect on the visit that discovers it rather than the following one.
- Cached Briefing content is served only while offline, and the page states that what is shown is from an earlier cycle, with its generation timestamp (FR-19).

**Notes:** `[NOTE FOR PM]` This is the requirement that makes the PWA safe to build. A conventional cache-first or stale-while-revalidate strategy would guarantee that the first thing a returning reader sees is yesterday's news — silently, with no signal that it is stale. For a product whose entire claim is *the 5 most important news of the day*, that is the worst failure available, and it is invisible to the reader. Any implementation that inverts the network/cache precedence breaks the product, not just the feature.

## 5. Cross-Cutting NFRs

- **NFR-1 (Latency).** A Briefing reaches first contentful paint within 1 second at the 95th percentile on a typical mobile connection, because it is static precomputed content. No reader-facing path includes an AI, embedding, or third-party API call. Changing Period or Zone re-renders within the same bound. `[ASSUMPTION: 1s p95 is the stated target; the brief's requirement is qualitative — that waiting never breaks the ritual, given ~8s was identified as fatal.]`
- **NFR-2 (Cost predictability).** Generation cost scales with the number of Briefings, not with the number of readers. Adding readers does not add AI calls.
- **NFR-3 (Ingestion resilience).** A failure or rate-limit block from any single upstream feed degrades coverage for the affected cycle without failing the pipeline or the served Briefings.
- **NFR-4 (Accessibility).** The page is readable and navigable without JavaScript for its core content, and meets WCAG 2.1 AA for contrast and keyboard navigation. `[ASSUMPTION: AA is the target; the reading-focused nature of the product makes it low-cost to meet.]`
- **NFR-5 (Legality of ingestion).** Content is acquired only via public APIs and published RSS feeds. No scraping.
- **NFR-6 (Offline scope).** Offline support is a safety net, not a feature surface. Only the application shell and at most the reader's last-viewed Briefing are retained for offline use — never the full 135-Briefing matrix, whose install cost is unbounded and whose contents expire daily.

## 6. Constraints and Guardrails

### 6.1 Editorial Integrity

The Consensus Score is the product's central claim. Two rules protect it:

- Ranking is deterministic. The AI never selects, orders, or scores Clusters — it only writes Summaries for Clusters already chosen.
- Displayed counts reflect Independent Sources. A number the reader cannot trust is worse than no number, because the number *is* the differentiator.

### 6.2 Anti-Engagement

The product is measured by how quickly the reader leaves. Permanently excluded from this product, not merely deferred:

- Infinite feed, endless scroll, or any "more like this" continuation past the End Screen.
- Multiple daily notifications.
- Programmatic advertising and engagement optimization.
- Human-interest filler admitted to raise item counts.

### 6.3 Cost

AI spend is capped by FR-15 and NFR-2, independently of traffic. Embedding a few thousand Articles per cycle is a cents-scale cost.

## 7. Aesthetic and Tone

- **The sentence is the interface.** The mad-libs title (FR-1 to FR-3) states the product's promise as the first thing the reader reads.
- **Voice: plain and finite.** Product-generated text sells clarity, not news. *That's all. Come back tomorrow.* is the register — direct, unapologetic, slightly dry. No urgency, no teasers, no "breaking".
- **Honesty over polish.** When the day produced three things, the page says three. When a Country falls back to its Continent, the page says so. Every visible shortfall is stated rather than smoothed over.
- **Anti-references.** Infinite feeds, engagement badges, red notification dots, "trending now" modules, autoplay.

## 8. Non-Goals (Explicit)

- 5 News is not a news reader. It does not host, reproduce, or replace original articles.
- It does not personalize. Importance is collective and identical for every reader of a given Briefing.
- It does not cover topics or beats — only Zones and Periods.
- It does not become a social layer or a discussion platform. (§6.2 bars the feed mechanics themselves.)
- It does not judge importance editorially or by model opinion. Only measured Consensus.

## 9. MVP Scope

### 9.1 In Scope

All of FR-1 to FR-21 and NFR-1 to NFR-6, web only — installable as a PWA, but no native application — built in the order of §10. The scope boundary is the matrix: 15 Zones × 3 Periods × 3 Output Languages = 135 precomputed Briefings. Syndication Detection ships all three layers.

### 9.2 Out of Scope for MVP

- **Newsletter and daily email** — deferred to v2. Reuses the same engine; the channel decision is not on the v1 path.
- **Push notifications** — deferred. They sit close to the anti-anxiety promise and have to be right the first time.
- **Audio briefing** — deferred to v2. `[NOTE FOR PM]` The brainstorm judged the 90-second audio briefing the single most differentiating format identified. Emotionally load-bearing; revisit early if timeline permits.
- **Clickable world map** — deferred. Better for discovery than for repeat use.
- **"Since your last visit" personal time window** — deferred. `[NOTE FOR PM]` Flagged in the brainstorm as a potential breakthrough — personal windows beating calendar windows. Cut for complexity, not for lack of value.
- **Tone badges, "explain it simply" mode, user-defined importance, shareable image cards** — deferred.
- **Archives and SEO pages** — undecided for v1; see Open Questions.
- **Authentication and accounts** — none in v1. Installability (FR-20) requires no account; see Open Questions on remembering the last selection.
- **Push notifications** — deferred, and deliberately not implied by FR-20. Installing the application grants no notification permission and sends nothing. The single-daily-notification idea sits close to the anti-anxiety promise and has to be right the first time.

## 10. Build Order

**Feature order in §4 is not build order.** The page is documented first because it is how the product is understood; it is built last. Downstream epic generation must follow the sequence below, not the section order.

1. **Ingestion and Syndication Detection** (FR-10, and the collection behind FR-15). Start with near-duplicate title collapse alone — the cheap layer that catches verbatim reprints.
2. **Inspect output here, before continuing.** Look at what the pipeline produces for World / day for several days. The risk in FR-10 is not cost but sequence: refining all three deduplication layers before ever seeing a Briefing inverts the point of building the pipeline first.
3. **Clustering and ranking** (FR-6, FR-18), then the remaining Syndication Detection layers.
4. **Summarization** (FR-11, FR-13, FR-14).
5. **The page** (FR-1 through FR-5, FR-7 through FR-9, FR-12).
6. **Installability and offline** (FR-20, FR-21). Last, and only once the page is real — a service worker caching a page that is still changing shape wastes effort, and FR-21's freshness rule can only be tested against actual published cycles.

The gate between stages 2 and 3 is SM-1: the interface is built only once the filter is credible. A beautiful page over a bad filter is worse than no product, because it makes the failure harder to see.

## 11. Success Metrics

**Primary**
- **SM-1**: Filter credibility — the author compares each day's World / day Briefing against what he independently knows of the day. Target: no absurdities, no human-interest filler, and no major omissions across a two-week observation window before the UI is built. Validates FR-10, FR-17, and the ranking behind FR-7.
- **SM-2**: Author daily use — the author opens 5 News unprompted, as a replacement for his existing habit, one month after launch. Validates the product as a whole.

**Secondary**
- **SM-3**: Zero reader-path AI calls — no AI, embedding, or ingestion call occurs in any reader request. Validates FR-15, NFR-1, NFR-2.

**Counter-metrics (do not optimize)**
- **SM-C1**: Time per visit — should trend *down*, not up. Counterbalances any instinct to enrich SM-2 by lengthening sessions. A reader who leaves in ninety seconds is the success case.
- **SM-C2**: Items per Briefing — must not drift toward 5. A rising average signals padding, which breaks FR-4 and the honesty the product sells.

## 12. Open Questions

1. **Persisting the last Zone/Period selection.** Does a remembered choice become the landing state, or does World / day always come first with the previous choice one click away? Decide whether v1 stores anything client-side.
2. **Archives and SEO.** Each archived Briefing is an indexable page; 365 a year is a compounding acquisition asset. In v1 or after?
3. **NewsData.io terms.** `[VERIFY]` Free-tier commercial use is claimed on their marketing blog, not confirmed in current terms. Confirm before depending on it.
4. **Name and domain.** Candidates in the brief addendum; availability unchecked.
5. **World Briefing anti-concentration.** Should FR-17's cap extend to World Briefings? FR-6's precedence rule makes this live: because Independent Source volume leads, a heavily covered national story (a German election, an American trial) can displace genuinely global Events. Watch for it during the §10 inspection window — it is the first thing that will show up if the rule is wrong.
6. **Default Period revisit.** v1 ships with *day*. Sunday-evening ritual usage may argue for *week*; observe once in use.

## 13. Assumptions Index

Open assumptions, in document order. FR-6's ranking precedence was the most consequential assumption here and is now settled — Independent Source volume leads — so it is not listed below; Open Question 5 tracks its consequence.

- **§4.1 FR-5 feature NFR** — one-breath readability interpreted as roughly 240–320 characters per Summary; confirm during UX.
- **§4.2 FR-10** — rewrite detection is the third and hardest Syndication Detection layer; the brief sequences it last and calls for inspecting output after layer 1.
- **§4.3 FR-12** — the Output Language control sits outside the mad-libs sentence, which keeps exactly two blanks; placement flagged for `bmad-ux`.
- **§4.4 FR-17** — the anti-concentration cap applies to Continent Briefings only; World may or may not need it (Open Question 5).
- **§4.4 FR-19** — Briefing freshness surfaced to the reader as "updated at HH:MM"; confirm form during UX.
- **§5 NFR-1** — 1s p95 first contentful paint as the latency target; the brief's requirement is qualitative (waiting must never break the ritual, ~8s identified as fatal).
- **§4.5 FR-21** — a 2–3 second network timeout before falling back to cache; tune against real mobile conditions.
- **§5 NFR-4** — WCAG 2.1 AA as the accessibility target.
