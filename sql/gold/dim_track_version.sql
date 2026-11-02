-- =============================================================================
-- GOLD | dim_track_version   (Slowly Changing Dimension, Type 2)
-- A track's descriptive attributes change while it is charting: a single is
-- re-released on an album (album_type, total_tracks and cover change), a
-- featured artist is dropped from the credit, or the explicit flag flips.
-- Each unbroken run of identical attributes becomes one version, with a
-- validity window [valid_from, valid_to]. This is a gaps-and-islands problem:
-- flag a change whenever the attribute hash differs from the previous chart
-- day, then a running sum of the flags numbers the versions.
-- Grain: one row per track per version.
-- =============================================================================
CREATE OR REPLACE TABLE gold.dim_track_version AS
WITH daily AS (
    SELECT DISTINCT
        track_key, chart_date, version_attributes_hash,
        artist_credit, album_type, album_total_tracks, duration_ms, is_explicit,
        album_cover_url, release_date, release_date_precision
    FROM silver.int_chart_entries
),
flagged AS (
    SELECT
        *,
        CASE
            WHEN version_attributes_hash IS DISTINCT FROM lag(version_attributes_hash) OVER (
                PARTITION BY track_key ORDER BY chart_date
            ) THEN 1 ELSE 0
        END AS is_new_version
    FROM daily
),
numbered AS (
    SELECT
        *,
        sum(is_new_version) OVER (
            PARTITION BY track_key ORDER BY chart_date ROWS UNBOUNDED PRECEDING
        ) AS version_number
    FROM flagged
),
versions AS (
    SELECT
        track_key, version_number,
        artist_credit, album_type, album_total_tracks, duration_ms, is_explicit,
        album_cover_url, release_date, release_date_precision,
        min(chart_date) AS valid_from
    FROM numbered
    GROUP BY ALL
)
SELECT
    md5(track_key || '|v' || version_number)                           AS track_version_key,
    track_key,
    CAST(version_number AS INTEGER)                                    AS version_number,
    artist_credit,
    album_type,
    album_total_tracks,
    duration_ms,
    round(duration_ms / 60000.0, 2)                                    AS duration_minutes,
    is_explicit,
    release_date,
    release_date_precision,
    album_cover_url,
    valid_from,
    coalesce(
        lead(valid_from) OVER (PARTITION BY track_key ORDER BY version_number) - 1,
        DATE '9999-12-31'
    )                                                                  AS valid_to,
    lead(valid_from) OVER (PARTITION BY track_key ORDER BY version_number) IS NULL AS is_current
FROM versions
ORDER BY track_key, version_number;
