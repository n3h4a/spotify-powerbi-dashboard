-- =============================================================================
-- GOLD | dim_track
-- One row per distinct recording (title + lead artist). Attributes that can
-- change over time (credits, album, duration...) live in dim_track_version.
-- Grain: one row per track.
-- =============================================================================
CREATE OR REPLACE TABLE gold.dim_track AS
SELECT
    track_key,
    arg_min(track_title, chart_date)                     AS track_title,
    arg_min(lead_artist_name, chart_date)                AS lead_artist_name,
    -- Unique display label: several different songs share a title ("Daylight").
    arg_min(track_title, chart_date) || ' · ' || arg_min(lead_artist_name, chart_date)
                                                         AS track_label,
    md5('artist|' || lower(arg_min(lead_artist_name, chart_date))) AS lead_artist_key,
    min(chart_date)                                      AS first_chart_date,
    max(chart_date)                                      AS last_chart_date
FROM silver.int_chart_entries
GROUP BY track_key
ORDER BY first_chart_date, track_title;
