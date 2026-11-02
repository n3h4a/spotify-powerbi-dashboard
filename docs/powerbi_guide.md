# Power BI Guide

The dashboard is a **Power BI Project (`.pbip`)**: Microsoft's text-based Power BI
format, where the semantic model is TMDL and the report is PBIR JSON. It is generated
from the warehouse by `spotify-pipeline powerbi`, so the model, the measures and the
data always match the tested pipeline. Every change shows up as a readable diff in git.

```text
powerbi/
├── Spotify Charts Analytics.pbip              ← open this in Power BI Desktop
├── Spotify Charts Analytics.SemanticModel/    ← TMDL: tables, relationships, measures
├── Spotify Charts Analytics.Report/           ← PBIR: 4 pages of visuals + theme
├── data/*.parquet                             ← the model's data (~750 KB)
└── measures.dax                               ← all DAX measures, for reading
```

## 1. Open it

1. Install or update **Power BI Desktop**. Any version from late 2025 onwards reads this
   project format.
2. Clone the repo, or download it as a ZIP, and open
   **`powerbi/Spotify Charts Analytics.pbip`**.
3. Click **Refresh** (Home ribbon). By default the data loads straight from this GitHub
   repository, so no local setup is needed. If asked about privacy levels, choose
   *Public*.
4. To get a single shareable file, use **File → Save As → Power BI file (.pbix)**.

### Loading the data from your own disk instead

*Transform data → Edit parameters → `DataLocation`*: set it to a local folder ending in
a slash, e.g. `C:\code\spotify-powerbi-dashboard\powerbi\data\`. Every table switches
from `Web.Contents` to `File.Contents` automatically.

## 2. What's inside

### Model

Nine tables in a star schema: `fact_chart_entry` at the centre; `dim_date` (marked as
the date table), `dim_track`, `dim_track_version` (SCD2) and `dim_artist` around it;
`bridge_track_artist` for collaborations; and the three marts.

| From (many) | To (one) | Key |
|---|---|---|
| `fact_chart_entry` | `dim_date` | `date_key` |
| `fact_chart_entry` | `dim_track` | `track_key` |
| `fact_chart_entry` | `dim_track_version` | `track_version_key` |
| `bridge_track_artist` | `dim_track` | `track_key` |
| `bridge_track_artist` | `dim_artist` | `artist_key` |
| `mart_track_performance` | `dim_track` | `track_key` |
| `mart_daily_chart` | `dim_date` | `date_key` |
| `mart_artist_performance` | `dim_artist` | `artist_key` |

Design choices:

- **All relationships are single-direction.** The artist measures filter through the
  bridge with `TREATAS` and `CROSSFILTER` only where needed, which avoids the ambiguity
  and performance cost of bidirectional relationships.
- **`dim_track_version` is deliberately not related to `dim_track`.** The fact table
  links to both, and a second path would make filtering ambiguous.
- **Implicit measures are discouraged.** Numeric columns don't auto-sum. Every number in
  a visual comes from an explicit, documented measure.
- **Auto date/time is off.** `dim_date` is the single date table.
- Keys are hidden, `month_name` sorts by `month`, `day_name` sorts by `day_of_week`, and
  album covers are tagged as image URLs.

### Measures

20 DAX measures in display folders (Chart, Movement, Artists, Point in time, Track life,
Chart health). All are listed with descriptions in
[`powerbi/measures.dax`](../powerbi/measures.dax). Highlights:

- **`Artist Weighted Chart Days`** splits each chart entry between collaborators, so
  totals never double count.
- **`Single Share` / `Explicit Share`** use the track *version valid on each day* (SCD2),
  not today's attributes.
- **`Median Days in First 180`** applies the same censoring rules as the statistical
  analysis.

### Report pages

| Page | Contents |
|---|---|
| **Overview** | KPI cards (entries, tracks, median chart life, peaked-on-debut %, artist HHI) · daily artist concentration · share of chart by artist |
| **Chart Dynamics** | Quarter slicer · turnover, holiday, collaboration and explicit shares · the Christmas cliff · longevity by launch shape and by release age |
| **Tracks** | Lead-artist slicer · every track's debut, peak, chart days, days at #1 and longest streak |
| **Artists** | Leaderboard by weighted share of chart |

The theme uses the same colour-blind-safe palette as the charts in `docs/figures/`.

## 3. Check the numbers

These must match the warehouse exactly:

| Measure (no filters) | Expected |
|---|---|
| `Chart Entries` | 27,800 |
| `Tracks Charting` | 807 |
| `Snapshots` | 556 |
| `Artist Weighted Chart Days` (total) | 27,800 |
| `Artist Weighted Chart Days` for Taylor Swift | 1,871 |
| `Median Chart Life (days)` | 7 (all 807 tracks); 6 with `is_left_censored` = false |

## 4. Editing the report

You can edit freely in Power BI Desktop. Save, and the `.pbip` folders update as
readable text diffs. Note that `make powerbi` **regenerates** the project from code and
overwrites manual edits to generated files. So either make lasting changes in
[`src/spotify_pipeline/powerbi.py`](../src/spotify_pipeline/powerbi.py), or stop
regenerating once you start customising by hand.

## 5. How it's verified

Power BI Desktop can't run in CI (it's Windows-only), so the project is checked
statically instead:

- Every PBIR JSON file was validated against **Microsoft's published Fabric JSON
  schemas** (report 3.0.0, page 2.0.0, visual container 2.2.0).
- [`tests/test_powerbi.py`](../tests/test_powerbi.py) checks that every field used by a
  visual exists in the model, every DAX reference resolves, every relationship column
  exists, TMDL indentation is valid, no Power Query step shadows a library function,
  the committed data equals the warehouse, and the committed project matches a fresh
  regeneration.

If Power BI Desktop reports a problem when opening the project, the error message names
the exact file and line. Open an issue with that message.

The original hand-built dashboard is kept at
[`dashboard/spotify_dashboard.pbix`](../dashboard/spotify_dashboard.pbix).
