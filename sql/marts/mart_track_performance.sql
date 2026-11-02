-- =============================================================================
-- MARTS | mart_track_performance
-- One row per track summarising its whole chart life: debut, peak, longevity,
-- re-entries, release timing, and the censoring flags needed for honest stats.
--
-- Censoring: the dataset is a window (2023-05-18 to 2024-11-27), not the
-- full history of the chart.
--   is_left_censored   already charting on the first snapshot, so the real
--                      debut date and position are unknown
--   is_right_censored  still charting on the last snapshot, so total chart
--                      life is a lower bound
-- chart_days_first_180 counts chart days in the 180 days after debut. It is
-- the fair longevity metric for comparing tracks that debuted at different
-- times; use it only where has_full_180_day_window is true.
-- Grain: one row per track.
-- =============================================================================
CREATE OR REPLACE TABLE marts.mart_track_performance AS
WITH bounds AS (
    SELECT min(chart_date) AS first_snapshot, max(chart_date) AS last_snapshot
    FROM gold.fact_chart_entry
),
debut AS (
    SELECT track_key, chart_date AS debut_date, chart_position AS debut_position,
           track_version_key AS debut_version_key
    FROM gold.fact_chart_entry
    WHERE chart_days_to_date = 1
),
first_peak AS (
    -- The first day a track reached its best-ever position.
    SELECT track_key,
           min(chart_position)                                   AS peak_position,
           arg_min(chart_date, (chart_position, chart_date))     AS first_peak_date,
           arg_min(chart_days_to_date, (chart_position, chart_date)) AS chart_day_of_peak
    FROM gold.fact_chart_entry
    GROUP BY track_key
),
lifetime AS (
    SELECT f.track_key,
           count(*)                                              AS total_chart_days,
           count(*) FILTER (WHERE f.entry_status = 're-entry')   AS n_reentries,
           max(f.current_streak_days)                            AS longest_streak_days,
           count(*) FILTER (WHERE f.chart_position = 1)          AS days_at_no1,
           count(*) FILTER (WHERE f.chart_position <= 10)        AS days_in_top10,
           round(avg(f.popularity), 1)                           AS avg_popularity,
           max(f.popularity)                                     AS max_popularity,
           avg(CASE WHEN d.is_holiday_season THEN 1.0 ELSE 0.0 END) AS holiday_season_share,
           max(f.chart_date)                                     AS last_chart_date
    FROM gold.fact_chart_entry AS f
    JOIN gold.dim_date AS d USING (date_key)
    GROUP BY f.track_key
),
first_180 AS (
    SELECT f.track_key, count(*) AS chart_days_first_180
    FROM gold.fact_chart_entry AS f
    JOIN debut AS db USING (track_key)
    WHERE f.chart_date < db.debut_date + 180
    GROUP BY f.track_key
),
credits AS (
    SELECT track_key, max(n_credited_artists) AS n_credited_artists
    FROM gold.bridge_track_artist
    GROUP BY track_key
)
SELECT
    t.track_key,
    t.track_title,
    t.lead_artist_name,
    t.lead_artist_key,
    c.n_credited_artists,
    c.n_credited_artists > 1                                   AS is_collaboration,
    db.debut_date,
    db.debut_position,
    l.last_chart_date,
    fp.peak_position,
    fp.first_peak_date,
    CAST(fp.chart_day_of_peak - 1 AS INTEGER)                  AS chart_days_debut_to_peak,
    fp.chart_day_of_peak = 1                                   AS peaked_on_debut,
    CAST(l.total_chart_days AS INTEGER)                        AS total_chart_days,
    CAST(l.n_reentries AS INTEGER)                             AS n_reentries,
    l.longest_streak_days,
    CAST(l.days_at_no1 AS INTEGER)                             AS days_at_no1,
    CAST(l.days_in_top10 AS INTEGER)                           AS days_in_top10,
    l.avg_popularity,
    l.max_popularity,
    v.album_type                                               AS debut_album_type,
    v.is_explicit                                              AS debut_is_explicit,
    v.duration_ms                                              AS debut_duration_ms,
    v.release_date,
    v.release_date_precision,
    CASE WHEN v.release_date_precision = 'day'
         THEN CAST(db.debut_date - v.release_date AS INTEGER) END AS days_release_to_debut,
    CASE
        WHEN db.debut_date - v.release_date <= 30  THEN 'new release'
        WHEN db.debut_date - v.release_date <= 365 THEN 'recent'
        ELSE 'catalog'
    END                                                        AS release_age_at_debut,
    -- Seasonal catalogue: charts only in the holiday season AND is an older
    -- release. The age condition excludes new albums that happen to drop in
    -- November (e.g. Linkin Park, Kendrick Lamar in Nov 2024).
    l.holiday_season_share >= 0.9
        AND db.debut_date - v.release_date > 365                  AS is_holiday_track,
    db.debut_date = b.first_snapshot                           AS is_left_censored,
    l.last_chart_date = b.last_snapshot                        AS is_right_censored,
    db.debut_date <= b.last_snapshot - 180                     AS has_full_180_day_window,
    CAST(f180.chart_days_first_180 AS INTEGER)                 AS chart_days_first_180
FROM gold.dim_track AS t
JOIN debut AS db USING (track_key)
JOIN first_peak AS fp USING (track_key)
JOIN lifetime AS l USING (track_key)
JOIN first_180 AS f180 USING (track_key)
JOIN credits AS c USING (track_key)
JOIN gold.dim_track_version AS v ON v.track_version_key = db.debut_version_key
CROSS JOIN bounds AS b
ORDER BY total_chart_days DESC, track_title;
