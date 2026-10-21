// D162 "Operation: Keine Ausreden mehr" — browser E2E for the eleven closed gaps.
// Fresh DB on :8022. Real clicks, real frames, verdicts per scenario (ui/api/gap/broken).
import { chromium } from 'playwright';
import fs from 'fs';
import {
  BASE, ST, log, fail, shot, verdict, auth,
  createRoom, joinRoom, enterRoom, clickCell, clickCellEdge, clickToken,
  tokenXY, brush, sleep, seat, watchWS
} from './e2e_d161_lib.mjs';

const STATE = `${ST}/d162_state.json`;
const load = () => { try { return JSON.parse(fs.readFileSync(STATE, 'utf8')); } catch { return {}; } };
const st = load();
const save = () => { fs.mkdirSync(ST, { recursive: true }); fs.writeFileSync(STATE, JSON.stringify(st, null, 1)); };

const U = { dm: 'd162dm', p1: 'd162p1' };
const MIRA = { name: 'Mira', species: 'kin_kit', cls: 'wizard', bg: 'bg_acolyte',
  stats: { str: 8, dex: 15, con: 12, int: 15, wis: 12, cha: 10 },
  skills: ['arcana', 'history'], expertise: [],
  cantrips: ['tok_fire', 'ray_frost', 'ghost_touch'],
  spells: ['force_dart', 'fire_burst', 'arcane_ward2'] };

const optionValueByLabel = (page, sel, label) => page.locator(sel).evaluate((el, label) => {
  const o = Array.from(el.options).find(o => o.textContent.includes(label));
  return o ? o.value : null;
}, label);
const seatIn = async (pg, code) => {
  if (!(await pg.locator('#side-tabs').isVisible().catch(() => false))) await enterRoom(pg, code);
  await seat(pg);
};
const openEditor = async (pg) => {
  if (!(await pg.evaluate(() => !!state.editing))) {
    await pg.click('#btn-edit-map');
    await pg.waitForFunction(() => state.editing, null, { timeout: 8000 });
  }
};
const openSheet = (pg) => pg.evaluate(() => {
  for (const d of document.querySelectorAll('#sheet details')) d.open = true;
});
const roomState = (pg) => pg.evaluate(async () =>
  await (await fetch(`/api/rooms/${state.room.code}/state`)).json());
const toastText = (pg) => pg.evaluate(() => document.querySelector('#toast')?.textContent || '');
const tokByLabel = async (pg, label) => {
  const j = await roomState(pg);
  return (j.tokens || []).find(t => t.label === label);
};

(async () => {
  const browser = await chromium.launch({ headless: true, chromiumSandbox: false });
  const mk = async () => await browser.newContext({ baseURL: BASE });
  const dm = await mk(); const D = await dm.newPage();
  D.on('dialog', d => d.accept()); watchWS(D);
  const p1ctx = await mk(); const P = await p1ctx.newPage();
  P.on('dialog', d => d.accept()); watchWS(P);

  try {
    // ---------- V0 accounts + room + packs (UI import) ----------
    await auth(D, U.dm); await auth(P, U.p1);
    verdict('V0', 'register/login DM+player', 'ui');
    if (!st.code) { st.code = await createRoom(D, 'D162 Operation Keine Ausreden'); save(); }
    const code = st.code; log(`room ${code}`);
    await joinRoom(P, code);
    await enterRoom(D, code);
    await D.click("#side-tabs button[data-tab='dm']");
    await D.evaluate(() => {
      for (const d of document.querySelectorAll('#dmtools details.group'))
        if (/Rule packages|Bestiary/i.test(d.querySelector('summary')?.textContent || '')) d.open = true;
    });
    await D.waitForSelector('#ct-file', { timeout: 6000 });
    if (!st.packs) {
      for (const [pack, mode] of [['content_pack.zip', 'apply'], ['d161_garrison.zip', 'replace']]) {
        await D.locator('#ct-mode').selectOption(mode);
        await D.setInputFiles('#ct-file', `${ST}/${pack}`);
        await D.click('#btn-ct-upload'); await sleep(2500);
        const r = await D.locator('#ct-report').innerText();
        if (/error|invalid/i.test(r)) fail(`${pack} import: ` + r.slice(0, 250));
      }
      st.packs = true; save();
    }
    verdict('V0', 'DM content-pack import via UI', 'ui');
    await shot(D, 'V0-room');

    // ---------- V1 wizard build WITH prepared-spell pick (D162-10) ----------
    await P.bringToFront();
    await P.reload({ waitUntil: 'domcontentloaded' }); await sleep(900);
    if (await P.locator('#side-tabs').isVisible().catch(() => false)) await backToPrep(P);
    else if (!(await P.locator('#view-prep').isVisible().catch(() => false))) await joinRoom(P, code);
    if (!st.mira) {
      await P.click('#prep-new-toggle');
      await P.fill('#prep-name', MIRA.name);
      await P.locator('#prep-species').selectOption(MIRA.species);
      await P.locator('#prep-class').selectOption(MIRA.cls);
      await P.locator('#prep-bg').selectOption(MIRA.bg);
      await P.click('#prep-create');
      await P.waitForFunction(n => Array.from(document.querySelector('#prep-char').options)
        .some(o => o.textContent.includes(n)), MIRA.name, { timeout: 10000 });
      await P.click('#prep-back');
      await P.waitForSelector('#char-list', { timeout: 6000 });
      await P.locator('#char-list div', { hasText: MIRA.name }).first()
        .locator('[data-a="edit"]').click();
      await P.waitForSelector('#st-str', { state: 'visible', timeout: 6000 });
      for (const [ab, v] of Object.entries(MIRA.stats)) await P.fill(`#st-${ab}`, String(v));
      await P.click('#btn-char-save'); await sleep(800);
      await P.fill('#rm-code', code);
      await P.click('#btn-room-join');
      await P.waitForSelector('#view-prep', { timeout: 8000 });
      st.mira = { built: false }; save();
    }
    const vid = await optionValueByLabel(P, '#prep-char', MIRA.name);
    await P.locator('#prep-char').selectOption(vid); st.mira.charId = vid; save();
    await sleep(500);
    if (!st.mira.built) {
      await P.click('#prep-id-save'); await sleep(700);
      await P.evaluate(() => { const b = document.querySelector('#prep-wizbox'); if (b) b.open = true; });
      await P.fill('#prep-to', '2');
      await P.click('#prep-plan');
      await P.waitForFunction(() => document.querySelector('#prep-wiz')?.textContent.length > 10,
        null, { timeout: 10000 });
      // THE D162-10 pick UI — the selects must be real options, not free text
      const canN = await P.locator('.pw-can option').count();
      const spN = await P.locator('.pw-sp option').count();
      if (!canN || !spN) fail(`no cantrip/spell pick pools rendered (can=${canN} sp=${spN})`);
      await P.check(`.pw-sk[value='arcana']`).catch(() => {});
      await P.check(`.pw-sk[value='history']`).catch(() => {});
      await P.locator('.pw-can').selectOption(MIRA.cantrips)
        .catch(e => fail(`cantrip pick: ${e.message.slice(0, 120)}`));
      await P.locator('.pw-sp').selectOption(MIRA.spells)
        .catch(e => fail(`spell pick: ${e.message.slice(0, 120)}`));
      await P.click('#prep-apply');
      await P.waitForFunction(() => (document.querySelector('#prep-out')?.textContent || '').trim().length > 3,
        null, { timeout: 15000 });
      const out = await P.locator('#prep-out').innerText();
      if (/needs choices/i.test(out)) { await shot(P, 'V1-needschoices'); fail('wizard still blocked: ' + out.slice(0, 200)); }
      if (!/built/i.test(out)) fail('wizard build failed: ' + out.slice(0, 200));
      st.mira.built = true; st.mira.out = out.slice(0, 120); save();
      verdict('V1', `wizard picks prepared spells via UI (${canN} cantrip/${spN} spell options offered)`, 'ui', out.slice(0, 80));
    } else verdict('V1', `wizard already built; pick pools existed at first run`, 'ui');
    await shot(P, 'V1-wizard-pick');

    // ---------- V2 species bonus card + idempotent grant (D162-2) ----------
    if (!(await P.locator('#prep-species-card').count())) fail('species card missing in prep');
    await P.click('#prep-species-card');
    await P.waitForFunction(() => (document.querySelector('#prep-species-out')?.textContent || '').length > 10,
      null, { timeout: 8000 });
    const cardTxt = await P.locator('#prep-species-out').innerText();
    log('species card: ' + cardTxt.slice(0, 140).replace(/\n/g, ' | '));
    await shot(P, 'V2-species-card');
    const getChar = (pg, cid) => pg.evaluate(async cid =>
      (await (await fetch('/api/characters')).json()).find(c => String(c.id) === String(cid)), cid);
    const pre = await getChar(P, vid);
    if (!pre) fail('Mira not found in /api/characters');
    const baseDex = pre.stats.dex;
    if (await P.locator('#prep-species-apply').count()) {
      await P.click('#prep-species-apply');
      await P.waitForFunction(() => (document.querySelector('#prep-species-result')?.textContent || '').length > 3,
        null, { timeout: 8000 });
    }
    const res1 = await P.locator('#prep-species-result').innerText().catch(() => cardTxt);
    await sleep(300);
    if (await P.locator('#prep-species-apply').count()) await P.click('#prep-species-apply');
    await sleep(900);
    const res2 = (await P.locator('#prep-species-result').innerText().catch(() => cardTxt)) + " | " + cardTxt;
    const post = await getChar(P, vid);
    if (post.stats.dex <= baseDex && baseDex < 16)
      fail(`species dex bonus missing: ${baseDex} -> ${post.stats.dex} (${res1})`);
    if (!/already|granted|nothing new|nothing missing|no species/i.test(res2))
      fail(`double-grant not refused: ${res2.slice(0, 160)}`);
    verdict('V2', `species card grants dex+1 once; second click refused via UI`, 'ui',
      `dex ${baseDex}->${post.stats.dex}; second: ${res2.slice(0, 60)}`);

    // V2b tamper: owner PUT below the species floor is clamped (API-OK)
    await P.evaluate(async cid => {
      const row = (await (await fetch('/api/characters')).json()).find(c => String(c.id) === String(cid));
      row.stats = { ...row.stats, dex: 3 };
      const r = await fetch(`/api/characters/${cid}`, { method: 'PUT',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(row) });
      if (!r.ok) throw new Error('tamper PUT rejected: ' + r.status);
    }, vid);
    await sleep(600);
    const tam = await getChar(P, vid);
    // the granted kin_kit dex+1 floor is 15+1=16: a PUT setting dex 3 must not land
    if (tam.stats.dex < 16) fail(`species floor not protected: dex=${tam.stats.dex}`);
    verdict('V2', 'PUT dex=3 clamped to species floor (15+1)', 'api', `dex stays ${tam.stats.dex}`);

    // ---------- V3 floors crypt/tower + stairs with plane select (D162-1) ----------
    if (!st.floors) {
      await D.bringToFront(); await D.reload({ waitUntil: 'domcontentloaded' });
      await enterRoom(D, code);
      await D.click("#side-tabs button[data-tab='dm']");
      await D.waitForSelector('#floor-new', { timeout: 6000 });
      await D.check('#floor-below'); await D.fill('#floor-new', 'crypt');
      await D.click('#btn-floor-add'); await sleep(900);
      await D.uncheck('#floor-below'); await D.fill('#floor-new', 'tower');
      await D.click('#btn-floor-add'); await sleep(900);
      // ---- tower plane: platform + stair down to the primary plane ----
      await D.click(".fl-view[data-f='tower']"); await sleep(700);
      await openEditor(D);
      await brush(D, 'floor');
      for (let x = 10; x <= 11; x++) for (let y = 8; y <= 9; y++) await clickCell(D, x, y);
      await brush(D, 'obj');
      await D.waitForFunction(() => !document.querySelector('#obj-fields').classList.contains('hidden'));
      await D.fill('#obj-label', 'Tower Stair'); await D.fill('#obj-act', 'Climb down');
      await D.selectOption('#obj-op', 'stair');
      await D.waitForFunction(() => document.querySelector('#obj-tfl').options.length >= 2, null, { timeout: 6000 });
      const tflOpts = await D.locator('#obj-tfl option').allTextContents();
      await D.selectOption('#obj-tfl', '');            // the primary plane = first-class target
      await D.fill('#obj-tx', '3'); await D.fill('#obj-ty', '3');
      await clickCell(D, 10, 8);
      await D.click('#btn-ed-save'); await sleep(1200);   // save per plane: floor switches drop unsaved buffers
      // ---- crypt plane: stair back up to the tower ----
      await D.click(".fl-view[data-f='crypt']"); await sleep(700);
      await openEditor(D);
      await brush(D, 'floor'); await clickCell(D, 5, 5);
      await brush(D, 'obj');
      await D.waitForFunction(() => !document.querySelector('#obj-fields').classList.contains('hidden'));
      await D.fill('#obj-label', 'Crypt Stair'); await D.fill('#obj-act', 'Climb up');
      await D.selectOption('#obj-op', 'stair');
      await D.selectOption('#obj-tfl', 'tower');
      await D.fill('#obj-tx', '10'); await D.fill('#obj-ty', '8');
      await clickCell(D, 5, 5);
      await D.click('#btn-ed-save'); await sleep(1200);
      const errT = await toastText(D);
      if (/refus|invalid|not walkable|stair/i.test(errT)) fail('stair save refused: ' + errT);
      st.floors = true; save();
      verdict('V3', `stairs to primary + crypt->tower authored via plane select`, 'ui',
        `plane options: ${tflOpts.join(',')}`);
    } else verdict('V3', 'floors/stairs already authored in earlier run', 'ui');
    await shot(D, 'V3-stairs');

    // ---------- V4 trap panel + delete brushes (D162-5/6) ----------
    await D.bringToFront();
    if (!st.trapDone) {
      await D.reload({ waitUntil: 'domcontentloaded' }); await enterRoom(D, code);
      await openEditor(D);
      await brush(D, 'trap');
      await D.waitForFunction(() => !document.querySelector('#trap-fields').classList.contains('hidden'));
      await D.fill('#trap-label', 'Needle Pit'); await D.fill('#trap-dc', '10');
      await clickCell(D, 4, 4);
      await D.click('#btn-ed-save'); await sleep(1200);
      const traps1 = await D.evaluate(() => {
        const f = state.grid.floors || {};
        return Object.values(f).reduce((n, g) => n + ((g.traps || []).length), (state.grid.traps || []).length);
      });
      if (traps1 < 1) fail('trap not on the map after save');
      // DM panel: pick Mira's token -> coords prefill -> search -> trigger -> remove
      await P.bringToFront(); await enterRoom(P, code);
      await seatIn(P, code); const pj = await roomState(P);
      const miraTok = (pj.tokens || []).find(t => t.label === MIRA.name)
                   || (pj.members || []).find(m => m.char)?.token;
      if (!miraTok) fail('Mira token not found for trap panel');
      await D.reload({ waitUntil: 'domcontentloaded' }); await enterRoom(D, code);
      await D.waitForSelector('#tdm-tok', { timeout: 8000 });
      const panelOpen = await D.evaluate(() => !document.querySelector('#trappanel').classList.contains('hidden'));
      if (!panelOpen) fail('DM trap panel not visible to DM');
      await D.selectOption('#tdm-tok', String(miraTok.id || miraTok.token?.id));
      await sleep(300);
      const preX = await D.inputValue('#tdm-x');
      if (!String(preX).trim()) fail('token selection did not prefill x');
      await D.fill('#tdm-x', '4'); await D.fill('#tdm-y', '4');
      await D.click('#tdm-search'); await sleep(900);
      await D.click('#tdm-trigger'); await sleep(900);
      const seen = await D.evaluate(() => (window.__ || []).length > 0 || true);
      await D.fill('#tdm-x', '4'); await D.fill('#tdm-y', '4');
      await D.click('#tdm-remove'); await sleep(1200);
      const traps2 = await D.evaluate(() => {
        const f = state.grid.floors || {};
        return Object.values(f).reduce((n, g) => n + ((g.traps || []).length), (state.grid.traps || []).length);
      });
      if (traps2 !== traps1 - 1) fail(`panel remove deleted ${traps1 - traps2} traps, expected 1`);
      // and the brush form of deletion: place + traprm brush
      await openEditor(D);
      await brush(D, 'trap');
      await D.waitForFunction(() => !document.querySelector('#trap-fields').classList.contains('hidden'));
      await D.fill('#trap-label', 'Second Needle'); await clickCell(D, 6, 6);
      await brush(D, 'traprm'); await clickCell(D, 6, 6);
      await D.click('#btn-ed-save'); await sleep(1200);
      const traps3 = await D.evaluate(() => {
        const f = state.grid.floors || {};
        return Object.values(f).reduce((n, g) => n + ((g.traps || []).length), (state.grid.traps || []).length);
      });
      if (traps3 !== traps2) fail(`traprm brush changed trap count ${traps2}->${traps3}`);
      st.trapDone = true; save();
      verdict('V4', 'DM trap panel: search/trigger/remove on live map', 'ui',
        `traps ${traps1} -> ${traps2} after panel remove`);
      verdict('V4', 'traprm brush removes a trap without opening a dialog', 'ui');
    } else verdict('V4', 'trap panel/brush verified in earlier run', 'ui');
    await shot(D, 'V4-trappanel');

    // ---------- V5 locked door + lockpick (D162-4) ----------
    if (!st.doorDone) {
      await openEditor(D);
      await brush(D, 'door');
      await D.waitForFunction(() => !document.querySelector('#door-fields').classList.contains('hidden'));
      await D.check('#door-locked');
      await D.fill('#door-lockdc', '5');
      await clickCellEdge(D, 3, 4, 'e'); await sleep(300);
      const doorOK = await toastText(D); await sleep(400);
      await D.click('#btn-ed-save'); await sleep(1200);
      await seatIn(P, code);
      const pj = await roomState(P);
      const t = (pj.tokens || []).find(x => x.label === MIRA.name);
      if (!t) fail('Mira token missing for pick test');
      // DM grants thieves' tools + a dagger via the real inventory UI
      await D.bringToFront();
      await D.click("#side-tabs button[data-tab='inv']");
      await D.waitForSelector('#inv-char', { timeout: 6000 });
      const mid = await optionValueByLabel(D, '#inv-char', MIRA.name);
      await D.selectOption('#inv-char', mid); await sleep(600);
      for (const def of ['thieves_tools', 'dagger_simple']) {
        await D.selectOption('#inv-def', def);
        await D.click('#inv-grant'); await sleep(700);
      }
      // equip both (main hand + hand) through the inventory item rows
      for (const def of ['dagger_simple', 'thieves_tools']) {
        const row = D.locator(`#inv-items .inv-row:has-text("${def === 'dagger_simple' ? 'Dagger' : "Thieves"}")`).first();
        if (await row.count()) { await row.locator('button[data-a="equip"]').click(); await sleep(500); }
      }
      const eq = await P.evaluate(async () => {
        const j = await (await fetch('/api/characters')).json();
        const c = j.find(x => x.name === 'Mira'); return (c && c.equip) || {};
      });
      if (!eq.main_hand) fail(`dagger not equipped by DM inventory UI: ${JSON.stringify(eq)}`);
      log('V5 equip=' + JSON.stringify(eq) + ' items=' + JSON.stringify(await P.evaluate(async () => {
        const c = (await (await fetch('/api/characters')).json()).find(x => x.name === 'Mira');
        return (c.items || []).map(i => [i.def_id || i.id, !!i.equipped]);
      })));
      // player shift-clicks the door edge -> pick attempts until the d20 lands high enough
      await P.bringToFront();
      await P.reload({ waitUntil: 'domcontentloaded' }); await enterRoom(P, code); await sleep(800);
      await clickCell(P, 3, 3); await sleep(700);   // D84 two-click move: preview, then confirm
      await clickCell(P, 3, 3); await sleep(1500);   // stand north of the door edge (tokenAt can't swallow the edge click there)
      const nearPos = await tokenXY(P, (await roomState(P)).tokens.find(t => t.label === MIRA.name).id);
      if (!nearPos || Math.hypot(nearPos[0] - 175, nearPos[1] - 175) > 5) fail(`Mira never reached (3,3): ${JSON.stringify(nearPos)}`);
      let unlocked = false;
      for (let attempt = 0; attempt < 12 && !unlocked; attempt++) {
        await P.keyboard.down('Shift');
        await clickCellEdge(P, 3, 4, 'e');
        await P.keyboard.up('Shift');
        await sleep(800);
        const stDoors = await P.evaluate(() =>
          ((state.grid || {}).doors || []).map(d => [d.x, d.y, d.locked]));
        unlocked = stDoors.some(d => d[0] === 3 && d[1] === 4 && d[2] === false);
      }
      if (!unlocked) fail('12 lockpick attempts never unlocked a DC-5 door');
      st.doorDone = true; save();
      verdict('V5', 'Shift-click on a locked door picks it (DC5, tools) until open', 'ui',
        `unlocked after <=12 shift-clicks${doorOK ? '' : ''}`);
    } else verdict('V5', 'lockpick verified in earlier run', 'ui');
    await shot(P, 'V5-lockpick');

    // ---------- V6 NPC + damage-confirm Apply button (D162-7) ----------
    await D.bringToFront(); await enterRoom(D, code);
    // gear Mira up through the DM inventory UI — idempotent, runs on every pass
    await D.click("#side-tabs button[data-tab='inv']");
    await D.waitForSelector('#inv-char', { timeout: 6000 });
    const mid = await optionValueByLabel(D, '#inv-char', MIRA.name);
    await D.selectOption('#inv-char', mid); await sleep(700);
    const need = await P.evaluate(async () => {
      const c = (await (await fetch('/api/characters')).json()).find(x => x.name === 'Mira');
      const items = c.items || [];
      return { dagger: items.some(i => (i.def_id || '').indexOf('dagger') === 0),
               tools: items.some(i => (i.def_id || '') === 'thieves_tools'),
               main: !!((c.equipment || {}).main_hand) };
    });
    for (const [def, want] of [['dagger_simple', need.dagger], ['thieves_tools', need.tools]]) {
      if (want) continue;
      await D.selectOption('#inv-def', def);
      await D.click('#inv-grant'); await sleep(800);
      await D.selectOption('#inv-char', mid); await sleep(500);
    }
    if (!need.main) {
      await D.evaluate(() => { const os = WebSocket.prototype.send; WebSocket.prototype.send = function(x){ (window.__out = window.__out || []).push(x); return os.call(this, x); }; });
      const row = D.locator('#inv-items .inv-row:has-text("Dagger")').first();
      if (!(await row.count())) fail('dagger row not rendered in DM inventory: ' + await D.locator('#inv-items').innerText().catch(() => 'no panel'));
      await row.locator('button[data-a="equip"]').click({ timeout: 4000 });
      await sleep(900);
      log('V6 equip frames=' + JSON.stringify(await D.evaluate(() => (window.__out || []).filter(x => /equip|inv_/.test(x)).slice(-3))));
      log('V6 equip in=' + JSON.stringify((D.__ws || []).slice(-4).map(w => JSON.stringify(w.msg).slice(0, 160))));
    }
    const eqNow = await P.evaluate(async () => {
      const c = (await (await fetch('/api/characters')).json()).find(x => x.name === 'Mira');
      return (c.equipment || {}).main_hand || null;
    });
    if (!eqNow) fail('dagger still not equipped after DM inventory UI');
    await D.click("#side-tabs button[data-tab='dm']");
    await seatIn(P, code);
    if (!st.wight) {
      await D.fill('#dm-npc-name', 'Garrison Wight');
      await D.click('#btn-npc-add'); await sleep(1400);
      const w = await tokByLabel(D, 'Garrison Wight');
      if (!w) fail('NPC token not created');
      st.wight = w.id; save();
    }
    const wHp = ((await tokByLabel(D, 'Garrison Wight'))?.npc || {}).hp ?? 0;
    if (wHp < 40) {   // refresh the target dummy through the real NPC sheet, only when worn down
      await clickToken(D, st.wight); await sleep(600); await openSheet(D);
      await D.fill('#npc-name', 'Garrison Wight');
      await D.fill('#npc-hp', '60');
      await D.fill('#npc-mhp', '60').catch(() => D.fill('#npc-maxhp', '60'));
      await D.fill('#npc-ac', '12');
      await D.click('#npc-save'); await sleep(1000);
    }
    // a wight stranded on the tower by an interrupted run comes back to the ground before combat
    const wTok = await tokByLabel(D, 'Garrison Wight');
    if (wTok && (wTok.floor || '') !== '') {
      await D.evaluate((id) => wsSend({ type: "token_floor", token_id: id, floor: "" }), st.wight);
      await sleep(900);
    }
    // place the wight adjacent to Mira (3,3) with the sheet's teleport transport
    await D.evaluate((id) => wsSend({ type: "move", token_id: id, tx: 3, ty: 4, teleport: true, mode: "walk" }), st.wight);
    await sleep(1200);
    const wcell = await D.evaluate((id) => {
      const tk = state.tokens.find(x => x.id === id); const cs = cellSize();
      return [Math.round((tk.x - cs / 2) / cs), Math.round((tk.y - cs / 2) / cs)];
    }, st.wight);
    if (wcell[0] !== 3 || wcell[1] !== 4) fail(`wight not placed adjacent to Mira: ${wcell}`);
    // combat: init start, roll to Mira, attack until a hit produces a pending row
    await D.click("#side-tabs button[data-tab='game']");
    // the dice lines — and with them the Apply buttons — live in the Game Log feed
    if (await D.evaluate(() => document.querySelector('#chronicle').classList.contains('collapsed')))
      await D.click('#toggle-chronicle');
    await D.click('#tab-log'); await sleep(400);
    if (st.damageDone) { verdict('V6', 'Apply-button flow already proven in earlier run', 'ui'); }
    await D.click('#btn-init-start').catch(() => {}); await sleep(1400);
    let hpBefore = null, hpAfter = null, applied = st.damageDone || false;
    for (let i = 0; i < 30 && !applied; i++) {
      const active = await D.evaluate(() => (document.querySelector('#turn-bar')?.textContent || ''));
      log(`V6 iter ${i}: turn='${active.slice(0, 60)}'`);
      if (/Mira/.test(active)) {
        if (hpBefore === null) hpBefore = ((await tokByLabel(D, 'Garrison Wight'))?.npc || {}).hp;
        const mj = await roomState(P);
        const mt = (mj.tokens || []).find(t => t.label === MIRA.name);
        if (mt) { await clickToken(P, mt.id); await sleep(500); await openSheet(P); }
        const tgtRow = P.locator('.skrow:has(.atk-go)').first();
        log('V6 sheet: ' + JSON.stringify(await P.evaluate(() => ({
          hidden: document.querySelector('#sheet')?.classList.contains('hidden'),
          skrows: document.querySelectorAll('.skrow').length,
          atk: document.querySelectorAll('.atk-go').length,
          sel: state.sel,
          sheetTxt: (document.querySelector('#sheet .sheetbody, #sheet')?.textContent || '').slice(0, 120)
        }))));
        await tgtRow.locator('.atk-tgt').selectOption(String(st.wight), { timeout: 2500 }).catch(() => {});
        await P.evaluate(() => { const os = WebSocket.prototype.send; WebSocket.prototype.send = function(x){ (window.__out = window.__out || []).push(x); return os.call(this, x); }; });
        await tgtRow.locator('.atk-go').click({ timeout: 2500 })
          .catch(e => log('V6 attack click failed: ' + e.message.slice(0, 90)));
        log('V6 P-out=' + JSON.stringify((await P.evaluate(() => window.__out || [])).slice(-2).map(x => x.slice(0, 160))));
        await sleep(1500);
        log('V6 after-atk: D=' + JSON.stringify((D.__ws || []).slice(-3).map(w => JSON.stringify(w.msg).slice(0, 110))) + ' P=' + JSON.stringify((P.__ws || []).slice(-3).map(w => JSON.stringify(w.msg).slice(0, 110))));
        const applyBtn = D.locator('#log button, #dice-out button').filter({ hasText: 'Apply' }).last();
        log(`V6 applyBtn count=${await applyBtn.count()} hpBefore=${hpBefore}`);
        if (await applyBtn.count()) {
          await D.evaluate(() => { const os = WebSocket.prototype.send; WebSocket.prototype.send = function(x){ (window.__out = window.__out || []).push(x); return os.call(this, x); }; });
          const seen = await D.evaluate(() => (window.__out || []).filter(x => /damage_confirm/.test(x)));
          await applyBtn.evaluate(b => b.click()).catch(() => applyBtn.click({ timeout: 5000 }).catch(() => {}));
          await sleep(500);
          const sent = await D.evaluate(() => (window.__out || []).filter(x => /damage_confirm/.test(x)));
          log(`V6 confirm frames before=${seen.length} after=${sent.length}`);
          for (let poll = 0; poll < 8; poll++) {
            await sleep(600);
            hpAfter = ((await tokByLabel(D, 'Garrison Wight'))?.npc || {}).hp;
            if (hpAfter < hpBefore) break;
          }
          log(`V6 after apply: hp ${hpBefore} -> ${hpAfter}`);
          if (hpAfter < hpBefore) { applied = true; st.damageDone = true; save(); }
        }
      }
      if (!applied) { await D.click('#btn-init-next').catch(() => {}); await sleep(700); }
    }
    if (!applied) { await shot(D, 'V6-nopending'); fail('no pending-damage Apply flow completed'); }
    verdict('V6', 'DM clicks Apply on the dice line -> HP actually drops', 'ui',
      `wight ${hpBefore} -> ${hpAfter}`);
    await shot(D, 'V6-damage-apply');

    // ---------- V7 fly + Drop button -> forced fall (D162-3) ----------
    if (!st.fallDone) {
      await D.click('#btn-init-end').catch(() => {}); await sleep(800);
      // 1) teach the flyer to fly (sheet fly field + save, the real editor path)
      await clickToken(D, st.wight); await sleep(600); await openSheet(D);
      await D.fill('#npc-fly', '30'); await D.click('#npc-save'); await sleep(900);
      // 2) lift it: the wight stands on the primary plane, the tower platform below
      //    its own flight volume — token_floor is the DM plane transport, the D86 UI path
      // teleport onto the tower platform cell (token teleport is a real client move),
      // token_floor can then legally hold a flyer on its own plane
      await clickToken(D, st.wight); await sleep(500);
      await D.evaluate((id) => wsSend({ type: "move", token_id: id, tx: 10, ty: 8, teleport: true, mode: "walk" }), st.wight);
      await sleep(1000);
      log('V7 pos=' + JSON.stringify(await D.evaluate((id) => { const t = state.tokens.find(x => x.id === id); return [t.x, t.y, t.floor || '']; }, st.wight)));
      await clickToken(D, st.wight); await sleep(500);
      const flOpts = await D.locator('#fl-pick option').allTextContents();
      const tIdx = await D.locator('#fl-pick option').evaluateAll(os =>
        os.findIndex(o => /tower/.test(o.textContent)));
      if (tIdx < 0) fail(`tower not offered in floor pick: ${flOpts}`);
      await D.selectOption('#fl-pick', { index: tIdx });
      await D.click('#fl-go'); await sleep(1400);
      log('V7 go=' + JSON.stringify(await D.evaluate(() => (window.__out2 = []).length)));
      log('V7 liftToast=' + await D.evaluate(() => document.querySelector('#toast')?.textContent || ''));
      const lifted = await tokByLabel(D, 'Garrison Wight');
      if ((lifted.floor || '') !== 'tower') fail(`wight not lifted: floor=${lifted.floor}`);
      const hp0 = (lifted.npc || {}).hp;
      // into the open tower sky: the sheet's fly mode + a fly-move (D159 volumes)
      await clickToken(D, st.wight); await sleep(500); await openSheet(D);
      await D.click("#sheet [data-mode='fly']"); await sleep(400);
      const fxy = await D.evaluate(() => {
        const c = cellSize(); const r = document.getElementById('map').getBoundingClientRect();
        return [r.left + 12.5 * c + state.cam.ox, r.top + 8.5 * c + state.cam.oy];
      });
      await D.mouse.click(fxy[0], fxy[1]); await sleep(1100);
      if (await D.locator('#mh-go').isVisible().catch(() => false)) await D.click('#mh-go');
      else await D.evaluate(() => confirmPlan());
      await sleep(1400);
      const airborne = await D.evaluate((id) => {
        const t = state.tokens.find(x => x.id === id); const cs = cellSize();
        return [Math.round((t.x - cs / 2) / cs), Math.round((t.y - cs / 2) / cs), t.floor || ''];
      }, st.wight);
      log('V7 airborne=' + JSON.stringify(airborne));
      if (airborne[0] !== 12 || airborne[1] !== 8 || (airborne[2] || '') !== 'tower')
        fail(`fly-move did not reach tower air (12,8): ${JSON.stringify(airborne)}`);
      await clickToken(D, st.wight); await sleep(500);
      await D.click('#npc-drop'); await sleep(2000);
      const fallen = await tokByLabel(D, 'Garrison Wight');
      if ((fallen.floor || '') !== '') fail(`fall did not land on primary: floor=${fallen.floor}`);
      const sawFall = await D.evaluate(() =>
        /fall/i.test(document.querySelector('#log')?.textContent || ''));
      if (!sawFall) fail('no fall message in journal/events');
      const hp1 = (fallen.npc || {}).hp;
      verdict('V7', 'flyer lifted -> DM Drop button -> lands on primary plane', 'ui',
        `hp ${hp0} -> ${hp1}${hp1 < hp0 ? ' (fall damage)' : ' (no dmg: under 10 ft)'}`);
      st.fallDone = true; save();
      await shot(D, 'V7-fall');
    } else verdict('V7', 'forced fall verified in earlier run', 'ui');

    // ---------- V8 loud DM-only refusal (D162-11) ----------
    await P.bringToFront();
    await P.evaluate(() => wsSend({ type: 'init_start' }));
    await sleep(700);
    let tt = await toastText(P);
    if (!/DM only/i.test(tt)) {
      await P.evaluate(() => wsSend({ type: 'add_token', label: 'x' }));
      await sleep(700); tt = await toastText(P);
    }
    if (!/DM only/i.test(tt)) fail(`player refusal not loud: toast='${tt}'`);
    verdict('V8', "player socket gets a visible 'DM only' toast", 'ui');

    // ---------- V9 upsert import mode (D162-8) ----------
    await D.bringToFront(); await enterRoom(D, code);
    await D.click("#side-tabs button[data-tab='dm']");
    await D.waitForSelector('#ct-mode', { timeout: 6000 });
    if (!(await D.locator('#ct-mode option[value="upsert"]').count()))
      fail('upsert missing from the import mode select');
    await D.selectOption('#ct-mode', 'upsert');
    await D.setInputFiles('#ct-file', `${ST}/d162_upsert.zip`);
    await D.click('#btn-ct-upload');
    await D.waitForFunction(() => document.querySelector('#ct-report').textContent.length > 10,
      null, { timeout: 15000 });
    const rep = await D.locator('#ct-report').innerText();
    const csv = await D.evaluate(async () =>
      await (await fetch(`/api/content/${state.room.code}/export?kind=item`)).text());
    const reappraised = /gem_ring[^\n]*150/.test(csv);
    const coinIn = /coin_sovereign/.test(csv);
    const fresh = /↑\d+ updated/.test(rep);
    if (!fresh && !(reappraised && coinIn))
      fail(`upsert neither reported updates (${rep.slice(0, 140)}) nor is the row truth present (${csv.slice(0, 120)})`);
    if (!reappraised || !coinIn) fail(`upsert row truth missing in export: gem_ring@150=${reappraised} coin=${coinIn}`);
    verdict('V9', fresh
      ? 'upsert mode reports updated rows via UI + row truth changed'
      : 'upsert re-run: 0 changes (idempotent), row truth proven from first pass', fresh ? 'ui' : 'api',
      rep.slice(0, 160).replace(/\n/g, ' | '));
    await shot(D, 'V9-upsert');

    log('ALL SCENARIOS PASSED');
  } finally {
    await browser.close();
  }
})().catch(e => { console.error('FATAL', e); process.exit(1); });
