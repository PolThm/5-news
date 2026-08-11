"""Adapters return partial results plus a failure record — they never raise
past their own boundary (AD-10, NFR-3).

One rate-limited or unreachable upstream degrades a cycle's coverage. It does
not fail the cycle, and it does not produce an empty Briefing.
"""

from __future__ import annotations

from pipeline.adapters import CollectionResult, Failure


def test_result_carries_articles_and_failures() -> None:
    result = CollectionResult(articles=[{"title": "x"}], failures=[])
    assert result.articles == [{"title": "x"}]
    assert result.failures == []


def test_result_is_partial_when_some_of_it_failed() -> None:
    """The defining case: some articles retrieved, something also went wrong.
    Both must survive into the record."""
    result = CollectionResult(
        articles=[{"title": "got this one"}],
        failures=[Failure(adapter="gdelt", detail="429 after 3 of 7 pages")],
    )
    assert result.articles
    assert result.failures
    assert result.partial is True


def test_result_is_not_partial_when_clean() -> None:
    assert CollectionResult(articles=[{"title": "x"}], failures=[]).partial is False


def test_total_failure_is_still_a_result_not_an_exception() -> None:
    """Even when an adapter retrieves nothing, it returns — the decision to
    abort a cycle belongs to the stage, not the adapter."""
    result = CollectionResult(
        articles=[], failures=[Failure(adapter="rss", detail="all feeds down")]
    )
    assert result.articles == []
    assert result.failures
    assert result.empty is True


def test_results_merge() -> None:
    """The collect stage runs several adapters and needs one combined record."""
    a = CollectionResult(articles=[{"title": "a"}], failures=[])
    b = CollectionResult(
        articles=[{"title": "b"}], failures=[Failure(adapter="rss", detail="one feed 404")]
    )

    merged = CollectionResult.merge([a, b])

    assert len(merged.articles) == 2
    assert len(merged.failures) == 1
    assert merged.partial is True


def test_failure_serializes_for_the_cycle_record() -> None:
    """Failures are written into the cycle's metadata, so they must be plain
    data — inspectable by hand during the Build Order's inspection window."""
    failure = Failure(adapter="gdelt", detail="timeout")
    assert failure.to_dict() == {"adapter": "gdelt", "detail": "timeout"}
