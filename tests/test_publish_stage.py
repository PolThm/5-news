"""Tests for the publish stage: the final assembly of the 15 Zone x 3
Period x 3 Output Language matrix, and its atomic write to disk (AD-7).

No live network call anywhere here -- publish's inputs are already-computed
ZoneRankings and already-collected per-language summaries, both produced by
prior stages; this module only assembles and writes.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pipeline.config import PERIODS, ZONES
from pipeline.domain import BriefingRecord, OutputLanguage, Period
from pipeline.stages.publish import (
    _SUMMARIZE_OWNED_FIELDS,
    _attach_summary,
    assemble_briefings,
    publish_briefings,
)
from pipeline.stages.rank import ZoneRanking


def _cluster(cluster_id: str, summary: str = "Un resume.") -> dict:
    """No `summary`/`outbound_url`/`outbound_source` here on purpose --
    those are attached by `assemble_briefings` from `summaries_by_language`
    (mirroring the real pipeline: rank/briefing_matrix output never carries
    them; summarize's collected output is what does)."""
    return {
        "cluster_id": cluster_id,
        "members": [{"title": f"title {cluster_id}", "url": f"https://example.com/{cluster_id}"}],
        "independent_source_count": 2,
        "country_count": 2,
        "countries": ["france", "germany"],
        "origin_country": "france",
        "rank": 1,
    }


def _ranking_for_every_zone(clusters: list[dict]) -> list[ZoneRanking]:
    return [
        ZoneRanking(requested_zone=zone, served_zone=zone, ranked_clusters=clusters)
        for zone in ZONES
    ]


def _full_zone_rankings(clusters: list[dict]) -> dict[Period, list[ZoneRanking]]:
    return {period: _ranking_for_every_zone(clusters) for period in PERIODS}


def _full_summaries_by_language(cluster_ids: list[str]) -> dict[OutputLanguage, dict[str, dict]]:
    return {
        language: {
            cid: {
                "summary": f"{language.value} summary for {cid}",
                "outbound_url": f"https://example.com/{cid}",
                "outbound_source": "example.com",
            }
            for cid in cluster_ids
        }
        for language in (OutputLanguage.FR, OutputLanguage.EN, OutputLanguage.ES)
    }


GENERATED_AT = datetime(2026, 8, 11, 6, 0, tzinfo=UTC)


# --- assemble_briefings ------------------------------------------------------


def test_assembles_exactly_24_briefings() -> None:
    clusters = [_cluster("a")]
    zone_rankings = _full_zone_rankings(clusters)
    summaries_by_language = _full_summaries_by_language(["a"])

    briefings = assemble_briefings(zone_rankings, summaries_by_language, generated_at=GENERATED_AT)

    assert len(briefings) == 4 * 2 * 3


def test_every_briefing_carries_the_cycles_generated_at_not_wall_clock() -> None:
    clusters = [_cluster("a")]
    zone_rankings = _full_zone_rankings(clusters)
    summaries_by_language = _full_summaries_by_language(["a"])

    briefings = assemble_briefings(zone_rankings, summaries_by_language, generated_at=GENERATED_AT)

    assert all(b.generated_at == GENERATED_AT for b in briefings)


def test_a_clusters_summary_is_looked_up_per_language() -> None:
    clusters = [_cluster("a")]
    zone_rankings = _full_zone_rankings(clusters)
    summaries_by_language = _full_summaries_by_language(["a"])

    briefings = assemble_briefings(zone_rankings, summaries_by_language, generated_at=GENERATED_AT)

    fr_world_day = next(
        b
        for b in briefings
        if b.language == OutputLanguage.FR and b.zone.slug == "world" and b.period == Period.DAY
    )
    en_world_day = next(
        b
        for b in briefings
        if b.language == OutputLanguage.EN and b.zone.slug == "world" and b.period == Period.DAY
    )

    assert fr_world_day.clusters[0]["summary"] == "fr summary for a"
    assert en_world_day.clusters[0]["summary"] == "en summary for a"


def test_a_clusters_outbound_link_survives_into_the_published_briefing() -> None:
    """FR-14: a reader always has a genuine Article to click through to --
    summarize's collected output carries outbound_url/outbound_source per
    Cluster, and assemble_briefings must not drop them on the way to the
    published Briefing."""
    clusters = [_cluster("a")]
    zone_rankings = _full_zone_rankings(clusters)
    summaries_by_language = _full_summaries_by_language(["a"])

    briefings = assemble_briefings(zone_rankings, summaries_by_language, generated_at=GENERATED_AT)

    world_day_fr = next(
        b
        for b in briefings
        if b.language == OutputLanguage.FR and b.zone.slug == "world" and b.period == Period.DAY
    )

    assert world_day_fr.clusters[0]["outbound_url"] == "https://example.com/a"
    assert world_day_fr.clusters[0]["outbound_source"] == "example.com"


def test_the_score_that_decided_the_order_survives_into_the_published_briefing() -> None:
    """§5.3 asks that a team be able to explain why an item is n°2. That is only
    true if the score reaches the file: computing a breakdown and dropping it
    before publish would leave an ordering nobody can re-derive.

    Publish keeps it because `_attach_summary` spreads the whole cluster, so
    this pins the behaviour rather than adding to it: it fails if publish ever
    grows an allowlist for cluster fields the way it has one for member fields.
    It says nothing about the name `rank` writes -- the rank tests own that.
    """
    scored = {
        **_cluster("a"),
        "score": {
            "total": 0.7531,
            "components": {"freshness": 0.1768, "prominence": 1.0},
            "weights_version": "2026-08-20.1",
        },
    }
    briefings = assemble_briefings(
        _full_zone_rankings([scored]),
        _full_summaries_by_language(["a"]),
        generated_at=GENERATED_AT,
    )

    published = next(
        b
        for b in briefings
        if b.language == OutputLanguage.FR and b.zone.slug == "world" and b.period == Period.DAY
    ).clusters[0]

    assert published["score"]["total"] == 0.7531
    assert published["score"]["weights_version"] == "2026-08-20.1"
    assert published["score"]["components"]["freshness"] == 0.1768


def test_a_cluster_present_in_multiple_zones_is_not_summarized_twice_but_appears_in_both() -> None:
    """The dedup-union fan-out decision (Story 3.5): one Cluster, summarized
    once per language, must still show up correctly in every Zone/Period
    Briefing that selected it."""
    clusters = [_cluster("shared")]
    zone_rankings = _full_zone_rankings(clusters)
    summaries_by_language = _full_summaries_by_language(["shared"])

    briefings = assemble_briefings(zone_rankings, summaries_by_language, generated_at=GENERATED_AT)

    france_briefing = next(
        b
        for b in briefings
        if b.zone.slug == "france" and b.period == Period.DAY and b.language == OutputLanguage.FR
    )
    europe_briefing = next(
        b
        for b in briefings
        if b.zone.slug == "europe" and b.period == Period.DAY and b.language == OutputLanguage.FR
    )
    assert france_briefing.clusters[0]["cluster_id"] == "shared"
    assert europe_briefing.clusters[0]["cluster_id"] == "shared"


def test_a_cluster_missing_from_the_summaries_pool_degrades_to_no_summary_key_change() -> None:
    """A Cluster ranked into a Zone but somehow absent from the summarize
    pool (should not happen, but must not crash) is passed through with
    whatever fields it already carries -- assemble_briefings never invents
    a summary."""
    clusters = [_cluster("orphan")]
    zone_rankings = _full_zone_rankings(clusters)
    summaries_by_language = _full_summaries_by_language([])  # no summaries at all

    briefings = assemble_briefings(zone_rankings, summaries_by_language, generated_at=GENERATED_AT)

    world_day_fr = next(
        b
        for b in briefings
        if b.zone.slug == "world" and b.period == Period.DAY and b.language == OutputLanguage.FR
    )
    assert world_day_fr.clusters[0]["cluster_id"] == "orphan"
    assert "summary" not in world_day_fr.clusters[0]


# --- publish_briefings: atomicity --------------------------------------------


def _briefing(
    zone_slug: str, period: Period, language: OutputLanguage, cluster_id: str
) -> BriefingRecord:
    from pipeline.config import zone_by_slug

    return BriefingRecord(
        zone=zone_by_slug(zone_slug),
        period=period,
        language=language,
        clusters=(_cluster(cluster_id),),
        generated_at=GENERATED_AT,
    )


def test_publish_writes_one_file_per_briefing(tmp_path: Path) -> None:
    briefings = [
        _briefing("world", Period.DAY, OutputLanguage.FR, "a"),
        _briefing("france", Period.WEEK, OutputLanguage.EN, "b"),
    ]

    publish_briefings(briefings, data_root=tmp_path)

    assert (tmp_path / "briefings" / "fr" / "world" / "day.json").is_file()
    assert (tmp_path / "briefings" / "en" / "france" / "week.json").is_file()


def test_published_file_content_matches_the_briefing(tmp_path: Path) -> None:
    briefings = [_briefing("world", Period.DAY, OutputLanguage.FR, "a")]

    publish_briefings(briefings, data_root=tmp_path)

    data = json.loads((tmp_path / "briefings" / "fr" / "world" / "day.json").read_text())
    assert data["clusters"][0]["cluster_id"] == "a"
    assert data["generated_at"] == GENERATED_AT.isoformat()


def test_a_second_successful_publish_fully_replaces_the_first(tmp_path: Path) -> None:
    first = [_briefing("world", Period.DAY, OutputLanguage.FR, "old")]
    publish_briefings(first, data_root=tmp_path)

    second = [_briefing("world", Period.DAY, OutputLanguage.FR, "new")]
    publish_briefings(second, data_root=tmp_path)

    data = json.loads((tmp_path / "briefings" / "fr" / "world" / "day.json").read_text())
    assert data["clusters"][0]["cluster_id"] == "new"


def test_a_second_publish_removes_a_file_the_new_set_no_longer_needs(tmp_path: Path) -> None:
    """If a future cycle's set genuinely differs in shape (e.g. a Zone
    dropped entirely), no stale file from a previous publish should survive
    -- the live tree must always equal exactly the latest complete set."""
    first = [
        _briefing("world", Period.DAY, OutputLanguage.FR, "a"),
        _briefing("france", Period.DAY, OutputLanguage.FR, "b"),
    ]
    publish_briefings(first, data_root=tmp_path)

    second = [_briefing("world", Period.DAY, OutputLanguage.FR, "a")]
    publish_briefings(second, data_root=tmp_path)

    assert not (tmp_path / "briefings" / "fr" / "france" / "day.json").exists()
    assert (tmp_path / "briefings" / "fr" / "world" / "day.json").exists()


def test_a_failure_partway_through_staging_leaves_the_live_tree_untouched(tmp_path: Path) -> None:
    """AD-7: the publish stage writes the whole set or writes nothing --
    verified here by simulating a crash partway through assembling the new
    tree and confirming the previous, already-published tree survives
    byte-identical."""
    first = [_briefing("world", Period.DAY, OutputLanguage.FR, "old")]
    publish_briefings(first, data_root=tmp_path)
    live_path = tmp_path / "briefings" / "fr" / "world" / "day.json"
    original_bytes = live_path.read_bytes()

    class _Boom(Exception):
        pass

    def _raising_serializer(briefing: BriefingRecord) -> dict:
        if briefing.zone.slug == "france":
            raise _Boom("simulated crash mid-staging")
        return briefing.to_dict()

    second = [
        _briefing("world", Period.DAY, OutputLanguage.FR, "new"),
        _briefing("france", Period.DAY, OutputLanguage.FR, "new"),
    ]

    with contextlib.suppress(_Boom):
        publish_briefings(second, data_root=tmp_path, serialize=_raising_serializer)

    assert live_path.read_bytes() == original_bytes, "the previous complete set must be untouched"
    assert not (tmp_path / "briefings" / "fr" / "france" / "day.json").exists()


def test_a_failed_publish_leaves_no_partial_staging_directory_live(tmp_path: Path) -> None:
    """A leftover staging directory is acceptable debris; it must never be
    swapped into the live `briefings/` path."""
    first = [_briefing("world", Period.DAY, OutputLanguage.FR, "old")]
    publish_briefings(first, data_root=tmp_path)

    class _Boom(Exception):
        pass

    def _raising_serializer(briefing: BriefingRecord) -> dict:
        raise _Boom("simulated crash")

    second = [_briefing("world", Period.DAY, OutputLanguage.FR, "new")]

    with contextlib.suppress(_Boom):
        publish_briefings(second, data_root=tmp_path, serialize=_raising_serializer)

    live_dirs = {p.name for p in tmp_path.iterdir()}
    assert "briefings" in live_dirs
    # No staging directory should be mistaken for or promoted to "briefings"
    # itself -- the live directory's content must still be the first,
    # complete publish.
    data = json.loads((tmp_path / "briefings" / "fr" / "world" / "day.json").read_text())
    assert data["clusters"][0]["cluster_id"] == "old"


# --- main() -------------------------------------------------------------


def test_main_exits_nonzero_and_explains_it_has_no_standalone_cli_input(capsys) -> None:
    """publish's real inputs are structured (ZoneRankings + per-language
    summaries), assembled by cycle.py -- not something meaningfully passed
    on a command line. main() exists for the stage-contract convention but
    must fail loudly and explain why, rather than pretending to work."""
    from pipeline.stages.publish import main

    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "cycle" in captured.err


def test_headline_survives_publish_the_summarize_owned_fields_whitelist() -> None:
    """Story 6.1 regression guard, and the reason this test exists at all:
    `_attach_summary` copies only the fields named in
    `_SUMMARIZE_OWNED_FIELDS`, filtered by `if field in summarized`. A field
    that summarize produces but that is missing from that tuple is dropped
    SILENTLY -- no exception, no warning, just an absent key in the published
    JSON that the site then renders as a missing heading.

    Pinned here rather than left to the generic pass-through tests because
    those assert that *cluster* fields survive; `headline` is a
    summarize-owned field, so it travels the whitelist path instead and no
    existing test covered it."""
    cluster = _cluster("a")
    summarized = {
        "a": {
            "cluster_id": "a",
            "headline": "Un cessez-le-feu entre en vigueur",
            "summary": "Les delegations ont confirme un accord.",
            "outbound_url": "https://lemonde.fr/x",
            "outbound_source": "Le Monde",
        }
    }

    attached = _attach_summary(cluster, summarized)

    assert attached["headline"] == "Un cessez-le-feu entre en vigueur"
    assert attached["summary"] == "Les delegations ont confirme un accord."
    # Every summarize-owned field must arrive together -- a partial copy is
    # the failure mode this whitelist exists to make deliberate.
    assert attached["outbound_source"] == "Le Monde"


def test_every_summarize_owned_field_is_actually_copied() -> None:
    """The whitelist and the copy loop must not drift: if a field is added
    to `_SUMMARIZE_OWNED_FIELDS` but the producing stage never emits it, or
    vice versa, this catches it without naming the fields a second time."""
    cluster = _cluster("a")
    summarized = {"a": {"cluster_id": "a", **{f: f"value-{f}" for f in _SUMMARIZE_OWNED_FIELDS}}}

    attached = _attach_summary(cluster, summarized)

    for field_name in _SUMMARIZE_OWNED_FIELDS:
        assert attached[field_name] == f"value-{field_name}", (
            f"{field_name!r} is in _SUMMARIZE_OWNED_FIELDS but was not copied by _attach_summary"
        )


# --- Only facts are published ------------------------------------------------


def test_a_publishers_headline_never_reaches_a_published_briefing() -> None:
    """The design constraint the RSS adapter is built around.

    DSM Recital 57: press-publishers' rights do not extend to hyperlinking or to
    "mere facts reported in press publications" -- but a headline is the
    publisher's own expression and sits inside the right. So a headline is read,
    embedded to group articles covering one event, and handed to the summarizer
    that writes this project's own text, then dropped before anything is written
    to disk. Infopaq is the authority for why the line sits at persistence: an
    11-word extract failed the transient-copy exception once it was *printed*.

    The reader loses nothing -- BriefingPage.astro renders only `member.source`
    and `member.source_country`.
    """
    from pipeline.stages.publish import _attach_summary

    cluster = {
        "cluster_id": "c1",
        "members": [
            {
                "title": "Hind Rajab: l'armée israélienne reconnaît avoir tiré",
                "url": "https://www.lemonde.fr/x",
                "source": "lemonde.fr",
                "source_country": "france",
                "language": "fr",
            }
        ],
        "independent_source_count": 1,
        "country_count": 1,
    }

    published = _attach_summary(cluster, {})
    member = published["members"][0]

    assert "title" not in member, "the publisher's headline must not be persisted"
    # Everything that IS a fact survives, including the link.
    assert member["url"] == "https://www.lemonde.fr/x"
    assert member["source"] == "lemonde.fr"
    assert member["source_country"] == "france"
    assert member["language"] == "fr"


def test_the_summary_and_outbound_link_still_attach_over_facts_only_members() -> None:
    """Stripping headlines must not disturb what summarize owns."""
    from pipeline.stages.publish import _attach_summary

    cluster = {
        "cluster_id": "c1",
        "members": [{"title": "their words", "url": "https://a.example/x", "source": "a.example"}],
    }
    summarized = {
        "c1": {
            "headline": "our own headline",
            "summary": "our own paragraph",
            "outbound_url": "https://a.example/x",
            "outbound_source": "a.example",
        }
    }

    published = _attach_summary(cluster, summarized)

    assert published["headline"] == "our own headline"
    assert published["summary"] == "our own paragraph"
    assert "title" not in published["members"][0]


def test_a_member_missing_optional_fields_is_not_invented() -> None:
    """Fields absent upstream stay absent rather than becoming empty strings --
    a Briefing must not claim a language or country it was never told."""
    from pipeline.stages.publish import _attach_summary

    published = _attach_summary(
        {"cluster_id": "c1", "members": [{"url": "https://a.example/x"}]}, {}
    )

    assert published["members"][0] == {"url": "https://a.example/x"}


def test_every_field_summarize_produces_is_declared_here() -> None:
    """Closes the gap the neighbouring comment claims is already pinned.

    `_attach_summary` copies `if field in summarized`, so a field summarize
    emits but this tuple omits is dropped SILENTLY -- no error, no failing test,
    just an absent key in the published JSON. The existing contract test checks
    the other direction (every declared field is copied), which passes happily
    while a newly produced field vanishes.

    Verified by removing `why_it_matters` and `takeaway` from the tuple: the
    whole suite still passed. It does not any more.

    Derived from the LLM's own output schema plus the two link fields summarize
    attaches itself, so adding a field to that schema without declaring it here
    fails right here.
    """
    from pipeline.adapters.claude import _SUMMARY_SCHEMA

    produced = set(_SUMMARY_SCHEMA["required"]) | {"outbound_url", "outbound_source"}
    missing = produced - set(_SUMMARIZE_OWNED_FIELDS)

    assert not missing, (
        f"summarize produces {sorted(missing)} but publish does not declare them, "
        "so they would be dropped silently from every published Briefing"
    )


def test_discarded_volume_reaches_the_published_briefing_from_the_ranking() -> None:
    """FR-8, wired end to end: `assemble_briefings` must read the real
    per-Zone-per-Period count `rank_for_zone` computed rather than leaving the
    domain's own 0-default in place, which would silently keep the figure dead
    even though the ranking now knows the real number."""
    clusters = [_cluster("a"), _cluster("b")]
    zone_rankings = _full_zone_rankings(clusters)
    for rankings in zone_rankings.values():
        for ranking in rankings:
            object.__setattr__(ranking, "articles_ingested", 42)
    summaries_by_language = _full_summaries_by_language(["a", "b"])

    briefings = assemble_briefings(zone_rankings, summaries_by_language, generated_at=GENERATED_AT)

    world_day_fr = next(
        b
        for b in briefings
        if b.language == OutputLanguage.FR and b.zone.slug == "world" and b.period == Period.DAY
    )
    assert world_day_fr.discarded_ingested == 42
    assert world_day_fr.discarded_kept == 2
