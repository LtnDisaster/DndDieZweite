// D161 Akt VI — persistence across a real server restart: the whole played
// session (rooms, sheets, maps, traps, loot state, log) must survive a
// `docker restart` byte-for-byte where it matters. Production UI only.
import {
  log, fail, shot, verdict, loadState, auth, enterRoom, sleep,
} from './e2e_d161_lib.mjs';
import { chromium } from 'playwright';
import { writeFileSync } from 'fs';

const st = loadState();
const code = st.code;

const SNAP = `
  const j = await (await fetch('/api/rooms/' + state.room.code + '/state')).json();
  const pick = (o, ks) => Object.fromEntries(ks.filter(k => k in o).map(k => [k, o[k]]));
  return {
    code: j.code,
    floors: j.floors, floor_levels: j.floor_levels,
    members: j.members.map(m => pick(m.char || {}, ['name','level','char_class','max_hp','hp','items','spells','spell_slots','resources','equipment','ac_total'])),
    tokens: j.tokens.map(t => pick(t, ['label','x','y','floor','hp','max_hp','owner_user_id','death','conds'])),
    initiative: j.initiative,
    messages: (j.messages || []).length,
    chat: (j.chat || []).length,
    quests: j.quests,
  };
`;
async function snap(p) {
  const s = await p.evaluate(`(async () => { ${SNAP} })()`);
  // position floats can carry animation jitter — quantise to cell centres
  const cs = 50;
  s.tokens.forEach((t) => {
    t.x = Math.round((t.x || 0) / cs) * cs; t.y = Math.round((t.y || 0) / cs) * cs;
    t.death = t.death && { s: t.death.s, f: t.death.f, stable: !!t.death.stable, dead: !!t.death.dead };
    t.conds = (t.conds || []).map((c) => c.k || c).sort();
  });
  for (const m of s.members) if (m.items) m.items = (m.items || []).map((i) => [i.id, i.qty || 1, !!i.attuned, !!i.equipped]).sort();
  s.members.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
  s.tokens.sort((a, b) => (a.label || '').localeCompare(b.label || ''));
  return s;
}
const mapSnap = (p, f) => p.evaluate(async (fl) => {
  const j = await (await fetch(`/api/rooms/${state.room.code}/state?floor=${fl}`)).json();
  return { objects: j.grid.objects, doors: j.grid.doors, traps: j.grid.traps, loot: j.grid.loot };
}, f);

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1400, height: 860 } });
const p = await ctx.newPage();
await auth(p, st.users.dm);
await enterRoom(p, code);
await sleep(1000);

const floors = await p.evaluate(async () =>
  (await (await fetch(`/api/rooms/${state.room.code}/state`)).json()).floors);
const before = await snap(p);
const mapsBefore = {};
for (const f of floors) mapsBefore[f] = await mapSnap(p, f);
writeFileSync('/st/persist_before.json', JSON.stringify({ before, mapsBefore }, null, 1));

// the restart is NOT a browser action — the runner restarts the container
// (see chain script); this script only waits for health and re-verifies.
await page_wait();
async function page_wait() {
  await p.evaluate(async () => {
    for (let i = 0; i < 120; i++) {
      try { const r = await fetch('/api/health', { cache: 'no-store' }); if (r.ok) return; } catch {}
      await new Promise((r) => setTimeout(r, 1000));
    }
    throw new Error('server never came back');
  });
}

// fresh socket after the restart: reload the whole SPA like a real operator
await p.reload({ waitUntil: 'networkidle' });
await sleep(1200);
await enterRoom(p, code);   // the SPA boots into the lobby; re-enter like an operator
await sleep(1200);
const after = await snap(p);
const mapsAfter = {};
for (const f of floors) mapsAfter[f] = await mapSnap(p, f);
writeFileSync('/st/persist_after.json', JSON.stringify({ after, mapsAfter }, null, 1));

const keys = ['code', 'floors', 'floor_levels', 'members', 'tokens', 'initiative', 'quests'];
const lost = keys.filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]));
const mapLost = floors.filter((f) => JSON.stringify(mapsBefore[f]) !== JSON.stringify(mapsAfter[f]));
verdict('act6', 'full session survives a real container restart (sheets/tokens/maps/traps/loot)',
  lost.length === 0 && mapLost.length === 0 ? 'ui' : 'broken',
  `diff-in: ${JSON.stringify([...lost, ...mapLost.map((f) => 'map:' + f)])}`);
if (lost.length || mapLost.length) {
  for (const k of lost) log(`  DIFF ${k}:\n before=${JSON.stringify(before[k]).slice(0, 300)}\n after =${JSON.stringify(after[k]).slice(0, 300)}`);
  for (const f of mapLost) log(`  DIFF map ${f}:\n before=${JSON.stringify(mapsBefore[f]).slice(0, 400)}\n after =${JSON.stringify(mapsAfter[f]).slice(0, 400)}`);
}
verdict('act6', 'the campaign log survives (rounds/traps/rests still readable)',
  after.messages >= before.messages ? 'ui' : 'broken',
  `messages ${before.messages} -> ${after.messages}`);
await shot(p, 'T6-after-restart');

log('AKT VI COMPLETE');
await browser.close();
