// End-to-end run of the web dashboard in a real browser.
//
// Drives the site like a user (navigation, period filter, search, clicks) and prints
// every number it reads as JSON. tests/test_web_e2e.py compares them with independent
// SQL on the warehouse. Usage: node site/tests/e2e.cjs <base-url>
const { chromium } = require("playwright");

(async () => {
  const base = process.argv[2];
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    // album covers come from Spotify's CDN, which may be unreachable in CI: not an app error
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text());
  });

  const ready = (p) => page.waitForFunction((x) => document.body.dataset.ready === x, p, { timeout: 15000 });
  const read = (ids) => page.evaluate((list) => Object.fromEntries(list.map((id) => {
    const el = document.querySelector(`[data-testid="${id}"]`);
    return [id, el ? el.textContent.trim() : null];
  })), ids);
  // Run an action and wait until the page has rendered again. Waiting only for "the
  // artists page is ready" is not enough when the action re-renders the same page.
  const rendered = async (action, p) => {
    const before = await page.evaluate(() => Number(document.body.dataset.render) || 0);
    await action();
    await page.waitForFunction((n) => Number(document.body.dataset.render) > n, before, { timeout: 15000 });
    if (p) await ready(p);
  };
  const goto = async (hash, p) => {
    const current = await page.evaluate(() => location.hash);
    if (current === hash) return;
    await rendered(() => page.evaluate((h) => { location.hash = h; }, hash), p);
  };
  const OVERVIEW = ["kpi-songs", "kpi-artists", "kpi-popularity", "kpi-explicit", "kpi-no1"];
  const ARTIST = ["artist-name", "artist-songs", "artist-share", "artist-days", "artist-no1", "artist-best", "artist-pop"];
  const SONG = ["song-title", "song-release", "song-days", "song-peak", "song-first", "song-no1", "song-top10", "song-streak"];
  const out = { overview: {}, artists: [], songs: [], interactions: {} };

  await page.goto(base + "#/overview");
  await ready("overview");
  const data = await page.evaluate(() => fetch("data/dashboard.json").then((r) => r.json()));
  const periods = await page.$$eval("#period option", (os) => os.map((o) => o.value));

  // 1. Overview KPIs for every period
  for (const p of periods) {
    if (p !== "all") await rendered(() => page.selectOption("#period", p), "overview");
    out.overview[p] = await read(OVERVIEW);
  }
  await rendered(() => page.selectOption("#period", "all"), "overview");

  // 2. Every artist page (all time) and every song page
  for (let ai = 0; ai < data.artists.length; ai += 1) {
    if (data.artists[ai].placeholder) continue;
    await goto(`#/artists/${ai}`, "artists");
    out.artists.push(await read(ARTIST));
  }
  for (let ti = 0; ti < data.tracks.length; ti += 1) {
    await goto(`#/songs/${ti}`, "songs");
    out.songs.push(await read(SONG));
  }

  // 3. Real interactions
  // a) search for an artist and click the result
  await goto("#/artists", "artists");
  await page.fill("#artist-search", "sabrina");
  await rendered(() => page.click("#artist-list button"), "artists");
  out.interactions.artistSearch = await read(["artist-name", "artist-songs", "artist-no1"]);
  // b) click the first album cover in the discography -> song page of that song
  await rendered(() => page.click(".covers button"), "songs");
  out.interactions.coverClick = await read(["song-title"]);
  // c) the period filter changes the artist page
  await goto("#/artists", "artists");
  await rendered(() => page.selectOption("#period", "2023"), "artists");
  out.interactions.artist2023 = await read(["artist-name", "artist-share", "artist-songs"]);
  await rendered(() => page.selectOption("#period", "all"), "artists");
  // d) search for a song and click it
  await goto("#/songs", "songs");
  await page.fill("#song-search", "espresso");
  await rendered(() => page.click("#song-list button"), "songs");
  out.interactions.songSearch = await read(SONG);
  // e) the song page links back to its artist
  await rendered(() => page.click(".hero .by a"), "artists");
  out.interactions.songToArtist = await read(["artist-name"]);
  // f) watchlist row on the predictions page opens that song
  await goto("#/predictions", "predictions");
  const watchFirst = await page.$eval("[data-testid=watchlist] tbody tr td", (td) => td.textContent.trim());
  await rendered(() => page.click("[data-testid=watchlist] tbody tr"), "songs");
  out.interactions.watchlist = { row: watchFirst, opened: (await read(["song-title"]))["song-title"] };
  // g) every insight card has an image that loaded
  await goto("#/insights", "insights");
  // images are lazy-loaded; force-load each one and confirm the file exists and decodes
  out.interactions.insightImages = await page.$$eval(".qa img", (imgs) => Promise.all(imgs.map((i) => {
    i.loading = "eager";
    return i.decode().then(() => i.naturalWidth > 0, () => false);
  })));
  // h) tabs navigate
  out.interactions.tabs = [];
  for (const tab of ["overview", "artists", "songs", "insights", "predictions"]) {
    const href = await page.$eval(`.tabs a[data-page=${tab}]`, (a) => a.getAttribute("href"));
    if ((await page.evaluate(() => location.hash)) !== href) {
      await rendered(() => page.click(`.tabs a[data-page=${tab}]`), tab);
    }
    out.interactions.tabs.push(await page.$eval(".tabs a.active", (a) => a.dataset.page));
  }

  out.errors = errors;
  console.log(JSON.stringify(out));
  await browser.close();
})();
