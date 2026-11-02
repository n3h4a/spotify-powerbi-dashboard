"""Generate the Power BI Project (PBIP) from the warehouse: Power BI as code.

Writes powerbi/<PROJECT>.pbip with:
  * a TMDL semantic model: tables, typed columns, relationships, a marked date
    table and DAX measures, loading Parquet files through Power Query
  * a PBIR report: four pages of visuals bound to that model
  * a custom theme built from the project's validated chart palette
  * the data itself (powerbi/data/*.parquet), so the report refreshes anywhere

Open the .pbip in Power BI Desktop, click Refresh, then File > Save As .pbix if a
single file is needed. Everything is generated deterministically (stable IDs), so
reruns produce no diff unless the warehouse schema or this file changes.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

import duckdb

PROJECT = "Spotify Charts Analytics"
DATA_URL = "https://raw.githubusercontent.com/n3h4a/spotify-powerbi-dashboard/main/powerbi/data/"
_NS = uuid.UUID("6f0b6a4e-7c1d-4c55-9a43-3f1b2b0f5e21")

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
VERSIONS = {"report": "3.0.0", "page": "2.0.0", "visual": "2.2.0"}

MODEL_TABLES = {
    "fact_chart_entry": "gold.fact_chart_entry",
    "dim_date": "gold.dim_date",
    "dim_track": "gold.dim_track",
    "dim_track_version": "gold.dim_track_version",
    "dim_artist": "gold.dim_artist",
    "bridge_track_artist": "gold.bridge_track_artist",
    "mart_track_performance": "marts.mart_track_performance",
    "mart_daily_chart": "marts.mart_daily_chart",
    "mart_artist_performance": "marts.mart_artist_performance",
}

# (from = many side, to = one side). All single-direction filters.
RELATIONSHIPS = [
    ("fact_chart_entry", "date_key", "dim_date", "date_key"),
    ("fact_chart_entry", "track_key", "dim_track", "track_key"),
    ("fact_chart_entry", "track_version_key", "dim_track_version", "track_version_key"),
    ("bridge_track_artist", "track_key", "dim_track", "track_key"),
    ("bridge_track_artist", "artist_key", "dim_artist", "artist_key"),
    ("mart_track_performance", "track_key", "dim_track", "track_key"),
    ("mart_daily_chart", "date_key", "dim_date", "date_key"),
    ("mart_artist_performance", "artist_key", "dim_artist", "artist_key"),
]

PALETTE = ["#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#008300", "#6250D6", "#E34948"]


@dataclass(frozen=True)
class Measure:
    table: str
    name: str
    expression: str
    format: str
    folder: str
    description: str


MEASURES = [
    Measure(
        "fact_chart_entry",
        "Chart Entries",
        "COUNTROWS ( fact_chart_entry )",
        "#,0",
        "Chart",
        "Number of chart entries (track x day).",
    ),
    Measure(
        "fact_chart_entry",
        "Tracks Charting",
        "DISTINCTCOUNT ( fact_chart_entry[track_key] )",
        "#,0",
        "Chart",
        "Distinct tracks on the chart.",
    ),
    Measure(
        "fact_chart_entry",
        "Snapshots",
        "DISTINCTCOUNT ( fact_chart_entry[chart_date] )",
        "#,0",
        "Chart",
        "Number of daily chart snapshots.",
    ),
    Measure(
        "fact_chart_entry",
        "Avg Popularity",
        "AVERAGE ( fact_chart_entry[popularity] )",
        "0.0",
        "Chart",
        "Average Spotify popularity of charting tracks.",
    ),
    Measure(
        "fact_chart_entry",
        "Debuts",
        'CALCULATE ( [Chart Entries], fact_chart_entry[entry_status] = "debut" )',
        "#,0",
        "Movement",
        "Chart entries that are a track's first-ever appearance.",
    ),
    Measure(
        "fact_chart_entry",
        "Re-entries",
        'CALCULATE ( [Chart Entries], fact_chart_entry[entry_status] = "re-entry" )',
        "#,0",
        "Movement",
        "Chart entries where a track returns after dropping out.",
    ),
    Measure(
        "fact_chart_entry",
        "Turnover Rate",
        "VAR FirstSnapshot =\n"
        "    CALCULATE ( MIN ( fact_chart_entry[chart_date] ), ALL ( fact_chart_entry ) )\n"
        "RETURN\n"
        "    DIVIDE (\n"
        "        CALCULATE (\n"
        "            [Debuts] + [Re-entries],\n"
        "            fact_chart_entry[chart_date] <> FirstSnapshot\n"
        "        ),\n"
        "        CALCULATE ( [Chart Entries], fact_chart_entry[chart_date] <> FirstSnapshot )\n"
        "    )",
        "0.0%",
        "Movement",
        "Share of chart entries new versus the previous snapshot (first snapshot excluded).",
    ),
    Measure(
        "fact_chart_entry",
        "Days at #1",
        "CALCULATE ( [Chart Entries], fact_chart_entry[chart_position] = 1 )",
        "#,0",
        "Movement",
        "Chart entries at position 1.",
    ),
    Measure(
        "fact_chart_entry",
        "Best Position",
        "MIN ( fact_chart_entry[chart_position] )",
        "0",
        "Movement",
        "Best (lowest) chart position.",
    ),
    Measure(
        "fact_chart_entry",
        "Artist Weighted Chart Days",
        "SUMX (\n"
        "    bridge_track_artist,\n"
        "    bridge_track_artist[attribution_weight]\n"
        "        * CALCULATE (\n"
        "            [Chart Entries],\n"
        "            TREATAS ( { bridge_track_artist[track_key] }, dim_track[track_key] )\n"
        "        )\n"
        ")",
        "#,0.0",
        "Artists",
        "Chart entries split between credited artists; sums exactly to Chart Entries.",
    ),
    Measure(
        "fact_chart_entry",
        "Artist Credited Chart Days",
        "CALCULATE (\n"
        "    [Chart Entries],\n"
        "    CROSSFILTER ( bridge_track_artist[track_key], dim_track[track_key], BOTH )\n"
        ")",
        "#,0",
        "Artists",
        "Chart entries on which the artist is credited, counted in full.",
    ),
    Measure(
        "fact_chart_entry",
        "Artist Share of Chart",
        "DIVIDE (\n"
        "    [Artist Weighted Chart Days],\n"
        "    CALCULATE ( [Chart Entries], REMOVEFILTERS ( dim_artist ) )\n"
        ")",
        "0.0%",
        "Artists",
        "Artist's weighted share of all chart entries.",
    ),
    Measure(
        "fact_chart_entry",
        "Single Share",
        'DIVIDE ( CALCULATE ( [Chart Entries], dim_track_version[album_type] = "single" ), '
        "[Chart Entries] )",
        "0.0%",
        "Point in time",
        "Share of entries whose version on that day was a single (SCD2).",
    ),
    Measure(
        "fact_chart_entry",
        "Explicit Share",
        "DIVIDE ( CALCULATE ( [Chart Entries], dim_track_version[is_explicit] = TRUE () ), "
        "[Chart Entries] )",
        "0.0%",
        "Point in time",
        "Share of entries whose version on that day was explicit (SCD2).",
    ),
    Measure(
        "mart_track_performance",
        "Median Chart Life (days)",
        "MEDIAN ( mart_track_performance[total_chart_days] )",
        "0",
        "Track life",
        "Median total days on chart per track.",
    ),
    Measure(
        "mart_track_performance",
        "Peaked on Debut %",
        "DIVIDE (\n"
        "    CALCULATE (\n"
        "        COUNTROWS ( mart_track_performance ),\n"
        "        mart_track_performance[peaked_on_debut] = TRUE ()\n"
        "    ),\n"
        "    COUNTROWS ( mart_track_performance )\n"
        ")",
        "0%",
        "Track life",
        "Share of tracks whose best position was their debut position.",
    ),
    Measure(
        "mart_track_performance",
        "Median Days in First 180",
        "CALCULATE (\n"
        "    MEDIAN ( mart_track_performance[chart_days_first_180] ),\n"
        "    mart_track_performance[is_left_censored] = FALSE (),\n"
        "    mart_track_performance[has_full_180_day_window] = TRUE ()\n"
        ")",
        "0",
        "Track life",
        "Fair longevity comparison: chart days within 180 days of debut.",
    ),
    Measure(
        "mart_daily_chart",
        "Avg Artist HHI",
        "AVERAGE ( mart_daily_chart[artist_hhi] )",
        "#,0",
        "Chart health",
        "Artist concentration (Herfindahl-Hirschman index).",
    ),
    Measure(
        "mart_daily_chart",
        "Holiday Track Share",
        "AVERAGE ( mart_daily_chart[holiday_track_share] )",
        "0.0%",
        "Chart health",
        "Share of the chart held by holiday catalogue tracks.",
    ),
    Measure(
        "mart_daily_chart",
        "Collaboration Share",
        "AVERAGE ( mart_daily_chart[collaboration_share] )",
        "0.0%",
        "Chart health",
        "Share of the chart held by collaborations.",
    ),
]


# --------------------------------------------------------------------------- helpers


def _id(*parts: str) -> str:
    return str(uuid.uuid5(_NS, "|".join(parts)))


def _short_id(*parts: str) -> str:
    return uuid.uuid5(_NS, "|".join(parts)).hex[:20]


def _quote(name: str) -> str:
    """TMDL object name: quote unless it is a plain identifier."""
    return (
        name
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        else "'" + name.replace("'", "''") + "'"
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_json(path: Path, obj: dict) -> None:
    _write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def _column_format(name: str, duck_type: str) -> tuple[str, str]:
    """(TMDL dataType, formatString)."""
    if duck_type in ("INTEGER", "BIGINT"):
        return "int64", "0"
    if duck_type == "BOOLEAN":
        return "boolean", ""
    if duck_type == "DATE":
        return "dateTime", "yyyy-mm-dd"
    if duck_type == "DOUBLE":
        if name.endswith("_share") or name in ("share_of_chart", "turnover_rate"):
            return "double", "0.0%"
        return "double", "#,0.00"
    return "string", ""


# --------------------------------------------------------------------------- semantic model


def _table_tmdl(con: duckdb.DuckDBPyConnection, table: str, source: str) -> str:
    schema, name = source.split(".")
    cols = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
        [schema, name],
    ).fetchall()
    lines = [f"table {table}", f"\tlineageTag: {_id('table', table)}"]
    if table == "dim_date":
        lines.append("\tdataCategory: Time")  # marks the date table
    lines.append("")

    for m in (m for m in MEASURES if m.table == table):
        expr = m.expression.split("\n")
        if len(expr) == 1:
            lines.append(f"\tmeasure {_quote(m.name)} = {expr[0]}")
        else:
            lines.append(f"\tmeasure {_quote(m.name)} =")
            lines.extend(f"\t\t\t{e}" for e in expr)
        lines += [
            f"\t\tformatString: {m.format}",
            f"\t\tdisplayFolder: {m.folder}",
            f"\t\tlineageTag: {_id('measure', table, m.name)}",
            "",
        ]

    for col, duck_type in cols:
        data_type, fmt = _column_format(col, duck_type)
        lines.append(f"\tcolumn {_quote(col)}")
        lines.append(f"\t\tdataType: {data_type}")
        if col.endswith("_key"):
            lines.append("\t\tisHidden")
        if table == "dim_date" and col == "calendar_date":
            lines.append("\t\tisKey")
        if fmt:
            lines.append(f"\t\tformatString: {fmt}")
        lines.append(f"\t\tlineageTag: {_id('column', table, col)}")
        lines.append("\t\tsummarizeBy: none")
        lines.append(f"\t\tsourceColumn: {col}")
        if table == "dim_date" and col == "month_name":
            lines.append("\t\tsortByColumn: month")
        if table == "dim_date" and col == "day_name":
            lines.append("\t\tsortByColumn: day_of_week")
        if col == "album_cover_url":
            lines.append("\t\tdataCategory: ImageUrl")
        lines += ["", "\t\tannotation SummarizationSetBy = User", ""]

    lines += [
        f"\tpartition {table} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        f'\t\t\t\t    FileName = "{name}.parquet",',
        '\t\t\t\t    Content = if Text.StartsWith(DataLocation, "http")',
        "\t\t\t\t        then Web.Contents(DataLocation & FileName)",
        "\t\t\t\t        else File.Contents(DataLocation & FileName),",
        "\t\t\t\t    Source = Parquet.Document(Binary.Buffer(Content))",
        "\t\t\t\tin",
        "\t\t\t\t    Source",
        "",
    ]
    lines += ["\tannotation PBI_ResultType = Table", ""]
    return "\n".join(lines)


def _semantic_model(con: duckdb.DuckDBPyConnection, root: Path) -> None:
    sm = root / f"{PROJECT}.SemanticModel"
    _write_json(
        sm / "definition.pbism",
        {
            "$schema": f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json",
            "version": "4.2",
            "settings": {},
        },
    )
    _write_json(
        sm / ".platform",
        {
            "$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {"type": "SemanticModel", "displayName": PROJECT},
            "config": {"version": "2.0", "logicalId": _id("semanticModel")},
        },
    )
    d = sm / "definition"
    _write(d / "database.tmdl", "database\n\tcompatibilityLevel: 1567\n")
    query_order = json.dumps(["DataLocation", *MODEL_TABLES])
    _write(
        d / "model.tmdl",
        "\n".join(
            [
                "model Model",
                "\tculture: en-US",
                "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
                "\tdiscourageImplicitMeasures",
                "\tsourceQueryCulture: en-US",
                "\tdataAccessOptions",
                "\t\tlegacyRedirects",
                "\t\treturnErrorValuesAsNull",
                "",
                "annotation __PBI_TimeIntelligenceEnabled = 0",
                "",
                f"annotation PBI_QueryOrder = {query_order}",
                "",
            ]
        ),
    )
    _write(
        d / "expressions.tmdl",
        "\n".join(
            [
                f'expression DataLocation = "{DATA_URL}" meta [IsParameterQuery=true, Type="Text", '
                "IsParameterQueryRequired=true]",
                f"\tlineageTag: {_id('expression', 'DataLocation')}",
                "",
                "\tannotation PBI_ResultType = Text",
                "",
            ]
        ),
    )
    rel = []
    for frm, fcol, to, tcol in RELATIONSHIPS:
        rel += [
            f"relationship {_id('rel', frm, fcol, to, tcol)}",
            f"\tfromColumn: {frm}.{fcol}",
            f"\ttoColumn: {to}.{tcol}",
            "",
        ]
    _write(d / "relationships.tmdl", "\n".join(rel))
    for table, source in MODEL_TABLES.items():
        _write(d / "tables" / f"{table}.tmdl", _table_tmdl(con, table, source))


# --------------------------------------------------------------------------- report


def _lit(value) -> dict:
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        text = f"{value}D"
    else:
        text = "'" + str(value).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": text}}}


def _col(table: str, column: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": column}}


def _meas(name: str) -> dict:
    table = next(m.table for m in MEASURES if m.name == name)
    return {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def _proj(field: dict) -> dict:
    kind = "Measure" if "Measure" in field else "Column"
    entity = field[kind]["Expression"]["SourceRef"]["Entity"]
    prop = field[kind]["Property"]
    return {"field": field, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}


class _Page:
    def __init__(self, name: str, display: str):
        self.name, self.display, self.visuals = name, display, []

    def add(self, key: str, x, y, w, h, visual: dict, title: str | None = None) -> None:
        if title:
            visual["visualContainerObjects"] = {
                "title": [{"properties": {"show": _lit(True), "text": _lit(title)}}]
            }
        self.visuals.append(
            {
                "$schema": f"{SCHEMA}/item/report/definition/visualContainer/"
                f"{VERSIONS['visual']}/schema.json",
                "name": _short_id(self.name, key),
                "position": {
                    "x": x,
                    "y": y,
                    "z": len(self.visuals) * 1000,
                    "width": w,
                    "height": h,
                    "tabOrder": len(self.visuals) * 1000,
                },
                "visual": visual,
            }
        )

    def header(self, title: str, subtitle: str) -> None:
        self.add(
            "header",
            24,
            12,
            1232,
            64,
            {
                "visualType": "textbox",
                "objects": {
                    "general": [
                        {
                            "properties": {
                                "paragraphs": [
                                    {
                                        "textRuns": [
                                            {
                                                "value": title,
                                                "textStyle": {
                                                    "fontWeight": "bold",
                                                    "fontSize": "20pt",
                                                },
                                            }
                                        ]
                                    },
                                    {
                                        "textRuns": [
                                            {
                                                "value": subtitle,
                                                "textStyle": {
                                                    "fontSize": "11pt",
                                                    "color": "#52514E",
                                                },
                                            }
                                        ]
                                    },
                                ]
                            }
                        }
                    ]
                },
            },
        )

    def card(self, key: str, x, y, measure: str, w=232, h=104) -> None:
        self.add(
            key,
            x,
            y,
            w,
            h,
            {
                "visualType": "card",
                "query": {"queryState": {"Values": {"projections": [_proj(_meas(measure))]}}},
                "drillFilterOtherVisuals": True,
            },
        )

    def chart(
        self,
        key,
        x,
        y,
        w,
        h,
        visual_type: str,
        category: dict,
        value: str,
        title: str,
        sort_desc: bool = False,
    ) -> None:
        query = {
            "queryState": {
                "Category": {"projections": [_proj(category)]},
                "Y": {"projections": [_proj(_meas(value))]},
            }
        }
        if sort_desc:
            query["sortDefinition"] = {
                "sort": [{"field": _meas(value), "direction": "Descending"}],
                "isDefaultSort": False,
            }
        self.add(
            key,
            x,
            y,
            w,
            h,
            {"visualType": visual_type, "query": query, "drillFilterOtherVisuals": True},
            title,
        )

    def table(
        self, key, x, y, w, h, fields: list[dict], sort: dict, descending: bool, title: str
    ) -> None:
        self.add(
            key,
            x,
            y,
            w,
            h,
            {
                "visualType": "tableEx",
                "query": {
                    "queryState": {"Values": {"projections": [_proj(f) for f in fields]}},
                    "sortDefinition": {
                        "sort": [
                            {
                                "field": sort,
                                "direction": "Descending" if descending else "Ascending",
                            }
                        ],
                        "isDefaultSort": False,
                    },
                },
                "drillFilterOtherVisuals": True,
            },
            title,
        )

    def slicer(self, key, x, y, w, h, field: dict, title: str) -> None:
        self.add(
            key,
            x,
            y,
            w,
            h,
            {
                "visualType": "slicer",
                "query": {"queryState": {"Values": {"projections": [_proj(field)]}}},
                "drillFilterOtherVisuals": True,
            },
            title,
        )


def _pages() -> list[_Page]:
    overview = _Page("overview", "Overview")
    overview.header(
        "Spotify Global Top 50, May 2023 – Nov 2024",
        "556 daily snapshots · 27,800 chart entries · star schema built by the "
        "spotify-pipeline ELT",
    )
    for i, m in enumerate(
        [
            "Chart Entries",
            "Tracks Charting",
            "Median Chart Life (days)",
            "Peaked on Debut %",
            "Avg Artist HHI",
        ]
    ):
        overview.card(f"kpi{i}", 24 + i * 248, 88, m)
    overview.chart(
        "hhi",
        24,
        208,
        760,
        496,
        "lineChart",
        _col("dim_date", "calendar_date"),
        "Avg Artist HHI",
        "Artist concentration by day (album drops spike it)",
    )
    overview.chart(
        "artists",
        800,
        208,
        456,
        496,
        "clusteredBarChart",
        _col("dim_artist", "artist_name"),
        "Artist Share of Chart",
        "Share of chart by artist (collaborations split fairly)",
        sort_desc=True,
    )

    dynamics = _Page("dynamics", "Chart Dynamics")
    dynamics.header("Chart dynamics", "What makes a hit last, and how seasonal is the chart?")
    dynamics.slicer("quarter", 24, 88, 232, 104, _col("dim_date", "year_quarter"), "Quarter")
    for i, m in enumerate(
        ["Turnover Rate", "Holiday Track Share", "Collaboration Share", "Explicit Share"]
    ):
        dynamics.card(f"kpi{i}", 272 + i * 248, 88, m)
    dynamics.chart(
        "holiday",
        24,
        208,
        616,
        496,
        "areaChart",
        _col("dim_date", "calendar_date"),
        "Holiday Track Share",
        "The Christmas cliff: holiday share of the chart",
    )
    dynamics.chart(
        "shape",
        656,
        208,
        600,
        240,
        "clusteredColumnChart",
        _col("mart_track_performance", "peaked_on_debut"),
        "Median Days in First 180",
        "Median days on chart (first 180): peaked on debut?",
    )
    dynamics.chart(
        "age",
        656,
        464,
        600,
        240,
        "clusteredColumnChart",
        _col("mart_track_performance", "release_age_at_debut"),
        "Median Days in First 180",
        "Median days on chart (first 180) by release age",
    )

    tracks = _Page("tracks", "Tracks")
    tracks.header("Track explorer", "Every track's chart life: debut, peak and longevity")
    tracks.slicer(
        "artist",
        24,
        88,
        280,
        616,
        _col("mart_track_performance", "lead_artist_name"),
        "Lead artist",
    )
    t = "mart_track_performance"
    tracks.table(
        "table",
        320,
        88,
        936,
        616,
        [
            _col(t, "track_title"),
            _col(t, "lead_artist_name"),
            _col(t, "debut_date"),
            _col(t, "debut_position"),
            _col(t, "peak_position"),
            _col(t, "total_chart_days"),
            _col(t, "days_at_no1"),
            _col(t, "longest_streak_days"),
            _col(t, "release_age_at_debut"),
        ],
        _col(t, "total_chart_days"),
        True,
        "Tracks by total days on chart",
    )

    artists = _Page("artists", "Artists")
    artists.header(
        "Artist leaderboard",
        "Weighted chart days split collaborations between artists: no double counting",
    )
    a = "mart_artist_performance"
    artists.table(
        "table",
        24,
        88,
        1232,
        616,
        [
            _col(a, "artist_rank"),
            _col(a, "artist_name"),
            _col(a, "n_tracks"),
            _col(a, "weighted_chart_days"),
            _col(a, "share_of_chart"),
            _col(a, "days_at_no1"),
            _col(a, "days_in_top10"),
            _col(a, "best_position"),
        ],
        _col(a, "artist_rank"),
        False,
        "Artists ranked by share of the chart",
    )
    return [overview, dynamics, tracks, artists]


def _report(root: Path) -> None:
    rp = root / f"{PROJECT}.Report"
    _write_json(
        rp / "definition.pbir",
        {
            "$schema": f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json",
            "version": "4.0",
            "datasetReference": {"byPath": {"path": f"../{PROJECT}.SemanticModel"}},
        },
    )
    _write_json(
        rp / ".platform",
        {
            "$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {"type": "Report", "displayName": PROJECT},
            "config": {"version": "2.0", "logicalId": _id("report")},
        },
    )
    theme = "SpotifyCharts.json"
    _write_json(
        rp / "StaticResources" / "RegisteredResources" / theme,
        {
            "name": "Spotify Charts",
            "dataColors": PALETTE,
            "background": "#FCFCFB",
            "foreground": "#0B0B0B",
            "tableAccent": "#2A78D6",
        },
    )
    d = rp / "definition"
    _write_json(
        d / "version.json",
        {
            "$schema": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json",
            "version": "2.0.0",
        },
    )
    _write_json(
        d / "report.json",
        {
            "$schema": f"{SCHEMA}/item/report/definition/report/{VERSIONS['report']}/schema.json",
            "themeCollection": {
                "customTheme": {
                    "name": theme,
                    "reportVersionAtImport": {
                        "visual": VERSIONS["visual"],
                        "page": VERSIONS["page"],
                        "report": VERSIONS["report"],
                    },
                    "type": "RegisteredResources",
                }
            },
            "resourcePackages": [
                {
                    "name": "RegisteredResources",
                    "type": "RegisteredResources",
                    "items": [{"name": theme, "path": theme, "type": "CustomTheme"}],
                }
            ],
        },
    )
    pages = _pages()
    _write_json(
        d / "pages" / "pages.json",
        {
            "$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json",
            "pageOrder": [p.name for p in pages],
            "activePageName": pages[0].name,
        },
    )
    for p in pages:
        _write_json(
            d / "pages" / p.name / "page.json",
            {
                "$schema": f"{SCHEMA}/item/report/definition/page/{VERSIONS['page']}/schema.json",
                "name": p.name,
                "displayName": p.display,
                "displayOption": "FitToPage",
                "height": 720,
                "width": 1280,
            },
        )
        for v in p.visuals:
            _write_json(d / "pages" / p.name / "visuals" / v["name"] / "visual.json", v)


# --------------------------------------------------------------------------- entry points


def export_data(con: duckdb.DuckDBPyConnection, data_dir: Path) -> list[Path]:
    """Write every model table to Parquet for Power Query to load."""
    data_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for source in MODEL_TABLES.values():
        target = data_dir / f"{source.split('.')[1]}.parquet"
        path = target.as_posix().replace("'", "''")
        con.execute(f"COPY (SELECT * FROM {source}) TO '{path}' (FORMAT PARQUET)")
        out.append(target)
    return out


def measures_dax() -> str:
    """The measures as a plain .dax file, for reading and for manual models."""
    out = [
        "// Generated by `spotify-pipeline powerbi` from spotify_pipeline/powerbi.py.",
        "// The same measures are already defined in the PBIP semantic model.",
        "",
    ]
    folder = None
    for m in MEASURES:
        if m.folder != folder:
            folder = m.folder
            out += [f"// ---------------------------------------------------------------- {folder}"]
        out += [f"// {m.description}  [table: {m.table}]", f"{m.name} =", m.expression, ""]
    return "\n".join(out)


def generate(con: duckdb.DuckDBPyConnection, root: Path) -> None:
    """(Re)generate the PBIP project, its data files and powerbi/measures.dax."""
    for stale in (
        root / f"{PROJECT}.SemanticModel" / "definition",
        root / f"{PROJECT}.Report" / "definition",
    ):
        if stale.exists():
            shutil.rmtree(stale)
    export_data(con, root / "data")
    _semantic_model(con, root)
    _report(root)
    _write_json(
        root / f"{PROJECT}.pbip",
        {
            "$schema": f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json",
            "version": "1.0",
            "artifacts": [{"report": {"path": f"{PROJECT}.Report"}}],
            "settings": {"enableAutoRecovery": True},
        },
    )
    _write(root / "measures.dax", measures_dax())
