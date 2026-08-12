"""Claude adapter: turns a Cluster's member Articles into Summary text.

Isolated on purpose, same reasoning as ``cohere_embed.py`` (AD-13): an
injectable ``client`` keeps every test here network-free, and never raising
past this module's boundary (AD-10) means a summarization failure degrades
the affected Clusters rather than crashing the cycle.

Goes through the Batch API, not the synchronous Messages API (Story 3.6,
NFR-2): one request per Cluster, submitted together, polled until the batch
reports ``ended``, then collected. This function blocks on that poll loop
within one call — the deliberately simplified version of AD-11's two-phase
resumable cycle. Story 3.4 replaces this poll loop with a real submit-then-
exit / resume-later split; this story only builds the mechanism the split
will later wrap.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from pipeline.adapters import Failure

ADAPTER = "claude"

MODEL = "claude-haiku-4-5"

# Haiku 4.5 does not support the `effort` parameter or adaptive thinking
# (both error on this model) -- irrelevant anyway for a short, bounded,
# low-reasoning task: writing one paragraph from a handful of headlines.
MAX_TOKENS = 512

_NO_FABRICATION_INSTRUCTION = (
    "Only state facts present in the Articles given to you. Never invent a "
    "detail, quote, or figure that is not in them. Never attribute a "
    "synthesized statement to a named outlet -- if you are not directly "
    "quoting an outlet, do not say '<outlet> reports that...'."
)


class _BatchResult(Protocol):
    type: str


class _BatchResultItem(Protocol):
    custom_id: str
    result: _BatchResult


class _Batch(Protocol):
    id: str
    processing_status: str


class _Batches(Protocol):
    """The subset of ``client.messages.batches`` this adapter needs.

    Narrow on purpose, same reasoning as ``gdelt.Response`` and
    ``cohere_embed.Client``: keeps the vendor client swappable and lets
    tests supply a plain object instead of mocking a library.
    """

    def create(self, **kwargs: Any) -> _Batch: ...
    def retrieve(self, batch_id: str) -> _Batch: ...
    def results(self, batch_id: str) -> Any: ...


class _Messages(Protocol):
    batches: _Batches


class Client(Protocol):
    messages: _Messages


@dataclass(frozen=True, slots=True)
class SummarizeResult:
    """What summarization retrieved, and what it could not.

    Parallel to ``EmbeddingResult``/``CollectionResult`` rather than a reuse
    of either: this is a mapping keyed by ``cluster_id`` (the Batch API's
    own ``custom_id``), not a positional list -- results arrive in arbitrary
    order, so there is no "index i" this shape could sensibly mean.
    """

    summaries: dict[str, str] = field(default_factory=dict)
    failures: list[Failure] = field(default_factory=list)


def _escape_quotes(text: str) -> str:
    """Titles come from many uncontrolled international sources (RSS/GDELT)
    and are concatenated directly into the prompt. Escaping an embedded
    double-quote keeps a title from prematurely closing its own delimiter
    and blending into the surrounding instruction text."""
    return text.replace('"', '\\"')


def _member_lines(members: list[dict]) -> str:
    if not members:
        return "(no member Articles)"
    return "\n".join(f'- "{_escape_quotes(m["title"])}" ({m["source"]})' for m in members)


def _prompt_for(cluster: dict, language: str) -> str:
    members = cluster.get("members", [])
    lines = _member_lines(members)
    # A Cluster with fewer than 2 members is legitimate (a singleton Cluster
    # -- cluster.py's own docstring) and reachable via Continent fallback or
    # cross-day linking even though every ranked Cluster met the Qualifying
    # floor of 2+ Independent Sources -- Independent Source count and member
    # count are not the same number in those cases. Describe what is
    # actually known rather than ever claiming a second source that isn't
    # there; AC2's no-fabrication rule is about not inventing facts, not
    # about requiring 2+ members.
    corroboration_note = (
        "Only one Article is available for this event -- write from it "
        "alone; do not imply a second source confirmed anything."
        if len(members) < 2
        else "Write a short paragraph synthesizing what these Articles agree on."
    )
    return (
        f"Write one short paragraph, in {language}, summarizing the following "
        f"news event for a reader who has not seen any of these Articles.\n\n"
        f"Articles:\n{lines}\n\n"
        f"{corroboration_note}\n{_NO_FABRICATION_INSTRUCTION}"
    )


def summarize_clusters(
    clusters: list[dict],
    language: str,
    client: Client | None = None,
    poll_interval_seconds: float = 2.0,
    max_poll_attempts: int = 300,
) -> SummarizeResult:
    """Summarize each Cluster's member Articles into one paragraph, in
    ``language``, via the Batch API.

    ``custom_id`` is set to each Cluster's ``cluster_id`` — the only correct
    way to reassociate a result with its Cluster, since the Batch API makes
    no ordering guarantee on ``results()``.

    ``max_poll_attempts`` bounds the poll loop (default: 300 x the 2-second
    default interval = 10 minutes) so a stuck or permanently-wedged batch
    degrades to a ``Failure`` for every Cluster in the call rather than
    blocking this function -- and the whole cycle, since nothing else runs
    concurrently -- forever. This is still the deliberately simplified,
    blocking version of AD-11's two-phase split (Story 3.4 replaces the
    whole poll loop); the cap only prevents an unbounded hang within it.
    """
    if not clusters:
        return SummarizeResult()

    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return SummarizeResult(
                failures=[Failure(ADAPTER, "ANTHROPIC_API_KEY is not set; cannot summarize")]
            )
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)

    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    try:
        requests = [
            Request(
                custom_id=cluster["cluster_id"],
                params=MessageCreateParamsNonStreaming(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    messages=[
                        {"role": "user", "content": _prompt_for(cluster, language)},
                    ],
                ),
            )
            for cluster in clusters
        ]
        batch = client.messages.batches.create(requests=requests)

        attempts = 0
        while batch.processing_status != "ended":
            attempts += 1
            if attempts >= max_poll_attempts:
                return SummarizeResult(
                    failures=[
                        Failure(
                            ADAPTER,
                            f"batch {batch.id}: did not complete within "
                            f"{max_poll_attempts} poll attempts",
                        )
                    ]
                )
            time.sleep(poll_interval_seconds)
            batch = client.messages.batches.retrieve(batch.id)
    except Exception as exc:  # noqa: BLE001 - adapter boundary, must not raise past it
        return SummarizeResult(failures=[Failure(ADAPTER, f"batch submission failed: {exc}")])

    # A separate try/except from submission/polling above: an exception
    # raised partway through iterating results() (e.g. a transient network
    # blip) must not discard summaries already collected earlier in this
    # same iteration -- only the Clusters not yet reached by the time it
    # raised are reported as failed, matching this module's own claim that a
    # failure degrades only the affected Cluster, never everything already
    # collected.
    summaries: dict[str, str] = {}
    failures: list[Failure] = []
    seen_custom_ids: set[str] = set()
    try:
        for item in client.messages.batches.results(batch.id):
            seen_custom_ids.add(item.custom_id)
            if item.result.type == "succeeded":
                text_blocks = [b.text for b in item.result.message.content if b.type == "text"]
                summaries[item.custom_id] = "".join(text_blocks)
            else:
                failures.append(
                    Failure(
                        ADAPTER,
                        f"cluster {item.custom_id}: batch result was "
                        f"{item.result.type!r}, not succeeded",
                    )
                )
    except Exception as exc:  # noqa: BLE001 - adapter boundary, must not raise past it
        failures.append(Failure(ADAPTER, f"result collection interrupted: {exc}"))

    # A custom_id absent from results() entirely should not happen per the
    # Batch API's own contract, but this adapter must degrade that Cluster
    # rather than silently drop it or crash on a missing key. Also covers
    # every Cluster not yet reached when the loop above raised partway
    # through iteration.
    for cluster in clusters:
        cluster_id = cluster["cluster_id"]
        if cluster_id not in seen_custom_ids:
            failures.append(
                Failure(ADAPTER, f"cluster {cluster_id}: no result returned by the batch")
            )

    return SummarizeResult(summaries=summaries, failures=failures)


__all__ = ["ADAPTER", "MAX_TOKENS", "MODEL", "Client", "SummarizeResult", "summarize_clusters"]
