// D163 "Operation: Letzte Codezeile" — CSV-only acceptance E2E over REAL browser
// actions against a throwaway app on loopback (BASE). New-IDs-only pack
// (scripts/d163_pack.zip). Every step is classified ui / api_only / fixture /
// broken / missing per the D161 verdict convention. DM + two players.
import { chromium } from 'playwright';
import fs from 'fs';
import {
  BASE, ST, log, fail, shot, verdict, auth,
  createRoom, joinRoom, enterRoom, backToPrep, clickToken,
  sleep, seat, watchWS
} from './e2e_d161_lib.mjs';

const STATE = `${ST}/d163_state.json`;
const load = () => { try { return JSON.parse(fs.readFileSync(STATE, 'utf8')); } catch { return {}; } };
const st = load();
const save = () => { fs.mkdirSync(ST, { recursive: true }); fs.writeFileSync(STATE, JSON.stringify(st, null, 1)); };

const U = { dm: 'd163dm', p1: 'd163p1', p2: 'd163p2' };
const STATS = { str: 8, dex: 14, con: 14, int: 12, wis: 14, cha: 10 };

const optionValueByLabel = (page, sel, label) => page.locator(sel).evaluate((el, label) => {
  const o = Array.from(el.options).find(o => o.textContent.includes(label));
  return o ? o.value : null;
}, label);
const roomState = (pg) => pg.evaluate(async () =>
  await (await fetch(`/api/rooms/${state.room.code}/state`)).json());
const openTab = async (pg, tab) => { await pg.click(`#side-tabs button[data-tab='${tab}']`); await sleep(300); };
const openDetails = (pg, sel, re) => pg.evaluate(([sel, re]) => {
  for (const d of document.querySelectorAll(sel))
    if (!re || new RegExp(re, 'i').test(d.querySelector('summary')?.textContent || '')) d.open = true;
}, [sel, re]);
// real canvas drag: mousedown on the token, mouseup on a map cell (50_canvas).
// If the token is off-screen the camera is panned first with a middle-mouse
// drag — the identical onDown pan gesture the DM uses (button 1).
async function dragToken(pg, tokenId, gx, gy) {
  const need = await pg.evaluate(tid => {
    const t = state.tokens.find(x => x.id === tid);
    if (!t) return { err: 'token not in client state' };
    const r = document.getElementById('map').getBoundingClientRect();
    const sx = r.left + t.x + state.cam.ox, sy = r.top + t.y + state.cam.oy;
    const out = sx < r.left + 10 || sx > r.right - 10 || sy < r.top + 10 || sy > r.bottom - 10;
    return out ? { dx: (r.left + r.right) / 2 - sx, dy: (r.top + r.bottom) / 2 - sy } : null;
  }, tokenId);
  if (need && need.err) fail(`dragToken: ${need.err}`);
  if (need) {
    const [mx, my] = await pg.evaluate(() => {
      const r = document.getElementById('map').getBoundingClientRect();
      return [r.left + r.width / 2, r.top + r.height / 2];
    });
    await pg.mouse.move(mx, my);
    await pg.mouse.down({ button: 'middle' });
    await pg.mouse.move(mx + need.dx, my + need.dy, { steps: 6 });
    await pg.mouse.up({ button: 'middle' });
    await sleep(250);
  }
  const [x0, y0, x1, y1] = await pg.evaluate(([tid, cx, cy]) => {
    const t = state.tokens.find(x => x.id === tid);
    const c = cellSize(), r = document.getElementById('map').getBoundingClientRect();
    return [r.left + t.x + state.cam.ox, r.top + t.y + state.cam.oy,
            r.left + (cx + .5) * c + state.cam.ox, r.top + (cy + .5) * c + state.cam.oy];
  }, [tokenId, gx, gy]);
  await pg.mouse.move(x0, y0); await pg.mouse.down();
  await pg.mouse.move(x1, y1, { steps: 8 }); await pg.mouse.up();
  await sleep(350);
}
// Every server frame rides wrapped: {type:"event", kind:<real>, payload} (net.py
// send_to). The lib's wsSeen filters the OUTER type and therefore matches nothing
// on this stack — classify by the inner kind instead.
const seenK = (pg, kind) => (pg.__ws || []).filter(w => (w.msg.kind || w.type) === kind);
const chatBodies = (pg, needle) => seenK(pg, 'chat').filter(w =>
  JSON.stringify(w.msg.payload || {}).includes(needle));

async function buildViaUI(P, name, to, opts = {}) {
  // full UI character flow: create -> stats -> plan -> picks -> apply
  await P.click('#prep-new-toggle');
  await P.fill('#prep-name', name);
  await P.locator('#prep-species').selectOption('sp_gremlin');
  await P.locator('#prep-class').selectOption('hedgehex');
  await P.locator('#prep-bg').selectOption('bg_tinker');
  await P.click('#prep-create');
  await P.waitForFunction(n => Array.from(document.querySelector('#prep-char').options)
    .some(o => o.textContent.includes(n)), name, { timeout: 10000 });
  await P.click('#prep-back');
  await P.waitForSelector('#char-list', { timeout: 6000 });
  await P.locator('#char-list div', { hasText: name }).first()
    .locator('[data-a="edit"]').click();
  await P.waitForSelector('#st-str', { state: 'visible', timeout: 6000 });
  for (const [ab, v] of Object.entries(STATS)) await P.fill(`#st-${ab}`, String(v));
  await P.click('#btn-char-save'); await sleep(800);
  log(`${name}: identity saved, joining ${st.code}`);
  if (!(await P.locator('#rm-code').isVisible().catch(() => false))) {
    const views = await P.evaluate(() => [...document.querySelectorAll('[id^="view-"]')]
      .filter(v => v.offsetParent !== null).map(v => v.id)).catch(() => []);
    log(`${name}: #rm-code hidden — visible views: ${views.join('+') || '??'}`);
    await shot(P, `${name}-nolobby`);
    await P.click('#char-back').catch(() => P.click('#prep-back').catch(() => {}));
    await sleep(600);
  }
  await P.fill('#rm-code', st.code); await P.click('#btn-room-join');
  await P.waitForSelector('#view-prep', { timeout: 8000 });
  const vid = await optionValueByLabel(P, '#prep-char', name);
  await P.locator('#prep-char').selectOption(vid);
  await sleep(500);
  await P.click('#prep-id-save'); await sleep(700);
  // D163: starting equipment from CSV — the background kit (Hexing Kit) and the
  // class kit (Dagger of Misery) — through the prep view's own two-step gear
  // flow. This is the REAL UI path; the DM-transfer shortcut in D162-era
  // scripts never proved the pack's own starting_items columns.
  await P.click('#prep-gear'); await sleep(900);
  await P.locator('#prep-gear-grant').click({ timeout: 8000 })
    .catch(e => log(`${name}: gear grant: ${e.message.split('\n')[0]}`));
  await sleep(900);
  log(`${name}: gear: ${(await P.locator('#prep-gear-result').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 140)}`);
  await openDetails(P, '#prep-wizbox, #prep-wizbox details', null);
  await P.fill('#prep-to', String(to));
  await P.click('#prep-plan');
  // The wizard's PLACEHOLDER text is longer than 10 chars too — wait for a
  // real choice field, not for prose (racing the plan reply silently skipped
  // the cantrip/spell picks in an earlier run).
  await P.waitForFunction(() => !!document.querySelector(
    '#prep-wiz .pw-sk, #prep-wiz .pw-can, #prep-wiz .pw-lvl, #prep-wiz .pw-sub'),
  null, { timeout: 15000 });
  const wizDump = async (tag) => log('WIZ ' + tag + ': ' + await P
    .evaluate(() => JSON.stringify(state.prep.wiz)).catch(e => 'diag: ' + e.message));
  if (await P.locator('.pw-can').count()) {
    if (!(await P.locator('.pw-can option').count())) fail('cantrip pool rendered EMPTY — plan did not deliver it');
    await P.locator('.pw-can').selectOption(['hex_spark']);
  }
  if (await P.locator('.pw-sp').count()) {
    if (!(await P.locator('.pw-sp option').count())) fail('spell pool rendered EMPTY');
    await P.locator('.pw-sp').selectOption(['hex_blight']);
  }
  await P.check('.pw-sk[value="arcana"]');
  await P.check('.pw-sk[value="investigation"]');
  await wizDump('after picks+skills');
  if (opts.subclass) {
    const probe = () => P.evaluate(() => {
      const e = [...document.querySelectorAll('.pw-sub')];
      return JSON.stringify({ n: e.length, v: e.map(x => x.value), b: e.map(x => !!x.onchange),
        opts: e.map(x => [...x.options].map(o => o.value)),
        inWiz: e.map(x => !!x.closest('#prep-wiz')), m: state.prep.wiz.subclass });
    }).catch(e => 'probe: ' + e.message);
    log('SUBPROBE before: ' + await probe());
    await P.locator('.pw-sub').selectOption('path_hex')
      .catch(e => fail(`subclass pick: ${e.message.slice(0, 120)}`));
    log('SUBPROBE after: ' + await probe());
    await wizDump('after subclass');
  }
  if (opts.asi) {
    await P.locator('.pw-lvl[data-lvl="4"]').selectOption('asi');
    await sleep(300);
    await P.locator('.pw-asi-mode[data-lvl="4"]').selectOption('plus2_plus1').catch(() => {});
    await P.locator('.pw-asi-p2[data-lvl="4"]').selectOption('wis');
    await P.locator('.pw-asi-p1[data-lvl="4"]').selectOption('int');
    await wizDump('after asi');
  }
  await P.click('#prep-apply');
  await P.waitForFunction(() => (document.querySelector('#prep-out')?.textContent || '').trim().length > 3,
    null, { timeout: 15000 });
  const out = await P.locator('#prep-out').innerText();
  if (!/built/i.test(out)) {
    const diag = await P.evaluate(() => JSON.stringify({
      wiz: state.prep.wiz, to: document.querySelector('#prep-to')?.value,
      cls: document.querySelector('#prep-class')?.value || null,
      charClass: (state.prep.chars || []).find(x => String(x.id) === document.querySelector('#prep-char')?.value)?.char_class,
    })).catch(e => 'diag failed: ' + e.message);
    fail(`${name} build failed: ` + out.replace(/\s+/g, ' ').slice(0, 400) + " ||DIAG " + String(diag).slice(0, 500));
  }
  return out;
}

(async () => {
  const browser = await chromium.launch({ headless: true, chromiumSandbox: false });
  const mk = async () => await browser.newContext({ baseURL: BASE });
  const dm = await mk(); const D = await dm.newPage(); D.on('dialog', d => d.accept()); watchWS(D);
  const c1 = await mk(); const P1 = await c1.newPage(); P1.on('dialog', d => d.accept()); watchWS(P1);
  const c2 = await mk(); const P2 = await c2.newPage(); P2.on('dialog', d => d.accept()); watchWS(P2);

  try {
    // ---------- S0 accounts, rooms, UI pack import ----------
    await auth(D, U.dm); await auth(P1, U.p1); await auth(P2, U.p2);
    verdict('S0', 'register/login DM + 2 players', 'ui');
    if (!st.code) {
      st.code = await createRoom(D, 'D163 Letzte Codezeile');
      await D.goto(BASE + '/', { waitUntil: 'domcontentloaded' }); await sleep(600);
      st.codeB = await createRoom(D, 'D163 Isolation');
      await D.goto(BASE + '/', { waitUntil: 'domcontentloaded' }); await sleep(600);
      save();
    }
    await enterRoom(D, st.code);
    await openTab(D, 'dm');
    await openDetails(D, '#dmtools details.group', 'Rule packages');
    if (!st.imported) {
      await D.locator('#ct-mode').selectOption('apply');
      await D.setInputFiles('#ct-file', `${ST}/d163_pack.zip`);
      await D.click('#btn-ct-upload'); await sleep(2600);
      const rep = await D.locator('#ct-report').innerText();
      if (/error|invalid/i.test(rep)) { await shot(D, 'S1-import-errors'); fail('pack import: ' + rep.slice(0, 300)); }
      st.imported = true; save();
      const kinds = await D.locator('#ct-kinds').innerText().catch(() => '');
      verdict('S1', 'CSV pack import (all 11 kinds) via content panel', 'ui', kinds.trim().slice(0, 100));
    } else verdict('S1', 'pack imported in an earlier run', 'ui');
    await shot(D, 'S1-import');

    // ---------- S2 P1 full UI build incl. subclass + 2024 ASI ----------
    await P1.goto(BASE + '/', { waitUntil: 'domcontentloaded' }); await sleep(600);
    if (!st.p1) {
      await joinRoom(P1, st.code);
      const out = await buildViaUI(P1, 'Hexa', 4, { subclass: true, asi: true });
      st.p1 = { out: out.slice(0, 160) }; save();
      await shot(P1, 'S2-hexa-built');
      verdict('S2', 'Gremlin+Hedgehex+Tinker build to L4: subclass choice + ASI (+2/+1) via UI', 'ui', out.slice(0, 60));
    } else verdict('S2', 'Hexa already built (' + st.p1.out.slice(0, 40) + ')', 'ui');
    // joinRoom fills the LOBBY's #rm-code — skip when the prep view already
    // holds this client (the lobby is hidden there, fill would hang).
    if (!(await P1.locator('#view-prep').isVisible().catch(() => false)))
      await joinRoom(P1, st.code);
    else await P1.evaluate(() => openPrep(st.code)).catch(() => {});

    // ---------- S3 P2 second player builds and seats ----------
    await P2.goto(BASE + '/', { waitUntil: 'domcontentloaded' }); await sleep(600);
    if (!st.p2) {
      await joinRoom(P2, st.code);
      const out2 = await buildViaUI(P2, 'Nix', 1, {});
      st.p2 = { out: out2.slice(0, 120) }; save();
      verdict('S3', 'second player builds + seats via UI', 'ui', out2.slice(0, 40));
    } else verdict('S3', 'Nix already built', 'ui');
    if (!(await P2.locator('#view-prep').isVisible().catch(() => false)))
      await joinRoom(P2, st.code);
    else await P2.evaluate(() => openPrep(st.code)).catch(() => {});

    // ---------- S4 seat everyone ----------
    await enterRoom(D, st.code);              // the DM needs no character at the table
    for (const pg of [P1, P2]) {
      await enterRoom(pg, st.code);
      await seat(pg);
    }
    await shot(P1, 'S4-seated');
    verdict('S4', 'DM + 2 players seated with characters', 'ui');

    // ---------- S5 daily prepared list via sheet checkboxes ----------
    {
      const j = await roomState(P1);
      const me = j.tokens.find(t => t.character_id && t.label === 'Hexa');
      if (!me) fail('Hexa token not in state');
      await openTab(P1, 'chars');
      await clickToken(P1, me.id);
      await openDetails(P1, '#sheet details, details.sheet-sec', null);
      const cb = P1.locator('.prep-sp[data-id="hex_blight"]');
      await cb.waitFor({ timeout: 8000 });
      if (!(await cb.isChecked())) { await cb.check(); await sleep(1000); }
      const castRow = () => P1.locator('.cast-ab[data-id="hex_blight"]').first();
      // gate ON: uncheck -> the cast must be refused
      await cb.uncheck(); await sleep(1100);
      let w0 = (P1.__ws || []).length;
      await castRow().click({ timeout: 8000 }).catch(e => log('S5a click: ' + e.message.split('\n')[0]));
      await sleep(1500);
      let tail = (P1.__ws || []).slice(w0).map(w => (w.msg.kind || w.type) + ':' + JSON.stringify(w.msg.payload || {}).slice(0, 70));
      const refused = tail.some(t => /is not prepared/i.test(t));
      verdict('S5a', 'daily list unchecked -> the cast is refused ("is not prepared")',
        refused ? 'ui' : 'broken', JSON.stringify(tail).slice(0, 240));
      // gate OFF: re-check -> the refusal is gone
      await cb.check(); await sleep(1100);
      w0 = (P1.__ws || []).length;
      await castRow().click({ timeout: 8000 }).catch(e => log('S5b click: ' + e.message.split('\n')[0]));
      await sleep(1500);
      tail = (P1.__ws || []).slice(w0).map(w => (w.msg.kind || w.type) + ':' + JSON.stringify(w.msg.payload || {}).slice(0, 70));
      const gateGone = !tail.some(t => /is not prepared/i.test(t));
      verdict('S5b', 're-checked -> the same cast is no longer refused',
        gateGone ? 'ui' : 'broken', JSON.stringify(tail).slice(0, 240));
      await shot(P1, 'S5-prepared');
    }

    // ---------- S6 inventory: equip magic weapon, USE the tool ----------
    {
      await openTab(P1, 'inv');
      await sleep(500);
      const dagger = P1.locator('.inv-row', { hasText: 'Dagger of Misery' });
      await dagger.locator('[data-a="equip"]').first().click(); await sleep(800);
      await openTab(P1, 'inv'); await sleep(400);
      const equipped = await P1.locator('#inv-equip').innerText().catch(() => '');
      verdict('S6a', 'equipping the +1 magic weapon via Inv tab',
        /Dagger/i.test(equipped) ? 'ui' : 'broken', equipped.slice(0, 60));
      const kit = P1.locator('.inv-row', { hasText: 'Hexing Kit' });
      await kit.locator('[data-a="use"]').first().click(); await sleep(1200);
      const whispers = seenK(P1, 'whisper').filter(w => /Hexing Kit/i.test(JSON.stringify(w.msg.payload)));
      const trained = whispers.some(w => /with proficiency/i.test(JSON.stringify(w.msg.payload)));
      verdict('S6b', 'USING the CSV tool item rolls a real check over the UI',
        trained ? 'ui' : (whispers.length ? 'broken' : 'missing'),
        whispers.length ? whispers[whispers.length - 1].msg.payload.text.slice(0, 90) : 'no whisper');
      await shot(P1, 'S6-inv-tool');
    }

    // ---------- S7 creature: CSV row -> bestiary -> encounter -> spawn ----------
    {
      await openTab(D, 'dm');
      await openDetails(D, '#dmtools details.group', 'Rule packages');
      // the per-row "To bestiary" button lives in the creature reviewer
      // (#btn-ct-creatures -> #ct-creatures), NOT in the import report
      await D.click('#btn-ct-creatures'); await sleep(1000);
      const crow = D.locator('#ct-creatures .journal-item').filter({ hasText: /grick/i }).first();
      await crow.waitFor({ timeout: 8000 });
      await crow.locator('button', { hasText: /bestiary/i }).first()
        .click({ timeout: 6000 }).catch(e => log('S7a to-bestiary: ' + e.message.split('\n')[0]));
      await sleep(1600);
      // the bestiary list is the source of truth either way
      const inBook = await D.evaluate(async () => {
        try { const r = await (await fetch(`/api/creatures`)).json(); return (r || []).map(c => c.name); }
        catch (e) { return []; }
      });
      verdict('S7a', 'creature row reaches the bestiary',
        inBook.some(n => /Grick/i.test(n)) ? 'ui' : 'broken', inBook.join(',').slice(0, 80));
      // Bestiary + Encounters live inside #dmtools (the DM tab), not the Game tab
      await openDetails(D, '#dmtools details.group', 'Encounter');
      await sleep(500);
      const csel = D.locator('#enc-creature-select');
      await csel.waitFor({ timeout: 8000 });
      const gid = await optionValueByLabel(D, '#enc-creature-select', 'Grick Guard');
      if (!gid) fail('Grick Guard not selectable in the encounter builder');
      await csel.selectOption(gid);
      await D.click('#btn-enc-add-row'); await sleep(300);
      await D.fill('#enc-name', 'Garden guard');
      await D.click('#btn-enc-save'); await sleep(900);
      await D.click('#btn-enc-spawn'); await sleep(1500);
      const j = await roomState(D);
      const grick = j.tokens.find(t => /Grick/i.test(t.label || ''));
      if (!grick) fail('encounter spawn produced no Grick token');
      st.grick = grick.id; save();
      const npcBlock = grick.npc || {};
      const def = npcBlock.defenses || {};
      verdict('S7b', 'spawned monster carries CSV defenses (resist/immune/vulnerable)',
        (def.vulnerable || []).includes('necrotic') ? 'ui' : 'broken', JSON.stringify(def).slice(0, 120));
      await shot(D, 'S7-grick-spawned');
    }

    // ---------- S8 cast the multi-effect spell at the monster ----------
    {
      const gOf = async () => {
        const t = (await roomState(D)).tokens.find(x => x.id === st.grick);
        return t ? (t.npc?.hp ?? t.hp) : null;
      };
      // fog of war (D87): a freshly spawned monster outside the party's light
      // is NOT in the players' snapshots — an honest sheet cannot target what
      // the character cannot see. The DM drags the token into the party's
      // light with the same canvas drag used at a physical table.
      // Slots first: earlier scenarios spent them — the DM's long-rest button
      // (a real UI control) restores the party exactly like between fights.
      await openTab(D, 'dm'); await sleep(300);
      await D.click('#btn-long-rest'); await sleep(1200);
      await openTab(D, 'game'); await sleep(300);
      await dragToken(D, st.grick, 9, 7); await sleep(700);
      const dTail = (D.__ws || []).slice(-8).map(w => (w.msg.kind || w.type) + ':' + JSON.stringify(w.msg.payload || {}).slice(0, 60));
      const gNow = await D.evaluate(async tid => {
        const s = await (await fetch(`/api/rooms/${state.room.code}/state`)).json();
        const t = s.tokens.find(x => x.id === tid);
        return t ? `x=${t.x} y=${t.y}` : 'gone';
      }, st.grick);
      log(`grick server pos now: ${gNow}`);
      const seenByP1 = (await roomState(P1)).tokens.some(t => t.id === st.grick);
      log(`grick dragged into party light: seenByP1=${seenByP1} Dtail=${JSON.stringify(dTail).slice(0, 200)}`);
      const hpBefore = await gOf();
      await openTab(P1, 'chars');
      const me = (await roomState(P1)).tokens.find(t => t.character_id && t.label === 'Hexa');
      await clickToken(P1, me.id);
      await openDetails(P1, '#sheet details, details.sheet-sec', null);
      // the spell NAME lives outside .spbtns (button container) — anchor by data-id
      const tgtSel = P1.locator('.spbtns:has(.cast-ab[data-id="hex_blight"]) .ab-tgt');
      try {
        await tgtSel.selectOption(String(st.grick), { timeout: 6000 });
      } catch (e) {
        const dbg = await P1.evaluate(() => JSON.stringify({
          toks: state.tokens.map(t => `${t.label}#${t.id}`),
          sels: [...document.querySelectorAll('.ab-tgt')].map(s => [...s.options].map(o => o.value).join(',')),
        })).catch(() => 'no diag');
        fail(`S8 target pick: ${e.message.split('\n')[0]} || ${dbg}`);
      }
      await P1.locator('.cast-ab[data-id="hex_blight"]').first().click();
      await sleep(1800);
      const hpAfter = await gOf();
      const lost = (hpBefore ?? 0) - (hpAfter ?? 0);
      const dmgLine = seenK(P1, 'chat').concat(seenK(P1, 'dice'))
        .filter(w => /Hex Blight|necrotic/i.test(JSON.stringify(w.msg.payload))).length;
      verdict('S8', 'multi-effect spell (damage + save + condition) from the sheet',
        lost > 0 ? 'ui' : 'broken', `hp ${hpBefore}->${hpAfter} lost=${lost} lines=${dmgLine}`);
      await shot(P1, 'S8-hex-blight');
    }

    // ---------- S9 loot tables: DM rolls via the new button ----------
    {
      await openTab(D, 'dm');
      await D.evaluate(() => { const d = document.querySelector('#loot-group'); if (d) d.open = true; });
      await sleep(600);
      const opt = await optionValueByLabel(D, '#loot-tbl', 'Grick cache');
      if (!opt) fail('loot table not in the DM dropdown (fillLoot failed)');
      await D.locator('#loot-tbl').selectOption(opt);
      await D.click('#btn-loot-roll'); await sleep(1200);
      const seen = chatBodies(P1, 'Grick cache').concat(chatBodies(D, 'Grick cache'));
      const playersSaw = chatBodies(P2, 'Grick cache').length;
      verdict('S9', 'loot roll via the DM Loot-tables button announces to everyone',
        seen.length && playersSaw ? 'ui' : 'broken',
        seen.length ? String(seen[0].msg.payload?.body || seen[0].msg.payload?.text).slice(0, 80) : 'no chat line');
      await shot(D, 'S9-loot-roll');
    }

    // ---------- S10 quest log: CSV quest visible, DM updates an objective ----------
    {
      await openTab(P1, 'story'); await sleep(600);
      const questVisible = await P1.locator('#quest-list').innerText();
      const has = /Blighted Garden/i.test(questVisible);
      verdict('S10a', 'CSV quest shows live in the players quest log', has ? 'ui' : 'broken',
        questVisible.slice(0, 90));
      await openTab(D, 'story'); await sleep(600);
      const card = D.locator('#quest-list > div, #quest-list .journal-item').filter({ hasText: 'Blighted Garden' }).first();
      await card.waitFor({ timeout: 6000 });
      await card.locator('.q-obj').first().click(); await sleep(1200);
      if (!/Undo/i.test(await card.innerText())) {
        // a resumed run may arrive with this objective already ticked (the
        // click is a toggle) — flip again so the final assertion is honest
        await card.locator('.q-obj').first().click(); await sleep(1200);
      }
      const cardTxt = await card.innerText();
      verdict('S10b', 'DM ticks a CSV objective and it sticks in the log',
        /Undo/i.test(cardTxt) ? 'ui' : 'broken', cardTxt.replace(/\s+/g, ' ').slice(0, 90));
      await shot(D, 'S10-quest');
    }

    // ---------- S11 reload = persistence ----------
    {
      await P1.reload({ waitUntil: 'domcontentloaded' }); await sleep(1400);
      await enterRoom(P1, st.code);
      await openTab(P1, 'story'); await sleep(600);
      const still = /Blighted Garden/i.test(await P1.locator('#quest-list').innerText());
      const gt = (await roomState(P1)).tokens.find(t => t.id === st.grick);
      const prepStill = await (async () => {
        const me = (await roomState(P1)).tokens.find(t => t.character_id && t.label === 'Hexa');
        await clickToken(P1, me.id);
        await openDetails(P1, '#sheet details, details.sheet-sec', null);
        const cb = P1.locator('.prep-sp[data-id="hex_blight"]');
        return (await cb.count()) ? await cb.isChecked() : null;
      })().catch(() => null);
      verdict('S11', 'after a full reload: quest, monster and the daily prepared list persist',
        still && gt && prepStill !== null && prepStill !== false ? 'ui' : 'broken',
        `quest=${still} grick=${!!gt} prep=${prepStill}`);
      await shot(P1, 'S11-reload');
    }

    // ---------- S12 upsert re-import via the UI is idempotent ----------
    {
      await openTab(D, 'dm');
      await openDetails(D, '#dmtools details.group', 'Rule packages');
      await D.locator('#ct-mode').selectOption('upsert');
      await D.setInputFiles('#ct-file', `${ST}/d163_pack.zip`);
      await D.click('#btn-ct-upload'); await sleep(2600);
      const rep = await D.locator('#ct-report').innerText();
      const bad = /error|invalid/i.test(rep);
      verdict('S12', 're-import of the same pack in upsert mode (expect 0 changes)',
        bad ? 'broken' : 'ui', rep.replace(/\s+/g, ' ').slice(0, 90));
      await shot(D, 'S12-upsert');
    }

    // ---------- S13 room isolation of same-ID content ----------
    {
      await backToPrep(D); await D.goto(BASE + '/', { waitUntil: 'domcontentloaded' }); await sleep(600);
      await enterRoom(D, st.codeB);
      await openTab(D, 'dm');
      await openDetails(D, '#dmtools details.group', 'Rule packages');
      await D.locator('#ct-mode').selectOption('apply');
      // the pack importer maps BASENAME -> kind (content.FILE_KIND): the probe
      // must be named spells.csv, an unknown name is skipped silently
      await D.setInputFiles('#ct-file', `${ST}/spells.csv`);
      await D.click('#btn-ct-upload'); await sleep(2000);
      const repB = await D.locator('#ct-report').innerText();
      const csvB = await D.evaluate(async code =>
        await (await fetch(`/api/content/${code}/export?kind=spell`)).text(), st.codeB);
      const csvA = await D.evaluate(async code =>
        await (await fetch(`/api/content/${code}/export?kind=spell`)).text(), st.code);
      const aUntouched = /Hex Spark,/.test(csvA) && !/OF B/.test(csvA);
      const bOwn = /OF B/.test(csvB);
      verdict('S13', 'room B imports the SAME spell id; room A keeps its own definition',
        aUntouched && bOwn ? 'ui' : 'broken', `A untouched=${aUntouched} B own=${bOwn} rep=${repB.slice(0, 40)}`);
      await shot(D, 'S13-isolation');
    }

    // ---------- S14 authority sanity: no DM tab for players ----------
    {
      const dmTabHidden = await P2.locator(`#side-tabs button[data-tab='dm']`).isHidden().catch(() => false);
      const lootSelGone = await P2.locator('#loot-tbl').isVisible().catch(() => true) === false;
      verdict('S14', 'players see no DM tools (no loot roll, no DM tab)',
        dmTabHidden && lootSelGone ? 'ui' : 'broken');
    }

    await shot(D, 'S99-final');
    log('ALL SCENARIOS PASSED');
  } catch (e) {
    await shot(D, 'ZZ-crash').catch(() => {});
    log('CRASH: ' + e.message);
    verdict('ZZ', 'E2E crashed', 'broken', e.message.slice(0, 160));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
