-- =============================================================================
-- SILVER | stg_chart_entries
-- Typed, trimmed and renamed copy of bronze. TRY_CAST turns bad values into
-- NULLs instead of crashing; the data-quality suite then fails loudly on them.
--
-- release_date arrives in three precisions ('2023-04-28', '2019-05', '1962').
-- It is normalised to the first day of the period, and the precision is kept
-- so analysts never mistake '1962' for 1 January 1962.
-- Grain: one row per chart date x chart position.
-- =============================================================================
CREATE OR REPLACE TABLE silver.stg_chart_entries AS
WITH typed AS (
    SELECT
        TRY_CAST(date AS DATE)            AS chart_date,
        TRY_CAST(position AS INTEGER)     AS chart_position,
        trim(song)                        AS track_title,
        trim(artist)                      AS artist_credit,
        TRY_CAST(popularity AS INTEGER)   AS popularity,
        TRY_CAST(duration_ms AS INTEGER)  AS duration_ms,
        lower(trim(album_type))           AS album_type,
        TRY_CAST(total_tracks AS INTEGER) AS album_total_tracks,
        trim(release_date)                AS release_date_raw,
        TRY_CAST(is_explicit AS BOOLEAN)  AS is_explicit,
        trim(album_cover_url)             AS album_cover_url,
        _source_row_number
    FROM bronze.raw_chart_snapshots
)
SELECT
    * EXCLUDE (release_date_raw, _source_row_number),
    CASE
        WHEN regexp_full_match(release_date_raw, '\d{4}-\d{2}-\d{2}') THEN TRY_CAST(release_date_raw AS DATE)
        WHEN regexp_full_match(release_date_raw, '\d{4}-\d{2}')       THEN TRY_CAST(release_date_raw || '-01' AS DATE)
        WHEN regexp_full_match(release_date_raw, '\d{4}')             THEN TRY_CAST(release_date_raw || '-01-01' AS DATE)
    END AS release_date,
    CASE
        WHEN regexp_full_match(release_date_raw, '\d{4}-\d{2}-\d{2}') THEN 'day'
        WHEN regexp_full_match(release_date_raw, '\d{4}-\d{2}')       THEN 'month'
        WHEN regexp_full_match(release_date_raw, '\d{4}')             THEN 'year'
    END AS release_date_precision,
    release_date_raw,
    _source_row_number
FROM typed;
