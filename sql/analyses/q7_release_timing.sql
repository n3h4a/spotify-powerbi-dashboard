-- Q7. How quickly do new tracks reach the chart after release?
-- Only day-precision release dates; catalogue tracks (released 1+ years earlier) excluded.
SELECT
    count(*)                                                           AS n_tracks,
    median(days_release_to_debut)                                      AS median_days,
    round(avg(CASE WHEN days_release_to_debut <= 7 THEN 1.0 ELSE 0.0 END), 3) AS share_within_week,
    round(avg(CASE WHEN days_release_to_debut <= 1 THEN 1.0 ELSE 0.0 END), 3) AS share_within_day
FROM marts.mart_track_performance
WHERE NOT is_left_censored
  AND days_release_to_debut IS NOT NULL
  AND release_age_at_debut <> 'catalog'
