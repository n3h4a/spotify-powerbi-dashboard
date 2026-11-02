-- Analysis cohort: tracks whose full first 180 days on the chart are observable.
--   * debuted after the first snapshot (real debut date and position are known)
--   * debuted at least 180 days before the last snapshot (no right-censoring)
-- Comparing tracks on chart_days_first_180 then measures every track over the
-- same window, so tracks that debuted late in the dataset are not penalised.
SELECT *
FROM marts.mart_track_performance
WHERE NOT is_left_censored
  AND has_full_180_day_window
