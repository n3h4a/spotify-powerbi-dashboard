"""End-to-end test of the web dashboard: real browser, real clicks, numbers checked by SQL.

site/tests/e2e.cjs drives the dashboard in Chromium (every period, every artist page,
every song page, plus search, clicks and navigation) and reports every number it reads.
This test recomputes each of those numbers with independent SQL on the warehouse.
Skipped when Node.js and Playwright are not available.
"""

import functools
import http.server
import json
import os
import shutil
import subprocess
import threading

import pytest

from spotify_pipeline import web
from spotify_pipeline.config import PROJECT_ROOT

SITE = PROJECT_ROOT / "site"


def _node_with_playwright():
    node = shutil.which("node")
    if not node:
        return None
    env = dict(os.environ)
    root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    env["NODE_PATH"] = os.pathsep.join(
        p for p in [env.get("NODE_PATH", ""), root, str(SITE / "node_modules")] if p
    )
    ok = subprocess.run([node, "-e", "require('playwright')"], env=env, capture_output=True)
    return (node, env) if ok.returncode == 0 else None


@pytest.fixture(scope="module")
def browser_run(real_warehouse, tmp_path_factory):
    runner = _node_with_playwright()
    if runner is None:
        pytest.skip("Node.js with Playwright is not installed")
    con, settings = real_warehouse
    site = tmp_path_factory.mktemp("site")
    for name in ("index.html", "app.js", "style.css"):
        shutil.copy(SITE / name, site / name)
    shutil.copytree(SITE / "vendor", site / "vendor")
    for extra in ("insights.json", "model.json"):
        if (SITE / "data" / extra).exists():
            (site / "data").mkdir(exist_ok=True)
            shutil.copy(SITE / "data" / extra, site / "data" / extra)
    web.export(con, site, PROJECT_ROOT / "docs" / "figures")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.RequestHandlerClass.log_message = lambda *a: None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        node, env = runner
        proc = subprocess.run(
            [node, str(SITE / "tests" / "e2e.cjs"), f"http://127.0.0.1:{server.server_port}/"],
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
    finally:
        server.shutdown()
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1]), con


def num(text: str) -> float:
    """Parse a displayed number; displayed decimals are compared to exact SQL values within
    display precision (±0.05), so JS vs Python rounding of exact halves cannot differ."""
    return float(text.replace(",", "").replace("%", "").replace("#", "").replace(" d", ""))


def one(con, sql, *params):
    return con.execute(sql, params).fetchall()[0]


# --------------------------------------------------------------------------- overview


def _period_filter(period: str) -> str:
    if period == "all":
        return "TRUE"
    if "Q" in period:
        year, q = period.split("-Q")
        return f"year(f.chart_date) = {year} AND quarter(f.chart_date) = {q}"
    return f"year(f.chart_date) = {period}"


def test_overview_kpis_for_every_period(browser_run):
    out, con = browser_run
    assert len(out["overview"]) >= 9  # all time, 2 years, 7 quarters
    for period, shown in out["overview"].items():
        where = _period_filter(period)
        songs, pop, explicit, no1 = one(
            con,
            f"""
            SELECT count(DISTINCT f.track_key), avg(f.popularity),
                   avg(CASE WHEN v.is_explicit THEN 1.0 ELSE 0 END),
                   count(DISTINCT f.track_key) FILTER (WHERE f.chart_position = 1)
            FROM gold.fact_chart_entry f JOIN gold.dim_track_version v USING (track_version_key)
            WHERE {where}""",
        )
        (artists,) = one(
            con,
            f"""
            SELECT count(DISTINCT b.artist_key)
            FROM gold.fact_chart_entry f
            JOIN gold.bridge_track_artist b USING (track_key)
            JOIN gold.dim_artist a USING (artist_key)
            WHERE {where} AND a.artist_name <> 'Various Artists'""",
        )
        assert num(shown["kpi-songs"]) == songs, period
        assert num(shown["kpi-artists"]) == artists, period
        assert num(shown["kpi-popularity"]) == pytest.approx(pop, abs=0.0501), period
        assert num(shown["kpi-explicit"]) == pytest.approx(explicit * 100, abs=0.0501), period
        assert num(shown["kpi-no1"]) == no1, period


def test_known_all_time_headline_numbers(browser_run):
    out, _ = browser_run
    shown = out["overview"]["all"]
    assert shown == {
        "kpi-songs": "797",
        "kpi-artists": "345",
        "kpi-popularity": "89.6",
        "kpi-explicit": "40.2%",
        "kpi-no1": "37",
    }


# --------------------------------------------------------------------------- every artist


def test_every_artist_page_matches_sql(browser_run):
    out, con = browser_run
    expected = {
        r[0]: r[1:]
        for r in con.execute("""
            WITH total AS (SELECT count(*) AS n FROM gold.fact_chart_entry)
            SELECT a.artist_name,
                   count(DISTINCT f.track_key)                                  AS songs,
                   sum(b.attribution_weight) / (SELECT n FROM total)            AS share,
                   sum(b.attribution_weight)                                    AS weighted,
                   count(*) FILTER (WHERE f.chart_position = 1)                 AS no1,
                   min(f.chart_position)                                        AS best,
                   avg(f.popularity)                                            AS pop
            FROM gold.fact_chart_entry f
            JOIN gold.bridge_track_artist b USING (track_key)
            JOIN gold.dim_artist a USING (artist_key)
            WHERE a.artist_name <> 'Various Artists'
            GROUP BY a.artist_name""").fetchall()
    }
    assert len(out["artists"]) == len(expected) == 345
    for shown in out["artists"]:
        songs, share, weighted, no1, best, pop = expected[shown["artist-name"]]
        name = shown["artist-name"]
        assert num(shown["artist-songs"]) == songs, name
        assert num(shown["artist-share"]) == pytest.approx(share * 100, abs=0.0501), name
        assert num(shown["artist-days"]) == pytest.approx(weighted, abs=0.051), name
        assert num(shown["artist-no1"]) == no1, name
        assert num(shown["artist-best"]) == best, name
        assert num(shown["artist-pop"]) == pytest.approx(pop, abs=0.0501), name


# --------------------------------------------------------------------------- every song


def test_every_song_page_matches_sql(browser_run):
    out, con = browser_run
    expected = {
        r[0]: r[1:]
        for r in con.execute("""
            SELECT t.track_label, year(m.release_date), m.total_chart_days, m.peak_position,
                   m.debut_position, m.days_at_no1, m.days_in_top10, m.longest_streak_days
            FROM gold.dim_track t JOIN marts.mart_track_performance m USING (track_key)
        """).fetchall()
    }
    assert len(out["songs"]) == len(expected) == 797
    for shown in out["songs"]:
        year, days, peak, first, no1, top10, streak = expected[shown["song-title"]]
        title = shown["song-title"]
        assert int(shown["song-release"]) == year, title
        assert num(shown["song-days"]) == days, title
        assert num(shown["song-peak"]) == peak, title
        assert num(shown["song-first"]) == first, title
        assert num(shown["song-no1"]) == no1, title
        assert num(shown["song-top10"]) == top10, title
        assert num(shown["song-streak"]) == streak, title


# --------------------------------------------------------------------------- interactions


def test_search_and_click_interactions(browser_run):
    out, con = browser_run
    i = out["interactions"]
    assert i["artistSearch"] == {
        "artist-name": "Sabrina Carpenter",
        "artist-songs": "14",
        "artist-no1": "51",
    }
    assert i["coverClick"]["song-title"] == "Espresso"  # her longest-charting song
    assert i["songSearch"]["song-title"] == "Espresso"
    assert (
        i["songSearch"]["song-days"],
        i["songSearch"]["song-peak"],
        i["songSearch"]["song-no1"],
        i["songSearch"]["song-release"],
    ) == ("226", "#1", "31", "2024")
    assert i["songToArtist"]["artist-name"] == "Sabrina Carpenter"
    assert i["watchlist"]["row"] == i["watchlist"]["opened"]
    assert i["insightImages"] and all(i["insightImages"])
    assert i["tabs"] == ["overview", "artists", "songs", "insights", "predictions"]


def test_period_filter_changes_the_artist_page(browser_run):
    out, con = browser_run
    shown = out["interactions"]["artist2023"]
    name, songs, share = one(
        con,
        """
        WITH f AS (SELECT * FROM gold.fact_chart_entry WHERE year(chart_date) = 2023)
        SELECT a.artist_name, count(DISTINCT f.track_key),
               sum(b.attribution_weight) / (SELECT count(*) FROM f)
        FROM f JOIN gold.bridge_track_artist b USING (track_key)
        JOIN gold.dim_artist a USING (artist_key)
        WHERE a.artist_name <> 'Various Artists'
        GROUP BY a.artist_name ORDER BY sum(b.attribution_weight) DESC LIMIT 1""",
    )
    assert shown["artist-name"] == name
    assert num(shown["artist-songs"]) == songs
    assert num(shown["artist-share"]) == pytest.approx(share * 100, abs=0.0501)


def test_no_javascript_errors(browser_run):
    out, _ = browser_run
    assert out["errors"] == []
