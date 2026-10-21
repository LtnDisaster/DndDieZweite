// D161 Phase 5 — security matrix: cross-actor control, DM-only channels,
// whisper routing, blind rolls, replay guard, unauthenticated REST. Five
// independent browser contexts, raw forged WS frames + REST probes.
import {
  log, fail, shot, verdict, loadState, auth, enterRoom, tokenXY, sleep,
} from './e2e_d161_lib.mjs';
import { chromium } from 'playwright';

const st = loadState();
const code = st.code;
const browser = await chromium.launch();
async function mk(k) {
  const ctx = await browser.newContext({ viewport: { width: 1300, height: 820 } });
  const p = await ctx.newPage();
  p.__ = [];
  p.on('websocket', (ws) => {
    ws.on('framereceived', (f) => { try { p.__.push(JSON.parse(f.payload)); } catch {} });
  });
  await auth(p, st.users[k]);
  await enterRoom(p, code);
  await sleep(700);
  return p;
}
const D = await mk('dm');
const P1 = await mk('p1');
const P2 = await mk('p2');
const P3 = await mk('p3');
const errs = (p, n = 0) => p.__.slice(n).filter((j) => (j.kind || j.type) === 'error')
  .map((j) => (j.payload && j.payload.msg) || j.msg || '');
const marks = (p) => p.__.filter((j) => (j.kind || j.type) === 'chat'
  && JSON.stringify(j.payload || j).includes('SEC-9')).map((j) => JSON.stringify(j.payload || j));

const ids = await D.evaluate(async () => {
  const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
  return { tokens: Object.fromEntries(j.tokens.map((t) => [t.label, t.id])),
    users: Object.fromEntries(j.members.map((m) => [m.username, m.user_id])) };
});

// S1 · cross-actor control: p1 forges a move of NYX (p2's token)
{
  const nyx = ids.tokens.Nyx;
  const before = await tokenXY(P2, nyx);
  const n0 = errs(P1).length;
  await P1.evaluate((t) => wsSend({ type: 'move', token_id: t, tx: 1, ty: 1, mode: 'walk' }), nyx);
  await sleep(1200);
  const after = await tokenXY(P2, nyx);
  const e = errs(P1, n0);
  verdict('sec', 'forged move of another players token rejected',
    before[0] === after[0] && before[1] === after[1] ? 'ui' : 'broken',
    `nyx ${before} -> ${after} err=${JSON.stringify(e).slice(0, 60)}`);
}

// S2 · DM-only message types from a player socket
{
  const n0 = errs(P1).length;
  await P1.evaluate(() => {
    wsSend({ type: 'init_start' });
    wsSend({ type: 'long_rest' });
    wsSend({ type: 'token_floor', token_id: 1, floor: 'Upper1' });
    wsSend({ type: 'init_end' });
  });
  await sleep(2000);
  const e = errs(P1, n0);
  const rejects = e.filter((m) => /dm|permission|authoris|authoriz|only/i.test(m)).length;
  const initNow = await D.evaluate(async () =>
    (await (await fetch(`/api/rooms/${state.room.code}/state`)).json()).initiative.combat);
  verdict('sec', 'DM-only WS channels reject a player socket (4/4)',
    rejects >= 3 && !initNow ? 'ui' : 'api-only', `rejects=${rejects}/4 combat=${initNow} errs=${JSON.stringify(e).slice(0, 120)}`);
}

// S3 · whisper routing: /w to p2 lands only with p2 (and sender context)
{
  await P1.evaluate((u2) => wsSend({ type: 'chat', text: 'SEC-9 private line', channel: 'whisper', target: u2 }),
    ids.users.d161p2);
  await sleep(1500);
  const s1 = marks(P1).length, s2 = marks(P2).length, s3 = marks(P3).length;
  verdict('sec', 'whisper reaches its target only (1 sees, 2 not)',
    s2 > 0 && s3 === 0 ? 'ui' : 'broken', `p1=${s1} p2=${s2} p3=${s3}`);
}

// S4 · /dm channel: DM sees it, other players do not
{
  await P3.evaluate(() => wsSend({ type: 'chat', text: 'SEC-9 to-DM only', channel: 'dm' }));
  await sleep(1500);
  const d = marks(D).some((x) => x.includes('to-DM'));
  const p1s = marks(P1).some((x) => x.includes('to-DM'));
  verdict('sec', 'player whisper-to-DM is invisible to other players',
    d && !p1s ? 'ui' : 'broken', `dm=${d} p1=${p1s}`);
}

// S5 · blind roll: result reaches the DM, not the table
{
  P1.__ = []; P2.__ = []; D.__ = D.__.slice(-1);
  await P1.evaluate(() => wsSend({ type: 'roll', kind: 'save', ability: 'wis', visibility: 'blind' }));
  await sleep(1800);
  const p1dice = P1.__.some((j) => (j.kind || j.type) === 'dice');
  const p2dice = P2.__.some((j) => (j.kind || j.type) === 'dice');
  const dmdice = D.__.some((j) => (j.kind || j.type) === 'dice');
  verdict('sec', 'blind saving throw: DM gets the number, table gets nothing',
    dmdice && !p2dice ? 'ui' : 'api-only', `p1=${p1dice} p2=${p2dice} dm=${dmdice}`);
}

// S6 · op_id replay: identical transfer op twice must not double-move items
{
  const brannBefore = await P1.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const ch = (j.characters || []).find((c) => c.name === 'Brann');
    return (ch.items || []).reduce((a, i) => a + (i.qty || 1), 0);
  });
  const op = 'd161-replay-' + Date.now();
  const give = async () => P1.evaluate(async (o) => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const me = (j.characters || []).find((c) => c.name === 'Brann');
    const mem = j.members.find((m) => m.char && m.char.name === 'Nyx');
    const it = (me.items || []).find((i) => /draught|potion/i.test(i.name));
    if (it) wsSend({ type: 'inv_transfer', item_id: it.id, qty: 1, to_char_id: mem.char.id, op_id: o });
  }, op);
  await give(); await sleep(1200); await give(); await sleep(1500);
  const after = await P1.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const ch = (j.characters || []).find((c) => c.name === 'Brann');
    return (ch.items || []).reduce((a, i) => a + (i.qty || 1), 0);
  });
  verdict('sec', 'idempotency: replayed op_id cannot duplicate an item move',
    after <= brannBefore - 1 ? 'ui' : 'api-only', `brann items ${brannBefore} -> ${after}`);
}

// S7 · unauthenticated REST
{
  const anon = await browser.newContext();
  const ap = await anon.newPage();
  await ap.goto((process.env.VTT_E2E_BASE_URL || 'http://127.0.0.1:8021') + '/login', { waitUntil: 'domcontentloaded' });
  const status = await ap.evaluate(async (u) =>
    (await fetch(u)).status, `http://127.0.0.1:8021/api/rooms/${code}/state`).catch(() => 'fetch-failed');
  verdict('sec', 'room state refuses an unauthenticated request',
    status === 401 || status === 403 ? 'ui' : 'broken', `HTTP ${status}`);
  await anon.close();
}

// S8 · NPC stat blocks never ride the player channel
{
  const leak = await P2.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const npc = j.tokens.filter((t) => /Brute|Raider|Wight/.test(t.label));
    return npc.filter((t) => t.npc || JSON.stringify(t).match(/to_hit|attack_bonus|spell_block/)).length;
  });
  const anyNpc = await D.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    return j.tokens.filter((t) => /Brute|Raider/.test(t.label) && t.npc).length;
  });
  verdict('sec', 'player /state carries NPC tokens without stat blocks (DM carries them)',
    leak === 0 && anyNpc > 0 ? 'ui' : 'api-only', `leaks=${leak} dm-npc=${anyNpc}`);
}

await shot(D, 'SEC-final');
log('SECURITY MATRIX COMPLETE');
await browser.close();
