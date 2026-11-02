"""Shared fixtures: a tiny hand-built chart that exercises every known edge case."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from spotify_pipeline import pipeline
from spotify_pipeline.config import Settings

HEADER = (
    "date,position,song,artist,popularity,duration_ms,album_type,total_tracks,"
    "release_date,is_explicit,album_cover_url"
)

# A 3-position chart over four snapshots. 2024-01-04 is deliberately missing.
#   Song A: artist credit drifts from "Drake & SZA" to "Drake"  -> 1 track, 2 versions
#   Song B: protected name "Earth, Wind & Fire", year-only release; drops out and re-enters
#   Song C: flips single -> album -> single                     -> 3 SCD2 versions
#   Song D: lead artist spelled "ARTIST X" (case variant of "Artist X")
ROWS = [
    "2024-01-01,1,Song A,Drake & SZA,90,200000,single,1,2023-12-01,True,https://img/a1",
    '2024-01-01,2,Song B,"Earth, Wind & Fire & sped up + slowed",70,180000,album,10,1978,False,https://img/b',
    "2024-01-01,3,Song C,Artist X,80,150000,single,1,2023-11-10,False,https://img/c-single",
    "2024-01-02,1,Song C,Artist X,82,150000,album,12,2023-12-15,False,https://img/c-album",
    "2024-01-02,2,Song A,Drake,91,200000,single,1,2023-12-01,True,https://img/a1",
    "2024-01-02,3,Song D,ARTIST X & Peso Pluma,60,210000,single,1,2023-12-20,False,https://img/d",
    "2024-01-03,1,Song A,Drake,92,200000,single,1,2023-12-01,True,https://img/a1",
    "2024-01-03,2,Song C,Artist X,81,150000,single,1,2023-11-10,False,https://img/c-single",
    '2024-01-03,3,Song B,"Earth, Wind & Fire & sped up + slowed",71,180000,album,10,1978,False,https://img/b',
    "2024-01-05,1,Song A,Drake,93,200000,single,1,2023-12-01,True,https://img/a1",
    "2024-01-05,2,Song C,Artist X,80,150000,single,1,2023-11-10,False,https://img/c-single",
    "2024-01-05,3,Song D,Artist X & Peso Pluma,62,210000,single,1,2023-12-20,False,https://img/d",
]


def write_fixture_csv(path: Path) -> Path:
    # Reproduce the real file's mixed line endings: first day LF, the rest CRLF.
    lf_part = "\n".join([HEADER, *ROWS[:3]]) + "\n"
    crlf_part = "\r\n".join(ROWS[3:]) + "\r\n"
    path.write_bytes((lf_part + crlf_part).encode("utf-8"))
    return path


@pytest.fixture()
def fixture_settings(tmp_path: Path) -> Settings:
    return replace(
        Settings(),
        raw_csv=write_fixture_csv(tmp_path / "chart.csv"),
        database=tmp_path / "test.duckdb",
        export_dir=tmp_path / "exports",
        quality_report=tmp_path / "dq.md",
    )


@pytest.fixture()
def built(fixture_settings: Settings):
    con = pipeline.connect(fixture_settings.database)
    pipeline.build(con, fixture_settings)
    yield con
    con.close()


@pytest.fixture(scope="session")
def real_warehouse(tmp_path_factory: pytest.TempPathFactory):
    """The real dataset built once per test session (takes about a second)."""
    tmp = tmp_path_factory.mktemp("real")
    settings = replace(Settings(), database=tmp / "real.duckdb", quality_report=tmp / "dq.md")
    con = pipeline.connect(settings.database)
    pipeline.build(con, settings)
    yield con, settings
    con.close()


def rows(con, sql: str) -> list[tuple]:
    return con.execute(sql).fetchall()
