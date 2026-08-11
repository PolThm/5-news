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

from pipeline.domain import ArticleRecord
from pipeline.stages.dedupe import (
    ArticleGroup,
    group_by_title,
    normalize_title,
    run_dedupe,
)


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

    written = run_dedupe(source, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path)

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

    first = run_dedupe(source, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path)
    content = first.output_path.read_text()
    second = run_dedupe(source, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path)

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

    a = run_dedupe(forward, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path / "a")
    b = run_dedupe(reverse, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path / "b")

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

    written = run_dedupe(source, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path)

    meta = json.loads(written.metadata_path.read_text())
    assert meta["articles_in"] == 3
    assert meta["groups_out"] == 1
    assert meta["collapsed"] == 2


def test_empty_input_is_not_a_failure(tmp_path: Path) -> None:
    """A cycle where every upstream was down still runs dedupe — on nothing."""
    source = tmp_path / "articles.jsonl"
    source.write_text("")

    written = run_dedupe(source, cycle_id="2026-08-11T00-00-00Z", data_root=tmp_path)

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

    written = run_dedupe(input_path, cycle_id="c1", data_root=tmp_path / "data")
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
