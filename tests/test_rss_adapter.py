"""Tests for reading `mentioned_countries` out of a reference-press headline.

RSS publishes no locations, and until this existed that absence decided which
Briefings could be filled. Measured on 2026-08-20, 0 of 1,151 reference articles
carried `mentioned_countries` against 8,790 of 11,120 from GDELT, so an event
covered only by the French press -- a French court case, the thing a France
Briefing exists for -- could not be placed in France. Both country Briefings
fell back to Europe and served an item about Harry and Meghan.
"""

from __future__ import annotations

from pipeline.adapters.rss import parse_feed


def _feed(*titles: str) -> str:
    items = "".join(
        f"<item><title>{title}</title>"
        f"<link>https://www.lemonde.fr/{position}</link>"
        f"<pubDate>Wed, 20 Aug 2026 06:00:00 +0000</pubDate></item>"
        for position, title in enumerate(titles)
    )
    return f"<?xml version='1.0' encoding='UTF-8'?><rss><channel>{items}</channel></rss>"


def _one(title: str):
    records = parse_feed(_feed(title), "lemonde.fr", "france", "fr")
    assert records, f"the fixture must parse: {title}"
    return records[0]


def test_a_headline_naming_a_country_places_the_article_there() -> None:
    article = _one("Affaire Le Scouarnec : information judiciaire ouverte en France")

    assert "france" in article.mentioned_countries


def test_a_nationality_adjective_places_the_article_too() -> None:
    """ "L'armée israélienne", "el gobierno español", "la justice française" name
    a country without using its name, and they are how headlines are written. A
    table of country names alone would miss most of them."""
    for title, expected in (
        ("L'armée israélienne reconnaît avoir tiré sur le véhicule", "is"),
        ("Le Conseil constitutionnel français tranche", "france"),
        ("Moderna y Merck anuncian el éxito en Estados Unidos", "united-states"),
        ("Ceuta : bras de fer entre l'UE et l'Espagne", "spain"),
    ):
        assert expected in _one(title).mentioned_countries, title


def test_where_the_outlet_sits_stays_separate_from_what_the_story_is_about() -> None:
    """The distinction this pipeline was fixed for once already: a French paper
    covering a strike in Kharkiv is a French SOURCE reporting on Ukraine, and
    conflating the two put Russian missile strikes in Switzerland."""
    article = _one("Guerre en Ukraine : 13 personnes tuées à Kiev")

    assert article.source_country == "france"
    assert "up" in article.mentioned_countries
    assert "france" not in article.mentioned_countries


def test_a_headline_naming_nothing_places_nothing() -> None:
    """Empty is the honest answer, and a common one. Guessing from
    `source_country` is exactly the conflation above."""
    assert _one("Le récit d'une nuit blanche").mentioned_countries == ()


def test_only_the_headline_is_read_not_the_whole_entry() -> None:
    """A summary or a category list names countries the article merely mentions,
    and `mentioned_countries` is meant to say what a piece is ABOUT. A headline
    naming a country is about that country; a body naming ten is not about ten.
    """
    body = (
        "<?xml version='1.0' encoding='UTF-8'?><rss><channel><item>"
        "<title>Le récit d'une nuit blanche</title>"
        "<description>Reportage en France, en Espagne et en Italie.</description>"
        "<link>https://www.lemonde.fr/a</link>"
        "<pubDate>Wed, 20 Aug 2026 06:00:00 +0000</pubDate></item></channel></rss>"
    )

    records = parse_feed(body, "lemonde.fr", "france", "fr")

    assert records[0].mentioned_countries == ()
