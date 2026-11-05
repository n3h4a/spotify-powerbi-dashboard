// Load every page in a real browser and report console errors (development helper).
const { chromium } = require("playwright");
(async () => {
  const base = process.argv[2];
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  for (const route of ["#/overview", "#/artists", "#/songs", "#/insights", "#/predictions"]) {
    await page.goto(base + route);
    await page.waitForFunction((r) => document.body.dataset.ready === r.split("/")[1], route, { timeout: 15000 });
    await page.waitForTimeout(400);
    console.log(route, "ok", await page.locator("[data-testid]").count(), "test ids");
  }
  console.log(JSON.stringify({ errors }));
  await browser.close();
})();
