-- =============================================================================
-- SILVER | int_chart_entries
-- Conform each chart entry to a stable track identity.
--
-- The source has no track ID, and the artist credit of one recording drifts
-- over time (e.g. 'Drake & SZA' later appears as just 'Drake'). A track is
-- therefore identified by (title, lead artist): the lead artist is stable even
-- when featured credits change. When even the lead credit changes, identical
-- title + duration links the credits back to one recording (see lead_map). Surrogate keys are deterministic MD5 hashes, so
-- rebuilding the warehouse always produces the same keys.
--
-- version_attributes_hash fingerprints every descriptive attribute that can
-- change; dim_track_version uses it to detect new versions (SCD Type 2).
-- Grain: one row per chart date x chart position.
-- =============================================================================
CREATE OR REPLACE TABLE silver.int_chart_entries AS
WITH with_lead AS (
    SELECT e.*, lead_artist.artist_name AS credited_lead
    FROM silver.stg_chart_entries AS e
    LEFT JOIN silver.artist_credit_parts AS lead_artist
        ON  lead_artist.artist_credit = e.artist_credit
        AND lead_artist.credit_order = 1
),
-- Same recording, different lead credit. Spotify sometimes re-credits a recording
-- mid-run (Kanye West -> his duo ¥$ on 16 Feb 2024) or lists it on a compilation
-- under "Various Artists". Identical title AND identical duration (to the
-- millisecond) identifies one recording; it is credited to the lead artist under
-- whom it charted most (a real artist is preferred over "Various Artists").
lead_days AS (
    SELECT lower(track_title) AS title_lc, duration_ms, credited_lead, count(*) AS n_days
    FROM with_lead
    GROUP BY ALL
),
canonical AS (
    SELECT title_lc, duration_ms, credited_lead AS canonical_lead
    FROM lead_days
    QUALIFY row_number() OVER (
        PARTITION BY title_lc, duration_ms
        ORDER BY credited_lead = 'Various Artists', n_days DESC, credited_lead
    ) = 1
),
-- One canonical lead per (title, credited lead): take the mapping of its most-charted
-- duration, so a track whose duration changed slightly between versions stays whole.
lead_map AS (
    SELECT l.title_lc, l.credited_lead, c.canonical_lead
    FROM lead_days AS l
    JOIN canonical AS c USING (title_lc, duration_ms)
    QUALIFY row_number() OVER (
        PARTITION BY l.title_lc, l.credited_lead ORDER BY l.n_days DESC, l.duration_ms
    ) = 1
)
SELECT
    e.* EXCLUDE (credited_lead),
    m.canonical_lead AS lead_artist_name,
    md5('track|' || lower(e.track_title) || '|' || lower(m.canonical_lead)) AS track_key,
    md5(concat_ws('|',
        coalesce(e.artist_credit, '<null>'),
        coalesce(e.album_type, '<null>'),
        coalesce(CAST(e.album_total_tracks AS VARCHAR), '<null>'),
        coalesce(CAST(e.duration_ms AS VARCHAR), '<null>'),
        coalesce(CAST(e.is_explicit AS VARCHAR), '<null>'),
        coalesce(e.album_cover_url, '<null>'),
        coalesce(e.release_date_raw, '<null>')
    )) AS version_attributes_hash
FROM with_lead AS e
LEFT JOIN lead_map AS m
    ON  m.title_lc = lower(e.track_title)
    AND m.credited_lead IS NOT DISTINCT FROM e.credited_lead;
