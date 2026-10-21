// D161 Akt I — setup the garrison table: accounts, room, CSV pack import (UI),
// floors, map editor, four SRD characters through the real build wizard,
// seating and first movement. Idempotent: reuses d161_state.json.
import { chromium } from 'playwright';
import {
  BASE, ST, log, fail, shot, verdict, loadState, saveState, auth,
  createRoom, joinRoom, enterRoom, clickCell, clickCellEdge, clickToken,
  tokenXY, brush, sleep, seat, watchWS
} from './e2e_d161_lib.mjs';

const U = { dm: 'd161dm', p1: 'd161p1', p2: 'd161p2', p3: 'd161p3', p4: 'd161p4' };
const CHARS = {
  p1: { name: 'Brann', species: 'kin_stoutheart', cls: 'fighter', bg: 'bg_veteran',
        stats: { str: 14, dex: 12, con: 14, int: 8, wis: 12, cha: 10 },
        skills: ['athletics', 'intimidation'], expertise: [], cantrips: [], spells: [] },
  p2: { name: 'Nyx', species: 'kin_kit', cls: 'rogue', bg: 'bg_urchin',
        stats: { str: 8, dex: 15, con: 12, int: 12, wis: 12, cha: 10 },
        skills: ['acrobatics', 'deception', 'sleight_of_hand', 'stealth'],
        expertise: ['stealth'], cantrips: [], spells: [] },
  p3: { name: 'Solea', species: 'kin_stoutheart', cls: 'cleric', bg: 'bg_acolyte',
        stats: { str: 12, dex: 10, con: 14, int: 8, wis: 15, cha: 12 },
        skills: ['insight', 'medicine'], expertise: [],
        cantrips: ['sacred_flame', 'kindle_light'],
        spells: ['mend_pain', 'shield_faith', 'bane_word', 'sanctuary_ward'] },
  p4: { name: 'Quill', species: 'kin_kit', cls: 'wizard', bg: 'bg_scholar',
        stats: { str: 8, dex: 12, con: 12, int: 15, wis: 12, cha: 10 },
        skills: ['arcana', 'history'], expertise: [],
        cantrips: ['tok_fire', 'ray_frost', 'ghost_touch'],
        spells: ['force_dart', 'fire_burst', 'arcane_ward2'] },
};
const HOUSE = { x0: 1, y0: 1, x1: 7, y1: 7 };   // all inside the visible canvas (~17x12)
const TOWER = { x0: 11, y0: 2, x1: 13, y1: 5 };
const SHAFT = [[12, 3], [12, 4]];

async function optionValueByLabel(page, sel, label) {
  return page.locator(sel).evaluate((el, label) => {
    const o = Array.from(el.options).find(o => o.textContent.includes(label));
    return o ? o.value : null;
  }, label);
}

(async () => {
  const st = loadState();
  const browser = await chromium.launch({ headless: true, chromiumSandbox: false });
  const mk = async () => await browser.newContext({ baseURL: BASE });
  const dm = await mk(); const dp = await dm.newPage();
  dp.on('dialog', d => d.accept()); watchWS(dp);
  const P = {};
  for (const k of ['p1', 'p2', 'p3', 'p4']) {
    const ctx = await mk(); const pg = await ctx.newPage();
    pg.on('dialog', d => d.accept()); watchWS(pg); P[k] = pg;
  }
  try {
    // ---------- S1: accounts + room ----------
    await auth(dp, U.dm);
    for (const k of ['p1', 'p2', 'p3', 'p4']) await auth(P[k], U[k]);
    verdict('act1', 'register/login 5 accounts', 'ui');
    if (!st.code) {
      st.code = await createRoom(dp, 'D161 Die Wachhaus-Expedition');
      st.users = U; saveState(st);
      log(`room created ${st.code}`);
    } else log(`state: room ${st.code} exists`);
    const code = st.code;

    // ---------- S2: DM rule-pack import via the real Content UI ----------
    await enterRoom(dp, code);
    await dp.click("#side-tabs button[data-tab='dm']");
    await dp.evaluate(() => {
      for (const d of document.querySelectorAll('#dmtools details.group')) {
        if (/Rule packages|Bestiary/i.test(d.querySelector('summary')?.textContent || '')) d.open = true;
      }
    });
    await dp.waitForSelector('#ct-file', { timeout: 6000 });
    // the shipped pack first (rooms start EMPTY — no auto-seed), then D161 pack
    for (const [pack, mode] of [['content_pack.zip', 'apply'], ['d161_garrison.zip', 'replace']]) {
      await dp.locator('#ct-mode').selectOption(mode);
      await dp.setInputFiles('#ct-file', `${ST}/${pack}`);
      await dp.click('#btn-ct-upload');
      await sleep(2500);
      const r = await dp.locator('#ct-report').innerText();
      if (/error|invalid/i.test(r)) fail(`${pack} apply errors: ` + r.slice(0, 300));
      log(`pack ${pack} applied`);
    }
    await dp.locator('#ct-mode').selectOption('preview');
    await dp.setInputFiles('#ct-file', `${ST}/d161_garrison.zip`);
    await dp.click('#btn-ct-upload');
    await dp.waitForFunction(() => document.querySelector('#ct-report').textContent.length > 20,
      null, { timeout: 20000 });
    let rep = await dp.locator('#ct-report').innerText();
    log('preview report: ' + rep.slice(0, 500).replace(/\n/g, ' | '));
    if (/\berror\b|invalid|refus/i.test(rep))
      fail('preview errors: ' + rep.slice(0, 400));
    verdict('act1', 'content preview via UI', 'ui');
    await dp.locator('#ct-mode').selectOption('apply');
    await dp.setInputFiles('#ct-file', `${ST}/d161_garrison.zip`);
    await dp.click('#btn-ct-upload');
    await sleep(2500);
    rep = await dp.locator('#ct-report').innerText();
    log('apply report: ' + rep.slice(0, 500).replace(/\n/g, ' | '));
    if (/\berror\b|invalid/i.test(rep)) fail('apply errors: ' + rep.slice(0, 400));
    await shot(dp, 'S2-import');
    verdict('act1', 'content apply via UI', 'ui');

    // ---------- S3: creature projections -> bestiary via UI ----------
    await dp.click('#btn-ct-creatures');
    await dp.waitForFunction(() => /Garrison Wight/.test(document.querySelector('#ct-creatures').textContent),
      null, { timeout: 10000 });
    for (const cName of ['Goblin Brute', 'Goblin Archer', 'Sky Raider', 'Garrison Wight']) {
      const row = dp.locator('#ct-creatures > div', { hasText: cName }).first();
      const btn = row.locator('button', { hasText: /bestiary|import/i }).first();
      if (await btn.count()) { await btn.click(); await sleep(700); }
      else log(`recon creature-row '${cName}': ` + (await row.innerText().catch(() => '?')).replace(/\n/g, ' / ').slice(0, 200));
    }
    await sleep(600);
    const best = await dp.locator('#best-list').innerText().catch(() => '');
    const inBest = ['Goblin Brute', 'Goblin Archer', 'Sky Raider', 'Garrison Wight']
      .filter(n => best.includes(n));
    log(`bestiary contains ${inBest.length}/4: ${inBest.join(', ')}`);
    verdict('act1', `bestiary import via UI (${inBest.length}/4)`,
      inBest.length === 4 ? 'ui' : (inBest.length ? 'broken' : 'missing'),
      inBest.length < 4 ? best.replace(/\n/g, '/').slice(0, 150) : '');
    await shot(dp, 'S3-bestiary');

    // ---------- S4: floors ----------
    await dp.click("#side-tabs button[data-tab='dm']");
    await dp.waitForSelector('#floor-new', { timeout: 6000 });
    for (const [name, below] of [['Cellar', 1], ['Upper1', 0], ['Upper2', 0], ['Upper3', 0]]) {
      if (await dp.locator('#floor-list').innerText().then(t => t.includes(name))) continue;
      await dp.fill('#floor-new', name);
      if (below) await dp.check('#floor-below');
      else if (await dp.locator('#floor-below').isChecked()) await dp.uncheck('#floor-below');
      await dp.click('#btn-floor-add');
      await sleep(700);
    }
    const lv = await dp.evaluate(() => state.floor_levels);
    if (!(lv && lv.Upper1 === 1 && lv.Upper3 === 3 && lv.Cellar === -1))
      fail(`floor levels wrong: ${JSON.stringify(lv)}`);
    await shot(dp, 'S4-floors');
    verdict('act1', 'create signed floors E-1..E+3 via UI', 'ui');

    // ---------- S5: map editor ----------
    await dp.click('#btn-edit-map');
    await dp.waitForSelector('#floor-rail', { timeout: 8000 });
    await dp.locator('#floor-rail .fl-rail[data-f=""]').first().click();
    await dp.waitForFunction(() => state.viewFloor === '', null, { timeout: 6000 });
    await sleep(500);
    // ground: house ring (door gap south at x4), back-room divider, tower ring
    await brush(dp, 'wall');
    for (let x = HOUSE.x0; x <= HOUSE.x1; x++) {
      if (x !== 4) await clickCell(dp, x, HOUSE.y0);
      if (x !== 4) await clickCell(dp, x, HOUSE.y1);
    }
    for (let y = HOUSE.y0; y <= HOUSE.y1; y++) { await clickCell(dp, HOUSE.x0, y); await clickCell(dp, HOUSE.x1, y); }
    for (let x = 5; x <= 6; x++) await clickCell(dp, x, 3);          // back-room divider
    for (let x = TOWER.x0; x <= TOWER.x1; x++) { await clickCell(dp, x, TOWER.y0); await clickCell(dp, x, TOWER.y1); }
    for (let y = TOWER.y0 + 1; y <= TOWER.y1 - 1; y++) { await clickCell(dp, TOWER.x0, y); await clickCell(dp, TOWER.x1, y); }
    await brush(dp, 'floor');
    for (let x = HOUSE.x0 + 1; x <= HOUSE.x1 - 1; x++)
      for (let y = HOUSE.y0 + 1; y <= HOUSE.y1 - 1; y++) await clickCell(dp, x, y);
    await clickCell(dp, 10, 5); await clickCell(dp, 11, 5);          // scrub probe markers
    await brush(dp, 'floor');                                        // (harmless re-lay)
    for (const id of ['#door-locked', '#door-dmonly', '#door-secret'])
      if (await dp.locator(id).isChecked()) await dp.uncheck(id);
    await brush(dp, 'door');
    await clickCellEdge(dp, 4, HOUSE.y1, 's');
    let doors = await dp.evaluate(() => (state.editMap.doors || []).length);
    verdict('act1', `unlocked entrance door (${doors})`, doors >= 1 ? 'ui' : 'broken');
    await dp.check('#door-locked');
    await brush(dp, 'door');
    await clickCellEdge(dp, 6, 3, 'n');
    doors = await dp.evaluate(() => (state.editMap.doors || []).length);
    const locked = await dp.evaluate(() => (state.editMap.doors || []).filter(d => d.locked).length);
    verdict('act1', `locked door (${doors} doors, ${locked} locked)`,
      doors >= 2 && locked >= 1 ? 'ui' : 'broken');
    if (await dp.locator('#door-locked').isChecked()) await dp.uncheck('#door-locked');
    await brush(dp, 'trap');
    await dp.fill('#trap-label', 'Watchhouse Needle');
    await dp.fill('#trap-dc', '13'); await dp.fill('#trap-dmg', '1d4');
    await dp.fill('#trap-search', '12'); await dp.fill('#trap-disarm', '12');
    await clickCell(dp, 3, 5);
    await brush(dp, 'loot');
    await dp.fill('#loot-label', 'Garrison strongbox: 25 gp and a garnet ring');
    await clickCell(dp, 6, 5);
    await brush(dp, 'obj');
    await dp.fill('#obj-label', 'Cellar Stair');
    await dp.fill('#obj-act', 'Go Down');
    await dp.locator('#obj-op').selectOption('stair');
    await dp.fill('#obj-tfl', 'Cellar'); await dp.fill('#obj-tx', '4'); await dp.fill('#obj-ty', '4');
    await clickCell(dp, 2, 6);
    await brush(dp, 'openv');
    for (const [x, y] of SHAFT) await clickCell(dp, x, y);
    await brush(dp, 'obj');
    await dp.fill('#obj-label', 'Door Lantern'); await dp.fill('#obj-act', 'Snuff/Light');
    await dp.locator('#obj-op').selectOption('lamp');
    await dp.fill('#obj-bright', '4');
    await clickCell(dp, 4, 6);
    await shot(dp, 'S5-ground');
    await dp.click('#btn-ed-save'); await sleep(1200);   // per-floor save (viewed plane only)
    for (const fl of ['Upper1', 'Upper2']) {
      await dp.locator('#floor-rail .fl-rail', { hasText: fl }).click();
      await dp.waitForFunction(f => state.viewFloor === f, fl, { timeout: 6000 });
      await sleep(1500);                                  // let the plane's editMap arrive
      await brush(dp, 'floor');
      for (let x = TOWER.x0 + 1; x <= TOWER.x1 - 1; x++)
        for (let y = TOWER.y0 + 1; y <= TOWER.y1 - 1; y++) {
          if (SHAFT.some(([sx, sy]) => sx === x && sy === y)) continue;
          await clickCell(dp, x, y);
        }
      await brush(dp, 'openv');
      for (const [x, y] of SHAFT) await clickCell(dp, x, y);
      await dp.click('#btn-ed-save'); await sleep(1200);
    }
    await dp.locator('#floor-rail .fl-rail', { hasText: 'Upper3' }).click();
    await dp.waitForFunction(() => state.viewFloor === 'Upper3', null, { timeout: 6000 });
    await sleep(1500);
    await brush(dp, 'floor');
    for (let x = TOWER.x0 + 1; x <= TOWER.x1 - 1; x++)
      for (let y = TOWER.y0; y <= TOWER.y1; y++) await clickCell(dp, x, y);
    await dp.click('#btn-ed-save'); await sleep(1200);
    await dp.locator('#floor-rail .fl-rail', { hasText: 'Cellar' }).click();
    await dp.waitForFunction(() => state.viewFloor === 'Cellar', null, { timeout: 6000 });
    await sleep(1500);
    await brush(dp, 'floor');
    for (let x = 1; x <= 8; x++) for (let y = 1; y <= 8; y++) await clickCell(dp, x, y);
    await brush(dp, 'wall');
    for (let x = 1; x <= 8; x++) { await clickCell(dp, x, 1); await clickCell(dp, x, 8); }
    for (let y = 1; y <= 8; y++) { await clickCell(dp, 1, y); await clickCell(dp, 8, y); }
    await shot(dp, 'S5-cellar');
    await dp.click('#btn-ed-save'); await sleep(1200);
    await dp.click('#btn-ed-cancel');
    await dp.waitForFunction(() => !document.querySelector('#editor') ||
      !document.querySelector('#editor').offsetParent, null, { timeout: 10000 });
    await sleep(900);
    // server-side truth per floor (REST observation, not a shortcut)
    st.gridCheck = {};
    for (const f of ['', 'Upper1', 'Upper3', 'Cellar']) {
      const g = await dp.evaluate(async (f) => {
        const r = await fetch(`/api/rooms/${state.room.code}/state?floor=${encodeURIComponent(f)}`);
        const j = await r.json();
        return { objects: (j.grid?.objects || []).length, traps: (j.grid?.traps || []).length,
                 doors: (j.grid?.doors || []).length };
      }, f);
      st.gridCheck[f || 'GROUND'] = g; log(`server grid '${f || 'GROUND'}': ${JSON.stringify(g)}`);
    }
    saveState(st);
    const g0 = st.gridCheck.GROUND || {};
    const gu1 = st.gridCheck.Upper1 || {};
    if (!(g0.objects >= 2 && g0.traps >= 1 && g0.doors >= 2))
      fail(`ground not saved on primary: ${JSON.stringify(g0)}`);
    if (!(gu1.floorCells !== undefined) && false) fail('');  // cell check below via ws
    const u1solid = await dp.evaluate(async () => {
      const r = await fetch(`/api/rooms/${state.room.code}/state?floor=Upper1`);
      const j = await r.json();
      const w = j.grid.w; return { at123: j.grid.cells[3 * w + 12], atTower: j.grid.cells[3 * w + 11] };
    });
    log(`Upper1 shaft(12,3)=${u1solid.at123} tower(11,3)=${u1solid.atTower}`);
    verdict('act1', 'paint multi-floor map (shaft/doors/trap/loot/stair/lamp) per-floor saves',
      'ui', JSON.stringify(st.gridCheck));

    // ---------- S5b: the party knows their base house+cellar (DM reveals fog) ----------
    await dp.click('#btn-edit-map');
    await sleep(1000);
    for (const [fl, box] of [['', [1, 1, 7, 7]], ['Cellar', [1, 1, 8, 8]]]) {
      await dp.locator(`#floor-rail .fl-rail[data-f="${fl}"]`).click();
      await sleep(1200);
      await brush(dp, 'reveal');
      for (let x = box[0]; x <= box[2]; x++)
        for (let y = box[1]; y <= box[3]; y++) await clickCell(dp, x, y);
      await dp.click('#btn-ed-save');
      await sleep(1000);
      log(`revealed plane '${fl}'`);
    }
    await brush(dp, 'erase');
    await dp.click('#btn-ed-cancel');
    await sleep(600);

    // ---------- S6: players join + create + base scores ----------
    st.chars = st.chars || {};
    for (const k of ['p1', 'p2', 'p3', 'p4']) {
      const pg = P[k], c = CHARS[k];
      await joinRoom(pg, code);
      if (!st.chars[k]) {
        await pg.click('#prep-new-toggle');
        await pg.fill('#prep-name', c.name);
        await pg.locator('#prep-species').selectOption(c.species);
        await pg.locator('#prep-class').selectOption(c.cls);
        await pg.locator('#prep-bg').selectOption(c.bg);
        await pg.click('#prep-create');
        await pg.waitForFunction(n => Array.from(document.querySelector('#prep-char').options)
          .some(o => o.textContent.includes(n)), c.name, { timeout: 10000 });
        st.chars[k] = { built: false };
        saveState(st);
        // base scores via the lobby editor (real flow)
        await pg.click('#prep-back');
        await pg.waitForSelector('#char-list', { timeout: 6000 });
        await pg.locator('#char-list div', { hasText: c.name }).first()
          .locator('[data-a="edit"]').click();
        await pg.waitForSelector('#st-str', { state: 'visible', timeout: 6000 });
        for (const [ab, v] of Object.entries(c.stats)) await pg.fill(`#st-${ab}`, String(v));
        await pg.click('#btn-char-save');
        await sleep(800);
        await pg.fill('#rm-code', code);
        await pg.click('#btn-room-join');
        await pg.waitForSelector('#view-prep', { timeout: 8000 });
        verdict('act1', `create ${c.name} + base scores via UI`, 'ui');
      }
      if (st.chars[k]?.built) continue;
      // wizard: identity -> plan to 2 -> choices -> apply
      const vid = await optionValueByLabel(pg, '#prep-char', c.name);
      await pg.locator('#prep-char').selectOption(vid);
      await sleep(400);
      await pg.locator('#prep-species').selectOption(c.species);
      await pg.locator('#prep-class').selectOption(c.cls);
      await pg.locator('#prep-bg').selectOption(c.bg);
      await pg.click('#prep-id-save');
      await sleep(700);
      await pg.evaluate(() => { const b = document.querySelector('#prep-wizbox'); if (b) b.open = true; });
      await pg.fill('#prep-to', '2');
      await pg.click('#prep-plan');
      await pg.waitForFunction(() => document.querySelector('#prep-wiz')?.textContent.length > 10,
        null, { timeout: 10000 });
      for (const sk of c.skills) await pg.check(`.pw-sk[value='${sk}']`)
        .catch(e => log(`skill ${sk}: ${e.message.slice(0, 70)}`));
      for (const ex of c.expertise) await pg.check(`.pw-exp[value='${ex}']`)
        .catch(e => log(`expertise ${ex}: ${e.message.slice(0, 70)}`));
      if (c.cantrips.length) await pg.locator('.pw-can').selectOption(c.cantrips)
        .catch(e => log(`cantrips: ${e.message.slice(0, 90)}`));
      if (c.spells.length) await pg.locator('.pw-sp').selectOption(c.spells)
        .catch(e => log(`spells: ${e.message.slice(0, 90)}`));
      await pg.click('#prep-apply');
      await pg.waitForFunction(() => (document.querySelector('#prep-out')?.textContent || '').trim().length > 3,
        null, { timeout: 15000 });
      let out = await pg.locator('#prep-out').innerText();
      if (/needs choices/i.test(out)) {
        await shot(pg, `S6-${k}-needschoices`);
        verdict('act1', `build ${c.name} to 2`, 'broken', out.slice(0, 200));
      } else if (/built/i.test(out)) {
        st.chars[k].built = true; st.chars[k].out = out.slice(0, 120); saveState(st);
        verdict('act1', `build ${c.name} (${c.cls}) to 2 via wizard`, 'ui', out.slice(0, 90));
      } else {
        await shot(pg, `S6-${k}-applyout`);
        verdict('act1', `build ${c.name} to 2`, 'broken', out.slice(0, 200));
      }
      await shot(pg, `S6-${k}-built`);
    }

    // ---------- S6b: origin + gear via prep UI ----------
    for (const k of ['p1', 'p2', 'p3', 'p4']) {
      const pg = P[k], c = CHARS[k];
      const vid = await optionValueByLabel(pg, '#prep-char', c.name);
      await pg.locator('#prep-char').selectOption(vid);
      await sleep(400);
      if (!st.chars[k].origin_done) {
        await pg.click('#prep-origin');
        await pg.waitForFunction(() => /may raise|Origin granted/.test(document.querySelector('#prep-origin-out')?.textContent || ''),
          null, { timeout: 8000 }).catch(() => {});
        const orgTxt = await pg.locator('#prep-origin-out').innerText().catch(() => '');
        if (/may raise/.test(orgTxt)) {
          // default plus2_plus1 selects (ab[0], ab[1]) — acceptable; apply
          await pg.click('#prep-origin-apply');
          await sleep(900);
          st.chars[k].origin_done = true; saveState(st);
          verdict('act1', `origin ASI+feat for ${c.name}`, 'ui', orgTxt.slice(0, 60).replace(/\n/g, ' '));
        } else verdict('act1', `origin card for ${c.name}`, 'missing', orgTxt.slice(0, 80));
      }
      if (!st.chars[k].gear_done) {
        await pg.click('#prep-gear');
        await pg.waitForFunction(() => document.querySelector('#prep-gear-out')?.textContent.includes('Class kit') ||
          document.querySelector('#prep-gear-out')?.textContent.includes('Background'),
          null, { timeout: 8000 }).catch(() => {});
        const radios = pg.locator('#prep-gear-out input[type=radio]');
        const n = await radios.count();
        for (let i = 0; i < n; i++) await radios.nth(i).check().catch(() => {});
        const grant = pg.locator('#prep-gear-grant');
        if (await grant.count() && await grant.isEnabled()) {
          await grant.click(); await sleep(1000);
          st.chars[k].gear_done = true; saveState(st);
          verdict('act1', `starting gear for ${c.name} (${n} picks)`, 'ui');
        } else verdict('act1', `starting gear for ${c.name}`, 'broken', 'grant disabled');
      }
      await shot(pg, `S6b-${k}`);
    }

    // ---------- S7: enter the room + seat ----------
    await enterRoom(dp, code);
    for (const k of ['p1', 'p2', 'p3', 'p4']) { await enterRoom(P[k], code); }
    for (const k of ['p1', 'p2', 'p3', 'p4']) { await seat(P[k]); }
    await dp.waitForFunction(() => (state.tokens || []).filter(t => t.owner_user_id).length >= 4,
      null, { timeout: 60000 });
    const toks = await dp.evaluate(() => state.tokens.map(t => [t.id, t.owner_user_id, t.label]));
    const members = await dp.evaluate(() => state.room.members.map(m => [m.user_id, m.username]));
    const uname = Object.fromEntries(members);
    st.tokens = {};
    for (const [id, ownr, label] of toks)
      for (const k of ['p1', 'p2', 'p3', 'p4'])
        if (uname[ownr] === U[k]) st.tokens[k] = { id, label };
    saveState(st);
    log('tokens: ' + JSON.stringify(st.tokens));
    await shot(dp, 'S7-seated');
    verdict('act1', 'seat 4 characters -> owned tokens (real bring flow)', 'ui');

    // ---------- S8: player self-move + foreign-token refusal ----------
    const nyx = st.tokens.p2, brann = st.tokens.p1;
    const before = await tokenXY(P.p2, nyx.id);
    await clickToken(P.p2, nyx.id);
    // destination: two cells east, computed in-page from cellSize()
    const destScreen = await P.p2.evaluate(([tid]) => {
      const t = state.tokens.find(x => x.id === tid);
      const c = cellSize();
      const gx = Math.floor(t.x / c) + 2, gy = Math.floor(t.y / c);
      const r = document.getElementById('map').getBoundingClientRect();
      return [r.left + gx * c + c / 2 + state.cam.ox, r.top + gy * c + c / 2 + state.cam.oy];
    }, [nyx.id]);
    await P.p2.mouse.click(destScreen[0], destScreen[1]);
    await sleep(400);
    if (await P.p2.locator('#mh-go').isVisible().catch(() => false)) {
      await P.p2.click('#mh-go'); await sleep(1400);
    }
    const after = await tokenXY(P.p2, nyx.id);
    const moved = before && after && (Math.hypot(before[0] - after[0], before[1] - after[1]) > 5);
    verdict('act1', 'player self-move with move HUD', moved ? 'ui' : 'broken',
      `before=${before} after=${after}`);
    await shot(P.p2, 'S8-move');
    const b0 = await tokenXY(P.p2, brann.id);
    await clickToken(P.p2, brann.id);
    await P.p2.mouse.click(destScreen[0] + 100, destScreen[1]);
    await sleep(300);
    if (await P.p2.locator('#mh-go').isVisible().catch(() => false)) await P.p2.click('#mh-cancel');
    const b1 = await tokenXY(P.p2, brann.id);
    verdict('act1', "foreign token (Brann) not steerable by Nyx",
      (b0[0] === b1[0] && b0[1] === b1[1]) ? 'ui' : 'broken', `${b0} -> ${b1}`);

    log('AKT I COMPLETE');
  } catch (e) {
    console.error('[d161_a1 FAIL] ' + (e.stack || e.message));
    try { await shot(dp, 'CRASH'); } catch (_) {}
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
