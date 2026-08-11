---
title: "Product Brief: 5 News"
status: final
created: 2026-08-10
updated: 2026-08-10
---

# Product Brief: 5 News

## The Problem

The people who most want to be informed are the ones who gave up. They deleted the news apps because every session ended worse than it started — an infinite feed that mixes a coup with a celebrity divorce and never signals which was which.

The cost is not ignorance. It is a low-grade guilt about being ignorant, which is somehow worse.

So the need is not more news. It is the calm of being up to date, which is a different product: finite by design, and measured by how quickly the reader can leave.

## What This Is

Two to five events per day, chosen because the world's press converged on them and summarized in the reader's language. Then the page ends.

**The product is the filter, not the summary.** A ranked list of five raw headlines with links is already useful; five AI summaries of arbitrarily chosen stories are worthless. The engineering effort goes into clustering articles that describe the same event and ranking those clusters by how much of the world's press covered them. The AI is the last step, applied to clusters a deterministic pipeline has already selected.

**Importance is measured, not judged.** A story ranks because 34 outlets across 12 countries covered it — an inspectable criterion — rather than because a model decided it mattered. That measurement answers the product's hardest question — *who decides what is important?* — and the measurement is displayed on every item.

**Scarcity is the only defensible advantage.** Nothing here is hard to replicate: standard clustering, public APIs. A large platform can copy a summary in a week but cannot show less, because its business model forbids it. The moat is a positioning commitment, not a technology.

**Curation of the foreign press, not translation.** PressReader has auto-translated international newspapers into 30+ languages for years. The uncovered space is translation *plus* consensus-based curation — reading in French the five stories the Japanese press converged on. Competitive detail is in the addendum.

This is a personal project. The author is the first user and the first test case: if he does not open it every morning, it has failed regardless of what anyone else does.

## The Interface

The reader arrives and the day's five world stories are already on screen. No onboarding, no configuration before value is shown.

The page title is a fill-in-the-blank sentence whose blanks are the controls:

> The 5 most important news **[of the day]** **[in the world]**

Clicking a word changes it and the result refreshes: period cycles through day / week / month, zone through country / continent / world. The sentence replaces the title, the labels, and the submit button all at once.

Each item shows why it is there: *covered by 34 sources across 12 countries*. Beneath the list, the discarded volume: *1,247 articles read, 5 kept*. Making the invisible work visible is what makes the selection feel earned rather than asserted.

Then it stops. **That's all. Come back tomorrow.** When the day produced only three things worth knowing, it says three — padding to five would be the first lie.

Personas from the brainstorming session are in the addendum. Each one forced a decision already captured in Scope below; they are design constraints, not market segments.

## Success Criteria

Audience metrics are out of scope. Two signals matter for v1, in order:

1. **The filter is credible.** Compare the generated top 5 against what the author knows about the day: no absurdities, no human-interest filler, no major omissions. This is a daily eyeball check on pipeline output, and it gates everything else — a beautiful UI over a bad filter is worse than no product.
2. **The author uses it daily.** Unprompted, replacing his existing habit, one month after launch.

The long-run metric — *decreasing time-per-visit combined with daily return* — is not a v1 gate; it is the right instrument once there is an audience.

## Scope

### In

- The mad-libs interface: period (day / week / month) × zone (country / continent / world) as inline clickable words. Full selector, not a static page — the interaction is the experience and cannot be deferred.
- World / day as the immediate default on arrival.
- Ingestion → event clustering → ranking by coverage consensus → AI summary of the surviving clusters.
- Variable count of 2 to 5.
- Explicit end screen.
- Per-item transparency: source count and country count. Discarded-volume figure on the page.
- Visible attribution and outbound link on every item.
- Summaries generated in the reader's language regardless of source language.
- Web only.

### Out

Deferred with intent, not forgotten: newsletter, push notification, audio briefing, clickable world map, "since your last visit" personal time window, tone badges, "explain it simply" mode, user-defined importance, shareable image cards.

### Boundary conditions the pipeline must handle

- **Small countries with thin source coverage** → graceful fallback to the continent, stated explicitly to the reader rather than silently substituted.
- **Anti-concentration** → cap at 2 items from the same country in a continental top list, so a continent does not become its loudest nation. Settled as a product rule: without it, "Africa" returns four Nigerian stories and "Europe" four French ones, and the continental selector stops meaning anything.
- **A day with a single dominating story** → one item, full screen, rather than four filler items beneath it.

## Architecture Constraint

**Batch generation via cron. Never AI on demand.** An AI call at click time costs ~8 seconds of waiting, and waiting kills a ritual. Every zone × period combination is precomputed and served from cache. This one decision delivers three things at once: zero latency, predictable cost, and scalability — the AI runs a few dozen times a day rather than once per user.

The pipeline is three deterministic steps plus one AI step: collect headlines over the time window, cluster articles describing the same event, rank clusters by size and source diversity, then summarize the survivors.

**Sources.** GDELT is the primary signal: free, no API key, 65 languages, with `sourcecountry` and `sourcelang` facets that make geographic diversity directly measurable rather than inferred. It provides coverage volume per query but **does not provide event clusters** — clustering is ours to build. RSS feeds of major outlets supplement it. No scraping. NewsAPI.org is ruled out: its free tier is non-commercial and localhost-only, and the next tier up is $449/month with nothing in between. NewsData.io is the best free-tier fallback. `[VERIFY: its free tier reportedly permits commercial use, but the claim comes from their own marketing blog — confirm in the current terms before depending on it.]` Full API comparison, rate limits, and query ceilings are in the addendum.

**Clustering** is standard work, not a risk: multilingual sentence embeddings fed into HDBSCAN, with near-duplicate pre-filtering. Current multilingual models support cross-language clustering well, which is what makes the foreign-press angle affordable — embedding a few thousand headlines a day costs cents.

## The Ranking Integrity Risk

The single biggest threat to this product is not hallucination — it is **wire copy**. AP and Reuters dispatches are republished by hundreds of outlets. A count of "34 sources across 12 countries" may be measuring one dispatch reprinted 34 times — the opposite of consensus, yet indistinguishable from real consensus in the data.

This matters more than every other technical problem here, because the coverage-consensus number is both the ranking mechanism *and* the trust artifact shown to the reader. Syndication inflation breaks both at once — the wrong stories rank, and the number displayed as proof is itself wrong. Nothing off the shelf solves it.

The pipeline therefore needs explicit syndication detection, and the displayed count must reflect *independent* coverage. **This is a v1 requirement, not a later refinement** — the first success criterion is that the filter is credible, and credibility cannot be judged on a ranking whose signal is polluted. Three layers, in build order:

1. **Near-duplicate title collapse.** Catches verbatim reprints, which are the bulk of the noise. Cheap, and enough to make the number roughly honest.
2. **Wire-attribution metadata**, where the source exposes it.
3. **Rewrite detection** — semantic clustering that recognizes a locally rewritten dispatch as the same underlying report.

Build them in that order and inspect the output after the first layer rather than after the third. The risk here is not cost but sequence: several days spent refining deduplication before ever seeing a top 5 would invert the whole point of building the pipeline first.

## Anti-Hallucination Policy

The dominant failure mode in the AI-news literature is **misattribution, not incoherence**: models write perfectly readable prose that says the wrong thing about who said what. The EBU/BBC study of October 2025 found that 45% of AI assistant responses about news contained a significant issue and that 31% had sourcing problems; the supporting evidence table is in the addendum.

The architecture is sound on the point that matters most: the AI never selects or ranks, so the product's central judgment has no hallucination surface at all. The remaining surface is the summary text, governed by three rules:

1. A summary states nothing that is not present in at least two concordant sources within the cluster.
2. Every claim is anchored to a source, and the outbound link is prominent.
3. No synthesized statement is ever attributed to a named outlet.

The summary is a trailer, not a substitute: it should make the reader want the original. This is both an accuracy posture and the answer to the publisher's objection about stolen traffic.

## Build Order

**The pipeline is built and observed before the UI is built.** Collection, deduplication, clustering, and ranking come first; the output is inspected for several days; the interface follows only once the top 5 is credible. Validation targets the quality of the filter — the actual product — rather than market appetite. This replaces the brainstorm's suggestion to spend two weeks on manual briefings before writing code: development starts immediately, and the cost of being wrong is time rather than money.

## Open Questions

None of these block the start of development.

- **Launch geography** — covering 5–10 countries well beats covering the whole world badly. The specific list is undecided.
- **Default period** — settled: v1 ships with *day*. Week and month remain clickable from the start, but keeping the daily default off the critical path means cross-day cluster linking is only needed when those views are built. Sunday-evening ritual usage may still argue for *week* later; observe once in use.
- **Persisting the last zone/period choice** between visits — a returning reader should not reconfigure the sentence every morning. Does the remembered choice become the new landing state, or does world/day always greet first with the previous choice one click away?
- **Archives and SEO** — each archived briefing is an indexable page; 365 a year. In v1 or after?
- **Business model** — out of scope for a personal project. Options and the one permanently closed door (programmatic advertising and engagement optimization) are in the addendum.
- **Name and domain** — candidates and rationale in the addendum. Availability unchecked; worth doing early.

Later channels would reuse the same engine: a single daily email where the notification *is* the product, and a ninety-second audio briefing. Both are out of v1; rationale in the addendum.
