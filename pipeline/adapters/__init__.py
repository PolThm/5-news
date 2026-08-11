"""External service adapters — one module per service.

Stages depend on interfaces expressed in domain terms, never on a vendor SDK
type (AD-13). Rate limiting, retry, pagination, and batching live here, inside
the adapter, so that swapping a provider is a change to one file rather than a
pipeline-wide edit.

Every adapter returns partial results plus a record of what failed rather than
raising past its own boundary (AD-10): one rate-limited upstream degrades a
cycle's coverage, it does not fail the cycle.

Populated from Story 1.2 onward: gdelt, rss, cohere, claude.
"""
