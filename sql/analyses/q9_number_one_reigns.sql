-- Q9. Which songs ruled the #1 spot?
-- Total days at #1 per song, and its longest unbroken run (gaps-and-islands).
WITH at_one AS (
    SELECT f.chart_date, f.track_key,
           row_number() OVER (ORDER BY f.chart_date)
         - row_number() OVER (PARTITION BY f.track_key ORDER BY f.chart_date) AS run_id
    FROM gold.fact_chart_entry AS f
    WHERE f.chart_position = 1
),
runs AS (
    SELECT track_key, run_id, count(*) AS run_days
    FROM at_one
    GROUP BY track_key, run_id
)
SELECT
    t.track_label,
    t.lead_artist_name,
    CAST(sum(r.run_days) AS INTEGER) AS days_at_no1,
    CAST(max(r.run_days) AS INTEGER) AS longest_run,
    CAST(count(*) AS INTEGER)        AS n_runs
FROM runs AS r
JOIN gold.dim_track AS t USING (track_key)
GROUP BY t.track_label, t.lead_artist_name
ORDER BY days_at_no1 DESC, longest_run DESC, t.track_label
