"""Behaviour of each model, verified on the hand-built fixture chart."""

from datetime import date

from conftest import rows

from spotify_pipeline import pipeline


def track_key(con, title):
    [(key,)] = rows(con, f"SELECT track_key FROM gold.dim_track WHERE track_title = '{title}'")
    return key


def test_mixed_line_endings_are_ingested(built):
    assert rows(built, "SELECT count(*) FROM bronze.raw_chart_snapshots") == [(12,)]
    assert rows(built, "SELECT count(*) FROM gold.fact_chart_entry") == [(12,)]


def test_release_date_precision_is_preserved(built):
    result = rows(
        built,
        "SELECT DISTINCT release_date, release_date_precision FROM silver.stg_chart_entries "
        "WHERE track_title = 'Song B'",
    )
    assert result == [(date(1978, 1, 1), "year")]


def test_protected_and_case_variant_artists(built):
    artists = {name for (name,) in rows(built, "SELECT artist_name FROM gold.dim_artist")}
    assert artists == {
        "Drake",
        "SZA",
        "Earth, Wind & Fire",
        "sped up + slowed",
        "Artist X",
        "Peso Pluma",
    }


def test_credit_drift_keeps_one_track(built):
    assert rows(built, "SELECT count(*) FROM gold.dim_track") == [(4,)]
    key = track_key(built, "Song A")
    credits = rows(
        built,
        f"SELECT artist_credit FROM gold.dim_track_version WHERE track_key = '{key}' "
        "ORDER BY version_number",
    )
    assert credits == [("Drake & SZA",), ("Drake",)]


def test_bridge_roles_and_weights(built):
    key = track_key(built, "Song A")
    bridge = rows(
        built,
        f"SELECT a.artist_name, b.artist_role, b.attribution_weight "
        f"FROM gold.bridge_track_artist b JOIN gold.dim_artist a USING (artist_key) "
        f"WHERE track_key = '{key}' ORDER BY credit_order",
    )
    assert bridge == [("Drake", "lead", 0.5), ("SZA", "featured", 0.5)]


def test_scd2_records_flapping_as_separate_versions(built):
    key = track_key(built, "Song C")
    versions = rows(
        built,
        f"SELECT version_number, album_type, valid_from, valid_to, is_current "
        f"FROM gold.dim_track_version WHERE track_key = '{key}' ORDER BY version_number",
    )
    assert versions == [
        (1, "single", date(2024, 1, 1), date(2024, 1, 1), False),
        (2, "album", date(2024, 1, 2), date(2024, 1, 2), False),
        (3, "single", date(2024, 1, 3), date(9999, 12, 31), True),
    ]


def test_movement_metrics_ignore_missing_snapshot_days(built):
    key = track_key(built, "Song A")
    history = rows(
        built,
        f"SELECT chart_date, previous_position, position_change, entry_status, "
        f"chart_days_to_date, current_streak_days, peak_position_to_date "
        f"FROM gold.fact_chart_entry WHERE track_key = '{key}' ORDER BY chart_date",
    )
    assert history == [
        (date(2024, 1, 1), None, None, "debut", 1, 1, 1),
        (date(2024, 1, 2), 1, -1, "returning", 2, 2, 1),
        (date(2024, 1, 3), 2, 1, "returning", 3, 3, 1),
        # 2024-01-04 has no snapshot, so 01-05 still continues the streak.
        (date(2024, 1, 5), 1, 0, "returning", 4, 4, 1),
    ]


def test_reentry_resets_streak(built):
    key = track_key(built, "Song B")
    history = rows(
        built,
        f"SELECT entry_status, previous_position, chart_days_to_date, current_streak_days "
        f"FROM gold.fact_chart_entry WHERE track_key = '{key}' ORDER BY chart_date",
    )
    assert history == [("debut", None, 1, 1), ("re-entry", None, 2, 1)]


def test_dim_date_covers_whole_years_and_flags_gaps(built):
    assert rows(built, "SELECT count(*) FROM gold.dim_date") == [(366,)]  # 2024 is a leap year
    flags = rows(
        built,
        "SELECT calendar_date, has_chart_snapshot FROM gold.dim_date "
        "WHERE calendar_date BETWEEN '2024-01-03' AND '2024-01-05' ORDER BY 1",
    )
    assert [f for _, f in flags] == [True, False, True]


def test_rebuild_is_idempotent(built, fixture_settings):
    before = rows(built, "SELECT * FROM gold.fact_chart_entry ORDER BY ALL")
    pipeline.build(built, fixture_settings)
    assert rows(built, "SELECT * FROM gold.fact_chart_entry ORDER BY ALL") == before


def test_export_writes_every_gold_and_mart_table(built, fixture_settings):
    files = pipeline.export(built, fixture_settings.export_dir)
    assert len(files) == 2 * len(pipeline.EXPORT_TABLES)
    assert all(f.stat().st_size > 0 for f in files)
