/* Core: DOM helpers, shared state, API client. Must load first. */
const $ = (id) => document.getElementById(id);
const STATS = [["str","STR"],["dex","DEX"],["con","CON"],["int","INT"],["wis","WIS"],["cha","CHA"]];
const state = { me:null, room:null, ws:null, online:new Set(), tokens:[], ghosts:[], init:null,
                bg:null, sel:null, drag:null, pan:null, charEdit:null, weaponRows:[], itemRows:[],
                plan:null, reconnectTimer:null,
                grid:null, editMap:null, editing:false, brush:"wall",
                cam:{ox:0, oy:0}, keys:new Set(), tickOn:false };
const VISION_R = 6;

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
