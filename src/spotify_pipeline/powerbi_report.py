"""Port the original dashboard's design onto the new semantic model.

The original report (dashboard/spotify_dashboard.pbix) was designed by hand: dark
page backgrounds, rounded cards, Spotify-green accents, icons, an album-cover
"player", and page-navigation buttons. This module reads that design straight from
the .pbix and re-creates every visual in PBIR format, keeping its position and all of
its formatting (objects, container objects, images, page backgrounds, theme), and
re-binding only the data: each visual now shows fields and measures from the tested
star schema instead of the raw CSV.

The binding spec below says, for every data visual on every page, which fields it
shows. Static visuals (images, shapes, navigation buttons) are copied unchanged.
"""

from __future__ import annotations

import copy
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
VERSIONS = {"report": "3.3.0", "page": "2.1.0", "visual": "2.11.0"}

# Old (CSV) fields referenced inside the original formatting -> new model fields.
# Songs are identified by dim_track.track_label: unique (unlike titles) and sorted by
# chart_rank, so every song list and the album-cover player start with the biggest hit.
FIELD_MAP = {
    ("Top-50-World", "song"): ("dim_track", "track_label"),
    ("Top-50-World", "artist"): ("dim_track", "lead_artist_name"),
    ("Top-50-World", "album_cover_url"): ("mart_track_performance", "album_cover_url"),
    ("Top-50-World", "is_explicit"): ("dim_track_version", "is_explicit"),
    ("Top-50-World", "album_type"): ("dim_track_version", "album_type"),
}
STATIC_TYPES = {"image", "shape", "actionButton", "textbox", "basicShape"}
PAGE_NAMES = {"Home": "Home", "Overview": "Overview", "Artist": "Artists", "Songs": "Songs"}


@dataclass(frozen=True)
class F:
    """A field binding: a column (table, column) or a measure (name)."""

    table: str | None = None
    column: str | None = None
    measure: str | None = None
    label: str | None = None  # display name shown in the visual


def col(table: str, column: str, label: str | None = None) -> F:
    return F(table=table, column=column, label=label)


def meas(name: str, label: str | None = None) -> F:
    return F(measure=name, label=label)


@dataclass
class Binding:
    roles: dict[str, list[F]]
    title: str | None = None
    sort_desc: F | None = None
    drop: bool = False
    top_n: tuple[F, str, int] | None = None  # (category, ranking measure, N)
    # A "player" shows the current song; it follows the page's selections but its own
    # clicks never filter other visuals.
    player: bool = False


@dataclass
class _Visual:
    page: str
    x: float
    y: float
    visual_type: str
    container: dict
    old_roles: dict[str, list[str]] = field(default_factory=dict)


SONG = col("dim_track", "track_label", "Song")
SONG_LIST = {"Values": [SONG]}
PROGRESS = {"Y": [meas("Avg Popularity"), meas("Popularity Remainder")]}


def player() -> Binding:
    return Binding(SONG_LIST, player=True)


# (page, visual type, x, y) of the original visual -> what it shows now.
#
# Every number has one meaning:
#   Overview  the whole chart, filtered by whatever you click
#   Artists   all artists until you click one, then that artist
#   Songs     always ONE song: the one you click, or the biggest hit in the selection
#             (the player shows that same song)
BINDINGS: dict[tuple[str, str, int, int], Binding] = {
    # ------------------------------------------------------------------ Overview
    ("Overview", "advancedSlicerVisual", 37, 115): Binding(SONG_LIST, "Browse Songs"),
    ("Overview", "advancedSlicerVisual", 541, 110): player(),
    ("Overview", "advancedSlicerVisual", 1081, 341): Binding({}, drop=True),  # month/qtr toggle
    ("Overview", "cardVisual", 408, 114): Binding(
        {"Data": [meas("Tracks Charting", "Total Songs")]}
    ),
    ("Overview", "cardVisual", 408, 184): Binding(
        {"Data": [meas("Avg Popularity", "Avg Popularity")]}
    ),
    ("Overview", "cardVisual", 408, 254): Binding(
        {"Data": [meas("Artists Charting", "Unique Artists")]}
    ),
    ("Overview", "cardVisual", 401, 331): Binding({"Data": [meas("Explicit Share", "Explicit %")]}),
    ("Overview", "gauge", 816, 118): Binding(
        {"Y": [meas("Avg Popularity")], "MaxValue": [meas("Popularity Max")]},
        "Average Popularity Score",
    ),
    ("Overview", "donutChart", 1047, 115): Binding(
        {
            "Category": [col("dim_track_version", "is_explicit", "Explicit")],
            "Y": [meas("Chart Entries", "Chart entries")],
        },
        "Explicit Content (chart entries)",
    ),
    ("Overview", "lineClusteredColumnComboChart", 812, 225): Binding(
        {
            "Category": [col("dim_artist", "artist_name", "Artist")],
            "Y": [meas("Artist Weighted Chart Days", "Chart days (collabs split)")],
        },
        "Top 5 Artists",
        sort_desc=meas("Artist Weighted Chart Days"),
        top_n=(col("dim_artist", "artist_name"), "Artist Weighted Chart Days", 5),
    ),
    ("Overview", "barChart", 1044, 227): Binding(
        {
            "Category": [col("dim_track_version", "album_type", "Album type")],
            "Y": [meas("Chart Entries", "Chart entries")],
        },
        "Album Type (chart entries)",
    ),
    ("Overview", "hundredPercentStackedBarChart", 563, 289): Binding(PROGRESS),
    ("Overview", "areaChart", 808, 342): Binding(
        {
            "Category": [col("dim_date", "year_month", "Month")],
            "Y": [meas("Avg Popularity", "Avg popularity")],
        },
        "Average Popularity by Month",
    ),
    ("Overview", "clusteredBarChart", 307, 420): Binding(
        {
            "Category": [col("dim_artist", "artist_name", "Artist")],
            "Y": [meas("Artist Tracks", "Songs")],
        },
        "Songs by Artist",
        sort_desc=meas("Artist Tracks"),
    ),
    ("Overview", "clusteredBarChart", 563, 420): Binding(
        {"Category": [SONG], "Y": [meas("Days on Chart", "Days on chart")]},
        "Longest Chart Runs",
        sort_desc=meas("Days on Chart"),
    ),
    ("Overview", "scatterChart", 819, 514): Binding({}, drop=True),  # replaced below
    # ------------------------------------------------------------------ Artists
    ("Artist", "tableEx", 36, 119): Binding(
        {
            "Values": [
                col("dim_artist", "artist_name", "Artist"),
                meas("Artist Tracks", "Songs"),
                meas("Artist Share of Chart", "Chart share"),
            ]
        },
        "Browse Artists",
        sort_desc=meas("Artist Share of Chart"),
    ),
    ("Artist", "cardVisual", 300, 122): Binding({"Data": [meas("Artist Tracks", "Unique Songs")]}),
    ("Artist", "cardVisual", 540, 123): Binding(
        {"Data": [meas("Artist Avg Popularity", "Avg Popularity")]}
    ),
    ("Artist", "cardVisual", 777, 123): Binding(
        {"Data": [meas("Artist Days at #1", "Days at #1")]}
    ),
    ("Artist", "advancedSlicerVisual", 1006, 117): player(),
    ("Artist", "hundredPercentStackedBarChart", 1030, 290): Binding(PROGRESS),
    ("Artist", "cardVisual", 311, 422): Binding(
        {
            "Data": [
                meas("Top Track", "Top Song"),
                meas("Artist Best Position", "Best Position"),
                meas("Artist Weighted Chart Days", "Chart Days"),
                meas("Artist Share of Chart", "Chart Share"),
            ]
        }
    ),
    ("Artist", "clusteredBarChart", 618, 426): Binding(
        {"Category": [SONG], "Y": [meas("Days on Chart", "Days on chart")]},
        "Songs by Days on Chart",
        sort_desc=meas("Days on Chart"),
    ),
    ("Artist", "cardVisual", 409, 610): Binding({"Data": [meas("Artist Insight", " ")]}),
    # ------------------------------------------------------------------ Songs
    ("Songs", "cardVisual", 294, 112): Binding(
        {"Data": [meas("Song Days on Chart", "Days on Chart")]}
    ),
    ("Songs", "cardVisual", 537, 112): Binding({"Data": [meas("Peak Position", "Peak Position")]}),
    ("Songs", "cardVisual", 778, 113): Binding(
        {"Data": [meas("Debut Position", "First Position")]}
    ),
    ("Songs", "advancedSlicerVisual", 1013, 112): player(),
    ("Songs", "tableEx", 36, 119): Binding(
        {
            "Values": [
                SONG,
                col("dim_track", "lead_artist_name", "Artist"),
                meas("Days on Chart", "Days"),
            ]
        },
        sort_desc=meas("Days on Chart"),
    ),
    ("Songs", "hundredPercentStackedBarChart", 1026, 284): Binding(PROGRESS),
    ("Songs", "cardVisual", 281, 417): Binding(
        {
            "Data": [
                meas("Release Year", "Release Year"),
                meas("Explicit Label", "Explicit"),
                meas("Song Days at #1", "Days at #1"),
                meas("Song", "Song"),
            ]
        }
    ),
    ("Songs", "stackedAreaChart", 591, 426): Binding(
        {
            "Category": [col("dim_date", "calendar_date", "Date")],
            "Y": [meas("Chart Strength", "Chart strength (50 = #1)")],
        },
        "Chart Journey (50 = #1)",
    ),
}

# New visual that takes the dropped scatter chart's slot, styled like its neighbours.
# (page, slot taken from, style donor visual, binding)
REPLACEMENTS = [
    (
        ("Overview", "scatterChart", 819, 514),
        ("Overview", "clusteredBarChart", 307, 420),
        "clusteredColumnChart",
        Binding(
            {
                "Category": [col("mart_track_performance", "chart_life_bucket", "Chart life")],
                "Y": [meas("Tracks", "Songs")],
            },
            "How Long Songs Last on the Chart",
        ),
    ),
]


# --------------------------------------------------------------------------- reading


def _load_layout(pbix: Path) -> tuple[dict, dict[str, bytes]]:
    with zipfile.ZipFile(pbix) as z:
        layout = json.loads(z.read("Report/Layout").decode("utf-16-le").lstrip("﻿"))
        prefix = "Report/StaticResources/"
        resources = {n[len(prefix) :]: z.read(n) for n in z.namelist() if n.startswith(prefix)}
    return layout, resources


def _key(page: str, visual_type: str, x: float, y: float) -> tuple[str, str, int, int]:
    return page, visual_type, round(x), round(y)


def _find_binding(page: str, visual_type: str, x: float, y: float):
    for (p, t, bx, by), b in BINDINGS.items():
        if p == page and t == visual_type and abs(bx - x) <= 2 and abs(by - y) <= 2:
            return b
    return None


# --------------------------------------------------------------------------- rewriting


def _field_expr(f: F, measures: dict[str, str]) -> dict:
    if f.measure:
        return {
            "Measure": {
                "Expression": {"SourceRef": {"Entity": measures[f.measure]}},
                "Property": f.measure,
            }
        }
    return {"Column": {"Expression": {"SourceRef": {"Entity": f.table}}, "Property": f.column}}


def _query_ref(f: F, measures: dict[str, str]) -> str:
    return f"{measures[f.measure]}.{f.measure}" if f.measure else f"{f.table}.{f.column}"


class _Unmappable(Exception):
    """A formatting value refers to a field that does not exist in the new model."""


# Every change the port makes to the original formatting, for review (see port_log()).
PORT_LOG: list[str] = []


def port_log() -> list[str]:
    return list(PORT_LOG)


def _max_color(fill_rule: dict) -> dict | None:
    """The top colour of a conditional colour rule, e.g. the green of white->green."""
    for gradient in ("linearGradient3", "linearGradient2"):
        grad = fill_rule.get(gradient)
        if grad and "max" in grad:
            return grad["max"].get("color")
    return None


def _remap(node, model_tables: set[str], where: str):
    """Rewrite old field references to the new model.

    Formatting is kept whenever possible:
      * a conditional colour rule driven by an old measure becomes a solid colour (the
        rule's top colour), so the number keeps its look
      * otherwise only the single property that refers to a missing field is dropped,
        never the whole formatting block
    """
    if isinstance(node, dict):
        # A conditional colour is {"FillRule": {"Input": <field>, "FillRule": <gradient>}}.
        rule = node.get("FillRule")
        if len(node) == 1 and isinstance(rule, dict) and "Input" in rule:
            try:
                return {"FillRule": _remap(rule, model_tables, where)}
            except _Unmappable:
                color = _max_color(node["FillRule"].get("FillRule", {}))
                if color is None:
                    raise
                PORT_LOG.append(f"{where}: conditional colour on an old field -> solid colour")
                return color
        if "Property" in node and isinstance(node.get("Expression"), dict):
            src = node["Expression"].get("SourceRef", {})
            if "Entity" in src:
                key = (src["Entity"], node["Property"])
                if key in FIELD_MAP:
                    table, column = FIELD_MAP[key]
                    return {
                        **node,
                        "Expression": {"SourceRef": {"Entity": table}},
                        "Property": column,
                    }
                if src["Entity"] not in model_tables:
                    raise _Unmappable(f"{src['Entity']}.{node['Property']}")
        out = {}
        for k, v in node.items():
            if k == "properties" and isinstance(v, dict):
                props = {}
                for name, value in v.items():
                    try:
                        props[name] = _remap(value, model_tables, where)
                    except _Unmappable as e:
                        PORT_LOG.append(f"{where}: dropped property '{name}' (refers to {e})")
                out[k] = props
            else:
                out[k] = _remap(v, model_tables, where)
        return out
    if isinstance(node, list):
        kept = []
        for item in node:
            try:
                kept.append(_remap(item, model_tables, where))
            except _Unmappable as e:
                PORT_LOG.append(f"{where}: dropped a formatting rule (refers to {e})")
        return kept
    return node


def _remap_entities(node, model_tables: set[str], where: str = "?"):
    try:
        return _remap(node, model_tables, where)
    except _Unmappable as e:
        PORT_LOG.append(f"{where}: dropped (refers to {e})")
        return None


def _scope_columns(entry: dict) -> set[tuple[str, str]]:
    found = set()
    for m in re.finditer(
        r'"Entity": "([^"]+)"\}\}, "Property": "([^"]+)"',
        json.dumps(entry.get("selector", {}).get("data", [])),
    ):
        found.add((m.group(1), m.group(2)))
    return found


def _prune_scopes(objects: dict, bound: set[tuple[str, str]], where: str) -> dict:
    """Drop per-category formatting for fields the visual no longer shows.

    The original visuals had colours keyed to album type or an auto-date Year that are
    not part of the new visuals; Power BI can fail on such stale rules.
    """
    out = {}
    for group, entries in objects.items():
        kept = []
        for entry in entries:
            cols = _scope_columns(entry) if isinstance(entry, dict) else set()
            if cols and not cols <= bound:
                PORT_LOG.append(
                    f"{where}: dropped {group} rule for fields not in the visual "
                    f"{sorted(c[1] for c in cols - bound)}"
                )
                continue
            kept.append(entry)
        out[group] = kept
    return out


def _remap_metadata(node, mapping: dict[str, str], fallback: str | None):
    """Rewrite per-field selectors ({"metadata": queryRef}); drop unmappable ones."""
    if isinstance(node, list):
        out = []
        for item in node:
            sel = item.get("selector", {}) if isinstance(item, dict) else {}
            meta = sel.get("metadata")
            if meta is not None:
                new = mapping.get(meta, fallback)
                if new is None:
                    continue
                item = {**item, "selector": {**sel, "metadata": new}}
            out.append(_remap_metadata(item, mapping, fallback))
        return out
    if isinstance(node, dict):
        return {k: _remap_metadata(v, mapping, fallback) for k, v in node.items()}
    return node


def _set_title(vc_objects: dict, title: str) -> dict:
    vc = copy.deepcopy(vc_objects)
    entries = vc.setdefault("title", [{"properties": {}}])
    props = entries[0].setdefault("properties", {})
    props["text"] = {"expr": {"Literal": {"Value": "'" + title.replace("'", "''") + "'"}}}
    props["show"] = {"expr": {"Literal": {"Value": "true"}}}
    return vc


def _clean(objects: dict) -> dict:
    """Drop object groups left empty after remapping."""
    return {k: v for k, v in objects.items() if v}


def _build_visual(
    v: _Visual,
    binding: Binding | None,
    measures: dict[str, str],
    model_tables: set[str],
    visual_type: str | None = None,
    position: dict | None = None,
    name: str | None = None,
) -> dict:
    cfg = v.container["config"]
    sv = cfg.get("singleVisual", {})
    where = f"{v.page} {v.visual_type} ({v.x:.0f},{v.y:.0f})"
    objects = _remap_entities(sv.get("objects", {}), model_tables, where) or {}
    vc_objects = _remap_entities(sv.get("vcObjects", {}), model_tables, where) or {}

    visual: dict = {"visualType": visual_type or v.visual_type}
    if binding is not None and binding.roles:
        query_state, mapping = {}, {}
        for role, fields in binding.roles.items():
            projections = []
            for i, f in enumerate(fields):
                ref = _query_ref(f, measures)
                proj = {
                    "field": _field_expr(f, measures),
                    "queryRef": ref,
                    "nativeQueryRef": f.label or f.measure or f.column,
                }
                if f.label:
                    proj["displayName"] = f.label
                projections.append(proj)
                old = v.old_roles.get(role, [])
                if i < len(old):
                    mapping[old[i]] = ref
            query_state[role] = {"projections": projections}
        all_refs = [p["queryRef"] for s in query_state.values() for p in s["projections"]]
        fallback = all_refs[0] if len(all_refs) == 1 else None
        objects = _remap_metadata(objects, mapping, fallback)
        vc_objects = _remap_metadata(vc_objects, mapping, fallback)
        bound = {(f.table, f.column) for fs in binding.roles.values() for f in fs if f.column}
        objects = _prune_scopes(objects, bound, where)
        query: dict = {"queryState": query_state}
        if binding.sort_desc is not None:
            query["sortDefinition"] = {
                "sort": [
                    {"field": _field_expr(binding.sort_desc, measures), "direction": "Descending"}
                ],
                "isDefaultSort": False,
            }
        visual["query"] = query
        if binding.top_n is not None:
            visual_filter = _top_n_filter(binding, measures, v.container["config"]["name"])
        if binding.title:
            vc_objects = _set_title(vc_objects, binding.title)
    if visual["visualType"] == "cardVisual":
        objects = _full_numbers(objects)
    if _clean(objects):
        visual["objects"] = _clean(objects)
    if _clean(vc_objects):
        visual["visualContainerObjects"] = _clean(vc_objects)
    visual["drillFilterOtherVisuals"] = True

    pos = position or _position(v.container)
    out = {
        "$schema": f"{SCHEMA}/item/report/definition/visualContainer/{VERSIONS['visual']}"
        "/schema.json",
        "name": name or cfg["name"],
        "position": pos,
        "visual": visual,
    }
    if binding is not None and binding.top_n is not None:
        out["filterConfig"] = {"filters": [visual_filter]}
    return out


def _full_numbers(objects: dict) -> dict:
    """Cards show full numbers (display units: None), so 1,871 never becomes "2K".

    Uses the original dashboard's own setting (labelDisplayUnits = 1) on the default
    selector, so it applies to every field of the card.
    """
    objects = copy.deepcopy(objects)
    entries = objects.setdefault("value", [])
    default = next((e for e in entries if e.get("selector", {}).get("id") == "default"), None)
    if default is None:
        default = {"properties": {}, "selector": {"id": "default"}}
        entries.insert(0, default)
    default.setdefault("properties", {})["labelDisplayUnits"] = {
        "expr": {"Literal": {"Value": "1D"}}
    }
    return objects


def _top_n_filter(binding: Binding, measures: dict[str, str], visual_name: str) -> dict:
    """A visual-level Top N filter, as Power BI's own "Top N" filter type."""
    category, measure, n = binding.top_n
    by_table = measures[measure]
    return {
        "name": f"top{n}_{visual_name}"[:50],
        "field": _field_expr(category, measures),
        "type": "TopN",
        "filter": {
            "Version": 2,
            "From": [
                {
                    "Name": "subquery",
                    "Expression": {
                        "Subquery": {
                            "Query": {
                                "Version": 2,
                                "From": [
                                    {"Name": "c", "Entity": category.table, "Type": 0},
                                    {"Name": "m", "Entity": by_table, "Type": 0},
                                ],
                                "Select": [
                                    {
                                        "Column": {
                                            "Expression": {"SourceRef": {"Source": "c"}},
                                            "Property": category.column,
                                        },
                                        "Name": "field",
                                    }
                                ],
                                "OrderBy": [
                                    {
                                        "Direction": 2,
                                        "Expression": {
                                            "Measure": {
                                                "Expression": {"SourceRef": {"Source": "m"}},
                                                "Property": measure,
                                            }
                                        },
                                    }
                                ],
                                "Top": n,
                            }
                        }
                    },
                    "Type": 2,
                },
                {"Name": "c", "Entity": category.table, "Type": 0},
            ],
            "Where": [
                {
                    "Condition": {
                        "In": {
                            "Expressions": [
                                {
                                    "Column": {
                                        "Expression": {"SourceRef": {"Source": "c"}},
                                        "Property": category.column,
                                    }
                                }
                            ],
                            "Table": {"SourceRef": {"Source": "subquery"}},
                        }
                    }
                }
            ],
        },
        "howCreated": "User",
    }


def _position(container: dict) -> dict:
    layouts = container["config"].get("layouts") or [{}]
    tab = layouts[0].get("position", {}).get("tabOrder", container.get("z", 0))
    return {
        "x": container["x"],
        "y": container["y"],
        "z": container.get("z", 0),
        "width": container["width"],
        "height": container["height"],
        "tabOrder": tab,
    }


# --------------------------------------------------------------------------- writing


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )


def build_report(
    pbix: Path,
    report_dir: Path,
    measures: dict[str, str],
    model_tables: set[str],
    semantic_model_dir: str,
    logical_id: str,
    project: str,
) -> None:
    """Write the PBIR report folder, re-creating the original design on the new model."""
    PORT_LOG.clear()
    layout, resources = _load_layout(pbix)
    report_config = json.loads(layout["config"])

    # Static resources: background designs, icons, and the base theme, byte-for-byte.
    for rel, data in resources.items():
        target = report_dir / "StaticResources" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    _write_json(
        report_dir / "definition.pbir",
        {
            "$schema": f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json",
            "version": "4.0",
            "datasetReference": {"byPath": {"path": f"../{semantic_model_dir}"}},
        },
    )
    _write_json(
        report_dir / ".platform",
        {
            "$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {"type": "Report", "displayName": project},
            "config": {"version": "2.0", "logicalId": logical_id},
        },
    )

    d = report_dir / "definition"
    _write_json(
        d / "version.json",
        {
            "$schema": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json",
            "version": "2.0.0",
        },
    )

    base = report_config["themeCollection"]["baseTheme"]
    images = sorted(r.split("/", 1)[1] for r in resources if r.startswith("RegisteredResources/"))
    theme_files = sorted(r.split("/", 1)[1] for r in resources if r.startswith("SharedResources/"))
    report_json = {
        "$schema": f"{SCHEMA}/item/report/definition/report/{VERSIONS['report']}/schema.json",
        "themeCollection": {
            "baseTheme": {
                "name": base["name"],
                "reportVersionAtImport": base["version"],
                "type": "SharedResources",
            }
        },
        "objects": report_config.get("objects", {}),
        "resourcePackages": [
            {
                "name": "SharedResources",
                "type": "SharedResources",
                "items": [
                    {"name": base["name"], "path": p, "type": "BaseTheme"} for p in theme_files
                ],
            },
            {
                "name": "RegisteredResources",
                "type": "RegisteredResources",
                "items": [{"name": p, "path": p, "type": "Image"} for p in images],
            },
        ],
    }
    _write_json(d / "report.json", report_json)

    page_order = []
    for section in layout["sections"]:
        page = section["displayName"]
        page_order.append(section["name"])
        section_cfg = json.loads(section.get("config", "{}"))
        page_json = {
            "$schema": f"{SCHEMA}/item/report/definition/page/{VERSIONS['page']}/schema.json",
            "name": section["name"],
            "displayName": PAGE_NAMES.get(page, page),
            "displayOption": "FitToPage",
            "height": section["height"],
            "width": section["width"],
        }
        page_objects = _remap_entities(section_cfg.get("objects", {}), model_tables, f"{page} page")
        if page_objects:
            page_json["objects"] = page_objects
        data_visuals: list[str] = []  # names of visuals that show data
        players: set[str] = set()

        visuals: dict[tuple, _Visual] = {}
        for container in section["visualContainers"]:
            cfg = json.loads(container["config"])
            sv = cfg.get("singleVisual")
            if sv is None:
                continue
            v = _Visual(
                page,
                container["x"],
                container["y"],
                sv["visualType"],
                {**container, "config": cfg},
                {
                    role: [p["queryRef"] for p in items]
                    for role, items in sv.get("projections", {}).items()
                },
            )
            visuals[_key(page, v.visual_type, v.x, v.y)] = v

        for key, v in visuals.items():
            binding = _find_binding(page, v.visual_type, v.x, v.y)
            if v.visual_type not in STATIC_TYPES and binding is None:
                raise ValueError(f"No binding for data visual {key}; add it to BINDINGS")
            if binding is not None and binding.drop:
                continue
            out = _build_visual(v, binding, measures, model_tables)
            _write_json(
                d / "pages" / section["name"] / "visuals" / out["name"] / "visual.json", out
            )
            if binding is not None and binding.roles:
                data_visuals.append(out["name"])
                if binding.player:
                    players.add(out["name"])

        for slot, donor, new_type, binding in REPLACEMENTS:
            if slot[0] != page:
                continue
            slot_v = next(v for k, v in visuals.items() if _matches(k, slot))
            donor_v = next(v for k, v in visuals.items() if _matches(k, donor))
            out = _build_visual(
                donor_v,
                binding,
                measures,
                model_tables,
                new_type,
                position=_position(slot_v.container),
                name=slot_v.container["config"]["name"],
            )
            _write_json(
                d / "pages" / section["name"] / "visuals" / out["name"] / "visual.json", out
            )
            data_visuals.append(out["name"])

        interactions = _interactions(data_visuals, players)
        if interactions:
            page_json["visualInteractions"] = interactions
        _write_json(d / "pages" / section["name"] / "page.json", page_json)

    _write_json(
        d / "pages" / "pages.json",
        {
            "$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json",
            "pageOrder": page_order,
            "activePageName": page_order[0],
        },
    )


def _interactions(data_visuals: list[str], players: set[str]) -> list[dict]:
    """Explicit interaction rules, so every click behaves the same predictable way.

    * Selections FILTER other visuals (no cross-highlighting, where bars only dim and
      numbers become hard to read).
    * A player follows the selection but never filters anything itself.
    """
    rules = []
    for source in data_visuals:
        for target in data_visuals:
            if source != target:
                kind = "NoFilter" if source in players else "DataFilter"
                rules.append({"source": source, "target": target, "type": kind})
    return rules


def _matches(key: tuple, spec: tuple) -> bool:
    return (
        key[0] == spec[0]
        and key[1] == spec[1]
        and abs(key[2] - spec[2]) <= 2
        and abs(key[3] - spec[3]) <= 2
    )


def referenced_old_entities(report_dir: Path) -> set[str]:
    """Entities referenced anywhere in the report (used by tests)."""
    found = set()
    for f in report_dir.rglob("*.json"):
        found |= set(re.findall(r'"Entity": "([^"]+)"', f.read_text(encoding="utf-8")))
    return found
