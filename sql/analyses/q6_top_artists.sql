-- Q6. Which artists own the most chart real estate?
-- Weighted chart days split collaborations fairly, so duets are not double counted.
SELECT artist_rank, artist_name, n_tracks, weighted_chart_days, share_of_chart, days_at_no1
FROM marts.mart_artist_performance
WHERE artist_rank <= 10
ORDER BY artist_rank
