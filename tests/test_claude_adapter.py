"""Tests for the Claude summarization adapter.

No real network call anywhere here — the adapter takes an injectable client,
exactly like GdeltClient's injectable ``fetch`` and cohere_embed's injectable
``client``, so these tests never touch the actual Anthropic API.

Batch results are constructed out of submission order in every test that can
plausibly get this wrong — the adapter must key results by ``custom_id``,
never by position, since the real Batch API makes no ordering guarantee.

Story 3.4 split the old, poll-looping ``summarize_clusters`` into
``submit_batch`` (one call, returns a batch ID, never waits) and
``collect_batch`` (one call, checks status once, never sleeps) -- per AD-11,
"neither phase holds a process open waiting on an external service."
"""

from __future__ import annotations

import json

import pytest
from pipeline.adapters.claude import (
    _NO_FABRICATION_INSTRUCTION,
    MODEL,
    _prompt_for,
    collect_batch,
    submit_batch,
)
from pipeline.domain import OutputLanguage


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [_FakeTextBlock(text)]


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeSucceededResult:
    """A succeeded batch result.

    Story 6.1: the real API now returns a JSON object (`output_config`
    constrains it to `{headline, summary}`), not a bare paragraph. Callers
    still pass the summary text they care about; the headline is derived so
    every existing test keeps reading at its original level of detail. Pass
    `raw=` instead to inject a deliberately malformed body.
    """

    def __init__(self, text: str | None = None, *, raw: str | None = None) -> None:
        self.type = "succeeded"
        if raw is None:
            assert text is not None, "pass either text= or raw="
            raw = json.dumps(
                {
                    "headline": f"Titre: {text}",
                    "summary": text,
                    "why_it_matters": "Cela change X.",
                    "takeaway": "Le point a retenir.",
                },
                ensure_ascii=False,
            )
        self.message = _FakeMessage(raw)


class _FakeErroredResult:
    def __init__(self) -> None:
        self.type = "errored"
        self.error = _FakeError()


class _FakeError:
    def __init__(self) -> None:
        self.type = "api_error"


class _FakeBatchResult:
    def __init__(self, custom_id: str, result) -> None:
        self.custom_id = custom_id
        self.result = result


class _FakeBatch:
    def __init__(self, processing_status: str, batch_id: str = "batch_1") -> None:
        self.id = batch_id
        self.processing_status = processing_status


class _FakeBatches:
    """Records every call so tests can assert on submitted requests and on
    exactly how many times ``retrieve``/``results`` were called."""

    def __init__(
        self,
        text_by_custom_id: dict[str, str] | None = None,
        errored_custom_ids: set[str] | None = None,
        missing_custom_ids: set[str] | None = None,
        processing_status: str = "ended",
    ) -> None:
        self.create_calls: list[dict[str, object]] = []
        self.retrieve_calls = 0
        self.results_calls = 0
        self._text_by_custom_id = text_by_custom_id or {}
        self._errored_custom_ids = errored_custom_ids or set()
        self._missing_custom_ids = missing_custom_ids or set()
        self._processing_status = processing_status

    def create(self, **kwargs: object) -> _FakeBatch:
        self.create_calls.append(kwargs)
        return _FakeBatch(processing_status="in_progress")

    def retrieve(self, batch_id: str) -> _FakeBatch:
        self.retrieve_calls += 1
        return _FakeBatch(processing_status=self._processing_status, batch_id=batch_id)

    def results(self, batch_id: str) -> list[_FakeBatchResult]:
        self.results_calls += 1
        out = []
        for custom_id, text in self._text_by_custom_id.items():
            if custom_id in self._missing_custom_ids:
                continue
            if custom_id in self._errored_custom_ids:
                out.append(_FakeBatchResult(custom_id, _FakeErroredResult()))
            else:
                out.append(_FakeBatchResult(custom_id, _FakeSucceededResult(text)))
        return out


class _FakeMessages:
    def __init__(self, batches: _FakeBatches) -> None:
        self.batches = batches


class _FakeClient:
    def __init__(self, batches: _FakeBatches) -> None:
        self.messages = _FakeMessages(batches)


def _cluster(cluster_id: str, members: list[dict]) -> dict:
    return {"cluster_id": cluster_id, "members": members}


# --- submit_batch --------------------------------------------------------


def test_submit_submits_one_batch_request_per_cluster_with_custom_id() -> None:
    clusters = [
        _cluster("a", [{"title": "Ceasefire declared", "source": "lemonde.fr"}]),
        _cluster("b", [{"title": "Market rallies", "source": "cnn.com"}]),
    ]
    batches = _FakeBatches()
    client = _FakeClient(batches)

    submission = submit_batch(clusters, language=OutputLanguage.FR, client=client)

    assert not submission.failures
    assert submission.batch_id == "batch_1"
    submitted = batches.create_calls[0]["requests"]
    assert {r["custom_id"] for r in submitted} == {"a", "b"}
    # Submission never waits -- AC4: no retrieve()/results() call from
    # inside submit_batch itself.
    assert batches.retrieve_calls == 0
    assert batches.results_calls == 0


def test_submit_uses_the_configured_model() -> None:
    clusters = [_cluster("a", [{"title": "X", "source": "y.com"}])]
    batches = _FakeBatches()
    client = _FakeClient(batches)

    submit_batch(clusters, language=OutputLanguage.FR, client=client)

    submitted = batches.create_calls[0]["requests"]
    assert submitted[0]["params"]["model"] == MODEL


def test_submit_with_no_clusters_returns_no_batch_id_without_calling_create() -> None:
    batches = _FakeBatches()
    client = _FakeClient(batches)

    submission = submit_batch([], language=OutputLanguage.FR, client=client)

    assert submission.batch_id is None
    assert submission.failures == []
    assert batches.create_calls == []


def test_submit_missing_api_key_with_no_injected_client_degrades_to_a_failure(
    monkeypatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    clusters = [_cluster("a", [{"title": "X", "source": "y.com"}])]

    submission = submit_batch(clusters, language=OutputLanguage.FR)

    assert submission.batch_id is None
    assert len(submission.failures) == 1
    assert "ANTHROPIC_API_KEY" in submission.failures[0].detail


def test_submit_failure_degrades_rather_than_raising() -> None:
    class _RaisingBatches(_FakeBatches):
        def create(self, **kwargs: object) -> _FakeBatch:
            raise ConnectionError("boom")

    clusters = [_cluster("a", [{"title": "X", "source": "y.com"}])]
    client = _FakeClient(_RaisingBatches())

    submission = submit_batch(clusters, language=OutputLanguage.FR, client=client)

    assert submission.batch_id is None
    assert len(submission.failures) == 1


# --- collect_batch ---------------------------------------------------------


def test_collect_on_a_not_yet_ended_batch_makes_exactly_one_retrieve_call() -> None:
    """AC4: checking status is a single bounded call, never a poll loop --
    and never calls results() before the batch is actually ended."""
    clusters = [_cluster("a", [{"title": "X", "source": "y.com"}])]
    batches = _FakeBatches(text_by_custom_id={"a": "Texte."}, processing_status="in_progress")
    client = _FakeClient(batches)

    result = collect_batch("batch_1", clusters, client=client)

    assert result.status == "pending"
    assert result.texts == {}
    assert result.failures == []
    assert batches.retrieve_calls == 1
    assert batches.results_calls == 0


def test_collect_never_calls_time_sleep(monkeypatch) -> None:
    """Proves AC4 by construction: collect_batch contains no wait of its
    own, whether the batch is pending or ended."""
    import time

    def _raise_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("collect_batch must never sleep")

    monkeypatch.setattr(time, "sleep", _raise_if_called)

    clusters = [_cluster("a", [{"title": "X", "source": "y.com"}])]
    pending = _FakeBatches(text_by_custom_id={"a": "Texte."}, processing_status="in_progress")
    ended = _FakeBatches(text_by_custom_id={"a": "Texte."}, processing_status="ended")

    collect_batch("batch_1", clusters, client=_FakeClient(pending))
    collect_batch("batch_1", clusters, client=_FakeClient(ended))


def test_collect_on_an_ended_batch_reassociates_results_by_custom_id_not_position() -> None:
    """The fake deliberately returns results out of submission order --
    a real Batch API call makes no positional guarantee, and an adapter that
    assumed one would silently misattribute a summary to the wrong Cluster."""
    clusters = [
        _cluster("first", [{"title": "First event", "source": "a.com"}]),
        _cluster("second", [{"title": "Second event", "source": "b.com"}]),
    ]
    # dict insertion order below is reversed relative to `clusters` above;
    # _FakeBatches.results() yields in this (reversed) order.
    batches = _FakeBatches(
        text_by_custom_id={"second": "Deuxieme resume.", "first": "Premier resume."}
    )
    client = _FakeClient(batches)

    result = collect_batch("batch_1", clusters, client=client)

    assert result.status == "ended"
    assert result.texts["first"].summary == "Premier resume."
    assert result.texts["first"].headline == "Titre: Premier resume."
    assert result.texts["second"].summary == "Deuxieme resume."


def test_collect_an_errored_result_is_reported_as_a_failure_scoped_to_its_cluster() -> None:
    clusters = [
        _cluster("ok", [{"title": "Fine event", "source": "a.com"}]),
        _cluster("bad", [{"title": "Broken event", "source": "b.com"}]),
    ]
    batches = _FakeBatches(
        text_by_custom_id={"ok": "Ca va.", "bad": "n/a"},
        errored_custom_ids={"bad"},
    )
    client = _FakeClient(batches)

    result = collect_batch("batch_1", clusters, client=client)

    assert list(result.texts) == ["ok"]
    assert result.texts["ok"].summary == "Ca va."
    assert len(result.failures) == 1
    assert "bad" in result.failures[0].detail


def test_collect_a_custom_id_missing_from_results_is_reported_as_a_failure_not_a_crash() -> None:
    """Should not happen per the Batch API's own contract, but the adapter
    must degrade rather than raise (or silently drop the Cluster) if it does."""
    clusters = [
        _cluster("present", [{"title": "Present event", "source": "a.com"}]),
        _cluster("vanished", [{"title": "Vanished event", "source": "b.com"}]),
    ]
    batches = _FakeBatches(
        text_by_custom_id={"present": "Ok.", "vanished": "n/a"},
        missing_custom_ids={"vanished"},
    )
    client = _FakeClient(batches)

    result = collect_batch("batch_1", clusters, client=client)

    assert list(result.texts) == ["present"]
    assert result.texts["present"].summary == "Ok."
    assert len(result.failures) == 1
    assert "vanished" in result.failures[0].detail


def test_collect_a_failure_while_iterating_results_does_not_discard_already_collected() -> None:
    """A transient failure partway through iterating results() (e.g. a
    network blip) must not throw away summaries already collected earlier
    in the same iteration -- that would silently regress every one of those
    Clusters to a degrade, contradicting this module's own claim that a
    failure degrades only the affected Cluster."""

    class _RaisingBatches(_FakeBatches):
        def results(self, batch_id: str):
            yield _FakeBatchResult("a", _FakeSucceededResult("Resume A."))
            raise ConnectionError("boom, mid-stream")

    clusters = [
        _cluster("a", [{"title": "First event", "source": "a.com"}]),
        _cluster("b", [{"title": "Second event", "source": "b.com"}]),
    ]
    batches = _RaisingBatches()
    client = _FakeClient(batches)

    result = collect_batch("batch_1", clusters, client=client)

    assert result.status == "ended"
    assert list(result.texts) == ["a"]
    assert result.texts["a"].summary == "Resume A."
    assert any("b" in f.detail for f in result.failures)


def test_collect_missing_api_key_with_no_injected_client_degrades_to_a_failure(
    monkeypatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    clusters = [_cluster("a", [{"title": "X", "source": "y.com"}])]

    result = collect_batch("batch_1", clusters)

    assert result.status == "ended"  # nothing to poll for -- fails immediately
    assert result.texts == {}
    assert len(result.failures) == 1
    assert "ANTHROPIC_API_KEY" in result.failures[0].detail


# --- _prompt_for (language naming, unaffected by the submit/collect split) -


def test_the_prompt_names_the_language_not_the_bare_code() -> None:
    """Claude needs a natural-language instruction ("French"), not a bare
    ISO code ("fr") -- "Write ... in fr, summarizing ..." is not a sentence
    an instruction-following model should be expected to parse correctly."""
    cluster = _cluster("a", [{"title": "Un evenement", "source": "lemonde.fr"}])

    for language, name in (
        (OutputLanguage.FR, "French"),
        (OutputLanguage.EN, "English"),
        (OutputLanguage.ES, "Spanish"),
    ):
        prompt = _prompt_for(cluster, language)
        assert name in prompt
        assert f", in {language.value}," not in prompt  # never the bare code
        for other_name in ("French", "English", "Spanish"):
            if other_name != name:
                assert other_name not in prompt


def test_the_language_instruction_binds_every_field_the_schema_requires() -> None:
    """The instruction used to enumerate the fields it applied to -- "a headline
    and one short paragraph, both in French" -- written when the schema had
    exactly those two. Extending it to four left that sentence covering half of
    them, and the French Briefing published a Spanish headline above a French
    summary on 2026-08-20 for an item about a Spanish jet. The same batch's `en`
    and `es` items were both correct, so nothing was crossed: the model followed
    the subject's language where the instruction had stopped binding.

    Asserting on the phrasing rather than on a field list is the point -- a
    prompt that names fields can be narrowed by adding one, which is exactly
    what happened. Derived from `_SUMMARY_SCHEMA` so a newly added field cannot
    escape this test.
    """
    from pipeline.adapters.claude import _SUMMARY_SCHEMA

    required = _SUMMARY_SCHEMA["required"]
    assert required, "the schema must require at least one field to bind"

    for cluster in (
        _cluster("a", [{"title": "Un evenement", "source": "lemonde.fr"}]),
        # The agenda-only branch is a separate prompt string and was missing
        # the same coverage.
        {"cluster_id": "b", "members": [], "agenda_text": "Something happened."},
    ):
        prompt = _prompt_for(cluster, OutputLanguage.FR)
        assert "Write every field in French" in prompt
        # No enumeration that a new field could fall outside of.
        assert "both in French" not in prompt


def test_the_language_instruction_survives_a_subject_in_another_language() -> None:
    """The published failure was an item about Spain, so the instruction names
    that case rather than leaving the model to infer it."""
    cluster = _cluster("a", [{"title": "Un avion espanol", "source": "elpais.com"}])

    prompt = _prompt_for(cluster, OutputLanguage.FR)

    assert "regardless of the language of the Articles" in prompt
    assert "an event in Spain is still reported in French" in prompt


def test_the_same_member_data_is_embedded_regardless_of_target_language() -> None:
    """The facts available to ground a Summary must not vary by language --
    only the language of the resulting prose should differ."""
    cluster = _cluster(
        "a",
        [
            {"title": "Ceasefire declared", "source": "lemonde.fr"},
            {"title": "Market rallies", "source": "cnn.com"},
        ],
    )

    prompts = [
        _prompt_for(cluster, language)
        for language in (OutputLanguage.FR, OutputLanguage.EN, OutputLanguage.ES)
    ]
    for prompt in prompts:
        assert "Ceasefire declared" in prompt
        assert "lemonde.fr" in prompt
        assert "Market rallies" in prompt
        assert "cnn.com" in prompt


def test_non_latin_script_titles_pass_through_unchanged_for_every_language() -> None:
    """The model does the translation -- this adapter must not attempt to
    transliterate, filter, or otherwise preprocess non-Latin-script text."""
    cluster = _cluster(
        "a",
        [{"title": "停戦が宣言された", "source": "asahi.com", "source_country": "japan"}],
    )

    for language in (OutputLanguage.FR, OutputLanguage.EN, OutputLanguage.ES):
        prompt = _prompt_for(cluster, language)
        assert "停戦が宣言された" in prompt


def test_an_unsupported_language_raises_rather_than_silently_falling_back() -> None:
    """_LANGUAGE_NAMES is deliberately small and explicit (same reasoning as
    resolve_wire_agency's wire-service table) -- a value with no mapped name
    must raise, not silently produce a prompt with no language instruction
    or a wrong one. This is the module's only actual runtime enforcement of
    "one of the three supported languages" (OutputLanguage's typing alone
    does not stop a bare matching string, since it's a StrEnum)."""
    cluster = _cluster("a", [{"title": "X", "source": "y.com"}])

    with pytest.raises(KeyError):
        _prompt_for(cluster, "de")  # a real ISO code, but not a supported one


def test_the_prompt_includes_the_no_fabrication_instruction_for_every_language() -> None:
    """Story 4.6 AC2: no synthesized statement may be attributed to a named
    outlet. The site cannot enforce this at render time -- cluster.summary
    is free text the AI generates, and there is no structured signal to
    check it against -- so the only real lever is this prompt instruction.
    This test proves the instruction actually reaches every prompt, not
    that the model obeys it: an LLM's compliance with an instruction is not
    something a unit test can verify (see this story's own Dev Notes on
    why a runtime content-scan was considered and rejected)."""
    cluster = _cluster("a", [{"title": "Un evenement", "source": "lemonde.fr"}])

    for language in (OutputLanguage.FR, OutputLanguage.EN, OutputLanguage.ES):
        prompt = _prompt_for(cluster, language)
        assert _NO_FABRICATION_INSTRUCTION in prompt


def test_the_no_fabrication_instruction_explicitly_names_the_outlet_attribution_case() -> None:
    """Guards against the instruction's own wording drifting away from
    AC2's exact scenario in a future edit -- if this instruction is ever
    changed to a generic anti-hallucination clause that drops the
    outlet-attribution wording, this test (not just a passing prompt-
    inclusion check) should be the one to catch it."""
    assert "named outlet" in _NO_FABRICATION_INSTRUCTION
    assert "reports that" in _NO_FABRICATION_INSTRUCTION


# --- Story 6.1: structured-output parsing and its degrade paths -----------


def test_the_prompt_asks_for_a_headline_and_holds_it_to_the_same_rules() -> None:
    """FR-13 as extended by Story 6.1: the headline is held to the same
    non-fabrication rule as the Summary, and to PRD section 7's register
    ("no urgency, no teasers, no 'breaking'") -- a generated headline is
    exactly where clickbait would enter this product."""
    cluster = _cluster("a", [{"title": "Un evenement", "source": "lemonde.fr"}])

    prompt = _prompt_for(cluster, OutputLanguage.FR)

    assert "headline" in prompt
    # The anti-fabrication instruction still applies to the whole response,
    # headline included -- not weakened to cover only the paragraph.
    assert _NO_FABRICATION_INSTRUCTION in prompt
    # The register constraints, stated explicitly rather than left to the
    # model's defaults.
    assert "no teasers" in prompt
    assert "no 'breaking'" in prompt


def test_submit_constrains_the_response_to_the_headline_summary_schema() -> None:
    """The shape is a guarantee, not a request: every field required and
    additionalProperties false."""
    clusters = [_cluster("a", [{"title": "X", "source": "y.com"}])]
    batches = _FakeBatches()
    client = _FakeClient(batches)

    submit_batch(clusters, language=OutputLanguage.FR, client=client)

    params = batches.create_calls[0]["requests"][0]["params"]
    schema = params["output_config"]["format"]["schema"]
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert set(schema["required"]) == {"headline", "summary"}
    assert schema["additionalProperties"] is False


def test_collect_a_truncated_or_refused_response_degrades_that_cluster_only() -> None:
    """`output_config` guarantees the shape only when the response completes
    normally -- a truncated response (max_tokens) and a safety refusal both
    produce text that is not a valid object. That degrades one Cluster, not
    the batch."""
    batches = _FakeBatches(text_by_custom_id={"ok": "Ca va.", "truncated": "n/a"})

    # Replace the truncated one's body with a half-written JSON object,
    # exactly what a max_tokens cutoff produces.
    def results(batch_id: str):
        return [
            _FakeBatchResult("ok", _FakeSucceededResult("Ca va.")),
            _FakeBatchResult(
                "truncated", _FakeSucceededResult(raw='{"headline": "Un titre", "sum')
            ),
        ]

    batches.results = results  # type: ignore[method-assign]
    client = _FakeClient(batches)

    result = collect_batch(
        "batch_1",
        [_cluster("ok", []), _cluster("truncated", [])],
        client=client,
    )

    assert result.status == "ended"
    assert list(result.texts) == ["ok"]  # the good one survives
    assert len(result.failures) == 1
    assert "truncated" in result.failures[0].detail
    assert "not valid JSON" in result.failures[0].detail


def test_collect_an_empty_headline_is_rejected_rather_than_rendered_blank() -> None:
    """An empty string satisfies {"type": "string"}, so the schema alone
    does not stop a blank heading reaching the page."""
    batches = _FakeBatches()

    def results(batch_id: str):
        return [
            _FakeBatchResult(
                "blank",
                _FakeSucceededResult(
                    raw=(
                        '{"headline": "   ", "summary": "Un resume.",'
                        ' "why_it_matters": "X.", "takeaway": "Y."}'
                    )
                ),
            )
        ]

    batches.results = results  # type: ignore[method-assign]
    client = _FakeClient(batches)

    result = collect_batch("batch_1", [_cluster("blank", [])], client=client)

    assert result.texts == {}
    assert len(result.failures) == 1
    assert "'headline'" in result.failures[0].detail


def test_collect_strips_surrounding_whitespace_from_both_fields() -> None:
    batches = _FakeBatches()

    def results(batch_id: str):
        return [
            _FakeBatchResult(
                "a",
                _FakeSucceededResult(
                    raw=(
                        '{"headline": "  Un titre  ", "summary": " Un resume. ",'
                        ' "why_it_matters": " Cela change X. ", "takeaway": " Le point. "}'
                    )
                ),
            )
        ]

    batches.results = results  # type: ignore[method-assign]
    client = _FakeClient(batches)

    result = collect_batch("batch_1", [_cluster("a", [])], client=client)

    assert result.texts["a"].headline == "Un titre"
    assert result.texts["a"].summary == "Un resume."


# --- score_consequence -------------------------------------------------------


class _StubMessages:
    """Records what it was asked and answers with whatever was queued."""

    def __init__(self, replies: list[object]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.max_tokens: list[int] = []

    def create(self, **kwargs):  # noqa: ANN003, ANN201
        self.prompts.append(kwargs["messages"][0]["content"])
        self.max_tokens.append(kwargs["max_tokens"])
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class _StubClient:
    def __init__(self, replies: list[object]) -> None:
        self.messages = _StubMessages(replies)


def _reply(payload: dict):  # noqa: ANN202
    class _Part:
        type = "text"
        text = json.dumps(payload)

    class _Response:
        content = [_Part()]

    return _Response()


def test_the_prompt_uses_short_ids_and_maps_them_back() -> None:
    """A cluster_id is a slug plus a twelve-hex digest, and repeating fifty of
    them costs more output tokens than the verdicts do -- which is what
    truncated the first working version, reported as "Unterminated string". It
    also removes the hallucinated-id risk: an invented id resolves to nothing.
    """
    from pipeline.adapters.claude import score_consequence

    client = _StubClient([_reply({"verdicts": [{"id": "e0", "consequence": 3}]})])

    verdicts, failures = score_consequence(
        [("subject-ceuta-0123456789ab", "Ceuta : bras de fer avec l'UE")], client=client
    )

    assert failures == []
    assert verdicts == {"subject-ceuta-0123456789ab": 3}
    assert "subject-ceuta-0123456789ab" not in client.messages.prompts[0]
    assert "e0:" in client.messages.prompts[0]


def test_an_invented_id_is_dropped_rather_than_attached_to_another_event() -> None:
    from pipeline.adapters.claude import score_consequence

    client = _StubClient(
        [
            _reply(
                {
                    "verdicts": [
                        {"id": "e0", "consequence": 2},
                        {"id": "e99", "consequence": 3},
                    ]
                }
            )
        ]
    )

    verdicts, _ = score_consequence([("real", "Un titre")], client=client)

    assert verdicts == {"real": 2}


def test_a_verdict_outside_the_scale_is_dropped() -> None:
    """The output schema cannot express a range -- structured output rejects
    `minimum`/`maximum` on an integer -- so it is checked here instead. An
    out-of-range value would otherwise scale past 1.0 in `_impact`."""
    from pipeline.adapters.claude import score_consequence

    client = _StubClient([_reply({"verdicts": [{"id": "e0", "consequence": 9}]})])

    verdicts, _ = score_consequence([("real", "Un titre")], client=client)

    assert verdicts == {}


def test_the_output_budget_is_sized_from_the_batch_not_from_a_summary() -> None:
    """`MAX_TOKENS` is sized for one summary and truncated the JSON mid-string,
    losing 50 of 53 verdicts."""
    from pipeline.adapters.claude import (
        CONSEQUENCE_BATCH,
        MAX_TOKENS,
        score_consequence,
    )

    client = _StubClient([_reply({"verdicts": []})])
    score_consequence([("a", "x")], client=client)

    assert client.messages.max_tokens[0] > MAX_TOKENS
    assert client.messages.max_tokens[0] >= 24 * CONSEQUENCE_BATCH


def test_one_failed_chunk_does_not_lose_the_others() -> None:
    """AD-10 at the chunk level: fifty candidates are several calls, and one
    transient error must not discard the verdicts the rest returned."""
    from pipeline.adapters.claude import CONSEQUENCE_BATCH, score_consequence

    events = [(f"id{position}", f"Titre {position}") for position in range(CONSEQUENCE_BATCH + 1)]
    client = _StubClient(
        [RuntimeError("upstream down"), _reply({"verdicts": [{"id": "e0", "consequence": 1}]})]
    )

    verdicts, failures = score_consequence(events, client=client)

    assert len(failures) == 1
    assert verdicts == {f"id{CONSEQUENCE_BATCH}": 1}


def test_the_prompt_says_outright_that_coverage_is_not_the_question() -> None:
    """The confusion this scoring exists to fix: nine reference newsrooms put
    Harry and Meghan's return on their front pages, so every other signal ranked
    it above Evergrande, Trump's threats against Iran and Israel's admission over
    Hind Rajab. Coverage is measured elsewhere."""
    from pipeline.adapters.claude import _consequence_prompt

    prompt = _consequence_prompt([("e0", "Un titre")])

    assert "NOT the question" in prompt
    assert "celebrity and royal lives" in prompt


def test_the_language_instruction_is_the_last_thing_the_prompt_says() -> None:
    """Position, not just presence.

    It was the second line of the facts prompt, and the French Briefing published
    "La Comunidad de Madrid reconoce que algunos hospitales publicos no garantizan
    el aborto" as its headline AND summary -- the instruction was too far from
    the end for the model to still be following it.

    That is a hypothesis about recency rather than a proven cause -- but the
    position was arbitrary to begin with, so pinning it costs nothing and stops
    it drifting back. Asserted on all three prompts, including the agenda-only
    branch, which was missing the instruction entirely once already.
    """
    from pipeline.adapters.claude import _language_instruction, _prompt_for

    expected = _language_instruction("French")
    spanish_sources = {
        "members": [
            {
                "title": "La Comunidad de Madrid reconoce",
                "source": "elpais.com",
                "source_country": "spain",
                "language": "es",
                "url": "u",
            }
        ]
    }
    agenda_only = {"cluster_id": "x", "members": [], "agenda_text": "Something happened."}

    for prompt in (
        _prompt_for(spanish_sources, OutputLanguage.FR),
        _prompt_for(agenda_only, OutputLanguage.FR),
    ):
        assert prompt.rstrip().endswith(expected.rstrip()), prompt[-120:]
