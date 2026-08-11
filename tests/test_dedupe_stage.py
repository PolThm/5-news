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
) -> ArticleRecord:
    return ArticleRecord(
        title=title,
        url=url or f"https://{source}/{abs(hash(title + source))}",
        published_at=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
        source=source,
        source_country=country,
        language=language,
        collected_by="gdelt",
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
