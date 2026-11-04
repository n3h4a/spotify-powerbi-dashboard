# Data Dictionary

The star schema lives in the `gold` schema of `warehouse/spotify.duckdb`, and the
analytics marts in the `marts` schema. They are also
exported to `exports/<table>.parquet` and `exports/<table>.csv` by `make export`.
Design rationale is in [data_model.md](data_model.md).

**Key types.** Every `*_key` column except `date_key` is a deterministic MD5 hash
(`VARCHAR(32)`). `date_key` is an integer in `YYYYMMDD` form.

---

## `fact_chart_entry`

**Grain:** one row per chart date × chart position · **Rows:** 27,800

| Column | Type | Description |
|---|---|---|
| `date_key` | INTEGER | FK → `dim_date`. Chart date as `YYYYMMDD`. |
| `chart_date` | DATE | Chart snapshot date (kept alongside `date_key` for convenience). |
| `chart_position` | INTEGER | Position in the Global Top 50 (1 = top). |
| `track_key` | VARCHAR | FK → `dim_track`. |
| `track_version_key` | VARCHAR | FK → `dim_track_version`: the version valid on `chart_date`. |
| `popularity` | INTEGER | Spotify popularity score (0–100) on that day. |
| `previous_position` | INTEGER | Position on the previous snapshot; `NULL` if the track was not on it. |
| `position_change` | INTEGER | `previous_position − chart_position`. Positive = climbed; `NULL` if not on the previous snapshot. |
| `entry_status` | VARCHAR | `debut` (first ever appearance), `re-entry` (back after dropping out), `returning` (also on the previous snapshot). |
| `chart_days_to_date` | INTEGER | Number of snapshots the track has appeared on so far, including this one. |
| `current_streak_days` | INTEGER | Consecutive snapshots on the chart, ending with this one. |
| `peak_position_to_date` | INTEGER | Best (lowest) position the track has reached so far. |

## `dim_track`

**Grain:** one row per recording, identified by title + lead artist · **Rows:** 797

| Column | Type | Description |
|---|---|---|
| `track_key` | VARCHAR | PK. `md5('track|' + lower(title) + '|' + lower(lead_artist))`. |
| `track_title` | VARCHAR | Song title as first seen. |
| `lead_artist_name` | VARCHAR | First-credited artist. Stays the same when featured credits change. |
| `track_label` | VARCHAR | Unique display name: the title, plus `(lead artist)` only when several songs share that title. |
| `chart_rank` | INTEGER | 1 = most days on the chart. Orders song lists by success. |
| `lead_artist_key` | VARCHAR | FK → `dim_artist`. |
| `first_chart_date` | DATE | First day the track appears in the dataset. |
| `last_chart_date` | DATE | Last day the track appears in the dataset. |

## `dim_track_version` (SCD Type 2)

**Grain:** one row per track per unbroken run of identical attributes · **Rows:** 1,089

| Column | Type | Description |
|---|---|---|
| `track_version_key` | VARCHAR | PK. |
| `track_key` | VARCHAR | FK → `dim_track`. |
| `version_number` | INTEGER | 1, 2, 3, … in chronological order. |
| `artist_credit` | VARCHAR | Full artist credit as shown on the chart, e.g. `Drake & SZA`. |
| `album_type` | VARCHAR | `single`, `album` or `compilation`. |
| `album_total_tracks` | INTEGER | Number of tracks on the release. |
| `duration_ms` | INTEGER | Track length in milliseconds. |
| `duration_minutes` | DOUBLE | Track length in minutes (2 dp). |
| `is_explicit` | BOOLEAN | Explicit-content flag. |
| `release_date` | DATE | Release date, normalised to the first day of its period. |
| `release_date_precision` | VARCHAR | `day`, `month` or `year`: how precise the source date was. |
| `album_cover_url` | VARCHAR | Cover art image URL. |
| `valid_from` | DATE | First chart day this version applies to. |
| `valid_to` | DATE | Last day this version applies to; `9999-12-31` for the current version. |
| `is_current` | BOOLEAN | `true` for the latest version of each track. |

## `dim_artist`

**Grain:** one row per individual artist, after splitting collaboration credits · **Rows:** 346

| Column | Type | Description |
|---|---|---|
| `artist_key` | VARCHAR | PK. `md5('artist|' + lower(name))`. |
| `artist_name` | VARCHAR | Most frequent spelling across the source (case variants are merged). |

## `bridge_track_artist`

**Grain:** one row per track per credited artist · **Rows:** 986

| Column | Type | Description |
|---|---|---|
| `track_key` | VARCHAR | FK → `dim_track`. |
| `artist_key` | VARCHAR | FK → `dim_artist`. |
| `credit_order` | INTEGER | Position in the credit (1 = lead). |
| `is_lead_artist` | BOOLEAN | `credit_order = 1`. |
| `artist_role` | VARCHAR | `lead` or `featured`. |
| `n_credited_artists` | INTEGER | Number of artists ever credited on the track. |
| `attribution_weight` | DOUBLE | `1 / n_credited_artists`. Multiply a metric by this to share it between collaborators without double counting. |

## `dim_date`

**Grain:** one row per calendar day, covering whole years of the chart period · **Rows:** 731

| Column | Type | Description |
|---|---|---|
| `date_key` | INTEGER | PK, `YYYYMMDD`. |
| `calendar_date` | DATE | The date. |
| `year`, `quarter`, `month` | INTEGER | Calendar parts. |
| `year_quarter` | VARCHAR | e.g. `2024-Q3`. |
| `month_name` | VARCHAR | e.g. `September`. |
| `year_month` | VARCHAR | e.g. `2024-09`. |
| `iso_year`, `iso_week` | INTEGER | ISO-8601 week numbering. |
| `day_of_week` | INTEGER | ISO day of week (1 = Monday … 7 = Sunday). |
| `day_name` | VARCHAR | e.g. `Monday`. |
| `is_weekend` | BOOLEAN | Saturday or Sunday. |
| `is_holiday_season` | BOOLEAN | 15 Nov – 31 Dec, when Christmas music enters the chart. |
| `has_chart_snapshot` | BOOLEAN | `false` for days with no chart in the source, including the 4 missing days. |

---

# Marts (`marts` schema)

Business-level tables built on the star schema. Each one reconciles exactly to
`fact_chart_entry`, and the quality suite enforces it.

## `mart_track_performance`

**Grain:** one row per track · **Rows:** 797

| Column | Description |
|---|---|
| `track_key`, `track_title`, `lead_artist_name`, `lead_artist_key` | Track identity (see `dim_track`). |
| `n_credited_artists`, `is_collaboration` | Number of artists ever credited; `true` if more than one. |
| `debut_date`, `debut_position` | First chart day and position. Not the true debut if `is_left_censored`. |
| `last_chart_date` | Last chart day in the dataset. |
| `peak_position`, `first_peak_date` | Best position and the first day it was reached. |
| `chart_days_debut_to_peak`, `peaked_on_debut` | Chart days from debut to peak; `true` if the peak was the debut day. |
| `total_chart_days`, `n_reentries`, `longest_streak_days` | Chart life: total days, number of comebacks, longest unbroken run. |
| `days_at_no1`, `days_in_top10` | Days at #1 and in the top 10. |
| `avg_popularity`, `max_popularity` | Spotify popularity while charting. |
| `debut_album_type`, `debut_is_explicit`, `debut_duration_ms` | Attributes of the version that debuted. |
| `release_date`, `release_date_precision` | Release date of the debut version. |
| `days_release_to_debut` | Days from release to debut (day-precision dates only). |
| `release_age_at_debut` | `new release` (≤ 30 days), `recent` (31–365 days) or `catalog` (older). |
| `is_holiday_track` | ≥ 90% of chart days fall 15 Nov–31 Dec, and released more than a year before debut. |
| `is_left_censored` | Already charting on the first snapshot, so the real debut is unknown. |
| `is_right_censored` | Still charting on the last snapshot, so chart life is a lower bound. |
| `has_full_180_day_window` | Debuted at least 180 days before the last snapshot. |
| `chart_days_first_180` | Chart days within 180 days of debut: the fair longevity metric. |
| `chart_life_bucket`, `chart_life_bucket_order` | Total chart life grouped as `1 day`, `2-7 days`, …, `180+ days` (with a sort key). |
| `album_cover_url` | Cover art of the track's current version. |

## `mart_artist_performance`

**Grain:** one row per artist · **Rows:** 346

| Column | Description |
|---|---|
| `artist_rank` | Rank by `weighted_chart_days`. |
| `artist_key`, `artist_name` | Artist identity. |
| `n_tracks`, `n_tracks_as_lead`, `n_collaboration_tracks` | Track counts. |
| `credited_chart_days` | Chart days on which the artist is credited, counted in full. |
| `weighted_chart_days` | Chart days split between collaborators; sums to 27,800 across all artists. |
| `share_of_chart` | `weighted_chart_days` / total chart entries. |
| `days_at_no1`, `days_in_top10`, `best_position` | Peak performance. |
| `first_chart_date`, `last_chart_date` | Active period. |

## `mart_daily_chart`

**Grain:** one row per snapshot · **Rows:** 556

| Column | Description |
|---|---|
| `date_key`, `chart_date` | Snapshot date. |
| `n_debuts`, `n_reentries` | Tracks new to today's chart (`NULL` on the first snapshot). |
| `turnover_rate` | (`n_debuts` + `n_reentries`) / 50. |
| `n_distinct_artists` | Distinct credited artists on the chart. |
| `artist_hhi` | Herfindahl-Hirschman index of artist concentration (0–10,000). |
| `top_artist_share` | Share of slots held by the most-present artist. |
| `avg_popularity` | Mean popularity of the 50 entries. |
| `explicit_share`, `single_share`, `collaboration_share`, `holiday_track_share`, `catalog_share` | Composition of the chart, using point-in-time attributes. |
| `median_duration_minutes` | Median track length on the chart. |

---

# ML features (`ml` schema)

## `ml.track_features`

**Grain:** one row per track with a known debut · **Rows:** 747 ·
Full method in [model_report.md](model_report.md)

| Column group | Columns | Available at |
|---|---|---|
| Launch-day features | `debut_position`, `debut_popularity`, `release_age_days`, `is_new_release`, `is_collaboration`, `n_credited_artists`, `debut_is_explicit`, `is_single`, `duration_minutes`, `debut_in_holiday_season` | Debut day |
| Artist history | `artist_prior_tracks`, `artist_prior_chart_days` (lead artist's chart presence strictly before the debut date) | Debut day |
| Week-one features | `w1_chart_days`, `w1_best_position`, `w1_max_popularity`, `w1_on_chart_day7`, `w1_day7_position` (51 = off chart), `w1_position_change`, `w1_position_slope`, `w1_climbed` | Debut + 6 days |
| Availability | `has_full_week_one`, `has_label` | Data cut-off |
| Label | `lasts_30_days`: 30+ chart days within 180 days of debut (`NULL` if the window isn't fully observed) | Debut + 180 days |
| Survival | `chart_life_days` (time), `chart_life_ended` (event: absent for the final 14+ days) | Data cut-off |

---

## Example queries

**Longest unbroken chart runs**

```sql
SELECT t.track_title, t.lead_artist_name, max(f.current_streak_days) AS longest_streak
FROM gold.fact_chart_entry f
JOIN gold.dim_track t USING (track_key)
GROUP BY ALL
ORDER BY longest_streak DESC
LIMIT 10;
```

**Artist chart-days, shared fairly between collaborators**

```sql
SELECT a.artist_name, round(sum(b.attribution_weight), 1) AS weighted_chart_days
FROM gold.fact_chart_entry f
JOIN gold.bridge_track_artist b USING (track_key)
JOIN gold.dim_artist a USING (artist_key)
GROUP BY ALL
ORDER BY weighted_chart_days DESC
LIMIT 10;
```

**Album type as it was on each chart day (point-in-time, via SCD2)**

```sql
SELECT d.year_quarter, v.album_type, count(*) AS chart_entries
FROM gold.fact_chart_entry f
JOIN gold.dim_track_version v USING (track_version_key)
JOIN gold.dim_date d USING (date_key)
GROUP BY ALL
ORDER BY d.year_quarter, v.album_type;
```
