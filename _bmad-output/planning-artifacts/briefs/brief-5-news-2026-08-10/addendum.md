---
title: "Addendum: 5 News"
status: draft
created: 2026-08-10
updated: 2026-08-10
---

# Addendum: 5 News

Depth that earned a place but does not belong in the brief. Downstream consumers — PRD, architecture, UX — should read this alongside `brief.md`. Source: brainstorming session of 2026-08-10 plus grounding research run during brief creation.

This is a reference document, not a narrative one. Sections are independent; read the one you need. Each is tagged with the downstream consumer it primarily serves.

| Section | Primarily serves |
|---|---|
| Source Landscape | Architecture |
| Clustering Approach | Architecture |
| Wire Copy | Architecture, PRD |
| AI Accuracy Evidence | PRD |
| Competitive Landscape | PRD, positioning |
| Personas | UX |
| Rejected and Parked | All — read before reopening a settled question |
| Naming | Positioning |

## Source Landscape (for architecture)

What each candidate data source provides, what it costs, and which limits the ingestion design has to accommodate.

### GDELT — primary signal

Verified live and free as of August 2026; project blog active through 2026-08-08.

**Three usable surfaces:**

| Surface | Access | Notes |
|---|---|---|
| DOC 2.0 API | No auth, no key, JSON | Article-level search only |
| Events 2.0 | BigQuery | CAMEO-coded actor/action tuples, 15-min refresh |
| GKG 2.0 | BigQuery | 15-min refresh; inside BigQuery's free 1TB/month tier |

**DOC 2.0 modes relevant to coverage-consensus ranking:** `TimelineVol` and `TimelineVolRaw` (coverage volume over time), `TimelineSourceCountry` (the geographic-diversity signal), `TimelineLang`, `ToneChart`. Filters include `sourcecountry`, `sourcelang`, tone, and domain.

**Hard limits to design around:**
- `MAXRECORDS` caps at **250** (default 75). This is the ceiling that shapes ingestion batching.
- Default search window is 3 months; minimum timespan 15 minutes.
- Documented throttle is ~1 request / 5 seconds, but real-world enforcement is reportedly harsher: one measurement (2026-07-27) found that ~60 requests over 90 minutes triggered a block, with no stated retry interval. The real limit is undocumented and can change without notice.

**What GDELT does not give us:** event clusters. Events 2.0 offers CAMEO-coded tuples, which is a different abstraction — useful for "protest in country X", not for "the five biggest stories". Coverage-volume signals exist but only *per query you supply*, meaning you must already know the topic. Clustering remains ours to build.

**Non-English coverage is GDELT's strongest fit for this product:** 65 machine-translated languages, English keyword search across all of them, plus the `sourcecountry` / `sourcelang` facets that make the geographic-diversity ranking signal directly measurable rather than inferred.

### News API comparison

| Provider | Free tier | Commercial use on free | Verdict |
|---|---|---|---|
| **NewsData.io** | 200 credits/day, ~97k sources, ~89 languages | Reportedly permitted | Best free-tier fit; verify terms directly |
| **NewsAPI.org** | Developer tier, localhost only | No | Ruled out — next tier is $449/mo, nothing between |
| **Mediastack** | 100 req/**month**, 30-min delay | No | Not viable |
| **TheNewsAPI** | Evaluation only | No | Real-time and historical both paid |
| **Bing News Search** | — | — | **Retired 2025-08-11**, fully decommissioned |
| **Google News RSS** | Undocumented endpoints | No | ToS forbids scraping/redisplay; CAPTCHA-prone; legal and operational risk |

Bing's replacement is Grounding with Bing Search inside Azure AI Agent Service: preview status, per-tool-call billing, Azure lock-in, and reported cost increases of 40–483%. Not a drop-in.

**Full article text is unavailable on essentially every cheap tier** — headlines, snippets, and metadata only. This suits the architecture (cluster on headlines, summarize from snippets) but definitively rules out any design where the AI reads whole articles.

### Verification debt

Applies to this whole section. The research pass could not confirm the following, and they are carried forward as unverified — check them before any design depends on them:
- Exact current GDELT rate-limit numbers — undocumented, no official page.
- NewsData.io's 2026 paid pricing, and whether free-tier commercial permission appears in its **current** terms. The claim came from the provider's own marketing blog, not the terms themselves.

## Clustering Approach (for architecture)

The technique for grouping articles that describe the same event, its cost, and the two edges where it gets hard.

The standard 2026 stack: sentence embeddings → cosine similarity → **HDBSCAN** (no preset *k* required, and outperforms k-means and agglomerative clustering on news corpora). An alternative formulation is similarity-graph construction followed by **Leiden** community detection. MinHash/LSH serves as a near-duplicate pre-filter.

Cross-language clustering via multilingual embeddings (BGE-M3, Qwen3, LaBSE-class models) is a solved-enough problem, which is what makes the translated-foreign-press angle affordable rather than aspirational.

**Realistic difficulty: moderate. This is not where the risk lives.** Embedding a few thousand headlines per day costs cents.

**Two known hard edges:**

1. **Day-boundary continuity.** Clusters built per UTC ingest-day do not merge across days for ongoing stories. The weekly and monthly views require explicit cluster linking, not just a wider query window. This is a real design task, not a configuration flag.

2. **Wire-copy dedup.** The primary ranking-integrity risk; it has its own section below.

## Wire Copy — the Top Technical Risk (for architecture and PRD)

Why syndication is the one technical problem that threatens the product's core claim, and what mitigation must be built.

AP and Reuters dispatches are republished by hundreds of outlets. A naive source count measures republication, not consensus, while being indistinguishable from it in the data.

The problem compounds because the coverage-consensus number serves two roles at once: it is the ranking mechanism *and* the trust artifact displayed to the reader. Syndication inflation breaks both at once — the wrong stories rank, and the number shown as proof is itself the thing that is wrong.

Nothing off the shelf solves this. Settled as a v1 requirement, built in three layers in this order:

1. **Near-duplicate title collapse before counting.** Catches verbatim reprints — the bulk of the noise — for a few hours of work. Enough on its own to make the displayed number roughly honest.
2. **Wire-attribution metadata**, where the source exposes it. Cheap when present, absent often enough that it cannot be the only layer.
3. **Rewrite detection.** Semantic clustering that recognizes a locally rewritten dispatch as the same underlying report. The expensive layer, and the one that distinguishes real consensus from a well-syndicated wire story.

In all cases the displayed figure is *independent* coverage, never a raw source count.

**Sequencing note.** Inspect pipeline output after layer 1 rather than after layer 3. Spending several days refining deduplication before ever seeing a top 5 would invert the purpose of building the pipeline before the UI.

## AI Accuracy Evidence (for the PRD's anti-hallucination policy)

The published record on AI-generated news errors, and what it implies for where the guardrails belong.

| Study / event | Date | Finding |
|---|---|---|
| EBU/BBC multi-broadcaster study | 2025-10-21/22 | 22 public broadcasters, 14 languages, largest of its kind: **45%** of AI assistant responses about news contained ≥1 significant issue; **81%** had some issue; **31%** had sourcing problems. Gemini worst on sourcing at **72%** vs under 25% for others. Errors were consistent across languages and territories. |
| BBC-only study | 2025-02 | 51% of responses on BBC news queries had significant issues |
| Apple Intelligence | 2025-01-16 | News/Entertainment notification summaries disabled in iOS 18.3 beta after fabricating BBC headlines |
| Perplexity litigation | 2024-10 | Sued by Dow Jones and NY Post over allegedly hallucinated story content |

**The load-bearing implication:** the dominant failure mode across all of these is *misattribution and sourcing*, not fluency. Models produce readable prose that says the wrong thing about who said what. This is why the three-rule policy in the brief targets attribution rather than general accuracy, and why "no synthesized statement is ever attributed to a named outlet" is the rule that matters most.

It also explains why the architecture is structurally defensible: the AI never selects or ranks, so the product's central judgment — which five stories — has no hallucination surface at all.

## Competitive Landscape (for PRD and positioning)

Who else occupies this space, and what the scan established about where the genuine gap is.

| Product | Status | Relevance |
|---|---|---|
| **Particle** | Active | Closest architectural competitor. Ex-Twitter team (Sara Beykpour, Marcel Molina), $4.4M seed, multi-source AI synthesis |
| **Ground News** | Active | Bias and source-diversity angle — overlaps our geographic-diversity signal |
| **1440** | >4M subscribers | The finite-daily-digest incumbent, email not app |
| **Morning Brew** | >4M subscribers | Same category |
| **SmartNews SmartTake** | Active since 2023 | Explicit "anti-doomscrolling" finite-scroll feature |
| **PressReader** | Active | Auto-translates international newspapers into 30+ languages — the reason our differentiator is curation, not translation |
| **Artifact** | Dead (Jan 2024) | Tech acquired by Yahoo, folded into Yahoo News |
| **Nuzzel** | Dead | Lost to the Twitter/Scroll acquisition |

**The gap:** anti-doomscroll finite news is a recognized 2026 category, but no product was found doing "a fixed small number of items, per period, per geography." That specific framing appears genuinely unoccupied.

**The correction that matters:** "read Japanese press in French" already exists as a capability — PressReader and World Newspapers both auto-translate. What does not exist is *curated top-N + consensus ranking + translation*. PressReader is a full-catalog reader: it hands you everything and asks you to choose. Positioning must therefore be **curation over translated foreign press**; the raw translation claim does not survive contact with a knowledgeable sceptic.

## Personas — Full Session Material (for UX)

The brief compresses each persona to the decision it forced. The fuller material is preserved here for UX work. Each entry follows the same shape: who they are, what they forced into scope, and what they asked for that was parked.

**The political sceptic.** Asks "who decides what's important?" and will call bias at the first opportunity. Produced the transparency-of-criterion differentiator and the choice of coverage consensus as the measure — explicitly because it is *less attackable* than editorial or model judgment. Parked: seeing which sources are **not** covering a story, treating the blind spot as information in itself. Out of scope for v1, but a genuinely interesting future feature.

**The anxious reader.** Deleted the social news apps and feels guilty about it. Wants to return to news without an anxiety relapse. Produced the end screen, the refusal of the infinite feed, and anti-engagement as a stated marketing argument rather than an apology. Parked: a **tone badge** shown before opening an item, for emotional-load control.

**The commuter.** Seven minutes on the metro. Forced the whole list onto one screen without scrolling, readable in one breath. Session insight worth keeping: he does not want "the news", he wants **not to be caught out in a meeting** — the product angle is conversational assurance, not information delivery. Parked: a "read in 60 seconds" mode with a visible timer, proposed as a contractual promise.

**The expat.** French national in Singapore, follows both home and host country. Justified the zone selector. Revealed the real purpose of the **monthly** period: recovering from an absence, not following daily news — three different rituals in one UI (day = habit, week = catch-up, month = archive). Parked: two simultaneous zone selections.

**The summarized journalist.** Fears traffic theft. Demanded visible attribution and an outbound link on every card, and — the sharper version — that the summary make the reader want the original. **A trailer, not a substitute.** This is where the attribution rules in the brief come from.

**The parent.** Wants to explain the world to a teenager. Produced the "explain it simply" mode and the idea of one line of historical context per story — the *"previously on…"* device from TV serials applied to news. The session judged this the real gap in existing apps: nobody tells you what you missed in the previous episode. Parked, but the strongest of the parked features.

**The investor.** "Why isn't this just a ChatGPT prompt?" Forced the commoditization answer: the value is repeatable curation and trust in the criterion — the product is the filter, not the text. This single challenge produced the brief's central insight.

**The Sunday-evening user.** Weekly ritual rather than daily. The reason the default-period question stays open.

**The visually impaired / multitasking user.** Wants to listen, not read: five items as five 20-second audio tracks. The session judged the 90-second audio briefing the **most differentiating format identified** — it solves overload, time constraints, and multitasking at once — but it is more expensive to produce. Parked: out of v1, first in line for v2.

## Rejected and Parked — With Rationale (for all consumers)

Keeping the *why* so these are not relitigated from scratch. "Rejected" means the door is closed on current information; "parked" means the idea survived scrutiny but lost on v1 sequencing.

**Rejected outright:**
- **Programmatic advertising and engagement optimization.** Permanently excluded. Would betray the anti-anxiety premise and destroy the trust the entire product rests on. This is the one closed door.
- **Scraping.** Legal and operational risk; RSS plus aggregation APIs are sufficient.
- **On-demand AI generation.** ~8 seconds of latency per click kills the ritual. Superseded by cron batch precomputation.
- **Forcing exactly five items.** "Today, only three things matter" is a rare honesty signal. The number 5 is a marketing promise, not an editorial truth.
- **A static world/day page as v1.** Considered as the minimal MVP and rejected: the mad-libs interaction *is* the experience, and deferring it ships a different product.

**Parked with intent:**
- **Clickable world map.** More attractive for first visit and social sharing, slower for repeat use. The session's compromise: map for discovery/onboarding, text selector for repeat use — two doors to the same data.
- **"Since your last visit."** Replacing "the 5 news of the last 24h" with "the 5 news you missed" was flagged as a major potential breakthrough — personal time windows beating calendar windows. Cut from v1 for complexity, not for lack of value.
- **Shareable image cards.** Free acquisition engine; each share carries the branding and the promise.
- **Single daily notification containing the five headlines.** The session's resolution of the notification paradox: one notification, at a user-chosen hour, that already contains the value. The insight went further — *the notification may be the real product, and the app merely the detail.* Held back because notifications sit so close to the anti-anxiety promise that they have to be right first time.
- **Daily email newsletter** from the same engine. Zero-cost distribution channel.
- **User-defined importance.** Choosing between "impact on my life" and "impact on the world" — importance has at least three axes (geopolitical, personal, economic) and the product currently picks one.
- **Breaking mode.** On a day when one story crushes everything, a single card takes the full screen.
- **Archives as SEO asset.** Each archived briefing is an indexable page; a year yields 365 of them capturing retrospective search. A slow but real moat.

## Business Model (for positioning)

Out of scope for a personal project, and deliberately undecided. One position is settled permanently: **programmatic advertising and engagement optimization are excluded**, for the reasons under "Rejected outright" above.

Three options were sketched in the session and none was evaluated. They are recorded so the option space survives, not because any is favoured:

1. **Free with a single daily sponsor.** One sponsor per day, non-intrusive format. The option most compatible with the anti-advertising stance, since it needs no tracking and no engagement optimization.
2. **Freemium.** World/day free; zones, archives, and audio paid. Fits the existing architecture — the paid tier is the precomputed combinations the free tier does not serve.
3. **B2B.** Zone briefings sold to international employers for their expatriate staff. The expat persona is the origin of this one.

Each would need real work before it means anything. Deciding this is not on the v1 path.

## Naming — Session Candidates (for positioning)

Candidates and the reasoning behind them, held for when the name decision is actually made.

Five / FIVE.news / Cinq / The Brief / Worth Knowing / Signal. Domain availability unchecked; the session flagged checking early.

Reasoning from the title-autopsy exercise:
- **"5"** is a strong cognitive anchor (hand, fingers) — memorable where 7 or 10 would be noise. Worth keeping as the brand. Naming the constraint rather than the category ("Five", "The Five", "Daily Five") was the preferred direction.
- **"Get"** frames news as a transaction — come get your dose and leave — which is coherent with the anti-doomscroll stance. Alternatives: "Catch up on" (frames recovery), "Know" (frames competence).
- **"Ultimate"** was rejected as hollow marketing; replace vague superlatives with a counted proof ("we read 1,247 articles").
- **"News"** is negatively charged for news-avoiders. "The 5 things that happened" is more neutral. The deeper reframe: sell **clarity, not news** — the benefit is the calm of being up to date.
- **"Briefing"** as the central concept — military/executive connotation, synthesis for a decision-maker, more dignified than "summary".

Positioning line from the session: *"World news in 5 headlines. Nothing more. That's the point."*
