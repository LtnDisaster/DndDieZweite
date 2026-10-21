// D159 — real-Chromium E2E for open-volume floors, signed levels and the
// display-only floor filter. Node port of scripts/e2e_d159_open_volumes.py
// (the Playwright image ships Chromium but no Python binding).
//
// Run from inside mcr.microsoft.com/playwright:v1.64.0-noble against a
// throwaway app container (BASE), evidence via VTT_E2E_EVIDENCE.
import { chromium } from 'playwright';
import fs from 'fs';

const BASE = process.env.VTT_E2E_BASE_URL || 'http://127.0.0.1:8013';
const EVID = process.env.VTT_E2E_EVIDENCE || '/tmp/opencode';
const MINUS = '\u2212';
let step = 0;
const log = m => console.log('[d159] ' + m);

async function shot(page, tag) {
  step += 1;
  try { fs.mkdirSync(EVID, { recursive: true });
        await page.screenshot({ path: `${EVID}/e2e-d159-${String(step).padStart(2, '0')}-${tag}.png` }); }
  catch (e) { log('screenshot failed: ' + e.message); }
}
async function register(page, username) {
  await page.goto(BASE + '/');
  await page.waitForSelector('#btn-register');
  await page.fill('#au-user', username);
  await page.fill('#au-pass', 'secret12345');
  await page.click('#btn-register');
  await page.waitForFunction(u => document.querySelector('#lobby-user').textContent.includes(u), username, { timeout: 8000 });
}
async function createRoom(page, name) {
  await page.fill('#rm-name', name);
  await page.click('#btn-room-create');
  await page.waitForSelector('#view-prep');
  const code = (await page.locator('#prep-code').innerText()).trim().toUpperCase();
  return code;
}
async function enterRoom(page, code) {
  await page.evaluate(c => openRoom(c), code);
  await page.waitForSelector('#side-tabs');
}
async function clickCell(page, gx, gy) {
  const [x, y] = await page.evaluate(([gx, gy]) => {
    const c = cellSize(); const r = document.getElementById('map').getBoundingClientRect();
    return [r.left + gx * c + c / 2 + state.cam.ox, r.top + gy * c + c / 2 + state.cam.oy];
  }, [gx, gy]);
  await page.mouse.click(x, y); await page.waitForTimeout(140);
}

(async () => {
  const stamp = Math.floor(Date.now() / 1000);
  const browser = await chromium.launch({ headless: true, chromiumSandbox: false });
  const ctx = await browser.newContext({ baseURL: BASE });
  const page = await ctx.newPage();
  page.on('dialog', d => d.accept());
  const fail = m => { console.error('[d159 FAIL] ' + m); throw new Error(m); };
  try {
    await register(page, `d159_dm_${stamp}`);
    const code = await createRoom(page, `D159 ${stamp}`);
    await enterRoom(page, code);

    // K1: signed levels + below-floor + E-tags
    await page.click("#side-tabs button[data-tab='dm']");
    await page.fill('#floor-new', 'Attic'); await page.click('#btn-floor-add');
    await page.waitForFunction(() => (state.floors || []).length === 2, null, { timeout: 8000 });
    await page.fill('#floor-new', 'Cellar'); await page.check('#floor-below');
    await page.click('#btn-floor-add');
    await page.waitForFunction(() => state.floor_levels && Object.keys(state.floor_levels).length >= 3, null, { timeout: 8000 });
    const lv = await page.evaluate(() => state.floor_levels);
    const fl = await page.evaluate(() => state.floors);
    if (!(lv[''] === 0 && lv.Attic === 1 && lv.Cellar === -1 && Object.keys(lv).length === 3))
      fail(`levels ${JSON.stringify(lv)}`);
    if (JSON.stringify(fl) !== JSON.stringify(['Cellar', '', 'Attic'])) fail(`floors ${JSON.stringify(fl)}`);
    const tags = await page.locator('#floor-list .fl-lvl').allInnerTexts();
    if (!(tags.includes('E+1') && tags.includes('E0') && tags.includes('E' + MINUS + '1'))) fail(`tags ${tags}`);
    log(`K1 PASS — signed levels ${JSON.stringify(lv)}; tags ${tags}`);
    await shot(page, 'K1-levels');

    // K2: fresh named plane is AIR, ground is floor; rail order top->bottom
    await page.click('#btn-edit-map');
    await page.waitForSelector('#floor-rail');
    const order = await page.locator('#floor-rail .fl-rail .nm').allInnerTexts();
    if (JSON.stringify(order) !== JSON.stringify(['Attic', 'Ground', 'Cellar'])) fail(`rail order ${order}`);
    const lvlTop = await page.locator('#floor-rail .fl-rail').first().locator('.lvl').innerText();
    if (lvlTop !== 'E+1') fail(`top rail level ${lvlTop}`);
    await page.locator('#floor-rail .fl-rail', { hasText: 'Attic' }).click();
    await page.waitForFunction(() => state.viewFloor === 'Attic', null, { timeout: 8000 });
    await page.waitForTimeout(400);
    const atticCell = await page.evaluate(() => state.editMap.cells[0]);
    await page.locator('#floor-rail .fl-rail[data-f=""]').first().click();
    await page.waitForFunction(() => state.viewFloor === '', null, { timeout: 8000 });
    await page.waitForTimeout(400);
    const groundCell = await page.evaluate(() => state.editMap.cells[0]);
    if (atticCell !== 6) fail(`fresh plane must be AIR(6), got ${atticCell}`);
    if (groundCell !== 0) fail(`ground must be floor(0), got ${groundCell}`);
    log('K2 PASS — fresh plane AIR(6), ground floor(0)');
    await shot(page, 'K2-air');

    // K2b: air brush lays floor; erase on a named plane restores AIR
    await page.locator('#floor-rail .fl-rail', { hasText: 'Attic' }).click();
    await page.waitForFunction(() => state.viewFloor === 'Attic', null, { timeout: 8000 });
    await page.waitForTimeout(300);
    await page.click(".brush[data-b='floor']"); await clickCell(page, 4, 4);
    const laid = await page.evaluate(() => { const m = state.editMap; return m.cells[4 * m.w + 4]; });
    if (laid !== 0) fail(`floor brush laid ${laid}`);
    await page.click(".brush[data-b='erase']"); await clickCell(page, 4, 4);
    const erased = await page.evaluate(() => { const m = state.editMap; return m.cells[4 * m.w + 4]; });
    if (erased !== 6) fail(`erase on named plane must restore AIR(6), got ${erased}`);
    log('K2b PASS — floor lays 0, erase on a named plane restores AIR(6)');

    // K3: display-only floor filter
    await page.waitForSelector('#viewfilter:not(.hidden)');
    const before = await page.evaluate(() => state.viewFloor);
    const mode0 = await page.evaluate(() => state.viewFilter);
    if (mode0 !== 'current') fail(`default filter should be current, got ${mode0}`);
    await page.click('#vf-all');
    await page.waitForFunction(() => state.viewFilter === 'all', null, { timeout: 4000 });
    const ariaAll = await page.getAttribute('#vf-all', 'aria-pressed');
    const ariaCur = await page.getAttribute('#vf-current', 'aria-pressed');
    if (ariaAll !== 'true' || ariaCur !== 'false') fail(`aria all=${ariaAll} cur=${ariaCur}`);
    const after = await page.evaluate(() => state.viewFloor);
    if (before !== after) fail('display filter must not change the viewed plane');
    log('K3 PASS — filter toggles state, never moves the viewer');
    await shot(page, 'K3-filter');

    // K4: cross-floor token is badged + gated by the filter (real client fns)
    // Attic is open AIR, so a token cannot stand there — the DM first lays a
    // floor at (8,8) on Attic (D159: you author ground before a walker stands),
    // saves it, then drops a token on that cell while BROWSING the ground.
    await page.click(".brush[data-b='floor']"); await clickCell(page, 8, 8);
    await page.click('#btn-ed-save'); await page.waitForTimeout(900);
    await page.evaluate(() => { state.viewFloor = ''; });
    await page.evaluate(() => { const c = cellSize();
      wsSend({ type: 'add_token', label: 'Up', x: (8 + .5) * c, y: (8 + .5) * c, size: 'Medium', floor: 'Attic' }); });
    await page.waitForFunction(() => (state.tokens || []).some(t => t.floor === 'Attic' && t.label === 'Up'), null, { timeout: 8000 });
    const probe = await page.evaluate(() => {
      const t = state.tokens.find(t => t.floor === 'Attic');
      state.viewFilter = 'current'; const cur = onPlane(t);
      const label = tokenPlaneLabel(t);
      state.viewFilter = 'all'; const all = onPlane(t);
      return { cur, all, label };
    });
    if (probe.cur !== false) fail("in 'this floor only' a floor-A token must not be drawn below");
    if (probe.all !== true) fail("in 'all visible' the floor-A token must become drawable");
    if (!String(probe.label).startsWith('E+1')) fail(`bad label ${probe.label}`);
    log(`K4 PASS — cross-floor token labelled '${probe.label}', gated by the filter`);
    await shot(page, 'K4-badge');

    log('ALL D159 SCENARIOS PASS');
  } finally {
    await browser.close();
  }
})();
