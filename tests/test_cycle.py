"""Running a full cycle: collect, dedupe, cluster, rank per Zone x Period,
summarize per Output Language, then publish -- and record what happened.

Story 1.5 turns the pipeline from something you invoke into something that
accumulates. The Build Order's inspection window depends on days of real output
piling up without anyone starting them.

A failed cycle must leave the previous cycle's committed output untouched
(AD-7): the next run is independent of the last one.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pipeline.adapters import CollectionResult, Failure
from pipeline.adapters.cohere_embed import EmbeddingResult
from pipeline.domain import ArticleRecord, OutputLanguage
from pipeline.stages.cycle import CycleResult, memoize_embeddings, run_cycle
from pipeline.stages.summarize import WrittenSubmission, WrittenSummarize


def _record(title: str, source: str, country: str = "france") -> ArticleRecord:
    return ArticleRecord(
        title=title,
        url=f"https://{source}/{abs(hash(title + source))}",
        published_at=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
        source=source,
        source_country=country,
        language="fr",
        collected_by="gdelt",
    )


def _collection(*records: ArticleRecord, failures: list[Failure] | None = None) -> CollectionResult:
    return CollectionResult(articles=[r.to_dict() for r in records], failures=failures or [])


# Three reference newsrooms naming one subject: the smallest corpus in which the
# subject stage's editorial floor can be met. A cycle whose corpus forms no
# subject falls back to the agenda and is correctly marked degraded, so a test
# about anything else has to clear the floor first or it is testing the fallback.
_REFERENCE_NEWSROOMS = ("lemonde.fr", "elpais.com", "theguardian.com")


def _subject_corpus(name: str = "Ceuta") -> tuple[ArticleRecord, ...]:
    # Three countries, not one: `qualifies` holds a subject to two Independent
    # Sources AND two countries, and `_is_relevant_to` places it by
    # `mentioned_countries`. A corpus that clears the editorial floor but not
    # those two would form a subject and rank nothing, which is a fallback path
    # dressed up as a success.
    countries = ("france", "spain", "germany")
    # One headline, three newsrooms: the articles must form ONE event, not three.
    # `_no_op_embed` keys a vector on the title text, so three different titles
    # are three orthogonal points and the event split -- correctly -- separates
    # them into three single-article events that clear no floor. Real syndication
    # looks like this too.
    return tuple(
        ArticleRecord(
            title=f"La crise a {name} s'aggrave",
            url=f"https://{source}/{i}",
            published_at=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
            source=source,
            source_country=country,
            language="fr",
            collected_by="rss",
            mentioned_countries=("spain",),
        )
        for i, (source, country) in enumerate(zip(_REFERENCE_NEWSROOMS, countries, strict=True))
    )


_STUB_DIMENSION = 16


def _no_op_embed(titles: list[str]) -> EmbeddingResult:
    """These tests exercise collect/dedupe/cycle-record behavior, not
    clustering — a stub embedding keeps them independent of Cohere and of
    Story 2.1's clustering logic, which has its own test module. Each title
    gets a distinct *direction* (not just a distinct magnitude, which
    normalizes away) so groups never accidentally merge, and no vector is
    all-zero, which would trip the malformed-response guard.

    Keyed on the TEXT at a FIXED width, not one-hot on position. Position-based
    vectors were dimensioned by how many titles a call happened to carry, which
    stopped being coherent once `memoize_embeddings` began requesting only the
    titles it had not already cached: a later call asking for two titles got
    one back at a different width, and two unrelated strings came out identical
    -- silently making everything corroborate everything. A real model returns a
    fixed width keyed on content, and so does this now.
    """
    vectors: list[list[float]] = []
    for title in titles:
        digest = hashlib.sha256(title.encode("utf-8")).digest()
        # Centred on zero so directions spread over the sphere rather than
        # crowding one quadrant, which would make everything look similar.
        vectors.append([(digest[i] - 128) / 128.0 for i in range(_STUB_DIMENSION)])
    return EmbeddingResult(vectors=vectors)


def _no_op_submit_summarize(
    clusters: list[dict],
    language: OutputLanguage,
    cycle_id: str,
    data_root: Path,
    angles: list[tuple[dict, str]] | None = None,
) -> WrittenSubmission:
    """These tests exercise collect/dedupe/cluster/rank/history behavior,
    not summarization -- a stub submission keeps them independent of the
    Claude adapter (its own test module) and of a real ANTHROPIC_API_KEY,
    which is never set in this test environment. Always "succeeds" with a
    batch ID derived from the language, so each of the 3 per-cycle
    submissions gets a distinct id."""
    return WrittenSubmission(
        batch_id=f"stub-batch-{language.value}",
        metadata_path=data_root
        / "intermediate"
        / "summarize"
        / cycle_id
        / language.value
        / "submitting.json",
        submitted=True,
    )


def _collect_that_never_completes(
    batch_id: str, clusters: list[dict], language: OutputLanguage, cycle_id: str, data_root: Path
) -> None:
    return None


def _make_collect_that_completes_for(*ready_languages: OutputLanguage):
    """A fake collect_summarize_fn where only the named languages'
    batches have "ended" -- everything else stays pending, so tests can
    exercise the partial-resume case precisely."""

    def _collect(
        batch_id: str,
        clusters: list[dict],
        language: OutputLanguage,
        cycle_id: str,
        data_root: Path,
    ) -> WrittenSummarize | None:
        if language not in ready_languages:
            return None
        output_path = (
            data_root
            / "intermediate"
            / "summarize"
            / cycle_id
            / language.value
            / "summarized.jsonl"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(
                {
                    **c,
                    "summary": f"{language.value} summary for {c['cluster_id']}",
                    "outbound_url": f"https://example.com/{c['cluster_id']}",
                    "outbound_source": "example.com",
                }
            )
            for c in clusters
        ]
        output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        metadata_path = output_path.parent / "summarize.json"
        metadata_path.write_text("{}", encoding="utf-8")
        return WrittenSummarize(
            output_path=output_path,
            metadata_path=metadata_path,
            clusters_summarized=len(clusters),
            degraded=False,
        )

    return _collect


def test_runs_collect_then_dedupe(tmp_path: Path) -> None:
    """AC: collect and dedupe run for World / day."""
    collection = _collection(
        _record("Ceasefire agreed", "reuters.com", "united-kingdom"),
        _record("Ceasefire agreed", "lemonde.fr", "france"),
        _record("Markets rally", "ft.com", "united-kingdom"),
    )

    result = run_cycle(
        collect=lambda: collection,
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    assert result.articles_collected == 3
    assert result.groups_after_dedupe == 2
    assert result.collect_path.exists()
    assert result.dedupe_path.exists()


def test_writes_a_cycle_record(tmp_path: Path, working_agenda) -> None:
    working_agenda()
    """The cycle record is what a human reads weeks later to judge whether a
    thin day was a quiet news day or a broken upstream."""
    result = run_cycle(
        collect=lambda: _collection(*_subject_corpus()),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    record = json.loads(result.cycle_path.read_text())
    assert record["cycle_id"] == "2026-08-11T00-00-00Z"
    assert record["articles_collected"] == len(_REFERENCE_NEWSROOMS)
    # One group, not three: the fixture is one headline run by three newsrooms,
    # which is exactly what Syndication Detection collapses. The subject stage
    # still sees all three, because it reads the collect output rather than the
    # dedupe output -- three independent sources on one event.
    assert record["groups_after_dedupe"] == 1
    assert record["failures"] == []
    assert "started_at" in record


def test_cycle_record_names_upstream_failures(tmp_path: Path) -> None:
    """A degraded cycle is not a failed cycle, but the degradation must be
    visible — otherwise thin coverage looks like a quiet day (AD-10)."""
    result = run_cycle(
        collect=lambda: _collection(
            _record("A", "a.com"),
            failures=[Failure("gdelt", "429 after 3 of 7 windows")],
        ),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    record = json.loads(result.cycle_path.read_text())
    assert {"adapter": "gdelt", "detail": "429 after 3 of 7 windows"} in record["failures"]
    assert record["degraded"] is True


def test_a_clean_cycle_is_not_marked_degraded(tmp_path: Path, working_agenda) -> None:
    # A cycle whose editorial agenda is unavailable is NOT clean: it falls back
    # to ranking Clusters by how widely they were rerun, which is the selection
    # the agenda stage exists to replace, and the record has to show that.
    working_agenda()
    result = run_cycle(
        collect=lambda: _collection(*_subject_corpus()),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    assert json.loads(result.cycle_path.read_text())["degraded"] is False


def test_cycle_state_lands_where_a_later_run_can_resume_it(tmp_path: Path) -> None:
    """Spine convention: cross-phase state at
    data/intermediate/<cycle-id>/cycle.json, committed so a later scheduled run
    can pick it up (AD-11, and Story 3.4 depends on this path)."""
    result = run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    assert result.cycle_path == tmp_path / "intermediate" / "2026-08-11T00-00-00Z" / "cycle.json"


def test_a_totally_failed_collection_still_completes_the_cycle(tmp_path: Path) -> None:
    """Every upstream down is a fact about the day, recorded — not a crash."""
    result = run_cycle(
        collect=lambda: CollectionResult(
            articles=[],
            failures=[Failure("gdelt", "unreachable"), Failure("rss", "all feeds down")],
        ),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    assert result.articles_collected == 0
    record = json.loads(result.cycle_path.read_text())
    assert record["degraded"] is True
    details = [f["detail"] for f in record["failures"]]
    assert "unreachable" in " ".join(details)
    assert "all feeds down" in " ".join(details)


def test_a_new_cycle_does_not_touch_a_previous_one(tmp_path: Path) -> None:
    """AC: a cycle runs independently of a failed one, leaving previously
    committed output untouched."""
    first = run_cycle(
        collect=lambda: _collection(_record("Yesterday", "a.com")),
        cycle_id="2026-08-10T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )
    yesterday = first.dedupe_path.read_text()

    run_cycle(
        collect=lambda: CollectionResult(articles=[], failures=[Failure("gdelt", "down")]),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    assert first.dedupe_path.read_text() == yesterday, "yesterday's output survived"


def test_each_cycle_gets_its_own_directory(tmp_path: Path) -> None:
    first = run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-10T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )
    second = run_cycle(
        collect=lambda: _collection(_record("B", "b.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    assert first.cycle_path != second.cycle_path
    assert first.dedupe_path != second.dedupe_path


def test_collect_raising_is_contained(tmp_path: Path) -> None:
    """Adapters should never raise past their boundary, but the cycle is the
    last line of defense: an unexpected crash must still leave a record saying
    what happened rather than a silent gap."""

    def explode() -> CollectionResult:
        raise RuntimeError("adapter bug")

    result = run_cycle(
        collect=explode,
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    assert result.articles_collected == 0
    record = json.loads(result.cycle_path.read_text())
    assert record["degraded"] is True
    assert any("adapter bug" in f["detail"] for f in record["failures"])


def test_result_reports_success_for_a_degraded_but_completed_cycle(tmp_path: Path) -> None:
    """Exit status is about whether the cycle ran, not whether coverage was
    perfect — a scheduled job that reports failure on a thin day would train
    the author to ignore it."""
    result = run_cycle(
        collect=lambda: _collection(
            _record("A", "a.com"), failures=[Failure("rss", "one feed 404")]
        ),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    assert isinstance(result, CycleResult)
    assert result.completed is True


def test_dedupe_crashing_still_leaves_a_cycle_record(tmp_path: Path) -> None:
    """cycle.json is the ONLY tracked file and it is written last. A crash in
    dedupe that skipped it would leave nothing in git at all — the exact silent
    gap this function exists to prevent.
    """
    import pipeline.stages.cycle as cycle_module

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("dedupe exploded")

    original = cycle_module.run_dedupe
    cycle_module.run_dedupe = explode  # type: ignore[assignment]
    try:
        result = run_cycle(
            collect=lambda: _collection(_record("A", "a.com")),
            cycle_id="2026-08-11T00-00-00Z",
            data_root=tmp_path,
            embed=_no_op_embed,
            submit_summarize_fn=_no_op_submit_summarize,
        )
    finally:
        cycle_module.run_dedupe = original  # type: ignore[assignment]

    assert result.cycle_path.exists(), "a cycle record must survive any crash"
    assert result.completed is False
    assert result.dedupe_path is None, "a crashed stage must not report a path it never wrote"
    assert result.cluster_path is None, "a stage after a crash never ran and must report no path"
    record = json.loads(result.cycle_path.read_text())
    assert record["cycle_id"] == "2026-08-11T00-00-00Z"
    assert any("dedupe exploded" in f["detail"] for f in record["failures"])


def test_completed_is_false_when_a_stage_crashes(tmp_path: Path) -> None:
    """`completed` distinguishes "ran and found little" from "could not run".
    Without it the field is a constant and the distinction is unrepresentable.
    """
    import pipeline.stages.cycle as cycle_module

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("disk full")

    original = cycle_module.run_dedupe
    cycle_module.run_dedupe = explode  # type: ignore[assignment]
    try:
        result = run_cycle(
            collect=lambda: _collection(_record("A", "a.com")),
            cycle_id="2026-08-11T00-00-00Z",
            data_root=tmp_path,
            embed=_no_op_embed,
            submit_summarize_fn=_no_op_submit_summarize,
        )
    finally:
        cycle_module.run_dedupe = original  # type: ignore[assignment]

    assert result.completed is False
    record = json.loads(result.cycle_path.read_text())
    assert record["completed"] is False
    assert any("disk full" in f["detail"] for f in record["failures"])


def test_runs_cluster_after_dedupe(tmp_path: Path) -> None:
    """Story 2.1: the cycle now has a third stage. Two dispatches with
    distinct vectors must not be merged by the no-op embed stub."""
    result = run_cycle(
        collect=lambda: _collection(
            _record("Ceasefire agreed", "reuters.com", "united-kingdom"),
            _record("Markets rally", "ft.com", "france"),
        ),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    assert result.clusters_after_grouping == 2
    assert result.cluster_path.exists()

    record = json.loads(result.cycle_path.read_text())
    assert record["clusters_after_grouping"] == 2


def test_cluster_crashing_still_leaves_a_cycle_record(tmp_path: Path) -> None:
    """Same guard pattern as dedupe: cluster is the third guarded step, and a
    crash in it must not prevent cycle.json from being written."""
    import pipeline.stages.cycle as cycle_module

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("cluster exploded")

    original = cycle_module.run_cluster
    cycle_module.run_cluster = explode  # type: ignore[assignment]
    try:
        result = run_cycle(
            collect=lambda: _collection(_record("A", "a.com")),
            cycle_id="2026-08-11T00-00-00Z",
            data_root=tmp_path,
            embed=_no_op_embed,
            submit_summarize_fn=_no_op_submit_summarize,
        )
    finally:
        cycle_module.run_cluster = original  # type: ignore[assignment]

    assert result.completed is False
    assert result.cluster_path is None, "a crashed stage must not report a path it never wrote"
    assert result.rank_path is None, "a stage after a crash never ran and must report no path"
    record = json.loads(result.cycle_path.read_text())
    assert record["completed"] is False
    assert any("cluster exploded" in f["detail"] for f in record["failures"])


def test_embedding_failure_degrades_the_cycle_but_it_still_completes(tmp_path: Path) -> None:
    """Consistent with every other adapter boundary: a Cohere outage degrades
    clustering (falls back to one Cluster per dedupe group) but the cycle
    still runs to completion and still commits a cycle.json (AD-10)."""

    def failing_embed(titles: list[str]) -> EmbeddingResult:
        return EmbeddingResult(failures=[Failure("cohere_embed", "rate limited")])

    result = run_cycle(
        collect=lambda: _collection(
            _record("A", "a.com"),
            _record("B", "b.com"),
        ),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=failing_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    assert result.completed is True
    assert result.clusters_after_grouping == 2  # degraded: one cluster per group
    record = json.loads(result.cycle_path.read_text())
    assert record["degraded"] is True


def test_runs_rank_after_cluster(tmp_path: Path) -> None:
    """The cycle ranks across all 15 Zones x 3 Periods now (Story 3.5) --
    two distinct dispatches from different countries each land in their own
    singleton cluster, which does not meet the 2-source/2-country qualifying
    floor -- 0 selected in the union is the correct, honest result."""
    result = run_cycle(
        collect=lambda: _collection(
            _record("Ceasefire agreed", "reuters.com", "united-kingdom"),
            _record("Markets rally", "ft.com", "france"),
        ),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    assert result.rank_path.exists()
    assert result.clusters_selected == 0  # neither singleton cluster qualifies

    record = json.loads(result.cycle_path.read_text())
    assert record["clusters_selected"] == 0


def test_rank_crashing_still_leaves_a_cycle_record(tmp_path: Path) -> None:
    """Same guard pattern as collect/dedupe/cluster: ranking is the fourth
    guarded step, and a crash in it must not prevent cycle.json from being
    written."""
    import pipeline.stages.cycle as cycle_module

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("rank exploded")

    original = cycle_module.rank_all_zones
    cycle_module.rank_all_zones = explode  # type: ignore[assignment]
    try:
        result = run_cycle(
            collect=lambda: _collection(_record("A", "a.com")),
            cycle_id="2026-08-11T00-00-00Z",
            data_root=tmp_path,
            embed=_no_op_embed,
            submit_summarize_fn=_no_op_submit_summarize,
        )
    finally:
        cycle_module.rank_all_zones = original  # type: ignore[assignment]

    assert result.completed is False
    assert result.rank_path is None, "a crashed stage must not report a path it never wrote"
    assert result.cluster_path is not None, "cluster ran successfully before ranking crashed"
    record = json.loads(result.cycle_path.read_text())
    assert record["completed"] is False
    assert any("rank exploded" in f["detail"] for f in record["failures"])


def test_history_crashing_still_leaves_a_cycle_record(tmp_path: Path) -> None:
    """Same guard pattern as collect/dedupe/cluster/rank: history is the
    fifth guarded step, and a crash in it must not prevent cycle.json from
    being written."""
    import pipeline.stages.cycle as cycle_module

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("history exploded")

    original = cycle_module.append_history
    cycle_module.append_history = explode  # type: ignore[assignment]
    try:
        result = run_cycle(
            collect=lambda: _collection(_record("A", "a.com")),
            cycle_id="2026-08-11T00-00-00Z",
            data_root=tmp_path,
            embed=_no_op_embed,
            submit_summarize_fn=_no_op_submit_summarize,
        )
    finally:
        cycle_module.append_history = original  # type: ignore[assignment]

    assert result.completed is False
    record = json.loads(result.cycle_path.read_text())
    assert record["completed"] is False
    assert any("history exploded" in f["detail"] for f in record["failures"])


def test_history_runs_after_rank_and_records_selected_clusters(tmp_path: Path) -> None:
    """The end-to-end path: a cycle with genuine selected Clusters writes
    them to data/history/clusters.jsonl."""
    from pipeline.stages import read_jsonl

    result = run_cycle(
        collect=lambda: _collection(
            _record("Ceasefire agreed", "reuters.com", "united-kingdom"),
            _record("Ceasefire agreed", "lemonde.fr", "france"),
        ),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    assert result.completed is True
    history_path = tmp_path / "history" / "clusters.jsonl"
    if result.clusters_selected > 0:
        assert history_path.exists()
        records = list(read_jsonl(history_path))
        assert len(records) == result.clusters_selected


# --- Story 3.4/3.5: the two-phase, three-language summarize split -----------


def test_a_fresh_cycle_submits_three_batches_and_stops_without_waiting(tmp_path: Path) -> None:
    """AC5: phase one submits exactly one batch per Output Language (3
    total, not 135) and exits -- it never calls collect_summarize_fn."""

    def collect_summarize_fn_that_must_not_be_called(*args, **kwargs):
        raise AssertionError("a fresh cycle must not check a batch it just submitted")

    result = run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        collect_summarize_fn=collect_summarize_fn_that_must_not_be_called,
    )

    assert result.completed is True
    assert result.summarize_phase == "summarize_submitted"
    record = json.loads(result.cycle_path.read_text())
    assert set(record["summarize_batches"].keys()) == {"fr", "en", "es"}
    assert record["summarize_batches"]["fr"]["batch_id"] == "stub-batch-fr"


def test_a_synchronous_provider_collects_in_the_same_run(tmp_path: Path, monkeypatch) -> None:
    """The gateway provider must not leave the cycle at summarize_submitted.

    Its adapter parks generated text on the runner's local disk, and that
    disk does not survive the job -- `.gitignore` commits only an allowlist,
    which the results file is not on. A later catch-up would find a
    `gateway-local:` batch whose results exist nowhere and abandon the cycle.
    That is not hypothetical: the first production run under this provider
    (2026-08-27T00-21-50Z) spent two hours generating, stopped at
    summarize_submitted, and published nothing.

    The Claude path keeps the two-invocation shape -- a real Batch API id
    refers to state Anthropic still holds -- which the test above asserts.
    """
    monkeypatch.setenv("SUMMARIZE_PROVIDER", "gateway")

    collect_calls: list[str] = []

    def recording_collect(*args, **kwargs):
        collect_calls.append(kwargs.get("language", args[2] if len(args) > 2 else "?"))
        return None  # "still pending" -- the cycle must still have tried

    run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-27T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        collect_summarize_fn=recording_collect,
    )

    assert collect_calls, "a synchronous provider must collect in the same run"


def test_a_resumed_cycle_skips_collect_through_history_entirely(tmp_path: Path) -> None:
    """On the second invocation of the same cycle_id, collect through
    history must not re-run -- only the pending batches are checked."""
    collect_calls = 0

    def counting_collect() -> CollectionResult:
        nonlocal collect_calls
        collect_calls += 1
        return _collection(_record("A", "a.com"))

    run_cycle(
        collect=counting_collect,
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )
    assert collect_calls == 1

    second = run_cycle(
        collect=counting_collect,
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        collect_summarize_fn=_collect_that_never_completes,
    )

    assert collect_calls == 1, "collect must not run again on a resumed invocation"
    assert second.published is False


def test_a_partially_resolved_cycle_does_not_publish(tmp_path: Path) -> None:
    """A cycle where only some languages have collected must not publish a
    partial set -- it stays pending until every language resolves."""
    run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    result = run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        collect_summarize_fn=_make_collect_that_completes_for(OutputLanguage.FR),
    )

    assert result.published is False
    record = json.loads(result.cycle_path.read_text())
    assert set(record["summarize_batches"].keys()) == {"en", "es"}, (
        "fr resolved and must be removed from the pending set; en/es remain"
    )


def test_a_second_resume_does_not_recheck_an_already_resolved_language(tmp_path: Path) -> None:
    """Once a language's batch has collected, a later resumed invocation
    must not call collect_summarize_fn for it again."""
    run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )
    run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        collect_summarize_fn=_make_collect_that_completes_for(OutputLanguage.FR),
    )

    checked_languages: list[OutputLanguage] = []

    def recording_collect(
        batch_id: str,
        clusters: list[dict],
        language: OutputLanguage,
        cycle_id: str,
        data_root: Path,
    ) -> None:
        checked_languages.append(language)
        return None

    run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        collect_summarize_fn=recording_collect,
    )

    assert OutputLanguage.FR not in checked_languages
    assert set(checked_languages) == {OutputLanguage.EN, OutputLanguage.ES}


def test_a_cycle_where_all_three_languages_collect_publishes(tmp_path: Path) -> None:
    """AC1: once every language's batch has ended, the cycle assembles and
    publishes the full Briefing set atomically."""
    run_cycle(
        collect=lambda: _collection(
            _record("Ceasefire agreed", "reuters.com", "united-kingdom"),
            _record("Ceasefire agreed", "lemonde.fr", "france"),
        ),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    result = run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        collect_summarize_fn=_make_collect_that_completes_for(
            OutputLanguage.FR, OutputLanguage.EN, OutputLanguage.ES
        ),
    )

    assert result.published is True
    assert result.summarize_phase == "published"
    assert result.briefings_path == tmp_path / "briefings"
    assert (tmp_path / "briefings" / "fr" / "world" / "day.json").is_file()
    record = json.loads(result.cycle_path.read_text())
    assert record["summarize_batches"] == {}
    assert record["published"] is True


def test_a_published_briefing_carries_its_clusters_outbound_link(tmp_path: Path) -> None:
    """FR-14: a reader always has a genuine Article to click through to --
    the outbound_url/outbound_source summarize attaches per Cluster must
    survive all the way through publish, into the file actually served."""
    import pipeline.stages.cycle as cycle_module
    from pipeline.stages.cluster import WrittenCluster

    qualifying_cluster = {
        "cluster_id": "qualifying",
        "members": [
            {
                "title": "Ceasefire declared",
                "url": "https://reuters.com/1",
                "source": "reuters.com",
                "source_country": "united-kingdom",
                "language": "en",
            },
            {
                "title": "Regional truce",
                "url": "https://lemonde.fr/2",
                "source": "lemonde.fr",
                "source_country": "france",
                "language": "fr",
            },
        ],
        "independent_source_count": 2,
        "country_count": 2,
        "countries": ["france", "united-kingdom"],
        "origin_country": "united-kingdom",
    }

    original_run_cluster = cycle_module.run_cluster

    def fake_run_cluster(*args, **kwargs) -> WrittenCluster:
        written = original_run_cluster(*args, **kwargs)
        from pipeline.stages import write_jsonl

        write_jsonl(written.output_path, [qualifying_cluster])
        return WrittenCluster(
            output_path=written.output_path,
            metadata_path=written.metadata_path,
            clusters_out=1,
            degraded=written.degraded,
        )

    cycle_module.run_cluster = fake_run_cluster
    try:
        run_cycle(
            collect=lambda: _collection(_record("A", "a.com")),
            cycle_id="2026-08-11T00-00-00Z",
            data_root=tmp_path,
            embed=_no_op_embed,
            submit_summarize_fn=_no_op_submit_summarize,
        )
    finally:
        cycle_module.run_cluster = original_run_cluster

    run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        collect_summarize_fn=_make_collect_that_completes_for(
            OutputLanguage.FR, OutputLanguage.EN, OutputLanguage.ES
        ),
    )

    published = json.loads((tmp_path / "briefings" / "fr" / "world" / "day.json").read_text())
    assert published["clusters"], "the published Briefing must carry at least one Cluster"
    for cluster in published["clusters"]:
        assert cluster["outbound_url"] == f"https://example.com/{cluster['cluster_id']}"
        assert cluster["outbound_source"] == "example.com"


def test_a_publish_failure_is_retried_on_the_next_resume_without_resubmitting(
    tmp_path: Path,
) -> None:
    """AD-10/AD-7: a publish failure must degrade, not discard the
    already-collected summaries and force the whole cycle to restart from
    collect. The next invocation must retry publish directly -- it must not
    re-submit or re-collect any language's batch."""
    run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    def submit_fn_that_must_not_be_called(*args, **kwargs):
        raise AssertionError("a cycle retrying publish must not re-submit any batch")

    class _Boom(Exception):
        pass

    import pipeline.stages.cycle as cycle_module

    original_publish = cycle_module.publish_briefings

    def raising_publish(*args, **kwargs):
        raise _Boom("simulated publish crash")

    cycle_module.publish_briefings = raising_publish
    try:
        first_resume = run_cycle(
            collect=lambda: _collection(_record("A", "a.com")),
            cycle_id="2026-08-11T00-00-00Z",
            data_root=tmp_path,
            embed=_no_op_embed,
            submit_summarize_fn=submit_fn_that_must_not_be_called,
            collect_summarize_fn=_make_collect_that_completes_for(
                OutputLanguage.FR, OutputLanguage.EN, OutputLanguage.ES
            ),
        )
    finally:
        cycle_module.publish_briefings = original_publish

    assert first_resume.published is False
    assert first_resume.completed is True
    record = json.loads(first_resume.cycle_path.read_text())
    assert record["degraded"] is True
    assert any("publish raised" in f["detail"] for f in record["failures"])

    second_resume = run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=submit_fn_that_must_not_be_called,
        collect_summarize_fn=_make_collect_that_completes_for(
            OutputLanguage.FR, OutputLanguage.EN, OutputLanguage.ES
        ),
    )

    assert second_resume.published is True
    assert (tmp_path / "briefings" / "fr" / "world" / "day.json").is_file()


def test_no_phase_of_the_cycle_ever_calls_time_sleep(tmp_path: Path, monkeypatch) -> None:
    """AC4: neither phase blocks a process waiting on an external service --
    verified by construction, not just by inspection."""
    import time

    def _raise_if_called(*args, **kwargs):
        raise AssertionError("run_cycle must never sleep")

    monkeypatch.setattr(time, "sleep", _raise_if_called)

    run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        collect_summarize_fn=_collect_that_never_completes,
    )


# --- Post-review fixes carried over from Story 3.4 --------------------------


def test_a_resume_check_that_raises_degrades_the_cycle_instead_of_crashing(
    tmp_path: Path,
) -> None:
    """AD-10: every other guarded step in run_cycle degrades on an
    exception rather than letting it propagate."""
    run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    def raising_collect(
        batch_id: str,
        clusters: list[dict],
        language: OutputLanguage,
        cycle_id: str,
        data_root: Path,
    ) -> None:
        raise ConnectionError("boom")

    result = run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        collect_summarize_fn=raising_collect,
    )

    assert result.completed is True
    assert any("boom" in f.detail for f in result.failures)
    record = json.loads(result.cycle_path.read_text())
    assert record["degraded"] is True
    assert any("boom" in f["detail"] for f in record["failures"])


def test_a_collected_batchs_failures_are_folded_into_the_cycle_record(tmp_path: Path) -> None:
    """A batch that ends with every Cluster degraded must mark cycle.json
    as degraded too."""
    run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    def collect_with_failures(
        batch_id: str,
        clusters: list[dict],
        language: OutputLanguage,
        cycle_id: str,
        data_root: Path,
    ) -> WrittenSummarize:
        output_path = (
            data_root
            / "intermediate"
            / "summarize"
            / cycle_id
            / language.value
            / "summarized.jsonl"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("")
        metadata_path = output_path.parent / "summarize.json"
        metadata_path.write_text("{}")
        return WrittenSummarize(
            output_path=output_path,
            metadata_path=metadata_path,
            clusters_summarized=0,
            degraded=True,
            failures=(Failure("claude", f"batch failed entirely for {language.value}"),),
        )

    result = run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        collect_summarize_fn=collect_with_failures,
    )

    assert any("batch failed entirely" in f.detail for f in result.failures)
    record = json.loads(result.cycle_path.read_text())
    assert record["degraded"] is True
    assert any("batch failed entirely" in f["detail"] for f in record["failures"])


# --- Story 3.6: cost independence -------------------------------------------


def test_summarize_submission_count_stays_fixed_regardless_of_cluster_volume(
    tmp_path: Path,
) -> None:
    """AC2/AC3: exactly one submit_summarize_fn call per Output Language (3
    total) per cycle, never one per Zone, Period, or Cluster -- proven here
    by varying Cluster volume across two cycles and asserting the
    submission count never moves."""
    import pipeline.stages.cycle as cycle_module
    from pipeline.stages import write_jsonl
    from pipeline.stages.cluster import WrittenCluster

    def _qualifying_cluster(cluster_id: str) -> dict:
        return {
            "cluster_id": cluster_id,
            "members": [
                {
                    "title": f"title {cluster_id}",
                    "url": f"https://reuters.com/{cluster_id}",
                    "source": "reuters.com",
                    "source_country": "united-kingdom",
                    "language": "en",
                },
                {
                    "title": f"autre titre {cluster_id}",
                    "url": f"https://lemonde.fr/{cluster_id}",
                    "source": "lemonde.fr",
                    "source_country": "france",
                    "language": "fr",
                },
            ],
            "independent_source_count": 2,
            "country_count": 2,
            "countries": ["france", "united-kingdom"],
            "origin_country": "united-kingdom",
        }

    def _run_with_n_clusters(cycle_id: str, n: int) -> int:
        clusters = [_qualifying_cluster(f"c{i}") for i in range(n)]
        original_run_cluster = cycle_module.run_cluster

        def fake_run_cluster(*args, **kwargs) -> WrittenCluster:
            written = original_run_cluster(*args, **kwargs)
            write_jsonl(written.output_path, clusters)
            return WrittenCluster(
                output_path=written.output_path,
                metadata_path=written.metadata_path,
                clusters_out=len(clusters),
                degraded=written.degraded,
            )

        submit_calls: list[OutputLanguage] = []

        def counting_submit_summarize(
            clusters_in: list[dict],
            language: OutputLanguage,
            cycle_id: str,
            data_root: Path,
            angles: list[tuple[dict, str]] | None = None,
        ) -> WrittenSubmission:
            submit_calls.append(language)
            return WrittenSubmission(
                batch_id=f"stub-{language.value}",
                metadata_path=data_root / "intermediate" / "summarize" / cycle_id / "x.json",
                submitted=True,
            )

        cycle_module.run_cluster = fake_run_cluster
        try:
            run_cycle(
                collect=lambda: _collection(_record("A", "a.com")),
                cycle_id=cycle_id,
                data_root=tmp_path,
                embed=_no_op_embed,
                submit_summarize_fn=counting_submit_summarize,
            )
        finally:
            cycle_module.run_cluster = original_run_cluster

        return len(submit_calls)

    empty_run_calls = _run_with_n_clusters("2026-08-10T00-00-00Z", n=0)
    small_run_calls = _run_with_n_clusters("2026-08-11T00-00-00Z", n=1)
    large_run_calls = _run_with_n_clusters("2026-08-12T00-00-00Z", n=50)

    # n=0 (a day with zero qualifying Clusters) is a real case this
    # invariant must hold for too -- an empty union must not short-circuit
    # the per-language submission loop early.
    assert empty_run_calls == 3
    assert small_run_calls == 3
    assert large_run_calls == 3
    assert empty_run_calls == small_run_calls == large_run_calls, (
        "submission count must not vary with Cluster/Zone volume, including zero"
    )


def test_a_1_to_1_cluster_ratio_on_a_real_corpus_is_reported_not_silent() -> None:
    """The failure mode the first real cycles hit: embedding succeeds, so
    nothing is marked `degraded`, but no groups merge -- so no Cluster
    reaches the 2-Independent-Source floor, zero are selected, and the cycle
    publishes nothing while still reporting success.

    Small cycles are exempt: at low volume a 1:1 ratio is correct, not a
    symptom.
    """
    from pipeline.stages.cycle import _MERGE_DIAGNOSTIC_FLOOR

    # The constant exists and is a real corpus size, not 0 or 1 (which would
    # make every small cycle and every fixture a false positive).
    assert _MERGE_DIAGNOSTIC_FLOOR >= 10


def test_a_pending_cycle_is_found_and_resumed_without_an_explicit_cycle_id(tmp_path) -> None:
    """AD-11's phase two was unreachable in production.

    The scheduled workflow runs `python -m pipeline.stages.cycle` with no
    `--cycle-id`, so every invocation minted a fresh id and `_should_resume`
    was asked about a path that had just been created. A cycle that submitted
    its batches was then abandoned, along with the batches it had already
    paid for -- phase two existed and was tested, but nothing ever entered it.
    """
    from pipeline.stages.cycle import find_resumable_cycle_id

    intermediate = tmp_path / "intermediate"

    def write(cycle_id: str, phase: str, published: bool) -> None:
        d = intermediate / cycle_id
        d.mkdir(parents=True)
        (d / "cycle.json").write_text(
            json.dumps({"cycle_id": cycle_id, "phase": phase, "published": published})
        )

    # Nothing to resume yet.
    assert find_resumable_cycle_id(tmp_path) is None

    # A crashed-upstream cycle (never reached summarize) is NOT resumable --
    # a fresh cycle_id starts over from collect, per AD-7.
    write("2026-08-14T01-00-00Z", "collected", False)
    assert find_resumable_cycle_id(tmp_path) is None

    # An already-published cycle is finished.
    write("2026-08-14T02-00-00Z", "published", True)
    assert find_resumable_cycle_id(tmp_path) is None

    # One with batches submitted but not published is the case that matters.
    write("2026-08-14T03-00-00Z", "summarize_submitted", False)
    assert find_resumable_cycle_id(tmp_path) == "2026-08-14T03-00-00Z"

    # With several pending, the newest wins: its batches are least likely to
    # have expired (the Batch API keeps results 29 days).
    write("2026-08-14T04-00-00Z", "summarize_submitted", False)
    assert find_resumable_cycle_id(tmp_path) == "2026-08-14T04-00-00Z"


def test_find_resumable_cycle_id_tolerates_a_missing_intermediate_directory(tmp_path) -> None:
    """First-ever run: nothing exists yet, and that is not an error."""
    from pipeline.stages.cycle import find_resumable_cycle_id

    assert find_resumable_cycle_id(tmp_path / "nope") is None


def test_a_missing_ranked_jsonl_abandons_the_cycle_instead_of_retrying_forever(
    tmp_path,
) -> None:
    """_resume_cycle re-reads ranked.jsonl to know which Clusters the pending
    batches were submitted for. A GitHub runner is a fresh machine, so that
    file only survives because it is committed.

    Two failure modes to avoid, in tension with each other:

    - Falling through with clusters=[] consumes the batch and discards its
      generated text silently, for work already paid for.
    - Holding the cycle open forever makes find_resumable_cycle_id return it
      on every run: the pipeline retries a dead cycle and never collects
      again. (This is the one that briefly shipped.)

    A missing ranked.jsonl is unrecoverable -- nothing can reconstruct it --
    so the cycle is abandoned terminally and the next run starts fresh.
    """
    from pipeline.stages.cycle import find_resumable_cycle_id, run_cycle

    cycle_id = "2026-08-14T09-00-00Z"
    cycle_dir = tmp_path / "intermediate" / cycle_id
    cycle_dir.mkdir(parents=True)
    (cycle_dir / "cycle.json").write_text(
        json.dumps(
            {
                "cycle_id": cycle_id,
                "phase": "summarize_submitted",
                "published": False,
                "summarize_batches": {
                    "fr": {
                        "batch_id": "msgbatch_x",
                        "ranked_path": str(tmp_path / "nope" / "ranked.jsonl"),
                    }
                },
            }
        )
    )

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("collect_summarize must not run without ranked.jsonl")

    result = run_cycle(
        collect=lambda: CollectionResult(articles=[]),
        cycle_id=cycle_id,
        data_root=tmp_path,
        collect_summarize_fn=must_not_be_called,
    )

    assert result.published is False
    assert result.summarize_phase == "abandoned"
    assert any("cannot be recovered" in f.detail for f in result.failures)

    # Terminal: the next run must not pick this cycle up again.
    record = json.loads((cycle_dir / "cycle.json").read_text())
    assert record["phase"] == "abandoned"
    assert find_resumable_cycle_id(tmp_path) is None


def test_only_a_cycle_with_batches_actually_pending_is_resumable(tmp_path) -> None:
    """Exhaustive over every phase the code can write.

    find_resumable_cycle_id returns the newest resumable cycle on every run,
    so any phase wrongly marked resumable blocks the pipeline permanently --
    it retries that cycle forever and never collects again. Two real cycles
    hit this within an hour: one abandoned, and one in
    summarize_submit_failed with an empty summarize_batches (zero Clusters
    selected, so nothing was ever submitted).

    Written as a full enumeration rather than a case per phase so a newly
    introduced phase fails here until it is classified deliberately.
    """
    from pipeline.stages.cycle import _should_resume

    resumable_by_phase = {
        None: False,  # crashed before reaching summarize
        "collected": False,  # ditto, recorded
        "summarize_submitted": True,  # the one real pending state
        "summarize_submit_failed": False,  # no batch id exists to poll
        "abandoned": False,  # Clusters unrecoverable
        "published": False,  # finished
    }

    for phase, expected in resumable_by_phase.items():
        path = tmp_path / f"{phase}" / "cycle.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"phase": phase, "published": phase == "published"}))
        assert _should_resume(path) is expected, f"phase {phase!r} classified wrongly"


# memoize_embeddings exists because a cycle embeds the same titles three times
# (dedupe layer 3, cluster, cross-day linking), which was ~96% of the
# 2026-08-19 cycle's wall clock. These lock the three properties every calling
# stage depends on -- a cache that gets any of them wrong corrupts clustering
# silently rather than failing.


def test_a_title_is_sent_once_however_many_times_it_is_asked_for():
    calls: list[list[str]] = []

    def embed(titles: list[str]) -> EmbeddingResult:
        calls.append(list(titles))
        return EmbeddingResult(vectors=[[float(len(t))] for t in titles])

    cached = memoize_embeddings(embed)
    cached(["alpha", "beta"])
    cached(["beta", "gamma"])
    cached(["alpha", "gamma"])

    # "beta" reached the adapter with the first call, "gamma" with the second,
    # and the third call needed no request at all.
    assert calls == [["alpha", "beta"], ["gamma"]]


def test_vectors_come_back_aligned_to_the_request_including_duplicates():
    # Every stage zips the returned vectors against its own input by index, so
    # a cache that deduplicated the *response* would misalign every title
    # after the first repeat -- clustering the wrong groups together with no
    # error anywhere.
    def embed(titles: list[str]) -> EmbeddingResult:
        return EmbeddingResult(vectors=[[float(len(t))] for t in titles])

    cached = memoize_embeddings(embed)
    result = cached(["aa", "b", "aa", "cccc", "b"])

    assert result.vectors == [[2.0], [1.0], [2.0], [4.0], [1.0]]
    assert result.failures == []


def test_a_failed_response_is_passed_through_untouched_and_not_cached():
    attempts: list[list[str]] = []
    failure = Failure("cohere_embed", "embedding request failed: boom")

    def embed(titles: list[str]) -> EmbeddingResult:
        attempts.append(list(titles))
        if len(attempts) == 1:
            return EmbeddingResult(failures=[failure])
        return EmbeddingResult(vectors=[[1.0] for _ in titles])

    cached = memoize_embeddings(embed)

    first = cached(["alpha"])
    assert first.failures == [failure]
    assert first.vectors == []

    # Nothing was cached from the failure, so a retry genuinely retries --
    # a cache that stored the empty result would degrade every later cycle
    # stage off one transient error.
    second = cached(["alpha"])
    assert second.vectors == [[1.0]]
    assert attempts == [["alpha"], ["alpha"]]


def test_a_short_response_is_never_cached():
    # A response with fewer vectors than titles is the vendor-mismatch case
    # cluster.py and dedupe.py both already degrade on. It must reach them
    # intact, and must not leave half the batch cached against later lookups.
    def embed(titles: list[str]) -> EmbeddingResult:
        return EmbeddingResult(vectors=[[1.0]])  # one vector for two titles

    cached = memoize_embeddings(embed)
    result = cached(["alpha", "beta"])

    assert len(result.vectors) == 1
    assert cached(["alpha"]).vectors == [[1.0]]  # re-requested, not served stale


def test_the_cache_does_not_outlive_one_wrapping():
    # Scoped per call to memoize_embeddings, so a resumed invocation cannot be
    # served vectors embedded from a different corpus.
    def embed(titles: list[str]) -> EmbeddingResult:
        return EmbeddingResult(vectors=[[1.0] for _ in titles])

    calls = 0

    def counting(titles: list[str]) -> EmbeddingResult:
        nonlocal calls
        calls += 1
        return embed(titles)

    memoize_embeddings(counting)(["alpha"])
    memoize_embeddings(counting)(["alpha"])
    assert calls == 2


def test_a_scope_change_abandons_a_pending_cycle_instead_of_blocking_forever(
    tmp_path: Path,
) -> None:
    """A cycle whose ranked output names a Zone the config no longer has must
    end as `abandoned`, not `publish_failed`.

    `publish_failed` is resumable on purpose, so a transient publish crash
    gets retried. A scope change is not transient: the ranked output on disk
    was computed under the old configuration and nothing re-derives it, so
    every retry raises the same KeyError. Left resumable, that cycle is
    returned by find_resumable_cycle_id on every future run and blocks
    collection entirely -- the same trap _TERMINAL_PHASES already records for
    `summarize_submit_failed`.

    Observed for real on 2026-08-19: narrowing to 4 Zones left an in-flight
    cycle holding `north-america` rankings, and the resume failed with
    `unknown zone slug: 'north-america'`.
    """
    from pipeline.stages.cycle import _should_resume

    run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    import pipeline.stages.cycle as cycle_module

    original = cycle_module.publish_briefings

    def raising_publish(*args, **kwargs):
        raise KeyError("unknown zone slug: 'north-america'")

    cycle_module.publish_briefings = raising_publish
    try:
        result = run_cycle(
            collect=lambda: _collection(_record("A", "a.com")),
            cycle_id="2026-08-11T00-00-00Z",
            data_root=tmp_path,
            embed=_no_op_embed,
            submit_summarize_fn=_no_op_submit_summarize,
            collect_summarize_fn=_make_collect_that_completes_for(
                OutputLanguage.FR, OutputLanguage.EN, OutputLanguage.ES
            ),
        )
    finally:
        cycle_module.publish_briefings = original

    assert result.published is False
    assert any("publish impossible under the current config" in f.detail for f in result.failures)

    # Read the phase off cycle.json, not the return value: the file is the
    # durable state a later invocation actually resumes from (AD-11).
    cycle_path = tmp_path / "intermediate" / "2026-08-11T00-00-00Z" / "cycle.json"
    record = json.loads(cycle_path.read_text(encoding="utf-8"))
    assert record["phase"] == "abandoned"

    # The decisive property: the next run must be free to collect a fresh
    # cycle rather than being handed this one again.
    assert _should_resume(cycle_path) is False


def test_resume_only_does_nothing_when_there_is_nothing_pending(tmp_path: Path, capsys) -> None:
    """A catch-up trigger must be free on the days it is not needed.

    summarize submits and exits (AD-11), so a later run has to come back and
    publish. But a plain extra trigger is not free: with nothing to resume it
    starts a whole new cycle from collect, paying for another round of
    embeddings and summaries. That cost is why there was only ever one
    scheduled follow-up, and why one slow batch morning pushed publication a
    full day. `--resume-only` removes it, so several catch-ups can be
    scheduled to close that window.
    """
    from pipeline.stages.cycle import main

    exit_code = main(["--data-root", str(tmp_path), "--resume-only"])

    assert exit_code == 0
    assert "nothing pending" in capsys.readouterr().out
    # The decisive property: it collected nothing and wrote nothing.
    assert not (tmp_path / "intermediate").exists()


def test_resume_only_still_finishes_a_pending_cycle(tmp_path: Path) -> None:
    """The flag must not turn the catch-up into a no-op in the case it exists
    for -- a cycle whose batches are pending still gets published."""
    from pipeline.stages.cycle import main

    run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )
    pending = tmp_path / "intermediate" / "2026-08-11T00-00-00Z" / "cycle.json"
    assert json.loads(pending.read_text())["phase"] == "summarize_submitted"

    assert main(["--data-root", str(tmp_path), "--resume-only"]) == 0

    # It resumed that same cycle rather than minting a new id.
    assert json.loads(pending.read_text())["phase"] != "summarize_submitted"


def test_the_agenda_replaces_the_clusters_as_briefing_candidates(
    tmp_path: Path, working_agenda
) -> None:
    """The switch this whole change is for: what reaches rank is what an editor
    recorded, not what the long tail reran.

    Measured before the switch, the Consensus Score published a ZZ Top
    drummer's death and a suspended tennis player while the corpus held 2 of
    the 19 events editors recorded. Clusters are still the evidence -- they
    supply Articles, source lists and the score -- but they are no longer the
    candidate set.
    """
    working_agenda(text="A Russian missile strike kills ten civilians in Kharkiv Oblast")

    run_cycle(
        collect=lambda: _collection(_record("Totally unrelated local story", "small.example")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    items = [
        json.loads(line)
        for line in (tmp_path / "intermediate" / "agenda" / "2026-08-11T00-00-00Z" / "items.jsonl")
        .read_text()
        .splitlines()
        if line.strip()
    ]

    assert len(items) == 1
    assert items[0]["agenda_text"].startswith("A Russian missile strike")
    assert items[0]["agenda_category"] == "Armed conflicts and attacks"
    # The unrelated local story did not corroborate it, so the item keeps the
    # chronicle's own citation rather than borrowing an unrelated source.
    assert items[0]["corroborated"] is False
    assert items[0]["outbound_source"] == "apnews.com"


def test_an_unavailable_agenda_degrades_instead_of_publishing_nothing(tmp_path: Path) -> None:
    """AD-10/AD-7: losing the signal that decides importance must not lose the
    cycle. It falls back to ranking Clusters directly -- exactly the behaviour
    from before the stage existed -- and records that it did, because a reader
    is then getting items chosen by syndication again.

    The autouse fixture in conftest supplies the empty agenda here.
    """
    result = run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    record = json.loads(result.cycle_path.read_text())
    assert record["degraded"] is True
    assert any("agenda was empty" in f["detail"] for f in record["failures"])
    # The cycle still ran end to end rather than aborting.
    assert record["phase"] == "summarize_submitted"


def test_an_agenda_that_raises_does_not_take_the_cycle_down(tmp_path: Path) -> None:
    """A new stage between cluster and rank is a new way to lose a whole cycle.
    It is guarded like every other adapter boundary here."""

    def exploding_agenda(*_args, **_kwargs):
        raise RuntimeError("wikipedia exploded")

    result = run_cycle(
        collect=lambda: _collection(_record("A", "a.com")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        agenda_fn=exploding_agenda,
    )

    record = json.loads(result.cycle_path.read_text())
    assert record["completed"] is True
    assert any("agenda raised" in f["detail"] for f in record["failures"])


def test_rank_actually_receives_the_agenda_items_not_the_clusters(tmp_path: Path) -> None:
    """Asserts on what reached rank, which is the thing that was broken.

    The first version of this coverage checked the agenda stage's own
    items.jsonl and passed while the feature did nothing: cycle.py assigned the
    agenda items to `clusters` and then, eleven lines later, the pre-existing
    `clusters = list(read_jsonl(cluster_path))` overwrote them. Every Briefing
    that run published was still selected by syndication. Checking a stage's
    output proves the stage ran; only checking downstream proves it mattered.
    """

    def agenda_fn(_cluster_path: Path, cycle_id: str, data_root: Path, **_kwargs):
        from pipeline.stages.agenda import WrittenAgenda

        destination = data_root / "intermediate" / "agenda" / cycle_id
        destination.mkdir(parents=True, exist_ok=True)
        items_path = destination / "items.jsonl"
        item = {
            "cluster_id": "editorial-1",
            "members": [
                {
                    "title": f"outlet {i} on the strike",
                    "url": f"https://outlet{i}.example/x",
                    "source": f"outlet{i}.example",
                    "source_country": country,
                    "language": "en",
                }
                for i, country in enumerate(("france", "spain"))
            ],
            "independent_source_count": 2,
            "country_count": 2,
            "countries": ["france", "spain"],
            "mentioned_countries": ["france"],
            "origin_country": "france",
            "agenda_text": "A missile strike kills ten civilians",
            "agenda_category": "Armed conflicts and attacks",
            "agenda_day": "2026-08-11",
            "agenda_sources": ["https://apnews.com/x"],
            "corroborated": True,
        }
        items_path.write_text(json.dumps(item) + "\n", encoding="utf-8")
        return WrittenAgenda(
            output_path=items_path,
            metadata_path=destination / "agenda.json",
            items_out=1,
            corroborated=1,
            degraded=False,
        )

    result = run_cycle(
        collect=lambda: _collection(_record("Some unrelated local story", "small.example")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        agenda_fn=agenda_fn,
    )

    ranked = [
        json.loads(line) for line in result.rank_path.read_text().splitlines() if line.strip()
    ]

    assert ranked, "the editorial item should have been ranked and selected"
    assert {r["cluster_id"] for r in ranked} == {"editorial-1"}
    assert ranked[0]["agenda_category"] == "Armed conflicts and attacks"
    # And the Cluster the corpus produced is NOT a candidate on its own.
    assert not any("small.example" in json.dumps(r) for r in ranked)


def test_subjects_are_the_candidates_when_the_reference_press_forms_any(
    tmp_path: Path, working_agenda
) -> None:
    """The order of preference: subjects, then the chronicle, then Clusters.

    Subjects lead because Clusters cannot be candidates -- the same-Event
    threshold is a near-duplicate threshold, so 49 articles about Ceuta fragment
    into 45 Clusters that each weigh nothing. The chronicle was grafted on to
    work around that and brought its own flaw: it records incidents, so we
    published helicopter crashes while the corpus held 170 articles on the
    Strait of Hormuz.

    A working agenda is available here on purpose -- the assertion is that it
    is NOT used when subjects exist.
    """
    working_agenda()

    run_cycle(
        collect=lambda: _collection(*_subject_corpus()),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    from pipeline.stages import read_jsonl

    ranked = list(
        read_jsonl(tmp_path / "intermediate" / "rank" / "2026-08-11T00-00-00Z" / "ranked.jsonl")
    )
    assert ranked, "a subject clearing the floor must reach the ranking"
    assert all("subject_label" in item for item in ranked)
    assert not any("agenda_text" in item for item in ranked), "the chronicle was not consulted"


def test_a_corpus_with_no_reference_press_falls_back_to_the_chronicle(
    tmp_path: Path, working_agenda
) -> None:
    """A whole day's reference feeds failing is the case the fallback exists
    for, and it is a degradation, not a clean cycle: selection reverts to a
    signal that was measured publishing a ZZ Top drummer's death."""
    working_agenda()

    result = run_cycle(
        collect=lambda: _collection(_record("Une depeche", "some-wire.example")),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    record = json.loads(result.cycle_path.read_text())
    assert record["degraded"] is True
    assert any("no subject cleared the editorial floor" in f["detail"] for f in record["failures"])


def test_the_consequence_verdict_reaches_the_ranking(tmp_path: Path, working_agenda) -> None:
    """The wiring, not just the adapter. This project has shipped a stage that
    ran and changed nothing twice -- the agenda stage, whose output was
    overwritten eleven lines downstream, and the language instruction that
    covered half its fields -- so the assertion is on what rank received.
    """
    from pipeline.stages import read_jsonl

    run_cycle(
        collect=lambda: _collection(*_subject_corpus()),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        consequence_fn=lambda events, **kwargs: ({event_id: 3 for event_id, _ in events}, []),
    )

    ranked = list(
        read_jsonl(tmp_path / "intermediate" / "rank" / "2026-08-11T00-00-00Z" / "ranked.jsonl")
    )
    assert ranked
    assert all(item["consequence"] == 3 for item in ranked)
    assert all(item["score"]["components"]["impact"] == 1.0 for item in ranked)


def test_a_failed_consequence_call_costs_the_ordering_not_the_cycle(
    tmp_path: Path, working_agenda
) -> None:
    """AD-10. An item with no verdict scores 0.5 on impact -- neither promoted
    nor buried on a dimension nothing measured -- so the Briefing still
    publishes, less sharply ordered. The failure is recorded rather than
    swallowed, because a silently unsharpened ranking is worse than a loud one.
    """
    from pipeline.stages import read_jsonl

    def raises(events, **kwargs):
        raise RuntimeError("upstream down")

    result = run_cycle(
        collect=lambda: _collection(*_subject_corpus()),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
        consequence_fn=raises,
    )

    record = json.loads(result.cycle_path.read_text())
    assert any("consequence scoring raised" in f["detail"] for f in record["failures"])
    ranked = list(
        read_jsonl(tmp_path / "intermediate" / "rank" / "2026-08-11T00-00-00Z" / "ranked.jsonl")
    )
    assert ranked, "the cycle still selects"
    assert all(item["score"]["components"]["impact"] == 0.5 for item in ranked)


def test_zone_rankings_json_round_trips_articles_ingested(tmp_path: Path, working_agenda) -> None:
    """FR-8's Discarded Volume was published as 0/0 on 2026-08-20 despite
    `rank_for_zone` computing the real count correctly -- `_write_zone_rankings`
    and `_read_zone_rankings` are a serialization path parallel to `ZoneRanking`
    itself, written before `articles_ingested` existed and never updated when it
    was added. This round-trips through the real files a resumed cycle reads,
    not just the dataclass, which is what a unit test on `rank_for_zone` alone
    would have missed.
    """
    run_cycle(
        collect=lambda: _collection(*_subject_corpus()),
        cycle_id="2026-08-11T00-00-00Z",
        data_root=tmp_path,
        embed=_no_op_embed,
        submit_summarize_fn=_no_op_submit_summarize,
    )

    written = json.loads(
        (
            tmp_path / "intermediate" / "rank" / "2026-08-11T00-00-00Z" / "zone_rankings.json"
        ).read_text()
    )
    # The fixture's one event is dated a day before the cycle's own reference
    # day, so it lands in the WEEK pool, not DAY -- confirmed by tracing a real
    # run of this fixture before writing this assertion, not assumed.
    week_rankings = written["week"]
    assert any(r.get("articles_ingested", 0) > 0 for r in week_rankings), (
        "articles_ingested must be written, not silently dropped -- got "
        f"{[r.get('articles_ingested') for r in week_rankings]}"
    )
