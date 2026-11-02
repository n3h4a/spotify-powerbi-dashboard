-- =============================================================================
-- MARTS | mart_artist_performance
-- One row per artist. Chart presence is measured two ways:
--   credited_chart_days  every chart day on which the artist is credited
--                        (a duet counts fully for both artists)
--   weighted_chart_days  each chart day split between credited artists via
--                        attribution_weight; summed over all artists this
--                        equals the number of chart entries exactly
-- Note: credits are attached at track level (the union of every credit seen),
-- so an artist dropped from a later credit is still counted on those days.
-- Grain: one row per artist.
-- =============================================================================
CREATE OR REPLACE TABLE marts.mart_artist_performance AS
WITH totals AS (
    SELECT count(*) AS n_entries FROM gold.fact_chart_entry
),
per_artist AS (
    SELECT
        b.artist_key,
        count(DISTINCT b.track_key)                                   AS n_tracks,
        count(DISTINCT b.track_key) FILTER (WHERE b.is_lead_artist)   AS n_tracks_as_lead,
        count(DISTINCT b.track_key) FILTER (WHERE b.n_credited_artists > 1) AS n_collaboration_tracks,
        count(*)                                                      AS credited_chart_days,
        sum(b.attribution_weight)                                     AS weighted_chart_days,
        count(*) FILTER (WHERE f.chart_position = 1)                  AS days_at_no1,
        count(*) FILTER (WHERE f.chart_position <= 10)                AS days_in_top10,
        min(f.chart_position)                                         AS best_position,
        min(f.chart_date)                                             AS first_chart_date,
        max(f.chart_date)                                             AS last_chart_date
    FROM gold.fact_chart_entry AS f
    JOIN gold.bridge_track_artist AS b USING (track_key)
    GROUP BY b.artist_key
)
SELECT
    CAST(rank() OVER (ORDER BY p.weighted_chart_days DESC) AS INTEGER) AS artist_rank,
    a.artist_key,
    a.artist_name,
    CAST(p.n_tracks AS INTEGER)                    AS n_tracks,
    CAST(p.n_tracks_as_lead AS INTEGER)            AS n_tracks_as_lead,
    CAST(p.n_collaboration_tracks AS INTEGER)      AS n_collaboration_tracks,
    CAST(p.credited_chart_days AS INTEGER)         AS credited_chart_days,
    round(p.weighted_chart_days, 2)                AS weighted_chart_days,
    round(p.weighted_chart_days / t.n_entries, 5)  AS share_of_chart,
    CAST(p.days_at_no1 AS INTEGER)                 AS days_at_no1,
    CAST(p.days_in_top10 AS INTEGER)               AS days_in_top10,
    p.best_position,
    p.first_chart_date,
    p.last_chart_date
FROM per_artist AS p
JOIN gold.dim_artist AS a USING (artist_key)
CROSS JOIN totals AS t
ORDER BY artist_rank, artist_name;
