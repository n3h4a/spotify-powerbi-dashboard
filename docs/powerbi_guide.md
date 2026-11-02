# Power BI Guide: Rebuilding the Dashboard on the Star Schema

The original dashboard (`dashboard/spotify_dashboard.pbix`) reads the raw CSV directly.
This guide moves it onto the warehouse's star schema, so every visual uses the cleaned,
tested data: correct artist counts, point-in-time attributes and chart-movement metrics.

## 1. Produce the tables

```bash
make all   # builds the warehouse and writes exports/*.parquet and exports/*.csv
```

## 2. Load the tables

Power BI Desktop → **Get data → Parquet** (or **Text/CSV**), and load from `exports/`:

| Table | Role |
|---|---|
| `fact_chart_entry` | Fact: one row per chart day × position |
| `dim_date` | Date dimension |
| `dim_track` | Track dimension |
| `dim_track_version` | Track attributes as of each chart day (SCD2) |
| `dim_artist` | Artist dimension |
| `bridge_track_artist` | Track ↔ artist (many-to-many) |
| `mart_track_performance` | One row per track: debut, peak, longevity |
| `mart_daily_chart` | One row per day: turnover, concentration, mix |
| `mart_artist_performance` | One row per artist: ranked chart share |

> Tip: put the export folder path in a Power Query **parameter**, so the report refreshes
> on any machine after `make all`.

## 3. Create the relationships

Model view. All relationships are single-direction, one-to-many, unless noted.

| From (one) | To (many) | Key |
|---|---|---|
| `dim_date` | `fact_chart_entry` | `date_key` |
| `dim_track` | `fact_chart_entry` | `track_key` |
| `dim_track_version` | `fact_chart_entry` | `track_version_key` |
| `dim_track` | `bridge_track_artist` | `track_key` |
| `dim_artist` | `bridge_track_artist` | `artist_key` |
| `dim_track` | `mart_track_performance` | `track_key` (one-to-one) |
| `dim_date` | `mart_daily_chart` | `date_key` |
| `dim_artist` | `mart_artist_performance` | `artist_key` (one-to-one) |

Then:

- **Mark `dim_date` as the date table** (Table tools → Mark as date table → `calendar_date`).
- **Do not** relate `dim_track_version` to `dim_track`. The fact table already links both,
  and a second path would make filtering ambiguous.
- Keep `bridge_track_artist` single-direction. The artist measures use `TREATAS` and
  `CROSSFILTER` to filter through it only when needed, which avoids the performance cost
  and ambiguity of bidirectional relationships.
- Hide every `*_key` column from report view.
- Sort `dim_date[month_name]` by `dim_date[month]`.

## 4. Add the measures

Create a blank table called `_Measures`, then add every measure from
[`powerbi/measures.dax`](../powerbi/measures.dax). Each measure has a comment explaining it.

## 5. Suggested new page: "Chart Dynamics"

Answers the questions in [insights.md](insights.md):

| Visual | Fields |
|---|---|
| KPI cards | `Median Chart Life (days)`, `Peaked on Debut %`, `Turnover Rate`, `Avg Artist HHI` |
| Line chart | `dim_date[calendar_date]` × `Avg Artist HHI` (album-drop takeovers) |
| Area chart | `dim_date[calendar_date]` × `Holiday Track Share`, filtered to Nov–Jan |
| Clustered bar | `mart_track_performance[peaked_on_debut]` × `Median Days in First 180` |
| Bar chart | `dim_artist[artist_name]` × `Artist Share of Chart`, Top N = 10 |
| Table | Track title, lead artist, debut position, peak, total chart days, days at #1 |
| Slicers | `dim_date[year_quarter]`, `mart_track_performance[is_holiday_track]` |

## 6. Check the numbers

These should match the warehouse exactly, because they're the same data:

| Measure (no filters) | Expected |
|---|---|
| `Chart Entries` | 27,800 |
| `Tracks Charting` | 807 |
| `Snapshots` | 556 |
| `Artist Weighted Chart Days` (total row) | 27,800 |
| `Artist Weighted Chart Days` for Taylor Swift | 1,871 |
