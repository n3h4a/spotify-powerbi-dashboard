"""Command-line entry point: ``spotify-pipeline {build,check,export,all}``."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from spotify_pipeline import pipeline, quality
from spotify_pipeline.config import Settings

log = logging.getLogger("spotify_pipeline")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spotify-pipeline",
        description="Build, validate and export the Spotify charts warehouse.",
    )
    parser.add_argument(
        "command",
        choices=["build", "check", "export", "insights", "model", "powerbi", "all"],
        help="build: run the ELT | check: data-quality suite | export: gold tables to files | "
        "insights: analyses, charts and docs/insights.md | model: survival analysis and "
        "prediction, docs/model_report.md | powerbi: generate the Power BI project | "
        "all: build + check + export",
    )
    parser.add_argument("--raw", type=Path, help="Source CSV (default: dataset/...csv)")
    parser.add_argument("--db", type=Path, help="DuckDB file (default: warehouse/spotify.duckdb)")
    parser.add_argument("--export-dir", type=Path, help="Export folder (default: exports/)")
    parser.add_argument("--report", type=Path, help="Markdown data-quality report path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s")

    settings = Settings()
    overrides = {
        "raw_csv": args.raw,
        "database": args.db,
        "export_dir": args.export_dir,
        "quality_report": args.report,
    }
    settings = replace(settings, **{k: v for k, v in overrides.items() if v is not None})

    con = pipeline.connect(settings.database)
    try:
        if args.command in ("build", "all"):
            log.info("Building warehouse at %s", settings.database)
            pipeline.build(con, settings)

        if args.command in ("check", "all"):
            results = quality.run_checks(con, settings.raw_csv)
            quality.write_report(con, results, settings.quality_report)
            for r in results:
                log.log(
                    logging.INFO if r.passed else logging.WARNING,
                    "%s  [%s] %s (%d failing rows)",
                    r.status,
                    r.check.severity,
                    r.check.name,
                    r.failing_rows,
                )
            blocking = [r for r in results if not r.passed and r.check.severity == "error"]
            log.info("Data-quality report written to %s", settings.quality_report)
            if blocking:
                log.error("%d blocking data-quality check(s) failed", len(blocking))
                return 1

        if args.command in ("export", "all"):
            files = pipeline.export(con, settings.export_dir)
            log.info("Exported %d files to %s", len(files), settings.export_dir)

        if args.command == "insights":
            from spotify_pipeline import insights  # optional deps: pip install -e ".[analysis]"

            insights.generate(con, settings.sql_dir, settings.insights_report)

        if args.command == "model":
            from spotify_pipeline import modeling  # optional deps: pip install -e ".[ml]"

            modeling.generate(con, settings.model_report)

        if args.command == "powerbi":
            from spotify_pipeline import powerbi

            powerbi.generate(con, settings.powerbi_dir)
            log.info("Power BI project written to %s", settings.powerbi_dir)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
