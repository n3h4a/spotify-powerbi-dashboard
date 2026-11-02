"""Mart behaviour on the hand-built fixture chart (see conftest.py for the scenario)."""

from conftest import rows


def track(con, title):
    [row] = rows(
        con,
        "SELECT debut_position, peak_position, peaked_on_debut, chart_days_debut_to_peak, "
        "total_chart_days, n_reentries, longest_streak_days, release_age_at_debut, "
        "is_left_censored, is_right_censored "
        f"FROM marts.mart_track_performance WHERE track_title = '{title}'",
    )
    return row


def test_track_that_peaks_on_debut(built):
    # Song A: #1 on its debut day, never better, on every snapshot.
    assert track(built, "Song A") == (1, 1, True, 0, 4, 0, 4, "recent", True, True)


def test_track_that_climbs(built):
    # Song C: debuts #3, reaches #1 on its second chart day.
    debut, peak, peaked_on_debut, days_to_peak, *_ = track(built, "Song C")
    assert (debut, peak, peaked_on_debut, days_to_peak) == (3, 1, False, 1)


def test_reentry_and_catalogue_classification(built):
    *_, total, reentries, streak, age, left, right = track(built, "Song B")
    assert (total, reentries, streak, age) == (2, 1, 1, "catalog")
    assert left and not right


def test_artist_weights_reconcile(built):
    [(weighted, entries)] = rows(
        built,
        "SELECT (SELECT sum(weighted_chart_days) FROM marts.mart_artist_performance), "
        "(SELECT count(*) FROM gold.fact_chart_entry)",
    )
    assert weighted == entries == 12


def test_daily_churn(built):
    daily = rows(
        built,
        "SELECT chart_date::VARCHAR, n_debuts, n_reentries, turnover_rate "
        "FROM marts.mart_daily_chart ORDER BY chart_date",
    )
    assert daily == [
        ("2024-01-01", None, None, None),  # no previous chart to compare with
        ("2024-01-02", 1, 0, 0.02),  # Song D debuts, Song B drops out
        ("2024-01-03", 0, 1, 0.02),  # Song B re-enters
        ("2024-01-05", 0, 1, 0.02),  # Song D re-enters after a gap
    ]
