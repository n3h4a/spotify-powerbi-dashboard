-- =============================================================================
-- GOLD | dim_date
-- Contiguous calendar covering whole years of the chart period, as BI tools'
-- time-intelligence functions require. has_chart_snapshot marks the days that
-- actually have a chart, so gaps in the source are visible, not hidden.
-- Grain: one row per calendar day.
-- =============================================================================
CREATE OR REPLACE TABLE gold.dim_date AS
WITH bounds AS (
    SELECT
        make_date(year(min(chart_date)), 1, 1)   AS first_day,
        make_date(year(max(chart_date)), 12, 31) AS last_day
    FROM silver.stg_chart_entries
),
calendar AS (
    SELECT CAST(unnest(generate_series(
        CAST(first_day AS TIMESTAMP), CAST(last_day AS TIMESTAMP), INTERVAL 1 DAY
    )) AS DATE) AS calendar_date
    FROM bounds
),
snapshot_days AS (
    SELECT DISTINCT chart_date FROM silver.stg_chart_entries
)
SELECT
    CAST(strftime(c.calendar_date, '%Y%m%d') AS INTEGER) AS date_key,
    c.calendar_date,
    CAST(year(c.calendar_date) AS INTEGER)               AS year,
    CAST(quarter(c.calendar_date) AS INTEGER)            AS quarter,
    year(c.calendar_date) || '-Q' || quarter(c.calendar_date) AS year_quarter,
    CAST(month(c.calendar_date) AS INTEGER)              AS month,
    strftime(c.calendar_date, '%B')                      AS month_name,
    strftime(c.calendar_date, '%Y-%m')                   AS year_month,
    CAST(isoyear(c.calendar_date) AS INTEGER)            AS iso_year,
    CAST(week(c.calendar_date) AS INTEGER)               AS iso_week,
    CAST(isodow(c.calendar_date) AS INTEGER)             AS day_of_week,
    strftime(c.calendar_date, '%A')                      AS day_name,
    isodow(c.calendar_date) IN (6, 7)                    AS is_weekend,
    -- Christmas music floods the chart from late November; flag it for analysis.
    (month(c.calendar_date) = 12
        OR (month(c.calendar_date) = 11 AND day(c.calendar_date) >= 15)) AS is_holiday_season,
    s.chart_date IS NOT NULL                             AS has_chart_snapshot
FROM calendar AS c
LEFT JOIN snapshot_days AS s ON s.chart_date = c.calendar_date
ORDER BY c.calendar_date;
