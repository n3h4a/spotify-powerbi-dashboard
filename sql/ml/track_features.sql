-- =============================================================================
-- ML | track_features
-- One row per track with a known debut: model features, a classification
-- label, and survival-analysis columns.
--
-- Point-in-time rule (no leakage): every feature uses only data available at
-- prediction time.
--   launch-day features  the debut snapshot, release metadata, and the lead
--                        artist's chart history strictly BEFORE the debut date
--   week-one features    snapshots from debut_date to debut_date + 6
-- The label (lasts_30_days) looks 180 days ahead, so it is NULL wherever the
-- 180-day window is not fully observed.
--
-- Survival columns
--   chart_life_days   total chart days (the time scale for survival analysis)
--   chart_life_ended  event flag: the track has been absent for at least 14
--                     days before the data ends. Otherwise it is censored, since
--                     its chart life may continue.
-- Grain: one row per track (left-censored tracks excluded).
-- =============================================================================
CREATE OR REPLACE TABLE ml.track_features AS
WITH bounds AS (
    SELECT max(chart_date) AS last_snapshot FROM gold.fact_chart_entry
),
tracks AS (
    SELECT * FROM marts.mart_track_performance WHERE NOT is_left_censored
),
debut_row AS (
    SELECT f.track_key, f.popularity AS debut_popularity, d.is_holiday_season, d.day_of_week
    FROM gold.fact_chart_entry AS f
    JOIN gold.dim_date AS d USING (date_key)
    WHERE f.chart_days_to_date = 1
),
week_one AS (
    SELECT
        t.track_key,
        count(*)                                  AS w1_chart_days,
        min(f.chart_position)                     AS w1_best_position,
        max(f.popularity)                         AS w1_max_popularity,
        max(f.chart_date) = t.debut_date + 6      AS w1_on_chart_day7,
        arg_max(f.chart_position, f.chart_date)   AS w1_last_position,
        -- Least-squares slope of position over the week; negative = climbing.
        -- A single chart day has no trend (regr_slope would return NaN): use 0.
        CASE WHEN count(*) < 2 THEN 0.0
             ELSE regr_slope(f.chart_position, f.chart_date - t.debut_date) END
                                                  AS w1_position_slope
    FROM tracks AS t
    JOIN gold.fact_chart_entry AS f
      ON f.track_key = t.track_key
     AND f.chart_date BETWEEN t.debut_date AND t.debut_date + 6
    GROUP BY t.track_key, t.debut_date
),
artist_prior AS (
    -- Lead artist's chart presence before this track debuted (any credit).
    SELECT
        t.track_key,
        count(DISTINCT f.track_key)                AS artist_prior_tracks,
        count(f.track_key)                         AS artist_prior_chart_days
    FROM tracks AS t
    LEFT JOIN gold.bridge_track_artist AS b ON b.artist_key = t.lead_artist_key
    LEFT JOIN gold.fact_chart_entry AS f
      ON f.track_key = b.track_key
     AND f.chart_date < t.debut_date
    GROUP BY t.track_key
)
SELECT
    t.track_key,
    t.track_title,
    t.lead_artist_name,
    t.debut_date,
    -- launch-day features
    t.debut_position,
    dr.debut_popularity,
    greatest(t.debut_date - t.release_date, 0)               AS release_age_days,
    t.release_age_at_debut = 'new release'                   AS is_new_release,
    t.is_collaboration,
    t.n_credited_artists,
    t.debut_is_explicit,
    t.debut_album_type = 'single'                            AS is_single,
    round(t.debut_duration_ms / 60000.0, 3)                  AS duration_minutes,
    dr.is_holiday_season                                     AS debut_in_holiday_season,
    CAST(ap.artist_prior_tracks AS INTEGER)                  AS artist_prior_tracks,
    CAST(ap.artist_prior_chart_days AS INTEGER)              AS artist_prior_chart_days,
    -- week-one features
    CAST(w.w1_chart_days AS INTEGER)                         AS w1_chart_days,
    w.w1_best_position,
    w.w1_max_popularity,
    w.w1_on_chart_day7,
    CASE WHEN w.w1_on_chart_day7 THEN w.w1_last_position ELSE 51 END AS w1_day7_position,
    t.debut_position
        - CASE WHEN w.w1_on_chart_day7 THEN w.w1_last_position ELSE 51 END
                                                             AS w1_position_change,
    round(w.w1_position_slope, 4)                            AS w1_position_slope,
    w.w1_best_position < t.debut_position                    AS w1_climbed,
    -- availability flags
    t.debut_date <= b.last_snapshot - 6                      AS has_full_week_one,
    t.has_full_180_day_window                                AS has_label,
    -- classification label
    CASE WHEN t.has_full_180_day_window THEN t.chart_days_first_180 >= 30 END AS lasts_30_days,
    -- survival columns
    t.total_chart_days                                       AS chart_life_days,
    t.last_chart_date < b.last_snapshot - 14                 AS chart_life_ended
FROM tracks AS t
JOIN debut_row AS dr USING (track_key)
JOIN week_one AS w USING (track_key)
JOIN artist_prior AS ap USING (track_key)
CROSS JOIN bounds AS b
ORDER BY t.debut_date, t.track_title;
