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
