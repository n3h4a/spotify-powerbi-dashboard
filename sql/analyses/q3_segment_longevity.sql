-- Q3. Which launch characteristics go with a longer chart life?
-- Median chart days within 180 days of debut, by segment, for the analysis cohort.
WITH cohort AS (
    SELECT * FROM marts.mart_track_performance
    WHERE NOT is_left_censored AND has_full_180_day_window
),
segmented AS (
    SELECT 'Launch shape' AS dimension,
           CASE WHEN peaked_on_debut THEN 'Peaked on debut day' ELSE 'Climbed after debut' END AS segment,
           chart_days_first_180 FROM cohort
    UNION ALL
    SELECT 'Debut position',
           CASE WHEN debut_position <= 10 THEN 'Debuted #1-10'
                WHEN debut_position <= 25 THEN 'Debuted #11-25'
                ELSE 'Debuted #26-50' END,
           chart_days_first_180 FROM cohort
    UNION ALL
    SELECT 'Release age at debut',
           CASE release_age_at_debut
                WHEN 'new release' THEN 'Released <=30 days earlier'
                WHEN 'recent'      THEN 'Released 1-12 months earlier'
                ELSE 'Released 1+ years earlier' END,
           chart_days_first_180 FROM cohort
    UNION ALL
    SELECT 'Credits',
           CASE WHEN is_collaboration THEN 'Collaboration' ELSE 'Solo' END,
           chart_days_first_180 FROM cohort
)
SELECT dimension, segment,
       count(*)                                                   AS n_tracks,
       median(chart_days_first_180)                               AS median_chart_days,
       round(avg(CASE WHEN chart_days_first_180 >= 30 THEN 1.0 ELSE 0.0 END), 3) AS share_30_plus_days
FROM segmented
GROUP BY ALL
ORDER BY dimension, median_chart_days DESC
