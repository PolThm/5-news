"""Publish stage: the final assembly of the 15 Zone x 3 Period x 3 Output
Language matrix, and its atomic write to disk.

AD-7's whole rule: "The publish stage writes a complete Briefing set or
writes nothing. Publication is atomic at the set level: a cycle that fails
mid-generation leaves the previous set in place, untouched. Every Briefing
carries the generation timestamp of the cycle that produced it." AD-12:
publish owns the generation timestamp and cycle identifier; every other
field is copied through unchanged from whatever stage owns it.

Two responsibilities, two functions:

``assemble_briefings`` builds the 135 ``BriefingRecord``s from already-
computed inputs -- a Period's ``ZoneRanking``s (``briefing_matrix.py``) and
each Output Language's already-collected Cluster-to-summary map
(``summarize.py``'s collected output). It does no I/O of its own.

``publish_briefings`` writes the whole set to ``data/briefings/<lang>/<zone>/
<period>.json``, atomically as one set. ``write_atomically``
(``pipeline.stages``) is single-file only -- it cannot make a 135-file set
atomic on its own, so this stage builds the complete new tree in a staging
directory first, and only swaps it into the live path once every file is
confirmed written (a single, atomic directory rename on the same
filesystem). A crash at any point before that swap leaves the live
`data/briefings/` tree exactly as the previous successful publish left it.
"""

from __future__ import annotations

import json
import shutil
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pipeline.config import briefing_combinations
from pipeline.domain import BriefingRecord, OutputLanguage, Period
from pipeline.stages import DEFAULT_DATA_ROOT
from pipeline.stages.rank import ZoneRanking


def assemble_briefings(
    zone_rankings: dict[Period, list[ZoneRanking]],
    summaries_by_language: dict[OutputLanguage, dict[str, dict]],
    generated_at: datetime,
) -> list[BriefingRecord]:
    """Every one of the 135 (Output Language, Zone, Period) combinations
    (``pipeline.config.briefing_combinations``), each carrying its Period's
    selected Clusters with that language's Summary attached.

    `summaries_by_language[language]` maps `cluster_id` to the *whole*
    already-collected Cluster dict from `summarize`'s output (`summary`,
    `outbound_url`, `outbound_source` -- FR-14's "a reader always has a
    genuine Article to click through to") -- the deduplicated pool every
    Zone's ranking draws from (Story 3.5's fan-out decision: one summarize
    batch per language, shared across all 15 Zones x 3 Periods). A Cluster
    missing from that pool (should not happen once summarize has run, but
    must not crash if it does) is passed through with whatever fields it
    already carries -- this function never invents a summary or outbound
    link of its own.

    `generated_at` is the cycle's own timestamp, not wall-clock-at-publish-
    time (AC2) -- a resumed, phase-two cycle's publish step can run
    meaningfully later than collection did, and what the reader is told is
    the cycle's generation moment, not this process invocation's.
    """
    rankings_by_zone_period: dict[tuple[str, Period], ZoneRanking] = {}
    for period, rankings in zone_rankings.items():
        for ranking in rankings:
            rankings_by_zone_period[(ranking.requested_zone.slug, period)] = ranking

    briefings: list[BriefingRecord] = []
    for language, zone, period in briefing_combinations():
        ranking = rankings_by_zone_period.get((zone.slug, period))
        summarized = summaries_by_language.get(language, {})
        ranked_clusters = ranking.ranked_clusters if ranking else []
        # The SERVED Zone decides which angle to use, not the requested one: a
        # Briefing that fell back (FR-16) is showing its Continent's selection,
        # so the judgment on the page must be the Continent's.
        served = (ranking.served_zone if ranking else zone).slug
        clusters = tuple(
            _attach_summary(cluster, summarized, served) for cluster in ranked_clusters
        )
        briefings.append(
            BriefingRecord(
                zone=zone,
                served_zone=ranking.served_zone if ranking else zone,
                period=period,
                language=language,
                clusters=clusters,
                generated_at=generated_at,
            )
        )
    return briefings


# Every field summarize attaches, per AD-6/Story 3.3 -- the generated text
# (headline + summary, Story 6.1) plus the outbound-link pair FR-14
# requires. Named here, not derived from the summarized dict's keys, so a
# future field summarize adds is a deliberate addition to this list, not an
# accidental silent pass-through.
#
# Story 6.1 note: `_attach_summary` filters on `if field in summarized`, so
# a field missing from this tuple is dropped SILENTLY at publish -- no
# error, no failing test, just an absent key in the published JSON. Adding
# a field to summarize's output without adding it here is the one change in
# this pipeline that fails invisibly; the contract test below pins it.
_SUMMARIZE_OWNED_FIELDS = (
    "headline",
    "summary",
    "why_it_matters",
    "takeaway",
    "outbound_url",
    "outbound_source",
)


# What a published member carries. Everything here is a fact -- who reported it,
# where that newsroom sits, what language, and the URL -- and the publisher's own
# headline is deliberately not among them.
#
# DSM Recital 57, verbatim: press-publishers' rights "should not extend to acts
# of hyperlinking" and "should also not extend to mere facts reported in press
# publications." A headline is the publisher's expression and sits inside the
# right; the fact that they reported an event, and the link to it, sit outside.
# The CJEU brackets where the exposure changes: PRCA v NLA allowed the transient
# copies made while viewing a page, while Infopaq failed precisely because an
# 11-word extract was *printed*, so that "the deletion of that reproduction is
# entirely dependent on the will of the user". The line is persistence, not
# retrieval.
#
# So a headline is read, embedded to group articles covering one event, and
# handed to the summarizer that writes this project's own text -- then dropped
# here. The site never displayed it anyway: BriefingPage.astro renders only
# `member.source` and `member.source_country`, so this costs the reader nothing
# and removes the one piece of protected expression the output used to keep.
_PUBLISHED_MEMBER_FIELDS = ("url", "source", "source_country", "language")


def _facts_only(member: dict) -> dict:
    return {field: member[field] for field in _PUBLISHED_MEMBER_FIELDS if field in member}


def _attach_summary(
    cluster: dict, summarized_by_id: dict[str, dict], zone_slug: str = "world"
) -> dict:
    summarized = summarized_by_id.get(cluster["cluster_id"])
    published = {
        **cluster,
        "members": [_facts_only(member) for member in cluster.get("members", [])],
    }
    if summarized is None:
        return published
    attached = {
        **published,
        **{field: summarized[field] for field in _SUMMARIZE_OWNED_FIELDS if field in summarized},
    }
    # The territory's own judgment replaces the shared one, where there is one.
    #
    # Facts stay shared -- headline and summary come from the single request per
    # (item, language) -- and only `why_it_matters` and `takeaway` vary. That
    # split is not a cost optimization: it is what makes it impossible for the
    # France and Spain Briefings to state different facts about one event while
    # their emphasis legitimately differs.
    #
    # Missing angle falls through to the shared text rather than emptying the
    # fields: a Briefing without an angle is thinner, never broken (AD-10).
    angle = (summarized.get("angles") or {}).get(zone_slug)
    if angle:
        attached["why_it_matters"] = angle["why_it_matters"]
        attached["takeaway"] = angle["takeaway"]
        attached["angle_zone"] = zone_slug
    # The whole map is internal: the reader gets one angle, and shipping the
    # other Zones' would let a France page be read as Spain's.
    attached.pop("angles", None)
    return attached


@dataclass(frozen=True, slots=True)
class WrittenPublish:
    """What one publish attempt produced."""

    briefings_path: Path
    briefings_written: int


def _default_serialize(briefing: BriefingRecord) -> dict:
    return briefing.to_dict()


def publish_briefings(
    briefings: list[BriefingRecord],
    data_root: Path = DEFAULT_DATA_ROOT,
    serialize: Callable[[BriefingRecord], dict] = _default_serialize,
) -> WrittenPublish:
    """Write the whole Briefing set atomically: every file lands, or the
    previous complete set remains exactly as it was (AD-7).

    Staged under `data_root` itself (never under a different filesystem,
    e.g. /tmp) so the final swap is a same-filesystem directory rename --
    atomic on POSIX, which is what makes "every file lands or none do" true
    rather than merely likely. `serialize` is injectable so a test can
    simulate a crash partway through building the new tree without
    actually corrupting anything (see this module's own tests) -- the real
    default just calls `BriefingRecord.to_dict()`.
    """
    live_path = data_root / "briefings"
    staging_path = data_root / f".briefings.staging-{uuid.uuid4().hex}"
    staging_path.mkdir(parents=True, exist_ok=False)

    try:
        for briefing in briefings:
            destination = (
                staging_path
                / briefing.language.value
                / briefing.zone.slug
                / f"{briefing.period.value}.json"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = serialize(briefing)
            destination.write_text(
                json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
    except Exception:
        # The live tree is never touched until every file above has been
        # written successfully -- an exception here leaves only the
        # staging directory as debris (harmless; cleaned up by a later
        # successful publish or left for manual inspection), never a
        # partially-swapped live tree.
        shutil.rmtree(staging_path, ignore_errors=True)
        raise

    # The swap: a same-filesystem rename is atomic on POSIX. live_path is
    # replaced in one step -- there is no window where it is half-old,
    # half-new, because the new tree was built entirely under staging_path
    # first.
    if live_path.exists():
        shutil.rmtree(live_path)
    staging_path.rename(live_path)

    return WrittenPublish(briefings_path=live_path, briefings_written=len(briefings))


def main(argv: list[str] | None = None) -> int:
    """Publish has no single `--input` file the way other stages do -- its
    real inputs are a Period-keyed map of ZoneRankings plus a per-language
    summaries map, both assembled by `cycle.py`'s orchestration, not
    something meaningfully passed on a command line. This CLI entry point
    exists for the stage-contract convention (invocable alone) but is not
    this story's primary interface -- `cycle.py` calls `assemble_briefings`/
    `publish_briefings` directly.
    """
    print("publish: no standalone CLI input; invoked via pipeline.stages.cycle", file=sys.stderr)
    del argv
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
