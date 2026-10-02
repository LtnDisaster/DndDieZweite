/* Core: DOM helpers, shared state, API client. Must load first. */
const $ = (id) => document.getElementById(id);
const STATS = [["str","STR"],["dex","DEX"],["con","CON"],["int","INT"],["wis","WIS"],["cha","CHA"]];
const state = { me:null, room:null, ws:null, online:new Set(), tokens:[], ghosts:[], init:null,
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
                 cam:{ox:0, oy:0}, keys:new Set(), tickOn:false };
const VISION_R = 6;
const SIZE_FOOTPRINT = { Tiny:1, Small:1, Medium:1, Large:2, Huge:3, Gargantuan:4 };

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

/* AoE targeting templates (client-side geometry preview only — no game resolution). */
const DIRV = { N:[0,-1], NE:[1,-1], E:[1,0], SE:[1,1], S:[0,1], SW:[-1,1], W:[-1,0], NW:[-1,-1] };
function aoeCells(shape, cx, cy, size, w, h, dir){
  const cells = [], ok = (x, y) => x >= 0 && y >= 0 && x < w && y < h;
  const push = (x, y) => { if (ok(x, y)) cells.push(y * w + x); };
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
function _memberName(m){ return m.char ? m.char.name : m.username; }
function _chatSpeakerName(m){
  const kind = String(m.sender_kind || "user").toLowerCase();
  if ((kind === "npc" || kind === "persona") && m.persona) return m.persona;
  return m.display_name || m.username || "Someone";
}
function _isSelfChat(m){ return m.user_id === (state.me && state.me.id); }
loadAudioPrefs();
