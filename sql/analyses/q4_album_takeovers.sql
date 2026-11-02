-- Q4. When does a single artist take over the chart?
-- Days with artist HHI >= 1,500 (well above the median of ~300), grouped into
-- events: consecutive snapshots dominated by the same artist (gaps-and-islands).
WITH artist_day AS (
    SELECT f.chart_date, a.artist_name, sum(b.attribution_weight) AS slots
    FROM gold.fact_chart_entry AS f
    JOIN gold.bridge_track_artist AS b USING (track_key)
    JOIN gold.dim_artist AS a USING (artist_key)
    GROUP BY ALL
),
dominant AS (
    SELECT d.chart_date, d.artist_hhi, x.artist_name, x.slots
    FROM marts.mart_daily_chart AS d
    JOIN artist_day AS x USING (chart_date)
    WHERE d.artist_hhi >= 1500
    QUALIFY row_number() OVER (PARTITION BY d.chart_date ORDER BY x.slots DESC) = 1
),
seq AS (
    SELECT chart_date, row_number() OVER (ORDER BY chart_date) AS snapshot_seq
    FROM marts.mart_daily_chart
),
islands AS (
    SELECT dominant.*,
           s.snapshot_seq - row_number() OVER (PARTITION BY artist_name ORDER BY chart_date) AS island
    FROM dominant JOIN seq AS s USING (chart_date)
)
SELECT artist_name,
       min(chart_date)            AS first_day,
       count(*)                   AS n_days,
       CAST(max(slots) AS INTEGER) AS peak_slots_of_50,
       max(artist_hhi)            AS peak_hhi
FROM islands
GROUP BY artist_name, island
ORDER BY first_day
