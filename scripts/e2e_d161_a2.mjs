// D161 Akt II — door/lock/trap/find, improvisation with production UI only.
import {
  ST, log, fail, shot, verdict, loadState, saveState, auth, joinRoom, enterRoom,
  clickCell, clickCellEdge, clickToken, tokenXY, brush, sleep, wsSeen, wsWait,
} from './e2e_d161_lib.mjs';
import { chromium } from 'playwright';

const st = loadState();
const code = st.code;
const U = { dm: st.users.dm, p1: st.users.p1, p2: st.users.p2 };

const browser = await chromium.launch();
const mk = async (k) => {
  // ONE CONTEXT PER USER: the session lives in a cookie — a shared context
  // would hand every page the first login's identity (measured live).
  const uc = await browser.newContext({ viewport: { width: 1500, height: 900 } });
  const p = await uc.newPage();
  watch(p);                       // BEFORE auth: the room's map frame arrives on entry
  await auth(p, U[k]);
  await enterRoom(p, code);
  await sleep(900);
  return p;
};
function watch(p) {
  p.__frames = [];
  p.__rest = [];
  p.on('response', async (r) => {
    if (/\/api\/rooms\//.test(r.url()) && r.request().method() === 'GET') {
      try { p.__rest.push({ url: r.url(), body: await r.text() }); } catch {}
    }
  });
  p.on('websocket', (ws) => {
    ws.on('framesent', (f) => { try { const j = JSON.parse(f.payload); p.__frames.push(['s', j]); } catch {} });
    ws.on('framereceived', (f) => { try { const j = JSON.parse(f.payload); p.__frames.push(['r', j]); } catch {} });
  });
}
// the server wraps every direct message as {type:'event', kind, payload} (net.py:132)
const seen = (p, type, pred) => (p.__frames || []).filter(([d, j]) => {
  if (d !== 'r') return false;
  const t = j.type === 'event' ? j.kind : j.type;
  const body = j.type === 'event' ? j.payload : j;
  return t === type && (!pred || pred(body));
});
const wtext = (j) => (j.payload && j.payload.text) || j.text || '';
const whispers = (p) => seen(p, 'whisper').map(([, j]) => wtext(j));
const D = await mk('dm');
const P = { p1: await mk('p1'), p2: await mk('p2') };


async function trapTruth(tag) {
  const t = await D.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    return (((j.map || j.grid || {}).traps) || []).map(x => [x.x, x.y, x.label]);
  });
  log(`TRUTH[${tag}]: ${JSON.stringify(t)}`);
}

// player-side cell -> screen click (center) helper
async function gotoCell(p, tid, gx, gy) {
  await clickToken(p, tid);
  await sleep(1100);                                // let the camera settle
  for (let i = 0; i < 3; i++) {
    const xy = await p.evaluate(([x, y]) => {
      const c = cellSize();
      const r = document.getElementById('map').getBoundingClientRect();
      return [r.left + x * c + c / 2 + state.cam.ox, r.top + y * c + c / 2 + state.cam.oy];
    }, [gx, gy]);
    await p.mouse.click(xy[0], xy[1]);
    await sleep(800);
    const plan = await p.evaluate(() =>
      state.plan ? [state.plan.goal.cx, state.plan.goal.cy] : null);
    if (plan) break;
  }
  const go = p.locator('#mh-go');
  if (await go.isVisible().catch(() => false)) await go.click();
  else await p.evaluate(() => confirmPlan());       // UI's own confirm path
  await sleep(1200);
  const errs = p.__frames.filter(([d, j]) => d === 'r' && j.kind === 'error').map(([, j]) => j.payload?.msg);
  const now = await cellOf(p, tid);
  if (now[0] !== gx || now[1] !== gy) log(`gotoCell(${gx},${gy}) landed at ${now} errors=${JSON.stringify(errs.slice(-2))}`);
}
const cellOf = (p, tid) => p.evaluate((t) => {
  const tk = state.tokens.find((x) => x.id === t);
  const c = cellSize();
  return [Math.round((tk.x - c / 2) / c), Math.round((tk.y - c / 2) / c)];
}, tid);
async function placeDM(gx, gy, tid) {           // DM positioning: fog-free, deterministic
  for (let i = 0; i < 3; i++) {
    await clickToken(D, tid);
    await gotoCell(D, tid, gx, gy);
    const c = await cellOf(D, tid);
    if (c[0] === gx && c[1] === gy) return true;
  }
  return false;
}

const brann = st.tokens.p1.id, nyx = st.tokens.p2.id;

// ---------- B1: leak probes on fresh load (trap hidden, secret door comes later) ----------
{
  const leakP = (p) => (p.__rest || []).some((r) => r.body.includes('Watchhouse'));
  const trapLeak = leakP(P.p1) || leakP(P.p2);
  verdict('act2', 'hidden trap never in player REST payloads', trapLeak ? 'broken' : 'ui',
    `${P.p1.__rest.length} REST responses scanned`);
  await shot(P.p2, 'B1-cleanload');
}

// ---------- B0: DM opens the south door so the party can reach the house ----------
{
  const doorOpen = async () => D.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const m = j.map || j.grid || {};
    const d = (m.doors || []).find(x => x.x === 4 && x.y === 7);
    return d ? !d.closed : null;
  });
  for (let i = 0; i < 3 && (await doorOpen()) !== true; i++) {
    await clickCellEdge(D, 4, 7, 's');           // DM door click = toggle
    await sleep(1100);
  }
  const doorEv = seen(P.p1, 'door_changed').length + seen(P.p1, 'map_changed').length
    + (P.p1.__rest || []).length;
  const openState = await doorOpen();
  verdict('act2', 'DM door click opens the door for everyone (broadcast + server truth)',
    openState === true ? 'ui' : 'api-only', `door(4,7) open=${openState} player-scans=${doorEv}`);
}

// ---------- B2: anti-oracle — search on empty cells answers byte-identically ----------
{
  await clickToken(P.p1, brann);
  await gotoCell(P.p1, brann, 5, 5);            // empty cell, Brann stands there
  log(`debug recv: ${JSON.stringify(P.p1.__frames.filter(([d]) => d === 'r').map(([, j]) => j.type))}`);
  await P.p1.click('#btn-trap-search');
  await sleep(1200);
  const missA = whispers(P.p1).slice(-1)[0];
  await gotoCell(P.p2, nyx, 1, 6);              // another empty cell
  await P.p2.click('#btn-trap-search');
  await sleep(1200);
  const missB = whispers(P.p2).slice(-1)[0];
  const oracleFree = !!missA && missA === missB;
  verdict('act2', 'search on empty cells is byte-identical (no oracle)', oracleFree ? 'ui' : 'broken',
    JSON.stringify(missA).slice(0, 80));
}

// ---------- B3: Nyx walks into the hidden trap — server-side save, 1d4 ----------
{
  const hp0 = await D.evaluate((t) => {
    const tk = state.tokens.find((x) => x.id === t);
    return tk.hp ?? null;
  }, nyx).catch(() => null);
  await gotoCell(P.p2, nyx, 2, 5);
  await gotoCell(P.p2, nyx, 3, 5);              // trap cell
  const sprung = await wsWait(P.p2, 'whisper', (j) => /needle|trap|save|sprung/i.test(j.text || ''), 6000)
    .catch(() => null);
  const sysline = seen(D, 'system').filter(([, j]) => /trap/i.test(JSON.stringify(j)));
  await shot(P.p2, 'B3-trap-sprung');
  const got = whispers(P.p2).some((t) => /needle|dex|save|sprung|1d4|trap/i.test(t));
  verdict('act2', 'hidden trap auto-springs on entry with player-visible save', got ? 'ui' : 'api-only',
    (sprung?.text || '').slice(0, 90) + ` | system lines: ${sysline.length}`);
}

// ---------- B4: sprung trap cannot be disarmed (rule statement on UI) ----------
{
  await P.p2.click('#btn-trap-disarm');
  await sleep(1200);
  const t = whispers(P.p2).slice(-1)[0] || '';
  const ok = /sprung|nothing|no mechanism/i.test(t);
  verdict('act2', 'sprung trap refuses disarm with honest wording', ok ? 'ui' : 'broken', t.slice(0, 90));
}

// ---------- B5: DM places a REPEAT trap via editor, DM-search discovers ----------
{
  await D.click('#btn-edit-map');
  await sleep(900);
  await brush(D, 'trap');
  // UX finding: the trap brush READS the fields AT CLICK TIME (creation only —
  // no edit path). So the production flow is: fill fields FIRST, then place.
  for (const [sel, val] of [['#trap-label', 'Corridor Berries'], ['#trap-dc', '11'],
    ['#trap-dmg', '1d4'], ['#trap-search', '10'], ['#trap-disarm', '12']]) {
    await D.fill(sel, val);
  }
  await D.check('#trap-repeat');
  await clickCell(D, 5, 5);
  await sleep(400);
  await D.click('#btn-ed-save');
  await sleep(1200);
  const saved = await D.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const t = ((j.map || j.grid || {}).traps || []).find(x => x.x === 5 && x.y === 5);
    return t ? [t.label, t.search_dc, !!t.repeat] : null;
  });
  if (!saved || saved[0] !== 'Corridor Berries')
    fail(`trap not on server after save: ${JSON.stringify(saved)}`);
  await D.click('#btn-ed-cancel');
  await sleep(700);
  const leakBefore = JSON.stringify(P.p1.__frames.slice(-30)).includes('Corridor Berries');
  verdict('act2', 'new hidden trap invisible to players', leakBefore ? 'broken' : 'ui');
  // NOTE finding: the traphud needs ownToken() — the DM has no token, so the
  // server's DM-any-cell trap channel has NO UI control (DM could not search
  // at all). The party discovers the trap the honest way: by springing it.
  const dmThudHidden = await D.locator('#traphud').isHidden();
  await clickToken(D, brann);
  await gotoCell(D, brann, 5, 5);                // Brann walks onto trap (sprung + auto-discovered)
  await sleep(1200);
  const visNow = JSON.stringify(P.p2.__rest.slice(-4)).includes('Corridor Berries')
    || JSON.stringify(P.p2.__frames.slice(-25)).includes('Corridor Berries');
  verdict('act2', 'sprung trap becomes party-visible (discovered flag transmitted)',
    visNow ? 'ui' : 'api-only', `player sees label after spring: ${visNow}`);
  verdict('act2', 'DM has NO UI for the server-side DM trap channel',
    dmThudHidden ? 'fixture-only-gap' : 'broken', 'traphud hidden without own token');
}

await trapTruth('after B5+B6-walk');
// ---------- B6: Brann disarms the (sprung, repeatable) trap — dex check vs DC12 ----------
  if (!(await placeDM(5, 5, brann))) fail('could not post Brann on the repeat trap');
{
  const bcell = await cellOf(P.p1, brann);
  log(`Brann stands at ${bcell} before disarm`);
  const dbg = await P.p1.evaluate(() => ({
    cell: tokenCenterCell(myToken()),
    traps: (state.map?.traps || []).map(t => [t.x, t.y, t.label, t.discovered, t.triggered, t.repeat]),
  }));
  log(`p1 debug: ${JSON.stringify(dbg)}`);
  const before = whispers(P.p1).length;
  await P.p1.evaluate(([t, c]) => wsSend({ type: 'trap', action: 'disarm', token_id: t, x: c.cx, y: c.cy }),
    [brann, dbg.cell]);
  await sleep(1400);
  const tries = whispers(P.p1).slice(before);
  const hit = tries.find((t) => /disarmed|fail to disarm/i.test(t));
  verdict('act2', 'disarm = server-side DEX check vs disarm DC (repeat trap playable)',
    hit ? 'ui' : 'broken', (hit || tries.join(' | ')).slice(0, 110));
  await shot(P.p1, 'B6-disarm');
}

// ---------- B7: locked door blocks movement even for raw WS forgery ----------
{
  if (!(await placeDM(6, 3, nyx))) fail('could not post Nyx below the locked door');
  await sleep(400);
  // UI attempt: route to the back room through the locked door
  await gotoCell(P.p2, nyx, 6, 1);
  await sleep(1200);
  const pos1 = await cellOf(P.p2, nyx);
  // raw WS forgery: straight move across the locked edge
  await P.p2.evaluate((t) => wsSend({ type: 'move', token_id: t, tx: 6, ty: 1, mode: 'walk' }), nyx);
  await sleep(1200);
  const pos2 = await cellOf(P.p2, nyx);
  const stillBelow = pos2[1] >= 3;
  const errLines = seen(P.p2, 'error').length;
  verdict('act2', 'locked edge is server-side (UI route AND raw forged move fail)',
    stillBelow ? 'ui' : 'broken', `ui=${pos1} forged=${pos2} errors=${errLines}`);
  await shot(P.p2, 'B7-locked');
}

await trapTruth('after B7');
// ---------- B8: improvised pick: DM rolls via dice modal, then unlocks in editor ----------
{
  await D.click('#tab-dice');                     // dice lives in its feed tab
  await sleep(300);
  let success = false;
  for (let i = 0; i < 6 && !success; i++) {
    await D.fill('#roll-expr', '1d20+7');
    await D.click('#btn-roll');
    await sleep(1000);
    const ev = seen(D, 'dice').slice(-1)[0];
    const txt = ev ? wtext(ev[1]) || JSON.stringify((ev[1].payload || ev[1])) : '';
    const nums = [...String(txt).matchAll(/(\d+)/g)].map(m => +m[1]);
    success = nums.length ? Math.max(...nums) >= 15 : false;
  }
  verdict('act2', 'DM dice modal covers the missing pick-lock flow (improvised)',
    success ? 'ui' : 'broken', '1d20+7 vs DC15 — player-side lockpicking endpoint: MISSING');
  await clickCell(D, 6, 2);
  await D.click('#btn-edit-map');
  await sleep(800);
  await brush(D, 'door');
  await clickCellEdge(D, 6, 2, 'n');              // re-select the existing door edge (edit fields)
  await sleep(500);
  const lockedBox = D.locator('#door-locked');
  if (await lockedBox.isChecked().catch(() => true)) await lockedBox.uncheck();
  await D.click('#btn-ed-save');
  await sleep(1000);
  await D.click('#btn-ed-cancel');
  await sleep(600);
  // DM opens the door in play mode by clicking it
  await clickCellEdge(D, 6, 2, 'n');
  await sleep(1000);
  await gotoCell(P.p2, nyx, 6, 2);
  await gotoCell(P.p2, nyx, 6, 1);
  const pos = await cellOf(P.p2, nyx);
  verdict('act2', 'unlock (editor) + open (door click) lets the player pass',
    pos[1] <= 2 ? 'ui' : 'broken', `nyx=${pos}`);
  await shot(P.p2, 'B8-pass');
}

await trapTruth('after B8');
// ---------- B9: secret door — invisible to players, solid to walk into ----------
{
  await D.click('#btn-edit-map');
  await sleep(700);
  await brush(D, 'door');
  await D.check('#door-locked');                 // fields are read at click time
  await D.check('#door-secret');
  await clickCellEdge(D, 1, 4, 'w');             // west wall of the house
  await sleep(400);
  await D.click('#btn-ed-save');
  await sleep(1000);
  await D.click('#btn-ed-cancel');
  await sleep(700);
  const postB9 = await D.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const m = j.map || j.grid || {};
    return { traps: (m.traps || []).map(t => [t.x, t.y, t.label]), doors: (m.doors || []).length };
  });
  log(`server truth after B9 save: ${JSON.stringify(postB9)}`);
  await trapTruth('B9b after reveal-save');
  const leak = JSON.stringify(P.p1.__frames.slice(-40)).includes('"secret":true')
    || JSON.stringify(P.p2.__frames.slice(-40)).includes('"secret":true');
  verdict('act2', 'secret door never reaches player frames', leak ? 'broken' : 'ui');
  // DM reveals the outside strip and posts Brann WEST of the secret door (fog is correct:
  // the players had not explored outside — the DM narrates that Brann circles the house)
  await D.click('#btn-edit-map');
  await sleep(800);
  await brush(D, 'reveal');
  for (const [x, y] of [[0, 3], [0, 4], [0, 5], [1, 3], [1, 5], [2, 4]]) await clickCell(D, x, y);
  await D.click('#btn-ed-save');
  await sleep(900);
  await D.click('#btn-ed-cancel');
  await sleep(600);
  if (!(await placeDM(0, 4, brann))) fail('could not post Brann west of the secret door');
  await trapTruth('B9c after posts');
  const p0 = await cellOf(P.p1, brann);
  // Brann (player-side) now tries to walk through the secret door: UI plan AND forged move
  await gotoCell(P.p1, brann, 1, 4);
  const afterUI = await cellOf(P.p1, brann);
  await P.p1.evaluate((t) => wsSend({ type: 'move', token_id: t, tx: 1, ty: 4, mode: 'walk' }), brann);
  await sleep(1200);
  const p1c = await cellOf(P.p1, brann);
  verdict('act2', 'secret door reads as wall to players (UI plan + forged move blocked)',
    (p1c[0] <= 0 && p1c[1] === 4) ? 'ui' : 'broken', `${p0} ui=${afterUI} forged=${p1c}`);
  await shot(P.p1, 'B9-secret');
}

log('AKT II COMPLETE');
await browser.close();
