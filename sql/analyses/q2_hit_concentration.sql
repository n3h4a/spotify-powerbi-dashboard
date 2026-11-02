-- Q2. How concentrated is chart presence among tracks?
-- Share of all chart slots held by each decile of tracks (decile 1 = longest-charting 10%).
WITH ranked AS (
    SELECT total_chart_days, ntile(10) OVER (ORDER BY total_chart_days DESC) AS decile
    FROM marts.mart_track_performance
)
SELECT decile, count(*) AS n_tracks,
       round(sum(total_chart_days) / (SELECT sum(total_chart_days) FROM ranked), 4) AS share_of_slots
FROM ranked
GROUP BY decile
ORDER BY decile
