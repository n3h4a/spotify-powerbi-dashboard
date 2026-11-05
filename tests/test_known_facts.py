"""Known facts about the real dataset.

The quality suite checks structure; these tests check meaning. Each assertion is a fact
that was verified by hand (or is simply true of the Global Top 50), so a subtle modelling
regression shows up as a readable failure such as "Espresso no longer peaked at #1".
"""

import pytest


@pytest.fixture(scope="module")
def con(real_warehouse):
    return real_warehouse[0]


def fetch(con, sql, *params):
    return con.execute(sql, params).fetchall()


def test_every_chart_has_fifty_songs_and_one_number_one(con):
    rows = fetch(
        con,
        """
        SELECT count(*), count(*) FILTER (WHERE chart_position = 1)
        FROM gold.fact_chart_entry GROUP BY chart_date""",
    )
    assert len(rows) == 556
    assert set(rows) == {(50, 1)}


def test_espresso(con):
    [row] = fetch(
        con,
        """
        SELECT m.total_chart_days, m.peak_position, m.days_at_no1, m.debut_is_explicit,
               year(m.release_date)
        FROM marts.mart_track_performance m WHERE m.track_title = 'Espresso'""",
    )
    assert row == (226, 1, 31, True, 2024)


def test_longest_number_one(con):
    rows = fetch(
        con,
        """
        SELECT t.track_title, t.lead_artist_name, count(*) AS n
        FROM gold.fact_chart_entry f JOIN gold.dim_track t USING (track_key)
        WHERE f.chart_position = 1 GROUP BY ALL ORDER BY n DESC LIMIT 2""",
    )
    assert rows == [
        ("Die With A Smile", "Lady Gaga", 77),
        ("Seven (feat. Latto) (Explicit Ver.)", "Jung Kook", 75),
    ]


def test_taylor_swift_owns_the_most_chart_real_estate(con):
    [(name, weighted, songs)] = fetch(
        con,
        """
        SELECT artist_name, weighted_chart_days, n_tracks
        FROM marts.mart_artist_performance WHERE artist_rank = 1""",
    )
    assert (name, weighted, songs) == ("Taylor Swift", 1871.0, 85)


def test_tortured_poets_takeover(con):
    """The Tortured Poets Department (19 Apr 2024) took 30 of 50 slots on 21 Apr."""
    [(slots,)] = fetch(
        con,
        """
        SELECT sum(b.attribution_weight)
        FROM gold.fact_chart_entry f
        JOIN gold.bridge_track_artist b USING (track_key)
        JOIN gold.dim_artist a USING (artist_key)
        WHERE f.chart_date = DATE '2024-04-21' AND a.artist_name = 'Taylor Swift'""",
    )
    assert slots == 30


def test_vultures_recredit_is_one_recording(con):
    """Spotify moved Vultures 1 songs from 'Kanye West' to his duo '¥$' on 16 Feb 2024."""
    rows = fetch(
        con,
        """
        SELECT t.lead_artist_name, list(a.artist_name ORDER BY b.credit_order)
        FROM gold.dim_track t
        JOIN gold.bridge_track_artist b USING (track_key)
        JOIN gold.dim_artist a USING (artist_key)
        WHERE t.track_title = 'CARNIVAL' GROUP BY ALL""",
    )
    assert rows == [("¥$", ["¥$", "Kanye West", "Ty Dolla $ign"])]


def test_various_artists_never_takes_real_credit(con):
    [(artists,)] = fetch(
        con,
        """
        SELECT list(a.artist_name)
        FROM gold.dim_track t
        JOIN gold.bridge_track_artist b USING (track_key)
        JOIN gold.dim_artist a USING (artist_key)
        WHERE t.track_title = 'Beautiful Things'""",
    )
    assert artists == ["Benson Boone"]


def test_same_title_different_songs_stay_separate(con):
    rows = fetch(
        con,
        """
        SELECT lead_artist_name FROM gold.dim_track WHERE track_title = 'Daylight' ORDER BY 1""",
    )
    assert [r[0] for r in rows] == ["BERKO CHAMP", "David Kushner", "Drake"]


def test_christmas(con):
    [(peak, after)] = fetch(
        con,
        """
        SELECT max(holiday_track_share) FILTER (WHERE chart_date = DATE '2023-12-26'),
               max(holiday_track_share) FILTER (WHERE chart_date = DATE '2023-12-28')
        FROM marts.mart_daily_chart""",
    )
    assert peak > 0.9 and after < 0.1
    flags = dict(
        fetch(
            con,
            """
        SELECT track_title, is_holiday_track FROM marts.mart_track_performance
        WHERE track_title IN ('All I Want for Christmas Is You', 'Last Christmas', 'Heather')""",
        )
    )
    assert flags["All I Want for Christmas Is You"] is True
    assert flags["Heather"] is False  # winter-themed, not holiday music


def test_new_music_friday(con):
    [(friday,)] = fetch(
        con,
        """
        SELECT avg(CASE WHEN dayname(release_date) = 'Friday' THEN 1.0 ELSE 0 END)
        FROM marts.mart_track_performance
        WHERE NOT is_left_censored AND release_age_at_debut = 'new release'
          AND release_date_precision = 'day'""",
    )
    assert 0.6 < friday < 0.75


def test_old_songs_resurging(con):
    """I Wanna Be Yours (2013) is the longest-charting song of the whole period."""
    [row] = fetch(
        con,
        """
        SELECT t.track_title, t.lead_artist_name, year(m.release_date), m.total_chart_days
        FROM gold.dim_track t JOIN marts.mart_track_performance m USING (track_key)
        WHERE t.chart_rank = 1""",
    )
    assert row == ("I Wanna Be Yours", "Arctic Monkeys", 2013, 548)
