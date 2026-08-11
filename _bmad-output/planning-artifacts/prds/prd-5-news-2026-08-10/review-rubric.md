# PRD Quality Review — 5 News

*Reviewed 2026-08-10 against `.claude/skills/bmad-prd/assets/prd-validation-checklist.md`.*

**Calibration applied:** personal project, sole developer who is also the first user, no stakeholders, no compliance regime, no SLA, no monetization in v1. The absence of stakeholder sections, ROI analysis, rollout plans, and approval gates is deliberate and logged in `.memlog.md` — not flagged here. Per rubric §7 (Hobby / solo): *rigor light, substance bar still applies*. This PRD is also chain-top — it explicitly feeds UX, architecture, and epic generation (§0) — so rubric §6 Downstream usability is weighted **up**, not down. The bar used throughout: *is this precise enough that this developer can build from it and generate epics from it?*

## Overall verdict

This is a genuinely good PRD — it has a real thesis ("the product is the filter, not the summary"), it names its own biggest technical risk and promotes it to a v1 requirement rather than a refinement, and its Non-Goals and counter-metrics do actual work rather than decorating the document. The prose is disciplined and the Glossary is well-constructed. What is at risk is **done-ness of the pipeline half**: the term *qualifying Cluster* carries FR-4, FR-14, and FR-15 and is never defined, and there is no FR at all for the ranking and ordering step — the single stage the Vision calls the product's entire value. A developer could build the page from this PRD today but would have to invent the selection rule, which is the product.

Verdict: **pass-with-fixes**. Two critical gaps, both narrow and closable in one editing pass; nothing structural needs rethinking.

---

## 1. Decision-readiness — **strong**

Decisions are stated as decisions, not hedged into considerations. The Zone list is a hard 15 (FR-3), the Output Languages a hard 3 (FR-10), the item range a hard 2–5 (FR-4). §9.2 defers with named reasons rather than silence, and the two `[NOTE FOR PM]` callouts sit at genuine tensions — the audio briefing was judged *the single most differentiating format identified* and is being cut anyway, and the "since your last visit" window is cut *for complexity, not for lack of value*. That is the honest version of both statements, and neither is a safe checkpoint.

Trade-offs name what was given up. §1 concedes the approach is replicable ("nothing here is hard to replicate") in the brief and the PRD does not oversell it back. FR-9's Notes callout preserves the brief's sequencing warning — build layer 1, *look at the output*, then continue — which is a real process decision with a stated failure mode ("Building all three before ever seeing a Briefing would invert the point").

The six Open Questions are genuinely open. None is rhetorical; Q5 (World anti-concentration) even cross-links to the `[ASSUMPTION]` it originates from. No dodging found.

### Findings
- **low** — Open Question 3 (§11) carries `[VERIFY]` on NewsData.io terms but nothing in the PRD states what happens if the answer is no. *Fix:* one clause naming the fallback (GDELT + RSS only) so the answer "no" does not reopen the architecture.

## 2. Substance over theater — **strong**

No persona theater: four UJs, each exercising a distinct capability, and the memlog confirms candidates were actively rejected for redundancy (the Sunday-evening reader was dropped as covered by Rémi's week journey; the journalist was converted into an acceptance criterion rather than kept as a journey). Four is the rubric's ceiling and each one earns its place.

No NFR theater — and this is where the PRD outperforms its category. NFR-2 (Cost predictability) is stated as *cost scales with Briefings, not readers*, which is a product-specific structural claim, not "the system must be cost-effective." NFR-3 bounds the failure mode (single upstream source degrades coverage, does not fail the pipeline). NFR-5 is a flat prohibition ("No scraping"). Only NFR-1 slips into an adjective — see §4.

The Vision (§1) could not swap into another PRD in this category. "Then the page ends" and "the AI runs last, on Clusters a deterministic pipeline has already selected — so the product's central judgment has no hallucination surface" are specific commitments, not vision furniture. §7 Aesthetic and Tone is unusually load-bearing: *That's all. Come back tomorrow.* is quoted as a register, and the anti-references list (engagement badges, red notification dots, "trending now", autoplay) tells a developer what not to build.

### Findings
- None. This dimension is clean.

## 3. Strategic coherence — **strong**

The thesis is explicit and repeated where it needs to be: importance is *measured, not judged*, and the moat is a positioning commitment a large platform cannot copy because "its business model forbids it." Feature ordering follows the thesis rather than ease — §4.2 (Consensus Ranking and Transparency) argues its own priority: the Consensus Score is "simultaneously the ranking mechanism and the trust artifact, which is why its integrity is a v1 requirement rather than a refinement." That is prioritization derived from the thesis, exactly what the rubric asks for.

§6.1 Editorial Integrity is an invented section (the section menu does not name it) and it is the right invention: two rules protecting the central claim, one of which — "A number the reader cannot trust is worse than no number, because the number *is* the differentiator" — is the whole argument for FR-9's v1 status in one line.

MVP scope kind is coherently *problem-solving*: the scope logic is "make the filter credible first," and SM-1 gates on filter credibility *before the UI is built*, matching the brief's build order.

Success metrics validate the thesis rather than measuring activity. There is no DAU/MAU tell. SM-1 measures whether the filter is right; SM-2 measures whether the author actually uses it. Both are the correct instruments for the stated bet.

**Counter-metrics genuinely counterbalance.** SM-C1 (time per visit should trend *down*) counterbalances SM-2 — the named risk is "any instinct to enrich SM-2 by lengthening sessions," which is a real and specific temptation given SM-2 rewards daily opens. SM-C2 (items per Briefing must not drift toward 5) counterbalances FR-4 — a rising average signals padding. Both name what they push against and what breaks if they move. This is the rare case where counter-metrics are not decorative.

### Findings
- **medium** — SM-1 and SM-2 have targets; **SM-3 has no threshold and no measurement method** (§10). "Zero reader-path AI calls" is binary and checkable, but the PRD does not say *how* it is verified. *Fix:* name the check — e.g. "verified by request-log inspection over a 24h window showing no outbound AI/embedding/ingestion call originating from a reader request path."
- **low** — SM-C1 has a direction ("should trend *down*") but no baseline and no instrument (§10). For a v1 with one user this is arguably fine, but it means SM-C1 cannot actually fire. *Fix:* either name the instrument or mark SM-C1 explicitly as post-audience, as the brief does ("not a v1 gate; it is the right instrument once there is an audience").

## 4. Done-ness clarity — **thin**

This is the dimension the rubric says to be unforgiving on, and it is where the PRD's two real problems live. The UI half (FR-1 to FR-8, FR-12) is genuinely strong — consequences are concrete, countable, and falsifiable. FR-6's *"never raw Article counts"*, FR-12's *"visible without interaction — not hidden behind a menu or a hover state"*, and FR-5's *"no infinite-scroll trigger appears below the End Screen"* are all directly testable, and several are written as negative assertions, which is the harder and better form.

The pipeline half is where done-ness breaks down. Two gaps are critical.

### Findings

- **critical** — **"Qualifying Cluster" is undefined and it is load-bearing** (§4.1 FR-4, §4.4 FR-14, §4.4 FR-15; the term appears 6 times). FR-4 says items reflect "how many Events met **the ranking threshold**" — that threshold is never stated anywhere in the PRD. FR-14 triggers on "fewer than 2 **qualifying** Clusters." FR-15 reorders "**qualifying** Clusters." Every one of these is untestable as written, because the qualifying condition does not exist in the document. FR-11's consequence hints at one input ("Clusters with fewer than 2 Independent Sources do not qualify") but it is stated as a parenthetical inside an anti-hallucination FR, not as the definition, and it cannot be the whole rule — if 2 Independent Sources were sufficient, a World/day Briefing would qualify hundreds of Clusters and the cap to 5 would be doing all the work silently. *Fix:* add **Qualifying Cluster** to the Glossary with an explicit predicate (minimum Independent Source count, minimum distinct-country count, and any recency bound within the Period), and change FR-4 to reference the Glossary term instead of "the ranking threshold."

- **critical** — **No FR covers ranking and ordering.** The Vision stakes the entire product on this stage — "The engineering effort goes into clustering articles that describe the same event and ranking those Clusters by how much of the world's press covered them" — and §4.4's description lists it as a pipeline stage ("collect, deduplicate and cluster, rank, then summarize"). But no FR specifies it. The Glossary defines Briefing as "the **ordered** list of 2 to 5 Clusters" and FR-15 refers to "the 2 **highest-ranked**" — both presuppose an ordering rule that no requirement defines. Critically, Consensus Score is defined as **two** numbers (Independent Source count and distinct-country count) with no stated precedence: a developer cannot determine whether 30 sources / 4 countries outranks 12 sources / 11 countries. That is a coin flip on the product's central judgment. Also missing: what happens when more than 5 Clusters qualify (presumably top 5 by rank, but it is never said). *Fix:* add an FR — "Consensus ranking" — in §4.2 specifying how the two counts combine into a single order, the tie-break, and the truncation rule at 5. This is the single highest-value addition to the document.

- **high** — **No FR covers Output Language selection.** FR-10 requires every Briefing to be *generated* in three languages and states "The reader's Output Language is reflected in the URL," and FR-13 requires all 135 combinations to be served. But no requirement says how a reader *chooses or receives* their Output Language. UJ-2 has Rémi reading French summaries, yet he only ever clicks the Zone and Period words — he never selects a language, so French must arrive by default detection, URL, or a control the PRD never describes. Compare FR-2 and FR-3, which specify the Period and Zone controls precisely; Output Language is the third axis of the product's core combinatorics and has no equivalent. *Fix:* add an FR covering initial Output Language determination (browser `Accept-Language`? URL path? explicit control?) and whether a reader can change it. Note the Mad-Libs sentence has only two blanks, so this is a real UX decision, not an oversight to paper over.

- **high** — **NFR-1 states an adjective, not a bound.** "A Briefing renders **without a perceptible wait**" (§5). FR-1 defers to it — "Time to first rendered Briefing is governed by NFR-1" — so the one FR consequence about page speed resolves to an unmeasurable phrase. The second sentence of NFR-1 (no AI/embedding/third-party call in the reader path) *is* testable and is the architectural guarantee, but it does not bound render time on its own. *Fix:* give a number (e.g. p95 time-to-first-contentful-paint under 1s on a mid-range mobile connection). The PRD is otherwise excellent at numeric bounds — 15 Zones, 135 Briefings, 2–5 items, 240–320 characters — so this one is an outlier, not a habit.

- **medium** — **FR-16 freshness is under-specified for week and month.** The consequence covers only the day Period ("A day Briefing is regenerated at least once per day"). Week and month Briefings have no stated cadence, so "recent enough for its Period" is undefined for two thirds of the Period axis. *Fix:* state a cadence for each Period value.

- **medium** — **FR-7's "ingested count" is ambiguous for the Discarded Volume ratio.** The consequence says the count "reflects Articles retrieved for that Zone × Period" — but it is not stated whether that is Articles retrieved *before* or *after* Syndication Detection collapses Wire Copy. The two produce very different numbers, and since this figure is a trust artifact displayed to the reader (UJ-3), the choice is product-visible. *Fix:* state which stage the count is taken at.

- **medium** — **FR-11 is not testable as written.** "A Summary states nothing that is not present in at least two concordant Articles within its Cluster" is the right rule, but "concordant" is undefined and the consequence ("A claim appearing in exactly one Article of a Cluster does not appear in the Summary") describes a property of generated text with no stated verification method. Unlike every other FR here, there is no observable check a developer could run. *Fix:* either define the enforcement mechanism (the generation is constrained to a corroborated-claim set assembled before the AI call) or add an explicit acceptance procedure (spot-check protocol, sample size, pass condition). Given §6.1's insistence that the AI never selects, the former is likely the real intent and should be stated.

- **low** — **FR-8's reveal is untestable at the boundary.** "The number of Sources listed equals the displayed Independent Source count" is good, but with counts in the 30s the interaction needs a stated behavior (scroll, truncate, "and 22 more"). *Fix:* state the behavior above some N, or explicitly defer to UX with a `[NOTE FOR PM]`.

- **low** — §4.1's feature NFR ("readable in one breath") is the correct instinct and is already tagged `[ASSUMPTION]` with a numeric interpretation (240–320 characters), which is the right handling. Noted as resolved, not as a finding. "Fits a standard mobile viewport with minimal scrolling" remains unbounded, but for a solo project this is reasonably deferred to UX.

## 5. Scope honesty — **strong**

§8 Non-Goals does real work — six entries, each closing a door a reader might otherwise assume open ("It does not personalize", "It does not cover topics or beats — only Zones and Periods"). §6.2 Anti-Engagement goes further and distinguishes *permanently excluded* from *deferred*, which is the distinction that usually gets blurred. §9.2 gives a reason per deferral rather than a bare list.

Five `[ASSUMPTION]` tags, three `[NOTE FOR PM]`, one `[VERIFY]`, six Open Questions. Open-items density is appropriate: the stakes are low, the author is the only person affected, and none of the open items blocks the build order the brief established (pipeline first, UI second). Notably, the PRD *closed* two of the brief's open questions rather than inheriting them — launch geography became the hard 15-Zone list in FR-3, and the language set became the hard 3 in FR-10. That is a PRD doing its job.

De-scoping is proposed honestly. The audio briefing note admits it is cutting the most differentiating idea identified, which is the opposite of silent de-scoping.

### Findings
- **low** — §9.2 lists "Archives and SEO pages — **undecided** for v1" under *Out of Scope for MVP*. Undecided and out-of-scope are different states, and the entry occupies a section that asserts the latter. *Fix:* move it to Open Questions (where it already appears as Q2) and leave a pointer, or state a provisional default.

## 6. Downstream usability — **adequate**

Weighted up: §0 declares this PRD feeds UX, architecture, and epic generation, so traceability is not optional here.

The Glossary is the PRD's best structural asset — 14 terms, each with a real definition rather than a restatement, and the discipline statement ("Introducing a synonym anywhere in this document is a discipline violation") is enforced almost everywhere. Independent Source vs Source vs Wire Copy is a genuinely careful three-way distinction that a downstream implementer needs.

**Glossary discipline audit (checked term by term):** Article, Source, Independent Source, Wire Copy, Syndication Detection, Event, Cluster, Consensus Score, Zone, Period, Briefing, Summary, Output Language, Discarded Volume, End Screen are all used verbatim and consistently in FRs. No synonym substitution found in the FR bodies — the discipline holds where it matters most. Two leaks are noted below, both outside the FRs.

FR IDs are contiguous FR-1 to FR-16 with no gaps or duplicates. UJ-1 to UJ-4, SM-1 to SM-3, SM-C1 to SM-C2, NFR-1 to NFR-5 all contiguous. Every cross-reference resolves — FR-4→FR-14, FR-6→FR-9, FR-11→FR-14, FR-1→NFR-1, SM-1→FR-9/FR-15/FR-6, SM-3→FR-13/NFR-1/NFR-2, §6.3→FR-13, Open Q5→FR-15 all point at real targets. Assumptions Index round-trips cleanly: all five inline `[ASSUMPTION]` tags appear in §12, and all five §12 entries appear inline with correct section anchors.

All four UJs have named protagonists (Claire, Rémi, Malik, Sofia) with age, situation, device, and auth state carried inline — no floating UJs, and each is self-contained enough to extract alone. Coverage is complete in one direction (every UJ is claimed by at least one FR) but four FRs carry no `Realizes` line: FR-11, FR-13, FR-15, FR-16. Three are genuinely pipeline-internal with no user-visible surface, which is legitimate — but FR-15's absence is questionable, since a Rémi-style continental reader is precisely who notices when "Africa" returns four Nigerian stories.

### Findings

- **high** — **UJ-2 implies a capability no FR covers: cross-Period catch-up.** Rémi "clicks *of the day* to *of the month*, catching up on the four weeks he spent travelling" — this is the Contextual JTBD in §2.1 ("recover after an absence... without scrolling backwards through a feed") and it is one of the five named jobs. FR-2 covers *cycling the control*; nothing covers what a month Briefing must contain for that catch-up to work. The brief flags the underlying problem explicitly — keeping *day* as default "means cross-day cluster linking is only needed when those views are built" — so cross-day/cross-week Cluster linking is a known, named piece of work that the PRD inherits without ever stating. Yet §9.1 puts all 3 Periods in MVP scope. *Fix:* either add an FR specifying how a Cluster spanning multiple days is formed and ranked for week/month Periods, or move week/month behind a `[NOTE FOR PM]` acknowledging the dependency. As written, an epic generator will size week/month as a trivial parameter change on FR-2 when it is the pipeline's second-hardest problem.

- **medium** — **UJ-2 implies instant Zone switching; no FR guarantees client-side behavior.** "the Briefing refreshes **instantly** from cache." FR-3's consequences say the Briefing is replaced and the URL updates, and FR-13 guarantees precomputation server-side — but nothing bounds the switch itself, and FR-1 requires content in the *initial page response*, which suggests full page loads. Combined with NFR-4's no-JavaScript requirement, there is an unresolved tension: a no-JS page reload is not obviously "instant." *Fix:* state the intended behavior for control interaction and reconcile it with NFR-4.

- **medium** — **UJ-1's edge case is not fully covered by an FR.** Claire "sees a single item filling the screen and **understands immediately that today had one story, not that the page failed to load**." FR-4's consequence covers the layout ("displays that single item at full width") but not the comprehension requirement — nothing requires the page to *explain* the single-item state. Since misreading it as a failure is the named risk, and §7 commits to "Honesty over polish… every visible shortfall is stated," this needs a requirement. *Fix:* add a consequence to FR-4 requiring an explicit statement when a Briefing contains fewer items than the maximum, mirroring FR-14's non-silence rule.

- **low** — FR-15 has no `Realizes` line despite being the rule that makes the Continent Zone meaningful, and SM-1 explicitly validates it. *Fix:* add `Realizes UJ-2`.

## 7. Shape fit — **strong**

The shape is right. This is a consumer-facing product with meaningful UX, so per rubric §7 the UJs are load-bearing — and they are, each one exercising a distinct capability rather than padding. Four UJs for a product with one screen is not over-formalization; it is the minimum to cover finitude (UJ-1), the selector combinatorics (UJ-2), the trust artifact (UJ-3), and the mobile default path (UJ-4).

The hobby/solo calibration is visibly and correctly applied: no stakeholder matrix, no rollout plan, no ROI section, no approval gates, and SM-2 is unashamedly "the author opens it unprompted." That is the honest success metric for this project and dressing it up would have been worse. §6.3 Cost is three sentences because three sentences is what the question deserves at this scale.

The one place the shape is slightly under-formalized is the pipeline: §4.4 is a four-FR feature carrying what the Vision says is the entire product ("the engineering effort goes into clustering… and ranking"), and it is the thinnest of the four features. The UI, which the PRD itself calls the *less* important half, gets 5 FRs and the more precise ones. That inversion is the root of the §4 findings above.

### Findings
- **medium** — **Feature-to-value inversion between §4.1 and §4.4.** The Mad-Libs page (explicitly the lower-value half) has 5 FRs with sharp consequences; the pipeline (explicitly the product) has 4 FRs, two of which lean on the undefined *qualifying Cluster*, and no clustering FR at all — how Articles are grouped into a Cluster is never specified as a requirement, only assumed by the Glossary definition. The brief calls clustering "standard work, not a risk," which justifies light treatment, but *unspecified* is different from *light*. *Fix:* add a clustering FR with at least one testable consequence (e.g. two Articles describing the same Event in different languages land in the same Cluster) so the epic generator produces a story for it.

---

## Mechanical notes

- **Glossary drift — "Headline" is capitalized as a Glossary term but is not in the Glossary** (§1 line 21, §6.3 line 272: "Embedding a few thousand **Headlines** per cycle"). It also conflicts semantically with **Article**, which is the defined term for the thing being embedded and clustered. Under the PRD's own stated rule ("Introducing a synonym anywhere in this document is a discipline violation") this is a violation in the PRD's own voice. *Fix:* replace both with "Article", or add Headline to the Glossary if the title-only form is genuinely a distinct object in the pipeline (it may be — GDELT title-level data vs full Articles — in which case defining it matters for architecture).
- **Glossary drift — "outlet"** used in UJ-3 ("He clicks the Source count to see which **outlets** and which countries") where **Source** is the defined term. FR-8 gets it right. In §4.3 FR-12 ("attributed to a named outlet") the usage is quoting the brief's anti-hallucination rule and reads acceptably, but UJ-3 should be normalized. Low impact — UJ prose is allowed to be more natural than FR prose — but this is the one place a downstream extractor could mis-map.
- **Glossary drift — lowercase "summaries" / "articles" / "sources"** appear throughout the UJs (UJ-1 "the four summaries", UJ-3 "1,247 articles read", "an original article"). Mostly these are quoting on-screen copy, which is legitimate. Not a finding.
- **Broken reference — `addendum.md`.** §0 states "implementation choices live in `addendum.md`", but no addendum exists in the PRD directory (`prd-5-news-2026-08-10/` contains only `prd.md` and `.memlog.md`). §0's other addendum references correctly say "the brief addendum" and resolve. *Fix:* either create the PRD addendum, or change the sentence to point at the brief's addendum, or drop the clause. As written, a downstream workflow instructed to source implementation detail from `addendum.md` will fail to find it.
- **ID continuity — clean.** FR-1…FR-16, UJ-1…UJ-4, SM-1…SM-3, SM-C1…SM-C2, NFR-1…NFR-5. No gaps, no duplicates. All 30+ inline cross-references resolve to real targets.
- **Assumptions Index roundtrip — clean.** All 5 inline `[ASSUMPTION]` tags indexed in §12 with correct section anchors; all 5 index entries traceable inline. No orphans in either direction.
- **UJ protagonist naming — clean.** All four named, each with situation and device context carried inline.
- **`Realizes` coverage — 4 FRs without one** (FR-11, FR-13, FR-15, FR-16). Three are legitimately pipeline-internal; FR-15 should carry `Realizes UJ-2` (see §6 findings).
- **Required sections — present** for the agreed stakes and product type. Deliberate exclusions (stakeholders, ROI, rollout, compliance, data governance) are logged in `.memlog.md` and correctly absent.

---

## Priority fix list

Ordered by impact on whether this PRD can be built and epic'd from.

1. **Define *Qualifying Cluster*** in the Glossary with an explicit predicate; update FR-4 to use it instead of "the ranking threshold." *(critical — unblocks FR-4, FR-14, FR-15)*
2. **Add a ranking/ordering FR** in §4.2: how the two Consensus Score counts combine into one order, the tie-break, and truncation at 5. *(critical — this is the product's central judgment and currently has no requirement)*
3. **Add an Output Language selection FR.** *(high — third axis of the core combinatorics, no control specified)*
4. **Add a cross-Period Cluster FR**, or gate week/month behind a `[NOTE FOR PM]`. *(high — UJ-2 and the Contextual JTBD depend on it; currently invisible to epic sizing)*
5. **Give NFR-1 a number.** *(high — FR-1's only speed consequence currently resolves to an adjective)*
6. **Fix the `addendum.md` reference**, and replace "Headlines" with "Articles" in §1 and §6.3. *(mechanical, two-minute fix, but the Headline/Article conflation could mislead architecture)*
7. Specify FR-16 cadence for week and month; clarify FR-7's ingested-count stage; make FR-11 verifiable; add the single-item explanation consequence to FR-4. *(medium)*
