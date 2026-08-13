---
name: 5 News
status: final
sources:
  - {planning_artifacts}/epics.md
  - {planning_artifacts}/architecture/architecture-5-news-2026-08-10/ARCHITECTURE-SPINE.md
updated: 2026-08-12
---

# 5 News — Experience Spine

## Foundation

Single-surface, responsive web — mobile-first (NFR-1's "typical mobile connection" framing), scaling up to desktop with wider margins, never additional columns. No native app shell in v1 beyond Epic 5's PWA installability (add-to-home-screen, same single page). No UI system named; this spine and `DESIGN.md` are the whole visual/behavioral contract. Statically built (Astro, `output: "static"`, per the architecture spine's AD-1/AD-2) — every Briefing the page can ever show already exists as a JSON file at build time; there is no server-rendered or client-fetched per-request state. No account, no auth, no personalization — every visitor at the same URL sees the same content.

## Information Architecture

There is exactly **one page**, addressed by the (Output Language, Zone, Period) triple — the same addressing the pipeline already uses for `data/briefings/<lang>/<zone>/<period>.json` (architecture spine, Consistency Conventions). Changing any of the three re-renders the same page with a different Briefing; there is no separate route per Zone or Period.

| Surface | Reached from | Purpose |
|---|---|---|
| Briefing page | Any URL under the site (Zone/Period/Language all optional path segments, defaulting to World/day/browser-detected language) | The entire product: mad-libs sentence, item list, Discarded Volume, End Screen |

Within that one page, four regions stack top to bottom, always in this order:

1. **Header** — Output Language control (top-right), site identity mark (top-left, minimal).
2. **Mad-libs sentence** — the Zone/Period-selecting title ("Here's what's happening in **the World** **today**"), plus the Continent-fallback notice directly beneath it when FR-16 applies.
3. **Item list** — 2 to 5 Briefing items, each: a generated headline (`<h2>`), a Summary paragraph beneath it, Consensus chip (expandable to source list), attribution + outbound link. The headline is what makes the list scannable — a reader picks which items to read from the headlines alone. Both text fields come from the pipeline (`BriefingRecord` carries `headline` and `summary` per Cluster as of schema_version 2); the page never derives one from the other.
4. **Discarded Volume + End Screen** — the ingested/kept ratio (FR-8), then the hairline rule and completion statement (FR-5). Nothing renders below this.

→ Composition reference: `mockups/briefing-world-day.html` (World/day, 4 items, no fallback), `mockups/briefing-fallback.html` (a Country Zone showing its Continent-fallback notice, plus the Consensus chip's expanded state from Flow 3). Spine wins on conflict with either mock.

Every Zone/Period/Language combination the pipeline generates (135 per cycle) is reachable from this one IA node — closure holds because the mad-libs sentence is a complete selector for all three axes, not a partial one.

## Voice and Tone

Microcopy. Brand voice and visual register live in `DESIGN.md.Brand & Style`.

| Do | Don't |
|---|---|
| "Here's what's happening in **the World**, **today**." | "Your personalized world feed" |
| "5 independent sources across 4 countries." | "Trending in 4 countries! 🔥" |
| "Showing Europe — France doesn't have enough coverage today." | "Oops! Not enough news for France." |
| "You've reached the end. 3 items met today's bar." | "That's all for now — check back later!" |
| "1,247 articles reviewed, 5 kept." | "We filtered out 1,242 low-quality articles." |
| Complete, declarative sentences. States a fact plainly. | Exclamation marks, emoji, urgency language, apology language. |
| "Reported by *Le Monde*, *Reuters*, and 3 others." | "Sources: [icon][icon][icon]" |

The voice never apologizes for showing fewer than 5 items, never encourages a return visit, and never frames the Discarded Volume ratio as a failure — a high discard count is the filter working, not the filter underperforming. The same register binds the generated item headline: it states what happened, never teases what the reader will find by reading on. No urgency, no "breaking", no question marks — a headline written to earn a click would contradict everything else the page says about itself.

## Component Patterns

Behavioral. Visual specs live in `DESIGN.md.Components`.

| Component | Use | Behavioral rules |
|---|---|---|
| Mad-libs word (Zone) | Title sentence | Click/tap cycles World → 6 Continents → 8 Countries → World (FR-3). Keyboard: `Enter`/`Space` on focus advances one step, matching click; no separate multi-select control. Announces new value via `aria-live` on change (Story 4.8). |
| Mad-libs word (Period) | Title sentence | Click/tap cycles day → week → month → day (FR-2). Same keyboard/announcement behavior as the Zone word. |
| Consensus chip | Per item, below Summary | Collapsed by default, showing "N independent sources · M countries." Click/tap or `Enter` on focus expands inline (never a modal) to list contributing Sources + their countries (FR-9); the listed count always equals the displayed number — this is a rendering guarantee, not just a data one. Expand/collapse is per-item, independent of every other item's state. |
| Attribution + outbound link | Per item, always visible | Outlet name as plain visible text, immediately followed by a solid-underlined link to the original Article (FR-14) — present on initial render, never behind hover, a menu, or the Consensus chip's expansion. |
| Output Language control | Header, top-right | Three text options (the three supported languages); current selection visually distinct (`primary` color). Selecting one re-renders the whole page in that language and updates the URL (FR-12). Browser `Accept-Language` decides the *first* visit's default only; an explicit choice is not overridden by browser language on a later visit within the same session `[ASSUMPTION: persistence mechanism -- see State Patterns]`. |
| Continent-fallback notice | Directly beneath the mad-libs sentence, only when active | Static text, never dismissible, never a toast/banner that can be missed or auto-dismissed (FR-16). Disappears only when the reader picks a Zone that doesn't need to fall back. |
| Discarded Volume line | Once, above the End Screen rule | Plain sentence with two numeral-styled counts ("1,247 ingested → 5 kept"), FR-8. Never repeated per item. |
| End Screen | After the last item, always | A hairline rule followed by a completion statement (FR-5). Absolutely nothing — no "you might also like," no related content, no infinite-scroll trigger, no advertisement — renders below it. This is the one component whose entire job is to *stop* the page. |

## State Patterns

| State | Surface | Treatment |
|---|---|---|
| Cold load (first visit, no JS yet) | Whole page | Full Briefing content present in the initial HTML response (FR-1, NFR-4) — item list, attribution, Consensus counts, End Screen all readable with zero client-side execution. Mad-libs words render as plain (non-interactive-looking, but still valid) text links to the equivalent static URL for the next value in their cycle — a no-JS reader can still change Zone/Period by following a link, just without the inline word-swap animation. |
| Zone/Period change (JS present) | Mad-libs sentence + item list | Click swaps the sentence text and the item list in place, no full navigation flash; the URL updates via history push so back/forward and direct linking both work (FR-2/FR-3's "URL reflects the selection"). Latency bound matches first load (NFR-1) because the target Briefing's JSON is already a static asset — no network round-trip beyond fetching that one file. |
| Zone/Period change (no JS) | Whole page | A normal link navigation to the equivalent static route; same content, full page load. |
| Fewer than 5 items | Item list | Exactly as many items as qualified render — 2, 3, or 4 — with no placeholder, skeleton, or "loading more" affordance filling the gap (FR-4). The End Screen's rule sits directly beneath the last real item, regardless of count. |
| Single dominating item | Item list | That one item's block takes whatever vertical space its content needs (headline + full Summary paragraph + Consensus chip + attribution) rather than being height-capped to "look like" a multi-item layout — `DESIGN.md`'s content-driven block height. |
| Continent fallback active | Beneath mad-libs sentence | Notice renders unconditionally whenever `served_zone != requested_zone` (per the pipeline's own `ZoneRanking.substituted` signal) — this is data-driven, not a client-side guess. |
| Language not yet chosen (first visit) | Whole page | Output Language defaults from `Accept-Language` header at build/serve time if the header names a supported language, else English (FR-12). No language-picker modal interrupts first paint — the assumption in the default is a courtesy, not a gate. |
| Language explicitly chosen | Whole page | Persisted for the session via the URL's language segment; a reader who bookmarks or shares a URL always gets that language back, regardless of the visiting browser's `Accept-Language` `[ASSUMPTION: no cookie/localStorage persistence in v1 -- the URL itself is the only persistence mechanism, consistent with AD-1's no-client-state-beyond-cache posture]`. |
| Stale/failed generation cycle | Whole page | The previously published Briefing set continues to serve, unmodified (FR-19, AD-7) — there is no reader-visible "stale data" warning in v1; freshness is only ever stated positively via the generation timestamp, never negatively via an error state, because a failed cycle is invisible by design at this layer. |

## Interaction Primitives

- Click/tap is the only primary interaction; there is no swipe, no long-press, no drag anywhere on this page.
- The mad-libs words are the *only* multi-value inline-cycling controls on the page — no other element uses this pattern, so a reader who learns it once (dotted underline = click to cycle) can apply it everywhere it appears.
- The Consensus chip's expand/collapse is the only disclosure pattern on the page — no accordions, no tabs, no dropdown menus elsewhere.
- **Banned:** infinite scroll or any "load more" trigger (Story 4.4 exists specifically to forbid this), autoplay of any kind, modal dialogs (the Consensus chip expands inline, never in an overlay), hover-only affordances for anything required by an AC (attribution, outbound links, and the fallback notice must all work with hover entirely absent, i.e. on touch).
- Focus order follows visual/reading order top to bottom: header controls → mad-libs words in sentence order (Zone, then Period, matching "the World, today" word order) → item list top to bottom (per item: neither the headline nor the Summary paragraph is a separate focus stop — the headline is a heading, navigable by heading shortcut but not by Tab — then the Consensus chip, then the attribution link) → Discarded Volume (not interactive) → End Screen (not interactive).

## Accessibility Floor

Behavioral. Visual contrast lives in `DESIGN.md`.

- WCAG 2.1 AA is the floor (NFR-4) — confirmed, not deferred: 4.5:1 minimum contrast for body text, 3:1 for the `numeral` Consensus figures at their minimum rendered size, visible focus ring (not `outline: none`) on every interactive element.
- The document outline is exactly one `<h1>` (the mad-libs sentence) followed by one `<h2>` per item (its headline), with no skipped levels and nothing below `<h2>`. This is the page's primary non-visual navigation: a screen-reader user moves item to item by heading rather than reading every Summary in sequence. An item with no headline renders no heading at all rather than an empty one.
- Every mad-libs word announces its role and current value to a screen reader (e.g. "Zone, World, button, cycles to Europe") — not just its visible text — since the word's function (a cycling control) is not obvious from static text alone (Story 4.8's explicit requirement).
- The Consensus chip's expand/collapse announces its expanded state change (`aria-expanded`) and the newly revealed source list is reachable in the same tab sequence, not skipped.
- Tap targets for both mad-libs words and the Output Language control meet a 44×44px minimum hit area even though their visible text may be smaller — padding, not visible size, satisfies this.
- The generation timestamp (FR-19) is present as real text content, not an icon-only tooltip — screen-reader-reachable without a hover-triggered disclosure `[ASSUMPTION: "Updated at HH:MM" phrasing, in the reader's chosen Output Language's local time convention]`.
- No content depends on color alone: the Continent-fallback notice is a full sentence (not just red text), and the active Output Language is both colored *and* marked current via text weight/an explicit "current" state, not color alone.

## Key Flows

### Flow 1 — First arrival (Amara, checking the news over morning coffee, phone in hand)

1. Amara taps a shared link to 5 News with no prior visit.
2. The page loads; her phone's language preference is French, one of the three supported languages, so the Briefing renders in French with no prompt.
3. She sees, in serif type: "Voici ce qui se passe dans **le Monde**, **aujourd'hui**" — and, below it, 4 items already rendered, each with a Summary, a source count, and a visible link to the original article.
4. She reads the top item's Summary, glances at "6 sources indépendantes · 5 pays" beneath it — enough for her to trust it's not one outlet's spin.
5. She scrolls past all 4 items.
6. **Climax:** a hairline rule and "Vous avez atteint la fin. 4 sujets ont atteint le seuil aujourd'hui." — she knows, without wondering, that there is nothing more below. She closes the tab satisfied, not scrolling further out of habit or doubt.

Failure: her phone's language isn't among the three supported → Briefing renders in English (the fallback), still with no interrupting prompt.

### Flow 2 — Following two places (Kwame, an expatriate following both his home country and his host country)

1. Kwame has bookmarked 5 News at its default World/day URL.
2. He taps the Zone word ("World") once — it cycles to "Africa" inline, the item list swaps to Africa's Briefing, the URL updates.
3. He doesn't see his specific country in one click, so he taps "Africa" again — it cycles onward through Continents before reaching Countries; realizing the cycle order, he keeps tapping until his country's Briefing shows.
4. His country's coverage is thin today — fewer than 2 Qualifying Clusters — so instead of an empty page, the Continent-fallback notice appears: "Affichage de l'Afrique — [Pays] n'a pas assez de couverture aujourd'hui," and Africa's Briefing renders beneath it.
5. **Climax:** he understands immediately *why* he's seeing Africa instead of his country — the substitution is stated, not silently swapped — so he doesn't mistake Africa's news for his country's, and doesn't lose trust in the product for "getting it wrong."
6. He repeats the same word-tap pattern to check his host country next, in under 10 seconds total.

Failure: none applicable — the fallback path is itself the designed behavior for thin coverage, not an error state.

### Flow 3 — Verifying a claim (Priya, a skeptical reader who doesn't take a Summary at face value)

1. Priya reads an item's Summary: a ceasefire claim she finds surprising.
2. Rather than accepting it, she looks at the Consensus chip: "7 independent sources · 5 countries."
3. She taps the chip. It expands inline, listing the contributing outlets and their countries — she recognizes two she trusts.
4. Satisfied the number isn't inflated or from a single wire service repeated, she taps the visible attribution link beneath the Summary.
5. **Climax:** the original article opens in a new context, in the outlet's own words — she has verified the claim herself in three taps, without leaving with the sense that 5 News asked her to just believe it.

Failure: if the expanded list ever showed a count not matching the displayed number, this flow's entire trust mechanism breaks — this is why the rendering guarantee in `Component Patterns` (`Consensus chip`) is stated as a hard rule, not a nice-to-have.

## Inspiration & Anti-patterns

- **Lifted from Associated Press wire displays and Ground News' "blindspot" framing:** stating the Consensus Score as an inspectable number, not a hidden ranking signal — the reader is shown the *evidence* for placement, not just the placement.
- **Lifted from static site generators' own "it's just files" philosophy (Jekyll, Hugo, and this project's own Astro choice):** the entire reading experience works with zero JavaScript, because the content was never dynamic to begin with — this is a design constraint made into a design *feature* (Story 4.1's NFR-4 requirement, elevated to a brand statement: "you can read this even offline, even with scripts blocked").
- **Rejected — infinite scroll / "load more" (nearly every modern news feed):** directly forbidden by FR-5/Story 4.4. An anxious reader's actual complaint about news apps is not wanting *more*, it's not knowing when they can stop — the End Screen is the entire answer to that complaint, and infinite scroll is its exact opposite.
- **Rejected — personalized/algorithmic ranking (every major news aggregator):** FR-6 mandates deterministic, non-AI ranking by Consensus Score alone. The product's differentiator is that two readers with the same Zone/Period/Language see *identical* content — there is no "for you" anywhere in this experience, and no UI element should ever imply otherwise (no "recommended for you," no per-user history).
- **Rejected — social proof chrome (share counts, "trending," reaction counts):** none of these numbers exist in this pipeline's data model, and none should be simulated. The only number this product shows is the Consensus Score, because it's the only number that means something rigorous.
