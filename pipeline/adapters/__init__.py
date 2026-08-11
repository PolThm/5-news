"""External service adapters — one module per service.

Stages depend on interfaces expressed in domain terms, never on a vendor SDK
type (AD-13). Rate limiting, retry, pagination, and batching live here, inside
the adapter, so that swapping a provider is a change to one file rather than a
pipeline-wide edit.

Every adapter returns partial results plus a record of what failed rather than
raising past its own boundary (AD-10): one rate-limited upstream degrades a
cycle's coverage, it does not fail the cycle. The decision to abort belongs to
the stage, which can see every adapter's outcome; an adapter only ever reports
its own.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Failure:
    """What went wrong, in one adapter, in terms a human reading the cycle
    record will understand.

    ``detail`` is prose rather than an exception object on purpose: it lands in
    ``cycle.json`` and is read by eye during the inspection window.
    """

    adapter: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"adapter": self.adapter, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """What an adapter retrieved, and what it could not.

    Both halves matter. An adapter that hit a rate limit after three of seven
    pages returns the three pages *and* says so — discarding either would
    misrepresent the cycle.
    """

    articles: list[dict[str, Any]] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)

    @property
    def partial(self) -> bool:
        """Retrieved something, but not everything."""
        return bool(self.articles) and bool(self.failures)

    @property
    def empty(self) -> bool:
        """Retrieved nothing at all."""
        return not self.articles

    @classmethod
    def merge(cls, results: Iterable[CollectionResult]) -> CollectionResult:
        """Combine several adapters' outcomes into the cycle's single record."""
        articles: list[dict[str, Any]] = []
        failures: list[Failure] = []
        for result in results:
            articles.extend(result.articles)
            failures.extend(result.failures)
        return cls(articles=articles, failures=failures)


__all__ = ["CollectionResult", "Failure"]
