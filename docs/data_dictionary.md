# Data Dictionary

All tables live in the `gold` schema of `warehouse/spotify.duckdb`. They are also
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

**Grain:** one row per recording, identified by title + lead artist · **Rows:** 807

| Column | Type | Description |
|---|---|---|
| `track_key` | VARCHAR | PK. `md5('track|' + lower(title) + '|' + lower(lead_artist))`. |
| `track_title` | VARCHAR | Song title as first seen. |
| `lead_artist_name` | VARCHAR | First-credited artist. Stays the same when featured credits change. |
| `lead_artist_key` | VARCHAR | FK → `dim_artist`. |
| `first_chart_date` | DATE | First day the track appears in the dataset. |
| `last_chart_date` | DATE | Last day the track appears in the dataset. |

## `dim_track_version` (SCD Type 2)

**Grain:** one row per track per unbroken run of identical attributes · **Rows:** 1,079

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

**Grain:** one row per track per credited artist · **Rows:** 1,003

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
