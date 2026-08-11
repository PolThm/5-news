---
baseline_commit: b3cf82b827c95923c0e2695ab14eeff0b43238e0
---

# Story 1.1: Repository and pipeline skeleton

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As the developer,
I want a repository whose structure enforces the pipeline/site separation from the first commit,
so that the two halves cannot accidentally couple as the code grows.

## Acceptance Criteria

1. **Directory skeleton exists.** `pipeline/domain/`, `pipeline/adapters/`, `pipeline/stages/`, `pipeline/config/`, `data/briefings/`, `data/intermediate/`, and `site/` are present in the repository.

2. **Data directories have the correct git treatment.** `data/intermediate/` is gitignored except `cycle.json`; `data/briefings/` is committed. Both exist in a fresh clone (use `.gitkeep`). `data/briefings/` stays empty — do **not** pre-create the 135-combination `<lang>/<zone>/<period>` tree; the publish stage creates paths as it writes them. **Proof required:** paste the `git check-ignore` verification from Dev Notes into Completion Notes.

3. **Configuration is data, not code.** `pipeline/config/` declares the 15 Zones, 3 Periods, and 3 Output Languages as declarative data (values listed in Dev Notes). Adding a Zone is a config edit with no code change.

4. **CI fails on a cross-boundary import.** A CI check fails when any module under `site/` imports from `pipeline/`, or any module under `pipeline/` imports from `site/`. The check must actually fail on a deliberately introduced violation — prove it.

5. **A stage runs alone.** A stage is invocable from the command line against an input path, with no other stage present. Story 1.1 ships one placeholder stage that reads an input path and writes an output path, demonstrating the contract. **Proof required:** paste the invocation command and its output into Completion Notes.

6. **The toolchain is pinned and reproducible.** Python and Node versions are pinned; `uv.lock` is committed; `uv sync` and the site's install both succeed from a clean clone. **Proof required:** paste both commands and their exit codes into Completion Notes, run from a genuinely fresh clone — not the working directory.

## Tasks / Subtasks

- [ ] **Task 1: Directory skeleton and git treatment** (AC: 1, 2)
  - [ ] Create the directory tree exactly as specified in Dev Notes → Project Structure
  - [ ] Write `.gitignore` using the **exact three-line pattern** in Dev Notes → The cycle.json exception. Do not simplify it — the obvious two-line version silently fails. Add standard Python/Node ignores alongside.
  - [ ] Add `.gitkeep` to `data/intermediate/` and `data/briefings/` so both survive a fresh clone
  - [ ] Run the `git check-ignore` verification block from Dev Notes; all three lines must print `ok`
  - [ ] Verify: `git clone` into a temp dir produces both directories

- [ ] **Task 2: Python project setup** (AC: 6)
  - [ ] `pyproject.toml` with PEP 621 `[project]` metadata, `requires-python = ">=3.11"`
  - [ ] Dev dependencies in PEP 735 `[dependency-groups]`, not extras and not uv-specific tables
  - [ ] Configure `ruff` for both lint and format (no Black, no isort — ruff covers both)
  - [ ] Run `uv sync`, commit `uv.lock`
  - [ ] Pin the `uv` version used in CI

- [ ] **Task 3: Configuration module** (AC: 3)
  - [ ] `pipeline/config/` exposes `ZONES`, `PERIODS`, `OUTPUT_LANGUAGES` as **Python module-level constants** (not TOML/YAML). Rationale: they are read by every stage, need no runtime reload, and typed constants give the domain types something to validate against. Story 2.4's tunable thresholds go in the same module.
  - [ ] Use the exact slugs in Dev Notes → Configuration values. Do not invent slugs.
  - [ ] Each Zone records its kind (`world` | `continent` | `country`) and, for countries, its containing continent — FR-16's fallback needs this in Story 2.5
  - [ ] Verify: the 135-combination matrix (15 × 3 × 3) is derivable from config alone

- [ ] **Task 4: Domain types** (AC: 3)
  - [ ] `pipeline/domain/` defines the Glossary types with the exact names in Dev Notes → Domain vocabulary
  - [ ] `pipeline/domain/` imports nothing from `adapters/`, `stages/`, or `config/` — it is the leaf
  - [ ] Types only; no behavior, no I/O

- [ ] **Task 5: Stage contract and placeholder stage** (AC: 5)
  - [ ] Define the stage contract: read input path → write output path under `data/intermediate/<stage>/<cycle-id>/`
  - [ ] **Entrypoint convention — every later stage inherits this:** `python -m pipeline.stages.<name> --input <path> --cycle-id <id>`, with `--cycle-id` defaulting to a UTC timestamp derived at invocation. Fix the flag names now; Story 1.2 onward will copy them.
  - [ ] Ship one runnable placeholder stage proving the contract end to end
  - [ ] Verify: invoke it from the command line with an input path, alone, and it produces output

- [ ] **Task 6: Boundary check in CI** (AC: 4)
  - [ ] Write the grep-based boundary check (see Dev Notes → Boundary check for the exact violation patterns)
  - [ ] Wire it into a GitHub Actions workflow using the v7 action line (see Dev Notes → GitHub Actions)
  - [ ] **Prove it fails:** add a deliberate violation, watch CI go red, remove it. Do not mark this AC done on an untested check.

- [ ] **Task 7: Site scaffold** (AC: 1, 6)
  - [ ] Scaffold Astro 7.2.x under `site/` with `src/pages/`, `src/islands/`, `public/`
  - [ ] Pin Node ≥ 22.12.0 (Astro 7 requires it)
  - [ ] The scaffold must build. It renders nothing real yet — that is Epic 4.

## Dev Notes

### What this story is, and is not

This is scaffolding whose job is to make a specific class of mistake impossible later. The value is not the directories — it is that the pipeline/site boundary is mechanically enforced from commit one, before there is any code to couple.

**Do not build features.** No ingestion, no clustering, no page. The placeholder stage exists only to prove the stage contract runs; it must not become a real stage.

### Two languages is a decided fact, not a preference

The pipeline is **Python**; the site is **Astro/TypeScript**. They share no code.

- Clustering needs `sklearn.cluster.HDBSCAN` (scikit-learn 1.9.0, requires Python ≥ 3.11) — HDBSCAN is a first-class vendored estimator there, plus the surrounding numpy/scipy stack.
- JS HDBSCAN ports (`hdbscan-ts`, `clusternova`, `hdbscanjs`) are single-maintainer projects with no meaningful adoption. Not substitutes.
- Astro 7.2.0 requires Node ≥ 22.12.0 regardless, so both toolchains are needed anyway.

Do not attempt to unify the languages.

### Project structure

```text
5-news/
  pipeline/
    domain/        # Glossary types. Imports nothing. The leaf.
    adapters/      # one module per external service (gdelt, rss, cohere, claude)
    stages/        # collect, dedupe, cluster, rank, summarize, publish
    config/        # zones, periods, languages, thresholds — data, not code
  data/
    intermediate/  # per-cycle stage output, gitignored except cycle.json
    briefings/     # published Briefings, committed
  site/
    src/pages/     # [lang]/[zone]/[period].astro
    src/islands/   # the mad-libs selector — the only client JS
    public/        # manifest.json, sw.js
  .github/workflows/
```

Dependency direction — a violation of any row is a defect:

| Layer | May depend on |
| --- | --- |
| `pipeline/domain/` | nothing |
| `pipeline/adapters/` | `pipeline/domain/` |
| `pipeline/stages/` | `pipeline/domain/`, `pipeline/config/`, its own inputs |
| `site/` | `data/briefings/` only |

`[NOTE]` The spine's own table omits `pipeline/config/` from what stages may depend on, while its conventions require a config module "read by every stage". The table above resolves that in favour of the convention — stages read config. This is a deliberate reading of the spine, not an oversight; flag it if you disagree rather than silently following the narrower version.

### The cycle.json exception — read this before writing .gitignore

The architecture says two things that appear to conflict, and both are load-bearing:

- `data/intermediate/` is gitignored (this story, AC 2) — it holds bulky per-cycle stage output that must not enter git history.
- Cross-phase cycle state lives at `data/intermediate/<cycle-id>/cycle.json` and **must be committed**, because a later scheduled run reads it to resume a pending batch (AD-11, delivered in Story 3.4).

**Resolution:** use exactly this pattern. It is tested and works:

```gitignore
data/intermediate/**
!data/intermediate/**/
!data/intermediate/**/cycle.json
```

All three lines are required, in this order. The middle line is the one that is easy to omit and fatal to omit: **git never descends into an excluded directory**, so a negation for a file inside it can never match. Re-including the directories (`!data/intermediate/**/`) is what lets git reach the file-level negation.

The obvious-looking two-line version does **not** work:

```gitignore
data/intermediate/*          # ← WRONG
!data/intermediate/**/cycle.json
```

Under it, `git check-ignore` reports `cycle.json` as ignored, because `data/intermediate/cycle-xxx/` was excluded wholesale and git stopped there. The failure is silent — nothing errors, the file simply never gets committed, and Story 3.4's resume logic breaks weeks later with no obvious cause.

**Verify before marking AC 2 done:**

```sh
mkdir -p data/intermediate/test-cycle/collect
echo '{}' > data/intermediate/test-cycle/cycle.json
echo '{}' > data/intermediate/test-cycle/articles.jsonl
echo '{}' > data/intermediate/test-cycle/collect/out.jsonl
git check-ignore -q data/intermediate/test-cycle/cycle.json && echo "BROKEN" || echo "ok"
git check-ignore -q data/intermediate/test-cycle/articles.jsonl && echo "ok" || echo "BROKEN"
git check-ignore -q data/intermediate/test-cycle/collect/out.jsonl && echo "ok" || echo "BROKEN"
rm -rf data/intermediate/test-cycle
```

Three `ok` lines, no `BROKEN`.

### Configuration values

Use these exact slugs. They appear in URLs (FR-2, FR-3), in published file paths, and in the 135-Briefing matrix. Inventing different ones breaks the site's routing later.

**Zones — 15 total:**

| Slug | Kind | Continent |
| --- | --- | --- |
| `world` | world | — |
| `europe` | continent | — |
| `north-america` | continent | — |
| `south-america` | continent | — |
| `asia` | continent | — |
| `africa` | continent | — |
| `oceania` | continent | — |
| `france` | country | `europe` |
| `united-kingdom` | country | `europe` |
| `germany` | country | `europe` |
| `united-states` | country | `north-america` |
| `japan` | country | `asia` |
| `china` | country | `asia` |
| `india` | country | `asia` |
| `brazil` | country | `south-america` |

The `continent` column is not decoration — Story 2.5 (FR-16) serves a country's containing continent when the country has too few Qualifying Clusters. Model it now.

**Periods:** `day`, `week`, `month`
**Output Languages:** `fr`, `en`, `es` (two-letter codes)

A Briefing is addressed by the triple in this order: language, zone, period. Published path: `data/briefings/<lang>/<zone>/<period>.json`.

### Domain vocabulary — binding

These names come from the PRD Glossary and are binding in type names, file names, and JSON keys. **No synonyms anywhere.** Using `Story`, `Item`, `NewsItem`, or `Topic` where the Glossary says `Cluster` is a defect.

`Article`, `Source`, `IndependentSource`, `WireCopy`, `SyndicationDetection`, `Event`, `Cluster`, `QualifyingCluster`, `ConsensusScore`, `Zone`, `Period`, `Briefing`, `Summary`, `OutputLanguage`, `DiscardedVolume`

Definitions you need to model them correctly:

- **Event** — a real-world occurrence that multiple Articles describe. A **Cluster** is the set of Articles grouped as describing one Event; one Cluster represents one Event. Model `Event` explicitly: Story 2.7 (FR-18) turns on recognizing the same Event across ingest days, and without a name for it the agent will conflate Event with Cluster.
- **IndependentSource** — a Source whose Article is not a republication of another Source's dispatch. Only these count toward the ConsensusScore.
- **QualifyingCluster** — a Cluster with at least 2 IndependentSources from at least 2 distinct countries. Only these are eligible for a Briefing.
- **ConsensusScore** — the pair (IndependentSource count, distinct-country count).
- **DiscardedVolume** — Articles ingested for a Briefing minus those in its published Clusters.

`End Screen` is the sixteenth Glossary term and is deliberately out of scope here — it is a page concept delivered in Epic 4.

Story 1.1 defines these as types. It does not implement behavior on them.

### Stage contract

Every stage reads its input from disk and writes its output to disk, and is invocable alone. This is what makes the Build Order's inspection window possible — the author must be able to run `collect` and `dedupe` for days and look at the output before anything downstream exists.

- Input: a path
- Output: `data/intermediate/<stage>/<cycle-id>/`, JSON Lines, one record per line
- Stages never hand data to each other in memory or through a shared mutable object
- Cycle identifier derives from the run's UTC start instant

**Two path shapes share `data/intermediate/`, in opposite segment order:**

| What | Path |
| --- | --- |
| Stage output | `data/intermediate/<stage>/<cycle-id>/` |
| Cycle state | `data/intermediate/<cycle-id>/cycle.json` |

So `data/intermediate/collect/` and `data/intermediate/2026-08-11T00-00-00Z/` are siblings. This is what the spine specifies and both are load-bearing, but it means **a cycle identifier that ever collides with a stage name would corrupt both trees**.

Prevent it structurally: derive the cycle identifier from a UTC timestamp in a format that cannot collide with the six reserved stage names (`collect`, `dedupe`, `cluster`, `rank`, `summarize`, `publish`). A timestamp like `2026-08-11T00-00-00Z` satisfies this by construction — it starts with a digit. Assert it in the config module rather than relying on the format never changing.

The gitignore pattern in this story handles both depths correctly.

**File extension: `.jsonl`.** (`.ndjson` is the same format; `.jsonl` matches the Python/data-science convention and the Anthropic Batch API.) One JSON object per line, no embedded raw newlines, trailing newline at EOF, stable key ordering — these files are committed, and stable ordering keeps diffs readable during the inspection window.

### Boundary check

The constraint is cross-language, so a Python import graph analyzer (`import-linter`) is the wrong tool — `site/` is TypeScript and cannot import Python. A grep-based CI step covers the real violation modes with zero dependencies and no config drift.

**Do not check for `import site` in Python.** `site` is a Python **standard library module**. Such a rule produces false positives on legitimate code and catches nothing real: `site/` contains no Python and no `__init__.py`, so `import site` from a pipeline module resolves to stdlib and can never reach the site directory. A check built on it enforces nothing while looking like it does.

The violation modes that can actually occur:

| # | Violation | Detect by |
| --- | --- | --- |
| 1 | Python in `pipeline/` reads site files by path | `pipeline/**/*.py` matching a string literal containing `site/` (e.g. `open("site/...")`, `Path("site")`) |
| 2 | TS/Astro in `site/` imports across the boundary | `site/**/*.{ts,js,astro}` matching an import whose path traverses into `pipeline` (e.g. `from '../../pipeline/...'`) |
| 3 | TS/Astro in `site/` reads pipeline files by path | `site/**/*.{ts,js,astro}` matching a string literal containing `pipeline/` |

Rule 3 needs one legitimate exception: the site *must* read `data/briefings/`. That path contains no `pipeline/` substring, so no allowance is needed — but if you introduce a shared constant naming the data directory, keep `pipeline` out of its value.

**Proving AC 4.** Introduce one violation of *each* rule in turn, confirm CI fails on each, then remove them. A check that catches only rule 2 passes a naive test while leaving both Python-side modes open.

Keep the whole thing to roughly 20 lines and readable in six months. If `pipeline/` later grows internal layers worth enforcing (collect → dedupe → cluster → rank → summarize is a natural layered contract), `import-linter` 2.13 is the tool to add then — not now.

### Python tooling

- **`uv` 0.12.3** — the current default for dependency management and virtualenvs. Still 0.x with occasional breaking changes between minors: **pin the version in CI**, do not float it.
- **`ruff` 0.16.2** — covers lint *and* format. `ruff format` replaces Black; ruff's import sorting replaces isort. Do not add either.
- **`pyproject.toml`** with PEP 621 `[project]` metadata.
- **PEP 735 `[dependency-groups]`** for dev/test dependencies — the standard, tool-agnostic location. Use it rather than extras or uv-specific tables.
- Commit `uv.lock`.

`[NOTE]` Astral (uv, ruff) was reportedly acquired by OpenAI in March 2026. Both remain open source with no operational change reported. This is from secondary sources, not verified against a primary announcement — noted for awareness, not as a reason to choose differently.

### GitHub Actions

**Use the v7 action line.** Most tutorials still show v6; v7 landed across the board in July 2026.

| Action | Version |
| --- | --- |
| `actions/checkout` | `v7.0.1` |
| `actions/setup-python` | `v7.0.0` |
| `actions/setup-node` | `v7.0.0` |

**Deadline that matters:** Node 20 is removed from GitHub-hosted runners on **2026-09-16**. Actions pinned below v7 break then. Writing v7 today avoids the migration entirely.

Limits worth knowing for later stories: max job duration 6 hours; free tier 2,000 min/month on private repos, unlimited on public. Scheduled workflows are best-effort (can be delayed at peak) and are **auto-disabled after 60 days of repository inactivity** — relevant to a daily pipeline; Story 1.5 should account for it.

### Testing

No test framework is mandated by the architecture. For this story, "tested" means demonstrated:

- AC 2: clone into a temp directory, confirm both data directories exist and the `cycle.json` negation behaves
- AC 4: introduce a deliberate cross-boundary import, confirm CI fails, remove it
- AC 5: invoke the placeholder stage alone from the command line, confirm it writes output
- AC 6: from a clean clone, `uv sync` and the site install both succeed

Establish whatever test scaffolding you prefer here — later stories will build on it. Keep it proportionate: this is a solo project, not an enterprise codebase.

### Project Structure Notes

The structure above comes from the architecture spine's Structural Seed and is not negotiable at this altitude — later stories reference these paths directly.

One variance to be aware of: the spine describes `data/intermediate/` as gitignored *and* describes `cycle.json` inside it as committed. This story resolves that with the three-line negation pattern above, which has been verified against real `git check-ignore` behavior. Use it as written; do not simplify it.

### Previous story intelligence

None. This is the first story of the first epic. The repository contains one commit (`Init repo`) and a README; there is no existing code, no established conventions, and no prior story learnings. Every convention this story establishes becomes the precedent later stories inherit — choose deliberately.

### Git intelligence

Not applicable. Single commit, no code history to learn patterns from.

### References

- Story and acceptance criteria: [Source: _bmad-output/planning-artifacts/epics.md#Story-1.1]
- Epic 1 goal and downstream stories: [Source: _bmad-output/planning-artifacts/epics.md#Epic-1]
- Directory seed, dependency table, conventions: [Source: _bmad-output/planning-artifacts/architecture/architecture-5-news-2026-08-10/ARCHITECTURE-SPINE.md#Structural-Seed, #Consistency-Conventions]
- AD-2 (pipeline/site separation), AD-3 (stage independence), AD-11 (cycle state), AD-13 (adapter boundary): [Source: ARCHITECTURE-SPINE.md#Invariants-Rules]
- Zone list: [Source: _bmad-output/planning-artifacts/prds/prd-5-news-2026-08-10/prd.md#FR-3]
- Glossary terms: [Source: prd.md#3-Glossary]
- Build Order and the inspection window: [Source: prd.md#10-Build-Order]
- Tooling versions verified via web research 2026-08-11 (uv 0.12.3, ruff 0.16.2, scikit-learn 1.9.0, Astro 7.2.0, GitHub Actions v7 line, Node 20 runner removal 2026-09-16)

## Dev Agent Record

### Agent Model Used

_To be filled by the dev agent._

### Debug Log References

### Completion Notes List

### File List
