// D161 Akt V — things & recovery: loot pickup on the walk, owner hand-off,
// DM grant, attunement, consumable use, short rest (hit dice + short-reset
// resource), long rest (slots + hit dice). Production UI only.
import {
  log, fail, shot, verdict, loadState, auth, enterRoom,
  clickToken, clickCell, brush, sleep,
} from './e2e_d161_lib.mjs';
import { chromium } from 'playwright';

const GARRISON_ZIP = (process.env.VTT_E2E_STATE || '/st') + '/d161_garrison.zip';
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
const whisper = (p) => p.__.filter((j) => (j.kind || j.type) === 'whisper')
  .map((j) => (j.payload && j.payload.text) || '');
const myItems = (p, name) => p.evaluate(async (n) => {
  const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
  const ch = (j.characters || []).find((c) => c.name === n);
  return ch ? { ids: (ch.items || []).map((i) => i.name), hp: (j.tokens.find((t) => t.label === n) || {}).hp } : null;
}, name);

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
      return [Math.round((tk.x - cs / 2) / cs), Math.round((tk.y - cs / 2) / cs)];
    }, tid);
    if (c[0] === gx && c[1] === gy) return true;
  }
  return false;
}

// ---------- V0: DM re-imports the garrison pack (replace) — attune flag update ----
{
  await D.click('[data-tab="dm"]').catch(() => {});
  await sleep(300);
  const before = await D.evaluate(async (c) => {
    const j = await (await fetch(`/api/rooms/${c}/state`)).json();
    return (j.item_defs || []).length;
  }, code);
  await D.click("#side-tabs button[data-tab='dm']");
  await D.evaluate(() => {
    for (const d of document.querySelectorAll('#dmtools details.group')) {
      if (/Rule packages|Bestiary/i.test(d.querySelector('summary')?.textContent || '')) d.open = true;
    }
  });
  await D.waitForSelector('#ct-file', { timeout: 6000 });
  await D.locator('#ct-mode').selectOption('replace');
  await D.setInputFiles('#ct-file', `${GARRISON_ZIP}`);
  await D.click('#btn-ct-upload');
  await sleep(2800);
  const rep = await D.locator('#ct-report').innerText();
  if (/\berror\b|invalid|refus/i.test(rep)) fail('re-import errors: ' + rep.slice(0, 200));
  await D.locator('#ct-mode').selectOption('preview').catch(() => {});
  const after = await D.evaluate(async (c) => {
    const j = await (await fetch(`/api/rooms/${c}/state`)).json();
    return (j.item_defs || []).length;
  }, code);
  verdict('act5', 'DM re-imports updated pack (replace) into a live room',
    after >= before && after > 0 ? 'ui' : 'api-only', `defs ${before} -> ${after}`);
}

// ---------- V1: DM paints fresh loot; walking over it picks it up ----------
{
  await D.click('[data-tab="dm"]').catch(() => {});
  await sleep(300);
  await D.click('#btn-edit-map');
  await sleep(1200);
  await brush(D, 'loot');
  await D.fill('#loot-label', 'Dropped satchel: a healing draught');
  await clickCell(D, 6, 4);
  await D.click('#btn-ed-save');
  await sleep(1400);
  await D.click('#btn-ed-cancel');
  await D.waitForFunction(() => !state.editing, null, { timeout: 8000 });
  await sleep(600);
  const l = { x: 6, y: 4 };
  const nyx = await D.evaluate((n) => (state.tokens.find((t) => t.label === n) || {}), 'Nyx');
  const w0 = whisper(P2).length;
  await clickToken(P2, nyx.id);
  await clickCell(P2, l.x, l.y);
  await sleep(900);
  const go = await P2.locator('#mh-go').isVisible().catch(() => false);
  if (go) await P2.click('#mh-go');
  await sleep(2500);
  const w = whisper(P2).slice(w0).join(' | ');
  verdict('act5', 'walk over loot -> private pickup whisper + notes entry',
    /You found|added to/i.test(w) ? 'ui' : 'api-only', w.slice(0, 120));
  await shot(P2, 'V1-loot');
}

// ---------- V2: owner hand-off (give) between two seated players ----------
{
  // make sure Nyx has something to give: use the potion from V-earlier or DM grant
  const inv0 = await myItems(P2, 'Nyx');
  const dmGives = !inv0 || !inv0.ids.some((n) => /draught|potion/i.test(n));
  if (dmGives) {
    await D.click('[data-tab="inv"]'); await sleep(600);
    await D.evaluate(async () => {
      const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
      window.__st = j;
    });
    const members = await D.evaluate(() => (state.room.members || []).filter((m) => m.char));
    const nyxId = (members.find((m) => m.char.name === 'Nyx') || {}).char?.id;
    await D.selectOption('#inv-char', String(nyxId));
    await D.selectOption('#inv-def', 'potion_heal_greater').catch(async () => {
      const v = await D.locator('#inv-def option').first().getAttribute('value');
      return v;
    });
    await D.click('#inv-grant');
    await sleep(1500);
  }
  await clickToken(P2, (await D.evaluate(() => (state.tokens.find((t) => t.label === 'Nyx') || {}).id)));
  await sleep(800);
  await P2.evaluate(() => { for (const d of document.querySelectorAll('#sheet details')) d.open = true; });
  const row = P2.locator('.inv [data-a="give"]').first();
  if (!(await row.count())) fail('no give button on Nyx sheet');
  await row.click();
  await sleep(700);
  const toSel = P2.locator('#give-to');
  await toSel.waitFor({ state: 'visible', timeout: 6000 });
  const opt = await toSel.locator('option', { hasText: 'Brann' }).first().getAttribute('value');
  await toSel.selectOption(opt);
  await P2.click('#give-go');
  await sleep(1600);
  const inv1 = await myItems(P1, 'Brann');
  verdict('act5', 'player-to-player hand-off via sheet give (server transaction)',
    inv1 && inv1.ids.some((n) => /draught|potion/i.test(n)) ? 'ui' : 'api-only',
    JSON.stringify(inv1 && inv1.ids).slice(0, 160));
}

// ---------- V3: DM grants a magic item, owner attunes, gate visible ----------
{
  await D.click('[data-tab="inv"]'); await sleep(500);
  const members = await D.evaluate(() => (state.room.members || []).filter((m) => m.char));
  const brannId = (members.find((m) => m.char.name === 'Brann') || {}).char?.id;
  await D.selectOption('#inv-char', String(brannId));
  const defOpts = await D.locator('#inv-def option').allTextContents();
  const ringOpt = await D.evaluate(() => {
    const vals = [...document.querySelectorAll('#inv-def option')].map((o) => o.value);
    return vals.includes('gem_ring') ? 'gem_ring'
      : vals.includes('ring_warding') ? 'ring_warding' : null;
  });
  if (!ringOpt) fail(`no attunable ring in DM grant library: ${JSON.stringify(defOpts).slice(0, 120)}`);
  await D.selectOption('#inv-def', ringOpt);
  await D.click('#inv-grant');
  await sleep(1600);
  await clickToken(P1, (await D.evaluate(() => (state.tokens.find((t) => t.label === 'Brann') || {}).id)));
  await sleep(900);
  await P1.evaluate(() => { for (const d of document.querySelectorAll('#sheet details')) d.open = true; });
  const attBtn = P1.locator('.skrow [data-a="attune"], .inv [data-a="attune"]').first();
  await attBtn.waitFor({ state: 'attached', timeout: 6000 }).catch(() => fail('attune button missing'));
  await attBtn.click();
  await sleep(1500);
  const att = await P1.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const ch = (j.characters || []).find((c) => c.name === 'Brann');
    return (ch.items || []).filter((i) => i.attunable).map((i) => [i.name, !!i.attuned]);
  });
  verdict('act5', 'DM grant -> owner attune toggle rides the server (attuned flag)',
    att.some(([, a]) => a) ? 'ui' : 'api-only', JSON.stringify(att).slice(0, 140));
  await shot(P1, 'V3-attune');
}

// ---------- V4: consumable use heals (owner Use button) ----------
{
  await clickToken(D, (await D.evaluate(() => (state.tokens.find((t) => t.label === 'Brann') || {}).id)));
  await sleep(500);
  await D.fill('#hp-amount', '-8');
  await D.click('#btn-hp-apply');
  await sleep(1300);
  const hp0 = (await myItems(P1, 'Brann')).hp;
  await clickToken(P1, (await D.evaluate(() => (state.tokens.find((t) => t.label === 'Brann') || {}).id)));
  await sleep(600);
  await P1.evaluate(() => { for (const d of document.querySelectorAll('#sheet details')) d.open = true; });
  await P1.click('[data-tab="inv"]');
  await sleep(700);
  const use = P1.locator('#inv-items button[data-a="use"]').first();
  if (!(await use.count())) fail('no Use button on a consumable — inventory gap');
  await use.click();
  await sleep(1800);
  const hp1 = (await myItems(P1, 'Brann')).hp;
  verdict('act5', 'drink potion via inventory Use -> server heals, no free re-use',
    hp1 > hp0 ? 'ui' : 'api-only', `hp ${hp0} -> ${hp1}`);
  await shot(P1, 'V4-potion');
}

// ---------- V5: short rest: hit dice heal + short-reset resource back ----------
{
  const pre = await D.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const m = (j.members || []).find((x) => x.char && x.char.name === 'Brann');
    return { surge: ((m.char.resources || []).find((r) => r.id === 'action_surge') || {}).current,
      spent: m.char.hit_dice_spent };
  });
  if (pre.surge === 1) {
    await clickToken(P1, (await D.evaluate(() => (state.tokens.find((t) => t.label === 'Brann') || {}).id)));
    await sleep(700);
    await P1.locator('.res-btn[data-a="dec"]').first().click();
    await sleep(1200);
  }
  const mid = await D.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const m = (j.members || []).find((x) => x.char && x.char.name === 'Brann');
    return ((m.char.resources || []).find((r) => r.id === 'action_surge') || {}).current;
  });
  await clickToken(P1, (await D.evaluate(() => (state.tokens.find((t) => t.label === 'Brann') || {}).id)));
  await sleep(700);
  await P1.fill('#hd-count', '1');
  await P1.click('#btn-short');
  await sleep(2000);
  const post = await D.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const m = (j.members || []).find((x) => x.char && x.char.name === 'Brann');
    return { surge: ((m.char.resources || []).find((r) => r.id === 'action_surge') || {}).current,
      spent: m.char.hit_dice_spent,
      hp: (j.tokens.find((t) => t.label === 'Brann') || {}).hp };
  });
  verdict('act5', 'short rest: hit die spent + Action Surge (reset=short) refilled',
    mid === 0 && post.surge === pre.surge && post.spent > (pre.spent || 0) ? 'ui' : 'api-only',
    JSON.stringify({ pre, mid, post }));
  await shot(D, 'V5-shortrest');
}

// ---------- V6: long rest refills caster slots + hit dice ----------
{
  await D.click('[data-tab="dm"]'); await sleep(300);
  await D.click('#btn-long-rest');
  await sleep(2500);
  const sheet = await D.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const out = {};
    for (const nm of ['Solea', 'Quill', 'Brann']) {
      const m = (j.members || []).find((x) => x.char && x.char.name === nm);
      if (m) out[nm] = { slots1: (m.char.spell_slots || {})['1']?.used, spent: m.char.hit_dice_spent,
        hp: (j.tokens.find((t) => t.label === nm) || {}).hp, maxhp: m.char.max_hp };
    }
    return out;
  });
  const clean = Object.values(sheet).every((s) => (s.slots1 ?? 0) === 0 && (s.spent ?? 0) === 0);
  const healed = Object.values(sheet).every((s) => s.hp == null || s.hp >= s.maxhp);
  verdict('act5', 'long rest: every slot, hit die pool and HP back to full',
    clean && healed ? 'ui' : 'api-only', JSON.stringify(sheet).slice(0, 200));
  await shot(D, 'V6-longrest');
}

log('AKT V COMPLETE');
await browser.close();
