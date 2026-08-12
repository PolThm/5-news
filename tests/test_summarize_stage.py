"""Tests for the summarize stage.

AD-6 is the whole contract here: input is an already-ordered, already-counted
Briefing; output is the same Briefing with one field (`summary`) added. No
live Claude call anywhere — `summarize_fn` is injected, exactly like every
other adapter-boundary test in this pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.adapters import Failure
from pipeline.adapters.claude import SummarizeResult, _prompt_for
from pipeline.domain import OutputLanguage
from pipeline.stages import read_jsonl
from pipeline.stages.summarize import run_summarize


def _ranked_cluster(
    cluster_id: str,
    rank: int,
    members: list[dict] | None = None,
    published_at: str = "2026-08-11T06:00:00+00:00",
) -> dict:
    members = (
        members
        if members is not None
        else [
            {
                "title": f"title for {cluster_id}",
                "url": f"https://a.com/{cluster_id}",
                "source": "a.com",
                "source_country": "france",
                "language": "fr",
                "published_at": published_at,
            },
            {
                "title": f"second title for {cluster_id}",
                "url": f"https://b.com/{cluster_id}",
                "source": "b.com",
                "source_country": "germany",
                "language": "de",
                "published_at": published_at,
            },
        ]
    )
    return {
        "cluster_id": cluster_id,
        "rank": rank,
        "members": members,
        "independent_source_count": 2,
        "country_count": 2,
        "countries": ["france", "germany"],
        "origin_country": "france",
    }


def test_every_cluster_receives_a_summary_field_and_nothing_else_changes() -> None:
    """AD-6: summarize adds Summary text keyed to Cluster identity and may
    not add, remove, reorder, or renumber anything else."""
    clusters = [_ranked_cluster("a", rank=1), _ranked_cluster("b", rank=2)]

    def fake_summarize(clusters_in: list[dict], language: OutputLanguage) -> SummarizeResult:
        return SummarizeResult(summaries={"a": "Resume A.", "b": "Resume B."})

    written = run_summarize(
        clusters, language=OutputLanguage.FR, cycle_id="c1", summarize_fn=fake_summarize
    )
    out = list(read_jsonl(written.output_path))

    assert [c["cluster_id"] for c in out] == ["a", "b"]  # same order
    assert [c["rank"] for c in out] == [1, 2]  # untouched
    for original, produced in zip(clusters, out, strict=True):
        for key, value in original.items():
            assert produced[key] == value, f"field {key!r} must pass through unchanged"
    assert out[0]["summary"] == "Resume A."
    assert out[1]["summary"] == "Resume B."
    # AC2 (Story 3.3): the loop above already covers independent_source_count/
    # country_count/countries/origin_country generically (every original
    # field must survive unchanged) -- named explicitly here so the AC has a
    # direct assertion, not just an incidental one.
    for original, produced in zip(clusters, out, strict=True):
        assert produced["independent_source_count"] == original["independent_source_count"]
        assert produced["country_count"] == original["country_count"]
        assert produced["countries"] == original["countries"]
        assert produced["origin_country"] == original["origin_country"]


def test_the_prompt_receives_member_data_and_a_no_fabrication_instruction() -> None:
    """AC2: verified via prompt content, not live model behavior."""
    cluster = _ranked_cluster("a", rank=1)
    prompt = _prompt_for(cluster, OutputLanguage.FR)

    assert "title for a" in prompt
    assert "a.com" in prompt
    assert "second title for a" in prompt
    assert "b.com" in prompt
    assert "Never invent" in prompt
    assert "named outlet" in prompt


def test_a_failed_cluster_degrades_to_its_earliest_member_title_others_unaffected() -> None:
    """AC3: a summarize failure for one Cluster degrades that item to its
    title; every other Cluster in the same call keeps its real summary."""
    ok_cluster = _ranked_cluster("ok", rank=1)
    bad_cluster = _ranked_cluster(
        "bad",
        rank=2,
        members=[
            {
                "title": "later dispatch",
                "url": "https://later.com/bad",
                "source": "later.com",
                "source_country": "japan",
                "language": "ja",
                "published_at": "2026-08-11T09:00:00+00:00",
            },
            {
                "title": "earliest dispatch",
                "url": "https://earliest.com/bad",
                "source": "earliest.com",
                "source_country": "china",
                "language": "zh",
                "published_at": "2026-08-11T05:00:00+00:00",
            },
        ],
    )
    clusters = [ok_cluster, bad_cluster]

    def fake_summarize(clusters_in: list[dict], language: OutputLanguage) -> SummarizeResult:
        return SummarizeResult(
            summaries={"ok": "Tout va bien."},
            failures=[Failure("claude", "cluster bad: batch result was 'errored'")],
        )

    written = run_summarize(
        clusters, language=OutputLanguage.FR, cycle_id="c1", summarize_fn=fake_summarize
    )
    out = {c["cluster_id"]: c for c in read_jsonl(written.output_path)}

    assert out["ok"]["summary"] == "Tout va bien."
    # Degrades to the earliest-published member's title, not members[0]
    # (which is sorted by title, not publish order) and not the failure text.
    assert out["bad"]["summary"] == "earliest dispatch"

    metadata = json.loads(written.metadata_path.read_text())
    assert metadata["clusters_degraded"] == 1
    assert metadata["degraded_cluster_ids"] == ["bad"]


def test_degrade_tiebreak_on_equal_publish_time_matches_coverage_for_clusters_convention() -> None:
    """cluster.py's coverage_for_cluster tiebreaks on (published_at, url) --
    NOT title -- when publish times tie. Constructed so title-order and
    url-order disagree: if this stage's degrade path used title as the
    tiebreak, it would pick the wrong member."""
    tied_cluster = _ranked_cluster(
        "tied",
        rank=1,
        members=[
            {
                "title": "Z later-sorting title",
                "url": "https://a-first.com/x",  # url sorts first
                "source": "a-first.com",
                "source_country": "france",
                "language": "fr",
                "published_at": "2026-08-11T06:00:00+00:00",  # same instant
            },
            {
                "title": "A earlier-sorting title",
                "url": "https://z-second.com/x",  # url sorts second
                "source": "z-second.com",
                "source_country": "germany",
                "language": "de",
                "published_at": "2026-08-11T06:00:00+00:00",  # same instant
            },
        ],
    )

    def fake_summarize(clusters_in: list[dict], language: OutputLanguage) -> SummarizeResult:
        return SummarizeResult(failures=[Failure("claude", "cluster tied: errored")])

    written = run_summarize(
        [tied_cluster], language=OutputLanguage.FR, cycle_id="c1", summarize_fn=fake_summarize
    )
    out = list(read_jsonl(written.output_path))[0]

    assert out["summary"] == "Z later-sorting title"  # the (published_at, url)-earliest member


def test_a_non_degraded_cluster_carries_the_earliest_published_members_outbound_link() -> None:
    """AC1: every item carries an outbound link and Source name, selected by
    the same (published_at, url)-earliest convention _earliest_member_title
    already uses for the degrade path -- applied here for the ordinary,
    non-degraded case too."""
    cluster = _ranked_cluster(
        "a",
        rank=1,
        members=[
            {
                "title": "later dispatch",
                "url": "https://later.com/x",
                "source": "later.com",
                "source_country": "japan",
                "language": "ja",
                "published_at": "2026-08-11T09:00:00+00:00",
            },
            {
                "title": "earliest dispatch",
                "url": "https://earliest.com/x",
                "source": "earliest.com",
                "source_country": "china",
                "language": "zh",
                "published_at": "2026-08-11T05:00:00+00:00",
            },
        ],
    )

    def fake_summarize(clusters_in: list[dict], language: OutputLanguage) -> SummarizeResult:
        return SummarizeResult(summaries={"a": "Un resume reel."})

    written = run_summarize(
        [cluster], language=OutputLanguage.FR, cycle_id="c1", summarize_fn=fake_summarize
    )
    out = list(read_jsonl(written.output_path))[0]

    assert out["summary"] == "Un resume reel."
    assert out["outbound_url"] == "https://earliest.com/x"
    assert out["outbound_source"] == "earliest.com"


def test_a_degraded_cluster_still_carries_a_correct_outbound_link() -> None:
    """The degrade path only replaces `summary` -- attribution fields must
    still point somewhere real, so a reader always has a link to click
    through to regardless of whether the AI text is real or a fallback."""
    cluster = _ranked_cluster(
        "bad",
        rank=1,
        members=[
            {
                "title": "later dispatch",
                "url": "https://later.com/bad",
                "source": "later.com",
                "source_country": "japan",
                "language": "ja",
                "published_at": "2026-08-11T09:00:00+00:00",
            },
            {
                "title": "earliest dispatch",
                "url": "https://earliest.com/bad",
                "source": "earliest.com",
                "source_country": "china",
                "language": "zh",
                "published_at": "2026-08-11T05:00:00+00:00",
            },
        ],
    )

    def fake_summarize(clusters_in: list[dict], language: OutputLanguage) -> SummarizeResult:
        return SummarizeResult(failures=[Failure("claude", "cluster bad: errored")])

    written = run_summarize(
        [cluster], language=OutputLanguage.FR, cycle_id="c1", summarize_fn=fake_summarize
    )
    out = list(read_jsonl(written.output_path))[0]

    assert out["summary"] == "earliest dispatch"  # the degrade text
    assert out["outbound_url"] == "https://earliest.com/bad"
    assert out["outbound_source"] == "earliest.com"


def test_a_cluster_with_no_members_degrades_outbound_link_to_none_not_a_crash() -> None:
    """The link_across_days history-only-clique case (Story 3.1's Task 0)
    legitimately produces a Cluster with an empty members list. There is no
    Article to link to -- degrade to None, don't crash, don't fabricate."""
    cluster = _ranked_cluster("history-only", rank=1, members=[])

    def fake_summarize(clusters_in: list[dict], language: OutputLanguage) -> SummarizeResult:
        return SummarizeResult(summaries={"history-only": "Un resume."})

    written = run_summarize(
        [cluster], language=OutputLanguage.FR, cycle_id="c1", summarize_fn=fake_summarize
    )
    out = list(read_jsonl(written.output_path))[0]

    assert out["outbound_url"] is None
    assert out["outbound_source"] is None


def test_a_cluster_with_no_members_and_a_failed_summarize_degrades_both_fields() -> None:
    """The most degraded state a Cluster can be in: no members to link to,
    and summarization also failed. Both the summary-text fallback (its own
    cluster_id, per _earliest_member_title's None-representative branch) and
    the outbound-link fallback (None, None) must hold simultaneously --
    never exercised together before this test."""
    cluster = _ranked_cluster("history-only", rank=1, members=[])

    def fake_summarize(clusters_in: list[dict], language: OutputLanguage) -> SummarizeResult:
        return SummarizeResult(failures=[Failure("claude", "cluster history-only: errored")])

    written = run_summarize(
        [cluster], language=OutputLanguage.FR, cycle_id="c1", summarize_fn=fake_summarize
    )
    out = list(read_jsonl(written.output_path))[0]

    assert out["summary"] == "history-only"  # falls back to cluster_id
    assert out["outbound_url"] is None
    assert out["outbound_source"] is None


def test_a_member_missing_source_degrades_that_clusters_link_not_the_whole_cycle() -> None:
    """AD-10's degrade-not-abort principle must hold here too: a malformed
    upstream member (missing `source`) must not crash the whole summarize
    call -- it should degrade only that Cluster's outbound link."""
    ok_cluster = _ranked_cluster("ok", rank=1)
    malformed_cluster = _ranked_cluster(
        "malformed",
        rank=2,
        members=[
            {
                "title": "no source field",
                "url": "https://a.com/malformed",
                "source_country": "france",
                "language": "fr",
                "published_at": "2026-08-11T06:00:00+00:00",
                # "source" deliberately omitted
            }
        ],
    )
    clusters = [ok_cluster, malformed_cluster]

    def fake_summarize(clusters_in: list[dict], language: OutputLanguage) -> SummarizeResult:
        return SummarizeResult(summaries={"ok": "Ca va.", "malformed": "Aussi resume."})

    written = run_summarize(
        clusters, language=OutputLanguage.FR, cycle_id="c1", summarize_fn=fake_summarize
    )
    out = {c["cluster_id"]: c for c in read_jsonl(written.output_path)}

    assert out["ok"]["outbound_url"] is not None
    assert out["malformed"]["outbound_url"] == "https://a.com/malformed"
    assert out["malformed"]["outbound_source"] is None


def test_an_empty_string_url_or_source_degrades_to_none_not_a_broken_link() -> None:
    """A present-but-empty string is a different failure mode than a missing
    key -- both must degrade to None rather than pass through a falsy value
    that would render as a broken empty href on the display side."""
    cluster = _ranked_cluster(
        "a",
        rank=1,
        members=[
            {
                "title": "X",
                "url": "",
                "source": "",
                "source_country": "france",
                "language": "fr",
                "published_at": "2026-08-11T06:00:00+00:00",
            }
        ],
    )

    def fake_summarize(clusters_in: list[dict], language: OutputLanguage) -> SummarizeResult:
        return SummarizeResult(summaries={"a": "Un resume."})

    written = run_summarize(
        [cluster], language=OutputLanguage.FR, cycle_id="c1", summarize_fn=fake_summarize
    )
    out = list(read_jsonl(written.output_path))[0]

    assert out["outbound_url"] is None
    assert out["outbound_source"] is None


def test_metadata_records_how_many_clusters_lack_an_outbound_link() -> None:
    """AD-6/AD-10's philosophy throughout this file is to state every
    visible shortfall in metadata, never degrade silently -- a Cluster with
    no outbound link is exactly this kind of reader-facing shortfall, and
    deserves the same visibility degraded_cluster_ids already gives
    summary-text degrades."""
    linked_cluster = _ranked_cluster("linked", rank=1)
    unlinked_cluster = _ranked_cluster("unlinked", rank=2, members=[])

    def fake_summarize(clusters_in: list[dict], language: OutputLanguage) -> SummarizeResult:
        return SummarizeResult(summaries={"linked": "Ok.", "unlinked": "Ok aussi."})

    written = run_summarize(
        [linked_cluster, unlinked_cluster],
        language=OutputLanguage.FR,
        cycle_id="c1",
        summarize_fn=fake_summarize,
    )
    metadata = json.loads(written.metadata_path.read_text())

    assert metadata["clusters_without_outbound_link"] == 1
    assert metadata["clusters_without_outbound_link_ids"] == ["unlinked"]


def test_a_singleton_member_cluster_is_summarized_without_claiming_two_sources() -> None:
    """A Cluster with fewer than 2 members is legitimate (Continent fallback,
    cross-day linking) even though every ranked Cluster met the 2+
    Independent Source floor -- member count and Independent Source count
    are not always the same number."""
    singleton = _ranked_cluster(
        "solo",
        rank=1,
        members=[
            {
                "title": "only dispatch",
                "url": "https://only.com/solo",
                "source": "only.com",
                "source_country": "brazil",
                "language": "pt",
                "published_at": "2026-08-11T06:00:00+00:00",
            }
        ],
    )
    prompt = _prompt_for(singleton, OutputLanguage.FR)

    # A singleton-member prompt must never claim two sources -- the
    # two-source instruction ("synthesizing what these Articles agree on")
    # is exclusive to the 2+-member branch and must be genuinely absent here.
    assert "these Articles agree on" not in prompt
    assert "do not imply a second source confirmed" in prompt
    assert "only one Article" in prompt or "Only one Article" in prompt


def test_a_title_containing_a_quote_does_not_break_out_of_its_delimiter() -> None:
    """Article titles come from many uncontrolled international sources
    (RSS/GDELT) and are concatenated directly into the prompt. A title
    containing a double-quote must not be able to prematurely close its
    delimiter and blend into the surrounding instruction text."""
    cluster = _ranked_cluster(
        "a",
        rank=1,
        members=[
            {
                "title": 'Minister says "we will respond" to crisis',
                "url": "https://a.com/x",
                "source": "a.com",
                "source_country": "france",
                "language": "fr",
                "published_at": "2026-08-11T06:00:00+00:00",
            }
        ],
    )
    prompt = _prompt_for(cluster, OutputLanguage.FR)

    # The escaped quote must appear as \" (an escaped literal), not as a bare
    # " that would close the surrounding delimiter early.
    assert '\\"we will respond\\"' in prompt


def test_empty_input_produces_empty_output(tmp_path: Path) -> None:
    def fake_summarize(clusters_in: list[dict], language: OutputLanguage) -> SummarizeResult:
        return SummarizeResult()

    written = run_summarize(
        [],
        language=OutputLanguage.FR,
        cycle_id="c1",
        data_root=tmp_path,
        summarize_fn=fake_summarize,
    )
    out = list(read_jsonl(written.output_path))

    assert out == []
    metadata = json.loads(written.metadata_path.read_text())
    assert metadata["clusters_in"] == 0
    assert metadata["clusters_summarized"] == 0
