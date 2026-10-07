/* Core: DOM helpers, shared state, API client. Must load first. */
(typeof window !== "undefined") && ((window.__BUILDS = window.__BUILDS || {})["10_core.js"] = window.__BUILD__ || "?");
const $ = (id) => document.getElementById(id);
const STATS = [["str","STR"],["dex","DEX"],["con","CON"],["int","INT"],["wis","WIS"],["cha","CHA"]];
const state = { me:null, room:null, roomDeleted:false, ws:null, online:new Set(), tokens:[], ghosts:[], init:null,
                bg:null, sel:null, drag:null, pan:null, charEdit:null, weaponRows:[], itemRows:[],
                 plan:null, planRequest:null, moving:new Set(), reconnectTimer:null,
                 grid:null, editMap:null, editing:false, brush:"wall", fogTouched:{},
                 aoe:null, aoeArmed:false, pingArmed:false, rulerArmed:false, pings:[], ruler:null,
                 bestiary:[], spawnCreature:null,
                 defenses:{resist:[],vulnerable:[],immune:[]},
                 feed:"chat", messages:[], chat:[],
                 narrativeTimer:null, unread:{chat:0}, chatOpen:true,
                 audio:{ state:{sources:[],current_id:null,playing:false,updated_at:""},
                         local:{volume:0.7,muted:false}, element:null, iframe:null, lastSoundId:null },
                 sounds:[],
                 notes:[], encounters:[], creatures:[], encRows:[], encId:null, noteId:null,
                  cam:{ox:0, oy:0}, camT:{ox:0, oy:0}, camD:{ox:0, oy:0},
                  keys:new Set(), tickOn:false,
                  viewMode:"tactical" };
const VISION_R = 6;
const SIZE_FOOTPRINT = { Tiny:1, Small:1, Medium:1, Large:2, Huge:3, Gargantuan:4 };
/* D81: THE client footprint derivation — server fw/fh win, category is the
   square fallback. Never derive width/height anywhere else. */
function tokenSpan(t){
  const s = SIZE_FOOTPRINT[(t && t.size) || "Medium"] || 1;
  const w = (t && +t.fw > 0) ? Math.min(10, +t.fw) : s;
  const h = (t && +t.fh > 0) ? Math.min(10, +t.fh) : s;
  return [w, h];
}

/* Client mirrors of app/gear.py for previewing bonuses (server re-computes authoritatively). */
const SKILLS = {
  acrobatics:["Acrobatics","dex"], animal_handling:["Animal Handling","wis"],
  arcana:["Arcana","int"], athletics:["Athletics","str"], deception:["Deception","cha"],
  history:["History","int"], insight:["Insight","wis"], intimidation:["Intimidation","cha"],
  investigation:["Investigation","int"], medicine:["Medicine","wis"], nature:["Nature","int"],
  perception:["Perception","wis"], performance:["Performance","cha"], persuasion:["Persuasion","cha"],
  religion:["Religion","int"], sleight_of_hand:["Sleight of Hand","dex"], stealth:["Stealth","dex"],
  survival:["Survival","wis"],
};
const ITEM_ICONS = { armor:"🛡", shield:"🔰", potion:"🧪", scroll:"📜", wand:"🪄",
  staff:"🪵", ring:"💍", tool:"🧰", wondrous:"✨", spellbook:"📖", other:"🎒" };
const DMG_TYPES = ["bludgeoning","piercing","slashing","acid","cold","fire","force","lightning",
                   "necrotic","poison","psychic","radiant","thunder"];
/* Client mirror of app/conditions.py (labels + dot colors) for previews only. */
const CONDITIONS = {
  blinded:["Blinded","#8e44ad"], charmed:["Charmed","#e84393"], deafened:["Deafened","#7f8c8d"],
  frightened:["Frightened","#e67e22"], grappled:["Grappled","#16a085"], incapacitated:["Incapacitated","#c0392b"],
  invisible:["Invisible","#5dade2"], paralyzed:["Paralyzed","#2980b9"], petrified:["Petrified","#95a5a6"],
  poisoned:["Poisoned","#27ae60"], prone:["Prone","#d35400"], restrained:["Restrained","#34495e"],
  stunned:["Stunned","#f1c40f"], unconscious:["Unconscious","#7f8c8d"], concentrating:["Concentrating","#d4a017"],
};
const condLabel = k => (CONDITIONS[k] ? CONDITIONS[k][0] : String(k).slice(0, 24));
const condColor = k => (CONDITIONS[k] ? CONDITIONS[k][1] : "#7f8c8d");

/* ---------- world <-> storage coordinates (D72) ----------
   Everything on the wire (tokens, pins, doors, traps, preview cells) lives in
   WORLD coordinates. The per-cell arrays (cells/elev/explored) are STORAGE —
   a window at grid.origin. THESE are the only conversions the client uses;
   renderers and hit tests must not derive offsets of their own.
   Cells are WORLD cells unless a name says storage; array indexes are STORAGE. */
function gridOrigin(g){ const o = (g && g.origin) || [0, 0]; return [o[0] | 0, o[1] | 0]; }
function w2s(g, x, y){ const [ox, oy] = gridOrigin(g); return [x - ox, y - oy]; }   // world cell -> storage cell
function s2w(g, x, y){ const [ox, oy] = gridOrigin(g); return [x + ox, y + oy]; }   // storage cell -> world cell
function wIdx(g, x, y){                                                              // world cell -> flat storage idx
  if (!g) return -1;
  const [sx, sy] = w2s(g, x, y);
  return (sx >= 0 && sy >= 0 && sx < g.w && sy < g.h) ? sy * g.w + sx : -1;
}
function inWorld(g, x, y){
  if (!g) return false;
  const [sx, sy] = w2s(g, x, y);
  return sx >= 0 && sy >= 0 && sx < g.w && sy < g.h;
}

/* AoE targeting templates (client-side geometry preview only — no game resolution).
   Anchor and result cells are WORLD cells; clipping uses the world window. */
const DIRV = { N:[0,-1], NE:[1,-1], E:[1,0], SE:[1,1], S:[0,1], SW:[-1,1], W:[-1,0], NW:[-1,-1] };
function aoeCells(shape, cx, cy, size, g, dir){
  const cells = [], ok = (x, y) => inWorld(g, x, y);
  const push = (x, y) => { if (ok(x, y)) cells.push({x, y}); };
  const R = Math.max(0, Math.round(size));
  const d = (DIRV[dir] || DIRV.E);
  if (shape === "line"){
    push(cx, cy);
    for (let t = 1; t <= R; t++) push(cx + d[0]*t, cy + d[1]*t);
  } else if (shape === "cone"){
    const dl = Math.hypot(d[0], d[1]) || 1, cos45 = Math.SQRT1_2;
    for (let dy = -R; dy <= R; dy++) for (let dx = -R; dx <= R; dx++){
      const r = Math.hypot(dx, dy); if (r > R + 0.4) continue;
      if (r === 0 || (dx*d[0] + dy*d[1]) / (r*dl) >= cos45) push(cx + dx, cy + dy);
    }
  } else {
    for (let dy = -R; dy <= R; dy++) for (let dx = -R; dx <= R; dx++){
      if (shape === "circle" && Math.hypot(dx, dy) > R + 0.4) continue;
      push(cx + dx, cy + dy);
    }
  }
  return cells;
}
const _smod = v => Math.floor(((+v || 10) - 10) / 2);
const _pb = lvl => 2 + Math.floor(((+lvl || 1) - 1) / 4);

/* ---------- helpers ---------- */
async function api(path, method="GET", body) {
  const r = await fetch("/api"+path, { method,
    headers: body ? {"Content-Type":"application/json"} : {},
    body: body ? JSON.stringify(body) : undefined });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || ("HTTP "+r.status));
  return d;
}
function esc(s){ const d=document.createElement("div"); d.textContent = s==null?"":String(s); return d.innerHTML; }
function show(view){ for (const v of ["auth","lobby","room"]) $("view-"+v).classList.toggle("hidden", v!==view); }
function toast(msg){ const t=$("toast"); t.textContent=msg; t.classList.add("show");
  clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove("show"), 2500); }
function err(id, e){ $(id).textContent = e.message || String(e); }
const eid = () => "e" + Math.random().toString(36).slice(2, 9);
function loadAudioPrefs(){
  try {
    const raw = localStorage.getItem("dndtable-audio-volume");
    if (raw !== null){
      const v = parseFloat(raw);
      if (Number.isFinite(v)) state.audio.local.volume = Math.max(0, Math.min(1, v));
    }
    state.audio.local.muted = localStorage.getItem("dndtable-audio-muted") === "1";
  } catch { /* localStorage can be disabled */ }
}
function saveAudioPrefs(){
  try {
    localStorage.setItem("dndtable-audio-volume", String(state.audio.local.volume));
    localStorage.setItem("dndtable-audio-muted", state.audio.local.muted ? "1" : "0");
  } catch { /* best effort */ }
}
/* ---------- view mode (presentation only, CLIENT-LOCAL) ----------
   Never sent to the server, never broadcast, never affects rules.
   Each client picks its own renderer; the world state is shared. */
const VIEW_MODES = ["tactical", "diorama"];
function normalizeViewMode(v){ return VIEW_MODES.includes(v) ? v : "tactical"; }
function loadViewMode(){
  let v = "tactical";
  try { v = normalizeViewMode(localStorage.getItem("dndtable-view-mode")); }
  catch { /* localStorage can be disabled */ }
  state.viewMode = v;
}
function saveViewMode(){
  try { localStorage.setItem("dndtable-view-mode", state.viewMode); }
  catch { /* best effort */ }
}
function setViewMode(mode){
  const next = normalizeViewMode(mode);
  if (next === state.viewMode) return;
  // Each renderer frames its own camera; the shared state.cam must be saved
  // into the outgoing mode's slot and restored from the incoming one, or a
  // Diorama fit would fling the Tactical view into empty space (and vice
  // versa). Presentation-only: the world is untouched either way.
  const outSlot = state.viewMode === "diorama" ? state.camD : state.camT;
  const inSlot  = next === "diorama" ? state.camD : state.camT;
  outSlot.ox = state.cam.ox; outSlot.oy = state.cam.oy;
  state.viewMode = next;
  state.cam.ox = inSlot.ox; state.cam.oy = inSlot.oy;
  saveViewMode();
  renderViewToggle();
  if (next === "tactical" && typeof clampCam === "function") clampCam();
  if (next === "diorama" && typeof fitDiorama === "function") fitDiorama();
  draw();
}
function renderViewToggle(){
  for (const m of VIEW_MODES){
    const b = $("view-" + m);
    if (b) b.classList.toggle("primary", state.viewMode === m);
    if (b) b.classList.toggle("ghost", state.viewMode !== m);
  }
}
loadViewMode();
function _memberName(m){ return m.char ? m.char.name : m.username; }
function _chatSpeakerName(m){
  const kind = String(m.sender_kind || "user").toLowerCase();
  if ((kind === "npc" || kind === "persona") && m.persona) return m.persona;
  return m.display_name || m.username || "Someone";
}
function _isSelfChat(m){ return m.user_id === (state.me && state.me.id); }
loadAudioPrefs();
