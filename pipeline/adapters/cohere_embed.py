"""Cohere embed-v4 adapter: turns titles into vectors for cross-language
clustering.

A French and a Japanese headline about the same event share no words. The
cluster stage groups on semantic similarity instead of text similarity, and
that similarity has to come from somewhere outside this pipeline — this
adapter is where the vendor call for it lives, so the cluster stage never
imports ``cohere`` or sees a Cohere response object (AD-13).

Isolated on purpose: an injectable ``client`` (mirroring GdeltClient's
injectable ``fetch``) keeps every test here network-free, and never raising
past this module's boundary (AD-10) means an embedding outage degrades a
cycle's clustering rather than crashing it.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from pipeline.adapters import Failure
from pipeline.stages import trace

ADAPTER = "cohere_embed"

MODEL = "embed-v4.0"

# Matryoshka-truncatable to 256/512/1024/1536; 1024 balances clustering
# quality against payload size for title-length text — no evidence at this
# volume that 1536 would change any grouping decision.
EMBEDDING_DIMENSION = 1024

# Cohere's own per-request cap. A larger batch is rejected outright, not
# truncated, so this must be enforced before the call, not discovered from it.
MAX_TEXTS_PER_REQUEST = 96

# Trial keys are capped at 100,000 tokens per minute, enforced as a hard 429
# with body "trial token rate limit exceeded". At roughly 12 tokens per
# headline a full batch is ~1,150 tokens, so ~87 batches fit in a minute.
#
# This only started mattering with Story 6.2. The RSS corpus was ~350 titles
# (4 batches, nowhere near the ceiling); GDELT's raw files bring ~8,800, which
# is ~92 batches — just past it. Without pacing the run trips the limit partway
# through and `embed_titles` returns nothing, so the cycle degrades to one
# Cluster per dedupe group and no Briefing is ever published. That failure is
# silent in the sense that matters: the cycle still reports success.
#
# Pacing rather than retrying on 429: the limit is a rolling token budget, so
# backing off after the fact still wastes the tokens already spent. Spacing the
# calls keeps every request inside the budget instead.
TOKENS_PER_MINUTE = 100_000
ESTIMATED_TOKENS_PER_TEXT = 12
_BATCH_TOKENS = MAX_TEXTS_PER_REQUEST * ESTIMATED_TOKENS_PER_TEXT
# Seconds to leave between batches, with 15% headroom for longer-than-average
# headlines. ~0.8s at the current constants.
REQUEST_INTERVAL_SECONDS = (_BATCH_TOKENS / TOKENS_PER_MINUTE) * 60 * 1.15

# The SDK's own default (300s) discovered the hard way: a run that hung on
# 2026-08-18 burned the job's entire 30-minute timeout without ever raising,
# because nothing here bounded a single call shorter than that default. A
# real batch call takes low single-digit seconds; 30s leaves generous room
# for network jitter while still failing fast enough, across ~100+ batches,
# that a stuck call degrades this cycle's clustering (AD-10) instead of
# consuming the whole job budget in silence.
REQUEST_TIMEOUT_SECONDS = 30.0


class _Embeddings(Protocol):
    float_: list[list[float]]


class _EmbedResponse(Protocol):
    embeddings: _Embeddings


class Client(Protocol):
    """The subset of ``cohere.ClientV2`` this adapter needs.

    Narrow on purpose, same reasoning as ``gdelt.Response``: it keeps the
    vendor client swappable and lets tests supply a plain object instead of
    mocking a library.
    """

    def embed(self, **kwargs: Any) -> _EmbedResponse: ...


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """What embedding retrieved, and what it could not.

    Parallel to ``CollectionResult`` rather than a reuse of it: embeddings are
    vectors aligned by position to the input titles, not Article-shaped dicts,
    and forcing that shape into ``CollectionResult`` would be a worse fit than
    a small dedicated type.
    """

    vectors: list[list[float]] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def embed_titles(
    titles: list[str], client: Client | None = None, pace: bool = True
) -> EmbeddingResult:
    """Embed titles for clustering, in batches of at most
    ``MAX_TEXTS_PER_REQUEST``, preserving input order.

    ``input_type="clustering"`` is mandatory: the retrieval-oriented values
    (``search_document``/``search_query``) produce embeddings tuned for
    asymmetric query/document matching, not symmetric similarity grouping —
    using them would not error, it would just silently degrade every
    downstream clustering decision.
    """
    if not titles:
        return EmbeddingResult()

    if client is None:
        api_key = os.environ.get("COHERE_API_KEY")
        if not api_key:
            return EmbeddingResult(
                failures=[Failure(ADAPTER, "COHERE_API_KEY is not set; cannot embed titles")]
            )
        import cohere

        client = cohere.ClientV2(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)

    # Deliberately all-or-nothing, unlike CollectionResult's partial-results
    # convention: vectors are positional (index i is group i's embedding), and
    # the cluster stage has no way to cluster a partial vector list against a
    # full group list without either misaligning positions or re-deriving
    # which titles are missing. A partial batch failure degrades exactly like
    # a total one — one Cluster per dedupe group for the whole cycle — rather
    # than risk a subtler bug from partial alignment.
    vectors: list[list[float]] = []
    total_batches = (len(titles) + MAX_TEXTS_PER_REQUEST - 1) // MAX_TEXTS_PER_REQUEST
    trace(f"embed: {len(titles)} titles in {total_batches} batches")
    try:
        for index, batch in enumerate(_chunks(titles, MAX_TEXTS_PER_REQUEST)):
            # Pace every batch after the first — see REQUEST_INTERVAL_SECONDS.
            # Sleeping before the call rather than after keeps the last batch
            # from paying for a wait nothing follows.
            if index and pace:
                time.sleep(REQUEST_INTERVAL_SECONDS)
            response = client.embed(
                model=MODEL,
                texts=batch,
                input_type="clustering",
                embedding_types=["float"],
                output_dimension=EMBEDDING_DIMENSION,
                truncate="END",
            )
            vectors.extend(response.embeddings.float_)
            if index and index % 25 == 0:
                trace(f"embed: {index}/{total_batches} batches")
    except Exception as exc:  # noqa: BLE001 - adapter boundary, must not raise past it
        return EmbeddingResult(failures=[Failure(ADAPTER, f"embedding request failed: {exc}")])

    return EmbeddingResult(vectors=vectors)


__all__ = ["EMBEDDING_DIMENSION", "MAX_TEXTS_PER_REQUEST", "EmbeddingResult", "embed_titles"]
