-- =============================================================================
-- GOLD | bridge_track_artist
-- Resolves the many-to-many relationship between tracks and artists. Every
-- artist ever credited on a track is included, in credit order.
--
-- attribution_weight (1 / number of artists) lets analysts split a track's
-- metrics fairly across collaborators: summing weighted chart-days across all
-- artists equals the true total, with no double counting.
-- Grain: one row per track per credited artist.
-- =============================================================================
CREATE OR REPLACE TABLE gold.bridge_track_artist AS
WITH credits AS (
    SELECT DISTINCT e.track_key, lower(p.artist_name) AS artist_name_lc, p.credit_order
    FROM silver.int_chart_entries AS e
    JOIN silver.artist_credit_parts AS p USING (artist_credit)
),
per_artist AS (
    SELECT track_key, artist_name_lc, min(credit_order) AS best_credit_order
    FROM credits
    GROUP BY ALL
),
ranked AS (
    SELECT
        track_key,
        md5('artist|' || artist_name_lc) AS artist_key,
        row_number() OVER (
            PARTITION BY track_key ORDER BY best_credit_order, artist_name_lc
        ) AS credit_order,
        count(*) OVER (PARTITION BY track_key) AS n_credited_artists
    FROM per_artist
)
SELECT
    track_key,
    artist_key,
    CAST(credit_order AS INTEGER)                         AS credit_order,
    credit_order = 1                                      AS is_lead_artist,
    CASE WHEN credit_order = 1 THEN 'lead' ELSE 'featured' END AS artist_role,
    CAST(n_credited_artists AS INTEGER)                   AS n_credited_artists,
    CAST(1.0 / n_credited_artists AS DOUBLE)              AS attribution_weight
FROM ranked
ORDER BY track_key, credit_order;
