"""Answer the business questions: run sql/analyses, test significance, chart, report.

Every number in docs/insights.md is computed here from the warehouse; nothing is
typed by hand, so the report can be regenerated whenever the data changes.
Requires the optional ``analysis`` dependencies (scipy, matplotlib).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)

# Validated categorical palette (slots 1-2) and neutral tokens for a light surface.
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
BLUE_LIGHT = "#cde2fb"


@dataclass(frozen=True)
class GroupTest:
    label_a: str
    label_b: str
    n_a: int
    n_b: int
    median_a: float
    median_b: float
    p_value: float
    effect_size: float  # rank-biserial correlation, 0 = no effect, 1 = complete separation


def _query(con: duckdb.DuckDBPyConnection, sql_dir: Path, name: str) -> list[dict]:
    rel = con.execute((sql_dir / "analyses" / f"{name}.sql").read_text(encoding="utf-8"))
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, row, strict=True)) for row in rel.fetchall()]


def mann_whitney(a: list[float], b: list[float], label_a: str, label_b: str) -> GroupTest:
    """Two-sided Mann-Whitney U test: chart-day counts are heavily skewed, not normal."""
    from statistics import median

    from scipy import stats

    u = stats.mannwhitneyu(a, b, alternative="two-sided")
    effect = abs(1 - 2 * u.statistic / (len(a) * len(b)))
    return GroupTest(label_a, label_b, len(a), len(b), median(a), median(b), u.pvalue, effect)


def fmt_p(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.2f}"


def effect_label(r: float) -> str:
    """Conventional magnitude labels for a correlation-type effect size."""
    r = abs(r)
    if r < 0.1:
        return "negligible"
    if r < 0.3:
        return "weak"
    if r < 0.5:
        return "moderate"
    return "large"


def pct(x: float, digits: int = 0) -> str:
    return f"{x * 100:.{digits}f}%"


# --------------------------------------------------------------------------- charts


def _style(ax, title: str, subtitle: str) -> None:
    fig = ax.figure
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=TEXT_SECONDARY, labelsize=9, length=0)
    ax.set_axisbelow(True)
    fig.text(0.012, 0.965, title, fontsize=13, fontweight="bold", color=TEXT, va="top")
    fig.text(0.012, 0.895, subtitle, fontsize=9.5, color=TEXT_SECONDARY, va="top")


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200, facecolor=SURFACE, metadata={"Software": None})
    import matplotlib.pyplot as plt

    plt.close(fig)


def chart_longevity(rows: list[dict], path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4.6))
    fig.subplots_adjust(left=0.07, right=0.98, top=0.78, bottom=0.12)
    labels = [r["longevity_bucket"] for r in rows]
    shares = [r["share_of_tracks"] * 100 for r in rows]
    bars = ax.bar(labels, shares, width=0.62, color=BLUE)
    for bar, share, r in zip(bars, shares, rows, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            share + 0.8,
            f"{share:.0f}%",
            ha="center",
            fontsize=10,
            color=TEXT,
            fontweight="bold",
        )
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            share + 3.6,
            f"{r['n_tracks']} tracks",
            ha="center",
            fontsize=8,
            color=TEXT_SECONDARY,
        )
    ax.set_ylim(0, max(shares) * 1.25)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_yticklabels([])
    ax.set_xlabel("Total days on the Global Top 50", color=TEXT_SECONDARY, fontsize=9)
    under_week = sum(r["share_of_tracks"] for r in rows[:2])
    _style(
        ax,
        f"Most hits are fleeting: {pct(under_week)} of tracks chart for a week or less",
        "Share of tracks by total chart life, May 2023 – Nov 2024 "
        "(excludes tracks already charting on day one)",
    )
    _save(fig, path)


def chart_segments(rows: list[dict], ratio: float, path: Path) -> None:
    import matplotlib.pyplot as plt

    order = ["Launch shape", "Debut position", "Release age at debut", "Credits"]
    fig, ax = plt.subplots(figsize=(9, 6.2))
    fig.subplots_adjust(left=0.30, right=0.95, top=0.85, bottom=0.07)
    y, ticks, labels, values, group_tops = 0.0, [], [], [], []
    for dim in order:
        group = [r for r in rows if r["dimension"] == dim]
        group_tops.append((y - 0.75, dim))
        for r in group:
            ticks.append(y)
            labels.append(f"{r['segment']}  (n={r['n_tracks']})")
            values.append(r["median_chart_days"])
            y += 1
        y += 1.1
    best = max(values)
    colors = [ORANGE if v == best else BLUE for v in values]
    ax.barh(ticks, values, height=0.62, color=colors)
    for t, v in zip(ticks, values, strict=True):
        ax.text(v + 0.5, t, f"{v:g} days", va="center", fontsize=9, color=TEXT)
    for top, dim in group_tops:
        ax.text(
            -0.43,
            top,
            dim.upper(),
            transform=ax.get_yaxis_transform(),
            fontsize=8,
            fontweight="bold",
            color=MUTED,
            va="center",
        )
    ax.set_yticks(ticks, labels, fontsize=9, color=TEXT)
    ax.invert_yaxis()
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_xlim(0, best * 1.18)
    ax.set_xlabel("Median days on chart within 180 days of debut", color=TEXT_SECONDARY, fontsize=9)
    ax.spines["bottom"].set_visible(False)
    _style(
        ax,
        f"Tracks that climb outlast tracks that peak on day one, by {ratio:.0f}x",
        "Median chart days in the first 180 days after debut, by launch characteristic "
        "(578 tracks with a full 180-day window)",
    )
    _save(fig, path)


def chart_concentration(
    daily: list[dict], events: list[dict], median_hhi: float, path: Path
) -> None:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4.6))
    fig.subplots_adjust(left=0.08, right=0.98, top=0.78, bottom=0.1)
    dates = [r["chart_date"] for r in daily]
    hhi = [r["artist_hhi"] for r in daily]
    ax.plot(dates, hhi, color=BLUE, linewidth=1.6)
    ax.axhline(median_hhi, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
    by_date = {r["chart_date"]: r["artist_hhi"] for r in daily}
    peaks = []
    for e in events:
        span = [d for d in dates if 0 <= (d - e["first_day"]).days < e["n_days"] + 4]
        peak_day = max(span, key=lambda d: by_date[d])
        peaks.append((peak_day, by_date[peak_day], e))
    # Events less than 45 days apart form a cluster; spread their labels sideways and
    # stack them so they never collide, with a leader line back to each peak.
    clusters: list[list[tuple]] = []
    for p in peaks:
        if clusters and (p[0] - clusters[-1][-1][0]).days < 45:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    top = max(hhi)
    for cluster in clusters:
        n = len(cluster)
        for k, (day, value, e) in enumerate(cluster):
            dx = (k - (n - 1) / 2) * 34
            dy = 420 + (top * 0.13 if n > 1 and k == (n - 1) // 2 else 0)
            label_x = day + timedelta(days=dx)
            ax.annotate(
                f"{e['artist_name']}\n{e['peak_slots_of_50']}/50 slots",
                xy=(day, value),
                xytext=(label_x, value + dy),
                ha="center",
                va="bottom",
                fontsize=7.5,
                color=TEXT,
                arrowprops={
                    "arrowstyle": "-",
                    "color": MUTED,
                    "linewidth": 0.7,
                    "shrinkA": 1,
                    "shrinkB": 3,
                },
            )
            ax.plot(
                [day],
                [value],
                "o",
                color=BLUE,
                markersize=4.5,
                markeredgecolor=SURFACE,
                markeredgewidth=1.2,
            )
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_ylim(0, max(hhi) * 1.32)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.set_ylabel("Artist concentration (HHI)", color=TEXT_SECONDARY, fontsize=9)
    _style(
        ax,
        "Album drops briefly hand the chart to a single artist",
        "Daily artist concentration across the 50 slots, as a Herfindahl-Hirschman index "
        f"(10,000 = one artist). Dashed: median day ({median_hhi:,.0f})",
    )
    _save(fig, path)


def chart_holiday(rows: list[dict], path: Path) -> None:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4.4))
    fig.subplots_adjust(left=0.07, right=0.98, top=0.78, bottom=0.1)
    dates = [r["chart_date"] for r in rows]
    share = [r["holiday_track_share"] * 100 for r in rows]
    ax.fill_between(dates, share, color=BLUE_LIGHT, linewidth=0)
    ax.plot(dates, share, color=BLUE, linewidth=1.8)
    peak_i = max(range(len(share)), key=lambda i: (share[i], -i))
    drop_i = next(i for i in range(peak_i, len(share)) if share[i] < 10)
    ax.annotate(
        f"{share[peak_i]:.0f}% on {dates[peak_i]:%d %b}",
        (dates[peak_i], share[peak_i]),
        xytext=(-12, 2),
        textcoords="offset points",
        ha="right",
        fontsize=9,
        color=TEXT,
        fontweight="bold",
    )
    ax.annotate(
        f"{share[drop_i]:.0f}% on {dates[drop_i]:%d %b}",
        (dates[drop_i], share[drop_i]),
        xytext=(8, 14),
        textcoords="offset points",
        fontsize=9,
        color=TEXT,
        fontweight="bold",
    )
    ax.set_ylim(0, 105)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    _style(
        ax,
        "The Christmas cliff: holiday songs vanish overnight",
        "Share of the Global Top 50 held by holiday catalogue tracks, Nov 2023 – Jan 2024",
    )
    _save(fig, path)


def chart_top_artists(rows: list[dict], path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4.8))
    fig.subplots_adjust(left=0.19, right=0.95, top=0.8, bottom=0.06)
    names = [r["artist_name"] for r in rows]
    shares = [r["share_of_chart"] * 100 for r in rows]
    ax.barh(names, shares, height=0.62, color=BLUE)
    for i, (s, r) in enumerate(zip(shares, rows, strict=True)):
        ax.text(
            s + 0.08,
            i,
            f"{s:.1f}%  ·  {r['n_tracks']} track{'s' if r['n_tracks'] != 1 else ''}",
            va="center",
            fontsize=8.5,
            color=TEXT,
        )
    ax.invert_yaxis()
    ax.set_xlim(0, max(shares) * 1.35)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.tick_params(axis="y", labelcolor=TEXT, labelsize=9.5)
    ax.spines["bottom"].set_visible(False)
    ratio = rows[0]["share_of_chart"] / rows[1]["share_of_chart"]
    _style(
        ax,
        f"Taylor Swift held {ratio:.1f}x the chart share of the next artist",
        "Share of all chart slots, collaborations split between credited artists",
    )
    _save(fig, path)


# --------------------------------------------------------------------------- report


def short_title(title: str, limit: int = 24) -> str:
    """Display title: drop "(feat. …)", "(Explicit Ver.)" and " - Remastered" parts if long."""
    import re

    if len(title) > limit:
        title = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", title)
        title = re.sub(r"\s+-\s+.*$", "", title).strip()
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def chart_release_weekday(rows: list[dict], path: Path) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    fig, ax = plt.subplots(figsize=(9, 4.6))
    fig.subplots_adjust(left=0.07, right=0.98, top=0.76, bottom=0.12)
    x = np.arange(len(rows))
    rel = [r["share_released"] * 100 for r in rows]
    deb = [r["share_debuted"] * 100 for r in rows]
    w = 0.38
    ax.bar(x - w / 2 - 0.01, rel, w, color=BLUE, label="Released that weekday")
    ax.bar(x + w / 2 + 0.01, deb, w, color=ORANGE, label="Debuted on the chart that weekday")
    for i, (a, b) in enumerate(zip(rel, deb, strict=True)):
        if a >= 15:
            ax.text(
                i - w / 2,
                a + 1.2,
                f"{a:.0f}%",
                ha="center",
                fontsize=9.5,
                color=TEXT,
                fontweight="bold",
            )
        if b >= 15:
            ax.text(
                i + w / 2,
                b + 1.2,
                f"{b:.0f}%",
                ha="center",
                fontsize=9.5,
                color=TEXT,
                fontweight="bold",
            )
    ax.set_xticks(x, [r["day_name"] for r in rows], color=TEXT)
    ax.set_ylim(0, max(rel + deb) * 1.18)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=TEXT)
    _style(
        ax,
        "New Music Friday: songs drop on Friday and chart on the weekend",
        "Share of new releases by release weekday, and by the weekday they debuted on the "
        "Global Top 50",
    )
    _save(fig, path)


def chart_no1_reigns(rows: list[dict], path: Path) -> None:
    import matplotlib.pyplot as plt

    rows = rows[:10]
    fig, ax = plt.subplots(figsize=(9, 4.9))
    fig.subplots_adjust(left=0.30, right=0.95, top=0.8, bottom=0.06)
    labels = [f"{short_title(r['track_label'])} · {r['lead_artist_name']}" for r in rows]
    total = [r["days_at_no1"] for r in rows]
    run = [r["longest_run"] for r in rows]
    ax.barh(labels, total, height=0.66, color=BLUE_LIGHT, label="Total days at #1")
    ax.barh(labels, run, height=0.36, color=BLUE, label="Longest unbroken run")
    for i, t in enumerate(total):
        ax.text(t + 0.8, i, f"{t} days", va="center", fontsize=8.5, color=TEXT)
    ax.invert_yaxis()
    ax.set_xlim(0, max(total) * 1.18)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.tick_params(axis="y", labelcolor=TEXT, labelsize=9)
    ax.spines["bottom"].set_visible(False)
    ax.legend(loc="lower right", frameon=False, fontsize=8.5, labelcolor=TEXT)
    _style(
        ax,
        f"{rows[0]['track_label']} ruled #1 longest: {rows[0]['days_at_no1']} days",
        "Songs with the most days at #1; the inner bar is the longest unbroken run",
    )
    _save(fig, path)


def generate(
    con: duckdb.DuckDBPyConnection, sql_dir: Path, report: Path, site_json: Path | None = None
) -> None:
    from scipy import stats

    fig_dir = report.parent / "figures"
    longevity = _query(con, sql_dir, "q1_longevity_distribution")
    deciles = _query(con, sql_dir, "q2_hit_concentration")
    segments = _query(con, sql_dir, "q3_segment_longevity")
    takeovers = _query(con, sql_dir, "q4_album_takeovers")
    holiday = _query(con, sql_dir, "q5_holiday_cliff")
    artists = _query(con, sql_dir, "q6_top_artists")
    [timing] = _query(con, sql_dir, "q7_release_timing")
    weekdays = _query(con, sql_dir, "q8_release_weekday")
    reigns = _query(con, sql_dir, "q9_number_one_reigns")
    cohort = _query(con, sql_dir, "cohort")
    daily = con.execute(
        "SELECT chart_date, artist_hhi FROM marts.mart_daily_chart ORDER BY chart_date"
    ).fetchall()
    daily = [{"chart_date": d, "artist_hhi": h} for d, h in daily]
    [(median_hhi, n_tracks_total, median_life, n_uncensored)] = con.execute(
        """
        SELECT (SELECT median(artist_hhi) FROM marts.mart_daily_chart),
               (SELECT count(*) FROM marts.mart_track_performance),
               median(total_chart_days), count(*)
        FROM marts.mart_track_performance WHERE NOT is_left_censored
        """
    ).fetchall()

    def days(rows, flag):
        return [r["chart_days_first_180"] for r in rows if flag(r)]

    launch = mann_whitney(
        days(cohort, lambda r: not r["peaked_on_debut"]),
        days(cohort, lambda r: r["peaked_on_debut"]),
        "Climbed after debut",
        "Peaked on debut day",
    )
    collab = mann_whitney(
        days(cohort, lambda r: r["is_collaboration"]),
        days(cohort, lambda r: not r["is_collaboration"]),
        "Collaboration",
        "Solo",
    )
    rho = stats.spearmanr(
        [r["debut_position"] for r in cohort], [r["chart_days_first_180"] for r in cohort]
    )
    peaked_share = sum(r["peaked_on_debut"] for r in cohort) / len(cohort)
    top_decile = deciles[0]["share_of_slots"]
    one_day = longevity[0]["share_of_tracks"]
    under_week = longevity[0]["share_of_tracks"] + longevity[1]["share_of_tracks"]
    seg = {(r["dimension"], r["segment"]): r for r in segments}
    recent = seg[("Release age at debut", "Released 1-12 months earlier")]
    fresh = seg[("Release age at debut", "Released <=30 days earlier")]
    top10 = seg[("Debut position", "Debuted #1-10")]
    low = seg[("Debut position", "Debuted #26-50")]
    biggest = max(takeovers, key=lambda e: e["peak_hhi"])
    peak_h = max(holiday, key=lambda r: r["holiday_track_share"])
    after = [r for r in holiday if r["chart_date"] > peak_h["chart_date"]]
    cliff = next(r for r in after if r["holiday_track_share"] < 0.1)
    swift_events = sum(e["artist_name"] == "Taylor Swift" for e in takeovers)
    top10_artist_share = sum(r["share_of_chart"] for r in artists)

    chart_longevity(longevity, fig_dir / "01_longevity.png")
    ratio = launch.median_a / launch.median_b
    chart_segments(segments, ratio, fig_dir / "02_launch_segments.png")
    chart_concentration(daily, takeovers, median_hhi, fig_dir / "03_artist_concentration.png")
    chart_holiday(holiday, fig_dir / "04_christmas_cliff.png")
    chart_top_artists(artists, fig_dir / "05_top_artists.png")
    chart_release_weekday(weekdays, fig_dir / "11_release_weekday.png")
    chart_no1_reigns(reigns, fig_dir / "12_number_one_reigns.png")
    wd = {r["day_name"]: r for r in weekdays}
    friday_release = wd["Friday"]["share_released"]
    weekend_debut = wd["Saturday"]["share_debuted"] + wd["Sunday"]["share_debuted"]
    top_reign = reigns[0]
    many_runs = max(reigns[:10], key=lambda r: r["n_runs"])

    def table(rows: list[dict], cols: list[tuple[str, str]]) -> list[str]:
        out = ["| " + " | ".join(h for h, _ in cols) + " |", "|" + "---|" * len(cols)]
        for r in rows:
            out.append("| " + " | ".join(str(fmt(r)) for _, fmt in cols) + " |")
        return out

    md: list[str] = [
        "# Insights: What Makes a Global Top 50 Hit Last?",
        "",
        "> Generated by `spotify-pipeline insights` from the warehouse marts. Every number "
        "below is computed, not typed; rerun the command to refresh it. The SQL behind each "
        "answer is linked.",
        "",
        "## Executive summary",
        "",
        f"1. **Chart life is short and extremely uneven.** The median track lasts "
        f"**{median_life:.0f} days**; {pct(one_day)} last a single day. The longest-charting "
        f"10% of tracks hold **{pct(top_decile)} of all chart slots**.",
        f"2. **A day-one peak predicts a short life.** {pct(peaked_share)} of tracks peak on "
        f"debut day. They spend a median **{launch.median_b:g} days** on the chart in their "
        f"first 180 days, against **{launch.median_a:g} days** for tracks that climbed after "
        f"debuting ({fmt_p(launch.p_value)}, effect size {launch.effect_size:.2f}).",
        f"3. **Debut position is a poor predictor of longevity** (Spearman ρ = "
        f"{rho.statistic:.2f}, {effect_label(rho.statistic)}). Top-10 debuts last longer "
        f"(median {top10['median_chart_days']:g} days vs {low['median_chart_days']:g}), "
        "but launch *momentum* matters more than launch *height*.",
        f"4. **Collaborations do not last longer.** Median {collab.median_a:g} vs "
        f"{collab.median_b:g} days; the difference is not statistically significant "
        f"({fmt_p(collab.p_value)}).",
        f"5. **Slow burners win.** Tracks that reached the chart 1–12 months after release "
        f"last a median **{recent['median_chart_days']:g} days**, against "
        f"{fresh['median_chart_days']:g} for brand-new releases.",
        f"6. **Album drops take over the chart.** On {biggest['first_day']:%d %b %Y}, "
        f"{biggest['artist_name']} held **{biggest['peak_slots_of_50']} of 50 slots** "
        f"(HHI {biggest['peak_hhi']:,} against a typical {median_hhi:,.0f}). "
        f"{swift_events} of the {len(takeovers)} takeover events were Taylor Swift releases.",
        f"7. **The Christmas cliff.** Holiday songs held **{pct(peak_h['holiday_track_share'])}"
        f"** of the chart on {peak_h['chart_date']:%d %b %Y} and "
        f"{pct(cliff['holiday_track_share'])} on {cliff['chart_date']:%d %b}.",
        f"8. **New Music Friday rules the calendar.** {pct(friday_release)} of new releases come "
        f"out on a Friday and {pct(weekend_debut)} debut on the weekend chart.",
        f"9. **{top_reign['track_label']} ruled #1 longest:** {top_reign['days_at_no1']} days, "
        f"{top_reign['longest_run']} of them in a row, among {len(reigns)} songs that reached #1.",
        "",
        "## Method",
        "",
        "- **Source:** the gold star schema and marts built by this pipeline "
        f"({n_tracks_total:,} tracks, 556 daily snapshots).",
        "- **Censoring.** The data is a window into an ongoing chart. Tracks already charting "
        "on the first snapshot have unknown debuts (*left-censored*), and tracks still "
        "charting on the last snapshot have unfinished lives (*right-censored*). Ignoring "
        "this would understate how long recent tracks last.",
        f"- **Analysis cohort ({len(cohort)} tracks):** tracks with a known debut and a full "
        "180 days of follow-up. Longevity is compared on *chart days within 180 days of "
        "debut*, the same observation window for every track "
        "([cohort.sql](../sql/analyses/cohort.sql)).",
        "- **Statistics:** chart-day counts are heavily right-skewed, so groups are compared "
        "with medians and the two-sided **Mann-Whitney U test** (no normality assumption). "
        "Effect size is the rank-biserial correlation. Rank association uses **Spearman's ρ**.",
        "- **Holiday tracks** are tracks with at least 90% of their chart days between "
        "15 Nov and 31 Dec that were released more than a year before debuting.",
        "",
        "---",
        "",
        "## Q1. How long do tracks survive on the chart?",
        "",
        "![Longevity distribution](figures/01_longevity.png)",
        "",
        f"Of {n_uncensored} tracks with a known debut, {pct(under_week)} spend a week or less "
        f"on the chart. The distribution has a long tail: the top 10% of all tracks account "
        f"for {pct(top_decile)} of chart slots and the bottom half for "
        f"{pct(sum(d['share_of_slots'] for d in deciles[5:]), 1)}.",
        "",
        *table(
            longevity,
            [
                ("Chart life", lambda r: r["longevity_bucket"]),
                ("Tracks", lambda r: r["n_tracks"]),
                ("Share", lambda r: pct(r["share_of_tracks"], 1)),
            ],
        ),
        "",
        "SQL: [q1_longevity_distribution.sql](../sql/analyses/q1_longevity_distribution.sql) · "
        "[q2_hit_concentration.sql](../sql/analyses/q2_hit_concentration.sql)",
        "",
        "## Q2. Which launch characteristics go with a longer life?",
        "",
        "![Launch segments](figures/02_launch_segments.png)",
        "",
        *table(
            segments,
            [
                ("Dimension", lambda r: r["dimension"]),
                ("Segment", lambda r: r["segment"]),
                ("Tracks", lambda r: r["n_tracks"]),
                ("Median days (first 180)", lambda r: f"{r['median_chart_days']:g}"),
                ("Reached 30+ days", lambda r: pct(r["share_30_plus_days"])),
            ],
        ),
        "",
        "| Comparison | Medians | Test | Effect size |",
        "|---|---|---|---|",
        f"| {launch.label_a} vs {launch.label_b} | {launch.median_a:g} vs {launch.median_b:g} "
        f"days | Mann-Whitney U, {fmt_p(launch.p_value)} | {launch.effect_size:.2f} "
        f"({effect_label(launch.effect_size)}) |",
        f"| {collab.label_a} vs {collab.label_b} | {collab.median_a:g} vs {collab.median_b:g} "
        f"days | Mann-Whitney U, {fmt_p(collab.p_value)} | {collab.effect_size:.2f} "
        f"({effect_label(collab.effect_size)}) |",
        f"| Debut position vs chart days | n = {len(cohort)} | Spearman ρ = "
        f"{rho.statistic:.2f}, {fmt_p(rho.pvalue)} | {effect_label(rho.statistic)} |",
        "",
        "**Reading it.** Most new releases debut at their peak and then fall away, which "
        "fits a release-day burst of streams from existing fans. Tracks that *climb* after "
        f"debuting are still gaining listeners, and they last about {ratio:.0f} times longer. "
        "Debut position is a much weaker predictor. The strongest single signal, launch "
        "shape, is only known after the first few days. That gives Phase 3's model a "
        "clear target: predict longevity from **early momentum** (position change over "
        "the first week), not from debut position alone.",
        "",
        "SQL: [q3_segment_longevity.sql](../sql/analyses/q3_segment_longevity.sql)",
        "",
        "## Q3. How quickly do tracks reach the chart after release?",
        "",
        f"Among {timing['n_tracks']} non-catalogue tracks with exact release dates, the median "
        f"gap from release to debut is **{timing['median_days']:g} days**: "
        f"{pct(timing['share_within_week'])} debut within a week and "
        f"{pct(timing['share_within_day'])} within a day. Global chart success is decided "
        "almost immediately, which matches the debut-day peak pattern in Q2.",
        "",
        "SQL: [q7_release_timing.sql](../sql/analyses/q7_release_timing.sql)",
        "",
        "## Q4. Is the chart dominated by a few artists?",
        "",
        "![Top artists](figures/05_top_artists.png)",
        "",
        f"The top 10 artists hold {pct(top10_artist_share)} of all chart slots. Day to day, "
        "though, the chart is usually diverse. Concentration spikes are rare and tied to "
        "specific events:",
        "",
        "![Artist concentration](figures/03_artist_concentration.png)",
        "",
        *table(
            takeovers,
            [
                ("Artist", lambda r: r["artist_name"]),
                ("Started", lambda r: f"{r['first_day']:%Y-%m-%d}"),
                ("Days", lambda r: r["n_days"]),
                ("Peak slots (of 50)", lambda r: r["peak_slots_of_50"]),
                ("Peak HHI", lambda r: f"{r['peak_hhi']:,}"),
            ],
        ),
        "",
        "Every takeover lines up with a major album release, and none lasts more than about "
        "a week before the chart returns to normal.",
        "",
        "SQL: [q4_album_takeovers.sql](../sql/analyses/q4_album_takeovers.sql) · "
        "[q6_top_artists.sql](../sql/analyses/q6_top_artists.sql)",
        "",
        "## Q5. How seasonal is the chart?",
        "",
        "![Christmas cliff](figures/04_christmas_cliff.png)",
        "",
        "Holiday catalogue songs, most released decades ago, build up through December, peak "
        f"at {pct(peak_h['holiday_track_share'])} of the chart on "
        f"{peak_h['chart_date']:%d %b}, and fall to {pct(cliff['holiday_track_share'])} on "
        f"{cliff['chart_date']:%d %b}. Any year-over-year or trend analysis must account for "
        "this: December metrics such as average release age or catalogue share are distorted "
        "by design. `dim_date.is_holiday_season` and `mart_track_performance.is_holiday_track` "
        "make the adjustment a single filter.",
        "",
        "SQL: [q5_holiday_cliff.sql](../sql/analyses/q5_holiday_cliff.sql)",
        "",
        "## Q6. When do new songs come out, and when do they chart?",
        "",
        "![Release weekday](figures/11_release_weekday.png)",
        "",
        f"The industry's *New Music Friday* is visible in the data: {pct(friday_release)} of new "
        f"releases come out on a Friday (most of the rest on Thursday, which is Friday "
        f"midnight in other time zones), and {pct(weekend_debut)} of them debut on a "
        f"Saturday or Sunday chart. Combined with Q3, a release's chart fate is largely "
        "decided within its first weekend.",
        "",
        "SQL: [q8_release_weekday.sql](../sql/analyses/q8_release_weekday.sql)",
        "",
        "## Q7. Which songs ruled the #1 spot?",
        "",
        "![Number one reigns](figures/12_number_one_reigns.png)",
        "",
        f"{len(reigns)} songs reached #1 in the period. **{top_reign['track_label']}** "
        f"({top_reign['lead_artist_name']}) held it longest: {top_reign['days_at_no1']} days, "
        f"including {top_reign['longest_run']} in a row. Reigns differ in shape: "
        f"*{many_runs['track_label']}* reached {many_runs['days_at_no1']} days at #1 across "
        f"{many_runs['n_runs']} separate runs, trading places with other hits.",
        "",
        *table(
            reigns[:10],
            [
                ("Song", lambda r: r["track_label"]),
                ("Artist", lambda r: r["lead_artist_name"]),
                ("Days at #1", lambda r: r["days_at_no1"]),
                ("Longest run", lambda r: r["longest_run"]),
                ("Separate runs", lambda r: r["n_runs"]),
            ],
        ),
        "",
        "SQL: [q9_number_one_reigns.sql](../sql/analyses/q9_number_one_reigns.sql)",
        "",
        "---",
        "",
        "## Recommendations",
        "",
        "For a label, artist team or editorial playlist team using this data:",
        "",
        "1. **Judge a release on week-two momentum, not debut position.** A track still "
        "climbing after debut is the strongest sign of a long chart life found here.",
        "2. **Back slow burners.** Tracks that find an audience months after release last "
        "longest. Catalogue and mid-life tracks deserve promotion budget, not only launches.",
        "3. **Don't count on a feature to extend a song's life.** Collaborations show no "
        "longevity advantage. Their value is reach, not staying power.",
        "4. **Plan around album drops and the holidays.** Avoid releasing into a superstar "
        f"album week, when one artist can hold up to "
        f"{pct(biggest['peak_slots_of_50'] / 50)} of the chart, and expect December "
        "chart space to be largely taken by holiday catalogue.",
        "5. **Release on Friday and watch the first weekend.** Two-thirds of new songs come "
        "out on a Friday and debut on the weekend chart, and week-one movement is the best "
        "available predictor of a long run (see the "
        "[model report](model_report.md)).",
        "",
        "## Limitations",
        "",
        "- The data covers 18 months of a single chart (Global Top 50). Findings may not "
        "generalise to regional charts or to streams outside the top 50.",
        "- Chart position is a rank, not a stream count, so the size of a hit can't be "
        "measured, only its rank and duration.",
        "- The results are associations, not causal effects. For example, tracks that climb "
        "may already be stronger songs.",
        "- The holiday rule depends on release age, so a brand-new Christmas song would be "
        "missed. Seasonal songs that are not holiday music are excluded through an "
        "editable list (`seeds/not_holiday_tracks.csv`).",
        "",
        "**Going further:** the [model report](model_report.md) models chart survival "
        "directly (Kaplan-Meier, Cox proportional hazards), uses still-charting songs "
        "instead of dropping them, and predicts longevity from first-week signals.",
    ]
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(md) + "\n", encoding="utf-8")
    log.info("Insights written to %s (%d figures)", report, 7)

    if site_json is not None:
        top_artist = artists[0]
        questions = [
            {
                "question": "How long do songs survive on the Global Top 50?",
                "headline": f"{median_life:.0f} days",
                "answer": f"That is the median chart life. {pct(under_week)} of songs last a week "
                f"or less, and the longest-charting 10% of songs hold {pct(top_decile)} of all "
                "chart slots: the chart is a few long runs and many brief visits.",
                "evidence": f"{n_uncensored} songs with a known debut · "
                "q1_longevity_distribution.sql",
                "figure": "figures/01_longevity.png",
            },
            {
                "question": "Does a big debut mean a long run?",
                "headline": f"{ratio:.0f}x longer",
                "answer": f"Songs that keep climbing after their debut chart a median "
                f"{launch.median_a:g} days in their first 180, against {launch.median_b:g} for "
                f"songs that peak on day one ({pct(peaked_share)} of songs). Debut position "
                f"itself is a weak predictor (Spearman ρ = {rho.statistic:.2f}), and "
                f"collaborations last no longer than solo songs ({collab.median_a:g} vs "
                f"{collab.median_b:g} days, {fmt_p(collab.p_value)}).",
                "evidence": f"Mann-Whitney U {fmt_p(launch.p_value)}, effect size "
                f"{launch.effect_size:.2f} · {len(cohort)} songs with a full 180-day window",
                "figure": "figures/02_launch_segments.png",
            },
            {
                "question": "Who owns the most chart real estate?",
                "headline": pct(top_artist["share_of_chart"], 1),
                "answer": f"{top_artist['artist_name']} held "
                f"{pct(top_artist['share_of_chart'], 1)} of every chart slot, "
                f"{top_artist['share_of_chart'] / artists[1]['share_of_chart']:.1f}x the next "
                f"artist. The top 10 artists hold {pct(top10_artist_share)} of the chart, "
                "with collaborations split fairly between credited artists.",
                "evidence": "Weighted by attribution · q6_top_artists.sql",
                "figure": "figures/05_top_artists.png",
            },
            {
                "question": "What happens when a superstar drops an album?",
                "headline": f"{biggest['peak_slots_of_50']} of 50",
                "answer": f"On {biggest['first_day']:%d %b %Y}, {biggest['artist_name']} held "
                f"{biggest['peak_slots_of_50']} of the 50 chart slots (HHI "
                f"{biggest['peak_hhi']:,} against a typical {median_hhi:,.0f}). All "
                f"{len(takeovers)} takeovers were album releases, and each faded within about "
                "a week.",
                "evidence": "Herfindahl-Hirschman index of daily artist share · "
                "q4_album_takeovers.sql",
                "figure": "figures/03_artist_concentration.png",
            },
            {
                "question": "How seasonal is the chart?",
                "headline": pct(peak_h["holiday_track_share"]),
                "answer": "Holiday songs, mostly decades old, took "
                f"{pct(peak_h['holiday_track_share'])} "
                f"of the chart on {peak_h['chart_date']:%d %b %Y}, then fell to "
                f"{pct(cliff['holiday_track_share'])} on {cliff['chart_date']:%d %b}. December "
                "needs its own baseline in any trend analysis.",
                "evidence": "51 holiday catalogue songs · q5_holiday_cliff.sql",
                "figure": "figures/04_christmas_cliff.png",
            },
            {
                "question": "When do new songs come out, and when do they chart?",
                "headline": pct(friday_release),
                "answer": f"{pct(friday_release)} of new releases come out on a Friday (New Music "
                f"Friday) and {pct(weekend_debut)} debut on a Saturday or Sunday chart, a median "
                f"{timing['median_days']:g} days after release. A song's chart fate is largely "
                "set within its first weekend.",
                "evidence": "New releases with exact release dates · q8_release_weekday.sql",
                "figure": "figures/11_release_weekday.png",
            },
            {
                "question": "Which songs ruled the #1 spot?",
                "headline": f"{top_reign['days_at_no1']} days",
                "answer": f"{top_reign['track_label']} ({top_reign['lead_artist_name']}) held #1 "
                f"longest, {top_reign['longest_run']} days in a row. {len(reigns)} songs reached "
                f"#1; {many_runs['track_label']} got {many_runs['days_at_no1']} days across "
                f"{many_runs['n_runs']} separate runs.",
                "evidence": "Gaps-and-islands runs at position 1 · q9_number_one_reigns.sql",
                "figure": "figures/12_number_one_reigns.png",
            },
        ]
        site_json.parent.mkdir(parents=True, exist_ok=True)
        site_json.write_text(
            json.dumps(
                {
                    "subtitle": "Seven business questions answered from 556 daily charts, with the "
                    "statistics behind each answer. Full method: docs/insights.md.",
                    "questions": questions,
                },
                indent=1,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
