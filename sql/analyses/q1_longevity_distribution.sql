-- Q1. How long do tracks survive on the Global Top 50?
-- Total chart days per track, bucketed. Left-censored tracks are excluded
-- because their real chart life started before the dataset begins.
WITH tracks AS (
    SELECT total_chart_days FROM marts.mart_track_performance WHERE NOT is_left_censored
)
SELECT
    CASE
        WHEN total_chart_days = 1    THEN '1 day'
        WHEN total_chart_days <= 7   THEN '2-7 days'
        WHEN total_chart_days <= 30  THEN '8-30 days'
        WHEN total_chart_days <= 90  THEN '31-90 days'
        WHEN total_chart_days <= 180 THEN '91-180 days'
        ELSE '180+ days'
    END                                      AS longevity_bucket,
    min(total_chart_days)                    AS sort_key,
    count(*)                                 AS n_tracks,
    round(count(*) / sum(count(*)) OVER (), 4) AS share_of_tracks
FROM tracks
GROUP BY ALL
ORDER BY sort_key
