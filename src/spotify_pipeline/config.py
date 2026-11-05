"""Central place for every path the pipeline touches."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    raw_csv: Path = PROJECT_ROOT / "dataset" / "spotify-top-50-world.csv"
    database: Path = PROJECT_ROOT / "warehouse" / "spotify.duckdb"
    sql_dir: Path = PROJECT_ROOT / "sql"
    seeds_dir: Path = PROJECT_ROOT / "seeds"
    export_dir: Path = PROJECT_ROOT / "exports"
    quality_report: Path = PROJECT_ROOT / "docs" / "data_quality_report.md"
    insights_report: Path = PROJECT_ROOT / "docs" / "insights.md"
    model_report: Path = PROJECT_ROOT / "docs" / "model_report.md"
    powerbi_dir: Path = PROJECT_ROOT / "powerbi"
    site_dir: Path = PROJECT_ROOT / "site"
