"""Summarize stage: the AI stage, and the only one that calls a model.

AD-6's exact boundary: input is a Briefing that is already ordered and
counted (whatever `run_rank` produced). Output is Summary text keyed to
Cluster identity, plus (Story 3.3) an `outbound_url`/`outbound_source` pair
this stage now also owns. This stage may not add, remove, reorder, or
renumber anything -- every field on a ranked Cluster dict besides these is
owned by an earlier stage and is copied through unchanged, never recomputed
(AD-12).

One language per call (Story 3.2's explicit scope). A future orchestration
story calls this three times per cycle, once per Output Language. Output is
written under a language-scoped subdirectory so those three calls never
overwrite each other's output.

Two entry points, per AD-11's two-phase cycle (Story 3.4): `submit_summarize`
submits a batch and returns immediately -- it writes nothing but a pending
marker. `collect_summarize` checks that batch once; if it has not finished,
it returns `None` and writes nothing (the caller retries on a later
invocation); if it has finished, it writes the same `summarized.jsonl` shape
Stories 3.1-3.3 established. Neither function loops or sleeps waiting on the
Batch API -- that was Story 3.1's deliberately simplified stand-in
(a single blocking call), removed now that this two-phase split exists.

A summarize failure for one Cluster degrades that item's `summary` to its
title; it never fails the whole Briefing (AD-6, mirroring AD-10's "one
failure degrades, never aborts" pattern already used throughout this
pipeline). `outbound_url`/`outbound_source` are unaffected by a degrade --
they are attached from the same representative member regardless of
whether summarization succeeded, so a reader always has a genuine Article
to click through to. A representative with no usable `url`/`source` (a
malformed member, or an empty string) degrades both fields to `None`
rather than crashing or rendering a broken link.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pipeline.adapters import Failure
from pipeline.adapters.claude import (
    BatchCollectResult,
    BatchSubmission,
    collect_batch,
    submit_batch,
)
from pipeline.domain import OutputLanguage
from pipeline.stages import (
    DEFAULT_DATA_ROOT,
    cycle_id_for,
    read_jsonl,
    stage_arg_parser,
    write_atomically,
    write_jsonl,
)

STAGE = "summarize"

# submit_batch/collect_batch's real signatures also take optional `client`
# for injection; these aliases only describe the shape every call site here
# actually uses.
SubmitFn = Callable[[list[dict], OutputLanguage], BatchSubmission]
CollectFn = Callable[[str, list[dict]], BatchCollectResult]


def _representative_member(cluster: dict) -> dict | None:
    """The Article this Cluster is represented by wherever a single member
    must stand in for the whole Cluster: earliest-published, then URL as a
    stable tiebreak -- the *exact* convention `dedupe.py`'s
    `ArticleGroup.representative` and `cluster.py`'s `coverage_for_cluster`
    already use one layer down (both tiebreak on `url`, never `title` --
    titles are not guaranteed unique the way URLs are). `members` is sorted
    by title, not publish order (Story 3.1, Task 0), so this must be
    recomputed here rather than assumed from list position.

    `None` for a Cluster with no members -- the `link_across_days`
    history-only-clique case (Story 3.1, Task 0) legitimately produces one;
    there is nothing to be representative of.
    """
    members = cluster.get("members", [])
    if not members:
        return None
    return min(members, key=lambda m: (m.get("published_at", ""), m["url"]))


def _degrade_title(cluster: dict, representative: dict | None) -> str:
    """The representative title for a degraded Cluster -- see
    `_representative_member` for the selection convention. Takes the
    already-selected representative for the same reason
    `_select_outbound_link` does: one `_representative_member` call per
    Cluster, shared between both derivations."""
    if representative is None:
        return cluster["cluster_id"]
    return representative["title"]


def _select_outbound_link(representative: dict | None) -> tuple[str | None, str | None]:
    """The `(outbound_url, outbound_source)` every Briefing item carries
    (Story 3.3, FR-14) -- from the same representative member
    `_degrade_title` selects for the degrade path, applied here for every
    Cluster regardless of whether summarization succeeded or degraded, so
    a reader always has a genuine Article to click through to.

    Takes the already-selected representative (rather than the Cluster
    itself) so a caller that also needs `_degrade_title`'s degrade text for
    the same Cluster doesn't pay for `_representative_member`'s `min()`
    scan twice.

    Degrades to `(None, None)` for: a Cluster with no members (matching
    `_representative_member`'s own `None`); a representative missing
    `source` (a malformed upstream member must not crash the whole
    summarize call, per AD-10 -- it degrades only this Cluster's link); and
    a representative whose `url` or `source` is present but an empty
    string, which would otherwise render as a broken, empty href on the
    display side rather than being caught here.
    """
    if representative is None:
        return None, None
    url = representative.get("url") or None
    source = representative.get("source") or None
    return url, source


def _destination(data_root: Path, cycle_id: str, language: OutputLanguage) -> Path:
    return data_root / "intermediate" / STAGE / cycle_id / language.value


@dataclass(frozen=True, slots=True)
class WrittenSubmission:
    batch_id: str | None
    metadata_path: Path
    submitted: bool


def submit_summarize(
    clusters: list[dict],
    language: OutputLanguage,
    cycle_id: str,
    data_root: Path = DEFAULT_DATA_ROOT,
    submit_fn: SubmitFn = submit_batch,
) -> WrittenSubmission:
    """Submit a Batch API request for `clusters`, in `language`, and return
    immediately (AD-11) -- this never waits for the batch to complete.

    Writes only a small pending-batch marker (`submitting.json`), not
    `summarized.jsonl` -- there is nothing to summarize yet. `cycle.py` is
    responsible for recording the batch ID (and the fact that `clusters`
    came from this cycle's `ranked.jsonl`) durably enough for a later
    invocation to call `collect_summarize` with the same inputs.
    """
    destination = _destination(data_root, cycle_id, language)
    metadata_path = destination / "submitting.json"

    submission = submit_fn(clusters, language)

    metadata = {
        "stage": STAGE,
        "cycle_id": cycle_id,
        "language": language.value,
        "clusters_submitted": len(clusters),
        "batch_id": submission.batch_id,
        "failures": [f.to_dict() for f in submission.failures],
    }
    write_atomically(
        metadata_path, json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )

    return WrittenSubmission(
        batch_id=submission.batch_id,
        metadata_path=metadata_path,
        submitted=submission.batch_id is not None,
    )


@dataclass(frozen=True, slots=True)
class WrittenSummarize:
    output_path: Path
    metadata_path: Path
    clusters_summarized: int
    degraded: bool
    # The collect-side Failures a caller needs to fold into its own record
    # (e.g. cycle.json's `failures`/`degraded`) -- distinct from `degraded`,
    # which only reflects per-Cluster summary-text degrades, not every
    # Failure `collect_fn` reported (a batch-level failure can degrade
    # every Cluster without necessarily being one of `degraded_cluster_ids`).
    failures: tuple[Failure, ...] = ()


def collect_summarize(
    batch_id: str,
    clusters: list[dict],
    language: OutputLanguage,
    cycle_id: str,
    data_root: Path = DEFAULT_DATA_ROOT,
    collect_fn: CollectFn = collect_batch,
) -> WrittenSummarize | None:
    """Check `batch_id`'s status once. Returns `None` (writes nothing) if
    the batch has not finished -- the caller retries on a later invocation,
    per AD-11. If it has finished, attaches `summary`/`outbound_url`/
    `outbound_source` to every Cluster exactly as Story 3.1-3.3 established
    and writes `summarized.jsonl`.

    `clusters` must be the same list `submit_summarize` was called with for
    this `batch_id` -- `collect_batch` reassociates results by `cluster_id`
    against exactly this list.
    """
    result: BatchCollectResult = collect_fn(batch_id, clusters)
    if result.status == "pending":
        return None

    destination = _destination(data_root, cycle_id, language)
    output_path = destination / "summarized.jsonl"
    metadata_path = destination / f"{STAGE}.json"

    degraded_cluster_ids: list[str] = []
    unlinked_cluster_ids: list[str] = []
    summarized_out: list[dict] = []
    for cluster in clusters:
        cluster_id = cluster["cluster_id"]
        # One _representative_member call per Cluster, shared between the
        # degrade-text and outbound-link derivations below.
        representative = _representative_member(cluster)

        summary = result.summaries.get(cluster_id)
        if summary is None:
            summary = _degrade_title(cluster, representative)
            degraded_cluster_ids.append(cluster_id)

        # outbound_url/outbound_source (Story 3.3, FR-14) are attached
        # regardless of whether summarization degraded -- a reader always
        # needs somewhere to click through to, independent of whether the
        # AI text is real or a fallback title.
        outbound_url, outbound_source = _select_outbound_link(representative)
        if outbound_url is None:
            unlinked_cluster_ids.append(cluster_id)

        summarized_out.append(
            {
                **cluster,
                "summary": summary,
                "outbound_url": outbound_url,
                "outbound_source": outbound_source,
            }
        )

    write_jsonl(output_path, summarized_out)

    metadata = {
        "stage": STAGE,
        "cycle_id": cycle_id,
        "language": language.value,
        "clusters_in": len(clusters),
        "clusters_summarized": len(summarized_out) - len(degraded_cluster_ids),
        "clusters_degraded": len(degraded_cluster_ids),
        "degraded_cluster_ids": sorted(degraded_cluster_ids),
        # A Cluster with no outbound link is a reader-facing shortfall in
        # its own right (Story 3.3) -- tracked here the same way
        # degraded_cluster_ids tracks a summary-text shortfall, per this
        # file's AD-6/AD-10 philosophy of stating every visible degrade
        # rather than letting it pass silently.
        "clusters_without_outbound_link": len(unlinked_cluster_ids),
        "clusters_without_outbound_link_ids": sorted(unlinked_cluster_ids),
        "failures": [f.to_dict() for f in result.failures],
    }
    write_atomically(
        metadata_path, json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )

    return WrittenSummarize(
        output_path=output_path,
        metadata_path=metadata_path,
        clusters_summarized=len(summarized_out),
        degraded=bool(degraded_cluster_ids),
        failures=tuple(result.failures),
    )


def main(argv: list[str] | None = None) -> int:
    parser = stage_arg_parser(STAGE)
    parser.add_argument(
        "--language", required=True, choices=[lang.value for lang in OutputLanguage]
    )
    parser.add_argument(
        "--batch-id", default=None, help="Collect an already-submitted batch instead of submitting"
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"input not found or not a file: {args.input}", file=sys.stderr)
        return 1

    cycle_id = args.cycle_id or cycle_id_for(datetime.now())
    language = OutputLanguage(args.language)
    clusters = list(read_jsonl(args.input))

    if args.batch_id:
        collected = collect_summarize(
            args.batch_id, clusters, language=language, cycle_id=cycle_id, data_root=args.data_root
        )
        if collected is None:
            print(f"{STAGE}: batch {args.batch_id} not yet complete")
            return 0
        for failure in collected.failures:
            print(f"{STAGE}: degraded — {failure.adapter}: {failure.detail}", file=sys.stderr)
        print(f"{STAGE}: {collected.clusters_summarized} summarized -> {collected.output_path}")
        return 0

    submitted = submit_summarize(
        clusters, language=language, cycle_id=cycle_id, data_root=args.data_root
    )
    if submitted.batch_id is None:
        print(f"{STAGE}: submission failed; see {submitted.metadata_path}", file=sys.stderr)
        return 0
    print(f"{STAGE}: submitted batch {submitted.batch_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
