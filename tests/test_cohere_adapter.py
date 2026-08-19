"""Tests for the Cohere embedding adapter.

No real network call anywhere here — the adapter takes an injectable client
factory, exactly like GdeltClient's injectable ``fetch``, so these tests never
touch the actual Cohere API.
"""

from __future__ import annotations

from pipeline.adapters.cohere_embed import (
    EMBEDDING_DIMENSION,
    MAX_TEXTS_PER_REQUEST,
    embed_titles,
)


class _FakeEmbeddings:
    def __init__(self, float_: list[list[float]]) -> None:
        self.float_ = float_


class _FakeResponse:
    def __init__(self, float_: list[list[float]]) -> None:
        self.embeddings = _FakeEmbeddings(float_)


class _FakeClient:
    """Records every call so tests can assert on batching and parameters."""

    def __init__(self, vector_for: dict[str, list[float]] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._vector_for = vector_for or {}

    def embed(self, **kwargs: object) -> _FakeResponse:
        self.calls.append(kwargs)
        texts = kwargs["texts"]
        vectors = [self._vector_for.get(t, [0.1, 0.2, 0.3]) for t in texts]
        return _FakeResponse(vectors)


def test_embeds_titles_in_input_order() -> None:
    client = _FakeClient({"a": [1.0, 0.0], "b": [0.0, 1.0]})
    result = embed_titles(["a", "b"], client=client)

    assert result.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert result.failures == []


def test_uses_the_clustering_input_type() -> None:
    """input_type="clustering" is mandatory: any other value silently degrades
    quality with no error, which is exactly the kind of bug that never shows
    up in a test unless the test pins the parameter."""
    client = _FakeClient()
    embed_titles(["a"], client=client)

    assert client.calls[0]["input_type"] == "clustering"
    assert client.calls[0]["embedding_types"] == ["float"]
    assert client.calls[0]["model"] == "embed-v4.0"
    assert client.calls[0]["output_dimension"] == EMBEDDING_DIMENSION


def test_chunks_requests_at_the_batch_cap() -> None:
    titles = [f"title-{i}" for i in range(MAX_TEXTS_PER_REQUEST + 5)]
    client = _FakeClient()
    result = embed_titles(titles, client=client)

    assert len(client.calls) == 2
    assert len(client.calls[0]["texts"]) == MAX_TEXTS_PER_REQUEST
    assert len(client.calls[1]["texts"]) == 5
    assert len(result.vectors) == len(titles)


def test_empty_input_makes_no_call() -> None:
    client = _FakeClient()
    result = embed_titles([], client=client)

    assert result.vectors == []
    assert client.calls == []


def test_a_raising_client_produces_a_failure_not_an_exception() -> None:
    """Adapters never raise past their own boundary (AD-10)."""

    class _BrokenClient:
        def embed(self, **kwargs: object) -> _FakeResponse:
            raise RuntimeError("network exploded")

    result = embed_titles(["a", "b"], client=_BrokenClient())

    assert result.vectors == []
    assert len(result.failures) == 1
    assert "network exploded" in result.failures[0].detail


def test_missing_api_key_is_a_failure_not_a_crash(monkeypatch) -> None:
    monkeypatch.delenv("COHERE_API_KEY", raising=False)

    result = embed_titles(["a"])

    assert result.vectors == []
    assert len(result.failures) == 1
    assert "COHERE_API_KEY" in result.failures[0].detail


def test_no_spacing_is_applied_by_default() -> None:
    """The production key needs none, and the default reflects that.

    Measured 2026-08-19 on the production key with no spacing: 60 consecutive
    batches in 36.5s, then 115 in 57.7s, zero 429s. The 0.79s that used to sit
    between batches was derived from the *trial* key's 100,000 tokens/minute
    ceiling and cost ~81s per cycle once Story 6.2's corpus made a cycle ~100
    batches wide.

    Asserts on the sleeps rather than wall-clock, so the test stays fast and
    never depends on real sleeping.
    """
    from pipeline.adapters import cohere_embed

    slept: list[float] = []
    original = cohere_embed.time.sleep
    cohere_embed.time.sleep = slept.append
    try:
        cohere_embed.embed_titles(
            [f"title {i}" for i in range(cohere_embed.MAX_TEXTS_PER_REQUEST * 3)],
            client=_FakeClient(),
        )
    finally:
        cohere_embed.time.sleep = original

    assert slept == []


def test_the_pacing_mechanism_still_works_when_an_interval_is_set() -> None:
    """Kept working, not deleted, because the ceiling it defends against is
    real and undocumented: Cohere's public rate-limit page gives two different
    Embed numbers, and `embed_titles` is all-or-nothing, so one 429 costs the
    whole cycle its cross-language merging. Restoring protection must be a
    one-constant change, which only holds if the path stays exercised."""
    from pipeline.adapters import cohere_embed

    slept: list[float] = []
    original_sleep = cohere_embed.time.sleep
    original_interval = cohere_embed.REQUEST_INTERVAL_SECONDS
    cohere_embed.time.sleep = slept.append
    cohere_embed.REQUEST_INTERVAL_SECONDS = cohere_embed.TRIAL_KEY_INTERVAL_SECONDS
    try:
        cohere_embed.embed_titles(
            [f"title {i}" for i in range(cohere_embed.MAX_TEXTS_PER_REQUEST * 3)],
            client=_FakeClient(),
        )
    finally:
        cohere_embed.time.sleep = original_sleep
        cohere_embed.REQUEST_INTERVAL_SECONDS = original_interval

    # Three batches means two waits: the first never waits, and no wait trails
    # the last one.
    assert len(slept) == 2
    assert all(s == cohere_embed.TRIAL_KEY_INTERVAL_SECONDS for s in slept)


def test_pacing_can_be_disabled_for_tests_and_small_runs() -> None:
    from pipeline.adapters import cohere_embed

    slept: list[float] = []
    original = cohere_embed.time.sleep
    cohere_embed.time.sleep = slept.append
    try:
        cohere_embed.embed_titles(
            [f"title {i}" for i in range(cohere_embed.MAX_TEXTS_PER_REQUEST * 3)],
            client=_FakeClient(),
            pace=False,
        )
    finally:
        cohere_embed.time.sleep = original

    assert slept == []


def test_the_preserved_trial_interval_still_respects_the_trial_limit() -> None:
    """Guards the arithmetic, not just its result: if any constant is edited,
    the trial-key interval must still keep a full minute of batches inside the
    trial token budget, so falling back to it remains a real fix rather than a
    number that only looks like one."""
    from pipeline.adapters import cohere_embed

    batches_per_minute = 60 / cohere_embed.TRIAL_KEY_INTERVAL_SECONDS
    tokens_per_minute = (
        batches_per_minute
        * cohere_embed.MAX_TEXTS_PER_REQUEST
        * cohere_embed.ESTIMATED_TOKENS_PER_TEXT
    )

    assert tokens_per_minute <= cohere_embed.TOKENS_PER_MINUTE
