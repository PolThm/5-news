"""Tests for the AI Gateway summarization adapter.

No real network call anywhere here -- the adapter takes an injectable HTTP
client, exactly like ``claude``'s injectable ``client`` and GdeltClient's
injectable ``fetch``, so these tests never reach ai-gateway.vercel.sh.

Sleeping is injected too, and every retry test asserts on the *recorded*
sleeps rather than waiting: a suite that actually slept 60s per retry would
take an hour, and asserting the interval is the point anyway.

The two behaviours worth guarding hardest, because both are load-bearing and
neither is obvious from reading the call sites:

- The adapter is synchronous but wears ``claude``'s two-phase shape, so its
  ``submit_batch`` parks results on disk and its ``collect_batch`` reads them
  back. If that hand-off breaks, a cycle publishes titles instead of
  summaries and nothing raises.
- ``collect_batch`` routes on the batch id's own prefix, not on an env var,
  so a cycle that submitted through one provider is always collected through
  the same one.
"""

from __future__ import annotations

import json

import pytest
from pipeline.adapters.gateway import (
    BATCH_ID_PREFIX,
    MAX_ATTEMPTS,
    MAX_PHASE_SECONDS,
    MODEL,
    REASONING_EFFORT,
    RETRY_WAIT_SECONDS,
    batch_id_for,
    collect_batch,
    results_path,
    submit_batch,
)
from pipeline.domain import OutputLanguage

CYCLE_ID = "2026-08-26T05-30-00Z"


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload


def _summary_payload(
    headline: str = "A headline that states what happened",
    summary: str = "A paragraph summarizing the event.",
    why: str = "One concrete consequence.",
    takeaway: str = "The point, stated flatly.",
) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "headline": headline,
                            "summary": summary,
                            "why_it_matters": why,
                            "takeaway": takeaway,
                        }
                    )
                }
            }
        ]
    }


class _RecordingClient:
    """Returns queued responses in order and records every request body."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[dict] = []

    def post(self, url: str, **kwargs) -> _FakeResponse:
        self.requests.append(kwargs["json"])
        if not self._responses:
            raise AssertionError("more requests than queued responses")
        return self._responses.pop(0)


class _SleepRecorder:
    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _cluster(cluster_id: str = "subject-test-abc123") -> dict:
    return {
        "cluster_id": cluster_id,
        "members": [
            {"title": "First outlet's headline", "source": "Reuters", "url": "https://r.test/1"},
            {"title": "Second outlet's headline", "source": "AP", "url": "https://ap.test/2"},
        ],
    }


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "test-key")


def test_submit_sends_the_configured_model_and_reasoning_effort(tmp_path):
    # `minimal` is not cosmetic: at higher efforts this model spends hundreds
    # to thousands of billed reasoning tokens per call for no quality gain,
    # which is what the benchmark measured. A regression here is a silent
    # cost multiplier, so the request body is asserted directly.
    client = _RecordingClient([_FakeResponse(200, _summary_payload())])

    submit_batch(
        [_cluster()],
        OutputLanguage.FR,
        client=client,
        data_root=tmp_path,
        cycle_id=CYCLE_ID,
    )

    body = client.requests[0]
    assert body["model"] == MODEL
    assert body["reasoning"] == {"effort": REASONING_EFFORT}
    assert body["response_format"]["type"] == "json_schema"


def test_submit_parks_results_and_collect_reads_them_back(tmp_path):
    # The whole two-phase illusion in one test: submit does the work, collect
    # finds it, and the caller sees the same shape a real Claude batch gives.
    client = _RecordingClient([_FakeResponse(200, _summary_payload(headline="Parked and found"))])
    cluster = _cluster()

    submission = submit_batch(
        [cluster],
        OutputLanguage.FR,
        client=client,
        data_root=tmp_path,
        cycle_id=CYCLE_ID,
    )

    assert submission.batch_id == batch_id_for(CYCLE_ID, OutputLanguage.FR)
    assert results_path(tmp_path, CYCLE_ID, OutputLanguage.FR).exists()

    result = collect_batch(submission.batch_id, [cluster], data_root=tmp_path)

    # Never "pending": the work finished before submit_batch returned, so a
    # caller that waits for this batch would wait forever.
    assert result.status == "ended"
    assert result.texts[cluster["cluster_id"]].headline == "Parked and found"


def test_a_rate_limited_request_is_retried_on_the_flat_interval(tmp_path):
    # The free tier's refusal is a ~5-minute window, not a backoff-shaped
    # penalty, so the wait is flat and this asserts that rather than a
    # doubling sequence.
    sleeper = _SleepRecorder()
    client = _RecordingClient(
        [
            _FakeResponse(429),
            _FakeResponse(429),
            _FakeResponse(200, _summary_payload(headline="Landed on the third try")),
        ]
    )
    cluster = _cluster()

    submission = submit_batch(
        [cluster],
        OutputLanguage.FR,
        client=client,
        data_root=tmp_path,
        cycle_id=CYCLE_ID,
        sleep=sleeper,
    )
    result = collect_batch(submission.batch_id, [cluster], data_root=tmp_path)

    assert sleeper.waits == [RETRY_WAIT_SECONDS, RETRY_WAIT_SECONDS]
    assert result.texts[cluster["cluster_id"]].headline == "Landed on the third try"


def test_a_transport_exception_is_retried_too(tmp_path):
    # A dropped connection mid-cycle must not cost a Cluster its summary when
    # waiting out the interval would recover it.
    sleeper = _SleepRecorder()

    class _FlakyClient:
        def __init__(self) -> None:
            self.calls = 0

        def post(self, url: str, **kwargs) -> _FakeResponse:
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("connection reset")
            return _FakeResponse(200, _summary_payload(headline="Recovered"))

    cluster = _cluster()
    submission = submit_batch(
        [cluster],
        OutputLanguage.FR,
        client=_FlakyClient(),
        data_root=tmp_path,
        cycle_id=CYCLE_ID,
        sleep=sleeper,
    )
    result = collect_batch(submission.batch_id, [cluster], data_root=tmp_path)

    assert sleeper.waits == [RETRY_WAIT_SECONDS]
    assert result.texts[cluster["cluster_id"]].headline == "Recovered"


def test_a_non_429_http_error_is_not_retried(tmp_path):
    # Retrying a rejected request just spends 20 minutes reaching the same
    # answer, so a 400 fails once and degrades that Cluster.
    sleeper = _SleepRecorder()
    client = _RecordingClient([_FakeResponse(400)])
    cluster = _cluster()

    submission = submit_batch(
        [cluster],
        OutputLanguage.FR,
        client=client,
        data_root=tmp_path,
        cycle_id=CYCLE_ID,
        sleep=sleeper,
    )

    assert sleeper.waits == []
    assert len(client.requests) == 1
    assert submission.failures
    # The batch id still exists: one failed request degrades one Cluster, it
    # does not fail the submission (AD-10).
    assert submission.batch_id is not None

    result = collect_batch(submission.batch_id, [cluster], data_root=tmp_path)
    assert result.status == "ended"
    assert cluster["cluster_id"] not in result.texts


def test_a_request_that_never_lands_gives_up_after_the_attempt_ceiling(tmp_path):
    # Bounded rather than infinite: a permanently-refusing request degrades
    # one Cluster instead of blocking the cycle forever.
    sleeper = _SleepRecorder()
    client = _RecordingClient([_FakeResponse(429) for _ in range(MAX_ATTEMPTS)])
    cluster = _cluster()

    submission = submit_batch(
        [cluster],
        OutputLanguage.FR,
        client=client,
        data_root=tmp_path,
        cycle_id=CYCLE_ID,
        sleep=sleeper,
    )

    assert len(client.requests) == MAX_ATTEMPTS
    assert len(sleeper.waits) == MAX_ATTEMPTS - 1
    assert submission.failures


def test_the_phase_deadline_stops_retrying_before_the_job_is_killed(tmp_path):
    # Reaching the ceiling must degrade the remaining requests, not run the
    # job into a hard kill -- which would lose the summaries already written.
    # Derived from MAX_PHASE_SECONDS rather than a fixed constant: a fixed
    # number here silently stops testing "past the deadline" the moment the
    # constant is raised past it, which is exactly what happened when the
    # first real production cycle pushed the ceiling from 90m to 200m.
    past_deadline = MAX_PHASE_SECONDS * 2
    clock = iter([0.0] + [past_deadline] * 50)
    client = _RecordingClient([_FakeResponse(429)])
    cluster = _cluster()

    submission = submit_batch(
        [cluster],
        OutputLanguage.FR,
        client=client,
        data_root=tmp_path,
        cycle_id=CYCLE_ID,
        sleep=_SleepRecorder(),
        now=lambda: next(clock),
    )

    assert len(client.requests) == 1
    assert any("deadline" in f.detail for f in submission.failures)


def test_collect_refuses_a_batch_id_from_another_provider(tmp_path):
    # Routing is keyed on the id's own prefix so a Claude batch can never be
    # read as a parked gateway result, or the reverse.
    result = collect_batch("msgbatch_01ABC", [_cluster()], data_root=tmp_path)

    assert result.status == "ended"
    assert result.texts == {}
    assert any("not a gateway batch id" in f.detail for f in result.failures)


def test_collect_degrades_when_the_parked_results_are_missing(tmp_path):
    # "ended" with a failure, not "pending": a missing file is not something a
    # later invocation can recover, and reporting pending would resume forever.
    result = collect_batch(
        batch_id_for(CYCLE_ID, OutputLanguage.FR), [_cluster()], data_root=tmp_path
    )

    assert result.status == "ended"
    assert result.texts == {}
    assert result.failures


def test_submit_without_a_key_degrades_rather_than_raising(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)

    submission = submit_batch(
        [_cluster()],
        OutputLanguage.FR,
        data_root=tmp_path,
        cycle_id=CYCLE_ID,
    )

    assert submission.batch_id is None
    assert any("AI_GATEWAY_API_KEY" in f.detail for f in submission.failures)


def test_the_batch_id_encodes_the_language_so_three_cycles_cannot_collide(tmp_path):
    ids = {batch_id_for(CYCLE_ID, lang) for lang in OutputLanguage}

    assert len(ids) == 3
    assert all(i.startswith(BATCH_ID_PREFIX) for i in ids)
