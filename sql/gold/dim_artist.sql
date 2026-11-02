-- =============================================================================
-- GOLD | dim_artist
-- One row per individual artist, after collaboration credits are split.
-- Names are matched case-insensitively; the most frequent spelling is kept.
-- Grain: one row per artist.
-- =============================================================================
CREATE OR REPLACE TABLE gold.dim_artist AS
WITH spellings AS (
    SELECT p.artist_name, count(*) AS n_entries
    FROM silver.int_chart_entries AS e
    JOIN silver.artist_credit_parts AS p USING (artist_credit)
    GROUP BY p.artist_name
),
ranked AS (
    SELECT
        artist_name,
        row_number() OVER (
            PARTITION BY lower(artist_name) ORDER BY n_entries DESC, artist_name
        ) AS spelling_rank
    FROM spellings
)
SELECT
    md5('artist|' || lower(artist_name)) AS artist_key,
    artist_name
FROM ranked
WHERE spelling_rank = 1
ORDER BY artist_name;
