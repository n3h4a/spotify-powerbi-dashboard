-- Q5. How strongly does Christmas music take over, and how fast does it leave?
SELECT chart_date, holiday_track_share
FROM marts.mart_daily_chart
WHERE chart_date BETWEEN DATE '2023-11-10' AND DATE '2024-01-10'
ORDER BY chart_date
