"""Glossary terms are binding in code (AC 3, spine conventions).

The PRD Glossary defines the vocabulary. Using a synonym anywhere — Story,
Item, NewsItem, Topic where the Glossary says Cluster — is a defect. These
tests pin the names so a rename is deliberate rather than accidental.
"""

import pipeline.domain as domain


def test_every_glossary_term_exists() -> None:
    """Fifteen binding terms. `End Screen` is the sixteenth and is a page
    concept delivered in Epic 4, deliberately absent here."""
    for name in (
        "Article",
        "Source",
        "IndependentSource",
        "WireCopy",
        "SyndicationDetection",
        "Event",
        "Cluster",
        "QualifyingCluster",
        "ConsensusScore",
        "Zone",
        "Period",
        "Briefing",
        "Summary",
        "OutputLanguage",
        "DiscardedVolume",
    ):
        assert hasattr(domain, name), f"Glossary term missing from domain: {name}"


def test_domain_imports_nothing_from_the_rest_of_the_pipeline() -> None:
    """domain/ is the leaf (spine dependency table). It must not reach
    sideways into adapters, stages, or config.

    Parses the AST rather than grepping the source: a docstring may legitimately
    name another module in prose, and a text search would flag that as a
    violation while missing a dynamic import.
    """
    import ast
    from pathlib import Path

    forbidden = {"pipeline.adapters", "pipeline.stages", "pipeline.config"}
    domain_dir = Path(domain.__file__).parent

    for py in domain_dir.rglob("*.py"):
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden, f"{py.name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in forbidden, f"{py.name} imports from {node.module}"


def test_consensus_score_carries_both_counts() -> None:
    score = domain.ConsensusScore(independent_sources=34, countries=12)
    assert score.independent_sources == 34
    assert score.countries == 12


def test_consensus_score_is_a_plain_data_holder() -> None:
    """The Qualifying Cluster floor is a ranking rule, not a domain fact — it
    belongs to pipeline.stages.rank (Story 2.2), which may import the
    thresholds from pipeline.config. domain/ may not (it is the leaf), so it
    must not encode the rule at all rather than duplicate the numbers.
    """
    assert not hasattr(domain.ConsensusScore, "qualifies")


def test_discarded_volume() -> None:
    dv = domain.DiscardedVolume(ingested=1247, kept=5)
    assert dv.discarded == 1242
