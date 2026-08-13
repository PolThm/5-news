---
name: Wire & Ledger
status: final
sources:
  - {planning_artifacts}/epics.md
  - {planning_artifacts}/architecture/architecture-5-news-2026-08-10/ARCHITECTURE-SPINE.md
updated: 2026-08-12
colors:
  surface: '#faf9f6'
  surface-dim: '#e2e0d9'
  surface-bright: '#ffffff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f4f2ee'
  surface-container: '#eeece5'
  surface-container-high: '#e7e4dc'
  surface-container-highest: '#dfdcd2'
  on-surface: '#1a1a18'
  on-surface-variant: '#4d4a42'
  inverse-surface: '#2a2925'
  inverse-on-surface: '#f4f2ee'
  outline: '#777265'
  outline-variant: '#cac5b8'
  surface-tint: '#1f4d3d'
  primary: '#1f4d3d'
  on-primary: '#ffffff'
  primary-container: '#dbe8e0'
  on-primary-container: '#0f2e22'
  inverse-primary: '#8fc2ac'
  secondary: '#8a3a2b'
  on-secondary: '#ffffff'
  secondary-container: '#f6dcd4'
  on-secondary-container: '#5c1d10'
  tertiary: '#3d4a63'
  on-tertiary: '#ffffff'
  tertiary-container: '#dde2ee'
  on-tertiary-container: '#1a2438'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dbe8e0'
  primary-fixed-dim: '#8fc2ac'
  on-primary-fixed: '#0a1f16'
  on-primary-fixed-variant: '#0f2e22'
  secondary-fixed: '#f6dcd4'
  secondary-fixed-dim: '#e3a794'
  on-secondary-fixed: '#3a0f06'
  on-secondary-fixed-variant: '#5c1d10'
  tertiary-fixed: '#dde2ee'
  tertiary-fixed-dim: '#a9b3c9'
  on-tertiary-fixed: '#0d1626'
  on-tertiary-fixed-variant: '#1a2438'
  background: '#faf9f6'
  on-background: '#1a1a18'
  surface-variant: '#e7e4dc'
typography:
  display-lg:
    fontFamily: 'Source Serif 4'
    fontSize: 40px
    fontWeight: '500'
    lineHeight: '1.2'
    letterSpacing: -0.01em
  display-lg-mobile:
    fontFamily: 'Source Serif 4'
    fontSize: 28px
    fontWeight: '500'
    lineHeight: '1.25'
  headline-md:
    fontFamily: 'Source Serif 4'
    fontSize: 24px
    fontWeight: '500'
    lineHeight: '1.3'
  headline-sm:
    fontFamily: 'Source Serif 4'
    fontSize: 19px
    fontWeight: '500'
    lineHeight: '1.35'
  body-lg:
    fontFamily: 'IBM Plex Sans'
    fontSize: 17px
    fontWeight: '400'
    lineHeight: '1.55'
  body-md:
    fontFamily: 'IBM Plex Sans'
    fontSize: 15px
    fontWeight: '400'
    lineHeight: '1.5'
  numeral:
    fontFamily: 'IBM Plex Mono'
    fontSize: 15px
    fontWeight: '500'
    lineHeight: '1.4'
    letterSpacing: 0
  label-caps:
    fontFamily: 'IBM Plex Sans'
    fontSize: 11px
    fontWeight: '600'
    lineHeight: '1.4'
    letterSpacing: 0.08em
  caption:
    fontFamily: 'IBM Plex Sans'
    fontSize: 13px
    fontWeight: '400'
    lineHeight: '1.45'
rounded:
  sm: 0.125rem
  DEFAULT: 0.1875rem
  md: 0.25rem
  lg: 0.375rem
  full: 9999px
spacing:
  unit: 8px
  gutter: 20px
  margin-mobile: 16px
  margin-desktop: 48px
  section-gap: 40px
components:
  item-headline:
    typography: '{typography.headline-md}'
    color: '{colors.on-surface}'
  mad-libs-word:
    style: underline-dotted
    weight: '600'
    color: '{colors.primary}'
  consensus-chip:
    style: monospace-numeral
    background: '{colors.surface-container}'
  end-screen-rule:
    style: full-width-hairline
    color: '{colors.outline-variant}'
---

# 5 News — Design Spine

## Brand & Style

5 News reads like a wire report a measurement produced, not a feed an algorithm curated. Every visual decision defers to one governing idea, already stated in the product's own architecture: ranking is a measurement, not an opinion. The page must look like it could be audited — numbers sit in the open, typography is restrained enough that a Consensus Score reads as data rather than decoration, and nothing on screen competes with the two facts a reader actually needs: what happened, and how many independent sources agree.

The register is **Editorial Restraint** with a **Ledger** accent: a serif face for the mad-libs sentence and every item's headline (the voice of reporting — each item carries a generated headline above its Summary, the two together forming its display copy, with the Summary still "a trailer, not a substitute" per its own domain definition), a plain grotesque for controls, metadata, and the Summary paragraph itself (the voice of the interface), and a monospaced numeral face reserved *only* for the Consensus Score and Discarded Volume — so a reader's eye learns, within one visit, that monospace numbers are the thing worth trusting most on the page. No photography, no illustration, no decorative color. The palette is paper-and-ink: warm off-white surface, near-black ink, one desaturated forest green as the single interactive accent (the mad-libs words, the active Zone/Period state), one muted brick red reserved for a single meaning only — "this Zone fell back to its Continent" (FR-16) — so a reader learns the color itself signals substitution, never decoration.

## Colors

- **Surface (`#faf9f6`)** is the base — warm, non-clinical off-white, closer to newsprint than to a screen. `surface-container` tiers structure item cards and the Discarded Volume footer without borders.
- **On-surface (`#1a1a18`)** is near-black ink, used for all reading text — never pure black, which reads as screen-glare rather than print.
- **Primary (`#1f4d3d`, a desaturated forest green)** is the *only* interactive color: the mad-libs words (Zone, Period), their hover/focus state, the active Output Language, and link underlines on outbound attribution. If it's green, it's clickable. If nothing else on the page is colored, a reader still knows where to tap.
- **Secondary (`#8a3a2b`, a muted brick red)** is reserved for exactly one meaning: the Continent-fallback notice (FR-16, "France's Briefing is too thin — showing Europe instead"). It must never appear for any other purpose, including errors — a reader who has learned "red means substitution" must never have that association contradicted.
- **Tertiary (`#3d4a63`, a muted slate blue)** is reserved for the Consensus Score's expanded source list (FR-9) — a calm, neutral accent distinguishing "inspectable detail" from both the primary interaction color and the fallback-warning color.
- Dark mode: invert surface/on-surface roles; keep primary, secondary, tertiary hues but shift toward their `-fixed-dim` variants for sufficient contrast on a dark ground. Dark mode is a system-preference follow, not a manual toggle in v1 — no separate control competes with the two mad-libs words for the header's attention.

## Typography

- **Source Serif 4** carries the mad-libs sentence and every item's headline — the register of a printed dispatch. Set at `display-lg`/`display-lg-mobile` for the sentence itself (the page's single largest visual element, per FR-1/FR-2/FR-3's framing of the sentence as the primary control), and `headline-md` for the item headline. At 24px the headline stays below the sentence's 28px mobile size, so the sentence remains the most visually dominant element at every viewport (see Do's and Don'ts). The Summary paragraph sits beneath its headline in the grotesque at `body-lg`, not the serif: two stacked serif blocks read as one run-on paragraph, and the face change is what makes the headline scannable.

  The headline is what makes a five-item list scannable — a reader decides which items to read from the headlines, then reads the Summaries of the ones they chose. This is the one place three text elements share an item (headline, Summary, Consensus chip); the ordering above is what keeps that from competing with the two facts the page exists to deliver (what happened, and how many independent sources agree): the headline answers "what happened" faster than the Summary can, and the chip stays typographically distinct from both.
- **IBM Plex Sans** carries every other UI element: body copy (Summaries), labels, the language selector, the End Screen statement, attribution lines. Chosen for a grotesque that stays legible at small sizes without italics or condensed weights that would hurt the accessibility floor (NFR-4).
- **IBM Plex Mono**, at the `numeral` token, is reserved *exclusively* for the Consensus Score ("**5** independent sources · **4** countries") and the Discarded Volume line ("**1,247** ingested → **5** kept"). This is the single typographic signal that a number on this page is a measurement result, not prose — never use the numeral face for a page number, a date, or any other digit that isn't a ranking output.
- No italics anywhere except within a Summary's own prose (never for UI chrome) — italics in a serif headline face read as a stylistic flourish this product's register does not want.

## Layout & Spacing

A **single-column editorial stack**, never a multi-column grid, at every viewport — Story 4.4's "no infinite scroll, no filler" requirement is easier to honor when there is exactly one reading path top to bottom. Desktop gains generous side margins (`margin-desktop`, capped content width around 680px — a printed-column width, not a dashboard width) rather than additional columns; the page never asks a reader to choose where to look next.

`section-gap` (40px) separates the mad-libs sentence from the item list, and the item list from the Discarded Volume + End Screen block. Within the item list, each item is a self-contained block with generous internal padding — Story 4.4's "single dominating item fills the screen" case means an item block's height is content-driven, never fixed or cropped. Mobile margins (`margin-mobile`, 16px) keep text off the viewport edge without the wide "framed" gutters a lifestyle-editorial site would use — this is closer to a newspaper column than a magazine spread.

## Elevation & Depth

Depth is almost entirely **tonal**, not shadow-based — this is a flat, paper-like surface, and a heavy drop shadow would read as "app," undermining the wire-report register. Item cards sit on `surface-container-low` against the page's `surface` base, distinguished by a barely-perceptible tone shift, not a border or shadow. The single exception: the Output Language selector and the mad-libs words themselves may show a 1px `outline-variant` underline or box on focus/hover — an affordance, not decoration — to satisfy the keyboard-navigation requirement (NFR-4/Story 4.8) without adding visual weight anywhere else.

## Shapes

**Sharp-to-barely-rounded (`rounded.DEFAULT` = 0.1875rem)** — this is not a soft consumer app; corners are functionally square with just enough softening to avoid a harsh, technical edge. The Consensus Score chip and any tag-like element use `rounded.md`; nothing on the page uses `rounded.full` except a focus ring.

## Components

- **Mad-libs word** (`components.mad-libs-word`): the two clickable words (Zone, Period) inside the title sentence render in `primary` with a dotted underline (not solid — a dotted underline signals "this text behaves differently" at a glance, distinct from a normal hyperlink's solid underline used for outbound attribution). On click, the word cycles to its next value; the whole sentence re-renders inline, no page reload flash beyond what static navigation requires.
- **Item headline** (`components.item-headline`): the generated headline opening each item, set in Source Serif 4 at `headline-md`. Renders as a real `<h2>` — the page's only heading level below the mad-libs `<h1>` — so the item list is navigable by heading for screen-reader users. Absent entirely rather than empty when an item has no headline (a Briefing published before the field existed, or a Cluster whose generation degraded): an empty heading announces nothing and is an accessibility defect in its own right.

- **Consensus chip** (`components.consensus-chip`): the "N independent sources · M countries" line, set in the `numeral` typography token on a `surface-container` background — visually distinct from the Summary prose above it, so it reads as a data readout appended to the item, not a continuation of the sentence.
- **End Screen rule** (`components.end-screen-rule`): a full-width hairline in `outline-variant`, followed by the completion statement (FR-5) in `label-caps` — visually final, the one place on the page that explicitly says "stop scrolling, there is nothing further."
- **Attribution link**: a solid-underlined `on-surface-variant` text link with the outlet name visible as plain text before it (never a bare "Source" label or icon-only link) — FR-14 requires this be present without interaction, so it is never hidden behind a hover state or a "read more" disclosure.
- **Output Language control**: a small `label-caps` text control (e.g. "FR · EN · ES", active one in `primary`) sitting top-right of the page header, outside the mad-libs sentence `[ASSUMPTION: exact placement — the PRD only requires it sit outside the sentence; top-right chosen as the least visually competitive position with the sentence itself, and the conventional reading-language-switcher position]`.
- **Continent-fallback notice**: a single `secondary`-colored inline sentence directly beneath the mad-libs title ("Showing Europe — France doesn't have enough coverage today"), never a dismissible banner or toast — FR-16 requires the substitution be stated, and a banner a reader could dismiss and forget defeats that.

## Do's and Don'ts

- **Do** treat every number that comes from the ranking (Consensus Score, Discarded Volume, item count) as content worth its own typographic treatment.
- **Do** keep the mad-libs sentence as the single largest, most visually dominant element on the page at every viewport. The item headline sits one step below it in the type scale (`headline-md`, 24px, against the sentence's 28px mobile floor) — never at or above it.
- **Don't** let a headline become a hook. It states what happened, in the same plain and finite register as everything else the product writes: no urgency, no teasers, no "breaking", no question marks, no verbless fragments. A headline that would work on a wire desk is right; one written to make someone click is not, and would undo the register the rest of the page maintains.
- **Don't** introduce a second accent color for anything other than the Continent-fallback notice — color scarcity is what makes the fallback notice legible as a distinct signal.
- **Don't** add imagery, avatars, or per-outlet logos next to attribution — this is a text-and-number product; a logo grid would visually imply outlet ranking or endorsement the product does not make.
- **Don't** animate the mad-libs word cycle beyond an instant content swap — no carousel-style slide transition, which would suggest "more options exist below/beside" when the click already fully expresses the available choices.
