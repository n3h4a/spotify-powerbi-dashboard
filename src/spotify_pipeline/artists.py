"""Parse Spotify artist credits such as ``"Peso Pluma & Junior H"`` into individual artists.

The source joins every credited artist with ``" & "``. A few real artist names also
contain that separator (``"Earth, Wind & Fire"``), so those names are protected before
splitting. Protected names live in ``seeds/protected_artist_names.csv`` so analysts can
extend the list without touching code.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

SEPARATOR = " & "


def load_protected_names(seed_file: Path) -> list[str]:
    with seed_file.open(newline="", encoding="utf-8") as fh:
        return [row["artist_name"].strip() for row in csv.DictReader(fh) if row["artist_name"]]


def split_artist_credit(credit: str, protected_names: Iterable[str] = ()) -> list[str]:
    """Return the artists in ``credit`` in credit order, without duplicates.

    >>> split_artist_credit("Drake & SZA")
    ['Drake', 'SZA']
    >>> split_artist_credit("Earth, Wind & Fire & sped up + slowed", ["Earth, Wind & Fire"])
    ['Earth, Wind & Fire', 'sped up + slowed']
    """
    if credit is None or not credit.strip():
        return []

    placeholders: dict[str, str] = {}
    masked = credit.strip()
    # Longest names first so a protected name that contains another is masked whole.
    for i, name in enumerate(sorted(set(protected_names), key=len, reverse=True)):
        if name in masked:
            token = f"\x00{i}\x00"
            placeholders[token] = name
            masked = masked.replace(name, token)

    artists: list[str] = []
    seen: set[str] = set()
    for part in masked.split(SEPARATOR):
        for token, name in placeholders.items():
            part = part.replace(token, name)
        part = part.strip()
        if part and part.casefold() not in seen:
            seen.add(part.casefold())
            artists.append(part)
    return artists
