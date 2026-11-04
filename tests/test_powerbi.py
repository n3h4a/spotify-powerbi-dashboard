"""Static checks on the generated Power BI Project.

Power BI Desktop can't run in CI, so these tests catch, ahead of time, the mistakes
Desktop would reject on open: unknown fields, broken DAX references, bad TMDL
indentation, M names that shadow library functions, and a stale project or data.
"""

import json
import re

import pytest

from spotify_pipeline import powerbi
from spotify_pipeline.config import PROJECT_ROOT

ROOT = PROJECT_ROOT / "powerbi"
MODEL = ROOT / f"{powerbi.PROJECT}.SemanticModel" / "definition"
REPORT = ROOT / f"{powerbi.PROJECT}.Report" / "definition"


def model_objects() -> dict[str, set[str]]:
    """Table name -> set of column and measure names, parsed from the TMDL files."""
    objects = {}
    for f in (MODEL / "tables").glob("*.tmdl"):
        text = f.read_text(encoding="utf-8")
        table = re.match(r"table (\S+)", text).group(1)
        names = set()
        for _kind, name in re.findall(r"^\t(column|measure) ('(?:[^']|'')+'|\S+)", text, re.M):
            names.add(name.strip("'").replace("''", "'"))
        objects[table] = names
    return objects


def visual_fields():
    for f in REPORT.rglob("visual.json"):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(
            r'"(Column|Measure)": \{\s*"Expression": \{\s*"SourceRef": \{\s*"Entity": "([^"]+)"'
            r'\s*\}\s*\},\s*"Property": "([^"]+)"',
            text,
        ):
            yield f, m.group(1), m.group(2), m.group(3)


def test_every_visual_field_exists_in_the_model():
    objects = model_objects()
    fields = list(visual_fields())
    assert fields, "no fields found in visuals"
    missing = [(f.parent.name, t, n) for f, _, t, n in fields if n not in objects.get(t, set())]
    assert missing == []


def test_every_dax_reference_exists():
    objects = model_objects()
    all_names = set().union(*objects.values())
    for m in powerbi.MEASURES:
        for table, column in re.findall(r"(\w+)\[([^\]]+)\]", m.expression):
            assert column in objects[table], f"{m.name}: {table}[{column}]"
        bare = re.findall(r"(?<![\w\]])\[([^\]]+)\]", m.expression)
        for ref in bare:
            assert ref in all_names, f"{m.name}: [{ref}]"


def test_relationship_columns_exist():
    objects = model_objects()
    for frm, fcol, to, tcol in powerbi.RELATIONSHIPS:
        assert fcol in objects[frm] and tcol in objects[to]


def test_tmdl_uses_tab_indentation_only():
    for f in MODEL.rglob("*.tmdl"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            indent = line[: len(line) - len(line.lstrip())]
            # Structure is tab-indented. Only expression bodies (DAX or M, 3+ tabs deep)
            # may continue with spaces for their own internal formatting.
            tabs = len(indent) - len(indent.lstrip("\t"))
            assert indent.lstrip("\t").strip(" ") == "", f"{f.name}:{n}"
            assert indent == "\t" * tabs or tabs >= 3, f"{f.name}:{n}"


def test_power_query_does_not_shadow_library_names():
    for f in (MODEL / "tables").glob("*.tmdl"):
        steps = re.findall(r"^\t{4}    (\w+) =", f.read_text(encoding="utf-8"), re.M)
        assert not set(steps) & {"File", "Web", "Text", "Table", "Binary", "Parquet", "List"}


def test_json_files_parse_and_declare_a_schema():
    for f in (ROOT / f"{powerbi.PROJECT}.Report").rglob("*.json"):
        doc = json.loads(f.read_text(encoding="utf-8"))
        if "StaticResources" not in f.parts:
            assert doc["$schema"].startswith("https://developer.microsoft.com/json-schemas/")


def test_committed_project_is_up_to_date(real_warehouse, tmp_path):
    con, _ = real_warehouse
    powerbi.generate(con, tmp_path)
    fresh = {p.relative_to(tmp_path): p for p in tmp_path.rglob("*") if p.is_file()}
    committed = {
        p.relative_to(ROOT): p for p in ROOT.rglob("*") if p.is_file() and ".pbi" not in p.parts
    }
    assert set(fresh) == set(committed)
    for rel, path in fresh.items():
        if path.suffix == ".parquet":
            continue  # compared by content below
        assert path.read_bytes() == committed[rel].read_bytes(), f"stale: {rel}"


@pytest.mark.parametrize("table", list(powerbi.MODEL_TABLES))
def test_committed_data_matches_warehouse(real_warehouse, table):
    con, _ = real_warehouse
    path = (ROOT / "data" / f"{table}.parquet").as_posix()
    source = powerbi.MODEL_TABLES[table]
    [(diff,)] = con.execute(
        f"SELECT count(*) FROM ((SELECT * FROM {source} EXCEPT ALL SELECT * FROM '{path}') "
        f"UNION ALL (SELECT * FROM '{path}' EXCEPT ALL SELECT * FROM {source}))"
    ).fetchall()
    assert diff == 0


def test_measures_dax_matches_model():
    assert (ROOT / "measures.dax").read_text(encoding="utf-8") == powerbi.measures_dax()


def test_parquet_files_are_small_enough_for_git():
    total = sum(p.stat().st_size for p in (ROOT / "data").glob("*.parquet"))
    assert total < 5 * 1024 * 1024


def test_local_folder_path_works_for_file_contents():
    # The DataLocation parameter switches between web and local loading.
    text = (MODEL / "tables" / "dim_date.tmdl").read_text(encoding="utf-8")
    assert "File.Contents(DataLocation & FileName)" in text
    assert "Web.Contents(DataLocation & FileName)" in text


# ------------------------------------------------------------------ the ported original design


def _visuals():
    for f in REPORT.rglob("visual.json"):
        yield f, json.loads(f.read_text(encoding="utf-8"))


def test_report_references_only_model_tables():
    from spotify_pipeline.powerbi_report import referenced_old_entities

    assert referenced_old_entities(REPORT) <= set(powerbi.MODEL_TABLES)


def test_navigation_buttons_point_to_existing_pages():
    pages = {p.name for p in (REPORT / "pages").iterdir() if p.is_dir()}
    targets = []
    for _, v in _visuals():
        if v["visual"]["visualType"] == "actionButton":
            link = json.dumps(v["visual"].get("visualContainerObjects", {}).get("visualLink", []))
            targets += re.findall(r"'([0-9a-f]{20})'", link)
    assert targets and set(targets) <= pages


def test_every_referenced_image_is_packaged():
    resources = REPORT.parent / "StaticResources" / "RegisteredResources"
    text = "".join(f.read_text(encoding="utf-8") for f in REPORT.rglob("*.json"))
    images = set(re.findall(r'"ItemName": "([^"]+)"', text))
    assert images, "the design's background and icon images are missing"
    assert all((resources / name).exists() for name in images)


def test_design_pages_keep_their_backgrounds():
    with_background = [
        p
        for p in (REPORT / "pages").glob("*/page.json")
        if "Group_" in p.read_text(encoding="utf-8")
    ]
    assert len(with_background) == 3  # Overview, Artists, Songs (Home uses an image visual)


def test_base_theme_is_packaged():
    report = json.loads((REPORT / "report.json").read_text(encoding="utf-8"))
    name = report["themeCollection"]["baseTheme"]["name"]
    assert (
        REPORT.parent / "StaticResources" / "SharedResources" / "BaseThemes" / f"{name}.json"
    ).exists()


def test_model_has_no_ambiguous_filter_paths():
    """Power BI rejects models where a filter can reach a table by two routes."""
    edges = {}
    for rel in powerbi.RELATIONSHIPS:
        frm, _, to, _ = rel
        edges.setdefault(to, set()).add(frm)  # the one side filters the many side
        if rel in powerbi.BIDIRECTIONAL:
            edges.setdefault(frm, set()).add(to)

    def count_paths(node, target, seen):
        if node == target:
            return 1
        return sum(count_paths(n, target, seen | {n}) for n in edges.get(node, ()) if n not in seen)

    tables = set(powerbi.MODEL_TABLES)
    for a in tables:
        for b in tables - {a}:
            assert count_paths(a, b, {a}) <= 1, f"ambiguous filter paths {a} -> {b}"


def test_artist_selection_reaches_the_facts():
    """Clicking an artist must filter chart facts and track measures (via the bridge)."""
    edges = {}
    for rel in powerbi.RELATIONSHIPS:
        frm, _, to, _ = rel
        edges.setdefault(to, set()).add(frm)
        if rel in powerbi.BIDIRECTIONAL:
            edges.setdefault(frm, set()).add(to)
    reach, stack = set(), ["dim_artist"]
    while stack:
        for n in edges.get(stack.pop(), ()):
            if n not in reach:
                reach.add(n)
                stack.append(n)
    assert {"fact_chart_entry", "mart_track_performance", "dim_track"} <= reach
