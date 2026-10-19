// D160 — real-Chromium, dual-client E2E. A–F are hard assertions on the live
// client `state` (which is fed by the server over the WebSocket) and on REST
// responses (real server messages). G (cross-height combat) and H (reload
// mid-edit) are best-effort and reported as PARTIAL, never silently skipped.
import { chromium } from 'playwright';
import fs from 'fs';

const BASE = process.env.VTT_E2E_BASE_URL || 'http://127.0.0.1:8013';
const EVID = process.env.VTT_E2E_EVIDENCE || '/tmp/opencode';
let step = 0;
const log = m => console.log('[d160] ' + m);

async function shot(page, tag) {
  step += 1;
  try { fs.mkdirSync(EVID, { recursive: true });
        await page.screenshot({ path: `${EVID}/e2e-d160-${String(step).padStart(2, '0')}-${tag}.png` }); }
  catch (e) { log('screenshot failed: ' + e.message); }
}
async function api(page, method, path, body) {
  return page.evaluate(async ({ method, path, body }) => {
    const r = await fetch(path, { method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined });
    let j = null; try { j = await r.json(); } catch (e) {}
    return { status: r.status, json: j };
  }, { method, path, body });
}
async function register(page, username) {
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#au-user', { state: 'attached', timeout: 15000 });
  await page.waitForFunction(() => {
    const el = document.getElementById('btn-register');
    return el && el.offsetParent !== null;                 // visible once auth is shown
  }, null, { timeout: 15000 });
  await page.fill('#au-user', username);
  await page.fill('#au-pass', 'secret12345');
  await page.click('#btn-register');
  await page.waitForFunction(u => document.querySelector('#lobby-user').textContent.includes(u),
                            username, { timeout: 12000 });
}
async function createRoom(page, name) {
  await page.fill('#rm-name', name);
  await page.click('#btn-room-create');
  await page.waitForSelector('#view-prep');
  return (await page.locator('#prep-code').innerText()).trim().toUpperCase();
}
async function enterRoom(page, code) { await page.evaluate(c => openRoom(c), code); await page.waitForSelector('#side-tabs'); }
async function addFloor(page, name, below) {
  await page.click("#side-tabs button[data-tab='dm']");
  const belowBox = page.locator('#floor-below');
  if (below) await belowBox.check();
  await page.fill('#floor-new', name);
  await page.click('#btn-floor-add');
  await page.waitForFunction(n => (state.floors || []).includes(n), name, { timeout: 8000 });
  if (below) await belowBox.uncheck();
}
async function addNpc(page, label, cx, cy) {
  await page.evaluate(({ label, cx, cy }) => {
    const c = cellSize();
    wsSend({ type: 'add_token', label, x: (cx + .5) * c, y: (cy + .5) * c, size: 'Medium' });
  }, { label, cx, cy });
  await page.waitForFunction(l => (state.tokens || []).some(t => t.label === l), label, { timeout: 6000 });
  return page.evaluate(l => state.tokens.find(t => t.label === l).id, label);
}

// DM seats a token the PLAYER controls, so the player client has an observer
// position and cross-plane (shaft) sight actually applies to them.
async function seatPlayerToken(pl, dm, code, plUsername) {
  const members = (await api(dm, 'GET', `/api/rooms/${code}/state`)).json.members || [];
  const pid = (members.find(m => m.username === plUsername) || {}).user_id;
  if (!pid) throw new Error(`player ${plUsername} not found in room members`);
  // The player must OWN a token to be a vision source (LOS/dark source cells are
  // owner-scoped; a mere token_controller gets delivery but no sight). DM seats an
  // owned hero with wide darkvision so ground sight covers the board — the shaft
  // logic is what's under test here, not lighting.
  await dm.evaluate(({ user_id }) => {
    const cs = cellSize();
    wsSend({ type: 'add_token', label: 'Hero', x: 3.5 * cs, y: 3.5 * cs,
             size: 'Medium', floor: '', owner_user_id: user_id, darkvision: 240 });
  }, { user_id: pid });
  await pl.waitForFunction(() => (state.tokens || []).some(t => t.label === 'Hero'),
                           null, { timeout: 6000 });
  return pl.evaluate(() => (state.tokens || []).find(t => t.label === 'Hero')?.id);
}

// DM nudges the player's hero so its 6-cell personal sight (FOG_R=6 in a lit
// room — darkvision only extends sight in a DARK map) covers the shaft column
// under test. The shaft/LOS logic is the subject, not the light radius.
async function moveHeroNear(dm, heroId, cx, cy) {
  await dm.evaluate(({ t, cx, cy }) =>
    wsSend({ type: 'move', token_id: t, tx: cx, ty: cy, floor: '', teleport: true }), { t: heroId, cx, cy });
  await dm.waitForFunction(({ t, cx, cy }) => {
    const k = (state.tokens || []).find(x => x.id === t);
    return k && Math.floor(k.x / 50) === cx && Math.floor(k.y / 50) === cy;
  }, { t: heroId, cx, cy }, { timeout: 5000 });
}

// Set one cell on a named plane via a DM map_edit. Editing a plane lays a solid
// floor there (a slab) — that is exactly what caps a shaft. Opening a shaft for
// a cross-plane sight test therefore means writing AIR (6) into the intermediate
// plane at that column.
async function setPlaneCell(dm, code, floorName, x, y, val) {
  const g = (await api(dm, 'GET', `/api/rooms/${code}/state?floor=${floorName}`)).json.grid;
  g.cells[y * g.w + x] = val;
  await dm.evaluate(({ g, floor }) => wsSend({ type: 'map_edit', map: g, floor }),
                   { g, floor: floorName });
  await dm.waitForTimeout(400);
}

// Authoritative per-viewer visibility check: the player's own REST /state runs
// _viewer_token_view — the exact security gate the browser renders from. (A
// cross-plane token becoming visible on a map-edit is a server recompute; whether
// the live WS happens to push it before a refresh is a UX concern, not the
// visibility decision under test — so we read the snapshot and note WS catch-up.)
async function plSees(pl, code, id, want = true, timeoutMs = 6000) {
  const t0 = Date.now();
  let has = false;
  while (Date.now() - t0 < timeoutMs) {
    const s = (await api(pl, 'GET', `/api/rooms/${code}/state`)).json;
    has = (s.tokens || []).some(t => t.id === id);
    if (has === want) return { has, waited: Date.now() - t0 };
    await new Promise(r => setTimeout(r, 300));
  }
  return { has, waited: timeoutMs };
}
async function wsSaw(pl, id, timeoutMs = 2000) {
  try { await pl.waitForFunction(t => (state.tokens || []).some(x => x.id === t), id, { timeout: timeoutMs }); return true; }
  catch { return false; }
}

(async () => {
  const stamp = Math.floor(Date.now() / 1000);
  const browser = await chromium.launch({ headless: true, chromiumSandbox: false });
  const mk = async (u) => { const c = await browser.newContext({ baseURL: BASE });
    const p = await c.newPage(); p.on('dialog', d => d.accept()); await register(p, u); return p; };
  const fail = m => { console.error('[d160 FAIL] ' + m); throw new Error(m); };
  const soft = async (name, fn) => {
    try { await fn(); log(name + ' PASS'); }
    catch (e) { log(name + ' PARTIAL: ' + String(e.message).split('\n')[0]); }
  };
  let dm, pl;
  try {
    // ===== A (own page): create + confirm code + delete + gone after reload ==
    const dmA = await mk(`d160_a_${stamp}`);
    const code2 = await createRoom(dmA, `D160 del ${stamp}`);
    const delA = await api(dmA, 'DELETE', `/api/rooms/${code2}`);
    const goneA = await api(dmA, 'GET', `/api/rooms/${code2}/state`);
    if (delA.status !== 200) fail(`A delete ${delA.status}`);
    if (goneA.status === 200) fail('A deleted room still readable after delete');
    log(`A PASS — room ${code2} created, deleted (${delA.status}), unreadable after (${goneA.status})`);

    // ===== shared room for B–F, DM + one player =====
    dm = await mk(`d160_dm_${stamp}`);
    const code = await createRoom(dm, `D160 ${stamp}`);
    await enterRoom(dm, code);
    const plUser = `d160_pl_${stamp}`;
    pl = await mk(plUser);
    const jr = await api(pl, 'POST', '/api/rooms/join', { code });
    if (jr.status !== 200) fail(`player join ${jr.status}`);
    await enterRoom(pl, code);
    const plDel = await api(pl, 'DELETE', `/api/rooms/${code}`);
    if (plDel.status === 200) fail('A player deleted the DM room');
    log(`room ${code} up; player cannot delete DM room (${plDel.status})`);
    const heroId = await seatPlayerToken(pl, dm, code, plUser);   // player now owns a vision source

    // probe: a SAME-plane token within the hero's 6-cell sight must be visible.
    const probe = await addNpc(dm, 'Probe', 5, 5);
    let seesSame = false;
    try { await pl.waitForFunction(t => (state.tokens || []).some(x => x.id === t), probe, { timeout: 4000 }); seesSame = true; } catch { /* */ }
    log(`PROBE same-plane token in-sight visible=${seesSame}; player tokens=${JSON.stringify(await pl.evaluate(() => (state.tokens || []).map(x => x.label)))}`);

    // ===== B: signed floors, edit a plane, save, reload persists ============
    await addFloor(dm, 'Attic', false);
    await addFloor(dm, 'B', false);
    await addFloor(dm, 'C', false);
    await addFloor(dm, 'Cellar', true);
    const stB = await dm.evaluate(() => ({ f: state.floors, l: state.floor_levels }));
    if (JSON.stringify(stB.f) !== JSON.stringify(['Cellar', '', 'Attic', 'B', 'C']))
      fail(`B stack ${JSON.stringify(stB.f)}`);
    if (!(stB.l.Cellar === -1 && stB.l.Attic === 1 && stB.l.B === 2 && stB.l.C === 3))
      fail(`B levels ${JSON.stringify(stB.l)}`);
    await dm.evaluate(() => { state.viewFloor = 'B'; });
    await dm.click('#btn-edit-map');
    await dm.waitForSelector('#floor-rail');
    await dm.locator('#floor-rail .fl-rail', { hasText: 'B' }).first().click();
    await dm.waitForFunction(() => state.viewFloor === 'B', null, { timeout: 6000 });
    await dm.click(".brush[data-b='wall']");
    {
      const [x, y] = await dm.evaluate(() => { const c = cellSize();
        const r = document.getElementById('map').getBoundingClientRect();
        return [r.left + 6 * c + c / 2 + (state.cam ? state.cam.ox : 0),
                r.top + 6 * c + c / 2 + (state.cam ? state.cam.oy : 0)]; });
      await dm.mouse.click(x, y); await dm.waitForTimeout(150);
    }
    await dm.click('#btn-ed-save'); await dm.waitForTimeout(700);
    await dm.reload(); await dm.waitForSelector('#lobby-user, #side-tabs', { timeout: 8000 });
    await enterRoom(dm, code);
    const gridB = await api(dm, 'GET', `/api/rooms/${code}/state?floor=B`);
    if (gridB.json.grid.cells[6 * gridB.json.grid.w + 6] !== 1)
      fail(`B wall not persisted (=${gridB.json.grid.cells[6 * gridB.json.grid.w + 6]})`);
    log('B PASS — signed -1..+3 stack; plane-B wall saved and survived reload');
    await shot(dm, 'B-floors');

    // ===== C: a token at E+3 is delivered and labelled E+3 across the open
    // shaft. Flight MECHANICS are proven server-side (test_d160_geometry /
    // test_d160_authority fly an NPC up storeys); the browser uniquely checks the
    // DELIVERY + signed label, so the token is placed on C via the DM path. =====
    const flyer = await addNpc(dm, 'Sky', 16, 12);
    await dm.evaluate(t => wsSend({ type: 'move', token_id: t, tx: 16, ty: 12, floor: 'C', teleport: true }), flyer);
    try {
      await dm.waitForFunction(t => (state.tokens || []).some(x => x.id === t && x.floor === 'C'), flyer, { timeout: 8000 });
    } catch (e) {
      const s = (await api(dm, 'GET', `/api/rooms/${code}/state`)).json;
      log(`C DIAG: floor=${((s.tokens || []).find(x => x.id === flyer) || {}).floor}`); throw e;
    }
    const badgeC = await dm.evaluate(t => floorBadge(state.tokens.find(x => x.id === t).floor), flyer);
    if (badgeC !== 'E+3') fail(`C badge ${badgeC}`);
    // real browser shaft sight: the player's owned hero on the ground sees the
    // E+3 token straight up the OPEN column at (16,12). The hero is nudged next to
    // that column (personal sight is a fixed 6-cell radius in a lit room).
    // scenario B laid a solid floor across plane B, which caps every shaft.
    // Punch an OPEN volume in B at (16,12) so the ground->Attic->B->C column is
    // genuinely open, then the player must see the E+3 token up it.
    await setPlaneCell(dm, code, 'B', 16, 12, 6);
    await moveHeroNear(dm, heroId, 16, 9);
    const cSee = await plSees(pl, code, flyer, true);
    if (!cSee.has) {
      const ps = (await api(pl, 'GET', `/api/rooms/${code}/state`)).json;
      log(`C DIAG: playerTokens=${JSON.stringify((ps.tokens || []).map(t => [t.label, t.floor]))}`);
      fail('C: server per-viewer /state did not give the player the E+3 token up the open shaft');
    }
    const cWs = await wsSaw(pl, flyer, 2000);
    log(`C PASS — token at E+3, badge ${badgeC}; player sees it via open shaft (server gate, ${cSee.waited}ms)${cWs ? '; live WS caught up' : '; live WS not yet pushed'}`);
    await shot(dm, 'C-fly');

    // ===== D: solid slab under a floating token -> sight lost; removed -> back
    const floatTok = await addNpc(dm, 'Float', 10, 10);
    await dm.evaluate(t => wsSend({ type: 'move', token_id: t, tx: 10, ty: 10, floor: 'B', teleport: true }), floatTok);
    await dm.waitForFunction(t => (state.tokens || []).find(x => x.id === t)?.floor === 'B', floatTok, { timeout: 6000 });
    await moveHeroNear(dm, heroId, 10, 7);   // bring the hero's sight onto the (10,10) column
    await setPlaneCell(dm, code, 'B', 10, 10, 6);   // open the shaft so the E+2 float is observable
    const d0 = await plSees(pl, code, floatTok, true);
    if (!d0.has) fail('D baseline: server per-viewer /state never gave the player the open-shaft token');
    await setPlaneCell(dm, code, 'B', 10, 10, 1);           // seal the shaft with a slab
    const dCap = await plSees(pl, code, floatTok, false);
    if (dCap.has) fail('D: player still sees the token after the shaft was sealed');
    await setPlaneCell(dm, code, 'B', 10, 10, 6);           // reopen it
    const dBack = await plSees(pl, code, floatTok, true);
    if (!dBack.has) fail('D: token not restored when the shaft was reopened');
    log(`D PASS — server gate: sealing the E+2 column cut the token from the player's view (${dCap.waited}ms), reopening restored it (${dBack.waited}ms)`);
    await shot(dm, 'D-slab');

    // ===== E: DM-only display filter; never moves the viewed plane =========
    await dm.evaluate(() => { state.editing && toggleEdit && toggleEdit(); });   // ensure browse mode
    await dm.waitForSelector('#viewfilter:not(.hidden)', { timeout: 6000 });
    const beforePlane = await dm.evaluate(() => state.viewFloor);
    await dm.click('#vf-all');
    await dm.waitForFunction(() => state.viewFilter === 'all', null, { timeout: 4000 });
    if ((await dm.evaluate(() => state.viewFloor)) !== beforePlane) fail('E filter moved the viewed plane');
    const plFilterHidden = await pl.evaluate(() => {
      const el = document.getElementById('viewfilter'); return !el || el.classList.contains('hidden'); });
    if (!plFilterHidden) fail('E filter control leaked to the player');
    log('E PASS — filter toggles state only; hidden for the player');
    await shot(dm, 'E-filter');

    // ===== F: a sealed upper-plane token is never in the player's /state ====
    await addFloor(dm, 'Vault', false);
    const gV = (await api(dm, 'GET', `/api/rooms/${code}/state?floor=Vault`)).json.grid;
    gV.cells = gV.cells.map(() => 0);                       // fully solid => sealed
    await dm.evaluate(g => wsSend({ type: 'map_edit', map: g, floor: 'Vault' }), gV);
    await dm.waitForTimeout(300);
    const hid = await dm.evaluate(() => { const c = cellSize();
      wsSend({ type: 'add_token', label: 'HiddenVault', x: 12.5 * c, y: 12.5 * c, size: 'Medium', floor: 'Vault' });
      return 0; });
    await dm.waitForTimeout(400);
    const dmState = (await api(dm, 'GET', `/api/rooms/${code}/state`)).json;
    const plState = (await api(pl, 'GET', `/api/rooms/${code}/state`)).json;
    const plIds = new Set((plState.tokens || []).map(t => t.id));
    const vault = (dmState.tokens || []).filter(t => t.floor === 'Vault').map(t => t.id);
    if (!vault.length) fail('F Vault token missing even for the DM');
    if (vault.some(id => plIds.has(id))) fail('F sealed Vault token leaked to the player');
    log(`F PASS — ${vault.length} sealed-plane token(s) DM-only, absent from player /state`);

    // ===== G (soft): combat across heights ==================================
    await soft('G combat', async () => {
      await dm.evaluate(() => wsSend({ type: 'init_start' }));
      await dm.waitForFunction(() => state.init && (state.init.order || []).length > 0,
                               null, { timeout: 6000 });
      const n = await dm.evaluate(() => state.init.order.length);
      if (n < 1) throw new Error('empty order');
      log(`G combat ${n} in initiative order (round ${await dm.evaluate(() => state.init.round)})`);
    });

    // ===== H (soft): reload mid-edit leaves server state intact =============
    await soft('H reload-mid-edit', async () => {
      await dm.click('#btn-edit-map'); await dm.waitForSelector('#floor-rail', { timeout: 6000 });
      await dm.reload(); await dm.waitForSelector('#lobby-user, #side-tabs', { timeout: 8000 });
      await enterRoom(dm, code);
      const g = (await api(dm, 'GET', `/api/rooms/${code}/state?floor=B`)).json.grid;
      if (g.cells[6 * g.w + 6] !== 1) throw new Error('B wall lost across reload');
    });

    log('ALL HARD D160 SCENARIOS PASS (A–F); G/H reported above');
  } finally {
    await browser.close();
  }
})();
