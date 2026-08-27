"""Summarize via Vercel AI Gateway, drop-in for ``claude``'s batch pair.

Why this exists: on a 2026-08-26 benchmark against 15 real (Cluster,
language) prompts from this pipeline, ``openai/gpt-5-mini`` with reasoning
effort ``minimal`` produced summaries of comparable quality to
``claude-haiku-4-5`` at roughly 40% lower token cost, and the Gateway's free
tier covers the whole monthly volume. Every other candidate measured worse:
Gemini 2.5 Flash-Lite was cheaper still but consistently drier (it dropped
named attribution -- "Prime Minister Sánchez" -- that Haiku kept), and
GPT-5-mini at effort ``low`` or ``medium`` cost 2x and 6x more than
``minimal`` for no measurable quality gain.

**This adapter is synchronous, and that is the whole complication.** The
Gateway has no batch endpoint -- its REST surface is models/credits/
generation/report and nothing else -- so there is no submit-now-collect-later
to mirror, and no 50% batch discount either. AD-11's two-phase cycle is
nonetheless load-bearing across ``cycle.py`` (phase states, resume,
abandonment), so rather than unpick that, ``submit_batch`` here does the
real work and writes its results to disk, and ``collect_batch`` reads them
back. The returned ``batch_id`` is a local marker, not a provider handle.

The consequence worth stating plainly: this makes the "submit" phase take
~45 minutes instead of ~5 seconds, and a job killed mid-phase loses
everything it has done. That is the same exposure the Claude path already
had for a killed job, and the next scheduled cycle starts fresh either way
(AD-7) -- but the window is now much wider, which is why the workflow's
timeout is raised to 2h alongside this.

**Rate limiting is the other half of the design.** The free tier admits
about five calls, then refuses for about five minutes: measured 2026-08-26,
20 consecutive calls needed 34 attempts and 15.4 minutes, converging every
time (17 of 20 succeeded first try; none needed more than 6). Retrying on a
fixed 60s interval absorbs that completely, which is what this adapter
does. It is a *shared* free-tier limit, so a busier day at Vercel will be
slower than the measurement -- the 2h timeout leaves ~2.5x headroom over the
~46 minutes a 60-call cycle took.

Prompts, schemas, and parsers are imported from ``claude`` rather than
restated. That is deliberate: the benchmark that chose this model sent
``claude``'s exact prompts, so a divergent copy here would invalidate the
comparison the moment either side was edited.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pipeline.adapters import Failure
from pipeline.adapters.claude import (
    _CONSEQUENCE_MAX_TOKENS,
    _CONSEQUENCE_SCHEMA,
    _SUMMARY_SCHEMA,
    CONSEQUENCE_BATCH,
    BatchCollectResult,
    BatchSubmission,
    _consequence_prompt,
    _parse_cluster_text,
    _prompt_for,
)
from pipeline.domain import OutputLanguage

ADAPTER = "gateway"

BASE_URL = "https://ai-gateway.vercel.sh/v1/chat/completions"

# Benchmarked 2026-08-26. `minimal` is not a guess: at `low` this model spent
# ~330 hidden reasoning tokens per call and at `medium` ~1360, for summaries
# no better than `minimal`'s zero-reasoning output on the same prompts.
MODEL = "openai/gpt-5-mini"
REASONING_EFFORT = "minimal"

# Matches claude.MAX_TOKENS. The four summary fields run ~180 output tokens
# in practice; this is headroom, not a target.
MAX_TOKENS = 512

# Free-tier rate limiting. The interval is flat rather than exponential
# because the limit is a ~5-minute window, not a backoff-shaped penalty:
# measured, five calls pass, then five 60s retries ride out the window.
RETRY_WAIT_SECONDS = 60

# Per-request ceiling. At 60s apiece this is 20 minutes on one request before
# it is given up as a per-Cluster degrade (AD-10) rather than blocking the
# cycle forever. The measured worst case was 6 attempts.
MAX_ATTEMPTS = 20

# Whole-phase ceiling, well inside the workflow's 4h timeout. Reaching it
# means the free tier is far slower than measured; remaining requests degrade
# rather than run the job into a hard kill, which would lose the ones already
# done.
#
# Raised from 90m after the first real production cycle (2026-08-27, 18
# Clusters x 3 languages plus per-Zone angles) took ~2h against a 20-call
# measurement that predicted ~46m -- a full cycle makes far more calls than
# that sample did, and the free tier's rate limit only gets tighter as the
# day goes on. 200m keeps a real margin below the job's own 240m timeout.
MAX_PHASE_SECONDS = 200 * 60

# How a local, results-on-disk submission is marked. `collect_batch` accepts
# only ids carrying this prefix, so a Claude batch id can never be mistaken
# for one of these (or the reverse) if the two adapters are ever both live.
BATCH_ID_PREFIX = "gateway-local:"

_RESULTS_FILENAME = "gateway_results.json"


class Response(Protocol):
    """The subset of an HTTP response this adapter reads.

    Narrow on purpose, same reasoning as ``gdelt.Response``: keeps the HTTP
    client swappable and lets tests supply a plain object instead of
    mocking httpx.
    """

    status_code: int

    def json(self) -> Any: ...


class HttpClient(Protocol):
    def post(self, url: str, **kwargs: Any) -> Response: ...


@dataclass(frozen=True, slots=True)
class _Request:
    """One prompt to send, keyed the way `claude`'s batch requests are."""

    custom_id: str
    prompt: str
    schema: dict


def results_path(data_root: Path, cycle_id: str, language: OutputLanguage) -> Path:
    """Where one language's synchronous results are parked between the fake
    submit phase and the collect phase that reads them back."""
    return data_root / "intermediate" / "summarize" / cycle_id / language.value / _RESULTS_FILENAME


def batch_id_for(cycle_id: str, language: OutputLanguage) -> str:
    return f"{BATCH_ID_PREFIX}{cycle_id}:{language.value}"


def _client_or_degrade(client: HttpClient | None) -> tuple[HttpClient | None, Failure | None]:
    """Resolve the injected client, or build one -- and refuse early if the
    key is absent, mirroring ``claude._client_or_degrade`` so the
    missing-key degrade reads the same on both paths."""
    if client is not None:
        return client, None
    if not os.environ.get("AI_GATEWAY_API_KEY"):
        return None, Failure(ADAPTER, "AI_GATEWAY_API_KEY is not set; cannot summarize")
    import httpx

    return httpx.Client(), None


def _requests_for(clusters: list[dict], language: OutputLanguage) -> list[_Request]:
    """One request per Cluster, keyed the way `claude`'s batch requests are."""
    return [
        _Request(
            custom_id=cluster["cluster_id"],
            prompt=_prompt_for(cluster, language),
            schema=_SUMMARY_SCHEMA,
        )
        for cluster in clusters
    ]


def _post_once(
    client: HttpClient, api_key: str, request: _Request, max_tokens: int = MAX_TOKENS
) -> tuple[str | None, Failure | None, bool]:
    """One HTTP attempt. Returns ``(text, failure, retryable)``.

    A 429 is the expected free-tier refusal and is retryable. So is a
    transport exception -- a dropped connection mid-cycle should not cost a
    Cluster its summary when waiting 60s would recover it. Anything else
    (a 4xx that is not 429, a malformed body) is reported as final: retrying
    a rejected request just spends 20 minutes reaching the same answer.
    """
    try:
        response = client.post(
            BASE_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": request.prompt}],
                "max_tokens": max_tokens,
                "reasoning": {"effort": REASONING_EFFORT},
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "summary", "schema": request.schema},
                },
            },
            timeout=90,
        )
    except Exception as exc:  # noqa: BLE001 - adapter boundary, must not raise past it
        return None, Failure(ADAPTER, f"{request.custom_id}: request raised: {exc}"), True

    if response.status_code == 429:
        return None, Failure(ADAPTER, f"{request.custom_id}: rate limited"), True
    if response.status_code != 200:
        return (
            None,
            Failure(ADAPTER, f"{request.custom_id}: HTTP {response.status_code}"),
            False,
        )

    try:
        payload = response.json()
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return None, Failure(ADAPTER, f"{request.custom_id}: unreadable response: {exc}"), False

    if not isinstance(text, str) or not text.strip():
        return None, Failure(ADAPTER, f"{request.custom_id}: empty response content"), False

    return text, None, False


def _send_with_retry(
    client: HttpClient,
    api_key: str,
    request: _Request,
    deadline: float,
    sleep=time.sleep,
    now=time.monotonic,
    max_tokens: int = MAX_TOKENS,
) -> tuple[str | None, Failure | None]:
    """Retry a retryable refusal on a flat interval until it lands, the
    per-request ceiling is reached, or the phase deadline passes."""
    last_failure: Failure | None = None
    for attempt in range(MAX_ATTEMPTS):
        text, failure, retryable = _post_once(client, api_key, request, max_tokens=max_tokens)
        if text is not None:
            return text, None
        last_failure = failure
        if not retryable:
            return None, failure
        if attempt == MAX_ATTEMPTS - 1:
            break
        if now() + RETRY_WAIT_SECONDS > deadline:
            return None, Failure(
                ADAPTER,
                f"{request.custom_id}: phase deadline reached while rate limited",
            )
        sleep(RETRY_WAIT_SECONDS)

    return None, last_failure or Failure(
        ADAPTER, f"{request.custom_id}: gave up after {MAX_ATTEMPTS} attempts"
    )


def submit_batch(
    clusters: list[dict],
    language: OutputLanguage,
    client: HttpClient | None = None,
    data_root: Path | None = None,
    cycle_id: str | None = None,
    sleep=time.sleep,
    now=time.monotonic,
) -> BatchSubmission:
    """Do the whole job synchronously, write the results, return a local id.

    Signature-compatible with ``claude.submit_batch`` for the arguments
    ``summarize`` passes; ``data_root``/``cycle_id`` are extra because the
    results have to be parked somewhere the collect phase can find them.

    Returns a ``BatchSubmission`` with no ``batch_id`` only when nothing was
    submitted at all (no requests, no key, unwritable results) -- a request
    that individually failed is recorded in the results file and degrades one
    Cluster later, exactly as a Claude batch's per-Cluster failure does.
    """
    if not clusters:
        return BatchSubmission()
    if data_root is None or cycle_id is None:
        return BatchSubmission(
            failures=[Failure(ADAPTER, "data_root and cycle_id are required to park results")]
        )

    client, degrade = _client_or_degrade(client)
    if client is None:
        return BatchSubmission(failures=[degrade] if degrade else [])

    api_key = os.environ.get("AI_GATEWAY_API_KEY", "")
    requests = _requests_for(clusters, language)
    deadline = now() + MAX_PHASE_SECONDS

    texts: dict[str, str] = {}
    failures: list[Failure] = []
    for request in requests:
        text, failure = _send_with_retry(client, api_key, request, deadline, sleep=sleep, now=now)
        if text is not None:
            texts[request.custom_id] = text
        elif failure is not None:
            failures.append(failure)

    path = results_path(data_root, cycle_id, language)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "adapter": ADAPTER,
                    "model": MODEL,
                    "language": language.value,
                    "texts": texts,
                    "failures": [f.to_dict() for f in failures],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        # The work is done but unreachable by the collect phase, so this is
        # a submission failure, not a degrade: there is nothing to collect.
        return BatchSubmission(
            failures=[*failures, Failure(ADAPTER, f"could not write results: {exc}")]
        )

    return BatchSubmission(batch_id=batch_id_for(cycle_id, language), failures=failures)


def collect_batch(
    batch_id: str,
    clusters: list[dict],
    client: HttpClient | None = None,
    data_root: Path | None = None,
) -> BatchCollectResult:
    """Read back what ``submit_batch`` already produced.

    Never returns ``"pending"``: the work finished before ``submit_batch``
    returned, so there is nothing to wait for. A missing or unreadable
    results file is ``"ended"`` with a failure -- every Cluster degrades to
    its title (AD-6), which is the same outcome as a Claude batch that
    returned nothing, rather than a cycle that resumes forever.
    """
    if not batch_id.startswith(BATCH_ID_PREFIX):
        return BatchCollectResult(
            status="ended",
            failures=[Failure(ADAPTER, f"not a gateway batch id: {batch_id!r}")],
        )
    if data_root is None:
        return BatchCollectResult(
            status="ended",
            failures=[Failure(ADAPTER, "data_root is required to read parked results")],
        )

    _, cycle_id, language_value = batch_id.split(":", 2)
    path = results_path(data_root, cycle_id, OutputLanguage(language_value))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return BatchCollectResult(
            status="ended",
            failures=[Failure(ADAPTER, f"could not read results at {path}: {exc}")],
        )

    failures = [Failure(ADAPTER, f["detail"]) for f in payload.get("failures", [])]
    texts = {}
    for custom_id, raw in payload.get("texts", {}).items():
        text, failure = _parse_cluster_text(custom_id, raw)
        if text is not None:
            texts[custom_id] = text
        elif failure is not None:
            failures.append(failure)

    return BatchCollectResult(status="ended", texts=texts, failures=failures)


def score_consequence(
    events: list[tuple[str, str]],
    client: HttpClient | None = None,
    sleep=time.sleep,
    now=time.monotonic,
) -> tuple[dict[str, int], list[Failure]]:
    """How much each event changes, on ``claude._CONSEQUENCE_SCALE``.

    The gateway twin of ``claude.score_consequence``, so a deployment that
    sets ``SUMMARIZE_PROVIDER=gateway`` needs no Anthropic key at all. Same
    prompt, same schema, same short-id indirection -- only the transport and
    the rate-limit handling differ.

    Unlike summarize, this is on the cycle's critical path: `rank` needs the
    verdicts before it orders anything. A cycle's ~50 candidates take two or
    three calls, so even at the free tier's worst measured pace this adds
    minutes, not tens of minutes.

    Returns what it could score plus the failures. A missing verdict is not
    an error for the caller to raise on -- `rank` scores an unjudged item
    neutrally, so a failed call costs the ordering its sharpness and never
    the cycle (AD-10).
    """
    client, degrade = _client_or_degrade(client)
    if client is None:
        return {}, [degrade] if degrade else []

    api_key = os.environ.get("AI_GATEWAY_API_KEY", "")
    deadline = now() + MAX_PHASE_SECONDS
    verdicts: dict[str, int] = {}
    failures: list[Failure] = []

    for start in range(0, len(events), CONSEQUENCE_BATCH):
        chunk_events = events[start : start + CONSEQUENCE_BATCH]
        by_short = {f"e{position}": event_id for position, (event_id, _) in enumerate(chunk_events)}
        chunk = [
            (short, headline) for short, (_, headline) in zip(by_short, chunk_events, strict=True)
        ]
        request = _Request(
            custom_id=f"consequence-{start}",
            prompt=_consequence_prompt(chunk),
            schema=_CONSEQUENCE_SCHEMA,
        )
        raw, failure = _send_with_retry(
            client,
            api_key,
            request,
            deadline,
            sleep=sleep,
            now=now,
            max_tokens=_CONSEQUENCE_MAX_TOKENS,
        )
        if raw is None:
            if failure is not None:
                failures.append(failure)
            continue

        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            failures.append(Failure(ADAPTER, f"consequence scoring returned invalid JSON: {exc}"))
            continue

        for verdict in payload.get("verdicts", []):
            event_id = by_short.get(verdict.get("id", ""))
            value = verdict.get("consequence")
            # The id is echoed by the model, so it is looked up rather than
            # trusted: one it invents resolves to nothing instead of attaching
            # a verdict to another event. The range is checked here because the
            # output schema cannot express it.
            if event_id is not None and isinstance(value, int) and 0 <= value <= 3:
                verdicts[event_id] = value

    return verdicts, failures


__all__ = [
    "ADAPTER",
    "BATCH_ID_PREFIX",
    "MAX_ATTEMPTS",
    "MAX_PHASE_SECONDS",
    "MODEL",
    "REASONING_EFFORT",
    "RETRY_WAIT_SECONDS",
    "batch_id_for",
    "collect_batch",
    "results_path",
    "score_consequence",
    "submit_batch",
]
