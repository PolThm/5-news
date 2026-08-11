---
title: "Reconciliation: Brief + Addendum → PRD (5 News)"
status: draft
created: 2026-08-10
---

# Reconciliation — what the SOURCE holds that the PRD dropped or distorted

**SOURCE:** `briefs/brief-5-news-2026-08-10/brief.md` + `addendum.md`
**OUTPUT:** `prds/prd-5-news-2026-08-10/prd.md`

Verdict up front: the PRD is a faithful *functional* conversion. Nearly every rule in the brief has an FR. What it loses is almost entirely the second layer — the reasoning that makes the rules resistant to erosion, the sequencing advice that governs *when* to build, and a set of numbers the PRD invented that the brief never authorised. Roughly 20 gaps below, ordered by severity.

Legend for the PRD column: **DROPPED** (no trace) / **WEAKENED** (present but stripped of force) / **CONTRADICTED** (PRD says something the source does not support) / **INVENTED** (PRD asserts a number or scope the source never gave).

---

## A. Severe — a builder working from the PRD alone will get this wrong

### A1. Build order: pipeline first, UI second — the single most important sequencing instruction in the brief

- **Source (brief, "Build Order", entire section):** "**The pipeline is built and observed before the UI is built.** Collection, deduplication, clustering, and ranking come first; the output is inspected for several days; the interface follows only once the top 5 is credible. Validation targets the quality of the filter — the actual product — rather than market appetite. This replaces the brainstorm's suggestion to spend two weeks on manual briefings before writing code: development starts immediately, and the cost of being wrong is time rather than money."
- **PRD:** **DROPPED as a directive.** There is no build-order section. The only surviving trace is oblique: SM-1 mentions "a two-week observation window before the UI is built", and the FR-9 `[NOTE FOR PM]` says building all three dedup layers "before ever seeing a Briefing would invert the point of building the pipeline first" — which references a principle the PRD never actually states. A reader of the PRD alone encounters a dangling reference to a rule that isn't there.
- **Judgment:** Matters a great deal. This is the brief's top-level instruction about *how to build*, and the PRD's own notes assume the reader already knows it. Downstream epic/story sequencing will likely start with the mad-libs page because §4.1 is the first feature listed.

### A2. Syndication layer *sequencing* demoted from requirement to an assumption tag

- **Source (brief, "The Ranking Integrity Risk" + addendum "Wire Copy"):** three layers "in build order": near-duplicate title collapse → wire-attribution metadata → rewrite detection. And explicitly: "Build them in that order and inspect the output after the first layer rather than after the third. **The risk here is not cost but sequence** — several days spent refining deduplication before ever seeing a top 5 would invert the whole point of building the pipeline first."
- **PRD:** **WEAKENED.** FR-9 lists the three behaviours as flat, simultaneous testable consequences. The ordering survives only inside an `[ASSUMPTION:]` tag and a `[NOTE FOR PM]`, and §9.1 MVP Scope reads "Syndication Detection, **all three layers** (FR-9)" — which reads as "build all three before shipping", the exact failure the brief warns against.
- **Judgment:** Matters. The brief's warning is about wasted weeks; the PRD packages the three layers as one acceptance-criteria block, which is how a developer would naturally schedule them.

### A3. Zone list — 15 Zones invented; the brief explicitly left launch geography undecided

- **Source (brief, "Open Questions"):** "**Launch geography** — covering 5–10 countries well beats covering the whole world badly. The specific list is undecided."
- **PRD:** **CONTRADICTED / INVENTED.** FR-3 states "v1 supports 15 Zones: World; the continents Europe, North America, South America, Asia, Africa, Oceania; and the countries France, United Kingdom, Germany, United States, Japan, China, India, Brazil." This is presented as settled fact with no assumption tag, and it is not in the PRD's Open Questions list. It also drops the principle behind the number ("5–10 countries **well** beats the whole world badly") — the quality-over-breadth reasoning that should govern whichever list is eventually chosen.
- **Judgment:** Matters a lot. An open question was silently closed, and closed at 8 countries + 6 continents when the brief's guidance was 5–10 countries. The governing principle is gone.

### A4. Output Languages — three languages invented; the brief never enumerated any

- **Source (brief, Scope/In):** "Summaries generated in the reader's language regardless of source language." No language list anywhere in brief or addendum.
- **PRD:** **INVENTED.** Glossary: "Output Language — ... v1 supports French, English, Spanish." FR-10, FR-13, §9.1 all build on it, and it multiplies into the 135-Briefing figure.
- **Judgment:** Matters. It is a defensible guess but presented as a decision, untagged, and it triples generation cost and scope.

### A5. The 135-Briefing figure is a derived number resting on two invented inputs

- **Source:** brief says only "Every zone × period combination is precomputed", and "the AI runs a few dozen times a day".
- **PRD:** FR-13: "v1 generates 135 Briefings per cycle: 15 Zones × 3 Periods × 3 Output Languages." §9.1 repeats it.
- **Judgment:** Matters. "A few dozen times a day" (brief) vs 135 per cycle (PRD) is a ~4x cost/architecture delta, built on A3 and A4. Architecture will size ingestion, rate-limit budget, and AI spend off 135.

### A6. Day-boundary cluster continuity — a named hard design task, entirely absent

- **Source (addendum, "Clustering Approach", hard edge #1):** "Clusters built per UTC ingest-day do not merge across days for ongoing stories. The weekly and monthly views require **explicit cluster linking, not just a wider query window. This is a real design task, not a configuration flag.**" Reinforced in brief Open Questions: keeping the daily default off the critical path "means cross-day cluster linking is only needed when those views are built."
- **PRD:** **DROPPED.** FR-2 offers week and month as first-class, equal-cost selectors. FR-13 counts week/month Briefings in the 135. Nothing anywhere hints that week and month are architecturally harder than day.
- **Judgment:** Matters a lot. The PRD makes week/month look like a query-parameter change. This is the second-biggest technical risk in the source material after wire copy, and it is invisible in the PRD.

### A7. Full article text is unavailable — the constraint that rules out a whole class of designs

- **Source (addendum, "News API comparison"):** "**Full article text is unavailable on essentially every cheap tier** — headlines, snippets, and metadata only. This suits the architecture (cluster on headlines, summarize from snippets) but **definitively rules out any design where the AI reads whole articles.**"
- **PRD:** **DROPPED.** FR-11 (two-source corroboration) says a Summary states nothing not present in "at least two concordant Articles within its Cluster" — with no indication that "Article" here means a title and a snippet, not a body. The Glossary defines Article as having "a title, a publication timestamp, a Source, and a language" — notably no body — but never says why, and never states the prohibition.
- **Judgment:** Matters. Someone building FR-11 will reasonably assume article text is available for corroboration. This is a hard external constraint stated as a "definitive" ruling-out in the source.

### A8. GDELT rate limits and MAXRECORDS — the numbers that shape ingestion

- **Source (addendum, "Hard limits to design around"):** `MAXRECORDS` caps at **250** (default 75) — "the ceiling that shapes ingestion batching"; default search window 3 months, minimum timespan 15 minutes; documented throttle ~1 request / 5 seconds but "real-world enforcement is reportedly harsher: one measurement (2026-07-27) found that ~60 requests over 90 minutes triggered a block, with no stated retry interval. The real limit is undocumented and can change without notice."
- **PRD:** **WEAKENED to near-nothing.** NFR-3 says only "A failure or rate-limit block from any single upstream source degrades coverage for the affected cycle without failing the pipeline." No numbers, no named source, no note that the real limit is unknown and unstable.
- **Judgment:** Borderline — the PRD points at the addendum for architecture. But NFR-3's phrasing implies rate-limiting is an edge case to survive, when the source treats it as the primary design constraint on ingestion batching.

---

## B. Significant — reasoning, principle, and warning stripped from surviving rules

### B9. "Scarcity is the only defensible advantage" — the moat argument, gone

- **Source (brief, "What This Is"):** "Nothing here is hard to replicate: standard clustering, public APIs. A large platform can copy a summary in a week but **cannot show less, because its business model forbids it. The moat is a positioning commitment, not a technology.**"
- **PRD:** **DROPPED.** §6.2 Anti-Engagement lists the exclusions as rules ("Permanently excluded from this product, not merely deferred") but never says that the exclusions *are* the competitive advantage.
- **Judgment:** Matters for durability. Without the moat argument, every anti-engagement rule reads as ascetic preference and is negotiable under pressure. With it, they are the business.

### B10. Competitive landscape — the entire scan, and the correction that reshaped positioning

- **Source (addendum, "Competitive Landscape", tagged "for PRD and positioning"):** eight named competitors (Particle, Ground News, 1440, Morning Brew, SmartNews SmartTake, PressReader, Artifact†, Nuzzel†); "**The gap:** ... no product was found doing 'a fixed small number of items, per period, per geography.'"; and "**The correction that matters:** 'read Japanese press in French' already exists ... Positioning must therefore be **curation over translated foreign press**; the raw translation claim does not survive contact with a knowledgeable sceptic."
- **Also brief, "What This Is":** "**Curation of the foreign press, not translation.**"
- **PRD:** **DROPPED entirely.** No competitor is named. Worse, UJ-2's climax states Rémi "reads what the Japanese press collectively decided mattered this week, in his own language — **something he has never been able to do without effort**" — which is exactly the raw-translation claim the addendum says "does not survive contact with a knowledgeable sceptic." The curation-not-translation framing is nowhere in the PRD.
- **Judgment:** Matters. The addendum flags this section as serving the PRD specifically, and the PRD contains the very claim the addendum corrects.

### B11. "The product is the filter" origin, and the ChatGPT-prompt challenge

- **Source (addendum, Personas — the investor):** "'Why isn't this just a ChatGPT prompt?' Forced the commoditization answer: the value is repeatable curation and trust in the criterion — the product is the filter, not the text. **This single challenge produced the brief's central insight.**"
- **PRD:** **WEAKENED.** §1 Vision states "The product is the filter, not the summary" as an assertion. The challenge that produced it, and the commoditization answer, are gone.
- **Judgment:** Moderate. The rule survives; the defence of it does not.

### B12. Coverage consensus chosen because it is *less attackable* — not merely because it is measurable

- **Source (addendum, Personas — the political sceptic):** produced the transparency differentiator "and the choice of coverage consensus as the measure — **explicitly because it is *less attackable* than editorial or model judgment.**"
- **PRD:** **WEAKENED.** §1 and §6.1 say the Score is inspectable and countable. UJ-3's climax gets closest: "the criterion is stated, countable, and arguable — he can disagree with it, which is precisely what makes it trustworthy." But the comparative rationale (less attackable *than the alternatives*) is absent.
- **Judgment:** Moderate. Explains why consensus, not "our editors picked".

### B13. "Making the invisible work visible is what makes the selection feel earned rather than asserted"

- **Source (brief, "The Interface"):** the sentence justifying the Discarded Volume display.
- **PRD:** **WEAKENED.** FR-7 requires the figure and specifies placement, but gives no reason. §4.2's description covers the Consensus Score's dual role but not this.
- **Judgment:** Low-moderate. A builder may treat 1,247/5 as decorative telemetry and cut it under layout pressure.

### B14. "Padding to five would be the first lie" / "5 is a marketing promise, not an editorial truth"

- **Source (brief, "The Interface"):** "When the day produced only three things worth knowing, it says three — **padding to five would be the first lie.**" And addendum, Rejected outright: "**Forcing exactly five items.** 'Today, only three things matter' is a rare honesty signal. **The number 5 is a marketing promise, not an editorial truth.**"
- **PRD:** **PARTIALLY PRESERVED.** FR-4 states the rule mechanically. §7 Aesthetic ("Honesty over polish") and SM-C2 ("A rising average signals padding") carry the spirit well. The rejected-alternative framing — that forcing five was considered and rejected — is gone.
- **Judgment:** Low. Best-preserved qualitative item in the document.

### B15. Anti-concentration rationale — the concrete failure it prevents

- **Source (brief, Boundary conditions):** "cap at 2 items from the same country in a continental top list, so a continent does not become its loudest nation. **Settled as a product rule:** without it, 'Africa' returns four Nigerian stories and 'Europe' four French ones, and **the continental selector stops meaning anything.**"
- **PRD:** **WEAKENED.** FR-15 states the cap and its mechanics with no rationale, then opens a *new* question (Open Question 5: should World also be capped?) that the brief had settled by scoping to continents. The brief's phrase "Settled as a product rule" is exactly a marker against relitigating.
- **Judgment:** Moderate. The PRD reopens something the brief marked closed, and the "loudest nation" reasoning that would answer the reopened question is missing.

### B16. Two-source corroboration and the misattribution evidence base

- **Source (brief, "Anti-Hallucination Policy" + addendum "AI Accuracy Evidence"):** "The dominant failure mode ... is **misattribution, not incoherence**"; EBU/BBC Oct 2025 — 22 broadcasters, 14 languages, **45%** significant issue, **81%** some issue, **31%** sourcing problems, Gemini **72%** on sourcing; BBC-only 2025-02 51%; Apple Intelligence disabled 2025-01-16; Perplexity sued 2024-10. "**The load-bearing implication:** ... this is why ... 'no synthesized statement is ever attributed to a named outlet' **is the rule that matters most.**"
- **PRD:** **WEAKENED.** The three rules survive as FR-11 and FR-12. But: the evidence base is gone entirely (no percentage, no study, no date); "misattribution, not incoherence" is gone; and the ranking among the rules is lost — "no synthesized statement is ever attributed to a named outlet" is buried as the *third* testable consequence of FR-12, alongside link-visibility mechanics, when the source calls it the single most important rule.
- **Judgment:** Matters. The rule most likely to be dropped in implementation is the one the source ranks highest and the PRD ranks lowest.

### B17. The trailer rule's second purpose — the answer to publishers

- **Source (brief, Anti-Hallucination):** "The summary is a trailer, not a substitute ... This is both an accuracy posture and **the answer to the publisher's objection about stolen traffic.**" Addendum (summarized journalist persona): "Fears traffic theft. Demanded visible attribution and an outbound link on every card, and — the sharper version — that the summary make the reader want the original."
- **PRD:** **WEAKENED.** §4.3's description carries "a trailer, not a substitute" well. The publisher/legal-defence purpose is dropped, and the persona that demanded it is gone.
- **Judgment:** Low-moderate. The rule survives; one of its two justifications does not.

### B18. Author-as-first-user framing

- **Source (brief, "What This Is"):** "This is a personal project. The author is the first user and the first test case: **if he does not open it every morning, it has failed regardless of what anyone else does.**" And Success Criteria: "Audience metrics are out of scope."
- **PRD:** **MOSTLY PRESERVED.** JTBD "Builder's" bullet and SM-2 both carry it. "Audience metrics are out of scope" is not stated as a scope boundary; §10 has no equivalent line, and §8 Non-Goals does not exclude audience measurement.
- **Judgment:** Low.

### B19. Success criterion ordering and its stated gate

- **Source (brief, Success Criteria):** "Two signals matter for v1, **in order**" — and criterion 1 "gates everything else — **a beautiful UI over a bad filter is worse than no product.**"
- **PRD:** **WEAKENED.** SM-1 and SM-2 are both "Primary" with no gating relationship. The "beautiful UI over a bad filter is worse than no product" line — which is the emotional core of the build-order decision (A1) — is gone.
- **Judgment:** Moderate, and compounds A1.

### B20. Long-run metric explicitly deferred

- **Source (brief, Success Criteria):** "The long-run metric — *decreasing time-per-visit combined with daily return* — **is not a v1 gate**; it is the right instrument once there is an audience."
- **PRD:** **DISTORTED.** SM-C1 makes time-per-visit a v1 counter-metric ("should trend down"). Not wrong in spirit, but the brief explicitly said it is not a v1 gate and requires an audience to be meaningful. With n=1 (the author), it measures nothing.
- **Judgment:** Low-moderate. Risk of someone treating SM-C1 as a v1 acceptance measure.

---

## C. Personas and their forced decisions

The brief says: "Each one forced a decision already captured in Scope below; **they are design constraints, not market segments.**" The addendum preserves nine personas, tagged "for UX". The PRD compresses nine into four journeys.

| Persona (addendum) | Forced decision | PRD status |
|---|---|---|
| The political sceptic | Transparency of criterion; consensus *because less attackable*. Parked: seeing which sources are **not** covering a story — "treating the blind spot as information in itself ... a genuinely interesting future feature" | UJ-3 covers transparency. **Blind-spot feature DROPPED** — appears in no deferred list |
| The anxious reader | End screen; refusal of infinite feed; **anti-engagement as a stated marketing argument rather than an apology** | UJ-1 covers. **The marketing-argument framing DROPPED** — §6.2 states exclusions as rules, never as a pitch |
| The commuter | Whole list on one screen, readable in one breath. "He does not want 'the news', he wants **not to be caught out in a meeting**" | UJ-4 (Sofia) preserves both well — good |
| The expat | Zone selector; and **the real purpose of the monthly period: recovering from an absence, not following daily news — three different rituals in one UI (day = habit, week = catch-up, month = archive)** | UJ-2 has Rémi catching up on a month. **The three-rituals model DROPPED** — the PRD treats day/week/month as one uniform control, which also hides why week/month matter (see A6) |
| The summarized journalist | Attribution + trailer-not-substitute | §4.3 preserves the rule; persona and traffic-theft objection dropped (B17) |
| The parent | "Explain it simply" + **one line of historical context per story — the "previously on…" device.** "The session judged this **the real gap in existing apps: nobody tells you what you missed in the previous episode.** Parked, but **the strongest of the parked features**" | §9.2 defers "explain it simply" in a flat list. **"Previously on…" / historical context DROPPED entirely** — never named anywhere. The "strongest of the parked features" judgment is lost |
| The investor | "Why isn't this just a ChatGPT prompt?" → product is the filter | B11 — rule kept, origin dropped |
| The Sunday-evening user | Reason the default-period question stays open | Open Question 6 preserves it |
| Visually impaired / multitasking | Five items as five 20-second audio tracks; 90-second briefing judged **most differentiating format identified**; "first in line for v2" | §9.2 preserves the "most differentiating" note — good. **The accessibility persona itself is DROPPED**, and NFR-4 sets WCAG AA on an untagged-in-source assumption with no link back to this user |

- **Judgment:** Two forced decisions vanished without trace — the **blind-spot / who-is-*not*-covering-this** feature and the **"previously on…" historical-context line**, the latter explicitly rated the strongest parked idea. The **three-rituals model** (day/week/month = habit/catch-up/archive) is the most consequential loss for UX, since it is the only articulation of why week and month exist at all.

---

## D. Rejected alternatives — the anti-relitigation record

The addendum's "Rejected and Parked" section is tagged "for **all** consumers — read before reopening a settled question", and distinguishes rejected (door closed) from parked (survived scrutiny, lost on sequencing). The PRD's §9.2 flattens both into "Out of Scope for MVP", losing the distinction entirely.

**Rejected outright — PRD status:**

| Rejected item | Rationale in source | PRD |
|---|---|---|
| Programmatic advertising + engagement optimization | "Permanently excluded ... would betray the anti-anxiety premise and destroy the trust the entire product rests on. **This is the one closed door.**" | §6.2 lists it as excluded. **Rationale and "the one closed door" status DROPPED.** Reads as one bullet among four |
| Scraping | Legal and operational risk; RSS + APIs sufficient | NFR-5 states the rule. Rationale dropped. Also drops the Google News RSS specifics ("ToS forbids scraping/redisplay; CAPTCHA-prone") |
| On-demand AI generation | ~8s latency kills the ritual | **PRESERVED WELL** — §4.4 description carries both the number and the reason |
| Forcing exactly five items | See B14 | Rule preserved, rejection framing dropped |
| **A static world/day page as v1** | "Considered as the minimal MVP and **rejected: the mad-libs interaction *is* the experience, and deferring it ships a different product.**" Brief Scope/In: "Full selector, not a static page — the interaction is the experience and **cannot be deferred**" | **DROPPED.** FR-1 to FR-3 require the selectors, but nothing records that shipping a static page was considered and rejected. This is the single most likely v1 scope cut, and its pre-refutation is gone |

**Parked items — PRD status:** clickable world map (kept, with the map-for-discovery/text-for-repeat-use compromise reduced to "Better for discovery than for repeat use" — acceptable), "since your last visit" (kept with its breakthrough note — good), shareable image cards (kept, rationale "free acquisition engine, each share carries the branding" dropped), single daily notification (kept; **the insight "the notification may be the real product, and the app merely the detail" is DROPPED** — only the "has to be right first time" caution survives), daily email (kept), user-defined importance (kept; **the three-axes reasoning — geopolitical/personal/economic, "the product currently picks one" — DROPPED**), breaking mode (**absorbed into FR-4 as a consequence — fine, arguably an improvement**), archives as SEO (kept as Open Question 2).

- **Judgment:** The most damaging loss here is **"a static world/day page as v1 was considered and rejected."** Under schedule pressure the mad-libs selector is the obvious cut, and the PRD gives a future reader no record that this was already argued and closed.

---

## E. Business model and naming

### E21. Business model — three options preserved as an option space

- **Source (addendum, "Business Model"):** "Out of scope ... and deliberately undecided." One permanent exclusion, plus three sketched-but-unevaluated options: single daily sponsor (most compatible with the anti-advertising stance, needs no tracking); freemium (world/day free, zones/archives/audio paid — "fits the existing architecture — the paid tier is the precomputed combinations the free tier does not serve"); B2B (zone briefings to international employers for expat staff, originating from the expat persona). "They are recorded so **the option space survives**, not because any is favoured."
- **PRD:** **DROPPED entirely.** No mention of business model anywhere, not even as an out-of-scope note or open question.
- **Judgment:** Moderate. The freemium option in particular has an architectural implication (the paid tier *is* the precomputed matrix), and FR-13's flat "generate all 135" forecloses nothing but records nothing either. The exclusion of programmatic advertising survives in §6.2 without its context.

### E22. Naming — the "sell clarity, not news" reframe

- **Source (addendum, "Naming"):** candidates (Five / FIVE.news / Cinq / The Brief / Worth Knowing / Signal); "'5' is a strong cognitive anchor (hand, fingers)"; "'News' is negatively charged for news-avoiders ... The deeper reframe: **sell clarity, not news** — the benefit is the calm of being up to date"; "'Ultimate' rejected as hollow marketing; replace vague superlatives with a counted proof ('we read 1,247 articles')"; "'Briefing' as the central concept — military/executive connotation, more dignified than 'summary'"; positioning line *"World news in 5 headlines. Nothing more. That's the point."*
- **PRD:** **PARTIALLY PRESERVED.** §7 carries "Product-generated text sells clarity, not news" — the key reframe survives. The PRD also adopts "Briefing" as its core glossary term, which honours the naming reasoning without citing it. Dropped: the candidate list is only pointed at ("Candidates and rationale in the brief addendum"), the counted-proof-over-superlative principle, the positioning line, and the note that "News" is negatively charged for the target user — which has direct consequences for page copy.
- **Judgment:** Low-moderate. §7 is the PRD's strongest qualitative section; the loss is mainly copy-level guidance.

---

## F. Tone and register — what §7 keeps and what it loses

§7 Aesthetic and Tone is the best-preserved qualitative material in the PRD. It correctly carries: the sentence-as-interface, "plain and finite", "That's all. Come back tomorrow.", "sells clarity, not news", honesty over polish, and a useful anti-references list (the anti-references list is a PRD addition, not in the source — a good one).

What the register loses relative to the brief's opening:

- **Source (brief, "The Problem"):** "The people who most want to be informed are the ones who gave up ... every session ended worse than it started — an infinite feed that mixes **a coup with a celebrity divorce and never signals which was which.** **The cost is not ignorance. It is a low-grade guilt about being ignorant, which is somehow worse.** So the need is not more news. It is **the calm of being up to date**, which is a different product: **finite by design, and measured by how quickly the reader can leave.**"
- **PRD:** The problem statement is **DROPPED as a section.** §2.1's emotional JTBD ("be up to date without the anxiety and guilt ... The benefit is calm, not information") is a competent compression, and §6.2 opens with "The product is measured by how quickly the reader leaves." But the PRD has no problem statement — it opens at §1 Vision with what the product *is*, never with what is wrong with the world.
- **Judgment:** Moderate. A PRD without a problem statement gives downstream UX and epic work no grounding for trade-off decisions that the FRs do not cover. The "coup / celebrity divorce" image and the guilt framing are the material a designer would use.

---

## G. Smaller items, for completeness

- **`sourcecountry` / `sourcelang` facets make geographic diversity *directly measurable rather than inferred*** (brief, Sources; addendum, GDELT) — the reason the geographic axis of the Consensus Score is trustworthy. PRD: DROPPED. The Glossary defines Consensus Score as including a country count with no note on where the country attribution comes from or why it is reliable.
- **"No scraping"** appears in both source docs as a hard rule with reasons. PRD NFR-5 keeps the rule, drops the reasons. Fine.
- **Clustering technique** (HDBSCAN, multilingual embeddings BGE-M3/Qwen3/LaBSE, MinHash/LSH pre-filter, Leiden alternative; "not where the risk lives"; "costs cents") — the PRD deliberately routes implementation to the addendum, which §0 declares. The only leak is §6.3's "Embedding a few thousand Headlines per cycle is a cents-scale cost" — note the brief says "per **day**", the PRD says "per **cycle**", and "Headlines" is capitalized as if a Glossary term but is not defined in §3.
- **Verification debt** (addendum): two open items — GDELT rate limits AND NewsData.io terms. PRD Open Question 3 carries only NewsData.io. The GDELT rate-limit uncertainty is dropped.
- **NewsData.io as "best free-tier fallback"** (brief, Sources) — PRD mentions NewsData.io only in Open Question 3 as a terms question; its role as the designated fallback source is not stated. Mediastack, TheNewsAPI, Bing retirement all dropped (defensible — addendum is tagged for architecture).
- **"The AI runs a few dozen times a day rather than once per user"** (brief, Architecture Constraint) — the scalability half of the "three things at once" argument (zero latency, predictable cost, scalability). PRD keeps latency (NFR-1) and cost (NFR-2); scalability survives only implicitly in NFR-2's "adding readers does not add AI calls". Minor.
- **Consensus Score definition drift** — Glossary: "the count of Independent Sources **and** the count of distinct countries." FR-6 displays both. But nothing states how the two combine into a *ranking*. The brief says "rank clusters by **size and source diversity**". The PRD never specifies the ranking function or that diversity is a ranking input, not just a display. This is arguably the single most important algorithm in the product and the PRD leaves it undefined.

---

## Summary table — highest-priority remediation

| # | Gap | Type | Priority |
|---|---|---|---|
| A1 | Build order: pipeline built and observed before UI | DROPPED | **Critical** |
| A3/A4/A5 | 15 Zones, 3 languages, 135 Briefings asserted; brief left geography undecided (5–10 countries) and named no languages | INVENTED | **Critical** |
| A6 | Day-boundary cluster linking for week/month — "a real design task, not a configuration flag" | DROPPED | **Critical** |
| A2 | Syndication layers must be built in order, inspect after layer 1; §9.1 says "all three layers" | WEAKENED/CONTRADICTED | High |
| A7 | Full article text unavailable — "definitively rules out any design where the AI reads whole articles" | DROPPED | High |
| D | "A static world/day page as v1" was considered and rejected | DROPPED | High |
| B16 | "No synthesized statement attributed to a named outlet" is *the rule that matters most*; misattribution evidence base | WEAKENED | High |
| B10 | Competitive scan + "curation, not translation" correction; UJ-2 restates the corrected claim | DROPPED/CONTRADICTED | High |
| C | Three rituals: day = habit, week = catch-up, month = archive | DROPPED | High |
| C | "Previously on…" historical-context line — "the strongest of the parked features" | DROPPED | Medium |
| C | Blind-spot feature (which sources are *not* covering a story) | DROPPED | Medium |
| B9 | Scarcity as the moat — "cannot show less, because its business model forbids it" | DROPPED | Medium |
| B15 | Anti-concentration rationale; brief marked it "settled", PRD reopens it as Open Question 5 | WEAKENED | Medium |
| B19/B20 | SM-1 gates SM-2; "beautiful UI over a bad filter is worse than no product"; time-per-visit "not a v1 gate" | WEAKENED/DISTORTED | Medium |
| E21 | Business model section — three options + "the one closed door" rationale | DROPPED | Medium |
| F | Problem statement — guilt, "coup with a celebrity divorce", "calm of being up to date" | DROPPED | Medium |
| G | Ranking function never specified (brief: "size and source diversity") | DROPPED | Medium |
| A8/G | GDELT MAXRECORDS 250, real rate limit unknown; GDELT half of verification debt | WEAKENED | Medium |
