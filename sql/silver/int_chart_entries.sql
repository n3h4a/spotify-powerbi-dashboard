-- =============================================================================
-- SILVER | int_chart_entries
-- Conform each chart entry to a stable track identity.
--
-- The source has no track ID, and the artist credit of one recording drifts
-- over time (e.g. 'Drake & SZA' later appears as just 'Drake'). A track is
-- therefore identified by (title, lead artist): the lead artist is stable even
-- when featured credits change. Surrogate keys are deterministic MD5 hashes, so
-- rebuilding the warehouse always produces the same keys.
--
-- version_attributes_hash fingerprints every descriptive attribute that can
-- change; dim_track_version uses it to detect new versions (SCD Type 2).
-- Grain: one row per chart date x chart position.
-- =============================================================================
CREATE OR REPLACE TABLE silver.int_chart_entries AS
SELECT
    e.*,
    lead_artist.artist_name AS lead_artist_name,
    md5('track|' || lower(e.track_title) || '|' || lower(lead_artist.artist_name)) AS track_key,
    md5(concat_ws('|',
        coalesce(e.artist_credit, '<null>'),
        coalesce(e.album_type, '<null>'),
        coalesce(CAST(e.album_total_tracks AS VARCHAR), '<null>'),
        coalesce(CAST(e.duration_ms AS VARCHAR), '<null>'),
        coalesce(CAST(e.is_explicit AS VARCHAR), '<null>'),
        coalesce(e.album_cover_url, '<null>'),
        coalesce(e.release_date_raw, '<null>')
    )) AS version_attributes_hash
FROM silver.stg_chart_entries AS e
LEFT JOIN silver.artist_credit_parts AS lead_artist
    ON  lead_artist.artist_credit = e.artist_credit
    AND lead_artist.credit_order = 1;
