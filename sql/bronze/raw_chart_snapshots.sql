-- =============================================================================
-- BRONZE | raw_chart_snapshots
-- Land the source file exactly as received. Every column stays VARCHAR
-- (schema-on-read) so a malformed value can never break ingestion; typing and
-- validation happen downstream. Lineage columns record where each row came from.
--
-- The source mixes CRLF and LF line endings (it was assembled from files saved
-- on different operating systems), which DuckDB's strict parser rejects.
-- strict_mode is relaxed for that reason only; the data-quality suite
-- reconciles the bronze row count against an independent count of the file.
-- Grain: one row per line of the source CSV.
-- =============================================================================
CREATE OR REPLACE TABLE bronze.raw_chart_snapshots AS
SELECT
    date,
    position,
    song,
    artist,
    popularity,
    duration_ms,
    album_type,
    total_tracks,
    release_date,
    is_explicit,
    album_cover_url,
    parse_filename(filename)  AS _source_file,
    row_number() OVER ()      AS _source_row_number,
    current_timestamp         AS _loaded_at
FROM read_csv(
    '{{ raw_csv_path }}',
    header = true,
    delim = ',',
    quote = '"',
    escape = '"',
    strict_mode = false,
    all_varchar = true,
    filename = true
);
