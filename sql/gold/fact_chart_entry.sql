-- =============================================================================
-- GOLD | fact_chart_entry
-- The central fact table: one row per track per chart day, enriched with
-- chart-movement metrics computed with window functions.
--
-- Movement is measured between consecutive *snapshots*, not calendar days, so
-- the 4 days missing from the source do not register as a track dropping out.
--   previous_position    position on the previous snapshot (NULL if absent)
--   position_change      previous_position - chart_position (positive = climbed)
--   entry_status         'debut' | 're-entry' | 'returning'
--   chart_days_to_date   snapshots on chart so far, including today
--   current_streak_days  consecutive snapshots on chart ending today
--   peak_position_to_date best position reached so far
-- Grain: one row per chart date x chart position.
-- =============================================================================
CREATE OR REPLACE TABLE gold.fact_chart_entry AS
WITH snapshots AS (
    SELECT chart_date, row_number() OVER (ORDER BY chart_date) AS snapshot_seq
    FROM (SELECT DISTINCT chart_date FROM silver.int_chart_entries)
),
base AS (
    SELECT e.chart_date, e.chart_position, e.track_key, e.popularity, s.snapshot_seq
    FROM silver.int_chart_entries AS e
    JOIN snapshots AS s USING (chart_date)
),
windowed AS (
    SELECT
        *,
        lag(snapshot_seq)   OVER track_history AS prev_snapshot_seq,
        lag(chart_position) OVER track_history AS prev_chart_position,
        row_number()        OVER track_history AS chart_days_to_date,
        min(chart_position) OVER (track_history ROWS UNBOUNDED PRECEDING) AS peak_position_to_date,
        -- Gaps-and-islands: consecutive snapshots share the same island id.
        snapshot_seq - row_number() OVER track_history AS streak_island
    FROM base
    WINDOW track_history AS (PARTITION BY track_key ORDER BY snapshot_seq, chart_position)
)
SELECT
    CAST(strftime(w.chart_date, '%Y%m%d') AS INTEGER) AS date_key,
    w.chart_date,
    w.chart_position,
    w.track_key,
    v.track_version_key,
    w.popularity,
    CASE WHEN w.prev_snapshot_seq = w.snapshot_seq - 1 THEN w.prev_chart_position END
        AS previous_position,
    CASE WHEN w.prev_snapshot_seq = w.snapshot_seq - 1 THEN w.prev_chart_position - w.chart_position END
        AS position_change,
    CASE
        WHEN w.prev_snapshot_seq IS NULL                  THEN 'debut'
        WHEN w.prev_snapshot_seq < w.snapshot_seq - 1     THEN 're-entry'
        ELSE 'returning'
    END AS entry_status,
    CAST(w.chart_days_to_date AS INTEGER) AS chart_days_to_date,
    CAST(row_number() OVER (
        PARTITION BY w.track_key, w.streak_island ORDER BY w.snapshot_seq
    ) AS INTEGER) AS current_streak_days,
    w.peak_position_to_date
FROM windowed AS w
LEFT JOIN gold.dim_track_version AS v
    ON  v.track_key = w.track_key
    AND w.chart_date BETWEEN v.valid_from AND v.valid_to
ORDER BY w.chart_date, w.chart_position;
