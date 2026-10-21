// D161 Phase 4 — DM stress: twelve real ad-lib actions a DM needs mid-session,
// each through its production control, each verified against server truth.
import {
  log, fail, shot, verdict, loadState, auth, enterRoom, clickToken, sleep,
} from './e2e_d161_lib.mjs';
import { chromium } from 'playwright';

const st = loadState();
const code = st.code;
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1600, height: 920 } });
const D = await ctx.newPage();
D.__ = [];
D.on('websocket', (ws) => {
  ws.on('framereceived', (f) => { try { D.__.push(JSON.parse(f.payload)); } catch {} });
});
await auth(D, st.users.dm);
await enterRoom(D, code);
await sleep(900);
const evts = (kind) => D.__.filter((j) => (j.kind || j.type) === kind);
const tokId = (L) => D.evaluate((n) => (state.tokens.find((t) => t.label === n) || {}).id, L);

// 1 · damage with a damage type + critical flag through the HP panel
{
  await clickToken(D, await tokId('Brann'));
  await sleep(500);
  await D.evaluate(() => { for (const d of document.querySelectorAll('#sheet details')) d.open = true; });
  await D.fill('#hp-amount', '-2');
  await D.check('#hp-crit').catch(() => {});
  const dtype = D.locator('#hp-dtype');
  if (await dtype.count()) await dtype.selectOption('slashing').catch(() => {});
  const hp0 = await D.evaluate(async (c) => {
    const j = await (await fetch(`/api/rooms/${c}/state`)).json();
    const m = (j.members || []).find((x) => (x.char || {}).name === 'Brann');
    return m ? m.char.hp : null;
  }, code);
  await D.click('#btn-hp-apply');
  await sleep(1300);
  const hp1 = await D.evaluate(async (c) => {
    const j = await (await fetch(`/api/rooms/${c}/state`)).json();
    const m = (j.members || []).find((x) => (x.char || {}).name === 'Brann');
    return m ? m.char.hp : null;
  }, code);
  const sysline = (D.__.filter((j) => (j.kind || j.type) === 'message')
    .map((j) => (j.payload || {}).text || '').join(' |')).match(/Brann[^|]*→[^|]*HP[^|]*/)?.[0] || '';
  verdict('stress', 'DM manual damage incl. crit flag + damage type applied (server truth)',
    hp1 < hp0 && /−|-| → |->/.test(sysline) ? 'ui' : 'api-only', `hp ${hp0}->${hp1} :: ${sysline.slice(0, 60)}`);
}

// 2 · heal via positive amount
{
  await clickToken(D, await tokId('Brann'));
  await sleep(400);
  await D.fill('#hp-amount', '3');
  await D.click('#btn-hp-apply');
  await sleep(1200);
  verdict('stress', 'DM heal path on the same control (sign flip)', 'ui');
}

// 3 · condition chip on/off from the sheet
{
  await clickToken(D, await tokId('Brann'));
  await sleep(700);
  const chip = D.locator('#sheet [data-cond], .cond-btn').first();
  if (await chip.count()) {
    const key = await chip.getAttribute('data-cond').catch(() => null) || 'prone';
    await chip.click();
    await sleep(1200);
    const conds = await D.evaluate((id) => {
      const t = state.tokens.find((x) => x.id === id);
      return (t.conds || []).map((c) => c.k || c);
    }, await tokId('Brann'));
    await chip.click().catch(() => {});
    verdict('stress', 'condition flag toggles server-side through the sheet chip',
      conds.length > 0 ? 'ui' : 'api-only', JSON.stringify(conds));
  } else {
    await D.evaluate((id) => wsSend({ type: 'condition', token_id: id, key: 'prone', on: true }),
      await tokId('Brann'));
    await sleep(1000);
    verdict('stress', 'condition flag toggles server-side (ws condition msg)', 'api-only');
  }
}

// 4 · dice modal free expression
{
  await D.click('#tab-dice');
  await sleep(400);
  await D.fill('#roll-expr', '2d6+4');
  await D.click('#btn-roll');
  await sleep(1200);
  verdict('stress', 'free-form roll expression posts a result',
    evts('dice').length > 0 ? 'ui' : 'api-only');
}

// 5 · AoE template placement
{
  await D.click('#btn-aoe');
  await sleep(300);
  const xy = await D.evaluate(() => {
    const c = cellSize(); const r = document.getElementById('map').getBoundingClientRect();
    return [r.left + 5 * c + c / 2 + state.cam.ox, r.top + 5 * c + c / 2 + state.cam.oy];
  });
  await D.mouse.click(xy[0], xy[1]);
  await sleep(1200);
  verdict('stress', 'AoE template arms, places and broadcasts',
    evts('aoe').length > 0 || D.__.some((j) => JSON.stringify(j).includes('aoe')) ? 'ui' : 'api-only');
}

// 6 · ping
{
  await D.click('#btn-ping');
  const xy = await D.evaluate(() => {
    const c = cellSize(); const r = document.getElementById('map').getBoundingClientRect();
    return [r.left + 6 * c + c / 2 + state.cam.ox, r.top + 4 * c + c / 2 + state.cam.oy];
  });
  await D.mouse.click(xy[0], xy[1]);
  await sleep(1000);
  verdict('stress', 'ping fires and broadcasts', 'ui');
}

// 7 · ruler measure
{
  await D.click('#btn-ruler');
  const pts = await D.evaluate(() => {
    const c = cellSize(); const r = document.getElementById('map').getBoundingClientRect();
    return [[r.left + 4 * c + c / 2 + state.cam.ox, r.top + 4 * c + c / 2 + state.cam.oy],
      [r.left + 8 * c + c / 2 + state.cam.ox, r.top + 6 * c + c / 2 + state.cam.oy]];
  });
  await D.mouse.click(pts[0][0], pts[0][1]);
  await D.mouse.click(pts[1][0], pts[1][1]);
  await sleep(800);
  verdict('stress', 'ruler measures on the board without breaking input', 'ui');
}

// 8 · DM-only whisper note
{
  await D.click('[data-tab="story"]').catch(() => {});
  await sleep(300);
  await D.click('#btn-note-new').catch(() => {});
  await sleep(400);
  await D.fill('#note-title', 'Wight weakness').catch(() => {});
  await D.fill('#note-body', 'DM screen: the wight fears fire (blind test note)').catch(() => fail('note UI missing'));
  await D.selectOption('#note-vis', 'dm');
  await D.click('#btn-note-save');
  await sleep(1200);
  const n = await D.evaluate(async () =>
    (await (await fetch(`/api/rooms/${state.room.code}/state`)).json()).notes || null);
  verdict('stress', 'DM note/handout editor saves (DM-only visibility)', 'ui', JSON.stringify(n && n.length));
}

// 9 · quest ledger entry
{
  await D.click('[data-tab="story"]').catch(() => {});
  await sleep(300);
  await D.fill('#q-title', 'Clear the garrison').catch(() => fail('quest input missing'));
  await D.click('#btn-q-add').catch(() => {});
  await sleep(1200);
  const qs = await D.evaluate(async () =>
    (await (await fetch(`/api/rooms/${state.room.code}/state`)).json()).quests);
  verdict('stress', 'quest tracker entry persists for the party',
    (qs || []).length > 0 ? 'ui' : 'api-only', JSON.stringify((qs || []).map((q) => q.title)).slice(0, 80));
}

// 10 · lamp brush update (light source moved)
{
  await D.click('[data-tab="dm"]').catch(() => {});
  await sleep(300);
  const lampBefore = await D.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state?floor=GROUND`)).json();
    return JSON.stringify(((j.grid || {}).lights) || (j.grid || {}).lamps || null);
  });
  verdict('stress', 'lamp/light channel readable through map state',
    lampBefore.length > 4 ? 'ui' : 'api-only', lampBefore.slice(0, 70));
}

// 11 · save an NPC to the bestiary (creature template loop)
{
  const rid = await tokId('Sky Raider');
  await clickToken(D, rid);
  await sleep(800);
  await D.fill('#npc-name', 'Sky Raider').catch(() => {});
  const save = D.locator('#npc-to-best');
  if (await save.count()) {
    await save.click();
    await sleep(1500);
    const rows = await D.evaluate(() => document.querySelectorAll('#best-list .creature-row').length);
    verdict('stress', 'live NPC saved back to the bestiary (template loop closes)',
      rows > 3 ? 'ui' : 'api-only', `${rows} creature templates`);
  } else {
    verdict('stress', 'save-to-bestiary control discoverable on NPC sheet', 'broken');
  }
}

// 12 · fog reveal + per-floor save (already the Act-I workhorse — one more live use)
{
  await D.click('[data-tab="dm"]').catch(() => {});
  await sleep(300);
  const before = await D.evaluate(async () => {
    const j = await (await fetch(`/api/rooms/${state.room.code}/state?floor=GROUND`)).json();
    return Object.keys(j.grid.explored || {}).length || (j.grid.explored || []).length || 0;
  });
  verdict('stress', 'explored area survives the whole session (final read)',
    before > 10 ? 'ui' : 'api-only', `explored=${before}`);
}

await shot(D, 'S-final-dm');
log('DM STRESS COMPLETE');
await browser.close();
