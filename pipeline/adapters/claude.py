"""Claude adapter: turns a Cluster's member Articles into Summary text.

Isolated on purpose, same reasoning as ``cohere_embed.py`` (AD-13): an
injectable ``client`` keeps every test here network-free, and never raising
past this module's boundary (AD-10) means a summarization failure degrades
the affected Clusters rather than crashing the cycle.

Goes through the Batch API, not the synchronous Messages API (Story 3.6,
NFR-2). Split into two functions per AD-11's two-phase cycle: ``submit_batch``
submits a request and returns immediately with a batch ID -- it never waits.
``collect_batch`` checks a batch's status with a single call and either
returns "pending" (nothing to report yet) or collects and degrades results
exactly as a completed batch's per-Cluster failures always have. Neither
function loops, sleeps, or otherwise holds a process open waiting on the
Batch API to finish -- that was Story 3.1's deliberately simplified stand-in
(a single blocking ``summarize_clusters``), removed by Story 3.4 now that a
real two-phase caller (``pipeline.stages.summarize``) exists to use the split.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pipeline.adapters import Failure
from pipeline.domain import OutputLanguage

ADAPTER = "claude"

MODEL = "claude-haiku-4-5"

# Haiku 4.5 does not support the `effort` parameter or adaptive thinking
# (both error on this model) -- irrelevant anyway for a short, bounded,
# low-reasoning task: writing one paragraph from a handful of headlines.
MAX_TOKENS = 512

# Claude needs an instruction it can actually parse -- "Write ... in fr,
# summarizing ..." is not a sentence. Deliberately small and explicit, same
# reasoning as resolve_wire_agency's wire-service table (Story 2.3): a
# missing mapping should raise loudly (KeyError), never silently fall back
# to something plausible-but-wrong. Exactly the three values OutputLanguage
# has -- not a general i18n library or locale-name lookup.
_LANGUAGE_NAMES: dict[OutputLanguage, str] = {
    OutputLanguage.FR: "French",
    OutputLanguage.EN: "English",
    OutputLanguage.ES: "Spanish",
}
# A future OutputLanguage value added without a matching entry here would
# otherwise fail as a KeyError deep inside _prompt_for, at batch-submission
# time -- not at import time, and not caught by any test that doesn't
# specifically construct that missing case. Catch it at import instead.
assert set(_LANGUAGE_NAMES) == set(OutputLanguage), (
    "_LANGUAGE_NAMES must have exactly one entry per OutputLanguage value"
)

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
class BatchSubmission:
    """What submitting a batch produced: a batch ID to record and check
    later, or a submission-level failure (e.g. no API key, the request
    itself was rejected) with no ID to check.

    ``batch_id`` is ``None`` exactly when submission never happened or
    never succeeded -- there is nothing for a caller to poll in that case,
    distinct from ``collect_batch``'s "pending" outcome, where a real batch
    exists but has not finished.
    """

    batch_id: str | None = None
    failures: list[Failure] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BatchCollectResult:
    """The outcome of checking one batch's status, once.

    ``status`` is the caller-facing tri-state AD-11's phase two needs:
    ``"pending"`` means the batch has not reached ``ended`` yet -- there is
    nothing to report, and the caller should check again later (via a new
    invocation, never a loop inside this call). ``"ended"`` means results
    were collected (``summaries``/``failures`` populated per-Cluster exactly
    as a completed batch's outcome always has, including the mid-iteration-
    failure-preserves-already-collected-summaries fix from Story 3.1).

    Deliberately not a reuse of the old ``SummarizeResult`` shape: a
    "pending" outcome is not "every Cluster failed" -- collapsing the two
    would make a client unable to tell "retry the same batch" apart from
    "this batch is done and everything in it genuinely failed."
    """

    status: Literal["pending", "ended"]
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


def _prompt_for(cluster: dict, language: OutputLanguage) -> str:
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
    # The language *name* ("French"), never the bare OutputLanguage code
    # ("fr") -- "Write ... in fr, summarizing ..." is not an instruction an
    # instruction-following model should be expected to parse correctly.
    language_name = _LANGUAGE_NAMES[language]
    return (
        f"Write one short paragraph, in {language_name}, summarizing the "
        f"following news event for a reader who has not seen any of these "
        f"Articles.\n\n"
        f"Articles:\n{lines}\n\n"
        f"{corroboration_note}\n{_NO_FABRICATION_INSTRUCTION}"
    )


def _client_or_degrade(client: Client | None) -> tuple[Client | None, Failure | None]:
    """Resolve the injected client, or build the real one from
    ``ANTHROPIC_API_KEY`` -- shared by both ``submit_batch`` and
    ``collect_batch`` so the missing-key degrade is expressed once, not
    twice with two chances to drift."""
    if client is not None:
        return client, None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, Failure(ADAPTER, "ANTHROPIC_API_KEY is not set; cannot summarize")
    import anthropic

    return anthropic.Anthropic(api_key=api_key), None


def submit_batch(
    clusters: list[dict],
    language: OutputLanguage,
    client: Client | None = None,
) -> BatchSubmission:
    """Submit one Batch API request per Cluster and return immediately with
    the batch ID -- this call never waits for the batch to complete (AD-11:
    "neither phase holds a process open waiting on an external service").

    ``custom_id`` is set to each Cluster's ``cluster_id`` — the only correct
    way to reassociate a result with its Cluster later, since the Batch API
    makes no ordering guarantee on ``results()``.

    ``language`` is typed on ``OutputLanguage`` (not a bare ``str``) for
    static analysis and self-documentation. ``OutputLanguage`` is a
    ``StrEnum``, so this is not a runtime guard -- a bare ``"fr"`` still
    behaves identically, since ``OutputLanguage.FR == "fr"`` holds and
    dict lookups by that string succeed the same way. The only actual
    runtime enforcement is ``_prompt_for``'s ``_LANGUAGE_NAMES[language]``
    lookup, which raises ``KeyError`` for any value -- string or enum
    member -- outside the three supported languages.
    """
    if not clusters:
        return BatchSubmission()

    client, degrade = _client_or_degrade(client)
    if degrade is not None:
        return BatchSubmission(failures=[degrade])

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
    except Exception as exc:  # noqa: BLE001 - adapter boundary, must not raise past it
        return BatchSubmission(failures=[Failure(ADAPTER, f"batch submission failed: {exc}")])

    return BatchSubmission(batch_id=batch.id)


def collect_batch(
    batch_id: str,
    clusters: list[dict],
    client: Client | None = None,
) -> BatchCollectResult:
    """Check ``batch_id``'s status with a single call. If it has not
    reached ``"ended"``, return immediately with ``status="pending"`` --
    this function never loops, sleeps, or otherwise waits for the batch to
    finish (AD-11). If it has ended, collect and degrade results exactly as
    a completed batch's outcome always has.

    ``clusters`` is needed to detect a ``custom_id`` absent from
    ``results()`` entirely -- the Batch API's own contract says this
    shouldn't happen, but this adapter degrades that Cluster rather than
    silently dropping it or crashing on a missing key.
    """
    client, degrade = _client_or_degrade(client)
    if degrade is not None:
        # Nothing to poll for without a client -- report as an ended batch
        # whose every Cluster failed, not "pending" (retrying won't help).
        return BatchCollectResult(status="ended", failures=[degrade])

    try:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status != "ended":
            return BatchCollectResult(status="pending")
    except Exception as exc:  # noqa: BLE001 - adapter boundary, must not raise past it
        return BatchCollectResult(
            status="ended", failures=[Failure(ADAPTER, f"batch status check failed: {exc}")]
        )

    # A separate try/except from the status check above: an exception
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
        for item in client.messages.batches.results(batch_id):
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

    return BatchCollectResult(status="ended", summaries=summaries, failures=failures)


__all__ = [
    "ADAPTER",
    "MAX_TOKENS",
    "MODEL",
    "BatchCollectResult",
    "BatchSubmission",
    "Client",
    "collect_batch",
    "submit_batch",
]
