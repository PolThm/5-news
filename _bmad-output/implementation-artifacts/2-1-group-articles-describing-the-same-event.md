---
baseline_commit: 37d4486
---

# Story 2.1: Group Articles describing the same Event

Status: done

## Story

As the developer,
I want Articles about one Event grouped into one Cluster across languages,
so that a Japanese and a French Article about the same event count as one story, not two.

## Acceptance Criteria

1. **The cluster stage runs alone, on dedupe's output.** `python -m pipeline.stages.cluster --input <dedupe-groups-path> --cycle-id <id>` reads the dedupe stage's `groups.jsonl` and writes Clusters to `data/intermediate/cluster/<cycle-id>/clusters.jsonl`, one JSON Line per Cluster, each carrying its member Article-group identifiers (normalized titles, since that is what dedupe's output keys on — there is no separate Article-level ID yet).

2. **Cross-language grouping actually works.** Two dedupe groups whose representative titles are semantically the same Event but in different languages (e.g. a French headline and a Japanese headline about the same event) land in the same Cluster. This is the whole point of the story — a same-language near-duplicate is dedupe's job (Epic 1); embedding-based semantic clustering across languages is this stage's job, and did not exist before it.

3. **The embedding vendor is isolated.** All calls to the Cohere SDK live in `pipeline/adapters/cohere_embed.py`. `pipeline/stages/cluster.py` calls an adapter function that takes strings and returns vectors — it never imports `cohere` directly and never sees a Cohere response object (AD-13).

4. **Independent Source counts are inherited, never recomputed.** A Cluster's Independent Source count and country count are the union of its member dedupe-groups' counts (an ArticleGroup is one Independent Source with one origin country — Story 1.4's semantics). The cluster stage does not re-derive these from raw articles or re-implement any part of Syndication Detection (AD-5, AD-12).

5. **A cycle degrades, not crashes, on an embedding failure.** If the Cohere adapter fails (network error, auth error, rate limit exhausted), the cluster stage records a failure and falls back to one Cluster per dedupe group (i.e., no cross-language merging that cycle) rather than aborting the cycle — consistent with `run_cycle`'s existing degrade-not-crash contract (AD-10, `pipeline/stages/cycle.py`).

6. **Determinism within a single embedding response is preserved.** Given the same embeddings, clustering the same input twice produces the same groupings and the same output bytes (sorted keys, stable ordering, stable Cluster-ID assignment). Note the explicit exception below under Dev Notes → "What determinism means here" — embeddings themselves are not byte-reproducible across API calls by contract, only the clustering step downstream of them is.

## Tasks / Subtasks

- [x] **Task 1: Cohere embedding adapter** (AC: 3)
  - [x] Add `cohere>=7.0.0` to `pyproject.toml` `[project.dependencies]`
  - [x] `pipeline/adapters/cohere_embed.py`: a function `embed_titles(titles: list[str]) -> CollectionResult` (reuse the existing `CollectionResult`/`Failure` shape from `pipeline/adapters/__init__.py` if it fits, or a parallel narrow result type — see Dev Notes → Adapter contract shape)
  - [x] Chunk input into batches of ≤ 96 titles per call (Cohere's per-request cap) and concatenate results in input order
  - [x] Call `co.embed(model="embed-v4.0", texts=<batch>, input_type="clustering", embedding_types=["float"], output_dimension=1024, truncate="RIGHT")` — `input_type="clustering"` is mandatory; using `search_document`/`search_query` silently degrades clustering quality with no error (see Dev Notes → Cohere API specifics)
  - [x] Read the API key from an environment variable (`COHERE_API_KEY`); the adapter raises a clear, caught-at-the-boundary error if it is unset — never hardcode or default a key
  - [x] Adapter never raises past its own boundary (AD-10): wrap the SDK call, return a `Failure` on any exception
  - [x] Confirm the exact response attribute path (`response.embeddings.float_` vs `.float`) against the actually-installed `cohere` version with a two-line smoke test before writing the parsing code — the two spellings both appear in circulation depending on SDK minor version (see Dev Notes)

- [x] **Task 2: Clustering logic** (AC: 2, 6)
  - [x] `pipeline/stages/cluster.py`: read `groups.jsonl` from the given `--input` path (dedupe's output format — see Dev Notes → Dedupe output shape)
  - [x] Embed each group's representative title (the `title` field already on dedupe's output dict — no need to re-read raw articles)
  - [x] L2-normalize the returned vectors (`sklearn.preprocessing.normalize`) before clustering — `sklearn.cluster.HDBSCAN` rejects `metric="cosine"` outright (`InvalidParameterError`); normalizing to unit vectors first makes Euclidean distance monotonic with cosine distance, which is the standard workaround (see Dev Notes)
  - [x] Add `scikit-learn>=1.3` to `pyproject.toml` dependencies
  - [x] Run `sklearn.cluster.HDBSCAN(min_cluster_size=2, metric="euclidean")` on the normalized vectors — `min_cluster_size=2` because a Cluster needs only 2 dedupe-groups to later qualify (Story 2.2's floor), not sklearn's default of 5
  - [x] `labels_ == -1` is noise (HDBSCAN's own convention) — each noise point becomes its own singleton Cluster, not a discarded one; singleton Clusters are legitimate and will simply fail Story 2.2's qualifying floor later. The cluster stage does not decide what qualifies (AD-12) — do not filter singleton Clusters out here.
  - [x] Assign a stable, deterministic Cluster ID per output group: derive it from a sorted tuple of member normalized-titles (e.g. a hash of the sorted-joined titles), not from HDBSCAN's arbitrary integer label — labels are not stable across runs with reordered input, but this derivation is

- [x] **Task 3: Degrade-on-failure path** (AC: 5)
  - [x] If the embedding adapter returns any failures (partial or total), fall back to one Cluster per dedupe group for this run and record the failure in the cluster stage's own metadata output (mirror the `{stage}.json` metadata pattern from `collect.py`/`dedupe.py`)
  - [x] Wire `run_cycle` (`pipeline/stages/cycle.py`) to call the cluster stage after dedupe, guarded by its own independent try/except, following the exact pattern already used for `write_collection`/`run_dedupe` — the cycle must still write `cycle.json` if clustering crashes outright, not just if it degrades

- [x] **Task 4: Cluster and Coverage inheritance** (AC: 4)
  - [x] Cluster output JSON carries: cluster ID, member dedupe-group titles (or their normalized-title keys), `independent_source_count` and `country_count` as computed by unioning member groups (reuse or mirror `ArticleGroup.merge_all`'s logic from `pipeline/stages/dedupe.py` — do not reimplement source/country counting from scratch)
  - [x] Write output with `write_jsonl` from `pipeline.stages` (sorted keys, atomic, trailing newline — the existing stage-contract helper)

- [x] **Task 5: Tests**
  - [x] Unit test the Cohere adapter against an injected fake client (same pattern as `GdeltClient`'s injectable `fetch`) — no real network call in tests
  - [x] Unit test the L2-normalize + HDBSCAN clustering logic with **hand-constructed embedding vectors** (not real Cohere calls) covering: two vectors close together cluster together; two far-apart vectors land in separate clusters; a single vector becomes a singleton cluster
  - [x] Test the Independent Source / country count inheritance with a constructed multi-group Cluster, verifying it matches the union semantics from Story 1.4 exactly
  - [x] Test the degrade path: inject an adapter failure, verify the stage falls back to one-cluster-per-group and the cycle still completes and writes `cycle.json`
  - [x] Test determinism: same input embeddings run twice → byte-identical output file

## Dev Notes

### What determinism means here

AD-4 requires the **rank** stage (Story 2.2) to be fully deterministic and AI-free. This stage is different: it legitimately calls an external model (Cohere's embedding API), and embedding outputs are not contractually guaranteed byte-identical across calls by Cohere (model updates, floating-point non-determinism on their infrastructure are outside our control). What **is** required to be deterministic here is everything downstream of the embeddings: given the same vectors, `normalize` → `HDBSCAN` → Cluster-ID assignment → JSON serialization must produce byte-identical output every time. Do not chase byte-identical output across two separate live API calls — that is not achievable and not the contract. Tests should verify determinism using fixed, hand-constructed embedding vectors, never live API output.

### Cohere API specifics (verified 2026-08, cite this if versions drift)

- Package: `cohere` on PyPI, `>=7.0.0` (7.0.5 confirmed current at time of writing)
- Client: `cohere.ClientV2(api_key=...)`, method `co.embed(...)`
- Required params for this use case: `model="embed-v4.0"`, `texts=[...]` (≤ 96 per call, ≤ 128,000 tokens per call), `input_type="clustering"` (the four allowed values are `search_document`, `search_query`, `classification`, `clustering` — using the wrong one does not error, it just silently produces worse clusters), `embedding_types=["float"]` (must be a list; other values like `int8`/`binary` exist but are not what HDBSCAN needs)
- `output_dimension`: pick one value (256/512/1024/1536) and pin it in the adapter as a constant — mixing dimensions across pipeline runs would silently corrupt distance math rather than erroring. This story picks **1024** as a reasonable cost/quality tradeoff; there is no strong reason to prefer 1536 for title-length text.
- Response shape: `response.embeddings.<embedding_type>` where `<embedding_type>` matches what was requested (i.e. `.float_` or `.float` depending on the installed SDK's generated stubs — confirmed to vary; **do not hardcode blind**, run `print(dir(response.embeddings))` once against the actually-pinned version and use whatever attribute is really there)
- Rate limit: ~2,000 inputs/minute on the embed endpoint. At the volumes one daily World/day cycle produces (low hundreds of dedupe groups at most, going by Epic 1's observed output), this will not be hit — no pacing logic is required for v1, unlike GDELT's adapter. Revisit only if daily group counts grow into the thousands.
- Trial keys cap at ~1,000 calls/month — fine for development, but note in `.env.example` or README that production needs a paid key. This story does not need to build key provisioning, only read `COHERE_API_KEY` from the environment.

### HDBSCAN specifics

- `sklearn.cluster.HDBSCAN` has been stable (non-experimental) since scikit-learn 1.3 — no feature flag needed
- `metric="cosine"` raises `InvalidParameterError` — HDBSCAN's tree-based internals don't support it despite what general sklearn docs on `pairwise_distances` might suggest (this is a known, still-open scikit-learn limitation). **Always L2-normalize with `sklearn.preprocessing.normalize` first, then use the default `metric="euclidean"`.** On unit vectors, Euclidean distance is a monotonic transform of cosine distance, so results are equivalent.
- `labels_` gives one integer label per input point; **`-1` means noise** (did not fit any dense-enough cluster) — this is a real, standard sklearn/HDBSCAN convention, not an error condition. Per Task 2, treat every `-1` point as its own singleton Cluster rather than discarding it — discarding happens later, at the rank stage's qualifying floor (Story 2.2), not here (AD-12: this stage doesn't own that decision).

### Dedupe output shape (what this stage reads)

From `pipeline/stages/dedupe.py`, `groups.jsonl` (one `ArticleGroup.to_dict()` per line) has these keys: `title`, `url`, `published_at`, `source`, `source_country`, `language`, `collected_by` (from the representative `ArticleRecord`), plus `normalized_title`, `independent_source_count` (always 1 at this stage — one dedupe group is one dispatch), `country_count` (always 1), `sources` (list), `countries` (list), `article_count`. Read with `pipeline.stages.read_jsonl`.

The cluster stage's job is exactly the aggregation `ArticleGroup.merge_all` already does for *groups you already know belong together* — Story 1.4 built that half. This story builds the half that decides *which groups belong together* across languages, then calls the same union logic.

### Independent Source / country inheritance (AD-5, AD-12)

`ArticleGroup.merge_all(groups: list[ArticleGroup]) -> Coverage` in `pipeline/stages/dedupe.py` already implements: `independent_source_count=len(groups)`, `country_count=len({g.origin_country for g in groups})`. The cluster stage groups dedupe-groups by semantic similarity and must apply the *same* union semantics to the resulting membership — either by importing and reusing this function directly (if the dedupe-group dicts read from disk can be reconstructed into `ArticleGroup` objects cheaply) or by re-deriving the identical union logic against the plain dicts if reconstructing full `ArticleGroup`/`ArticleRecord` objects is awkward from serialized JSON. Whichever approach is simpler, the **arithmetic must be provably identical** — this is the same number that will be shown to the reader as proof of coverage (FR-7), and Story 1.4/the epic-wide review already spent two rounds getting this exact union right. Do not re-derive it independently; re-use or mirror line-for-line.

### Adapter contract shape

Look at `pipeline/adapters/__init__.py`'s `Failure`/`CollectionResult` dataclasses and `pipeline/adapters/gdelt.py`'s `GdeltClient` for the established pattern: an injectable callable for the actual network call (keeps tests network-free), a method that never raises past the adapter boundary, and a result type that separates "here's what I got" from "here's what failed." `CollectionResult` is shaped around collecting Articles (a list of dicts); if reusing it for embeddings is awkward (embeddings are vectors, not Article-shaped dicts), define a small parallel result type in `cohere_embed.py` following the same shape/spirit — do not force-fit `CollectionResult` if the fit is bad, but do not invent a structurally different failure-handling story either.

### Cycle wiring (AD-10)

`pipeline/stages/cycle.py`'s `run_cycle` currently guards `write_collection` then `run_dedupe`, each in its own try/except, writing `cycle.json` unconditionally at the end regardless of where a crash occurred (this exact pattern was hardened in the Epic 1 review — see the "Epic 1: address adversarial review findings" commit). Add a third guarded step for the cluster stage, following the identical pattern: its own try/except, its own `completed`-affecting failure record, no change to the unconditional final `cycle.json` write. Read `run_cycle` in full before touching it — it is short (~90 lines) and the guard pattern must be copied exactly, not reinvented.

### Project Structure Notes

New files this story creates:
- `pipeline/adapters/cohere_embed.py`
- `pipeline/stages/cluster.py`
- `tests/test_cohere_adapter.py`
- `tests/test_cluster_stage.py`

Files this story modifies:
- `pipeline/stages/cycle.py` (add the guarded cluster step)
- `pyproject.toml` (add `cohere`, `scikit-learn` dependencies)
- `.github/workflows/collect.yml` — rename or extend to also run clustering, OR confirm whether the existing workflow already invokes `pipeline.stages.cycle` as a whole (it does — `uv run python -m pipeline.stages.cycle`, per `.github/workflows/collect.yml`) and only needs the `COHERE_API_KEY` secret wired in via `env:` for the "Run the cycle" step. Check the current workflow file before assuming which is true.
- `.github/workflows/ci.yml` — likely needs the same env var (or a placeholder/mock) if any CI test path would otherwise attempt a live Cohere call; tests must not require a real API key to pass (Task 5 tests use fakes, so this should be a non-issue if adapter tests are written correctly)

### Previous Story Intelligence (from Epic 1 and its review)

- The Epic 1 adversarial review found and fixed several defects worth remembering here: (1) a crash in one guarded pipeline step must not prevent `cycle.json` from being written — replicate the guard pattern, don't just wrap the happy path; (2) atomic writes (`write_atomically`/`write_jsonl`) are mandatory for anything written to `data/intermediate/` — a timeout kill mid-write must never leave a truncated file; (3) country-count aggregation is easy to get subtly wrong (inflate by unioning every republisher's country, or deflate by collapsing to one country) — Story 1.4 required two correction rounds to get right, so this story reuses that logic rather than re-deriving it.
- GDELT's adapter (`pipeline/adapters/gdelt.py`) is the reference pattern for "vendor SDK isolated behind an injectable-fetch adapter that never raises past its boundary" — follow its shape for `cohere_embed.py`.
- Request budgets matter: GDELT needed a hard cap after a live worst-case calculation showed unbounded recursion could take ~410 minutes. Cohere's real limits (2,000/min, 96/request) are generous enough at current volumes that no equivalent cap is needed yet — but if daily dedupe-group counts ever grow past roughly 2,000, this will need revisiting (unlikely before Epic 2 stabilizes; not in scope now).

### References

- [Source: architecture/architecture-5-news-2026-08-10/ARCHITECTURE-SPINE.md#AD-13] — vendor SDKs isolated to adapters
- [Source: architecture/architecture-5-news-2026-08-10/ARCHITECTURE-SPINE.md#AD-5, AD-12] — Independent Source counting happens once, never recomputed
- [Source: architecture/architecture-5-news-2026-08-10/ARCHITECTURE-SPINE.md#AD-10] — adapters never raise past their boundary
- [Source: architecture/architecture-5-news-2026-08-10/ARCHITECTURE-SPINE.md — Tooling versions] — Cohere `embed-v4`, $0.01/M tokens (spine's estimate; verified research above found $0.12/M text tokens — the spine's figure appears to predate a pricing update; use the verified $0.12/M for any cost estimation, and note the spine may want a refresh)
- [Source: epics.md#Story 2.1] — acceptance criteria origin
- [Source: pipeline/stages/dedupe.py] — `ArticleGroup`, `Coverage`, `merge_all` — reused, not reimplemented
- [Source: pipeline/stages/cycle.py] — guard pattern to replicate for the cluster step
- [Source: pipeline/adapters/gdelt.py] — reference adapter isolation pattern

## Dev Agent Record

### Context Reference

Implemented directly from this story file's Dev Notes; no separate story-context document was generated.

### Debug Log

- Confirmed the installed `cohere` SDK is 7.0.8 (story assumed 7.0.5 as "current at time of writing" — no breaking difference found) and confirmed the response attribute is `response.embeddings.float_` (with trailing underscore) via `EmbedByTypeResponseEmbeddings.model_fields.keys()` before writing any parsing code, per Task 1's explicit instruction.
- `co.embed`'s real signature only accepts `truncate` values `NONE`/`START`/`END` — the story's Dev Notes suggested `RIGHT`, which does not exist on the real SDK. Used `END` (equivalent intent: truncate from the end if a title is pathologically long).
- The story specified `HDBSCAN(min_cluster_size=2, metric="euclidean")` on L2-normalized vectors. Live-tested against realistic small inputs (3-5 groups, typical of one day's dedupe output) and found HDBSCAN's density-based criterion alone labels genuinely near-identical pairs as noise (`-1`) at this data scale — verified directly: two vectors 0.02 apart (post-normalization) alongside one unrelated point all returned noise under the story's specified parameters. Root cause: HDBSCAN's density comparison needs more surrounding points than a single day's cluster count provides. Fixed by adding `min_samples=1`, `cluster_selection_epsilon=0.4` (empirically chosen: on unit vectors this Euclidean threshold corresponds to cosine similarity ~0.92, mapped via d² = 2 - 2c), and `allow_single_cluster=True` — verified this combination correctly merges close pairs while still treating genuinely unrelated points, and pairs of totally unrelated points, as noise. This is a deviation from the story's exact constructor call but not from its intent; documented inline in `cluster_vectors`'s docstring.
- `ArticleGroup.merge_all` (Story 1.4) operates on reconstructed `ArticleGroup` objects; dedupe's serialized `groups.jsonl` does not carry enough information to reconstruct one losslessly (per-article detail is flattened away). Mirrored the identical union arithmetic (`len(groups)` sources, `len({origin countries})`) against the flat dicts instead of reconstructing objects, as the story's Dev Notes anticipated as an acceptable alternative if reconstruction was awkward.

### Completion Notes

All 5 tasks and their subtasks are complete. 22 new tests added initially (6 adapter, 12 cluster-stage, 4 new/modified cycle-integration tests), all passing; full suite was 134 tests, all green. `ruff check` and `ruff format --check` both pass. Boundary check passes.

**Post-review fixes (bmad-code-review, 3-layer adversarial pass — Blind Hunter, Edge Case Hunter, Acceptance Auditor):**

The Acceptance Auditor found zero AC violations — all 6 ACs independently verified against code and passing. The Blind Hunter and Edge Case Hunter each independently found the same two serious defects, from different angles, both live-reproduced before fixing:

1. **False-merge via HDBSCAN single-linkage chaining (high severity).** The original `cluster_vectors` used `HDBSCAN(cluster_selection_epsilon=0.4, allow_single_cluster=True, ...)`. The epsilon threshold governs where HDBSCAN cuts its internal single-linkage tree, not the pairwise distance between merged points — a chain of intermediate points lets two points 1.0-1.4 apart (well over the 0.4 threshold) merge into one cluster. Live-reproduced: 40 unrelated random vectors plus one genuine near-duplicate pair, 18 of 30 trials merged an unrelated group into the pair's cluster. This would have inflated `independent_source_count` for unrelated Events — the exact class of bug this whole pipeline exists to prevent. **Fixed** by replacing HDBSCAN entirely with connected-components over an explicit pairwise-distance threshold graph (`scipy.sparse.csgraph.connected_components`): an edge exists only if two points' *own* distance is within threshold, so no transitive chaining is possible. Re-verified: 0 of 30 trials false-merge.

2. **Cluster-ID hash collision on duplicate title text (high severity).** `assign_cluster_ids` hashed the sorted *title text* of each cluster's members. Two dedupe groups with an identical `title` string but placed in different clusters by `cluster_vectors` (different countries, unrelated embeddings) collided onto the same cluster ID and were silently re-merged in `run_cluster`'s `members_by_id` grouping — reintroducing the exact inflation clustering had just correctly avoided. **Fixed** by deriving cluster IDs from sorted *member indices* instead of title text, which cannot collide regardless of content. `assign_cluster_ids`'s signature simplified from `(titles, labels)` to `(labels)` since title text was never actually load-bearing once fixed.

3. **Malformed-vector crash escalating to whole-cycle failure (medium severity, Edge Case Hunter).** A vendor response with ragged vector rows or NaN/Inf components would raise uncaught inside `cluster_vectors`/`normalize`/`pdist`, propagating to `cycle.py`'s generic exception handler and marking the *entire cycle* `completed=False` — worse than the graceful one-cluster-per-group degrade every other embedding failure gets. A batch of all-zero vectors (a plausible response to an empty/truncated title) was a second, quieter variant: it wouldn't crash, but would silently merge every zero-vector group into one cluster with no failure ever recorded. **Fixed** by adding `_vectors_are_well_formed` (checks uniform length, all-finite, not-all-zero) as a pre-clustering guard in `run_cluster`; any failure there now degrades exactly like an embedding failure, with the shortfall recorded in metadata.

4. **Minor, disclosed-not-fixed:** `EmbedFn`'s type alias only describes the single-arg call shape actually used (not `embed_titles`'s full two-parameter signature) — annotated inline rather than widened, since widening would let `run_cluster` silently start accepting a `client` parameter it has no way to use. Stale job name in `collect.yml` (`Collect and deduplicate` → `Collect, dedupe, and cluster`) — fixed. All-or-nothing (not partial) vector recovery on a multi-batch embedding failure in `cohere_embed.py` — deliberately kept as-is and documented inline: `EmbeddingResult.vectors` is positional (index-aligned to input groups), so a partial vector list can't safely combine with a full group list without either misalignment or added complexity for a case Cohere's real rate limits make unlikely to matter (~2000 req/min against expected daily volumes in the tens).

After fixes: 136 tests passing (up from 134 — 2 net new tests added during the fix pass; a few pre-existing tests were also rewritten in place rather than added-alongside, since they asserted behavior the fix deliberately changed — e.g. HDBSCAN's `-1` noise label no longer exists under connected-components). Re-verified the chaining fix empirically at the same 40-vector realistic scale: 0/30 false merges (down from 18/30 before the fix).

Key implementation notes for future stories:
- `pipeline/adapters/cohere_embed.py` follows the GDELT adapter's injectable-client pattern exactly; no live network call happens in any test.
- The cluster stage degrades to one-Cluster-per-dedupe-group on any embedding failure (AC5), verified both at the stage level and through the full `run_cycle` integration path — a Cohere outage no longer crashes a cycle.
- `run_cycle` gained a third guarded stage (cluster, after dedupe), following the exact try/except-per-stage pattern hardened during the Epic 1 review. `cycle.json` still always gets written, now also carrying `clusters_after_grouping`.
- `.github/workflows/collect.yml` now passes `COHERE_API_KEY` from a repository secret to the cycle step. This secret does not exist yet in the repository — **a human needs to add it before the next scheduled run**, or the cycle will degrade (never crash) every day until it's added. `ci.yml` needed no changes since all tests use fakes.
- Existing `tests/test_cycle.py` tests were updated to pass an explicit no-op `embed` stub, since `run_cycle`'s new `embed` parameter defaults to the real `embed_titles` (consistent with `collect`'s existing pattern of defaulting to real adapters) and would otherwise have attempted a live call with no API key during those tests.

### File List

**New:**
- `pipeline/adapters/cohere_embed.py`
- `pipeline/stages/cluster.py`
- `tests/test_cohere_adapter.py`
- `tests/test_cluster_stage.py`

**Modified:**
- `pipeline/stages/cycle.py` (added guarded cluster step, `clusters_after_grouping` field, `cluster_path`, `embed` parameter)
- `tests/test_cycle.py` (added no-op embed stub to all existing `run_cycle` calls; added 3 new tests for the cluster integration)
- `pyproject.toml` (added `cohere>=7.0.0`, `scikit-learn>=1.3`, `numpy` dependencies)
- `uv.lock` (regenerated)
- `.github/workflows/collect.yml` (added `COHERE_API_KEY` env var from repository secret)

## Change Log

- 2026-08-11: Story created via bmad-create-story, targeting Epic 2's first story.
- 2026-08-11: Implemented via bmad-dev-story. All tasks complete, 134/134 tests passing. Status set to review.
- 2026-08-11: Reviewed via bmad-code-review (3-layer adversarial: Blind Hunter, Edge Case Hunter, Acceptance Auditor). Two high-severity findings fixed (HDBSCAN single-linkage false-merge; cluster-ID hash collision on duplicate titles), one medium fixed (malformed-vector crash escalation), minor findings disclosed. 136/136 tests passing. Status set to done.
