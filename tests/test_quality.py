"""The data-quality suite passes on real data and actually catches broken data."""

import pytest

from spotify_pipeline import quality


def by_name(results):
    return {r.check.name: r for r in results}


def test_all_blocking_checks_pass_on_real_data(real_warehouse):
    con, settings = real_warehouse
    results = quality.run_checks(con, settings.raw_csv)
    failures = [r.check.name for r in results if r.check.severity == "error" and not r.passed]
    assert failures == []


def test_known_source_issues_are_reported(real_warehouse):
    con, settings = real_warehouse
    results = by_name(quality.run_checks(con, settings.raw_csv))
    assert results["missing_snapshot_days"].failing_rows == 4
    assert not results["release_attributes_flap"].passed


@pytest.mark.parametrize(
    ("sabotage", "expected_failure"),
    [
        (
            "INSERT INTO gold.fact_chart_entry SELECT * FROM gold.fact_chart_entry LIMIT 1",
            "fact_grain_unique",
        ),
        (
            "UPDATE gold.fact_chart_entry SET popularity = 150 WHERE chart_position = 1",
            "popularity_in_range",
        ),
        ("DELETE FROM gold.dim_track WHERE track_title = 'Song A'", "fact_to_dim_track"),
        ("UPDATE gold.dim_track_version SET is_current = true", "scd2_one_current_version"),
        (
            "UPDATE gold.bridge_track_artist SET attribution_weight = 1",
            "attribution_weights_sum_to_one",
        ),
    ],
)
def test_checks_catch_corruption(built, sabotage, expected_failure):
    assert by_name(quality.run_checks(built))[expected_failure].passed
    built.execute(sabotage)
    assert not by_name(quality.run_checks(built))[expected_failure].passed


def test_report_renders(built, fixture_settings):
    results = quality.run_checks(built, fixture_settings.raw_csv)
    quality.write_report(built, results, fixture_settings.quality_report)
    text = fixture_settings.quality_report.read_text()
    assert text.startswith("# Data Quality Report")
    assert "`missing_snapshot_days`" in text
