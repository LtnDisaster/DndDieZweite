// D161 — shared helpers for the play-session audit E2Es.
// Real UI only for gameplay actions; REST is used for observation and for the
// clearly-labelled fixture/observation calls only.
import fs from 'fs';

export const BASE = process.env.VTT_E2E_BASE_URL || 'http://127.0.0.1:8021';
export const EVID = process.env.VTT_E2E_EVIDENCE || '/shots';
export const ST = process.env.VTT_E2E_STATE || '/st';
export const PASS = 'secret12345';

const T = process.env.D161_TAG || 'd161';
let step = +(process.env.D161_STEP0 || 0);

export function log(m) { console.log(`[${T}] ${m}`); }
export class Fail extends Error {}
export function fail(m) { console.error(`[${T} FAIL] ${m}`); throw new Fail(m); }

export function shot(page, tag) {
  step += 1;
  try {
    fs.mkdirSync(EVID, { recursive: true });
    return page.screenshot({ path: `${EVID}/${T}-${String(step).padStart(2, '0')}-${tag}.png`, full_page: false });
  } catch (e) { log(`screenshot failed: ${e.message}`); }
}

// verdicts: one JSON line per checked capability, the six-way classification
export function verdict(area, action, klass, note = '') {
  const rec = { area, action, klass, note };
  try {
    fs.mkdirSync(ST, { recursive: true });
    fs.appendFileSync(`${ST}/verdicts_${T}.jsonl`, JSON.stringify(rec) + '\n');
  } catch (e) { /* evidence dir may be read-only in recon runs */ }
  const mark = { ui: 'UI-OK', api_only: 'API-ONLY', fixture: 'FIXTURE', missing: 'MISSING', broken: 'BROKEN', infra: 'INFRA' }[klass] || klass;
  log(`VERDICT ${mark} — ${area} :: ${action}${note ? ' :: ' + note : ''}`);
}

export function loadState() {
  try { return JSON.parse(fs.readFileSync(`${ST}/d161_state.json`, 'utf8')); }
  catch (e) { return {}; }
}
export function saveState(s) {
  fs.mkdirSync(ST, { recursive: true });
  fs.writeFileSync(`${ST}/d161_state.json`, JSON.stringify(s, null, 1));
}

// WS message recorder: stores every server->client message per page
export function watchWS(page) {
  page.__ws = [];
  page.on('websocket', ws => {
    ws.on('framereceived', f => {
      try {
        const m = JSON.parse(f.payload);
        page.__ws.push({ t: Date.now(), type: m.type, msg: m });
      } catch (e) { /* non-JSON frame */ }
    });
  });
}
export function wsSeen(page, type, pred = null) {
  return (page.__ws || []).filter(w => w.type === type && (!pred || pred(w.msg)));
}
export function wsWait(page, type, pred = null, ms = 8000) {
  return page.waitForFunction(([type, ms]) => {
    return true;
  }, [type, ms], { timeout: ms }).catch(() => {}).then(() => wsSeen(page, type, pred));
}

export async function auth(page, username) {
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  // shared context: a cookie may already carry a session (a2+ spawns multiple pages)
  const already = await page.evaluate(() =>
    (document.querySelector('#lobby-user')?.textContent || ''));
  if (already.includes(username)) return;
  await page.waitForSelector('#au-user', { timeout: 15000 });
  await page.fill('#au-user', username);
  await page.fill('#au-pass', PASS);
  await page.click('#btn-register');
  await page.waitForTimeout(600);
  const ok = await page.evaluate(() => document.querySelector('#lobby-user')?.textContent || '');
  if (!ok.includes(username)) {
    // already registered in an earlier run -> login
    await page.fill('#au-user', username);
    await page.fill('#au-pass', PASS);
    await page.click('#btn-login');
  }
  await page.waitForFunction(u => (document.querySelector('#lobby-user')?.textContent || '').includes(u),
    username, { timeout: 12000 });
}

export async function createRoom(page, name) {
  await page.fill('#rm-name', name);
  await page.click('#btn-room-create');
  await page.waitForSelector('#view-prep', { timeout: 10000 });
  return (await page.locator('#prep-code').innerText()).trim().toUpperCase();
}
export async function joinRoom(page, code) {
  await page.fill('#rm-code', code);
  await page.click('#btn-room-join');
  await page.waitForSelector('#view-prep', { timeout: 10000 });
}
export async function enterRoom(page, code) {
  await page.evaluate(c => openRoom(c), code);
  await page.waitForSelector('#side-tabs', { timeout: 10000 });
}
export async function backToPrep(page) {
  await page.click('#btn-back');
  await page.waitForSelector('#view-prep', { timeout: 8000 });
}

export async function clickCell(page, gx, gy) {
  const [x, y] = await page.evaluate(([gx, gy]) => {
    const c = cellSize(); const r = document.getElementById('map').getBoundingClientRect();
    return [r.left + gx * c + c / 2 + state.cam.ox, r.top + gy * c + c / 2 + state.cam.oy];
  }, [gx, gy]);
  await page.mouse.click(x, y); await page.waitForTimeout(120);
}
export async function clickCellEdge(page, gx, gy, edge) {
  // click the shared edge between cells (for the door brush)
  const [x, y] = await page.evaluate(([gx, gy, edge]) => {
    const c = cellSize(); const r = document.getElementById('map').getBoundingClientRect();
    let dx = 0, dy = 0;
    if (edge === 'n') dy = -0.45; if (edge === 's') dy = 0.45;
    if (edge === 'w') dx = -0.45; if (edge === 'e') dx = 0.45;
    return [r.left + (gx + .5 + dx) * c + state.cam.ox, r.top + (gy + .5 + dy) * c + state.cam.oy];
  }, [gx, gy, edge]);
  await page.mouse.click(x, y); await page.waitForTimeout(140);
}
export async function clickToken(page, token_id) {
  const pos = await page.evaluate(tid => {
    const t = state.tokens.find(x => x.id === tid);
    if (!t) return null;
    const r = document.getElementById('map').getBoundingClientRect();
    return [r.left + t.x + state.cam.ox, r.top + t.y + state.cam.oy];
  }, token_id);
  if (!pos) fail(`token ${token_id} not visible on this client`);
  await page.mouse.click(pos[0], pos[1]);
  await page.waitForTimeout(150);
}
export async function tokenXY(page, id) {
  return page.evaluate(tid => { const t = state.tokens.find(x => x.id === tid); return t ? [t.x, t.y] : null; }, id);
}
export async function tokenFloor(page, id) {
  return page.evaluate(tid => { const t = state.tokens.find(x => x.id === tid); return t ? (t.floor || '') : null; }, id);
}
export async function brush(page, b) {
  await page.click(`.brush[data-b='${b}']`);
  await page.waitForTimeout(80);
}
export function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

export async function seat(page) {
  const tab = page.locator("#side-tabs button[data-tab='chars']");
  if (await tab.count()) await tab.click();
  const bringN = await page.locator("#my-chars [data-a='bring']").count();
  if (bringN) await page.locator("#my-chars [data-a='bring']").first().click();
  await page.waitForFunction(() => document.querySelectorAll('#my-chars .badge').length > 0 &&
    document.querySelector('#my-chars').textContent.includes('at table'), null, { timeout: 12000 });
}
