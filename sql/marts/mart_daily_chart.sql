-- =============================================================================
-- MARTS | mart_daily_chart
-- One row per snapshot: chart composition and churn over time.
--   n_debuts + n_reentries  tracks new to today's chart. Because the chart
--                           always holds 50 tracks, this also equals the number
--                           of tracks that dropped out since the last snapshot.
--   turnover_rate           new tracks / 50
--   artist_hhi              Herfindahl-Hirschman index of artist concentration
--                           (0-10,000) over weighted chart slots. Higher means
--                           fewer artists dominate the chart.
-- The first snapshot has no previous chart, so its churn metrics are NULL.
-- Grain: one row per chart date.
-- =============================================================================
CREATE OR REPLACE TABLE marts.mart_daily_chart AS
WITH first_day AS (
    SELECT min(chart_date) AS d FROM gold.fact_chart_entry
),
composition AS (
    SELECT
        f.chart_date,
        f.date_key,
        count(*) FILTER (WHERE f.entry_status = 'debut')       AS n_debuts,
        count(*) FILTER (WHERE f.entry_status = 're-entry')    AS n_reentries,
        round(avg(f.popularity), 2)                            AS avg_popularity,
        round(avg(CASE WHEN v.is_explicit THEN 1.0 ELSE 0.0 END), 4)          AS explicit_share,
        round(avg(CASE WHEN v.album_type = 'single' THEN 1.0 ELSE 0.0 END), 4) AS single_share,
        round(avg(CASE WHEN tp.is_collaboration THEN 1.0 ELSE 0.0 END), 4)     AS collaboration_share,
        round(avg(CASE WHEN tp.is_holiday_track THEN 1.0 ELSE 0.0 END), 4)     AS holiday_track_share,
        round(avg(CASE WHEN tp.release_age_at_debut = 'catalog' THEN 1.0 ELSE 0.0 END), 4)
                                                               AS catalog_share,
        round(median(v.duration_ms) / 60000.0, 2)              AS median_duration_minutes
    FROM gold.fact_chart_entry AS f
    JOIN gold.dim_track_version AS v USING (track_version_key)
    JOIN marts.mart_track_performance AS tp ON tp.track_key = f.track_key
    GROUP BY f.chart_date, f.date_key
),
artist_slots AS (
    SELECT f.chart_date, b.artist_key, sum(b.attribution_weight) / 50.0 AS slot_share
    FROM gold.fact_chart_entry AS f
    JOIN gold.bridge_track_artist AS b USING (track_key)
    GROUP BY f.chart_date, b.artist_key
),
concentration AS (
    SELECT
        chart_date,
        count(*)                                 AS n_distinct_artists,
        round(sum(power(slot_share, 2)) * 10000) AS artist_hhi,
        round(max(slot_share), 4)                AS top_artist_share
    FROM artist_slots
    GROUP BY chart_date
)
SELECT
    c.date_key,
    c.chart_date,
    CASE WHEN c.chart_date = fd.d THEN NULL ELSE c.n_debuts END     AS n_debuts,
    CASE WHEN c.chart_date = fd.d THEN NULL ELSE c.n_reentries END  AS n_reentries,
    CASE WHEN c.chart_date = fd.d THEN NULL
         ELSE round((c.n_debuts + c.n_reentries) / 50.0, 4) END     AS turnover_rate,
    CAST(k.n_distinct_artists AS INTEGER)                           AS n_distinct_artists,
    CAST(k.artist_hhi AS INTEGER)                                   AS artist_hhi,
    k.top_artist_share,
    c.avg_popularity,
    c.explicit_share,
    c.single_share,
    c.collaboration_share,
    c.holiday_track_share,
    c.catalog_share,
    c.median_duration_minutes
FROM composition AS c
JOIN concentration AS k USING (chart_date)
CROSS JOIN first_day AS fd
ORDER BY c.chart_date;
