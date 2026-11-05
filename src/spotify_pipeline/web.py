"""Export the warehouse for the web dashboard (site/).

Writes site/data/dashboard.json: one compact, self-contained file with every track,
artist and daily chart entry the dashboard needs. The page computes all of its numbers
from this file in the browser, using the same definitions as the Power BI measures, and
the end-to-end tests check those numbers against the warehouse independently.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import duckdb

ALBUM_TYPES = ["album", "single", "compilation"]


def _rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    rel = con.execute(sql)
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r, strict=True)) for r in rel.fetchall()]


def build_payload(con: duckdb.DuckDBPyConnection) -> dict:
    dates = [
        d
        for (d,) in con.execute(
            "SELECT DISTINCT chart_date FROM gold.fact_chart_entry ORDER BY 1"
        ).fetchall()
    ]
    day_index = {d: i for i, d in enumerate(dates)}

    tracks = _rows(
        con,
        """
        SELECT t.track_key, t.track_label, t.track_title, t.lead_artist_name, t.chart_rank,
               m.total_chart_days, m.peak_position, m.debut_position, m.debut_date,
               m.last_chart_date, m.release_date, m.release_date_precision,
               m.debut_is_explicit, m.debut_album_type, m.days_at_no1, m.days_in_top10,
               m.longest_streak_days, m.n_reentries, m.chart_life_bucket, m.peaked_on_debut,
               m.is_left_censored, m.is_right_censored, m.is_holiday_track,
               m.release_age_at_debut, m.album_cover_url
        FROM gold.dim_track AS t
        JOIN marts.mart_track_performance AS m USING (track_key)
        ORDER BY t.chart_rank
    """,
    )
    track_index = {t["track_key"]: i for i, t in enumerate(tracks)}

    artists = _rows(
        con,
        """
        SELECT a.artist_key, a.artist_name, p.artist_rank, p.n_tracks, p.weighted_chart_days,
               p.share_of_chart, p.days_at_no1, p.best_position
        FROM gold.dim_artist AS a
        JOIN marts.mart_artist_performance AS p USING (artist_key)
        ORDER BY p.artist_rank, a.artist_name
    """,
    )
    credits = _rows(
        con,
        """
        SELECT b.artist_key, b.track_key, b.attribution_weight, b.is_lead_artist
        FROM gold.bridge_track_artist AS b
        ORDER BY b.track_key, b.credit_order  -- deterministic output for CI diff checks
    """,
    )
    by_artist: dict[str, list] = {}
    track_artists: dict[str, list] = {}
    for c in credits:
        by_artist.setdefault(c["artist_key"], []).append(
            [track_index[c["track_key"]], round(c["attribution_weight"], 6)]
        )
        track_artists.setdefault(c["track_key"], []).append(c)

    artist_index = {a["artist_key"]: i for i, a in enumerate(artists)}

    # Entries: per track, flat [day, position, popularity, explicit, album_type] tuples.
    entries: list[list[int]] = [[] for _ in tracks]
    for d, pos, key, pop, explicit, album in con.execute("""
        SELECT f.chart_date, f.chart_position, f.track_key, f.popularity, v.is_explicit,
               v.album_type
        FROM gold.fact_chart_entry AS f
        JOIN gold.dim_track_version AS v USING (track_version_key)
        ORDER BY f.track_key, f.chart_date
    """).fetchall():
        entries[track_index[key]] += [
            day_index[d],
            pos,
            pop,
            int(explicit),
            ALBUM_TYPES.index(album),
        ]

    versions: list[list] = [[] for _ in tracks]
    for v in _rows(
        con,
        """
        SELECT track_key, version_number, valid_from, valid_to, is_current, album_type,
               album_total_tracks, artist_credit, is_explicit, duration_ms, release_date
        FROM gold.dim_track_version ORDER BY track_key, version_number
    """,
    ):
        versions[track_index[v["track_key"]]].append(
            [
                v["version_number"],
                str(v["valid_from"]),
                None if v["is_current"] else str(v["valid_to"]),  # None = still current
                v["album_type"],
                v["album_total_tracks"],
                v["artist_credit"],
                int(v["is_explicit"]),
                v["duration_ms"],
                str(v["release_date"]),
            ]
        )

    daily = _rows(
        con,
        """
        SELECT chart_date, artist_hhi, holiday_track_share, turnover_rate, avg_popularity,
               n_debuts, n_reentries
        FROM marts.mart_daily_chart ORDER BY chart_date
    """,
    )
    number_one = dict(
        con.execute(
            "SELECT chart_date, track_key FROM gold.fact_chart_entry WHERE chart_position = 1"
        ).fetchall()
    )

    return {
        "meta": {
            "first_date": str(dates[0]),
            "last_date": str(dates[-1]),
            "n_snapshots": len(dates),
            "n_entries": sum(len(e) // 5 for e in entries),
            "album_types": ALBUM_TYPES,
            "source": "Spotify Global Top 50 daily snapshots, modelled by spotify-pipeline",
        },
        "dates": [str(d) for d in dates],
        "tracks": [
            {
                "label": t["track_label"],
                "title": t["track_title"],
                "artist": t["lead_artist_name"],
                "rank": t["chart_rank"],
                "days": t["total_chart_days"],
                "peak": t["peak_position"],
                "first_pos": t["debut_position"],
                "first_date": str(t["debut_date"]),
                "last_date": str(t["last_chart_date"]),
                "release": str(t["release_date"]),
                "release_precision": t["release_date_precision"],
                "explicit": bool(t["debut_is_explicit"]),
                "album": t["debut_album_type"],
                "no1": t["days_at_no1"],
                "top10": t["days_in_top10"],
                "streak": t["longest_streak_days"],
                "reentries": t["n_reentries"],
                "bucket": t["chart_life_bucket"],
                "peaked_on_debut": bool(t["peaked_on_debut"]),
                "left_censored": bool(t["is_left_censored"]),
                "right_censored": bool(t["is_right_censored"]),
                "holiday": bool(t["is_holiday_track"]),
                "release_age": t["release_age_at_debut"],
                "cover": t["album_cover_url"],
                "artists": [
                    artist_index[c["artist_key"]]
                    for c in sorted(
                        track_artists[t["track_key"]], key=lambda c: not c["is_lead_artist"]
                    )
                ],
            }
            for t in tracks
        ],
        "artists": [
            {
                "name": a["artist_name"],
                "rank": a["artist_rank"],
                "placeholder": a["artist_name"] == "Various Artists",
                "tracks": by_artist.get(a["artist_key"], []),
                "weighted": round(a["weighted_chart_days"], 2),
                "share": a["share_of_chart"],
                "no1": a["days_at_no1"],
                "best": a["best_position"],
            }
            for a in artists
        ],
        "entries": entries,
        "versions": versions,
        "daily": {
            "hhi": [d["artist_hhi"] for d in daily],
            "holiday": [d["holiday_track_share"] for d in daily],
            "turnover": [d["turnover_rate"] for d in daily],
            "avg_pop": [d["avg_popularity"] for d in daily],
            "debuts": [d["n_debuts"] for d in daily],
            "no1": [track_index[number_one[d]] for d in dates],
        },
    }


def export(con: duckdb.DuckDBPyConnection, site_dir: Path, figures: Path | None = None) -> Path:
    """Write site/data/dashboard.json and copy the analysis figures into site/figures."""
    if figures is not None and figures.exists():
        out = site_dir / "figures"
        out.mkdir(parents=True, exist_ok=True)
        for png in sorted(figures.glob("*.png")):
            shutil.copyfile(png, out / png.name)
    target = site_dir / "data" / "dashboard.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload(con)
    target.write_text(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8"
    )
    return target
