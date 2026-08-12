"""Dedupe stage, layer 1: collapse verbatim reprints.

The cheapest and largest slice of wire-copy inflation. A Reuters dispatch
republished under an identical headline by thirty outlets is one story covered
once, not thirty independent confirmations — and the Consensus Score is both
the ranking input and the number shown to the reader as proof (AD-5).

This stage is the ONLY place that decides what counts as an Independent Source.
Every later stage consumes its verdict and never recounts (AD-12).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pipeline.adapters import Failure
from pipeline.adapters.cohere_embed import EmbeddingResult
from pipeline.domain import ArticleRecord
from pipeline.stages.dedupe import (
    ArticleGroup,
    group_by_title,
    normalize_title,
    run_dedupe,
)


def _no_embed(titles: list[str]) -> EmbeddingResult:
    """These tests exercise layers 1 (title) and 2 (agency), not layer 3
    (rewrite detection, Story 2.4) — a stub that always reports failure
    short-circuits run_dedupe's rewrite-detection pass immediately, with no
    network attempt, leaving layer 1+2 output untouched for these tests to
    assert on. Story 2.4's own tests call merge_by_rewrite_detection and
    run_dedupe directly with purpose-built embeddings instead."""
    return EmbeddingResult(failures=[Failure("cohere_embed", "not used in this test")])


def _record(
    title: str,
    source: str,
    country: str = "france",
    url: str | None = None,
    language: str = "fr",
    wire_agency: str | None = None,
) -> ArticleRecord:
    return ArticleRecord(
        title=title,
        url=url or f"https://{source}/{abs(hash(title + source))}",
        published_at=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
        source=source,
        source_country=country,
        language=language,
        collected_by="gdelt",
        wire_agency=wire_agency,
    )


# --- Title normalization -----------------------------------------------------


def test_normalization_ignores_case_and_whitespace() -> None:
    assert normalize_title("Ceasefire  Agreed") == normalize_title("ceasefire agreed")


def test_normalization_ignores_punctuation() -> None:
    """Outlets differ on dashes, quotes, and trailing periods for the same wire
    headline."""
    assert normalize_title("Ceasefire agreed, sources say.") == normalize_title(
        "Ceasefire agreed — sources say"
    )


def test_normalization_strips_a_trailing_outlet_suffix() -> None:
    """Syndicated headlines carry the republisher's name appended, in whatever
    punctuation and casing that outlet happens to use. All of these are the
    same dispatch and must land in one group."""
    for variant in (
        "Ceasefire agreed | Reuters",
        "Ceasefire agreed - BBC News",
        "Ceasefire agreed-Reuters",
        "Ceasefire agreed | reuters",
        "Ceasefire agreed — AFP",
    ):
        assert normalize_title(variant) == normalize_title("Ceasefire agreed"), variant


def test_normalization_keeps_a_real_attribution_tail() -> None:
    """The trap this layer must not fall into: wire headlines routinely end in
    an attribution that IS the story. "Ukraine strikes back - Zelensky" and
    "Ukraine strikes back - Pentagon" are different dispatches, and merging
    them would delete real coverage from the Consensus Score.

    Matching a known-outlet list rather than a shape is what makes this
    possible — no "capitalized words after a dash" rule can tell Zelensky from
    Reuters.
    """
    assert normalize_title("Ukraine strikes back - Zelensky") != normalize_title(
        "Ukraine strikes back - Pentagon"
    )
    assert "zelensky" in normalize_title("Ukraine strikes back - Zelensky")
    assert "un" in normalize_title("Death toll rises - UN")
    assert "officials say" in normalize_title("Fire contained — Officials Say")


def test_normalization_keeps_genuinely_different_headlines_apart() -> None:
    """The layer must not collapse independent reporting — that would understate
    real consensus, which is the opposite failure and just as bad."""
    assert normalize_title("Ceasefire agreed in Gaza") != normalize_title(
        "Ceasefire talks collapse in Gaza"
    )


def test_normalization_is_stable() -> None:
    assert normalize_title("Ceasefire agreed") == normalize_title("Ceasefire agreed")


# --- Grouping ----------------------------------------------------------------


def test_two_sources_with_identical_titles_count_once() -> None:
    """AC: two Articles from different Sources with near-identical titles
    contribute 1 to the Independent Source count, not 2."""
    groups = group_by_title(
        [
            _record("Ceasefire agreed", "reuters.com", "united-kingdom"),
            _record("Ceasefire agreed", "lemonde.fr", "france"),
        ]
    )

    assert len(groups) == 1
    assert groups[0].independent_source_count == 1


def test_different_stories_stay_separate() -> None:
    groups = group_by_title(
        [
            _record("Ceasefire agreed", "reuters.com"),
            _record("Markets rally on tech earnings", "ft.com"),
        ]
    )

    assert len(groups) == 2


def test_the_same_source_twice_is_still_one_source() -> None:
    """An outlet republishing its own story is not two independent sources."""
    groups = group_by_title(
        [
            _record("Ceasefire agreed", "lemonde.fr", url="https://lemonde.fr/1"),
            _record("Ceasefire agreed", "lemonde.fr", url="https://lemonde.fr/2"),
        ]
    )

    assert groups[0].independent_source_count == 1


def test_distinct_headlines_from_distinct_sources_count_separately() -> None:
    """Independent reporting of the same event produces different headlines and
    must survive as separate Independent Sources — this layer only collapses
    verbatim reprints."""
    groups = group_by_title(
        [
            _record("Ceasefire agreed after all-night talks", "reuters.com", "united-kingdom"),
            _record("Both sides announce truce in surprise deal", "lemonde.fr", "france"),
        ]
    )

    assert len(groups) == 2
    assert all(g.independent_source_count == 1 for g in groups)


# --- Counts written for downstream ------------------------------------------


def test_coverage_counts_distinct_dispatches_not_articles() -> None:
    """Three genuinely different headlines from three countries is three-source,
    three-country coverage — this is what real consensus looks like."""
    groups = group_by_title(
        [
            _record("Storm hits coast", "reuters.com", "united-kingdom"),
            _record("Different angle on the storm", "lemonde.fr", "france"),
            _record("Another take entirely", "spiegel.de", "germany"),
        ]
    )
    coverage = ArticleGroup.merge_all(groups)

    assert coverage.independent_source_count == 3
    assert coverage.country_count == 3


def test_coverage_country_count_is_distinct_countries() -> None:
    """Two independent British outlets are two sources but one country — the
    two numbers measure different things and FR-6 uses both."""
    groups = group_by_title(
        [
            _record("A", "bbc.co.uk", "united-kingdom"),
            _record("B", "theguardian.com", "united-kingdom"),
        ]
    )
    coverage = ArticleGroup.merge_all(groups)

    assert coverage.independent_source_count == 2
    assert coverage.country_count == 1


def test_collapsed_reprints_do_not_inflate_the_country_count() -> None:
    """The failure this whole layer exists to prevent: one dispatch republished
    across twelve countries must not read as twelve-country consensus."""
    reprints = [
        _record("Ceasefire agreed", f"outlet{i}.com", country)
        for i, country in enumerate(["france", "germany", "japan", "brazil", "india", "china"])
    ]
    groups = group_by_title(reprints)

    assert len(groups) == 1
    assert groups[0].independent_source_count == 1
    assert groups[0].country_count == 1


# --- Stage output ------------------------------------------------------------


def test_writes_deduplicated_records_with_counts(tmp_path: Path) -> None:
    source = tmp_path / "articles.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(r.to_dict(), sort_keys=True)
            for r in [
                _record("Ceasefire agreed", "reuters.com", "united-kingdom"),
                _record("Ceasefire agreed", "lemonde.fr", "france"),
                _record("Markets rally", "ft.com", "united-kingdom"),
            ]
        )
        + "\n"
    )

    written = run_dedupe(
        source, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path, embed=_no_embed
    )

    lines = written.output_path.read_text().splitlines()
    assert len(lines) == 2, "two distinct stories survive"
    records = [json.loads(line) for line in lines]
    assert all("independent_source_count" in r for r in records)
    assert all("country_count" in r for r in records)


def test_rerun_is_byte_identical(tmp_path: Path) -> None:
    """AC: given an identical input file, the output is byte-identical."""
    source = tmp_path / "articles.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(r.to_dict(), sort_keys=True)
            for r in [
                _record("Zeta story", "z.com", "france"),
                _record("Alpha story", "a.com", "germany"),
                _record("Zeta story", "y.com", "japan"),
            ]
        )
        + "\n"
    )

    first = run_dedupe(source, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path, embed=_no_embed)
    content = first.output_path.read_text()
    second = run_dedupe(
        source, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path, embed=_no_embed
    )

    assert second.output_path.read_text() == content


def test_output_ordering_does_not_depend_on_input_ordering(tmp_path: Path) -> None:
    """Determinism means a reordered input yields the same output — otherwise
    cycle-to-cycle diffs during the inspection window are pure noise."""
    records = [
        _record("Beta", "b.com", "france"),
        _record("Alpha", "a.com", "germany"),
        _record("Gamma", "c.com", "japan"),
    ]

    forward = tmp_path / "fwd.jsonl"
    forward.write_text("\n".join(json.dumps(r.to_dict(), sort_keys=True) for r in records) + "\n")
    reverse = tmp_path / "rev.jsonl"
    reverse.write_text(
        "\n".join(json.dumps(r.to_dict(), sort_keys=True) for r in reversed(records)) + "\n"
    )

    a = run_dedupe(
        forward, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path / "a", embed=_no_embed
    )
    b = run_dedupe(
        reverse, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path / "b", embed=_no_embed
    )

    assert a.output_path.read_text() == b.output_path.read_text()


def test_records_what_it_collapsed(tmp_path: Path) -> None:
    """The inspection window needs to see how much inflation was removed, not
    just the result — that ratio is the evidence the layer is working."""
    source = tmp_path / "articles.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(r.to_dict(), sort_keys=True)
            for r in [
                _record("Ceasefire agreed", "a.com", "france"),
                _record("Ceasefire agreed", "b.com", "germany"),
                _record("Ceasefire agreed", "c.com", "japan"),
            ]
        )
        + "\n"
    )

    written = run_dedupe(
        source, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path, embed=_no_embed
    )

    meta = json.loads(written.metadata_path.read_text())
    assert meta["articles_in"] == 3
    assert meta["groups_out"] == 1
    assert meta["collapsed"] == 2


def test_empty_input_is_not_a_failure(tmp_path: Path) -> None:
    """A cycle where every upstream was down still runs dedupe — on nothing."""
    source = tmp_path / "articles.jsonl"
    source.write_text("")

    written = run_dedupe(
        source, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path, embed=_no_embed
    )

    assert written.output_path.read_text() == ""
    meta = json.loads(written.metadata_path.read_text())
    assert meta["articles_in"] == 0


def test_one_dispatch_across_twelve_countries_is_not_twelve_country_consensus() -> None:
    """The product's central failure mode, pinned.

    "Covered by 34 sources across 12 countries" is simultaneously the ranking
    input and the proof shown to the reader. If a single wire dispatch can
    produce that number, both break at once — and the reader has no way to see
    it. Layer 1 is the cheapest defense against it.
    """
    countries = [
        "france",
        "germany",
        "japan",
        "brazil",
        "india",
        "china",
        "united-states",
        "united-kingdom",
        "france",
        "germany",
        "japan",
        "brazil",
    ]
    reprints = [
        _record("Ceasefire agreed", f"outlet{i}.com", country)
        for i, country in enumerate(countries)
    ]

    groups = group_by_title(reprints)
    coverage = ArticleGroup.merge_all(groups)

    assert len(groups) == 1, "one dispatch"
    assert coverage.independent_source_count == 1
    assert coverage.country_count == 1, "not 8, and certainly not 12"


# --- Wire-agency attribution merge (Story 2.3, FR-10 layer 2) ----------------


def test_two_agency_attributed_near_miss_titles_merge() -> None:
    """Same agency AND similar (but not identical-after-normalization) titles
    is the corroborating-evidence case this layer exists for — e.g. two
    slightly different local translations/edits of one AFP dispatch."""
    from pipeline.stages.dedupe import merge_by_agency

    a = _record("Ceasefire declared in the region", "outlet-a.com", wire_agency="AFP")
    b = _record(
        "Ceasefire declared across the region",
        "outlet-b.com",
        url="https://outlet-b.com/x",
        wire_agency="AFP",
    )

    groups = group_by_title([a, b])
    assert len(groups) == 2, "titles differ enough that layer 1 alone keeps them separate"

    merged = merge_by_agency(groups)
    assert len(merged) == 1
    assert merged[0].independent_source_count == 1


def test_same_agency_but_unrelated_titles_do_not_merge() -> None:
    """The false-merge guard: two different Reuters stories on the same day
    share wire_agency="Reuters" but are not the same Event. Agency alone must
    never be sufficient — this is exactly the class of bug Story 2.1's review
    caught twice (HDBSCAN chaining, cluster-ID hash collisions)."""
    from pipeline.stages.dedupe import merge_by_agency

    a = _record("Ceasefire declared in the capital", "outlet-a.com", wire_agency="Reuters")
    b = _record(
        "Stock markets rally on earnings",
        "outlet-b.com",
        url="https://outlet-b.com/x",
        wire_agency="Reuters",
    )

    groups = group_by_title([a, b])
    merged = merge_by_agency(groups)

    assert len(merged) == 2, "unrelated titles must not merge even with matching agency"


def test_groups_with_no_agency_attribution_are_unaffected() -> None:
    """AC3: a Source exposing no attribution metadata is treated as
    independent, and the stage does not fail — the normal case."""
    from pipeline.stages.dedupe import merge_by_agency

    a = _record("Ceasefire declared", "outlet-a.com")
    b = _record("Markets rally", "outlet-b.com", url="https://outlet-b.com/x")

    groups = group_by_title([a, b])
    merged = merge_by_agency(groups)

    assert len(merged) == 2


def test_merged_group_carries_a_marker_distinguishing_it_from_a_title_merge() -> None:
    """AC4: the change in grouping mechanism must be inspectable in the
    output, not a silent difference in composition."""
    from pipeline.stages.dedupe import merge_by_agency

    a = _record("Ceasefire declared in the region", "outlet-a.com", wire_agency="AFP")
    b = _record(
        "Ceasefire declared across the region",
        "outlet-b.com",
        url="https://outlet-b.com/x",
        wire_agency="AFP",
    )

    groups = group_by_title([a, b])
    merged = merge_by_agency(groups)

    assert merged[0].to_dict()["formed_by"] == "agency"


def test_a_title_only_group_is_marked_accordingly() -> None:
    from pipeline.stages.dedupe import merge_by_agency

    a = _record("Ceasefire declared", "outlet-a.com")
    groups = group_by_title([a])
    merged = merge_by_agency(groups)

    assert merged[0].to_dict()["formed_by"] == "title"


def test_run_dedupe_end_to_end_with_agency_merging(tmp_path: Path) -> None:
    """A GDELT article (no wire_agency, per Story 2.3's scope) and two
    RSS-shaped agency-attributed near-miss dispatches flow through the same
    cycle without error, mirroring a realistic mixed-source day."""
    gdelt_record = _record("Unrelated GDELT story", "reuters.com", url="https://reuters.com/g")
    a = _record("Ceasefire declared in the region", "outlet-a.com", wire_agency="AFP")
    b = _record(
        "Ceasefire declared across the region",
        "outlet-b.com",
        url="https://outlet-b.com/x",
        wire_agency="AFP",
    )

    input_path = tmp_path / "articles.jsonl"
    input_path.write_text(
        "\n".join(json.dumps(r.to_dict()) for r in [gdelt_record, a, b]) + "\n",
        encoding="utf-8",
    )

    written = run_dedupe(input_path, cycle_id="c1", data_root=tmp_path / "data", embed=_no_embed)
    groups = [json.loads(line) for line in written.output_path.read_text().splitlines()]

    assert written.groups_out == 2  # the unrelated story + the merged AFP pair
    assert any(g["formed_by"] == "agency" for g in groups)
    assert any(g["formed_by"] == "title" for g in groups)


def test_three_agency_attributed_groups_that_all_mutually_qualify_merge() -> None:
    """A genuine clique of 3+ groups (every pair independently clears both
    signals) is exactly the intended, safe case for this layer to handle."""
    from pipeline.stages.dedupe import merge_by_agency

    a = _record("Ceasefire declared across the wider capital region", "s1.com", wire_agency="AFP")
    b = _record(
        "Ceasefire declared across the wider capital area",
        "s2.com",
        url="https://s2.com/x",
        wire_agency="AFP",
    )
    c = _record(
        "Ceasefire declared across the wider capital zone",
        "s3.com",
        url="https://s3.com/x",
        wire_agency="AFP",
    )

    groups = group_by_title([a, b, c])
    assert len(groups) == 3

    merged = merge_by_agency(groups)
    assert len(merged) == 1
    assert merged[0].independent_source_count == 1
    assert merged[0].to_dict()["formed_by"] == "agency"


def test_transitive_chaining_does_not_fold_a_non_clique_triple_together() -> None:
    """The exact bug an adversarial review caught in the first implementation:
    a chain of individually-passing pairs (A-B similar, B-C similar, A-C not)
    must NOT fold all three into one group just because each hop matches —
    every pair in the final group must directly qualify, not just adjacent
    ones. Verified by mocking similarity directly rather than hunting for
    natural-language strings with this exact property, since SequenceMatcher
    empirically resists producing one."""
    import pipeline.stages.dedupe as dedupe_module
    from pipeline.stages.dedupe import merge_by_agency

    a = _record("x" * 21, "s1.com", wire_agency="Reuters")  # long enough to clear the length floor
    b = _record("y" * 21, "s2.com", url="https://s2.com/x", wire_agency="Reuters")
    c = _record("z" * 21, "s3.com", url="https://s3.com/x", wire_agency="Reuters")
    groups = [
        ArticleGroup(normalized_title=a.title, articles=(a,)),
        ArticleGroup(normalized_title=b.title, articles=(b,)),
        ArticleGroup(normalized_title=c.title, articles=(c,)),
    ]

    # A-B and B-C both qualify; A-C does not — a non-clique chain.
    similarities = {
        (a.title, b.title): 0.9,
        (b.title, a.title): 0.9,
        (b.title, c.title): 0.8,
        (c.title, b.title): 0.8,
        (a.title, c.title): 0.1,
        (c.title, a.title): 0.1,
    }

    class _FakeMatcher:
        def __init__(self, _isjunk: object, t1: str, t2: str) -> None:
            self._ratio = similarities[(t1, t2)]

        def ratio(self) -> float:
            return self._ratio

    original = dedupe_module.SequenceMatcher
    dedupe_module.SequenceMatcher = _FakeMatcher  # type: ignore[assignment]
    try:
        merged = merge_by_agency(groups)
    finally:
        dedupe_module.SequenceMatcher = original  # type: ignore[assignment]

    # A and B merge (they mutually qualify); C stands alone, because merging
    # it into A's cluster would violate the A-C pair, and merging it into a
    # hypothetical B-C-only cluster would break the "every pair" requirement
    # once A is already claimed by B.
    sources_by_group = [sorted(art.source for art in g.articles) for g in merged]
    assert sorted(sources_by_group) == [["s1.com", "s2.com"], ["s3.com"]]


def test_agency_on_a_non_representative_member_is_still_detected() -> None:
    """A title-normalization group can mix an attributed and an unattributed
    Article under the identical headline. An adversarial review found that
    checking only the group's representative (earliest-published) made
    visibility to this layer depend on which member happened to publish
    first — an accident unrelated to whether attribution evidence exists."""
    from pipeline.stages.dedupe import merge_by_agency

    early_no_agency = _record(
        "Ceasefire declared across the wider capital region",
        "s1.com",
        wire_agency=None,
    )
    later_with_agency = ArticleRecord(
        title="Ceasefire declared across the wider capital region",
        url="https://s1.com/later",
        published_at=early_no_agency.published_at.replace(hour=7),
        source="s1.com",
        source_country="france",
        language="fr",
        collected_by="rss",
        wire_agency="AFP",
    )
    other = _record(
        "Ceasefire declared across the wider capital area",
        "s2.com",
        url="https://s2.com/x",
        wire_agency="AFP",
    )

    group_a = ArticleGroup(
        normalized_title=normalize_title(early_no_agency.title),
        articles=(early_no_agency, later_with_agency),
    )
    group_b = ArticleGroup(normalized_title=normalize_title(other.title), articles=(other,))

    merged = merge_by_agency([group_a, group_b])
    assert len(merged) == 1, "the AFP signal on the non-representative member must still count"


def test_short_titles_do_not_merge_on_agency_alone() -> None:
    """SequenceMatcher.ratio() on short strings is dominated by character
    overlap rather than semantic similarity — verified: 'un dead' vs.
    'un lead' scores 0.857 despite describing opposite outcomes. Below the
    length floor, similarity is not trustworthy evidence, agency match or
    not."""
    from pipeline.stages.dedupe import merge_by_agency

    a = _record("UN dead", "s1.com", wire_agency="AP")
    b = _record("UN lead", "s2.com", url="https://s2.com/x", wire_agency="AP")

    groups = group_by_title([a, b])
    merged = merge_by_agency(groups)

    assert len(merged) == 2, "short titles must not merge purely on character overlap"


# --- Rewrite detection merge (Story 2.4, FR-10 layer 3) -----------------------


def _fake_embed(vectors_by_title: dict[str, list[float]]):
    from pipeline.adapters.cohere_embed import EmbeddingResult

    def embed(titles: list[str]):
        return EmbeddingResult(vectors=[vectors_by_title[t] for t in titles])

    return embed


def test_two_rewritten_dispatches_with_close_embeddings_merge() -> None:
    """AC1: no title overlap and no shared agency — embeddings alone
    corroborate that these are the same underlying dispatch, reworded."""
    from pipeline.stages.dedupe import merge_by_rewrite_detection

    a = _record("Government announces new economic measures", "s1.com")
    b = _record(
        "Officials unveil fresh economic policy package",
        "s2.com",
        url="https://s2.com/x",
    )
    groups = group_by_title([a, b])
    assert len(groups) == 2

    embed = _fake_embed(
        {
            groups[0].representative.title: [1.0, 0.0],
            groups[1].representative.title: [0.99, 0.02],
        }
    )
    merged = merge_by_rewrite_detection(groups, embed=embed)

    assert len(merged) == 1
    assert merged[0].independent_source_count == 1
    assert merged[0].to_dict()["formed_by"] == "rewrite"


def test_two_independent_reports_of_the_same_event_do_not_merge() -> None:
    """AC2, the central risk this story exists to manage: two Articles that
    are BOTH genuinely original reporting of one real-world Event must not
    be collapsed by this layer, or real independent coverage silently
    vanishes from the Consensus Score."""
    from pipeline.stages.dedupe import merge_by_rewrite_detection

    a = _record("Local reporters describe scene after the earthquake", "s1.com")
    b = _record(
        "Correspondent files firsthand account of earthquake aftermath",
        "s2.com",
        url="https://s2.com/x",
    )
    groups = group_by_title([a, b])

    # Topically related (same Event) but NOT a rewrite of one dispatch --
    # embeddings for genuinely independent reporting on the same Event are
    # typically closer than unrelated stories but must still fall short of
    # the stricter "same dispatch" floor.
    embed = _fake_embed(
        {
            groups[0].representative.title: [1.0, 0.0, 0.0],
            groups[1].representative.title: [0.7, 0.7, 0.14],
        }
    )
    merged = merge_by_rewrite_detection(groups, embed=embed)

    assert len(merged) == 2, "independent reporting on the same Event must not collapse"


def test_rewrite_detection_composes_with_a_prior_agency_merge() -> None:
    """Layers compose: a group already merged by merge_by_agency remains
    eligible for further merging via rewrite detection with an unattributed
    group."""
    from pipeline.stages.dedupe import merge_by_agency, merge_by_rewrite_detection

    a = _record("Ceasefire declared across the wider capital region", "s1.com", wire_agency="AFP")
    b = _record(
        "Ceasefire declared across the wider capital area",
        "s2.com",
        url="https://s2.com/x",
        wire_agency="AFP",
    )
    c = _record(
        "Truce takes hold in the metropolitan zone overnight",
        "s3.com",
        url="https://s3.com/x",
    )

    after_agency = merge_by_agency(group_by_title([a, b, c]))
    assert len(after_agency) == 2  # {a, b} merged by agency; c alone

    agency_group = next(g for g in after_agency if len(g.articles) == 2)
    lone_group = next(g for g in after_agency if len(g.articles) == 1)

    embed = _fake_embed(
        {
            agency_group.representative.title: [1.0, 0.0],
            lone_group.representative.title: [0.98, 0.02],
        }
    )
    merged = merge_by_rewrite_detection(after_agency, embed=embed)

    assert len(merged) == 1
    assert merged[0].independent_source_count == 1


def test_embedding_failure_leaves_dedupe_output_unchanged() -> None:
    """AC4: an embedding failure skips this layer's merge for the cycle
    entirely rather than crashing -- output is whatever layers 1+2 already
    produced (AD-10)."""
    from pipeline.adapters import Failure
    from pipeline.adapters.cohere_embed import EmbeddingResult
    from pipeline.stages.dedupe import merge_by_rewrite_detection

    a = _record("Government announces new economic measures", "s1.com")
    b = _record(
        "Officials unveil fresh economic policy package",
        "s2.com",
        url="https://s2.com/x",
    )
    groups = group_by_title([a, b])

    def failing_embed(titles: list[str]):
        return EmbeddingResult(failures=[Failure("cohere_embed", "rate limited")])

    result, reason = merge_by_rewrite_detection(groups, embed=failing_embed, return_degraded=True)

    assert len(result) == 2, "a failed embedding must leave layer 1+2 output untouched"
    assert reason is not None
    assert "rate limited" in reason, "the specific failure detail must survive, not a bare flag"


def test_transitive_chaining_does_not_fold_a_non_clique_triple_together_via_embeddings() -> None:
    """The same clique discipline Story 2.3 needed, verified again here since
    this layer has its own independent call site into _clique_merge.

    An earlier version of this test used vectors where only the A-B pair
    actually qualified (B-C and A-C both scored ~1.0, nowhere near the
    floor) -- an adversarial review caught that it could not have failed
    even against the old, buggy fixed-anchor algorithm, because there was no
    chain to exploit in the first place. These vectors are placed at
    controlled angular separation (0, 35, 70 degrees on the unit circle) so
    that A-B and B-C each sit at cosine distance ~0.18 (comfortably under
    the 0.25 floor) while A-C sits at ~0.66 (comfortably over it) -- a
    genuine chain where a fixed-anchor or connected-components merge would
    incorrectly fold all three together, and the clique requirement must
    not."""
    from pipeline.stages.dedupe import merge_by_rewrite_detection

    a = _record("aaaaaaaaaaaaaaaaaaaaaaaaa", "s1.com")
    b = _record("bbbbbbbbbbbbbbbbbbbbbbbbb", "s2.com", url="https://s2.com/x")
    c = _record("ccccccccccccccccccccccccc", "s3.com", url="https://s3.com/x")
    groups = group_by_title([a, b, c])

    embed = _fake_embed(
        {
            groups[0].representative.title: [1.0, 0.0, 0.0],
            groups[1].representative.title: [0.8191520442889918, 0.573576436351046, 0.0],
            groups[2].representative.title: [0.3420201433256688, 0.9396926207859083, 0.0],
        }
    )
    merged = merge_by_rewrite_detection(groups, embed=embed)

    sources_by_group = [sorted(art.source for art in g.articles) for g in merged]
    assert ["s1.com", "s2.com", "s3.com"] not in sources_by_group, (
        "all three must never fold into one group via transitive chaining"
    )
    # The two directly-qualifying groups (A-B) do merge; C, which qualifies
    # against B but not against A, is correctly excluded from that cluster.
    merged_sizes = sorted(len(g.articles) for g in merged)
    assert merged_sizes == [1, 2], "A-B merge; C stands alone, not folded in via B"


def test_a_single_group_passes_through_unchanged_and_still_calls_embed() -> None:
    """No pairs to compare, so nothing can merge -- but the embed call still
    happens (Cohere is invoked once even for a lone group), which callers
    should be aware of as a cost consideration, not a bug."""
    from pipeline.stages.dedupe import merge_by_rewrite_detection

    a = _record("A perfectly ordinary headline about something", "s1.com")
    groups = group_by_title([a])

    calls: list[list[str]] = []

    def counting_embed(titles: list[str]):
        calls.append(titles)
        return _fake_embed({groups[0].representative.title: [1.0, 0.0]})(titles)

    merged = merge_by_rewrite_detection(groups, embed=counting_embed)

    assert len(merged) == 1
    assert merged[0].to_dict()["formed_by"] == "title"
    assert len(calls) == 1, "embed is called even for a group that can never merge"


def test_exact_boundary_distance_qualifies_for_a_merge() -> None:
    """The comparison is `<=`, making the floor inclusive -- verified
    explicitly since an adversarial review noted this boundary decision had
    no test pinning it down, and `<=` is the more permissive of the two
    reasonable choices."""
    import numpy as np
    from pipeline.config import REWRITE_SIMILARITY_FLOOR
    from pipeline.stages.dedupe import merge_by_rewrite_detection

    a = _record("A perfectly ordinary headline about something", "s1.com")
    b = _record(
        "A totally different headline about another thing",
        "s2.com",
        url="https://s2.com/x",
    )
    groups = group_by_title([a, b])

    # Construct two unit vectors at exactly REWRITE_SIMILARITY_FLOOR cosine
    # distance apart: d = 1 - cos(theta), so cos(theta) = 1 - d.
    cos_theta = 1 - REWRITE_SIMILARITY_FLOOR
    sin_theta = (1 - cos_theta**2) ** 0.5
    vec_a = [1.0, 0.0]
    vec_b = [cos_theta, sin_theta]

    embed = _fake_embed(
        {
            groups[0].representative.title: vec_a,
            groups[1].representative.title: vec_b,
        }
    )
    merged = merge_by_rewrite_detection(groups, embed=embed)

    # Sanity-check the constructed distance is actually at the boundary.
    from scipy.spatial.distance import cosine

    actual_distance = cosine(np.array(vec_a), np.array(vec_b))
    assert abs(actual_distance - REWRITE_SIMILARITY_FLOOR) < 1e-9

    assert len(merged) == 1, "a pair exactly at the floor must qualify (inclusive boundary)"


def test_run_dedupe_end_to_end_produces_a_rewrite_formed_group_on_disk() -> None:
    """AC5's literal claim -- a rewrite-formed group is inspectable in
    groups.jsonl -- exercised through the real run_dedupe entrypoint, not
    just the in-memory merge function. An earlier round of tests only ever
    called merge_by_rewrite_detection directly; the one true run_dedupe
    test used an always-failing embed stub, so layer 3 never actually ran
    there."""
    a = _record("Government announces new economic measures", "s1.com")
    b = _record(
        "Officials unveil fresh economic policy package",
        "s2.com",
        url="https://s2.com/x",
    )

    input_path_content = "\n".join(json.dumps(r.to_dict()) for r in [a, b]) + "\n"

    def embed(titles: list[str]):
        vectors_by_title = {
            "Government announces new economic measures": [1.0, 0.0],
            "Officials unveil fresh economic policy package": [0.99, 0.02],
        }
        return EmbeddingResult(vectors=[vectors_by_title[t] for t in titles])

    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = _Path(tmp)
        source = tmp_path / "articles.jsonl"
        source.write_text(input_path_content)

        written = run_dedupe(source, cycle_id="c1", data_root=tmp_path / "data", embed=embed)

        lines = written.output_path.read_text().splitlines()
        assert len(lines) == 1, "the rewrite pair collapses to one group on disk"
        record = json.loads(lines[0])
        assert record["formed_by"] == "rewrite"
        assert record["independent_source_count"] == 1

        metadata = json.loads(written.metadata_path.read_text())
        assert metadata["rewrite_detection_degraded"] is None


def test_short_titles_do_not_merge_via_rewrite_detection_even_with_close_embeddings() -> None:
    """A defensive floor, not one verified against a confirmed failure mode
    (no live Cohere call is available to test whether short embeddings
    actually behave unreliably the way SequenceMatcher does) -- but this
    layer has no second corroborating signal at all, so the floor is kept
    as a zero-cost precaution."""
    from pipeline.stages.dedupe import merge_by_rewrite_detection

    a = _record("UN dead", "s1.com")
    b = _record("UN lead", "s2.com", url="https://s2.com/x")
    groups = group_by_title([a, b])

    embed = _fake_embed(
        {
            groups[0].representative.title: [1.0, 0.0],
            groups[1].representative.title: [0.999, 0.001],  # would otherwise clearly qualify
        }
    )
    merged = merge_by_rewrite_detection(groups, embed=embed)

    assert len(merged) == 2, "short titles must not merge even with a near-identical embedding"
