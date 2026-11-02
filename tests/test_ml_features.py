"""Point-in-time correctness of ml.track_features: no feature may see the future."""

from dataclasses import replace

from conftest import rows, write_fixture_csv

from spotify_pipeline import pipeline

# Every column that a model consumes (labels, survival and availability excluded).
FEATURE_COLUMNS = (
    "debut_position, debut_popularity, release_age_days, is_new_release, is_collaboration, "
    "n_credited_artists, debut_is_explicit, is_single, duration_minutes, "
    "debut_in_holiday_season, artist_prior_tracks, artist_prior_chart_days, w1_chart_days, "
    "w1_best_position, w1_max_popularity, w1_on_chart_day7, w1_day7_position, "
    "w1_position_change, w1_position_slope, w1_climbed"
)


def features(con):
    return rows(con, f"SELECT track_title, {FEATURE_COLUMNS} FROM ml.track_features ORDER BY 1")


def test_left_censored_tracks_are_excluded(built):
    titles = {t for (t,) in rows(built, "SELECT track_title FROM ml.track_features")}
    assert titles == {"Song D"}  # A, B and C were already charting on the first snapshot


def test_artist_history_uses_only_earlier_days(built):
    # Song D (lead: Artist X) debuts 2024-01-02. Artist X's Song C charted on 2024-01-01
    # (counts) and on 2024-01-02 (same day as the debut, so it must NOT count).
    [(tracks, days)] = rows(
        built,
        "SELECT artist_prior_tracks, artist_prior_chart_days FROM ml.track_features "
        "WHERE track_title = 'Song D'",
    )
    assert (tracks, days) == (1, 1)


def test_week_one_features(built):
    # Song D: #3 on 01-02, absent 01-03, #3 again on 01-05; not on chart on day 7 (01-08).
    [row] = rows(
        built,
        "SELECT w1_chart_days, w1_best_position, w1_on_chart_day7, w1_day7_position, "
        "w1_position_change, w1_climbed FROM ml.track_features WHERE track_title = 'Song D'",
    )
    assert row == (2, 3, False, 51, 3 - 51, False)


def test_future_data_does_not_change_features(fixture_settings, tmp_path):
    """Append chart days far in the future: every feature must stay identical."""
    con = pipeline.connect(fixture_settings.database)
    pipeline.build(con, fixture_settings)
    before = features(con)
    con.close()

    future = [
        "2024-03-01,1,Song D,Artist X & Peso Pluma,99,210000,album,9,2023-12-20,True,https://img/x",
        "2024-03-01,2,Song A,Drake,50,200000,single,1,2023-12-01,True,https://img/a1",
        "2024-03-01,3,Song E,New Artist,70,190000,single,1,2024-02-28,False,https://img/e",
    ]
    later = replace(
        fixture_settings,
        raw_csv=write_fixture_csv(tmp_path / "with_future.csv", future),
        database=tmp_path / "later.duckdb",
    )
    con = pipeline.connect(later.database)
    pipeline.build(con, later)
    after = [r for r in features(con) if r[0] != "Song E"]  # Song E debuts in the future
    con.close()
    assert after == before
