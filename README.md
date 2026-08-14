# 5 News

**Five stories a day, chosen by how many independent sources agree — never by an editor, never by a model.**

[5-news.vercel.app](https://5-news.vercel.app)

Most news products optimise for engagement. This one optimises for *finishing*: it shows at most five items, tells you exactly why each one is there, and then ends the page. No infinite scroll, no recommendations, no "you might also like".

The product is the filter, not the writing. A ranked list of five raw headlines with links is already useful; five AI summaries of arbitrarily chosen stories are worthless.

---

## How an item earns its place

Ranking is **deterministic**. No model call, no randomness, no wall-clock read — re-running on identical input produces byte-identical output. The AI never selects, orders, or scores anything; it only writes the text for stories already chosen.

A story qualifies when at least **2 independent sources** covered it. "Independent" is the load-bearing word: a Reuters dispatch republished by twelve outlets counts **once**. Three layers of syndication detection collapse those reprints before anything is counted, so the number you see is a claim about genuine corroboration rather than about republication volume.

Every item shows its own evidence — the independent source count and the number of distinct countries, expandable to the actual outlet list. If the displayed count says 5 sources, the expanded list contains exactly 5. Each Briefing also states how many articles were reviewed to produce it ("1,384 reviewed → 4 kept"), because a high discard count is the filter working, not the filter underperforming.

## Reading it

One sentence is the entire interface:

> Here's what's happening **in the World**, **today**.

The two bold words are controls. Clicking the first cycles through 15 zones (World, 6 continents, 8 countries); clicking the second cycles day → week → month. The URL always reflects the selection, so any combination is linkable, and the page works without JavaScript — every combination is also a real static route.

When a country has too little coverage to fill a Briefing, it serves the containing continent's instead **and says so in a full sentence** rather than silently substituting.

Available in French, English, and Spanish, with summaries written in the reader's language regardless of what language the underlying articles were in.

---

## Architecture

Two halves that share nothing but a directory of JSON files.

```
GDELT + 11 RSS feeds
        │
        ▼
   ┌──────────────────────────────────────────────┐
   │ pipeline/  (Python 3.11)                     │
   │                                              │
   │ collect → dedupe → cluster → rank            │
   │            │         │        │              │
   │      syndication  Cohere   deterministic     │
   │       detection   embed-v4  Consensus Score  │
   │                                              │
   │ → summarize (Claude Haiku 4.5, Batch API)    │
   │ → publish   (atomic, 135 files)              │
   └──────────────────────────────────────────────┘
        │
        ▼   data/briefings/<lang>/<zone>/<period>.json
        │
   ┌──────────────────────────────────────────────┐
   │ site/  (Astro 7, static)                     │
   │ reads JSON, renders, does nothing else       │
   └──────────────────────────────────────────────┘
```

Four invariants do most of the work:

| | |
|---|---|
| **The read path computes nothing** | No code under `site/` may call an AI, embedding, or third-party API — at build time or request time. A reader request costs no money and no latency proportional to demand. |
| **Files are the only interface** | The pipeline writes JSON; the site reads it. Neither half imports the other, and a boundary check in CI enforces it. Either half is replaceable without touching the other. |
| **One stage owns each field** | `dedupe` owns counts, `cluster` owns membership, `rank` owns ordering, `summarize` owns generated text, `publish` owns timestamps. Recomputing another stage's value is a defect even when the result matches. |
| **Failure degrades coverage, never the cycle** | Every adapter returns partial results plus a record of what failed. A rate-limited upstream produces a thinner Briefing with the shortfall stated in the cycle metadata — not an empty page, and not a red build. |

A cycle runs daily in GitHub Actions and is **two-phase**: the Batch API is asynchronous (up to 24 h), and a scheduled job must exit rather than block. Phase one submits and exits; a later invocation collects and publishes. Publication is atomic — a complete Briefing set is written, or the previous one is left untouched.

## Repository layout

```
pipeline/        stages/ (9) and adapters/ (GDELT, RSS, Cohere, Claude)
site/            Astro app — components, islands, fixtures, e2e tests
data/            briefings/ (published output), intermediate/, history/
tests/           pipeline test suite
scripts/         check-boundary.sh — enforces the pipeline/site split
docs/            project documentation
_bmad-output/    planning artifacts: PRD, architecture spine, UX spines, per-story records
```

## Running it

Requires Python 3.11 (via [uv](https://docs.astral.sh/uv/)) and Node 24.

```bash
# Site — works immediately, no keys needed (falls back to committed fixtures)
cd site && npm install && npm run dev

# Pipeline — needs API keys, see .env
set -a; source .env; set +a
uv run python -m pipeline.stages.cycle
```

Stages are independently invocable against a saved input, which is what makes the output inspectable stage by stage rather than only end to end.

### Verification

The full check, as CI runs it:

```bash
uv run ruff check . && uv run ruff format --check .   # lint
uv run pytest -q                                      # 328 pipeline tests
bash scripts/check-boundary.sh                        # pipeline/site independence
cd site && npx tsc --noEmit && npx astro check        # types
cd site && npx vitest run                             # 196 site + e2e tests
cd site && npm run build                              # 136 static pages
```

### Keys

Two, both used only by the pipeline. See `.env` (gitignored) for what each one does and how each degrades when absent. Scheduled cycles read them from GitHub repository secrets; the site needs none.

---

## Status

The pipeline, the reading surface, and the PWA layer are built and tested. Deployed to Vercel from `main`.

**The pipeline published its first real Briefing set on 2026-08-14** — 135 files, real headlines and summaries written per language, real outbound links. Getting there took five distinct fixes, each hidden behind the previous one: the same-Event clustering threshold was strict enough that nothing ever merged (so no story reached the 2-source floor), collection was bounded by request count but not by wall-clock, AD-11's phase two was unreachable because every run minted a fresh cycle id, and the three files a resumed cycle re-reads were gitignored.

Coverage is currently thin — typically 2 items rather than 5 — because GDELT has been returning HTTP 429 to every request for days, leaving only the 11 RSS feeds. That is the filter working as designed on a small corpus, not a fault: a Zone without enough qualifying coverage falls back to its Continent and says so. Volume will follow whenever GDELT is reachable again.

Built with the [BMad Method](https://github.com/bmad-code-org/BMAD-METHOD) — every epic and story, including the adversarial review findings and the decisions that were reversed along the way, is recorded under `_bmad-output/`.
