// Capture screenshots of every dashboard page.
// Usage: node site/tests/screenshots.cjs <base-url> <out-dir> [artist name] [song title]
// Runs in the Pages deployment, where album covers load, so the README always shows the
// live site as it is.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

(async () => {
  const [base, out, artistName = "Taylor Swift", songTitle = "Espresso"] = process.argv.slice(2);
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  await page.goto(base + "#/overview");
  await page.waitForFunction(() => document.body.dataset.ready === "overview");
  const ids = await page.evaluate(([a, s]) => fetch("data/dashboard.json").then((r) => r.json()).then((d) => ({
    artist: d.artists.findIndex((x) => x.name === a),
    song: d.tracks.findIndex((x) => x.title === s),
  })), [artistName, songTitle]);

  const shots = [
    ["overview", "#/overview"],
    ["artists", `#/artists/${Math.max(ids.artist, 0)}`],
    ["songs", `#/songs/${Math.max(ids.song, 0)}`],
    ["insights", "#/insights"],
    ["predictions", "#/predictions"],
  ];
  for (const [name, route] of shots) {
    await page.evaluate((h) => { location.hash = h; }, route);
    await page.waitForFunction((r) => document.body.dataset.ready === r, name, { timeout: 15000 });
    // load lazy images (covers, figures) and wait for them before capturing
    await page.$$eval("img", (imgs) => imgs.forEach((i) => { i.loading = "eager"; }));
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(1200); // chart animations
    await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: true });
    console.log("saved", name);
  }
  await browser.close();
})();
