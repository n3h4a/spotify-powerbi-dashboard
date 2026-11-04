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

from spotify_pipeline.config import PROJECT_ROOT

PROJECT = "Spotify Charts Analytics"
DATA_URL = "https://raw.githubusercontent.com/n3h4a/spotify-powerbi-dashboard/main/powerbi/data/"
_NS = uuid.UUID("6f0b6a4e-7c1d-4c55-9a43-3f1b2b0f5e21")

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"

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

# (from = many side, to = one side).
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

# Relationships that filter in both directions:
#  * bridge -> dim_track lets an artist selection flow artist -> bridge -> track ->
#    facts, so clicking an artist filters every visual (the standard bridge pattern)
#  * the track mart is one row per track (1:1 with dim_track), so selecting one of its
#    fields (e.g. a chart-life bucket) filters the whole report
# Everything else stays single-direction; a test checks no filter path is ambiguous.
BIDIRECTIONAL = {
    ("bridge_track_artist", "track_key", "dim_track", "track_key"),
    ("mart_track_performance", "track_key", "dim_track", "track_key"),
}
# One-to-one relationships (both sides unique): the track mart extends dim_track.
ONE_TO_ONE = {("mart_track_performance", "track_key", "dim_track", "track_key")}


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
        (
            "DIVIDE (\n"
            "    [Artist Weighted Chart Days],\n"
            "    CALCULATE (\n"
            "        [Chart Entries],\n"
            "        REMOVEFILTERS ( dim_artist ),\n"
            "        REMOVEFILTERS ( bridge_track_artist ),\n"
            "        REMOVEFILTERS ( dim_track ),\n"
            "        REMOVEFILTERS ( dim_track_version ),\n"
            "        REMOVEFILTERS ( mart_track_performance )\n"
            "    )\n"
            ")"
        ),
        "0.0%",
        "Artists",
        (
            "Artist's weighted chart days as a share of ALL chart entries in the selected period "
            "(only date filters are kept in the denominator)."
        ),
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
    # ---------------------------------------------------- measures used by the dashboard design
    Measure(
        "fact_chart_entry",
        "Artists Charting",
        (
            "CALCULATE (\n"
            "    DISTINCTCOUNT ( bridge_track_artist[artist_key] ),\n"
            "    CROSSFILTER ( fact_chart_entry[track_key], dim_track[track_key], BOTH ),\n"
            '    dim_artist[artist_name] <> "Various Artists"\n'
            ")"
        ),
        "#,0",
        "Artists",
        (
            "Distinct individual artists on the chart (collaborations split; the 'Various Artists' "
            "compilation placeholder is not an artist)."
        ),
    ),
    Measure(
        "fact_chart_entry",
        "Popularity Max",
        "100",
        "0",
        "Chart",
        "Top of the popularity scale (gauge maximum).",
    ),
    Measure(
        "fact_chart_entry",
        "Popularity Remainder",
        "[Popularity Max] - [Avg Popularity]",
        "0.0",
        "Chart",
        "Distance from average popularity to 100 (progress bars).",
    ),
    Measure(
        "fact_chart_entry",
        "Artist Tracks",
        "CALCULATE (\n"
        "    DISTINCTCOUNT ( bridge_track_artist[track_key] ),\n"
        "    CROSSFILTER ( fact_chart_entry[track_key], dim_track[track_key], BOTH )\n"
        ")",
        "#,0",
        "Artists",
        "Distinct tracks credited to the artist(s) in context.",
    ),
    Measure(
        "fact_chart_entry",
        "Artist Avg Popularity",
        "CALCULATE (\n"
        "    [Avg Popularity],\n"
        "    CROSSFILTER ( bridge_track_artist[track_key], dim_track[track_key], BOTH )\n"
        ")",
        "0.0",
        "Artists",
        "Average popularity of the artist's chart entries.",
    ),
    Measure(
        "fact_chart_entry",
        "Artist Days at #1",
        "COALESCE (\n"
        "    CALCULATE (\n"
        "        [Days at #1],\n"
        "        CROSSFILTER ( bridge_track_artist[track_key], dim_track[track_key], BOTH )\n"
        "    ),\n"
        "    0\n"
        ")",
        "#,0",
        "Artists",
        "Days the artist held position 1.",
    ),
    Measure(
        "fact_chart_entry",
        "Artist Best Position",
        "CALCULATE (\n"
        "    [Best Position],\n"
        "    CROSSFILTER ( bridge_track_artist[track_key], dim_track[track_key], BOTH )\n"
        ")",
        "0",
        "Artists",
        "Best chart position reached by the artist.",
    ),
    Measure(
        "fact_chart_entry",
        "Top 5 Artist Days",
        "VAR Rank =\n"
        "    RANKX ( ALL ( dim_artist[artist_name] ), [Artist Weighted Chart Days], , DESC )\n"
        "RETURN\n"
        "    IF ( Rank <= 5, [Artist Weighted Chart Days] )",
        "#,0",
        "Artists",
        "Weighted chart days, shown only for the top 5 artists.",
    ),
    Measure(
        "fact_chart_entry",
        "Artist Insight",
        "VAR Artist = SELECTEDVALUE ( dim_artist[artist_name] )\n"
        "RETURN\n"
        "    IF (\n"
        "        ISBLANK ( Artist ),\n"
        '        "Select an artist to see their chart story.",\n'
        '        Artist & " holds " & FORMAT ( [Artist Share of Chart], "0.0%" )\n'
        '            & " of all chart slots across " & FORMAT ( [Artist Tracks], "0" )\n'
        '            & " songs, with " & FORMAT ( [Artist Days at #1], "0" ) & " days at #1."\n'
        "    )",
        "",
        "Artists",
        "One-sentence summary of the selected artist.",
    ),
    Measure(
        "fact_chart_entry",
        "Chart Strength",
        (
            "VAR FocusRank = MIN ( dim_track[chart_rank] )\n"
            "RETURN\n"
            "    CALCULATE (\n"
            "        51 - MIN ( fact_chart_entry[chart_position] ),\n"
            "        dim_track[chart_rank] = FocusRank\n"
            "    )"
        ),
        "0",
        "Song",
        (
            "Chart journey: 51 minus chart position (50 = #1). For the selected song, or the "
            "top-ranked song in the current selection."
        ),
    ),
    Measure(
        "mart_track_performance",
        "Days on Chart",
        "CALCULATE (\n"
        "    SUM ( mart_track_performance[total_chart_days] ),\n"
        "    CROSSFILTER ( bridge_track_artist[track_key], dim_track[track_key], BOTH )\n"
        ")",
        "#,0",
        "Track life",
        "Total days on chart (respects artist selection).",
    ),
    Measure(
        "mart_track_performance",
        "Tracks",
        "COUNTROWS ( mart_track_performance )",
        "#,0",
        "Track life",
        "Number of tracks.",
    ),
    Measure(
        "mart_track_performance",
        "Top Track",
        (
            "VAR FocusRank = MIN ( dim_track[chart_rank] )\n"
            "RETURN\n"
            "    CALCULATE ( MAX ( dim_track[track_label] ), dim_track[chart_rank] = FocusRank )"
        ),
        "",
        "Track life",
        "The longest-charting song in the current selection.",
    ),
    Measure(
        "mart_track_performance",
        "Peak Position",
        (
            "VAR FocusRank = MIN ( dim_track[chart_rank] )\n"
            "RETURN\n"
            "    CALCULATE (\n"
            "        MIN ( mart_track_performance[peak_position] ),\n"
            "        dim_track[chart_rank] = FocusRank\n"
            "    )"
        ),
        "0",
        "Song",
        (
            "Best chart position reached. For the selected song, or the top-ranked song in the "
            "current selection."
        ),
    ),
    Measure(
        "mart_track_performance",
        "Debut Position",
        (
            "VAR FocusRank = MIN ( dim_track[chart_rank] )\n"
            "RETURN\n"
            "    CALCULATE (\n"
            "        MIN ( mart_track_performance[debut_position] ),\n"
            "        dim_track[chart_rank] = FocusRank\n"
            "    )"
        ),
        "0",
        "Song",
        (
            "Chart position on the debut day. For the selected song, or the top-ranked song in the "
            "current selection."
        ),
    ),
    Measure(
        "mart_track_performance",
        "Release Year",
        (
            "VAR FocusRank = MIN ( dim_track[chart_rank] )\n"
            "RETURN\n"
            "    CALCULATE (\n"
            "        YEAR ( MIN ( mart_track_performance[release_date] ) ),\n"
            "        dim_track[chart_rank] = FocusRank\n"
            "    )"
        ),
        "0",
        "Song",
        "Release year. For the selected song, or the top-ranked song in the current selection.",
    ),
    Measure(
        "mart_track_performance",
        "Explicit Label",
        (
            "VAR FocusRank = MIN ( dim_track[chart_rank] )\n"
            "VAR IsExplicit =\n"
            "    CALCULATE (\n"
            "        COUNTROWS ( mart_track_performance ),\n"
            "        dim_track[chart_rank] = FocusRank,\n"
            "        mart_track_performance[debut_is_explicit] = TRUE ()\n"
            "    )\n"
            "RETURN\n"
            '    IF ( ISBLANK ( FocusRank ), BLANK (), IF ( IsExplicit > 0, "Yes", "No" ) )'
        ),
        "",
        "Song",
        (
            "Whether the song is explicit. For the selected song, or the top-ranked song in the "
            "current selection."
        ),
    ),
    Measure(
        "mart_track_performance",
        "Album Type",
        (
            "VAR FocusRank = MIN ( dim_track[chart_rank] )\n"
            "RETURN\n"
            "    CALCULATE (\n"
            "        SELECTEDVALUE ( mart_track_performance[debut_album_type] ),\n"
            "        dim_track[chart_rank] = FocusRank\n"
            "    )"
        ),
        "",
        "Song",
        (
            "Release type when the song debuted. For the selected song, or the top-ranked song in "
            "the current selection."
        ),
    ),
    Measure(
        "mart_track_performance",
        "Song",
        (
            "VAR FocusRank = MIN ( dim_track[chart_rank] )\n"
            "RETURN\n"
            "    CALCULATE ( MAX ( dim_track[track_label] ), dim_track[chart_rank] = FocusRank )"
        ),
        "",
        "Song",
        (
            "Name of the song the Songs page describes. For the selected song, or the top-ranked "
            "song in the current selection."
        ),
    ),
    Measure(
        "mart_track_performance",
        "Song Days on Chart",
        (
            "VAR FocusRank = MIN ( dim_track[chart_rank] )\n"
            "RETURN\n"
            "    CALCULATE (\n"
            "        SUM ( mart_track_performance[total_chart_days] ),\n"
            "        dim_track[chart_rank] = FocusRank\n"
            "    )"
        ),
        "#,0",
        "Song",
        (
            "Total days on chart. For the selected song, or the top-ranked song in the current "
            "selection."
        ),
    ),
    Measure(
        "fact_chart_entry",
        "Song Days at #1",
        (
            "VAR FocusRank = MIN ( dim_track[chart_rank] )\n"
            "RETURN\n"
            "    COALESCE (\n"
            "        CALCULATE ( [Days at #1], dim_track[chart_rank] = FocusRank ),\n"
            "        IF ( NOT ISBLANK ( FocusRank ), 0 )\n"
            "    )"
        ),
        "#,0",
        "Song",
        (
            "Days at position 1. For the selected song, or the top-ranked song in the current "
            "selection."
        ),
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
        if m.format:
            lines.append(f"\t\tformatString: {m.format}")
        lines += [
            f"\t\tdisplayFolder: {m.folder}",
            f"\t\tlineageTag: {_id('measure', table, m.name)}",
            "",
        ]

    for col, duck_type in cols:
        data_type, fmt = _column_format(col, duck_type)
        lines.append(f"\tcolumn {_quote(col)}")
        lines.append(f"\t\tdataType: {data_type}")
        if col.endswith("_key") or col.endswith("_order") or col == "chart_rank":
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
        if table == "dim_track" and col == "track_label":
            lines.append("\t\tsortByColumn: chart_rank")
        if col == "chart_life_bucket":
            lines.append("\t\tsortByColumn: chart_life_bucket_order")
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
        ]
        if (frm, fcol, to, tcol) in ONE_TO_ONE:
            rel.append("\tfromCardinality: one")
        if (frm, fcol, to, tcol) in BIDIRECTIONAL:
            rel.append("\tcrossFilteringBehavior: bothDirections")
        rel.append("")
    _write(d / "relationships.tmdl", "\n".join(rel))
    for table, source in MODEL_TABLES.items():
        _write(d / "tables" / f"{table}.tmdl", _table_tmdl(con, table, source))


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


def generate(con: duckdb.DuckDBPyConnection, root: Path, pbix: Path | None = None) -> None:
    """(Re)generate the PBIP project, its data files and powerbi/measures.dax.

    The report re-creates the design of ``pbix`` (the original hand-built dashboard)
    on the new semantic model.
    """
    from spotify_pipeline.powerbi_report import build_report

    pbix = pbix or PROJECT_ROOT / "dashboard" / "spotify_dashboard.pbix"
    for stale in (root / f"{PROJECT}.SemanticModel" / "definition", root / f"{PROJECT}.Report"):
        if stale.exists():
            shutil.rmtree(stale)
    export_data(con, root / "data")
    _semantic_model(con, root)
    build_report(
        pbix,
        root / f"{PROJECT}.Report",
        measures={m.name: m.table for m in MEASURES},
        model_tables=set(MODEL_TABLES),
        semantic_model_dir=f"{PROJECT}.SemanticModel",
        logical_id=_id("report"),
        project=PROJECT,
    )
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
