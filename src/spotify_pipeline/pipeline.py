"""Build the warehouse: bronze (raw) -> silver (typed and conformed) -> gold (star schema)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import duckdb

from spotify_pipeline.artists import load_protected_names, split_artist_credit
from spotify_pipeline.config import Settings

log = logging.getLogger(__name__)

GOLD_TABLES = (
    "dim_date",
    "dim_artist",
    "dim_track",
    "dim_track_version",
    "bridge_track_artist",
    "fact_chart_entry",
)


@dataclass(frozen=True)
class Step:
    layer: str
    name: str
    run: Callable[[duckdb.DuckDBPyConnection, Settings], None]


def _sql_step(relative_path: str) -> Callable[[duckdb.DuckDBPyConnection, Settings], None]:
    def run(con: duckdb.DuckDBPyConnection, settings: Settings) -> None:
        sql = (settings.sql_dir / relative_path).read_text(encoding="utf-8")
        # The only templated value is the source path; quote it as a SQL string literal.
        raw_path = settings.raw_csv.as_posix().replace("'", "''")
        con.execute(sql.replace("{{ raw_csv_path }}", raw_path))

    return run


def _build_artist_credit_parts(con: duckdb.DuckDBPyConnection, settings: Settings) -> None:
    """Explode each distinct artist credit into one row per artist (Python: needs unit tests)."""
    protected = load_protected_names(settings.seeds_dir / "protected_artist_names.csv")
    credits = con.execute(
        "SELECT DISTINCT artist_credit FROM silver.stg_chart_entries "
        "WHERE artist_credit IS NOT NULL"
    ).fetchall()
    rows = [
        (credit, artist, order)
        for (credit,) in credits
        for order, artist in enumerate(split_artist_credit(credit, protected), start=1)
    ]
    con.execute(
        """
        CREATE OR REPLACE TABLE silver.artist_credit_parts (
            artist_credit VARCHAR NOT NULL,
            artist_name   VARCHAR NOT NULL,
            credit_order  INTEGER NOT NULL,
            PRIMARY KEY (artist_credit, credit_order)
        )
        """
    )
    con.executemany("INSERT INTO silver.artist_credit_parts VALUES (?, ?, ?)", rows)


STEPS: tuple[Step, ...] = (
    Step("bronze", "raw_chart_snapshots", _sql_step("bronze/raw_chart_snapshots.sql")),
    Step("silver", "stg_chart_entries", _sql_step("silver/stg_chart_entries.sql")),
    Step("silver", "artist_credit_parts", _build_artist_credit_parts),
    Step("silver", "int_chart_entries", _sql_step("silver/int_chart_entries.sql")),
    Step("gold", "dim_date", _sql_step("gold/dim_date.sql")),
    Step("gold", "dim_artist", _sql_step("gold/dim_artist.sql")),
    Step("gold", "dim_track", _sql_step("gold/dim_track.sql")),
    Step("gold", "dim_track_version", _sql_step("gold/dim_track_version.sql")),
    Step("gold", "bridge_track_artist", _sql_step("gold/bridge_track_artist.sql")),
    Step("gold", "fact_chart_entry", _sql_step("gold/fact_chart_entry.sql")),
)


def connect(database: Path | str) -> duckdb.DuckDBPyConnection:
    if str(database) != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(database))


def build(con: duckdb.DuckDBPyConnection, settings: Settings) -> None:
    """Run every step in order. Each step is a full, idempotent rebuild of its table."""
    if not settings.raw_csv.exists():
        raise FileNotFoundError(f"Source file not found: {settings.raw_csv}")
    for schema in ("bronze", "silver", "gold"):
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    for step in STEPS:
        started = time.perf_counter()
        step.run(con, settings)
        [(rows,)] = con.execute(f"SELECT count(*) FROM {step.layer}.{step.name}").fetchall()
        log.info(
            "%-6s %-22s %7d rows  %5.0f ms",
            step.layer,
            step.name,
            rows,
            (time.perf_counter() - started) * 1000,
        )


def export(con: duckdb.DuckDBPyConnection, export_dir: Path) -> list[Path]:
    """Write every gold table to Parquet (analytics tools) and CSV (Power BI / Excel)."""
    export_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for table in GOLD_TABLES:
        for fmt, ext in (("PARQUET", "parquet"), ("CSV", "csv")):
            target = export_dir / f"{table}.{ext}"
            options = "FORMAT PARQUET" if fmt == "PARQUET" else "FORMAT CSV, HEADER"
            path_literal = target.as_posix().replace("'", "''")
            con.execute(f"COPY gold.{table} TO '{path_literal}' ({options})")
            written.append(target)
    return written
