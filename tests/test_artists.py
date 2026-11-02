import pytest

from spotify_pipeline.artists import load_protected_names, split_artist_credit
from spotify_pipeline.config import Settings

PROTECTED = ["Earth, Wind & Fire", "Daryl Hall & John Oates", "Fast & Furious: The Fast Saga"]


@pytest.mark.parametrize(
    ("credit", "expected"),
    [
        ("Drake", ["Drake"]),
        ("Drake & SZA", ["Drake", "SZA"]),
        ("Peso Pluma & Junior H & Oscar Maydon", ["Peso Pluma", "Junior H", "Oscar Maydon"]),
        ("Tyler, The Creator", ["Tyler, The Creator"]),
        ("Earth, Wind & Fire", ["Earth, Wind & Fire"]),
        ("Earth, Wind & Fire & sped up + slowed", ["Earth, Wind & Fire", "sped up + slowed"]),
        (
            "Fast & Furious: The Fast Saga & Jimin & BTS",
            ["Fast & Furious: The Fast Saga", "Jimin", "BTS"],
        ),
        ("  Drake  &  SZA ", ["Drake", "SZA"]),
        ("Jung Kook & jung kook", ["Jung Kook"]),  # case-insensitive de-duplication
        ("", []),
        ("   ", []),
    ],
)
def test_split_artist_credit(credit, expected):
    assert split_artist_credit(credit, PROTECTED) == expected


def test_without_protection_names_are_split():
    assert split_artist_credit("Daryl Hall & John Oates") == ["Daryl Hall", "John Oates"]


def test_longest_protected_name_wins():
    protected = ["Hall & Oates", "Daryl Hall & Oates"]
    assert split_artist_credit("Daryl Hall & Oates & SZA", protected) == [
        "Daryl Hall & Oates",
        "SZA",
    ]


def test_seed_file_loads():
    names = load_protected_names(Settings().seeds_dir / "protected_artist_names.csv")
    assert "Earth, Wind & Fire" in names
    assert 'Bobby "Boris" Pickett & The Crypt-Kickers' in names
