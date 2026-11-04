-- =============================================================================
-- GOLD | dim_track
-- One row per distinct recording (title + lead artist). Attributes that can
-- change over time (credits, album, duration...) live in dim_track_version.
-- chart_rank orders tracks by total days on chart (1 = longest-charting).
-- Grain: one row per track.
-- =============================================================================
CREATE OR REPLACE TABLE gold.dim_track AS
WITH tracks AS (
    SELECT
        track_key,
        arg_min(track_title, chart_date)                 AS track_title,
        arg_min(lead_artist_name, chart_date)            AS lead_artist_name,
        min(chart_date)                                  AS first_chart_date,
        max(chart_date)                                  AS last_chart_date,
        count(*)                                         AS total_chart_days
    FROM silver.int_chart_entries
    GROUP BY track_key
)
SELECT
    track_key,
    track_title,
    lead_artist_name,
    md5('artist|' || lower(lead_artist_name))            AS lead_artist_key,
    -- Unique display label. Most titles are unique; where several songs share a title
    -- ("Daylight"), the lead artist is appended so charts never merge two songs.
    CASE WHEN count(*) OVER (PARTITION BY lower(track_title)) > 1
         THEN track_title || ' (' || lead_artist_name || ')'
         ELSE track_title END                            AS track_label,
    -- 1 = most days on the chart. Unique, so it can order song lists by success.
    CAST(row_number() OVER (
        ORDER BY total_chart_days DESC, first_chart_date, track_title, track_key
    ) AS INTEGER)                                        AS chart_rank,
    first_chart_date,
    last_chart_date
FROM tracks
ORDER BY first_chart_date, track_title;
