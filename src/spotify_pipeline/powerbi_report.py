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
FIELD_MAP = {
    ("Top-50-World", "song"): ("dim_track", "track_title"),
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


@dataclass
class _Visual:
    page: str
    x: float
    y: float
    visual_type: str
    container: dict
    old_roles: dict[str, list[str]] = field(default_factory=dict)


SLICER_SONGS = {"Values": [col("dim_track", "track_title", "Song")]}
PROGRESS = {"Y": [meas("Avg Popularity"), meas("Popularity Remainder")]}

# (page, visual type, x, y) of the original visual -> what it shows now.
BINDINGS: dict[tuple[str, str, int, int], Binding] = {
    # ------------------------------------------------------------------ Overview
    ("Overview", "advancedSlicerVisual", 37, 115): Binding(SLICER_SONGS, "Browse Songs"),
    ("Overview", "advancedSlicerVisual", 541, 110): Binding(SLICER_SONGS),
    ("Overview", "advancedSlicerVisual", 1081, 341): Binding({}, drop=True),  # month/qtr toggle
    ("Overview", "cardVisual", 408, 114): Binding(
        {"Data": [meas("Chart Entries", "Chart entries")]}
    ),
    ("Overview", "cardVisual", 408, 184): Binding(
        {"Data": [meas("Avg Popularity", "Avg popularity")]}
    ),
    ("Overview", "cardVisual", 408, 254): Binding(
        {"Data": [meas("Artists Charting", "Unique artists")]}
    ),
    ("Overview", "cardVisual", 401, 331): Binding(
        {"Data": [meas("Explicit Share", "Explicit entries")]}
    ),
    ("Overview", "gauge", 816, 118): Binding(
        {"Y": [meas("Avg Popularity")], "MaxValue": [meas("Popularity Max")]},
        "Average Popularity Score",
    ),
    ("Overview", "donutChart", 1047, 115): Binding(
        {
            "Category": [col("dim_track_version", "is_explicit", "Explicit")],
            "Y": [meas("Chart Entries")],
        },
        "Explicit Content",
    ),
    ("Overview", "lineClusteredColumnComboChart", 812, 225): Binding(
        {
            "Category": [col("dim_artist", "artist_name", "Artist")],
            "Y": [meas("Top 5 Artist Days", "Weighted chart days")],
        },
        "Top 5 Artists",
        sort_desc=meas("Top 5 Artist Days"),
    ),
    ("Overview", "barChart", 1044, 227): Binding(
        {
            "Category": [col("dim_track_version", "album_type", "Album type")],
            "Y": [meas("Chart Entries")],
        },
        "Album Type Distribution",
    ),
    ("Overview", "hundredPercentStackedBarChart", 563, 289): Binding(PROGRESS),
    ("Overview", "areaChart", 808, 342): Binding(
        {
            "Category": [col("dim_date", "year_month", "Month")],
            "Y": [meas("Avg Artist HHI", "Artist concentration")],
        },
        "Artist Dominance by Month",
    ),
    ("Overview", "clusteredBarChart", 307, 420): Binding(
        {
            "Category": [col("dim_artist", "artist_name", "Artist")],
            "Y": [meas("Artist Tracks", "Tracks")],
        },
        "Songs by Artist",
        sort_desc=meas("Artist Tracks"),
    ),
    ("Overview", "clusteredBarChart", 563, 420): Binding(
        {
            "Category": [col("dim_track", "track_title", "Song")],
            "Y": [meas("Days on Chart", "Days on chart")],
        },
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
    ("Artist", "advancedSlicerVisual", 1006, 117): Binding(SLICER_SONGS),
    ("Artist", "hundredPercentStackedBarChart", 1030, 290): Binding(PROGRESS),
    ("Artist", "cardVisual", 311, 422): Binding(
        {
            "Data": [
                meas("Top Track", "Longest-charting song"),
                meas("Artist Share of Chart", "Share of the chart"),
                meas("Artist Weighted Chart Days", "Weighted chart days"),
                meas("Artist Best Position", "Best position"),
            ]
        }
    ),
    ("Artist", "clusteredBarChart", 618, 426): Binding(
        {
            "Category": [col("mart_track_performance", "track_title", "Song")],
            "Y": [meas("Days on Chart", "Days on chart")],
        },
        "Songs by Days on Chart",
        sort_desc=meas("Days on Chart"),
    ),
    ("Artist", "cardVisual", 409, 610): Binding({"Data": [meas("Artist Insight", " ")]}),
    # ------------------------------------------------------------------ Songs
    ("Songs", "cardVisual", 294, 112): Binding({"Data": [meas("Days on Chart", "Days on Chart")]}),
    ("Songs", "cardVisual", 537, 112): Binding({"Data": [meas("Peak Position", "Peak Position")]}),
    ("Songs", "cardVisual", 778, 113): Binding(
        {"Data": [meas("Debut Position", "Debut Position")]}
    ),
    ("Songs", "advancedSlicerVisual", 1013, 112): Binding(SLICER_SONGS),
    ("Songs", "tableEx", 36, 119): Binding(
        {
            "Values": [
                col("dim_track", "track_title", "Song"),
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
                meas("Days at #1", "Days at #1"),
                meas("Album Type", "Album type"),
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
                "Y": [meas("Tracks", "Tracks")],
            },
            "How Long Tracks Last",
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


def _remap_entities(node, model_tables: set[str]):
    """Rewrite old field references; return None for entries that can't be mapped."""
    if isinstance(node, dict):
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
                    return None
        out = {}
        for k, v in node.items():
            new = _remap_entities(v, model_tables)
            if new is None:
                return None
            out[k] = new
        return out
    if isinstance(node, list):
        kept = []
        for item in node:
            new = _remap_entities(item, model_tables)
            if new is not None:
                kept.append(new)
        return kept
    return node


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
    objects = _remap_entities(sv.get("objects", {}), model_tables) or {}
    vc_objects = _remap_entities(sv.get("vcObjects", {}), model_tables) or {}

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
        query: dict = {"queryState": query_state}
        if binding.sort_desc is not None:
            query["sortDefinition"] = {
                "sort": [
                    {"field": _field_expr(binding.sort_desc, measures), "direction": "Descending"}
                ],
                "isDefaultSort": False,
            }
        visual["query"] = query
        if binding.title:
            vc_objects = _set_title(vc_objects, binding.title)
    if _clean(objects):
        visual["objects"] = _clean(objects)
    if _clean(vc_objects):
        visual["visualContainerObjects"] = _clean(vc_objects)
    visual["drillFilterOtherVisuals"] = True

    pos = position or _position(v.container)
    return {
        "$schema": f"{SCHEMA}/item/report/definition/visualContainer/{VERSIONS['visual']}"
        "/schema.json",
        "name": name or cfg["name"],
        "position": pos,
        "visual": visual,
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
        page_objects = _remap_entities(section_cfg.get("objects", {}), model_tables)
        if page_objects:
            page_json["objects"] = page_objects
        _write_json(d / "pages" / section["name"] / "page.json", page_json)

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

    _write_json(
        d / "pages" / "pages.json",
        {
            "$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json",
            "pageOrder": page_order,
            "activePageName": page_order[0],
        },
    )


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
