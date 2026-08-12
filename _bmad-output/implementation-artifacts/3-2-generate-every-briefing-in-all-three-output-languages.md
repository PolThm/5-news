---
baseline_commit: 7e3ed6f
---

# Story 3.2: Generate every Briefing in all three Output Languages

Status: done

## Story

As a reader,
I want the Japanese press's account in my own language,
So that I can read what a country's press converged on without reading that language.

## Scope, decided explicitly before this story was written

**This story does not build the 15 Zone × 3 Period assembly loop.** Story 3.1 delivered `run_summarize`/`summarize_clusters` as standalone, tested mechanisms — no orchestration exists yet that calls `rank_for_zone` (Story 2.5) for a real Zone/Period combination and feeds its output to `run_summarize`. Building that loop now, before Story 3.5 (publish) exists to consume its output and decide where 135 files actually land on disk, would mean guessing at the loop's shape twice. Per the user's explicit decision when this story was scoped: **Story 3.2 proves summarize produces grounded, correctly-attributed text in all three Output Languages for a given set of Clusters — it does not assemble or count all 135 Briefings.** The literal "135 Briefings exist" language in this story's AC2 (below) is the Build Order's target state for the whole pipeline once publish (3.5) exists, not a deliverable of this story alone; this story is verified by testing that `summarize_clusters`/`run_summarize` behave correctly per-language, not by running the full matrix end-to-end.

## A real gap this story closes: the adapter currently sends a bare language code into the prompt, not a language name

Confirmed by reading Story 3.1's shipped code (`pipeline/adapters/claude.py`): `_prompt_for` interpolates `language` verbatim into `"Write one short paragraph, in {language}, summarizing..."`. Every call site so far has passed a bare two-letter `OutputLanguage` value (`"fr"`, `"en"`, `"es"`) — the prompt Claude actually receives today literally says "Write one short paragraph, in fr, summarizing...". A two-letter ISO code is not a natural-language instruction; this story fixes that by mapping each `OutputLanguage` to the language name Claude should write in ("French", "English", "Spanish") before it reaches the prompt. This is not a new architecture decision — `pipeline.domain.OutputLanguage` already exists with exactly the three values this mapping needs (Story 1.1's domain design); this story is simply the first real consumer that needs the enum's values turned into prose.

## Acceptance Criteria

1. **Summarization runs in French, English, and Spanish, regardless of the Articles' own language.** Given a Cluster composed entirely of Japanese-language Articles (title/source/source_country all reflecting Japanese sources), when `summarize_clusters` is called once per `OutputLanguage`, each call produces a prompt instructing Claude to write in that call's language by name — not by ISO code — and the same Cluster's member data (titles, sources) is passed unchanged across all three calls, so the underlying facts available to ground the Summary do not vary by language, only the language of the resulting prose (FR-11).

2. **The mechanism that produces the full 135-Briefing matrix (15 Zones × 3 Periods × 3 Output Languages) is proven correct at the unit it operates on — summarize per language — not assembled end-to-end in this story.** `run_summarize`'s existing per-call behavior (Story 3.1: input Clusters unchanged in count/order/fields, output adds only `summary`) is verified independently for each of the three `OutputLanguage` values, confirming nothing about the mechanism is FR/EN/ES-specific in a way that would silently break for one language and not the others. The literal 135-Briefing count is Story 3.5's (publish) responsibility once the assembly loop exists (FR-15) — not re-asserted here.

## Tasks / Subtasks

- [x] **Task 1: Map `OutputLanguage` to the language name Claude should write in** (AC1)
  - [x] Add a small, explicit mapping in `pipeline/adapters/claude.py` — `{OutputLanguage.FR: "French", OutputLanguage.EN: "English", OutputLanguage.ES: "Spanish"}` — not a general i18n library or a locale-name lookup; exactly the three values `OutputLanguage` has, deliberately small and explicit for the same reason `resolve_wire_agency`'s wire-service table is small and explicit (Story 2.3): a missing mapping should fail loudly (`KeyError`), not silently fall back to something plausible-but-wrong
  - [x] Change `summarize_clusters`'s and `_prompt_for`'s `language` parameter type from bare `str` to `OutputLanguage` — this also fixes a latent type gap: nothing before this story constrained callers to the three actually-supported values
  - [x] Update `_prompt_for` to interpolate the mapped language *name* ("French") into the instruction text, not the enum's raw value ("fr")
  - [x] Update `pipeline/stages/summarize.py`'s `run_summarize` (and its `SummarizeFn` type alias) to accept `language: OutputLanguage` instead of `str`, and to write its metadata's `"language"` field as the enum's string value (`language.value`, i.e. still `"fr"`/`"en"`/`"es"` on disk — the metadata field is a machine-readable identifier, not a prompt instruction, and every other stage's metadata already uses lowercase slugs for this kind of field; only the *prompt text* needed the human-readable name, not the on-disk record)

- [x] **Task 2: Confirm language does not affect what the model is given to ground a Summary in** (AC1)
  - [x] No production code change expected here (this is a verification task) — confirm via test, not by inspection, that a call to `_prompt_for` with the same Cluster and three different `OutputLanguage` values embeds the identical set of member titles/sources in all three prompts, and that only the language-name instruction and the no-fabrication/corroboration text differ
  - [x] Confirm a Cluster whose members are entirely non-Latin-script (Japanese titles, Japanese `source`/`source_country`) round-trips through `_prompt_for` unchanged in content (no transliteration, no filtering) for every target language — the model does the translation; this adapter must not attempt to preprocess or normalize non-Latin text

- [x] **Task 3: Tests**
  - [x] `tests/test_claude_adapter.py`: for each of the three `OutputLanguage` values, `_prompt_for` produces a prompt containing the correct language *name* ("French"/"English"/"Spanish"), never the bare code, and never one of the other two languages' names; a call with a value outside `OutputLanguage` (if reachable through any remaining `str`-typed call site) raises rather than silently producing a malformed prompt
  - [x] `tests/test_claude_adapter.py`: a Cluster with entirely Japanese-language members produces prompts (across all three `OutputLanguage` calls) that still contain the original Japanese titles verbatim — proving the adapter passes the source text through unchanged and lets the model translate, rather than attempting any language handling of its own
  - [x] `tests/test_summarize_stage.py`: `run_summarize` still passes every non-`summary` field through unchanged (Story 3.1's own AD-6 test, re-run — not rewritten — against all three `OutputLanguage` values, confirming the language change doesn't touch AD-6's pass-through guarantee) and each call's metadata records the correct `language.value`

## Dev Notes

### Why this is a small story

Story 3.1 already built the entire mechanism (`claude.py`, `summarize.py`) generically over a `language` parameter — this story's only real work is (a) making that parameter type-correct (`OutputLanguage`, not bare `str`) and (b) fixing the prompt to instruct in a language *name* rather than a bare code, which is a genuine correctness gap Story 3.1 shipped with (it was not caught by that story's own review because no test asserted on the literal prompt text's language-naming, only on the presence of member data and the no-fabrication instruction). Confirm this gap is real by reading `_prompt_for`'s current f-string before writing any test — do not assume; verify against the actual shipped code.

### What this story explicitly does not do

- **No assembly loop.** `cycle.py` still only calls `run_rank` flat, exactly as Story 3.1 left it — this story does not add a per-Zone or per-Period loop, and does not wire `run_summarize` into `cycle.py` at all. That remains Story 3.5's job (or whichever story first needs a real per-cycle orchestration of the 15×3×3 matrix).
- **No publish-side output.** `data/briefings/` does not exist yet as a concept in code; this story writes nothing there.
- **No translation quality verification.** Whether Claude's French/Spanish output is *good* is not testable without a live call and is out of scope for a unit-tested story; this story verifies the *mechanism* (correct language instruction, correct grounding data, Story 3.1's degrade/pass-through guarantees hold per-language), not translation fluency.

### Project Structure Notes

No new files. Files this story modifies:
- `pipeline/adapters/claude.py` (language-name mapping; `_prompt_for`/`summarize_clusters` typed on `OutputLanguage`)
- `pipeline/stages/summarize.py` (`run_summarize`/`SummarizeFn` typed on `OutputLanguage`; metadata writes `language.value`)
- `tests/test_claude_adapter.py` (new language-name and non-Latin-script tests)
- `tests/test_summarize_stage.py` (re-run AD-6 pass-through test across all three languages; metadata assertion updated for `language.value`)

### Previous Story Intelligence

- Story 3.1's single-layer review (Blind Hunter) found 6 real issues, all fixed — the prompt's language-naming gap found while drafting this story is a **new, separate** issue Blind Hunter did not flag, because no test in Story 3.1 asserted on the literal instruction text beyond checking for member data and the no-fabrication phrase. This is worth noting for whoever reviews this story: a prompt can pass every existing assertion and still contain a wrong instruction if nothing asserts on that specific piece of text.
- Story 3.1's `_prompt_for` and `summarize_clusters` are both currently typed `language: str`. Changing this to `OutputLanguage` is a breaking signature change for any existing caller — confirm there are no other call sites beyond the two files this story lists before making the change (a quick grep, following the same discipline Story 3.1's Task 0 used for `member_titles`).
- Single-layer adversarial review (Blind Hunter only) remains the process for this story, per the user's standing cost-reduction decision.

### References

- [Source: epics.md#Story 3.2] — acceptance criteria origin (verbatim AC text reproduced above)
- [Source: pipeline/adapters/claude.py#_prompt_for] — the exact line carrying the bare-code prompt gap this story fixes
- [Source: pipeline/domain/__init__.py#OutputLanguage] — the existing three-value enum this story's mapping is keyed on
- [Source: ARCHITECTURE-SPINE.md#Structural Seed] — confirms `publish` (not `summarize`) is where `data/briefings/` output lands, supporting this story's decision to defer the assembly loop
- [Source: _bmad-output/implementation-artifacts/3-1-summarize-selected-clusters-in-one-language.md] — the story this one extends; its Post-Review Fixes section for the single-layer review precedent

## Dev Agent Record

### Context Reference

_To be filled by dev-story._

### Debug Log

- Confirmed the prompt-language gap was real before writing any code: read `_prompt_for`'s shipped f-string directly and verified it interpolated the bare `OutputLanguage` value (e.g. `"fr"`) rather than a name — matching the story's own prediction exactly.
- Grepped for all call sites of `summarize_clusters`/`_prompt_for`/`run_summarize` before retyping their `language` parameter — confirmed only `pipeline/adapters/claude.py`, `pipeline/stages/summarize.py`, and their two test files reference these functions, matching the story's Dev Notes prediction. No other call sites needed updating.
- 14 existing test call sites passed `language="fr"` as a bare string; bulk-updated to `language=OutputLanguage.FR` (and `_prompt_for`'s positional calls, and `fake_summarize`'s callback signature) as part of the signature change, not left as a parallel untyped path.

### Completion Notes

Both tasks complete, TDD throughout. 243/243 tests passing (up from 240 at story start: +3 new tests for language-name correctness, grounding-data invariance, and non-Latin-script pass-through).

**Task 1:** Added `_LANGUAGE_NAMES: dict[OutputLanguage, str]` to `pipeline/adapters/claude.py` — small and explicit, same reasoning as `resolve_wire_agency`'s wire-service table (Story 2.3): a missing entry raises `KeyError` rather than silently degrading. `_prompt_for` and `summarize_clusters` are now typed `language: OutputLanguage`, not bare `str`; the prompt interpolates the mapped name ("French") instead of the raw code ("fr"). `pipeline/stages/summarize.py`'s `run_summarize`/`SummarizeFn` follow the same retyping — its on-disk path segment and metadata `"language"` field still write `language.value` (the lowercase slug every other stage's metadata already uses for this kind of field), since only the prompt *text* needed the human-readable name, never a machine-readable record. The CLI entry point (`main()`) now validates `--language` against `OutputLanguage`'s values via `argparse`'s `choices` and converts to the enum before calling `run_summarize`.

**Task 2 (verification, no production code):** Confirmed via test that the same Cluster's member data (titles, sources) appears identically in all three languages' prompts — only the language-name instruction and no-fabrication/corroboration text vary. Confirmed a Cluster with entirely Japanese-script members (`"停戦が宣言された"`) passes through `_prompt_for` byte-for-byte unchanged for every target language — this adapter does no transliteration or preprocessing; translation is the model's job.

**Not built in this story, by explicit design (confirmed with the user before story creation):** the 15 Zone × 3 Period assembly loop that would produce the literal 135-Briefing matrix — `cycle.py` still calls only the flat `run_rank`, with no per-Zone/Period orchestration. That remains deferred to Story 3.5 (publish), which is where `data/briefings/` output actually lands per the architecture spine's Structural Seed.

**Post-review fixes (single-layer adversarial pass — Blind Hunter only, per the standing cost-reduction decision):**

Blind Hunter returned 11 findings. Five were dismissed on triage as correct-but-out-of-scope or nitpicks not worth a code change: no test for `main()`'s invalid `--language` CLI path (argparse's own `choices` validation already handles it — a test would only be testing argparse); the non-Latin-script test exercising `_prompt_for` directly rather than the full `summarize_clusters` batch path (the batch layer doesn't touch title text either, so this adds no real coverage); the language-name substring-exclusivity assumption (correct observation, not a bug for the three real names); the token-budget nitpick (the "fr"→"French" length delta is trivial); and the "no-op" framing of the `language.value` comment change (addressed via a smaller comment edit, not a functional fix, since the underlying behavior genuinely doesn't change).

**Fixed (real gap): nothing enforced that `_LANGUAGE_NAMES` stayed in sync with `OutputLanguage`.** A future fourth language added to the enum without a matching entry in `_LANGUAGE_NAMES` would fail as a `KeyError` deep inside `_prompt_for`, at batch-submission time, mid-cycle — not at import time, and not caught by any existing test. Fixed by adding an import-time `assert set(_LANGUAGE_NAMES) == set(OutputLanguage)` in `claude.py`, so the mismatch surfaces immediately on load rather than during a real cycle.

**Fixed (real gap): the documented "raises loudly, never silently falls back" behavior for an unmapped language was asserted in a comment but never actually exercised by a test.** Added `test_an_unsupported_language_raises_rather_than_silently_falling_back`, calling `_prompt_for` with a real-but-unsupported ISO code (`"de"`) and asserting `KeyError`.

**Fixed (real overstatement, doc-only): the docstrings for `summarize_clusters` and `run_summarize` claimed that typing `language` on `OutputLanguage` (rather than bare `str`) meant "a caller can only ever request one of the three actually-supported languages."** This is not true at runtime: `OutputLanguage` is a `StrEnum`, so `OutputLanguage.FR == "fr"` holds and a bare `"fr"` string works identically everywhere this parameter is used — confirmed directly (`mapping["fr"]` succeeds against an `OutputLanguage`-keyed dict). The type annotation is a static-analysis and self-documentation aid only; the only actual runtime enforcement is `_prompt_for`'s `_LANGUAGE_NAMES` lookup. Corrected both docstrings to state this precisely rather than overselling what the retyping buys.

**Fixed (real style defect, zero behavior change): `_prompt_for` was imported locally inside 6 individual test functions across two files instead of once at module scope**, inconsistent with every other import in both files. Consolidated to a single top-of-file import in each.

**Deferred, not fixed (correct observation, but a design question beyond this story's scope):** `pipeline/config/__init__.py`'s `OUTPUT_LANGUAGES` tuple and `claude.py`'s `_LANGUAGE_NAMES` dict are now two independently-maintained enumerations of "all supported languages," in two files, with nothing asserting they agree beyond both being keyed off the same `OutputLanguage` enum (which the new sync-assertion fix does verify, transitively, for `_LANGUAGE_NAMES`). A shared derivation (e.g. deriving one from the other, or a single source-of-truth mapping) would be a reasonable follow-up but is not a bug today — both currently agree, and `OUTPUT_LANGUAGES` is itself just `tuple(OutputLanguage)` in the natural case. Noted for whoever next touches either file.

After fixes: 244 tests passing (up from 243 immediately post-implementation; +1 net from the new `KeyError` regression test).

### File List

**Modified:**
- `pipeline/adapters/claude.py` (added `_LANGUAGE_NAMES` mapping plus an import-time sync assertion against `OutputLanguage`; `_prompt_for`/`summarize_clusters` retyped to `language: OutputLanguage`; prompt interpolates the mapped name; docstring corrected to state precisely what the retyping does and doesn't enforce)
- `pipeline/stages/summarize.py` (`run_summarize`/`SummarizeFn` retyped to `OutputLanguage`; metadata and path segment write `language.value`; CLI `--language` arg validated against `OutputLanguage`'s values; docstring corrected alongside `claude.py`'s)
- `tests/test_claude_adapter.py` (bulk-updated 10 existing call sites from bare `"fr"` to `OutputLanguage.FR`; added 4 new tests — language-name correctness, cross-language grounding-data invariance, non-Latin-script pass-through, and the unsupported-language `KeyError`; consolidated 3 local `_prompt_for` imports to module scope)
- `tests/test_summarize_stage.py` (bulk-updated 4 existing call sites and 4 `fake_summarize` signatures to `OutputLanguage`; consolidated 3 local `_prompt_for` imports to module scope)

## Change Log

- 2026-08-12: Story created via bmad-create-story. User explicitly decided this story stays scoped to per-language summarize correctness, deferring the 15 Zone × 3 Period assembly loop to Story 3.5 (publish), since `cycle.py` has no per-Zone/Period orchestration yet and publish is where `data/briefings/` output actually lands per the architecture spine's Structural Seed. Story creation also surfaced a real gap in Story 3.1's shipped code: the prompt interpolates a bare `OutputLanguage` code ("fr") rather than a language name ("French") — folded into this story as Task 1 rather than filed separately.
- 2026-08-12: Implemented via bmad-dev-story. Both tasks complete, TDD throughout. Confirmed the prompt-language gap was real by reading the shipped code before writing any test. 243/243 tests passing (up from 240). Status set to review.
- 2026-08-12: Reviewed via bmad-code-review (single-layer adversarial pass, per the standing cost-reduction decision). Fixed 4 real findings: no import-time sync check between `_LANGUAGE_NAMES` and `OutputLanguage`, no test proving the documented `KeyError`-on-unmapped-language behavior, an overstated docstring claim about what `OutputLanguage` typing actually enforces at runtime (it's a `StrEnum` — typing alone is not a runtime guard), and 6 redundant local imports consolidated to module scope. One finding (two independently-maintained language enumerations across `config` and `claude.py`) was noted as a legitimate future consideration, not a bug today. 244/244 tests passing. Status set to done.
