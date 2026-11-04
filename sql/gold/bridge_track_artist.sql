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
all_artists AS (
    SELECT track_key, artist_name_lc, min(credit_order) AS best_credit_order
    FROM credits
    GROUP BY track_key, artist_name_lc
),
per_artist AS (
    -- "Various Artists" is a compilation placeholder, not a performer: it never takes
    -- credit from a real artist. It is kept only where it is a track's sole credit.
    SELECT a.*
    FROM all_artists AS a
    WHERE a.artist_name_lc <> 'various artists'
       OR NOT EXISTS (
           SELECT 1 FROM all_artists AS o
           WHERE o.track_key = a.track_key AND o.artist_name_lc <> 'various artists'
       )
),
track_lead AS (
    SELECT DISTINCT track_key, lower(lead_artist_name) AS lead_lc
    FROM silver.int_chart_entries
),
ranked AS (
    SELECT
        p.track_key,
        md5('artist|' || p.artist_name_lc) AS artist_key,
        -- The track's lead artist always comes first, then credit order.
        row_number() OVER (
            PARTITION BY p.track_key
            ORDER BY p.artist_name_lc = l.lead_lc DESC, p.best_credit_order, p.artist_name_lc
        ) AS credit_order,
        count(*) OVER (PARTITION BY p.track_key) AS n_credited_artists
    FROM per_artist AS p
    JOIN track_lead AS l USING (track_key)
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
