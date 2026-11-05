// Capture README screenshots of each page (run: node site/tests/screenshots.cjs <base-url> <out-dir>).
const { chromium } = require("playwright");
const path = require("path");
(async () => {
  const [base, out] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const shots = [
    ["overview", "#/overview"],
    ["artists", "#/artists/" + (process.argv[4] || "")],
    ["songs", "#/songs/" + (process.argv[5] || "")],
    ["insights", "#/insights"],
    ["predictions", "#/predictions"],
  ];
  for (const [name, route] of shots) {
    await page.goto(base + route);
    await page.waitForFunction((r) => document.body.dataset.ready === r, name, { timeout: 15000 });
    await page.waitForTimeout(900); // let chart animations finish
    await page.screenshot({ path: path.join(out, `web_${name}.png`), fullPage: true });
    console.log("saved", name);
  }
  await browser.close();
})();
