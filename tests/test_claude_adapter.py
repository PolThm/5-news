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

import pytest
from pipeline.adapters.claude import (
    MODEL,
    _NO_FABRICATION_INSTRUCTION,
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
    def __init__(self, text: str) -> None:
        self.type = "succeeded"
        self.message = _FakeMessage(text)


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
    assert result.summaries == {}
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
    assert result.summaries["first"] == "Premier resume."
    assert result.summaries["second"] == "Deuxieme resume."


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

    assert result.summaries == {"ok": "Ca va."}
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

    assert result.summaries == {"present": "Ok."}
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
    assert result.summaries == {"a": "Resume A."}
    assert any("b" in f.detail for f in result.failures)


def test_collect_missing_api_key_with_no_injected_client_degrades_to_a_failure(
    monkeypatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    clusters = [_cluster("a", [{"title": "X", "source": "y.com"}])]

    result = collect_batch("batch_1", clusters)

    assert result.status == "ended"  # nothing to poll for -- fails immediately
    assert result.summaries == {}
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
