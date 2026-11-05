-- Q8. When do new songs come out, and when do they reach the chart?
-- Weekday of release (day-precision new releases) next to weekday of chart debut.
WITH new_songs AS (
    SELECT release_date, debut_date
    FROM marts.mart_track_performance
    WHERE NOT is_left_censored
      AND release_age_at_debut = 'new release'
      AND release_date_precision = 'day'
),
days AS (
    SELECT * FROM (VALUES (1, 'Monday'), (2, 'Tuesday'), (3, 'Wednesday'), (4, 'Thursday'),
                          (5, 'Friday'), (6, 'Saturday'), (7, 'Sunday')) AS d(day_of_week, day_name)
)
SELECT
    d.day_of_week,
    d.day_name,
    round(avg(CASE WHEN isodow(s.release_date) = d.day_of_week THEN 1.0 ELSE 0.0 END), 4) AS share_released,
    round(avg(CASE WHEN isodow(s.debut_date) = d.day_of_week THEN 1.0 ELSE 0.0 END), 4)   AS share_debuted
FROM days AS d
CROSS JOIN new_songs AS s
GROUP BY d.day_of_week, d.day_name
ORDER BY d.day_of_week
