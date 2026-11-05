/* Global Top 50 Analytics: a static dashboard over the spotify-pipeline warehouse.
 *
 * Every number is computed in the browser from data/dashboard.json using the same
 * definitions as the Power BI measures (see docs/powerbi_guide.md):
 *   songs           distinct tracks with at least one chart entry in the period
 *   unique artists  distinct credited artists on those tracks ("Various Artists" excluded)
 *   avg popularity  mean Spotify popularity of the period's chart entries
 *   explicit share  share of chart entries whose version that day was explicit
 *   chart share     an artist's chart entries, split between collaborators by
 *                   attribution weight, over all chart entries in the period
 * tests/e2e checks the rendered numbers against the warehouse with independent SQL.
 */
"use strict";

const COLORS = {
  green: "#1aac4e", greenText: "#1db954", blue: "#3987e5", orange: "#d95926",
  text: "#f2f3f5", text2: "#b6b9c6", muted: "#7d8193", grid: "#262938", card: "#181a23",
};
const fmtInt = (n) => (n == null || Number.isNaN(n) ? "–" : Math.round(n).toLocaleString("en-US"));
const fmt1 = (n) => (n == null || Number.isNaN(n) ? "–" : n.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
const fmtDays = (n) => (Number.isInteger(+(+n).toFixed(1)) ? fmtInt(n) : fmt1(n));
const fmtPct = (x, d = 1) => (x == null || Number.isNaN(x) ? "–" : (x * 100).toFixed(d) + "%");
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const prettyDate = (iso) => { const [y, m, d] = iso.split("-"); return `${+d} ${MONTHS[+m - 1]} ${y}`; };
const prettyMonth = (ym) => { const [y, m] = ym.split("-"); return `${MONTHS[+m - 1]} ${y.slice(2)}`; };

const state = { data: null, extra: {}, period: "all", charts: [] };

/* ------------------------------------------------------------------ data model */

function prepare(data) {
  const D = data;
  D.monthOf = D.dates.map((d) => d.slice(0, 7));
  D.months = [...new Set(D.monthOf)];
  // per-artist weights by track, and per-track credit list with weights
  D.trackCredits = D.tracks.map(() => []);
  D.artists.forEach((a, ai) => a.tracks.forEach(([ti, w]) => D.trackCredits[ti].push([ai, w])));
  // dominant artist per day (for annotating concentration peaks)
  const slots = D.dates.map(() => new Map());
  D.entries.forEach((e, ti) => {
    for (let k = 0; k < e.length; k += 5) {
      const day = e[k];
      for (const [ai, w] of D.trackCredits[ti]) slots[day].set(ai, (slots[day].get(ai) || 0) + w);
    }
  });
  D.topArtistByDay = slots.map((m) => {
    let best = null, bestV = -1;
    m.forEach((v, ai) => { if (v > bestV) { bestV = v; best = ai; } });
    return [best, bestV];
  });
  return D;
}

function periods(D) {
  const out = [{ id: "all", label: `All time (${prettyMonth(D.months[0])} – ${prettyMonth(D.months.at(-1))})` }];
  for (const y of [...new Set(D.dates.map((d) => d.slice(0, 4)))]) out.push({ id: y, label: y });
  const qs = [...new Set(D.dates.map((d) => `${d.slice(0, 4)}-Q${Math.floor((+d.slice(5, 7) - 1) / 3) + 1}`))];
  for (const q of qs) out.push({ id: q, label: q.replace("-", " ") });
  return out;
}

function dayRange(D, period) {
  if (period === "all") return [0, D.dates.length - 1];
  const inP = (d) => (period.includes("Q")
    ? `${d.slice(0, 4)}-Q${Math.floor((+d.slice(5, 7) - 1) / 3) + 1}` === period
    : d.startsWith(period));
  const idx = D.dates.map((d, i) => (inP(d) ? i : -1)).filter((i) => i >= 0);
  return [idx[0], idx.at(-1)];
}

/** Aggregate chart entries in [lo, hi], optionally restricted to a set of tracks. */
function aggregate(D, lo, hi, trackFilter = null) {
  const res = { entries: 0, popSum: 0, explicit: 0, tracks: new Map(), no1: new Map(), best: 51,
    album: [0, 0, 0] };
  D.entries.forEach((e, ti) => {
    if (trackFilter && !trackFilter.has(ti)) return;
    for (let k = 0; k < e.length; k += 5) {
      const day = e[k];
      if (day < lo || day > hi) continue;
      const pos = e[k + 1];
      res.entries += 1; res.popSum += e[k + 2]; res.explicit += e[k + 3]; res.album[e[k + 4]] += 1;
      res.tracks.set(ti, (res.tracks.get(ti) || 0) + 1);
      if (pos === 1) res.no1.set(ti, (res.no1.get(ti) || 0) + 1);
      if (pos < res.best) res.best = pos;
    }
  });
  return res;
}

function artistStats(D, lo, hi) {
  const total = aggregate(D, lo, hi);
  const daysByTrack = total.tracks;
  return D.artists.map((a, ai) => {
    let weighted = 0, songs = 0, credited = 0, top = null, topDays = 0;
    for (const [ti, w] of a.tracks) {
      const n = daysByTrack.get(ti) || 0;
      if (n) { songs += 1; weighted += n * w; credited += n; }
      // biggest song in the period (ties: higher overall chart rank): its cover is the
      // artist's picture, since the chart data has album art but no artist photos
      if (n > topDays || (n === topDays && n && D.tracks[ti].rank < D.tracks[top].rank)) {
        top = ti; topDays = n;
      }
    }
    return { ai, name: a.name, placeholder: a.placeholder, songs, weighted, credited, top,
      share: total.entries ? weighted / total.entries : 0 };
  }).filter((s) => s.songs > 0).sort((x, y) => y.weighted - x.weighted || x.name.localeCompare(y.name));
}

/* ------------------------------------------------------------------ charts */

function baseOption(extra = {}) {
  return Object.assign({
    backgroundColor: "transparent",
    textStyle: { color: COLORS.text2, fontFamily: "Segoe UI, system-ui, sans-serif" },
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    tooltip: {
      backgroundColor: "#0d0f16", borderColor: "#2a2d3b", textStyle: { color: COLORS.text },
      confine: true,
    },
    animationDuration: 450,
  }, extra);
}
const axisCommon = {
  axisLine: { lineStyle: { color: COLORS.grid } },
  axisTick: { show: false },
  axisLabel: { color: COLORS.muted },
  splitLine: { lineStyle: { color: COLORS.grid } },
};

function chart(el, option, onClick) {
  const c = echarts.init(el, null, { renderer: "svg" });
  c.setOption(option);
  if (onClick) c.on("click", onClick);
  state.charts.push(c);
  return c;
}

function hbar(el, rows, { value, label, fmt = fmtInt, onClick, name = "" }) {
  const top = rows.slice().reverse();
  return chart(el, baseOption({
    grid: { left: 8, right: 56, top: 6, bottom: 6, containLabel: true },
    tooltip: { trigger: "item", formatter: (p) => `${esc(top[p.dataIndex].tip || label(top[p.dataIndex]))}<br><b>${fmt(p.value)}</b> ${esc(name)}` },
    xAxis: { type: "value", ...axisCommon, splitLine: { show: false }, axisLabel: { show: false } },
    yAxis: { type: "category", data: top.map(label), ...axisCommon,
      axisLabel: { color: COLORS.text2, width: 150, overflow: "truncate" } },
    series: [{ type: "bar", data: top.map(value), barWidth: "58%",
      itemStyle: { color: COLORS.green, borderRadius: [0, 4, 4, 0] },
      emphasis: { itemStyle: { color: COLORS.greenText } },
      label: { show: true, position: "right", color: COLORS.text, formatter: (p) => fmt(p.value) } }],
  }), onClick ? (p) => onClick(top[p.dataIndex]) : null);
}

/* ------------------------------------------------------------------ helpers */

function kpi(id, label, value, note = "") {
  return `<div class="card kpi"><div class="label">${esc(label)}</div>
    <div class="value" data-testid="${id}">${value}</div>${note ? `<div class="note">${esc(note)}</div>` : ""}</div>`;
}
function card(title, sub, body, cls = "") {
  return `<section class="card ${cls}"><h2>${esc(title)}</h2>${sub ? `<p class="sub">${esc(sub)}</p>` : ""}${body}</section>`;
}
/** Album cover, with a designed fallback tile if the image can't load. */
function cover(t, cls = "") {
  const tile = fallbackTile(t.label);
  if (!t.cover) return `<div class="${cls} tile" style="${tile}">${esc(initial(t.label))}</div>`;
  return `<img class="${cls}" src="${esc(t.cover)}" alt="" loading="lazy"
    data-fallback="${esc(initial(t.label))}" data-tile="${esc(tile)}" onerror="coverFailed(this)">`;
}
function initial(label) { return (label.match(/[A-Za-z0-9]/) || ["♪"])[0].toUpperCase(); }
function fallbackTile(label) {
  let h = 0;
  for (const ch of label) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `background:linear-gradient(135deg,hsl(${h} 45% 34%),hsl(${(h + 40) % 360} 55% 18%))`;
}
window.coverFailed = (img) => {
  const div = document.createElement("div");
  div.className = `${img.className} tile`;
  div.setAttribute("style", img.dataset.tile);
  div.textContent = img.dataset.fallback;
  img.replaceWith(div);
};
const go = (hash) => { location.hash = hash; };
function periodLabel() {
  return periods(state.data).find((p) => p.id === state.period).label;
}

/* ------------------------------------------------------------------ Overview */

function renderOverview(D, root) {
  const [lo, hi] = dayRange(D, state.period);
  const agg = aggregate(D, lo, hi);
  const artistsInPeriod = new Set();
  agg.tracks.forEach((_, ti) => D.trackCredits[ti].forEach(([ai]) => {
    if (!D.artists[ai].placeholder) artistsInPeriod.add(ai);
  }));
  const stats = artistStats(D, lo, hi);
  const runs = [...agg.tracks.entries()].sort((a, b) => b[1] - a[1] || D.tracks[a[0]].rank - D.tracks[b[0]].rank).slice(0, 10);
  const reigns = [...agg.no1.entries()].sort((a, b) => b[1] - a[1] || D.tracks[a[0]].rank - D.tracks[b[0]].rank).slice(0, 10);
  const buckets = ["1 day", "2-7 days", "8-30 days", "31-90 days", "91-180 days", "180+ days"];
  const bucketCounts = buckets.map((b) => [...agg.tracks.keys()].filter((ti) => D.tracks[ti].bucket === b).length);

  root.innerHTML = `
    <div class="page-head"><div>
      <h1>The Global Top 50 at a glance</h1>
      <p>${esc(periodLabel())}: ${fmtInt(hi - lo + 1)} daily charts and ${fmtInt(agg.entries)} chart entries.
      Click any artist or song to drill in.</p></div></div>
    <div class="kpis">
      ${kpi("kpi-songs", "Songs", fmtInt(agg.tracks.size), "distinct tracks that charted")}
      ${kpi("kpi-artists", "Unique artists", fmtInt(artistsInPeriod.size), "collaborations split")}
      ${kpi("kpi-popularity", "Avg popularity", fmt1(agg.popSum / agg.entries), "Spotify score, 0–100")}
      ${kpi("kpi-explicit", "Explicit share", fmtPct(agg.explicit / agg.entries), "of chart entries")}
      ${kpi("kpi-no1", "Songs that hit #1", fmtInt(agg.no1.size), `over ${fmtInt(hi - lo + 1)} days`)}
    </div>
    <div class="grid cols-12" style="margin-top:16px">
      ${card("Who dominates the chart, day by day", "Artist concentration (HHI, 0 = diverse, 10,000 = one artist). Spikes are album releases.",
        '<div class="chart" id="c-hhi"></div>', "span-8")}
      ${card("Top artists by chart share", "Share of all chart entries · collaborations split fairly",
        '<div class="chart" id="c-artists"></div>', "span-4")}
      ${card("Longest chart runs", "Days on the chart in this period", '<div class="chart" id="c-runs"></div>', "span-4")}
      ${card("Longest #1 reigns", "Days at #1 in this period", '<div class="chart" id="c-no1"></div>', "span-4")}
      ${card("How long songs last", "Songs charting in this period, by their total chart life", '<div class="chart" id="c-buckets"></div>', "span-4")}
      ${card("Albums vs singles, month by month", "Release type of each chart entry, as it was that day",
        '<div class="chart" id="c-album"></div>', "span-6")}
      ${card("New songs entering the chart", "Debuts and re-entries per day, monthly average (fair to partial months)", '<div class="chart" id="c-churn"></div>', "span-6")}
    </div>`;

  // concentration line with the three biggest takeovers annotated
  const days = D.dates.slice(lo, hi + 1);
  const hhi = D.daily.hhi.slice(lo, hi + 1);
  const peaks = [];
  const order = hhi.map((v, i) => [v, i]).sort((a, b) => b[0] - a[0]);
  for (const [v, i] of order) {
    if (peaks.length === 3) break;
    if (v < 1500) break;
    if (peaks.some((p) => Math.abs(p.i - i) < 30)) continue;
    const [ai, slots] = D.topArtistByDay[lo + i];
    peaks.push({ i, v, name: `${D.artists[ai].name} · ${Math.round(slots)}/50` });
  }
  chart(document.getElementById("c-hhi"), baseOption({
    tooltip: { trigger: "axis", formatter: (ps) => {
      const i = ps[0].dataIndex, [ai, slots] = D.topArtistByDay[lo + i];
      return `${prettyDate(days[i])}<br>HHI <b>${fmtInt(hhi[i])}</b><br>Top artist: ${esc(D.artists[ai].name)} (${fmt1(slots)}/50 slots)`;
    } },
    xAxis: { type: "category", data: days, ...axisCommon, splitLine: { show: false },
      axisLabel: { color: COLORS.muted, formatter: (d) => prettyMonth(d.slice(0, 7)), interval: Math.max(1, Math.floor(days.length / 8)) } },
    yAxis: { type: "value", ...axisCommon },
    series: [{ type: "line", data: hhi, showSymbol: false, lineStyle: { width: 2, color: COLORS.green },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "rgba(26,172,78,0.35)" }, { offset: 1, color: "rgba(26,172,78,0)" }]) },
      markPoint: { symbol: "circle", symbolSize: 8, itemStyle: { color: COLORS.greenText },
        label: { show: true, position: "top", color: COLORS.text, fontSize: 11, formatter: (p) => p.name },
        data: peaks.map((p) => ({ coord: [p.i, p.v], name: p.name })) } }],
  }));

  const topArtists = stats.filter((s) => !s.placeholder).slice(0, 10);
  hbar(document.getElementById("c-artists"), topArtists, { value: (s) => +(s.share * 100).toFixed(2),
    label: (s) => s.name, fmt: (v) => v.toFixed(1) + "%", name: "of the chart", onClick: (s) => go(`#/artists/${s.ai}`) });
  hbar(document.getElementById("c-runs"), runs.map(([ti, n]) => ({ ti, n, tip: `${D.tracks[ti].label} – ${D.tracks[ti].artist}` })),
    { value: (r) => r.n, label: (r) => D.tracks[r.ti].label, name: "days", onClick: (r) => go(`#/songs/${r.ti}`) });
  hbar(document.getElementById("c-no1"), reigns.map(([ti, n]) => ({ ti, n, tip: `${D.tracks[ti].label} – ${D.tracks[ti].artist}` })),
    { value: (r) => r.n, label: (r) => D.tracks[r.ti].label, name: "days at #1", onClick: (r) => go(`#/songs/${r.ti}`) });

  chart(document.getElementById("c-buckets"), baseOption({
    tooltip: { trigger: "item", formatter: (p) => `${p.name}: <b>${fmtInt(p.value)}</b> songs` },
    xAxis: { type: "category", data: buckets, ...axisCommon, splitLine: { show: false }, axisLabel: { color: COLORS.muted, interval: 0, fontSize: 10 } },
    yAxis: { type: "value", ...axisCommon },
    series: [{ type: "bar", data: bucketCounts, barWidth: "56%", itemStyle: { color: COLORS.green, borderRadius: [4, 4, 0, 0] },
      label: { show: true, position: "top", color: COLORS.text } }],
  }));

  // monthly album/single/compilation split (point in time) and churn
  const months = [...new Set(days.map((d) => d.slice(0, 7)))];
  const mIndex = new Map(months.map((m, i) => [m, i]));
  const album = D.meta.album_types.map(() => months.map(() => 0));
  D.entries.forEach((e) => {
    for (let k = 0; k < e.length; k += 5) {
      const day = e[k];
      if (day < lo || day > hi) continue;
      album[e[k + 4]][mIndex.get(D.monthOf[day])] += 1;
    }
  });
  const totals = months.map((_, i) => album.reduce((s, a) => s + a[i], 0));
  const colors = [COLORS.green, COLORS.blue, COLORS.orange];
  chart(document.getElementById("c-album"), baseOption({
    legend: { top: 0, right: 0, textStyle: { color: COLORS.text2 }, itemWidth: 10, itemHeight: 10 },
    grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis", valueFormatter: (v) => fmtPct(v / 100) },
    xAxis: { type: "category", data: months.map(prettyMonth), ...axisCommon, splitLine: { show: false } },
    yAxis: { type: "value", max: 100, ...axisCommon, axisLabel: { color: COLORS.muted, formatter: "{value}%" } },
    series: D.meta.album_types.map((t, j) => ({
      name: t[0].toUpperCase() + t.slice(1), type: "bar", stack: "a", barWidth: "62%",
      data: album[j].map((v, i) => +(100 * v / totals[i]).toFixed(2)),
      itemStyle: { color: colors[j], borderColor: COLORS.card, borderWidth: 1.5 },
    })),
  }));
  const churnSum = months.map(() => 0), churnDays = months.map(() => 0);
  for (let day = Math.max(lo, 1); day <= hi; day += 1) {  // day 0 has no previous chart
    const m = mIndex.get(D.monthOf[day]);
    churnSum[m] += Math.round(D.daily.turnover[day] * 50);
    churnDays[m] += 1;
  }
  const churn = churnSum.map((v, i) => (churnDays[i] ? +(v / churnDays[i]).toFixed(2) : null));
  chart(document.getElementById("c-churn"), baseOption({
    tooltip: { trigger: "axis", valueFormatter: (v) => `${fmt1(v)} new songs per day` },
    xAxis: { type: "category", data: months.map(prettyMonth), ...axisCommon, splitLine: { show: false } },
    yAxis: { type: "value", ...axisCommon },
    series: [{ type: "bar", data: churn, barWidth: "56%", itemStyle: { color: COLORS.green, borderRadius: [4, 4, 0, 0] } }],
  }));
}

/* ------------------------------------------------------------------ Artists */

function renderArtists(D, root, selected) {
  const [lo, hi] = dayRange(D, state.period);
  const stats = artistStats(D, lo, hi).filter((s) => !s.placeholder);
  if (!stats.length) { root.innerHTML = "<p>No artists in this period.</p>"; return; }
  const pick = stats.find((s) => s.ai === selected) || stats[0];
  const a = D.artists[pick.ai];
  const rank = stats.indexOf(pick) + 1;
  const trackSet = new Set(a.tracks.map(([ti]) => ti));
  const agg = aggregate(D, lo, hi, trackSet);
  const songs = [...agg.tracks.entries()].sort((x, y) => y[1] - x[1] || D.tracks[x[0]].rank - D.tracks[y[0]].rank);
  const no1 = [...agg.no1.values()].reduce((s, v) => s + v, 0);
  const topSong = D.tracks[songs[0][0]];

  root.innerHTML = `
    <div class="split">
      <aside class="card list-card">
        <input type="search" id="artist-search" placeholder="Search ${fmtInt(stats.length)} artists" aria-label="Search artists">
        <ul class="list" id="artist-list" data-testid="artist-list"></ul>
      </aside>
      <div class="grid">
        <section class="card hero">
          ${cover({ ...topSong, label: a.name }, "cover round")}
          <div>
            <div class="eyebrow">#${rank} artist · ${esc(periodLabel())}</div>
            <h1 data-testid="artist-name">${esc(a.name)}</h1>
            <div class="by">Top song: <a href="#/songs/${songs[0][0]}">${esc(topSong.label)}</a></div>
            <div class="insight" data-testid="artist-insight">${esc(a.name)} holds <b>${fmtPct(pick.share)}</b> of all chart slots in this period
              across <b>${fmtInt(agg.tracks.size)}</b> songs${no1 ? `, with <b>${fmtInt(no1)}</b> days at #1` : ", without reaching #1"}.
              That makes them the <b>#${rank}</b> artist of ${fmtInt(stats.length)}.</div>
          </div>
        </section>
        <div class="kpis">
          ${kpi("artist-songs", "Songs", fmtInt(agg.tracks.size))}
          ${kpi("artist-share", "Chart share", fmtPct(pick.share), "collaborations split")}
          ${kpi("artist-days", "Chart days", fmtDays(pick.weighted), "collaborations split")}
          ${kpi("artist-no1", "Days at #1", fmtInt(no1))}
          ${kpi("artist-best", "Best position", agg.best <= 50 ? "#" + agg.best : "–")}
          ${kpi("artist-pop", "Avg popularity", fmt1(agg.popSum / agg.entries))}
        </div>
        <div class="grid cols-12">
          ${card("Chart share by month", "Share of all chart slots held that month", '<div class="chart" id="c-share"></div>', "span-7")}
          ${card("Songs by days on the chart", "Click a song for its chart journey", '<div class="chart" id="c-songs"></div>', "span-5")}
          ${card("Discography on the chart", `${fmtInt(songs.length)} songs, longest-charting first`, `<div class="covers">${songs.slice(0, 24).map(([ti, n]) => `
            <button data-song="${ti}" title="${esc(D.tracks[ti].label)} · ${n} days">${cover(D.tracks[ti])}<span>${esc(D.tracks[ti].label)}</span></button>`).join("")}</div>`, "span-12")}
        </div>
      </div>
    </div>`;

  const list = document.getElementById("artist-list");
  const drawList = (q) => {
    const ql = q.trim().toLowerCase();
    list.innerHTML = stats.filter((s) => !ql || s.name.toLowerCase().includes(ql)).slice(0, 200).map((s, i) => `
      <li><button class="${s.ai === pick.ai ? "active" : ""}" data-artist="${s.ai}">
        <span class="rank">${stats.indexOf(s) + 1}</span>
        ${cover({ ...D.tracks[s.top], label: s.name }, "round")}
        <span class="name"><b>${esc(s.name)}</b><span>${fmtInt(s.songs)} song${s.songs === 1 ? "" : "s"}</span></span>
        <span class="metric">${fmtPct(s.share)}</span></button></li>`).join("");
  };
  drawList("");
  document.getElementById("artist-search").addEventListener("input", (e) => drawList(e.target.value));
  list.addEventListener("click", (e) => { const b = e.target.closest("[data-artist]"); if (b) go(`#/artists/${b.dataset.artist}`); });
  root.querySelector(".covers").addEventListener("click", (e) => { const b = e.target.closest("[data-song]"); if (b) go(`#/songs/${b.dataset.song}`); });
  list.querySelector(".active")?.scrollIntoView({ block: "nearest" });

  // monthly share: weighted slots / all slots per month
  const months = [...new Set(D.monthOf.slice(lo, hi + 1))];
  const mi = new Map(months.map((m, i) => [m, i]));
  const mine = months.map(() => 0), all = months.map(() => 0);
  for (let d = lo; d <= hi; d += 1) all[mi.get(D.monthOf[d])] += 50;
  for (const [ti, w] of a.tracks) {
    const e = D.entries[ti];
    for (let k = 0; k < e.length; k += 5) if (e[k] >= lo && e[k] <= hi) mine[mi.get(D.monthOf[e[k]])] += w;
  }
  chart(document.getElementById("c-share"), baseOption({
    tooltip: { trigger: "axis", valueFormatter: (v) => v.toFixed(1) + "%" },
    xAxis: { type: "category", data: months.map(prettyMonth), ...axisCommon, splitLine: { show: false } },
    yAxis: { type: "value", ...axisCommon, axisLabel: { color: COLORS.muted, formatter: "{value}%" } },
    series: [{ type: "line", smooth: 0.25, data: mine.map((v, i) => +(100 * v / all[i]).toFixed(2)), symbolSize: 6,
      lineStyle: { width: 2, color: COLORS.green }, itemStyle: { color: COLORS.greenText },
      areaStyle: { color: "rgba(26,172,78,0.18)" } }],
  }));
  hbar(document.getElementById("c-songs"), songs.slice(0, 12).map(([ti, n]) => ({ ti, n })),
    { value: (r) => r.n, label: (r) => D.tracks[r.ti].label, name: "days", onClick: (r) => go(`#/songs/${r.ti}`) });
}

/* ------------------------------------------------------------------ Songs */

function renderSongs(D, root, selected) {
  const ti = Number.isInteger(selected) && D.tracks[selected] ? selected : 0;
  const t = D.tracks[ti];
  const e = D.entries[ti];
  const versions = D.versions[ti];
  const position = D.dates.map(() => null), popularity = D.dates.map(() => null);
  for (let k = 0; k < e.length; k += 5) { position[e[k]] = e[k + 1]; popularity[e[k]] = e[k + 2]; }
  const credits = t.artists.map((ai) => D.artists[ai]);
  const year = t.release.slice(0, 4);

  root.innerHTML = `
    <div class="split">
      <aside class="card list-card">
        <input type="search" id="song-search" placeholder="Search ${fmtInt(D.tracks.length)} songs or artists" aria-label="Search songs">
        <ul class="list" id="song-list" data-testid="song-list"></ul>
      </aside>
      <div class="grid">
        <section class="card hero">
          ${cover(t, "cover")}
          <div>
            <div class="eyebrow">#${t.rank} of ${fmtInt(D.tracks.length)} by days on the chart</div>
            <h1 data-testid="song-title">${esc(t.label)}</h1>
            <div class="by">${credits.map((a) => `<a href="#/artists/${D.artists.indexOf(a)}">${esc(a.name)}</a>`).join(", ")}
              · released <span data-testid="song-release">${esc(year)}</span>${t.release_precision !== "day" ? " (year only)" : ""}</div>
            <div class="badges">
              ${t.explicit ? '<span class="badge">Explicit</span>' : ""}
              <span class="badge">${esc(t.album)}</span>
              ${!t.left_censored && t.peaked_on_debut ? '<span class="badge">Peaked on debut day</span>' : ""}
              ${!t.left_censored && !t.peaked_on_debut ? '<span class="badge green">Climbed after debut</span>' : ""}
              ${t.holiday ? '<span class="badge">Holiday song</span>' : ""}
              ${t.left_censored ? '<span class="badge">Already charting when the data starts</span>' : ""}
              ${t.right_censored ? '<span class="badge green">Still charting at the end of the data</span>' : ""}
            </div>
          </div>
        </section>
        <div class="kpis">
          ${kpi("song-days", "Days on chart", fmtInt(t.days))}
          ${kpi("song-peak", "Peak position", "#" + t.peak)}
          ${kpi("song-first", t.left_censored ? "Position on day 1 of data" : "Debut position", "#" + t.first_pos, prettyDate(t.first_date))}
          ${kpi("song-no1", "Days at #1", fmtInt(t.no1))}
          ${kpi("song-top10", "Days in top 10", fmtInt(t.top10))}
          ${kpi("song-streak", "Longest streak", fmtInt(t.streak) + " d")}
        </div>
        <div class="grid cols-12">
          ${card("Chart journey", "Daily position · gaps are days off the chart", '<div class="chart tall" id="c-journey"></div>', "span-12")}
          ${card("Spotify popularity while charting", versions.length > 2
            ? "Each release version has its own score: zig-zags line up with the release history"
            : "Popularity score on each chart day", '<div class="chart short" id="c-pop"></div>', "span-7")}
          ${card("Release history", `${versions.length} version${versions.length === 1 ? "" : "s"} tracked (SCD Type 2)`, `
            <div style="max-height:220px;overflow:auto"><table class="data" data-testid="song-versions"><thead><tr>
              <th>From</th><th>To</th><th>Release</th><th class="num">Tracks</th><th>Credit</th></tr></thead><tbody>
              ${versions.map((v) => `<tr><td class="nowrap">${esc(v[1])}</td><td class="nowrap">${v[2] ? esc(v[2]) : "current"}</td><td>${esc(v[3])}</td>
                <td class="num">${v[4]}</td><td>${esc(v[5])}</td></tr>`).join("")}</tbody></table></div>`, "span-5")}
        </div>
      </div>
    </div>`;

  const list = document.getElementById("song-list");
  const drawList = (q) => {
    const ql = q.trim().toLowerCase();
    list.innerHTML = D.tracks.map((s, i) => [s, i]).filter(([s]) => !ql || s.label.toLowerCase().includes(ql)
      || s.artist.toLowerCase().includes(ql)).slice(0, 200).map(([s, i]) => `
      <li><button class="${i === ti ? "active" : ""}" data-song="${i}">
        <span class="rank">${s.rank}</span>${cover(s)}
        <span class="name"><b>${esc(s.label)}</b><span>${esc(s.artist)}</span></span>
        <span class="metric">${fmtInt(s.days)} d</span></button></li>`).join("");
  };
  drawList("");
  document.getElementById("song-search").addEventListener("input", (ev) => drawList(ev.target.value));
  list.addEventListener("click", (ev) => { const b = ev.target.closest("[data-song]"); if (b) go(`#/songs/${b.dataset.song}`); });
  list.querySelector(".active")?.scrollIntoView({ block: "nearest" });

  const first = e[0], last = e[e.length - 5];
  const lo = Math.max(0, first - 7), hi = Math.min(D.dates.length - 1, last + 7);
  const days = D.dates.slice(lo, hi + 1);
  const interval = Math.max(1, Math.floor(days.length / 8));
  chart(document.getElementById("c-journey"), baseOption({
    tooltip: { trigger: "axis", formatter: (ps) => `${prettyDate(days[ps[0].dataIndex])}<br>${ps[0].value == null ? "Off the chart" : `Position <b>#${ps[0].value}</b>`}` },
    xAxis: { type: "category", data: days, ...axisCommon, splitLine: { show: false },
      axisLabel: { color: COLORS.muted, interval, formatter: (d) => prettyDate(d).replace(/ 20/, " ’") } },
    yAxis: { type: "value", inverse: true, min: 0, max: 50, interval: 10, ...axisCommon,
      axisLabel: { color: COLORS.muted, formatter: (v) => "#" + Math.max(1, v) } },
    series: [{ type: "line", data: position.slice(lo, hi + 1), connectNulls: false, showSymbol: days.length < 40,
      symbolSize: 5, lineStyle: { width: 2.2, color: COLORS.green }, itemStyle: { color: COLORS.greenText },
      markLine: { symbol: "none", silent: true, lineStyle: { color: COLORS.muted, type: "dashed" },
        label: { color: COLORS.text2, position: "insideStartTop", formatter: `Peak #${t.peak}` },
        data: [{ yAxis: t.peak }] } }],
  }));
  chart(document.getElementById("c-pop"), baseOption({
    tooltip: { trigger: "axis", formatter: (ps) => `${prettyDate(days[ps[0].dataIndex])}<br>Popularity <b>${ps[0].value ?? "–"}</b>` },
    xAxis: { type: "category", data: days, ...axisCommon, splitLine: { show: false },
      axisLabel: { color: COLORS.muted, interval, formatter: (d) => prettyMonth(d.slice(0, 7)) } },
    yAxis: { type: "value", min: (v) => Math.max(0, v.min - 5), max: 100, ...axisCommon },
    series: [{ type: "line", data: popularity.slice(lo, hi + 1), connectNulls: false, showSymbol: false,
      lineStyle: { width: 2, color: COLORS.blue } }],
  }));
}

/* ------------------------------------------------------------------ Insights & Predictions */

function renderInsights(D, root) {
  const ins = state.extra.insights;
  if (!ins) { root.innerHTML = "<p>Insights not generated yet: run <code>make insights</code>.</p>"; return; }
  root.innerHTML = `
    <div class="page-head"><div><h1>What makes a Global Top 50 hit last?</h1>
      <p>${esc(ins.subtitle)}</p></div></div>
    <div class="grid">${ins.questions.map((q, i) => `
      <section class="card qa" data-testid="insight-${i + 1}">
        <div><div class="q">Question ${i + 1}</div><h2>${esc(q.question)}</h2>
          <div class="big-number">${esc(q.headline)}</div>
          <p>${esc(q.answer)}</p><div class="evidence">${esc(q.evidence)}</div></div>
        <img src="${esc(q.figure)}" alt="${esc(q.question)}" loading="lazy">
      </section>`).join("")}</div>`;
}

function renderPredictions(D, root) {
  const m = state.extra.model;
  if (!m) { root.innerHTML = "<p>Model not generated yet: run <code>make model</code>.</p>"; return; }
  root.innerHTML = `
    <div class="page-head"><div><h1>Will a new song last 30+ days?</h1>
      <p>${esc(m.subtitle)}</p></div></div>
    <div class="kpis">${m.kpis.map((k, i) => kpi(`model-kpi-${i}`, k.label, esc(k.value), k.note)).join("")}</div>
    <div class="grid cols-12" style="margin-top:16px">
      ${card("Watchlist: recent debuts scored by the model", "Genuine forecasts for songs too recent to have an outcome yet", `
        <table class="data" data-testid="watchlist"><thead><tr><th>Song</th><th>Artist</th><th>Debut</th>
          <th class="num">Debut pos.</th><th class="num">Day-7 pos.</th><th class="num">P(30+ days)</th><th class="num">Days so far</th></tr></thead>
        <tbody>${m.watchlist.map((w) => `<tr class="click" data-song="${w.track}"><td>${esc(w.song)}</td><td>${esc(w.artist)}</td>
          <td>${esc(w.debut)}</td><td class="num">#${w.debut_pos}</td><td class="num">${w.day7 === 51 ? "off" : "#" + w.day7}</td>
          <td class="num"><b style="color:var(--green)">${fmtPct(w.p, 0)}</b></td><td class="num">${fmtInt(w.days)}</td></tr>`).join("")}</tbody></table>`, "span-12")}
      ${m.figures.map((f) => card(f.title, f.sub, `<img src="${esc(f.src)}" alt="${esc(f.title)}" style="width:100%;border-radius:10px;background:#fcfcfb">`, "span-6")).join("")}
    </div>`;
  root.querySelector("[data-testid=watchlist]").addEventListener("click", (ev) => {
    const r = ev.target.closest("[data-song]"); if (r && r.dataset.song !== "undefined") go(`#/songs/${r.dataset.song}`);
  });
}

/* ------------------------------------------------------------------ router */

function render() {
  const D = state.data;
  state.charts.forEach((c) => c.dispose());
  state.charts = [];
  const [, page = "overview", arg] = location.hash.split("/");
  const id = arg !== undefined && arg !== "" ? Number(arg) : null;
  document.querySelectorAll(".tabs a").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
  document.getElementById("period").disabled = ["songs", "insights", "predictions"].includes(page);
  const root = document.getElementById("app");
  ({ overview: renderOverview, artists: renderArtists, songs: renderSongs, insights: renderInsights,
    predictions: renderPredictions }[page] || renderOverview)(D, root, id);
  window.scrollTo({ top: 0 });
  document.body.dataset.ready = page;
  // incremented on every render, so tests can wait for a re-render of the same page
  document.body.dataset.render = String((Number(document.body.dataset.render) || 0) + 1);
}

async function main() {
  const [data, insights, model] = await Promise.all([
    fetch("data/dashboard.json").then((r) => r.json()),
    fetch("data/insights.json").then((r) => (r.ok ? r.json() : null)).catch(() => null),
    fetch("data/model.json").then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  state.data = prepare(data);
  state.extra = { insights, model };
  const sel = document.getElementById("period");
  sel.innerHTML = periods(state.data).map((p) => `<option value="${p.id}">${esc(p.label)}</option>`).join("");
  sel.addEventListener("change", () => { state.period = sel.value; render(); });
  document.getElementById("foot-meta").textContent =
    `${fmtInt(data.meta.n_snapshots)} daily snapshots · ${fmtInt(data.meta.n_entries)} chart entries · ${prettyDate(data.meta.first_date)} – ${prettyDate(data.meta.last_date)}`;
  window.addEventListener("hashchange", render);
  window.addEventListener("resize", () => state.charts.forEach((c) => c.resize()));
  render();
}

main();
