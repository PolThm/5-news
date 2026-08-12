"""Tests for the Claude summarization adapter.

No real network call anywhere here — the adapter takes an injectable client,
exactly like GdeltClient's injectable ``fetch`` and cohere_embed's injectable
``client``, so these tests never touch the actual Anthropic API.

Batch results are constructed out of submission order in every test that can
plausibly get this wrong — the adapter must key results by ``custom_id``,
never by position, since the real Batch API makes no ordering guarantee.
"""

from __future__ import annotations

import pytest
from pipeline.adapters.claude import MODEL, _prompt_for, summarize_clusters
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
    """Records every call so tests can assert on submitted requests and
    control how many polls occur before the batch reports ``ended``."""

    def __init__(
        self,
        text_by_custom_id: dict[str, str] | None = None,
        errored_custom_ids: set[str] | None = None,
        missing_custom_ids: set[str] | None = None,
        polls_before_ended: int = 0,
    ) -> None:
        self.create_calls: list[dict[str, object]] = []
        self.retrieve_calls = 0
        self._text_by_custom_id = text_by_custom_id or {}
        self._errored_custom_ids = errored_custom_ids or set()
        self._missing_custom_ids = missing_custom_ids or set()
        self._polls_before_ended = polls_before_ended

    def create(self, **kwargs: object) -> _FakeBatch:
        self.create_calls.append(kwargs)
        return _FakeBatch(processing_status="in_progress")

    def retrieve(self, batch_id: str) -> _FakeBatch:
        self.retrieve_calls += 1
        if self.retrieve_calls > self._polls_before_ended:
            return _FakeBatch(processing_status="ended", batch_id=batch_id)
        return _FakeBatch(processing_status="in_progress", batch_id=batch_id)

    def results(self, batch_id: str) -> list[_FakeBatchResult]:
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


def test_submits_one_batch_request_per_cluster_with_custom_id() -> None:
    clusters = [
        _cluster("a", [{"title": "Ceasefire declared", "source": "lemonde.fr"}]),
        _cluster("b", [{"title": "Market rallies", "source": "cnn.com"}]),
    ]
    text_by_custom_id = {"a": "Un cessez-le-feu.", "b": "Les marches montent."}
    batches = _FakeBatches(text_by_custom_id=text_by_custom_id)
    client = _FakeClient(batches)

    result = summarize_clusters(
        clusters, language=OutputLanguage.FR, client=client, poll_interval_seconds=0
    )

    assert not result.failures
    assert result.summaries == text_by_custom_id

    submitted = batches.create_calls[0]["requests"]
    assert {r["custom_id"] for r in submitted} == {"a", "b"}


def test_uses_the_configured_model() -> None:
    clusters = [_cluster("a", [{"title": "X", "source": "y.com"}])]
    batches = _FakeBatches(text_by_custom_id={"a": "Texte."})
    client = _FakeClient(batches)

    summarize_clusters(clusters, language=OutputLanguage.FR, client=client, poll_interval_seconds=0)

    submitted = batches.create_calls[0]["requests"]
    assert submitted[0]["params"]["model"] == MODEL


def test_results_are_reassociated_by_custom_id_not_position() -> None:
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

    result = summarize_clusters(
        clusters, language=OutputLanguage.FR, client=client, poll_interval_seconds=0
    )

    assert result.summaries["first"] == "Premier resume."
    assert result.summaries["second"] == "Deuxieme resume."


def test_an_errored_result_is_reported_as_a_failure_scoped_to_its_cluster() -> None:
    clusters = [
        _cluster("ok", [{"title": "Fine event", "source": "a.com"}]),
        _cluster("bad", [{"title": "Broken event", "source": "b.com"}]),
    ]
    batches = _FakeBatches(
        text_by_custom_id={"ok": "Ca va.", "bad": "n/a"},
        errored_custom_ids={"bad"},
    )
    client = _FakeClient(batches)

    result = summarize_clusters(
        clusters, language=OutputLanguage.FR, client=client, poll_interval_seconds=0
    )

    assert result.summaries == {"ok": "Ca va."}
    assert len(result.failures) == 1
    assert "bad" in result.failures[0].detail


def test_a_custom_id_missing_from_results_is_reported_as_a_failure_not_a_crash() -> None:
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

    result = summarize_clusters(
        clusters, language=OutputLanguage.FR, client=client, poll_interval_seconds=0
    )

    assert result.summaries == {"present": "Ok."}
    assert len(result.failures) == 1
    assert "vanished" in result.failures[0].detail


def test_polls_until_the_batch_reports_ended() -> None:
    clusters = [_cluster("a", [{"title": "X", "source": "y.com"}])]
    batches = _FakeBatches(text_by_custom_id={"a": "Texte."}, polls_before_ended=3)
    client = _FakeClient(batches)

    result = summarize_clusters(
        clusters, language=OutputLanguage.FR, client=client, poll_interval_seconds=0
    )

    assert batches.retrieve_calls == 4  # 3 in-progress polls, then the ended one
    assert result.summaries == {"a": "Texte."}


def test_a_failure_while_iterating_results_does_not_discard_already_collected_summaries() -> None:
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

    result = summarize_clusters(
        clusters, language=OutputLanguage.FR, client=client, poll_interval_seconds=0
    )

    assert result.summaries == {"a": "Resume A."}
    assert any("b" in f.detail for f in result.failures)


def test_a_batch_that_never_reaches_ended_degrades_instead_of_hanging_forever() -> None:
    """No maximum poll count previously existed -- a stuck batch (vendor
    incident, permanently wedged job) would block this call, and therefore
    the whole cycle, forever."""
    clusters = [_cluster("a", [{"title": "X", "source": "y.com"}])]
    batches = _FakeBatches(text_by_custom_id={"a": "Texte."}, polls_before_ended=10_000)
    client = _FakeClient(batches)

    result = summarize_clusters(
        clusters,
        language=OutputLanguage.FR,
        client=client,
        poll_interval_seconds=0,
        max_poll_attempts=5,
    )

    assert result.summaries == {}
    assert len(result.failures) == 1
    assert "did not complete" in result.failures[0].detail.lower()
    assert batches.retrieve_calls == 4  # capped at max_poll_attempts - 1 retrieves before giving up


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


def test_no_clusters_returns_empty_without_submitting_a_batch() -> None:
    batches = _FakeBatches()
    client = _FakeClient(batches)

    result = summarize_clusters(
        [], language=OutputLanguage.FR, client=client, poll_interval_seconds=0
    )

    assert result.summaries == {}
    assert result.failures == []
    assert batches.create_calls == []


def test_missing_api_key_with_no_injected_client_degrades_to_a_failure(
    monkeypatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    clusters = [_cluster("a", [{"title": "X", "source": "y.com"}])]

    result = summarize_clusters(clusters, language=OutputLanguage.FR)

    assert result.summaries == {}
    assert len(result.failures) == 1
    assert "ANTHROPIC_API_KEY" in result.failures[0].detail
