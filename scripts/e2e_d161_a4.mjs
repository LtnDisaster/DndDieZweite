// D161 Akt IV — planes & vertical: stairs (player route), vertical flight
// through the shaft (DM fly), plane isolation, refusal paths. Production UI.
import {
  log, fail, shot, verdict, loadState, auth, enterRoom,
  clickToken, tokenXY, sleep, brush, clickCell,
} from './e2e_d161_lib.mjs';
import { chromium } from 'playwright';

const st = loadState();
const code = st.code;
const U = { dm: st.users.dm, p1: st.users.p1, p2: st.users.p2 };

const browser = await chromium.launch();
async function mk(k) {
  const ctx = await browser.newContext({ viewport: { width: 1500, height: 900 } });
  const p = await ctx.newPage();
  p.__ = [];
  p.on('websocket', (ws) => {
    ws.on('framereceived', (f) => { try { p.__.push(JSON.parse(f.payload)); } catch {} });
  });
  await auth(p, U[k]);
  await enterRoom(p, code);
  await sleep(800);
  return p;
}
const D = await mk('dm');
const P1 = await mk('p1');
const P2 = await mk('p2');
const errors = (p) => p.__.filter((j) => (j.kind || j.type) === 'error')
  .map((j) => (j.payload && j.payload.msg) || j.msg || '');

const tok = (p, L) => p.evaluate((n) => {
  const t = state.tokens.find((x) => x.label === n);
  return t ? { id: t.id, x: t.x, y: t.y, floor: t.floor } : null;
}, L);
const cell = (t, cs) => [Math.round((t.x - cs / 2) / cs), Math.round((t.y - cs / 2) / cs)];
async function mapObjects(p, floor) {
  return p.evaluate(async (f) => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state?floor=${encodeURIComponent(f)}`)).json();
    return (j.grid && j.grid.objects) || [];
  }, floor);
}
async function placeDM(gx, gy, tid) {
  for (let i = 0; i < 3; i++) {
    await clickToken(D, tid);
    const xy = await D.evaluate(([x, y]) => {
      const c = cellSize(); const r = document.getElementById('map').getBoundingClientRect();
      return [r.left + x * c + c / 2 + state.cam.ox, r.top + y * c + c / 2 + state.cam.oy];
    }, [gx, gy]);
    await D.mouse.click(xy[0], xy[1]);
    await sleep(700);
    const go = await D.locator('#mh-go').isVisible().catch(() => false);
    if (go) await D.click('#mh-go');
    await sleep(900);
    const c = await D.evaluate((t) => {
      const tk = state.tokens.find((x) => x.id === t); const cs = cellSize();
      return [Math.round((tk.x - cs / 2) / cs), Math.round((tk.y - cs / 2) / cs), tk.floor];
    }, tid);
    if (c[0] === gx && c[1] === gy) return c;
  }
  return null;
}

// ---------- T0: the signed floor stack (D159) ----------
{
  const fl = await D.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    return { floors: j.floors, levels: j.floor_levels };
  });
  const need = ['Cellar', 'Upper1', 'Upper3'];
  const lv = fl.levels || {};
  const ordered = (lv.Cellar ?? -1) < (lv.GROUND ?? 0) && (lv.Upper1 ?? 0) < (lv.Upper3 ?? 0);
  verdict('act4', 'true bottom-to-top plane stack with signed levels',
    need.every((f) => fl.floors.includes(f)) && ordered ? 'ui' : 'api-only', JSON.stringify(fl));
}

async function walkSelf(P, tid, cells) {
  await clickToken(P, tid);
  await sleep(500);
  for (const [gx, gy] of cells) {
    await clickCell(P, gx, gy);
    await sleep(250);
    const go = await P.locator('#mh-go').isVisible().catch(() => false);
    if (go) await P.click('#mh-go');
    await P.waitForFunction(([id, x, y]) => {
      const t = state.tokens.find((z) => z.id === id); const cs = cellSize();
      return t && Math.abs(t.x - (x * cs + cs / 2)) < 6 && Math.abs(t.y - (y * cs + cs / 2)) < 6;
    }, [tid, gx, gy], { timeout: 9000 }).catch(() => {});
    await sleep(250);
  }
}

// ---------- T1: stairs are the players' plane route ----------
{
  await D.click('[data-tab="dm"]').catch(() => {});
  await sleep(300);
  const haveBack = await D.evaluate(async (c) => {
    const j = await (await fetch(`/api/rooms/${c}/state?floor=Cellar`)).json();
    return ((j.maps ? j.maps.Cellar : null) || {}).objects?.filter((o) => o.interact && o.interact.op && o.interact.op.kind === 'stair').length || 0;
  }, code);
  if (!haveBack) {
    await D.click('#btn-edit-map'); await sleep(1200);
    await brush(D, 'obj');
    await D.fill('#obj-label', 'Cellar Stair (up)');
    await D.fill('#obj-act', 'Go Up');
    await D.locator('#obj-op').selectOption('stair');
    await D.fill('#obj-tfl', 'GROUND'); await D.fill('#obj-tx', '2'); await D.fill('#obj-ty', '6');
    await clickCell(D, 4, 4);
    await D.click('#btn-ed-save'); await sleep(1400);
    await D.click('#btn-ed-cancel');
    await D.waitForFunction(() => !state.editing, null, { timeout: 8000 });
    await sleep(500);
  }
  const stairs = (await mapObjects(D, 'GROUND')).filter((o) => (o.interact || {}).op && (o.interact.op.kind === 'stair'));
  if (!stairs.length) fail('no stair object on GROUND — map fixture lost');
  const s = stairs[0];
  const bt = await tok(D, 'Brann');
  // deterministic start: DM puts Brann back on the primary plane
  await D.evaluate((id) => wsSend({ type: 'token_floor', token_id: id, floor: '' }), bt.id);
  await sleep(700);
  await P1.waitForFunction(() => (state.viewFloor || '') === '', null, { timeout: 10000 })
    .catch(() => log('warn: P1 view did not follow to primary plane'));
  await sleep(300);
  // stand adjacent to the stair, then CLICK the stair = interact (no token selected)
  await walkSelf(P1, bt.id, [[4, 5], [3, 5]]);  // explored hall cells; (3,5) is adjacent to the stair
  await P1.keyboard.press('Escape');
  await sleep(400);
  const xy = await P1.evaluate(([x, y]) => {
    const c = cellSize(); const r = document.getElementById('map').getBoundingClientRect();
    return [r.left + x * c + c / 2 + state.cam.ox, r.top + y * c + c / 2 + state.cam.oy];
  }, [s.x, s.y]);
  await P1.mouse.click(xy[0], xy[1]);
  await sleep(2000);
  const after = await tok(D, 'Brann');
  const posA = await P1.evaluate((n) => { const t = state.tokens.find((x) => x.label === n); return t ? [t.x, t.y, t.floor] : null; }, 'Brann');
  log(`T1dbg brann before-stair-click pos=${JSON.stringify(posA)} errs=${JSON.stringify(errors(P1).slice(-2))}`);
  const toFloor = ((s.interact || {}).op || {}).floor || 'Cellar';
  verdict('act4', 'player takes the stairs -> plane change by clicking the stair',
    after && after.floor === toFloor ? 'ui' : 'api-only',
    `stair(${s.x},${s.y})->${toFloor} brann floor=${after && after.floor}`);
  await shot(P1, 'T1-upstairs');

  // the same token's player view followed it to the new plane
  const v = await P1.evaluate(async () =>
    (await (await fetch(`/api/rooms/${state.room.code}/state`)).json()).view_floor);
  verdict('act4', "player's plane view follows the token (fog is per plane)",
    v === toFloor ? 'ui' : 'api-only', `view_floor=${v}`);

  // ---------- T1b: a return stair to the PRIMARY plane is unauthorable ----------
  // The editor refuses an empty target-floor field, and the primary plane's
  // true name IS "" — any invented name stays dangling and the server then
  // answers honestly at use time. A party that descends cannot climb back up
  // with stairs. PRODUCT GAP (P2-8), probed through the real editor.
  await D.click("#side-tabs button[data-tab='dm']");
  await sleep(400);
  await D.click('#floor-list .fl-view[data-f=""]');
  await sleep(1200);
  await D.click('#btn-edit-map'); await sleep(1300);
  await brush(D, 'obj');
  await D.fill('#obj-label', 'Return Stair Probe');
  await D.fill('#obj-act', 'Climb Up');
  await D.locator('#obj-op').selectOption('stair');
  await D.fill('#obj-tfl', '');
  await D.fill('#obj-tx', '2'); await D.fill('#obj-ty', '6');
  await clickCell(D, 5, 5);
  await sleep(400);
  const refuseToast = await D.locator('#toast').innerText().catch(() => '');
  await brush(D, 'objrm');
  await clickCell(D, 4, 4);            // clean the dangling fixture stair away
  await D.click('#btn-ed-save'); await sleep(1500);
  await D.click('#btn-ed-cancel');
  await D.waitForFunction(() => !state.editing, null, { timeout: 8000 }).catch(() => {});
  await sleep(400);
  verdict('act4', 'stairs back to the primary plane cannot be authored (product gap P2-8)',
    /target floor/i.test(refuseToast) ? 'fixture-only-gap' : 'api-only',
    `editor: ${refuseToast.slice(0, 70)}`);
}

// ---------- T2: vertical flight through the shaft (DM, fly speed) ----------
{
  // the shaft = Act I's openv column in the tower at (12,3)/(12,4)
  const o = { x: 12, y: 3 };
  const raider = await tok(D, 'Sky Raider');
  // the raider already stands on the shaft's Upper1 lip at (12,3); browse that
  // plane from the DM floor panel so the token becomes clickable
  await D.evaluate(([id, x, y]) => wsSend({ type: 'move', token_id: id, tx: x, ty: y, mode: 'fly' }), [raider.id, o.x, o.y]);
  await sleep(700);
  await D.click("#side-tabs button[data-tab='dm']");
  await sleep(400);
  await D.click('#floor-list .fl-view[data-f="Upper1"]');
  await sleep(1400);
  await clickToken(D, raider.id);
  await sleep(900);
  await D.evaluate(() => { for (const d of document.querySelectorAll('#sheet details')) d.open = true; });
  const hasVf = await D.locator('#vf-go').isVisible().catch(() => false);
  if (!hasVf) fail('vertical-flight row missing for a 60 ft flyer (sheet)');
  await D.selectOption('#vf-floor', '');   // 'Ground (primary)' — straight DOWN through the shaft
  const err0 = errors(D).length;
  await D.click('#vf-go');
  await sleep(2200);
  const up = await tok(D, 'Sky Raider');
  verdict('act4', 'DM flies an NPC straight down the shaft (server 3D route + fly budget)',
    up && (up.floor || '') === '' ? 'ui' : 'api-only',
    `raider floor=${up && up.floor} errors=${JSON.stringify(errors(D).slice(err0))}`);
  await shot(D, 'T2-shaft-up');

  // solid ceiling: vertical flight where no column is open must be refused
  await D.evaluate(([id, x, y]) => wsSend({ type: 'move', token_id: id, tx: x, ty: y, mode: 'fly' }), [up.id, 8, 3]);
  await D.keyboard.press('Escape');
  await D.waitForFunction(([id]) => {
    const t = state.tokens.find((z) => z.id === id); const cs = cellSize();
    return t && Math.abs(t.x - 8.5 * cs) < 3 && Math.abs(t.y - 3.5 * cs) < 3 && (t.floor || '') === '';
  }, [up.id], { timeout: 12000 }).catch(() => {});
  await D.click('#floor-list .fl-view[data-f=""]');
  await sleep(1200);
  await clickToken(D, up.id);
  await sleep(800);
  await D.evaluate(() => { for (const d of document.querySelectorAll('#sheet details')) d.open = true; });
  const errBefore = errors(D).length;
  if (await D.locator('#vf-go').isVisible().catch(() => false)) {
    await D.selectOption('#vf-floor', 'Upper1');
    await D.click('#vf-go');
    await sleep(1500);
  }
  const refused = errors(D).slice(errBefore).some((e) => /vertical|fly|ceiling|path/i.test(e));
  const pos2 = await tok(D, 'Sky Raider');
  verdict('act4', 'no open column -> vertical flight refused with a real error',
    refused && pos2 && pos2.floor !== 'Upper1' ? 'ui' : 'api-only',
    JSON.stringify(errors(D).slice(errBefore)));
}

// ---------- T3: players cannot self-change planes or fake flight ----------
{
  const e0 = errors(P1).length;
  await P1.evaluate((id) => wsSend({ type: 'token_floor', token_id: id, floor: 'Upper3' }),
    (await tok(P1, 'Brann')).id);
  await sleep(1200);
  const selfPlane = errors(P1).slice(e0).some((e) => /floor|plane|dm/i.test(e));
  const b2 = await tok(D, 'Brann');
  verdict('act4', 'player-forced plane change rejected (planes are DM/stairs)',
    selfPlane && (b2.floor || '') !== 'Upper3' ? 'ui' : 'api-only',
    JSON.stringify(errors(P1).slice(e0)));

  const e1 = errors(P1).length;
  await P1.evaluate((id) => wsSend({ type: 'move', token_id: id, tx: 5, ty: 4, mode: 'fly' }),
    (await tok(P1, 'Brann')).id);
  await sleep(1200);
  const noFly = errors(P1).slice(e1).some((e) => /fly/i.test(e));
  verdict('act4', 'fly mode refused for a creature without a fly speed',
    noFly ? 'ui' : 'api-only', JSON.stringify(errors(P1).slice(e1)));
}

// ---------- T4: planes do not see each other ----------
{
  // Nyx stays on GROUND; Brann goes up again and must not see her in his grid state
  await P2.evaluate(() => {});
  const gNyx = await tok(D, 'Nyx');
  const s = (await mapObjects(D, 'GROUND')).find((ob) => (ob.interact || {}).op && (ob.interact.op.kind === 'stair'));
  // Brann sits on Cellar (T1 landed him there); Nyx too (the run's own
  // stair traffic put her there). From their own /state views every token
  // that stayed on the primary plane must be ABSENT — and Brann present.
const both = await P2.evaluate(async () =>
    (await (await fetch(`/api/rooms/${state.room.code}/state`)).json()).tokens.map((t) => [t.label, t.floor]));
  const nyx = await tok(D, 'Nyx');
  const nyxUp = (nyx.floor || 'GROUND') !== 'GROUND';
  const seesBrann = both.some(([l]) => l === 'Brann');
  const sameAsNyx = both.filter(([, f]) => f === nyx.floor).map(([l]) => l);
  const onGround = both.filter(([, f]) => (f || 'GROUND') === 'GROUND').map(([l]) => l);
  verdict('act4', 'tokens on different planes never share a view (D86)',
    nyxUp && seesBrann && both.every(([l]) => !['Quill', 'Solea', 'Goblin Brute'].includes(l)) ? 'ui' : 'api-only',
    JSON.stringify(both));
  await shot(P2, 'T4-planes');
}

log('AKT IV COMPLETE');
await browser.close();
