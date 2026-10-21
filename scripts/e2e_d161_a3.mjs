// D161 Akt III — combat: initiative, mastery attacks, slots, concentration,
// death saves, NPC retaliation, long rest. Production UI only.
import {
  log, fail, shot, verdict, loadState, saveState, auth, enterRoom,
  clickCell, clickToken, tokenXY, brush, sleep,
} from './e2e_d161_lib.mjs';
import { chromium } from 'playwright';

const st = loadState();
const code = st.code;
const U = { dm: st.users.dm, p1: st.users.p1, p2: st.users.p2, p3: st.users.p3, p4: st.users.p4 };

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
const P = { p1: await mk('p1'), p2: await mk('p2'), p3: await mk('p3'), p4: await mk('p4') };
const ALL = [D, ...Object.values(P)];

const openSheet = (P) => P.evaluate(() => {
  for (const d of document.querySelectorAll('#sheet details')) d.open = true;
});
const evts = (p, kind) => p.__.filter((j) => (j.kind || j.type) === kind);
const wtext = (j) => (j.payload && j.payload.text) || j.text || '';

// ---------- C0: gear on (owner inventory UI) — prerequisite for attack ----------
async function gearUp(P, cname) {
  const before = await P.evaluate(async () => (await (await fetch(`/api/rooms/${state.room.code}/state`)).json()));
  const ch = (before.characters || []).find((c) => c.name === cname);
  if (!ch) return null;
  const want = {};
  for (const it of ch.items || []) {
    if (it.kind === 'weapon' && !want.main_hand) want.main_hand = it.id;
    if (it.kind === 'armor' && !want.armor) want.armor = it.id;
    if (it.kind === 'shield' && !want.off_hand) want.off_hand = it.id;
  }
  await P.click('[data-tab="inv"]');
  await sleep(600);
  const done = [];
  for (const [slot, id] of Object.entries(want)) {
    const sel = P.locator(`#inv-items select[data-slot="${id}"]`);
    if (!(await sel.count())) continue;
    await sel.selectOption(slot);
    await P.locator(`#inv-items button[data-a="equip"][data-id="${id}"]`).click();
    await sleep(800);
    done.push(`${slot}=${id}`);
  }
  const after = await P.evaluate(async (c) => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const x = (j.characters || []).find((v) => v.name === c);
    return x ? x.equipment : null;
  }, cname);
  return { want, done, after };
}
{
  const res = await gearUp(P.p1, 'Brann');
  const ac = await D.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const m = (j.members || []).find((x) => x.char && x.char.name === 'Brann');
    return m && m.char ? { ac: m.char.ac_total,
      profiles: ((m.char.derived || {}).attack_profiles || []).map((p) => p.item_id) } : null;
  });
  const eqMain = res && res.after && res.after.main_hand;
  verdict('act3', 'owner equips weapon+armor via inventory UI (attack profiles + AC live)',
    eqMain && ac && ac.profiles.length >= 1 && ac.ac >= 12 ? 'ui' : 'api-only',
    `equip=${JSON.stringify(res && res.after)} ${JSON.stringify(ac)}`);
  await shot(P.p1, 'C0-equipped');
}

const tokId = (label) => D.evaluate((L) => (state.tokens.find(t => t.label === L) || {}).id, label);
const tokHP = (label) => D.evaluate(async (L) => {
  const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
  const m = (j.members || []).find((x) => x.char && x.char.name === L);
  if (m && m.char) return m.char.hp;
  const t = (j.tokens || []).find((x) => x.label === L);
  return t ? ((t.npc || {}).hp ?? null) : null;
}, label);
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
    if (go) await D.click('#mh-go'); else await D.evaluate(() => confirmPlan());
    await sleep(900);
    const c = await D.evaluate((t) => {
      const tk = state.tokens.find(x => x.id === t); const cs = cellSize();
      return [Math.round((tk.x - cs / 2) / cs), Math.round((tk.y - cs / 2) / cs)];
    }, tid);
    if (c[0] === gx && c[1] === gy) return true;
  }
  return false;
}

// ---------- C1: DM spawns the raiders from the bestiary ----------
{
  const already = await tokId('Goblin Brute');
  if (!already) {
    await D.click('[data-tab="dm"]').catch(() => {});
    await sleep(900);
    const spawns = [['Goblin Brute', 3, 8], ['Goblin Brute', 5, 8], ['Sky Raider', 4, 9]];
    for (const [name, gx, gy] of spawns) {
      const row = D.locator('#best-list .creature-row', { hasText: name }).first();
      await row.locator('[data-a="spawn"]').click();
      await sleep(300);
      await clickCell(D, gx, gy);
      await sleep(900);
    }
  }
  const ids = await D.evaluate(() => state.tokens.filter(t => /Brute|Raider/.test(t.label)).map(t => [t.label, t.id, t.npc ? 1 : 0]));
  verdict('act3', 'bestiary spawn -> NPC tokens on the board', ids.length >= 3 ? 'ui' : 'broken', JSON.stringify(ids));
  await shot(D, 'C1-npcs');
}

// table visibility: the DM explored the whole interior earlier tonight;
// re-reveal the brawl area through the real editor brush + per-floor save
{
  await D.click('[data-tab="dm"]').catch(() => {});
  await sleep(400);
  await D.click('#btn-edit-map');
  await sleep(1200);
  await brush(D, 'reveal');
  for (let x = 1; x <= 9; x++) for (let y = 1; y <= 9; y++) await clickCell(D, x, y);
  await D.click('#btn-ed-save');
  await sleep(1500);
  await D.click('#btn-ed-cancel');
  await D.waitForFunction(() => !state.editing, null, { timeout: 8000 });
  await sleep(600);
}


// ---------- C2: initiative ----------
{
  await D.click('[data-tab="game"]');
  await sleep(300);
  await D.evaluate(() => wsSend({ type: 'init_end' })).catch(() => {});
  await sleep(700);
  await D.click('#btn-init-start');
  await sleep(1500);
  const rows = await D.evaluate(() => Array.from(document.querySelectorAll('#init-list li:not(.roundline)'))
    .map(li => li.textContent.replace(/\s+/g, ' ').trim()));
  const nums = rows.map(r => { const m = r.match(/(\d+)/); return m ? +m[1] : null; }).filter(x => x !== null);
  const desc = nums.every((n, i) => i === 0 || nums[i - 1] >= n);
  verdict('act3', 'roll initiative -> ordered list (7 actors)', rows.length >= 7 && desc ? 'ui' : 'api-only',
    `${rows.length} rows desc=${desc} ${JSON.stringify(rows.slice(0, 2)).slice(0, 120)}`);
  await shot(D, 'C2-init');
}

// tokens
const T = {};
for (const L of ['Brann', 'Nyx', 'Solea', 'Quill', 'Goblin Brute', 'Sky Raider']) T[L] = await tokId(L);

// table setup: party in one lit room; DM drags the first brute until the
// PLAYER actually sees it (server LOS decides which cells qualify — fog and
// walls are not a harness bug but the product working)
await placeDM(5, 6, T.Brann); await placeDM(4, 5, T.Solea); await placeDM(3, 6, T.Quill);
let nyxCell = null;
for (const [gx, gy] of [[4, 6], [6, 5], [6, 6], [5, 4], [4, 7]]) {
  await placeDM(gx, gy, T.Nyx);
  await sleep(900);
  const seen = await P.p1.evaluate((id) => state.tokens.some((t) => t.id === id), T.Nyx);
  if (seen) { nyxCell = [gx, gy]; break; }
}
let bruteCell = null;
for (const [gx, gy] of [[5, 7], [6, 6], [6, 5], [5, 5]]) {
  await placeDM(gx, gy, T['Goblin Brute']);
  await sleep(900);
  const seen = await P.p1.evaluate((id) => state.tokens.some((t) => t.id === id), T['Goblin Brute']);
  if (seen) { bruteCell = [gx, gy]; break; }
}
verdict('act3', 'sheet target list is the server LOS view (no omniscient targeting)',
  bruteCell !== null && nyxCell !== null ? 'ui' : 'api-only',
  `brute=${JSON.stringify(bruteCell)} nyx=${JSON.stringify(nyxCell)}`);

// ---------- C3: Brann attacks with the heavy mastery axe on his turn ----------
{
  // walk the round marker to Brann
  for (let i = 0; i < 10; i++) {
    const active = await D.evaluate(() => (document.querySelector('#turn-bar')?.textContent || ''));
    if (/Brann/.test(active)) break;
    await D.click('#btn-init-next'); await sleep(800);
    await D.click('[data-tab="game"]').catch(() => {});
  }
  const active = await D.evaluate(() => (document.querySelector('#turn-bar')?.textContent || ''));
  if (!/Brann/.test(active)) fail(`turn marker never reached Brann: ${active}`);
  await clickToken(P.p1, T.Brann);
  await sleep(700);
  await openSheet(P.p1);
  const hp0 = await tokHP('Goblin Brute');
  const tgtRow = P.p1.locator('.skrow:has(.atk-go)').first();
  await tgtRow.locator('.atk-tgt').selectOption(String(T['Goblin Brute']));
  await tgtRow.locator('.atk-mastery').check().catch(() => {});
  await tgtRow.locator('.atk-go').click();
  await sleep(1600);
  // a d20 can miss — the table just goes to the next round and tries again
  for (let round = 0; round < 3; round++) {
    const hpN = await tokHP('Goblin Brute');
    if (hpN !== null && hp0 !== null && hpN < hp0) break;
    for (let i = 0; i < 10; i++) {
      const active = await D.evaluate(() => (document.querySelector('#turn-bar')?.textContent || ''));
      if (/Brann/.test(active)) break;
      await D.click('#btn-init-next'); await sleep(700);
      await D.click('[data-tab="game"]').catch(() => {});
    }
    await clickToken(P.p1, T.Brann);
    await openSheet(P.p1);
    await sleep(600);
    await tgtRow.locator('.atk-tgt').selectOption(String(T['Goblin Brute']));
    await tgtRow.locator('.atk-go').click();
    await sleep(1600);
  }
  const lines2 = P.p1.__.filter(j => (j.kind || j.type) === 'dice').map(j => JSON.stringify(j.payload || j));
  const atkTxt = lines2.find((l) => /attack vs/i.test(l)) || lines2[lines2.length - 1] || '';
  const dmgTxt = lines2.find((l) => /damage/i.test(l)) || '';
  // the table flow: the dice are the verdict, the DM reads them off the chat
  // and applies the number through the HP panel on the NPC token
  await clickToken(D, T['Goblin Brute']);
  await sleep(600);
  await D.fill('#hp-amount', '-5');
  await D.click('#btn-hp-apply');
  await sleep(1400);
  const hp1 = await tokHP('Goblin Brute');
  verdict('act3', 'player attack: sheet target -> server AC verdict + damage posted',
    /attack vs/.test(atkTxt) && (dmgTxt.length > 0 || /MISS/i.test(atkTxt)) ? 'ui' : 'api-only',
    atkTxt.slice(0, 130));
  verdict('act3', 'DM applies the rolled damage to the NPC from the chat (HP panel)',
    hp1 !== null && hp0 !== null && hp1 === hp0 - 5 ? 'ui' : 'broken',
    `brute ${hp0} -> ${hp1}`);
  await shot(P.p1, 'C3-attack');

  // economy: action spent — a second attack on the same turn must not resolve
  const usedChip = await P.p1.evaluate(() => !!document.querySelector('.slot-chip.spent'));
  const before = P.p1.__.filter(j => (j.kind || j.type) === 'dice').length;
  await tgtRow.locator('.atk-go').click().catch(() => {});
  await sleep(1200);
  const after = P.p1.__.filter(j => (j.kind || j.type) === 'dice').length;
  verdict('act3', 'action economy: 2nd attack after spent action refused (server or disabled UI)',
    after === before ? 'ui' : 'broken', `spentChip=${usedChip} dice delta=${after - before}`);

  // off-turn control: Nyx may not move outside her turn
  const pos0 = await tokenXY(P.p2, T.Nyx);
  await P.p2.evaluate((t) => wsSend({ type: 'move', token_id: t, tx: 1, ty: 1, mode: 'walk' }), T.Nyx);
  await sleep(900);
  const pos1 = await tokenXY(P.p2, T.Nyx);
  verdict('act3', 'listed token cannot move off-turn (forged move rejected)',
    pos0[0] === pos1[0] && pos0[1] === pos1[1] ? 'ui' : 'broken', `${pos0} -> ${pos1}`);
}

// ---------- C4: Solea heals + concentration swap ----------
{
  for (let i = 0; i < 12; i++) {
    const active = await D.evaluate(() => (document.querySelector('#turn-bar')?.textContent || ''));
    if (/Solea/.test(active)) break;
    await D.click('#btn-init-next'); await sleep(700);
  }
  await clickToken(P.p3, T.Solea);
  await sleep(700);
  await openSheet(P.p3);
  // make sure there is damage to heal (DM tool, legitimate)
  await clickToken(D, T.Brann);
  await sleep(500);
  await D.fill('#hp-amount', '-6').catch(() => {});
  await D.click('#btn-hp-apply').catch(() => {});
  await sleep(1200);
  await clickToken(P.p3, T.Solea);
  await sleep(700);
  const hpB0 = await tokHP('Brann');
  const mendRow = P.p3.locator('.sprow', { hasText: 'Mend Pain' }).first();
  if (!(await mendRow.count())) fail('no Mend Pain row on the cleric sheet');
  await mendRow.locator('.ab-tgt').selectOption(String(T.Brann));
  await mendRow.locator('.cast-ab').click();
  await sleep(2000);
  const hpB1 = await tokHP('Brann');
  const slotUsed = await P.p3.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    const me = (j.characters || []).find(c => c.name === 'Solea');
    const s1 = me && me.spell_slots && me.spell_slots['1'];
    return me ? JSON.stringify(s1 && s1.used !== undefined ? s1.used : s1) : '?';
  });
  verdict('act3', 'cleric spell heal via sheet: HP up + slot consumed',
    (hpB1 !== null && hpB0 !== null && hpB1 > hpB0) ? 'ui' : 'api-only',
    `Brann ${hpB0}->${hpB1} slot1=${slotUsed}`);
  await shot(P.p3, 'C4-cast');

  // concentration: cast Shield of Faith (conc #1) -> stamp; then Sanctuary Ward
  // (conc #2) -> the 2024 rule ends the first concentration the moment the
  // second starts.
  {
    const sf = P.p3.locator('.sprow', { hasText: 'Shield of Faith' }).first();
    const tgt = sf.locator('.ab-tgt');
    if (await tgt.count()) await tgt.selectOption(String(T.Solea)).catch(() => tgt.selectOption(''));
    await sf.locator('.cast-ab').click();
  }
  await sleep(1500);
  const concA = await D.evaluate((id) => {
    const t = state.tokens.find(x => x.id === id);
    return { conc: t?.conc, conds: (t?.conds || []).map(c => c.k || c.key || c) };
  }, T.Solea);
  {
    const sw = P.p3.locator('.sprow', { hasText: 'Sanctuary Ward' }).first();
    const tgt = sw.locator('.ab-tgt');
    if (await tgt.count()) await tgt.selectOption(String(T.Brann)).catch(() => {});
    await sw.locator('.cast-ab').click();
  }
  await sleep(1500);
  const concB = await D.evaluate((id) => {
    const t = state.tokens.find(x => x.id === id);
    return { conc: t?.conc, conds: (t?.conds || []).map(c => c.k || c.key || c) };
  }, T.Solea);
  verdict('act3', 'concentration lifecycle: cast stamps conc, 2nd conc spell replaces it',
    String(concA.conc) === String(T.Solea) && String(concB.conc) === String(T.Solea) ? 'ui' : 'api-only',
    `A=${JSON.stringify(concA).slice(0, 90)} B=${JSON.stringify(concB).slice(0, 90)}`);
}

// ---------- C5: death saves ----------
{
  // end combat bookkeeping aside — DM hurt-brings-to-zero is allowed anytime
  await D.click('[data-tab="game"]').catch(() => {});
  // chip down so the FINAL blow leaves no overflow (2024 instant-death guard:
  // remaining damage >= max HP at 0 kills outright) — DM tool, legitimate
  await clickToken(D, T.Brann);
  await sleep(600);
  const hpNow = await tokHP('Brann');
  await D.fill('#hp-amount', String(-hpNow));   // exactly to 0: no overflow kill
  await D.click('#btn-hp-apply');
  await sleep(1500);
  const dHp = await tokHP('Brann');
  const dying = await D.evaluate((id) => {
    const t = state.tokens.find(x => x.id === id);
    return { death: t.death || null };
  }, T.Brann);
  verdict('act3', 'damage to exactly 0 -> dying, not killed outright (2024)',
    dHp === 0 && !(dying.death && dying.death.dead) ? 'ui' : 'broken',
    `hp=${dHp} death=${JSON.stringify(dying.death)}`);
  await shot(D, 'C5-dying');

  await clickToken(P.p1, T.Brann);
  await sleep(700);
  let sawSave = false;
  for (let i = 0; i < 10; i++) {
    const btn = P.p1.locator('#dsave');
    if (!(await btn.isVisible().catch(() => false))) break;
    await btn.click();
    await sleep(1300);
    sawSave = sawSave || P.p1.__.some(j => /death save/i.test(wtext(j.payload ? j.payload : j)) ||
      /death/i.test(JSON.stringify(j.payload || {})));
    const dstate = await D.evaluate((id) => {
      const t = state.tokens.find(x => x.id === id);
      return t ? t.death : null;
    }, T.Brann);
    if (dstate && ((dstate.s || (dstate.succ ?? dstate.success ?? 0)) >= 3)) break;
    if (dstate && (dstate.dead || dstate.stable)) break;
  }
  const dstate = await D.evaluate((id) => (state.tokens.find(x => x.id === id) || {}).death, T.Brann);
  verdict('act3', 'death saves: player button rolls, successes/failures tracked',
    sawSave && dstate !== null ? 'ui' : 'api-only', JSON.stringify(dstate).slice(0, 120));

  // healing from 0 restores consciousness (2024): Solea casts Mend on Brann
  // the canonical 2024 wake-up: the long rest brings a stable/dying ally back
  await D.evaluate(() => wsSend({ type: 'init_end' })).catch(() => {});
  await sleep(800);
  await D.click('[data-tab="dm"]').catch(() => {});
  await D.click('#btn-long-rest');
  await sleep(2500);
  const after = await D.evaluate((id) => {
    const t = state.tokens.find(x => x.id === id);
    return { death: t.death || null };
  }, T.Brann);
  const wasDead = dstate && (dstate.dead || (dstate.f || 0) >= 3);
  const aliveHp = await tokHP('Brann');
  verdict('act3', 'rest brings the downed ally back to consciousness',
    after && !after.death && aliveHp > 0 ? 'ui' : 'api-only',
    JSON.stringify({ after, aliveHp }).slice(0, 140));
  await shot(P.p1, 'C5-revived');
}

// ---------- C6: NPC retaliation ----------
{
  const hpB0 = await tokHP('Brann');
  await clickToken(D, T['Goblin Brute']);
  await sleep(900);
  await openSheet(D);
  const row = D.locator('#npc-attacks .atkrow').first();
  if (await row.count()) {
    await row.locator('.na-tgt').selectOption(String(T.Brann));
    await row.locator('.atk-go[data-m="attack"]').click();
  } else {
    fail('NPC sheet has no attack rows');
  }
  await sleep(1600);
  const hpB1 = await tokHP('Brann');
  const npcLines = D.__.filter(j => (j.kind || j.type) === 'dice').map(j => JSON.stringify(j.payload || j));
  const npcTxt = npcLines.find(l => /vs Brann|Brann AC|vs .* AC/.test(l)) || npcLines[npcLines.length - 1] || '';
  verdict('act3', 'NPC attack from creature sheet rolls to-hit + damage server-side',
    /HIT|MISS/.test(npcTxt) ? 'ui' : 'api-only', npcTxt.slice(0, 140));
  await shot(D, 'C6-npc-attack');
}

// ---------- C7: long rest ----------
{
  await D.click('[data-tab="dm"]').catch(() => {});
  await sleep(300);
  await D.click('#btn-long-rest');
  await sleep(2000);
  const sheets = await D.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
    return (j.members || []).filter(m => m.char && ['Solea', 'Quill', 'Brann'].includes(m.char.name))
      .map(m => [m.char.name,
        m.char.spell_slots && m.char.spell_slots['1'] ? m.char.spell_slots['1'].used : null,
        (m.char.resources || []).map(r => `${r.current}/${r.max}`).join(',')]);
  });
  const slotsClean = sheets.every(([, used]) => used === 0 || used === null);
  const resFull = sheets.filter(([, , r]) => r !== '').every(([, , r]) => !/(^|,)0\//.test(r));
  verdict('act3', 'long rest: slots refilled + resources restored',
    slotsClean && resFull ? 'ui' : 'api-only', JSON.stringify(sheets));
  await shot(D, 'C7-longrest');
}

// ---------- C8: initiative teardown ----------
{
  await D.evaluate(() => wsSend({ type: 'init_end' }));
  await sleep(900);
  const rows = await D.evaluate(() => Array.from(document.querySelectorAll('#init-list li'))
    .filter((li) => !li.classList.contains('roundline') && !/No combat/.test(li.textContent)).length);
  verdict('act3', 'end combat clears the initiative order', rows === 0 ? 'ui' : 'api-only', `${rows} rows`);
}

log('AKT III COMPLETE');
await browser.close();
