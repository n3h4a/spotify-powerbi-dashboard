"""Data-quality suite.

Every check is a SQL query that returns the rows violating a rule; zero rows means
pass. ``error`` checks block the pipeline (non-zero exit code, red CI). ``warn``
checks document known characteristics of the source without blocking.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

SAMPLE_SIZE = 5


@dataclass(frozen=True)
class Check:
    name: str
    category: str
    severity: str  # "error" | "warn"
    description: str
    sql: str
    sample_order: str = "ALL"  # ORDER BY clause for the report sample (deterministic)


@dataclass
class CheckResult:
    check: Check
    failing_rows: int
    columns: list[str] = field(default_factory=list)
    sample: list[tuple] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.failing_rows == 0

    @property
    def status(self) -> str:
        if self.passed:
            return "PASS"
        return "WARN" if self.check.severity == "warn" else "FAIL"


def _unique(table: str, columns: str) -> str:
    return f"SELECT {columns}, count(*) AS n FROM {table} GROUP BY ALL HAVING count(*) > 1"


def _not_null(table: str, column: str) -> str:
    return f"SELECT * FROM {table} WHERE {column} IS NULL"


def _foreign_key(child: str, parent: str, key: str) -> str:
    return (
        f"SELECT c.{key} FROM {child} AS c "
        f"LEFT JOIN {parent} AS p ON p.{key} = c.{key} WHERE p.{key} IS NULL"
    )


CHECKS: tuple[Check, ...] = (
    # ---------------------------------------------------------------- completeness
    Check(
        "bronze_reconciles_to_fact",
        "completeness",
        "error",
        "Every landed row reaches the fact table (no rows dropped or duplicated by joins).",
        """
        SELECT b.n AS bronze_rows, f.n AS fact_rows
        FROM (SELECT count(*) AS n FROM bronze.raw_chart_snapshots) AS b,
             (SELECT count(*) AS n FROM gold.fact_chart_entry) AS f
        WHERE b.n <> f.n
        """,
    ),
    Check(
        "no_type_cast_failures",
        "validity",
        "error",
        "Every raw value converts to its target type (TRY_CAST produced no NULLs).",
        """
        SELECT b._source_row_number, b.date, b.position, b.popularity, b.duration_ms,
               b.total_tracks, b.is_explicit, b.release_date
        FROM bronze.raw_chart_snapshots AS b
        JOIN silver.stg_chart_entries AS s USING (_source_row_number)
        WHERE s.chart_date IS NULL OR s.chart_position IS NULL OR s.popularity IS NULL
           OR s.duration_ms IS NULL OR s.album_total_tracks IS NULL OR s.is_explicit IS NULL
           OR s.release_date IS NULL
        """,
    ),
    Check(
        "every_track_has_lead_artist",
        "completeness",
        "error",
        "Every chart entry resolves to a lead artist and therefore a track.",
        _not_null("silver.int_chart_entries", "lead_artist_name"),
    ),
    # ---------------------------------------------------------------- validity
    Check(
        "chart_position_in_range",
        "validity",
        "error",
        "Chart position is between 1 and 50.",
        "SELECT * FROM gold.fact_chart_entry WHERE chart_position NOT BETWEEN 1 AND 50",
    ),
    Check(
        "popularity_in_range",
        "validity",
        "error",
        "Spotify popularity is between 0 and 100.",
        "SELECT * FROM gold.fact_chart_entry WHERE popularity NOT BETWEEN 0 AND 100",
    ),
    Check(
        "duration_positive",
        "validity",
        "error",
        "Track duration is positive and under one hour.",
        "SELECT * FROM gold.dim_track_version WHERE duration_ms NOT BETWEEN 1 AND 3600000",
    ),
    Check(
        "album_type_accepted_values",
        "validity",
        "error",
        "album_type is one of: album, single, compilation.",
        """
        SELECT album_type, count(*) AS n FROM gold.dim_track_version
        WHERE album_type NOT IN ('album', 'single', 'compilation') GROUP BY ALL
        """,
    ),
    # ---------------------------------------------------------------- uniqueness / grain
    Check(
        "fact_grain_unique",
        "uniqueness",
        "error",
        "One row per chart date and position.",
        _unique("gold.fact_chart_entry", "chart_date, chart_position"),
    ),
    Check(
        "track_charts_once_per_day",
        "uniqueness",
        "error",
        "A track never occupies two positions on the same day (validates the track identity rule).",
        _unique("gold.fact_chart_entry", "chart_date, track_key"),
    ),
    Check(
        "fifty_positions_per_snapshot",
        "completeness",
        "error",
        "Every snapshot contains exactly positions 1-50.",
        """
        SELECT chart_date, count(*) AS n_rows, count(DISTINCT chart_position) AS n_positions
        FROM gold.fact_chart_entry GROUP BY chart_date
        HAVING count(*) <> 50 OR count(DISTINCT chart_position) <> 50
        """,
    ),
    Check(
        "dim_date_pk_unique",
        "uniqueness",
        "error",
        "date_key is unique.",
        _unique("gold.dim_date", "date_key"),
    ),
    Check(
        "dim_artist_pk_unique",
        "uniqueness",
        "error",
        "artist_key is unique.",
        _unique("gold.dim_artist", "artist_key"),
    ),
    Check(
        "dim_track_pk_unique",
        "uniqueness",
        "error",
        "track_key is unique.",
        _unique("gold.dim_track", "track_key"),
    ),
    Check(
        "dim_track_version_pk_unique",
        "uniqueness",
        "error",
        "track_version_key is unique.",
        _unique("gold.dim_track_version", "track_version_key"),
    ),
    Check(
        "bridge_pk_unique",
        "uniqueness",
        "error",
        "(track_key, artist_key) is unique.",
        _unique("gold.bridge_track_artist", "track_key, artist_key"),
    ),
    # ---------------------------------------------------------------- referential integrity
    Check(
        "fact_to_dim_date",
        "integrity",
        "error",
        "Every fact date exists in dim_date.",
        _foreign_key("gold.fact_chart_entry", "gold.dim_date", "date_key"),
    ),
    Check(
        "fact_to_dim_track",
        "integrity",
        "error",
        "Every fact track exists in dim_track.",
        _foreign_key("gold.fact_chart_entry", "gold.dim_track", "track_key"),
    ),
    Check(
        "fact_to_dim_track_version",
        "integrity",
        "error",
        "Every fact row maps to exactly one track version.",
        _foreign_key("gold.fact_chart_entry", "gold.dim_track_version", "track_version_key"),
    ),
    Check(
        "bridge_to_dim_artist",
        "integrity",
        "error",
        "Every bridged artist exists.",
        _foreign_key("gold.bridge_track_artist", "gold.dim_artist", "artist_key"),
    ),
    Check(
        "bridge_to_dim_track",
        "integrity",
        "error",
        "Every bridged track exists.",
        _foreign_key("gold.bridge_track_artist", "gold.dim_track", "track_key"),
    ),
    Check(
        "dim_track_lead_artist_exists",
        "integrity",
        "error",
        "Every track's lead artist exists in dim_artist.",
        "SELECT t.* FROM gold.dim_track AS t LEFT JOIN gold.dim_artist AS a "
        "ON a.artist_key = t.lead_artist_key WHERE a.artist_key IS NULL",
    ),
    # ---------------------------------------------------------------- business rules
    Check(
        "scd2_versions_do_not_overlap",
        "business rule",
        "error",
        "Validity windows of a track's versions never overlap.",
        """
        SELECT a.track_key, a.version_number, b.version_number AS overlaps_version
        FROM gold.dim_track_version AS a
        JOIN gold.dim_track_version AS b
          ON a.track_key = b.track_key AND a.version_number < b.version_number
         AND a.valid_to >= b.valid_from
        """,
    ),
    Check(
        "scd2_one_current_version",
        "business rule",
        "error",
        "Each track has exactly one current version.",
        """
        SELECT track_key, count(*) FILTER (WHERE is_current) AS n_current
        FROM gold.dim_track_version GROUP BY track_key
        HAVING count(*) FILTER (WHERE is_current) <> 1
        """,
    ),
    Check(
        "fact_version_matches_source",
        "business rule",
        "error",
        "The version a fact row points to has exactly the attributes seen in the source that day.",
        """
        SELECT f.chart_date, f.chart_position, s.album_type, v.album_type AS version_album_type
        FROM gold.fact_chart_entry AS f
        JOIN silver.int_chart_entries AS s USING (chart_date, chart_position)
        JOIN gold.dim_track_version AS v USING (track_version_key)
        WHERE s.artist_credit IS DISTINCT FROM v.artist_credit
           OR s.album_type IS DISTINCT FROM v.album_type
           OR s.album_total_tracks IS DISTINCT FROM v.album_total_tracks
           OR s.duration_ms IS DISTINCT FROM v.duration_ms
           OR s.is_explicit IS DISTINCT FROM v.is_explicit
           OR s.album_cover_url IS DISTINCT FROM v.album_cover_url
           OR s.release_date IS DISTINCT FROM v.release_date
        """,
    ),
    Check(
        "one_lead_artist_per_track",
        "business rule",
        "error",
        "Each track has exactly one lead artist in the bridge.",
        """
        SELECT track_key, count(*) FILTER (WHERE is_lead_artist) AS n_leads
        FROM gold.bridge_track_artist GROUP BY track_key
        HAVING count(*) FILTER (WHERE is_lead_artist) <> 1
        """,
    ),
    Check(
        "attribution_weights_sum_to_one",
        "business rule",
        "error",
        "Collaboration weights per track sum to 1, so weighted artist metrics never double count.",
        """
        SELECT track_key, sum(attribution_weight) AS total_weight
        FROM gold.bridge_track_artist GROUP BY track_key
        HAVING abs(sum(attribution_weight) - 1) > 1e-9
        """,
    ),
    Check(
        "movement_metrics_consistent",
        "business rule",
        "error",
        "position_change equals previous_position - chart_position; debuts have no history.",
        """
        SELECT * FROM gold.fact_chart_entry
        WHERE position_change IS DISTINCT FROM previous_position - chart_position
           OR (entry_status = 'debut' AND chart_days_to_date <> 1)
           OR current_streak_days > chart_days_to_date
           OR peak_position_to_date > chart_position
        """,
    ),
    # ---------------------------------------------------------------- marts reconcile to the fact
    Check(
        "track_mart_reconciles_to_fact",
        "reconciliation",
        "error",
        "mart_track_performance has one row per track and its chart days sum to the fact.",
        """
        SELECT m.n_rows, m.chart_days, t.n_tracks, f.n_entries
        FROM (SELECT count(*) AS n_rows, sum(total_chart_days) AS chart_days
              FROM marts.mart_track_performance) AS m,
             (SELECT count(*) AS n_tracks FROM gold.dim_track) AS t,
             (SELECT count(*) AS n_entries FROM gold.fact_chart_entry) AS f
        WHERE m.n_rows <> t.n_tracks OR m.chart_days <> f.n_entries
        """,
    ),
    Check(
        "artist_mart_weights_reconcile",
        "reconciliation",
        "error",
        "Weighted artist chart days sum exactly to the number of chart entries.",
        """
        SELECT a.weighted, f.n_entries
        FROM (SELECT sum(weighted_chart_days) AS weighted FROM marts.mart_artist_performance) AS a,
             (SELECT count(*) AS n_entries FROM gold.fact_chart_entry) AS f
        WHERE abs(a.weighted - f.n_entries) > 0.5
        """,
    ),
    Check(
        "daily_mart_one_row_per_snapshot",
        "reconciliation",
        "error",
        "mart_daily_chart has exactly one row per chart snapshot.",
        """
        SELECT d.n_rows, f.n_days
        FROM (SELECT count(*) AS n_rows, count(DISTINCT chart_date) AS n_dates
              FROM marts.mart_daily_chart) AS d,
             (SELECT count(DISTINCT chart_date) AS n_days FROM gold.fact_chart_entry) AS f
        WHERE d.n_rows <> f.n_days OR d.n_dates <> f.n_days
        """,
    ),
    Check(
        "track_mart_metrics_consistent",
        "business rule",
        "error",
        "Peak is never worse than debut, and chart-day counts are internally consistent.",
        """
        SELECT track_title, debut_position, peak_position, total_chart_days,
               chart_days_first_180, longest_streak_days
        FROM marts.mart_track_performance
        WHERE peak_position > debut_position
           OR chart_days_first_180 > total_chart_days
           OR longest_streak_days > total_chart_days
           OR days_at_no1 > days_in_top10
           OR (peaked_on_debut AND peak_position <> debut_position)
        """,
    ),
    Check(
        "daily_mart_shares_in_range",
        "validity",
        "error",
        "Daily shares lie in [0, 1] and HHI in [0, 10000].",
        """
        SELECT * FROM marts.mart_daily_chart
        WHERE turnover_rate NOT BETWEEN 0 AND 1
           OR explicit_share NOT BETWEEN 0 AND 1
           OR collaboration_share NOT BETWEEN 0 AND 1
           OR holiday_track_share NOT BETWEEN 0 AND 1
           OR artist_hhi NOT BETWEEN 0 AND 10000
        """,
    ),
    # ---------------------------------------------------------------- ML feature table
    Check(
        "ml_features_one_row_per_debut",
        "reconciliation",
        "error",
        "ml.track_features has exactly one row per track with a known debut.",
        """
        SELECT m.n_rows, m.n_keys, t.n_tracks
        FROM (SELECT count(*) AS n_rows, count(DISTINCT track_key) AS n_keys
              FROM ml.track_features) AS m,
             (SELECT count(*) AS n_tracks FROM marts.mart_track_performance
              WHERE NOT is_left_censored) AS t
        WHERE m.n_rows <> t.n_tracks OR m.n_keys <> t.n_tracks
        """,
    ),
    Check(
        "ml_features_complete",
        "completeness",
        "error",
        "No model feature is NULL or NaN (models would silently drop or crash on them).",
        """
        SELECT track_title, debut_date FROM ml.track_features
        WHERE debut_position IS NULL OR debut_popularity IS NULL OR release_age_days IS NULL
           OR duration_minutes IS NULL OR isnan(duration_minutes)
           OR artist_prior_tracks IS NULL OR artist_prior_chart_days IS NULL
           OR w1_chart_days IS NULL OR w1_best_position IS NULL OR w1_max_popularity IS NULL
           OR w1_day7_position IS NULL OR w1_position_change IS NULL
           OR w1_position_slope IS NULL OR isnan(w1_position_slope)
        """,
    ),
    Check(
        "ml_week_one_window_respected",
        "business rule",
        "error",
        "Week-one features describe at most 7 days, starting at the debut.",
        """
        SELECT track_title, w1_chart_days, debut_position, w1_best_position, w1_day7_position
        FROM ml.track_features
        WHERE w1_chart_days NOT BETWEEN 1 AND 7
           OR w1_best_position > debut_position
           OR w1_day7_position NOT BETWEEN 1 AND 51
           OR w1_climbed <> (w1_best_position < debut_position)
        """,
    ),
    Check(
        "ml_label_only_when_observable",
        "business rule",
        "error",
        "The 180-day label exists exactly when the full 180-day window is observed.",
        """
        SELECT track_title, has_label, lasts_30_days FROM ml.track_features
        WHERE has_label <> (lasts_30_days IS NOT NULL)
        """,
    ),
    # ---------------------------------------------------------------- known source issues (warn)
    Check(
        "missing_snapshot_days",
        "source profile",
        "warn",
        "Calendar days inside the chart period with no snapshot in the source.",
        """
        SELECT calendar_date, day_name FROM gold.dim_date
        WHERE NOT has_chart_snapshot
          AND calendar_date BETWEEN (SELECT min(chart_date) FROM gold.fact_chart_entry)
                                AND (SELECT max(chart_date) FROM gold.fact_chart_entry)
        """,
    ),
    Check(
        "release_attributes_flap",
        "source profile",
        "warn",
        "Tracks whose chart entry alternates between releases (e.g. single <-> album) and "
        "returns to an earlier attribute set. SCD2 keeps every switch.",
        """
        SELECT t.track_title, t.lead_artist_name, count(*) AS n_versions
        FROM gold.dim_track_version AS v JOIN gold.dim_track AS t USING (track_key)
        WHERE v.track_key IN (
            SELECT track_key FROM gold.dim_track_version
            GROUP BY track_key, artist_credit, album_type, album_total_tracks, duration_ms,
                     is_explicit, album_cover_url, release_date
            HAVING count(*) > 1
        )
        GROUP BY ALL
        """,
        sample_order="n_versions DESC, track_title",
    ),
    Check(
        "imprecise_release_dates",
        "source profile",
        "warn",
        "Releases known only to the month or year (normalised to the first day of the period).",
        """
        SELECT DISTINCT t.track_title, t.lead_artist_name, v.release_date_precision, v.release_date
        FROM gold.dim_track_version AS v JOIN gold.dim_track AS t USING (track_key)
        WHERE v.release_date_precision <> 'day'
        """,
    ),
    Check(
        "artist_name_case_variants",
        "source profile",
        "warn",
        "The same artist is spelled with different letter case across credits (merged into one).",
        """
        SELECT lower(artist_name) AS artist, list(DISTINCT artist_name ORDER BY artist_name)
            AS spellings
        FROM silver.artist_credit_parts GROUP BY 1 HAVING count(DISTINCT artist_name) > 1
        """,
    ),
    Check(
        "release_after_first_chart_day",
        "source profile",
        "warn",
        "Version release date is after the day it charted (the chart links to a later reissue).",
        """
        SELECT t.track_title, v.version_number, v.release_date, v.valid_from
        FROM gold.dim_track_version AS v JOIN gold.dim_track AS t USING (track_key)
        WHERE v.release_date > v.valid_from
        """,
    ),
)


def count_source_rows(raw_csv: Path) -> int:
    """Count data rows with Python's csv module, independently of DuckDB's reader."""
    with raw_csv.open(newline="", encoding="utf-8") as fh:
        return sum(1 for _ in csv.reader(fh)) - 1  # minus header


def _source_reconciliation(raw_csv: Path) -> Check:
    expected = count_source_rows(raw_csv)
    return Check(
        "source_reconciles_to_bronze",
        "completeness",
        "error",
        "Bronze row count equals an independent count of the source CSV.",
        f"""
        SELECT {expected} AS source_rows, count(*) AS bronze_rows
        FROM bronze.raw_chart_snapshots HAVING count(*) <> {expected}
        """,
    )


def run_checks(con: duckdb.DuckDBPyConnection, raw_csv: Path | None = None) -> list[CheckResult]:
    checks = list(CHECKS)
    if raw_csv is not None:
        checks.insert(0, _source_reconciliation(raw_csv))
    results = []
    for check in checks:
        [(n,)] = con.execute(f"SELECT count(*) FROM ({check.sql})").fetchall()
        result = CheckResult(check, n)
        if n:
            rel = con.execute(
                f"SELECT * FROM ({check.sql}) ORDER BY {check.sample_order} LIMIT {SAMPLE_SIZE}"
            )
            result.columns = [d[0] for d in rel.description]
            result.sample = rel.fetchall()
        results.append(result)
    return results


def _profile(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    [row] = con.execute(
        """
        SELECT
            (SELECT count(*) FROM gold.fact_chart_entry),
            (SELECT min(chart_date) FROM gold.fact_chart_entry),
            (SELECT max(chart_date) FROM gold.fact_chart_entry),
            (SELECT count(DISTINCT chart_date) FROM gold.fact_chart_entry),
            (SELECT count(*) FROM gold.dim_track),
            (SELECT count(*) FROM gold.dim_track_version),
            (SELECT count(*) FROM gold.dim_artist)
        """
    ).fetchall()
    rows, first, last, days, tracks, versions, artists = row
    return [
        ("Chart entries (fact rows)", f"{rows:,}"),
        ("Chart period", f"{first} to {last}"),
        ("Daily snapshots", f"{days:,}"),
        ("Distinct tracks", f"{tracks:,}"),
        ("Track versions (SCD2)", f"{versions:,}"),
        ("Distinct artists", f"{artists:,}"),
    ]


def _md_cell(value: object) -> str:
    text = "NULL" if value is None else str(value)
    if len(text) > 60:
        text = text[:57] + "..."
    return text.replace("|", "\\|").replace("\n", " ")


def render_report(results: list[CheckResult], profile: list[tuple[str, str]]) -> str:
    errors = [r for r in results if r.check.severity == "error"]
    warns = [r for r in results if r.check.severity == "warn"]
    passed_errors = sum(r.passed for r in errors)
    status = "PASSING" if passed_errors == len(errors) else "FAILING"

    out = [
        "# Data Quality Report",
        "",
        "> Generated by `spotify-pipeline check`. Do not edit by hand. CI regenerates this file "
        "and fails if it is out of date.",
        "",
        f"**Status: {status}**: {passed_errors}/{len(errors)} blocking checks passed, "
        f"{sum(not r.passed for r in warns)} documented source issues.",
        "",
        "## Dataset profile",
        "",
        "| Metric | Value |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in profile],
        "",
        "## Results",
        "",
        "| | Check | Category | Severity | Failing rows | Rule |",
        "|---|---|---|---|---:|---|",
    ]
    for r in results:
        icon = "✅" if r.passed else ("⚠️" if r.check.severity == "warn" else "❌")
        out.append(
            f"| {icon} | `{r.check.name}` | {r.check.category} | {r.check.severity} | "
            f"{r.failing_rows:,} | {r.check.description} |"
        )

    failing = [r for r in results if not r.passed]
    if failing:
        out += ["", "## Findings", ""]
        for r in failing:
            out += [
                f"### `{r.check.name}` ({r.failing_rows:,} rows)",
                "",
                r.check.description,
                "",
                "| " + " | ".join(r.columns) + " |",
                "|" + "---|" * len(r.columns),
                *["| " + " | ".join(_md_cell(v) for v in row) + " |" for row in r.sample],
                "",
            ]
            if r.failing_rows > len(r.sample):
                out += [f"_Showing {len(r.sample)} of {r.failing_rows:,} rows._", ""]
    return "\n".join(out).rstrip() + "\n"


def write_report(con: duckdb.DuckDBPyConnection, results: list[CheckResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(results, _profile(con)), encoding="utf-8")
