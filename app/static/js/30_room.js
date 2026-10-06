/* ---------- room ---------- */
(typeof window !== "undefined") && ((window.__BUILDS = window.__BUILDS || {})["30_room.js"] = window.__BUILD__ || "?");
async function openRoom(code){
  const s = await api(`/rooms/${code}/state`);
  state.room = s; state.roomDeleted = false;   // fresh visit — re-arms auto-reconnect
  state.init = s.initiative; state.tokens = s.tokens; state.ghosts = s.ghosts || [];
  state.grid = s.grid; state.editing = false; state.editMap = null; state.sel = null;
  state.plan = null; state.planRequest = null; state.moving = new Set();
  state.pings = []; state.ruler = null; state.rulerArmed = false; state.pingArmed = false; state.aoe = null;
  state.online = new Set([state.me.username]);
  state.cam.ox = state.cam.oy = 0;
  state.camT = { ox: 0, oy: 0 }; state.camD = { ox: 0, oy: 0 };
  $("room-title").textContent = s.name;
  $("room-code").textContent = s.code;
  $("room-code").onclick = () => { navigator.clipboard?.writeText(s.code); toast("Code copied"); };
  $("room-role").textContent = s.role.toUpperCase();
  $("room-role").style.background = s.role === "dm" ? "var(--gold)" : "#2c3e50";
  for (const o of document.querySelectorAll(".dm-only")) o.style.display = s.role === "dm" ? "" : "none";
  $("dmtools").classList.toggle("hidden", s.role !== "dm");
  $("init-btns").classList.toggle("hidden", s.role !== "dm");
  state.messages = s.messages || []; state.chat = s.chat || [];
  const savedFeed = localStorage.getItem("vtt-feed");
  state.feed = ["chat", "log", "dice"].includes(savedFeed) ? savedFeed : "chat";
  state.unread.chat = 0;
  applyAudioState(s.audio || {});
  renderChatControls(); renderChatTargets(); renderVoiceTargets();
  if (s.role === "dm") loadSounds();
  renderFeed();
  applyFeedPanels();
  updateMoveControls();
  renderParty(); renderInit();   renderOnline();
  renderMyChars(); renderRolls(); applySideTab();
  if (s.map){ state.bg = new Image(); state.bg.src = s.map; } else state.bg = null;
  await loadNotes(s.role);
  if (s.role === "dm"){ await loadBestiary(); await loadEncounters(); }
  else { state.encounters = []; state.encRows = []; state.encId = null; }
  show("room"); resize();
  // D78: a camera framing failure must not abort the room join (WS would never
  // connect) — presentation errors are logged, never escalated as join errors.
  try { if (typeof initViewCam === "function") initViewCam(); }   // D75: open the view ON the action
  catch(e){ if (typeof dbgErr === "function") dbgErr(e, "initViewCam"); else console.error("[room] initViewCam", e); }
  startTick(); connectWS(s.code);
}
function sideTabKey(){ return "vtt-side-tab-" + ((state.me && state.me.username) || ""); }
function applySideTab(){
  const bar = $("side-tabs"); if (!bar || !state.room) return;
  let tab = localStorage.getItem(sideTabKey());
  if (!tab) tab = state.room.role === "dm" ? "dm" : "game";
  if (tab === "dm" && state.room.role !== "dm") tab = "game";
  // #sheet and other context panels carry no data-tab: their own logic decides.
  for (const p of document.querySelectorAll("aside.side .panel[data-tab]"))
    p.classList.toggle("hidden", p.dataset.tab !== tab);
  // an unassigned character is a blocking prompt, not a tab-scoped panel:
  const mc = $("mychars");
  if (mc && mc.classList.contains("nudge")) mc.classList.remove("hidden");
  for (const b of bar.querySelectorAll("button")){
    b.classList.toggle("active", b.dataset.tab === tab);
    b.setAttribute("aria-selected", b.dataset.tab === tab ? "true" : "false");
  }
}

async function refreshRoom(){
  const s = await api(`/rooms/${state.room.code}/state`);
  state.room = s; state.init = s.initiative; state.tokens = s.tokens; state.ghosts = s.ghosts || []; state.grid = s.grid;
  if (typeof renderFogToggle === "function") renderFogToggle();
  if (state.plan && !state.tokens.find(t => t.id === state.plan.token_id)) state.plan = null;
  updateMoveHud();
  renderParty(); renderInit(); renderMyChars();
  state.quests = s.quests || []; renderQuests();
  state.messages = s.messages || []; state.chat = s.chat || [];
  applyAudioState(s.audio || {}); renderChatTargets(); renderVoiceTargets(); renderAudio();
  renderFeed(); applySideTab(); applyFeedPanels();
}

/* ---------- bestiary (DM-owned monster templates) ---------- */
async function loadBestiary(){
  try { state.bestiary = await api("/creatures"); } catch(e){ state.bestiary = []; }
  renderBestiary(); renderEncounters();
}

async function loadEncounters(){
  try { state.encounters = await api("/encounters"); } catch(e){ state.encounters = []; }
  const sel = $("enc-list"); if (sel && state.encId && !state.encounters.some(e => e.id == state.encId)) state.encId = null;
  if (!state.encId && state.encounters.length) state.encId = state.encounters[0].id;
  if (state.encId){ const e = state.encounters.find(x => x.id == state.encId) || {};
    $("enc-name").value = e.name || ""; $("enc-notes").value = e.notes || ""; state.encRows = (e.entries||[]).map(x => ({...x})); }
  else { $("enc-name").value=""; $("enc-notes").value=""; state.encRows=[]; }
  renderEncounters();
}
function renderEncounters(){
  const sel = $("enc-list"); if (!sel) return;
  sel.innerHTML = "";
  if (state.bestiary){
    const cs = $("enc-creature-select"); if (cs){ cs.innerHTML = state.bestiary.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("") || "<option value=''>no creatures</option>"; }
  }
  for (const e of state.encounters){
    const o = document.createElement("option"); o.value=e.id; o.textContent=e.name;
    if (e.id == state.encId) o.selected = true; sel.appendChild(o);
  }
  if (!state.encounters.length){ sel.innerHTML = "<option value=''>no encounters</option>"; }
  const box = $("enc-rows"); if (!box) return;
  box.innerHTML = "";
  state.encRows.forEach((r, idx) => {
    const row = document.createElement("div"); row.className = "encounter-row";
    row.innerHTML = `<span>${esc(r.name)} ×${r.quantity} ${r.hidden?"<small>hidden</small>":""}</span>
      <button class="ghost" data-i="${idx}" data-a="dec">−</button><button class="ghost" data-i="${idx}" data-a="inc">+</button>
      <button class="ghost" data-i="${idx}" data-a="rm">✕</button>`;
    row.querySelectorAll("button").forEach(b => b.onclick = () => {
      const i=+b.dataset.i;
      if (b.dataset.a === "dec") state.encRows[i].quantity = Math.max(1, state.encRows[i].quantity-1);
      else if (b.dataset.a === "inc") state.encRows[i].quantity = Math.min(50, state.encRows[i].quantity+1);
      else state.encRows.splice(i,1);
      renderEncounters();
    });
    box.appendChild(row);
  });
}
function wireEncounters(){
  if (!$("btn-enc-add-row")) return;
  $("enc-list").onchange = () => { state.encId = $("enc-list").value ? +$("enc-list").value : null; loadEncounters(); };
  $("btn-enc-add-row").onclick = () => {
    const id = +$("enc-creature-select").value;
    if (!id) return;
    const cr = state.bestiary.find(c => c.id == id); if (!cr) return;
    state.encRows.push({ creature_id:id, name:cr.name, quantity:Math.max(1,+$("enc-qty").value||1), hidden:$("enc-hidden").checked });
    renderEncounters();
  };
  $("btn-enc-save").onclick = async () => {
    try {
      const name = $("enc-name").value.trim(); if (!name) return toast("Name required");
      const payload = { name, notes:$("enc-notes").value, entries:state.encRows.map(r => ({creature_id:r.creature_id, quantity:r.quantity, hidden:!!r.hidden})) };
      const r = state.encId ? await api(`/encounters/${state.encId}`, "PUT", payload) : await api("/encounters", "POST", payload);
      state.encId = r.id; await loadEncounters(); toast("Encounter saved");
    } catch(e){ toast(e.message); }
  };
  $("btn-enc-del").onclick = async () => {
    if (!state.encId || !confirm("Delete encounter?")) return;
    try { await api(`/encounters/${state.encId}`, "DELETE"); state.encId = null; await loadEncounters(); } catch(e){ toast(e.message); }
  };
  $("btn-enc-spawn").onclick = () => {
    if (!state.encId) return toast("No encounter selected");
    wsSend({ type:"spawn_encounter", encounter_id: state.encId }); toast("Encounter spawned");
  };
}

async function loadNotes(role){
  try { state.notes = await api(`/rooms/${state.room.code}/notes`); } catch(e){ state.notes = []; }
  const sel = $("note-list"); if (!sel) return;
  sel.innerHTML = "";
  if (!state.notes.length){ sel.innerHTML = "<option value=''>no journal entries</option>"; $("note-panel").classList.add("hidden"); return; }
  for (const n of state.notes){ const o=document.createElement("option"); o.value=n.id; o.textContent=`${n.title} (${n.visibility})`; if (n.id == state.noteId) o.selected=true; sel.appendChild(o); }
  if (!state.noteId || !state.notes.some(n => n.id == state.noteId)) state.noteId = state.notes[0].id;
  renderNote(role);
}
function renderNote(role){
  const n = state.notes.find(x => x.id == state.noteId) || {};
  $("note-panel").classList.remove("hidden");
  $("note-title").value = n.title || ""; $("note-body").value = n.body || "";
  $("note-cat").value = n.category || "notes"; $("note-vis").value = n.visibility || "dm";
  $("note-recips").value = (n.recipients || []).join(",");
  const editable = role === "dm";
  for (const b of document.querySelectorAll(".dm-only-note")) b.style.display = editable ? "" : "none";
  for (const id of ["note-title","note-cat","note-vis","note-recips","note-body"]) { const el=$(id); if (el) el.disabled = !editable; }
}
function wireNotes(){
  if (!$("note-list")) return;
  $("note-list").onchange = () => { state.noteId = $("note-list").value ? +$("note-list").value : null; renderNote(state.room.role); };
  $("btn-note-view").onclick = () => { state.noteId = $("note-list").value ? +$("note-list").value : null; renderNote(state.room.role); };
  $("btn-note-new").onclick = () => { state.noteId = null; $("note-title").value=""; $("note-body").value=""; $("note-cat").value="notes"; $("note-vis").value="party"; $("note-recips").value=""; $("note-title").focus(); };
  $("btn-note-save").onclick = async () => {
    try {
      const recips = $("note-recips").value.split(",").map(x=>+x.trim()).filter(x=>x);
      const p = { category:$("note-cat").value, title:$("note-title").value.trim(), body:$("note-body").value,
                  visibility:$("note-vis").value, recipients:recips };
      if (!p.title) return toast("Title required");
      if (state.noteId) await api(`/rooms/${state.room.code}/notes/${state.noteId}`, "PUT", p);
      else { const r = await api(`/rooms/${state.room.code}/notes`, "POST", p); state.noteId = r.id; }
      await loadNotes(state.room.role); toast("Note saved");
    } catch(e){ toast(e.message); }
  };
  $("btn-note-del").onclick = async () => {
    if (!state.noteId || !confirm("Delete note?")) return;
    try { await api(`/rooms/${state.room.code}/notes/${state.noteId}`, "DELETE"); state.noteId = null; await loadNotes(state.room.role); } catch(e){ toast(e.message); }
  };
}

function renderBestiary(){
  const box = $("best-list"); if (!box) return;
  box.innerHTML = "";
  if (!state.bestiary || !state.bestiary.length){
    box.innerHTML = "<div class='meta' style='opacity:.6'>No saved creatures yet.</div>"; return; }
  for (const c of state.bestiary){
    const b = c.block || {}, row = document.createElement("div");
    row.className = "creature-row";
    row.innerHTML = `<span class="cr-name"><b>${esc(c.name)}</b> ` +
      `<small>L${b.level||1} · HP ${b.max_hp||0}${esc(c.tags ? " · " + c.tags : "")}</small></span>` +
      `<button data-a="spawn" class="primary">Spawn</button><button data-a="del" title="Delete">✕</button>`;
    row.querySelector('[data-a=spawn]').onclick = () => { state.spawnCreature = c; toast(`Click the map to place ${c.name}`); };
    row.querySelector('[data-a=del]').onclick = async () => {
      if (!confirm("Delete this creature?")) return;
      try { await api(`/creatures/${c.id}`, "DELETE"); await loadBestiary(); } catch(e){ toast(e.message); } };
    box.appendChild(row);
  }
}
async function saveNpcToBestiary(n, name, tok){
  try {
    await api("/creatures", "POST", { name: name || "Creature", level: n.level, stats: n.stats,
      hp: n.hp, max_hp: n.max_hp, ac: n.ac, speed: n.speed, attacks: n.attacks || [],
      spells: n.spells || [], spell_slots: n.spell_slots || {},
      saves: n.saves || {}, defenses: n.defenses || {},
      abilities: n.abilities || [], resources: n.resources || [], notes: n.notes || "",
      size: tok?.size || n.size || "Medium", disposition: tok?.disposition || n.disposition || "" });
    toast("Saved to Bestiary"); await loadBestiary();
  } catch(e){ toast(e.message); }
}
function renderMyChars(){
  const el = $("my-chars"); if (!el || !state.room) return;
  $("mychars").classList.remove("hidden");
  const tok = state.tokens.find(t => t.owner_user_id === state.me.id);
  $("mychars").classList.toggle("nudge", !tok);
  const chars = state.room.characters || [];
  el.innerHTML = "";
  if (!chars.length){ el.innerHTML = "<div class='meta' style='opacity:.6'>No characters — create one in the lobby.</div>"; return; }
  for (const c of chars){
    const active = tok && tok.character_id === c.id;
    const d = document.createElement("div"); d.className = "char-card compact";
    d.innerHTML = `<div class="head"><b>${esc(c.name)}</b>
      ${active ? "<span class='badge'>at table</span>" : `<button data-a="bring">Bring</button>`}</div>
      <div class="meta">${esc(c.race)} ${esc(c.char_class)} · HP ${c.hp}/${c.max_hp} · AC ${c.ac}</div>`;
    const b = d.querySelector('[data-a="bring"]');
    if (b) b.onclick = async () => {
      b.disabled = true;
      // D78: the authoritative result and the presentation result are reported
      // apart — a placed token must never look like a failed Bring because
      // camera/render setup threw afterwards (that mislabel burned a whole sprint).
      try { await api(`/rooms/${state.room.code}/assign`, "POST", { character_id: c.id }); }
      catch(e){ state._bringLast = "server FAIL: " + e.message; toast(e.message); b.disabled = false; return; }
      state._bringLast = "ok @ " + new Date().toISOString().slice(11, 19);
      toast(`${c.name} takes a seat at the table`);
      try {
        await refreshRoom();
        if (typeof initViewCam === "function") initViewCam();   // land on my token (D75)
      } catch(e){
        state._bringLast += " | render FAIL: " + e.message;
        console.error("[bring] presentation error", e);
        toast("Character is seated — but the view could not initialize: " + e.message);
      }
    };
    el.appendChild(d);
  }
}
function myChar(){
  if (!state.room) return null;
  const m = state.room.members.find(x => x.user_id === state.me.id && x.char);
  return m ? m.char : null;
}
function renderRolls(){
  const panel = $("sheet-roll"); if (!panel || !state.room) return;
  const ch = myChar();
  panel.classList.toggle("hidden", !ch);
  if (!ch) return;
  $("sr-name").textContent = `${ch.name}'s Rolls · Lv ${ch.level}`;
  const mods = {};
  for (const [k,l] of [["str","STR"],["dex","DEX"],["con","CON"],["int","INT"],["wis","WIS"],["cha","CHA"]]){
    const v = (ch.stats && typeof ch.stats[k] === "number") ? ch.stats[k] : 10;
    mods[k] = Math.floor((v-10)/2);
  }
  const pb = 2 + Math.floor((ch.level-1)/4);
  const cSaves = ch.saves || {};
  const ab = $("sr-abil"); ab.innerHTML = "";
  for (const [k,l] of [["str","STR"],["dex","DEX"],["con","CON"],["int","INT"],["wis","WIS"],["cha","CHA"]]){
    const wrap = document.createElement("span"); wrap.className = "abil";
    const m = mods[k], sb = m + (cSaves[k] ? pb : 0);
    wrap.innerHTML = `<button data-k="${k}" title="Ability check">${l} ${m>=0?"+":""}${m}</button>` +
                     `<button class="sv" data-k="${k}" title="${l} saving throw">${sb>=0?"+":""}${sb}${cSaves[k]?" #":""}</button>`;
    ab.appendChild(wrap);
  }
  const sheetVis = () => ($("sr-vis") && $("sr-vis").value) || "public";
  for (const b of ab.querySelectorAll("button")) b.onclick = () => {
    const kind = b.classList.contains("sv") ? "save" : "check";
    wsSend({ type:"roll", kind, ability: b.dataset.k,
             prof: kind === "check" && $("sr-prof").checked, adv: $("sr-adv").value || null, visibility: sheetVis() });
  };
  const wl = $("sr-weapons"); wl.innerHTML = "";
  for (const w of (ch.weapons||[])){
    const mod = mods[w.ability] || 0;
    const pb = 2 + Math.floor((ch.level-1)/4);
    const tohit = mod + (w.proficient ? pb : 0);
    const row = document.createElement("div"); row.className = "wrow";
    row.innerHTML = `<span class="wn">${esc(w.name)} <small>+${tohit}</small></span>
      <button data-a="atk">⚔️</button><button data-a="dmg">${esc(w.dmg)}</button>
      <button data-a="crit" title="Crit damage">×2</button>`;
    const [atk, dmg, crit] = row.querySelectorAll("button");
    atk.onclick = () => wsSend({ type:"roll", kind:"attack", weapon:w.name, adv: $("sr-adv").value || null,
                                 visibility: sheetVis(),
                                 cover: ($("sr-cover") && $("sr-cover").value) || "",
                                 ability: ($("sr-atk-abil") && $("sr-atk-abil").value) || null });
    dmg.onclick = () => wsSend({ type:"roll", kind:"damage", weapon:w.name, crit:false, visibility: sheetVis() });
    crit.onclick = () => wsSend({ type:"roll", kind:"damage", weapon:w.name, crit:true, visibility: sheetVis() });
    wl.appendChild(row);
  }
}
function _time(m){ const t = m.created_at ? new Date(m.created_at + "Z") : new Date();
  return isNaN(t) ? "" : t.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"}); }
function _visBadge(m){ return ["self","dm","blind"].includes(m.visibility) ? ` <small class="visbadge">${esc(m.visibility)}</small>` : ""; }
function _recipientNames(ids){
  if (!ids || !ids.length) return [];
  return ids.map(id => {
    const m = (state.room && state.room.members || []).find(x => x.user_id === id);
    return m ? _memberName(m) : `#${id}`;
  });
}
function _chatClasses(m){
  const k = [];
  if (m.type === "narrative") k.push("narrative");
  else k.push("chat");
  if (m.visibility === "whisper") k.push("whisper");
  if (m.visibility === "dm") k.push("dm-note");
  const kind = String(m.sender_kind || "user").toLowerCase();
  if (kind === "persona") k.push("persona");
  if (kind === "npc") k.push("npc");
  if (m.style === "voice") k.push("voice");
  if (_isSelfChat(m)) k.push("me");
  return k.join(" ");
}
function chatEntry(m){
  const p = document.createElement("p");
  p.className = _chatClasses(m);
  const who = document.createElement("b");
  who.textContent = _chatSpeakerName(m);
  p.appendChild(who);
  if (m.visibility === "whisper"){
    const to = _recipientNames((m.recipient_ids || []).filter(id => id !== m.user_id)).filter(Boolean);
    if (to.length){
      const span = document.createElement("span");
      span.className = "to";
      span.textContent = ` → ${to.join(", ")}`;
      p.appendChild(span);
    }
  }
  if (m.style === "voice" || m.meta?.voice){
    const badge = document.createElement("small");
    badge.className = "visbadge";
    badge.textContent = "voice";
    p.appendChild(badge);
  }
  const text = document.createElement("span");
  text.className = "text";
  text.textContent = m.text ?? m.body ?? "";
  p.appendChild(text);
  return p;
}
function feedEntry(m, kind){
  if (kind === "chat") return chatEntry(m);
  const p = document.createElement("p");
  const cls = m.type === "system" ? "sys" : m.type === "dice" ? "dice"
    : m.type === "whisper" ? "whisper"
    : (m.username === state.me?.username ? "me" : "");
  p.className = cls;
  const time = kind === "log" ? `<small class="ts">${esc(_time(m))}</small> ` : "";
  const who = m.username && m.type !== "system" && m.type !== "whisper" ? `<b>${esc(m.username)}</b> ` : "";
  p.innerHTML = time + who + esc(m.body ?? m.text ?? "") + _visBadge(m);
  return p;
}
function stickToBottom(el){ return el.scrollHeight - el.scrollTop - el.clientHeight < 40; }
function appendTo(el, p, stick){ el.appendChild(p); if (stick) el.scrollTop = el.scrollHeight; }
function renderChatAll(msgs){ renderFeed(msgs); }
function _isChatVisible(){
  return state.feed === "chat" && !$("chronicle").classList.contains("collapsed");
}
function renderFeed(msgs){
  if (msgs && Array.isArray(msgs)) state.messages = msgs;
  const c = $("chat"), l = $("log");
  if (c){
    c.innerHTML = "";
    for (const m of state.chat || []) appendTo(c, chatEntry(m), false);
    c.scrollTop = c.scrollHeight;
  }
  if (l){
    l.innerHTML = "";
    for (const m of state.messages || []) appendTo(l, feedEntry(m, "log"), false);
    l.scrollTop = l.scrollHeight;
  }
  const dout = $("dice-out");
  if (dout){
    dout.innerHTML = "";
    for (const m of (state.messages || []).filter(x => x && x.type === "dice").slice(-50))
      appendTo(dout, feedEntry(m, "log"), false);
    dout.scrollTop = dout.scrollHeight;
  }
  renderTabs();
}
function _dedupeAppend(arr, item, cap){
  if (item == null) return;
  if (item.id != null && arr.some(x => x.id === item.id)) return;
  arr.push(item);
  while (arr.length > (cap || 300)) arr.shift();
}
function appendChatMessage(m){
  m = m || {};
  _dedupeAppend(state.chat, m, 300);
  const visible = _isChatVisible();
  if (visible){
    const c = $("chat");
    if (c) appendTo(c, chatEntry(m), stickToBottom(c));
  } else {
    state.unread.chat = (state.unread.chat || 0) + 1;
  }
  renderTabs();
}
function appendGameLogMessage(m){
  m = m || {};
  _dedupeAppend(state.messages, m, 500);
  const open = !$("chronicle").classList.contains("collapsed");
  if (state.feed === "log" && open){
    const l = $("log");
    if (l) appendTo(l, feedEntry(m, "log"), stickToBottom(l));
  }
  if (m.type === "dice" && state.feed === "dice" && open){
    const d = $("dice-out");
    if (d) appendTo(d, feedEntry(m, "log"), stickToBottom(d));
  }
  renderTabs();
}
function appendChat(m){
  if (m && ["dice", "system", "whisper"].includes(m.type)) appendGameLogMessage(m);
  else appendChatMessage(m);
}
function renderTabs(){
  const chat = $("tab-chat"), log = $("tab-log");
  const unread = state.unread.chat || 0;
  const showUnread = unread && (!state.room || !_isChatVisible());
  if (chat) chat.textContent = `Chat${showUnread ? ` (${Math.min(99, unread)}${unread > 99 ? "+" : ""})` : ""}`;
  if (log) log.textContent = `Game Log (${(state.messages || []).length})`;
  if (chat) chat.className = state.feed === "chat" ? "primary" : "ghost";
  if (log) log.className = state.feed === "log" ? "primary" : "ghost";
  const dice = $("tab-dice");
  if (dice) dice.className = state.feed === "dice" ? "primary" : "ghost";
}
function switchFeed(which){
  state.feed = which === "log" ? "log" : which === "dice" ? "dice" : "chat";
  localStorage.setItem("vtt-feed", state.feed);
  if (state.feed === "chat"){
    state.unread.chat = 0;
    if (!$("chronicle").classList.contains("collapsed")) renderFeed();
    const c = $("chat"); if (c) c.scrollTop = c.scrollHeight;
  } else {
    renderFeed();
  }
  applyFeedPanels();
  renderTabs();
}
// exactly one feed surface (chat | log | dice) is visible; the composer rows
// belong to chat alone — dice never shares the panel area with them.
function applyFeedPanels(){
  $("chat").classList.toggle("hidden", state.feed !== "chat");
  $("log").classList.toggle("hidden", state.feed !== "log");
  const d = $("dice-panel");
  if (d) d.classList.toggle("hidden", state.feed !== "dice");
  const send = document.querySelector(".chat-send-row");
  if (send) send.classList.toggle("hidden", state.feed !== "chat");
  renderChatControls();
}
function setChronicleOpen(open){
  state.chatOpen = !!open;
  $("chronicle").classList.toggle("collapsed", !open);
  $("toggle-chronicle").textContent = open ? "▾" : "▸";
  if (open){
    state.unread.chat = 0;
    renderFeed();
    applyFeedPanels();
    const target = $(state.feed === "dice" ? "dice-out" : "chat");
    if (target) target.scrollTop = target.scrollHeight;
  }
  renderTabs();
}
function renderChatControls(){
  const row = $("chat-persona-row");
  if (row) row.classList.toggle("hidden", state.feed !== "chat" || !state.room || state.room.role !== "dm");
  const ch = $("chat-channel"); if (ch) syncChatTarget();
}
function renderChatTargets(){
  const targets = $("chat-target"), narr = $("narr-target");
  const members = ((state.room && state.room.members) || []).filter(m => m.user_id !== (state.me && state.me.id));
  if (targets){
    const old = targets.value;
    targets.innerHTML = "<option value=''>recipient…</option>" +
      members.map(m => `<option value="${m.user_id}">${esc(_memberName(m))} (${esc(m.username)})</option>`).join("");
    targets.value = members.some(m => String(m.user_id) === old) ? old : "";
  }
  if (narr){
    const old = narr.value;
    narr.innerHTML = `<option value="all">Everyone</option>` +
      members.map(m => `<option value="${m.user_id}">${esc(_memberName(m))}</option>`).join("");
    narr.value = old && (old === "all" || members.some(m => String(m.user_id) === old)) ? old : "all";
  }
  syncChatTarget();
}
function syncChatTarget(){
  const ch = $("chat-channel"), tg = $("chat-target");
  if (!ch || !tg) return;
  const role = state.room && state.room.role;
  const need = ch.value === "whisper" || (ch.value === "dm" && role === "dm");
  tg.classList.toggle("hidden", !need);
  if (!need) tg.value = "";
}
function renderVoiceTargets(){
  const tokens = (state.tokens || []).filter(t => !t.owner_user_id && !t.character_id && t.npc);
  const opts = tokens.map(t => `<option value="${t.id}">${esc(t.label || "NPC")}</option>`).join("") ||
    "<option value=''>no NPC tokens</option>";
  for (const id of ["chat-npc", "narr-npc"]){
    const el = $(id); if (!el) continue;
    const old = el.value;
    el.innerHTML = opts;
    el.value = tokens.some(t => String(t.id) === old) ? old : (tokens[0] ? String(tokens[0].id) : "");
  }
}
async function loadSounds(){
  if (!state.room || state.room.role !== "dm") return;
  try { state.sounds = await api("/sounds"); } catch { state.sounds = []; }
  renderSoundSelectors(); renderSoundboard(); renderAmbience();
}
function renderSoundSelectors(){
  for (const id of ["secret-sound", "sound-select"]){
    const el = $(id); if (!el) continue;
    const old = el.value;
    el.innerHTML = (id === "secret-sound" ? "<option value=''>No sound</option>" : "<option value=''>Sound…</option>") +
      (state.sounds || []).map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
    el.value = (state.sounds || []).some(s => String(s.id) === old) ? old : "";
  }
}
function renderAmbience(){
  const list = $("ambience-list"); if (!list) return;
  list.innerHTML = "";
  for (const s of state.audio.state.sources || []){
    const row = document.createElement("div"); row.className = "ambience-row";
    const title = document.createElement("span"); title.className = "am-title";
    title.textContent = `${s.title || "source"} · ${s.kind || "direct"}`;
    const play = document.createElement("button"); play.textContent = "▶";
    play.title = s.kind === "direct" ? "Play / resume" : "Play (embeds always start at 0)";
    play.onclick = () => wsSend({ type:"audio_play", source_id:s.id });
    const del = document.createElement("button"); del.textContent = "✕"; del.className = "del";
    del.onclick = () => wsSend({ type:"audio_remove", source_id:s.id });
    row.append(title, play);
    if (state.audio.state.current_id === s.id && state.audio.state.playing){
      const pause = document.createElement("button"); pause.textContent = "⏸"; pause.title = "Pause";
      pause.onclick = () => wsSend({ type:"audio_pause" });
      row.append(pause);
      title.style.color = "var(--gold)";
    }
    row.append(del);
    list.appendChild(row);
  }
}
function renderAudio(){
  const bar = $("audio-bar");
  if (!bar) return;
  const st = state.audio.state || {};
  const src = (st.sources || []).find(x => x.id === st.current_id) || null;
  bar.classList.toggle("hidden", !(src || (st.sources || []).length));
  const title = $("audio-title");
  if (title) title.textContent = src ? `${src.title || "Ambience"} · ${src.kind || "direct"}` : "No current ambience";
  const status = $("audio-status");
  if (status) status.textContent = state.audio.local.muted ? "muted"
    : (st.playing ? (src?.kind === "direct" ? "playing" : "open embed") : (src ? "paused" : "stopped"));
  const mute = $("btn-audio-mute");
  if (mute) mute.textContent = state.audio.local.muted ? "🔇" : "🔊";
  const vol = $("audio-vol");
  if (vol && document.activeElement !== vol) vol.value = state.audio.local.volume;
  renderAmbience();
}
function stopAudioPlayback(){
  if (state.audio.element){ try { state.audio.element.pause(); } catch {} state.audio.element = null; }
  const box = $("audio-embed");
  if (box){ box.innerHTML = ""; box.classList.add("hidden"); }
  state.audio.iframe = null;
}
function setAudioPlayback(){
  const st = state.audio.state || {};
  const src = (st.sources || []).find(x => x.id === st.current_id) || null;
  renderAudio();
  const want = !!(src && st.playing && !state.audio.local.muted);
  let directSame = false;
  try {
    directSame = !!(src && src.kind === "direct" && state.audio.element &&
      state.audio.element.src === new URL(src.url, location.origin).href);
  } catch { directSame = false; }
  if (!want){
    // Paused (or locally muted) direct source: keep the element, pause in
    // place — ▶ resumes where it stopped. Embeds cannot pause, they stop.
    if (directSame) state.audio.element.pause();
    else stopAudioPlayback();
    return;
  }
  if (directSame){
    state.audio.element.volume = state.audio.local.volume;
    state.audio.element.play().catch(() => toast("Click ▶ to allow audio playback"));
    return;
  }
  stopAudioPlayback();
  if (src.kind === "direct"){
    try {
      const a = new Audio(src.url);
      a.loop = true;
      a.volume = state.audio.local.volume;
      a.onerror = () => toast("Audio could not play");
      state.audio.element = a;
      a.play().catch(() => toast("Click ▶ to allow audio playback"));
    } catch { toast("Audio playback failed"); }
    return;
  }
  if (src.embed){
    const box = $("audio-embed");
    if (!box) return;
    box.innerHTML = "";
    const iframe = document.createElement("iframe");
    const sep = src.embed.includes("?") ? "&" : "?";
    iframe.src = `${src.embed}${sep}autoplay=1`;
    iframe.allow = "encrypted-media; clipboard-write; fullscreen; picture-in-picture";
    iframe.loading = "lazy";
    box.appendChild(iframe);
    box.classList.remove("hidden");
    state.audio.iframe = iframe;
  }
}
function applyAudioState(payload){
  const safe = {
    sources: [],
    current_id: String(payload?.current_id || "") || null,
    playing: !!payload?.playing,
    updated_at: String(payload?.updated_at || ""),
  };
  for (const s of (payload?.sources || []).slice(0, 20)){
    const id = String(s?.id || "");
    if (!id || !["direct", "youtube", "spotify"].includes(String(s?.kind || ""))) continue;
    const url = String(s.url || "");
    const embed = String(s.embed || "");
    if (!url) continue;
    const title = String(s.title || "Ambience").slice(0, 80);
    const category = String(s.category || "ambience").slice(0, 16);
    const kind = String(s.kind);
    const cleanEmbed = kind === "direct" ? "" :
      (kind === "youtube" && embed.startsWith("https://www.youtube-nocookie.com/embed/") ? embed :
       kind === "spotify" && embed.startsWith("https://open.spotify.com/embed/") ? embed : "");
    if (kind !== "direct" && !cleanEmbed) continue;
    safe.sources.push({ id, title, url: url.slice(0, 2048), embed: cleanEmbed, kind, category });
  }
  if (!safe.sources.some(s => s.id === safe.current_id)){ safe.current_id = null; safe.playing = false; }
  const old = JSON.stringify(state.audio.state);
  const next = JSON.stringify(safe);
  state.audio.state = safe;
  if (old !== next) setAudioPlayback();
}
function playSoundEvent(p){
  if (!p || p.kind !== "direct" || state.audio.local.muted) return;
  if (p.event_id && state.audio.lastSoundId === p.event_id) return;
  state.audio.lastSoundId = p.event_id || null;
  try {
    const a = new Audio(p.url);
    a.volume = state.audio.local.volume;
    a.onended = () => { try { a.src = ""; } catch {} };
    a.play().catch(() => toast("Click audio ▶ to allow sound playback"));
  } catch { /* no-op */ }
}
function showNarrativeOverlay(p){
  if (!p || !p.text) return;
  const el = $("narrative-overlay");
  if (!el) return;
  const box = el.querySelector(".narrative-box");
  const persona = box.querySelector(".narrative-persona");
  const text = box.querySelector(".narrative-text");
  persona.textContent = p.persona || p.display_name || p.username || "";
  persona.classList.toggle("hidden", !persona.textContent);
  text.textContent = p.text;
  el.dataset.style = p.style || "overlay";
  el.classList.add("show");
  clearTimeout(state.narrativeTimer);
  state.narrativeTimer = setTimeout(() => el.classList.remove("show"), 6500);
}
function renderSoundboard(){
  const list = $("sound-list"); if (!list) return;
  list.innerHTML = "";
  for (const s of state.sounds || []){
    const row = document.createElement("div"); row.className = "ambience-row";
    const name = document.createElement("span"); name.className = "am-title"; name.textContent = s.name;
    const play = document.createElement("button"); play.textContent = "▶";
    play.onclick = () => wsSend({ type:"sound_trigger", sound_id:s.id,
                                  target: ($("narr-target") && $("narr-target").value) || "all" });
    const del = document.createElement("button"); del.textContent = "✕"; del.className = "del";
    del.onclick = async () => {
      if (!confirm("Delete this sound?")) return;
      try { await api(`/sounds/${s.id}`, "DELETE"); await loadSounds(); }
      catch(e){ toast(e.message); }
    };
    row.append(name, play, del);
    list.appendChild(row);
  }
  renderSoundSelectors();
}
function renderParty(){
  const el = $("party"); el.innerHTML = "";
  for (const m of state.room.members){
    const d = document.createElement("div"); d.className = "prow";
    const tok = state.tokens.find(t => t.owner_user_id === m.user_id);
    const ch = m.char;
    d.innerHTML = `<span class="dot" style="background:${tok ? tok.color : "#555"}"></span>
      <span>${esc(m.char ? m.char.name : m.username)} <small style="opacity:.6">(${esc(m.username)}${m.role==="dm"?" · DM":""})</small></span>`;
    if (state.room.role === "dm" && m.role !== "dm"){
      const k = document.createElement("button"); k.className="kick"; k.textContent="✕"; k.title="Kick";
      k.onclick = async () => { if (!confirm("Kick "+m.username+"?")) return;
        try { await api(`/rooms/${state.room.code}/members/${m.user_id}`, "DELETE"); await refreshRoom(); } catch(e){ toast(e.message); } };
      d.appendChild(k);
    }
    if (ch){
      const bar = document.createElement("div"); bar.className = "hpbar"; bar.style.flexBasis="100%";
      const f = document.createElement("div"); f.style.width = Math.max(0, ch.hp/ch.max_hp*100)+"%";
      if (ch.hp/ch.max_hp <= .25) f.style.background = "var(--red)";
      bar.appendChild(f); d.appendChild(bar);
    }
    el.appendChild(d);
  }
}
const SLOT_ABBR = { action: "A", bonus: "B", reaction: "R" };
function renderInit(){
  const ol = $("init-list"); ol.innerHTML = "";
  const bar = $("turn-bar");
  if (bar){ bar.innerHTML = ""; bar.classList.add("hidden"); }
  const i = state.init;
  if (!i || !i.combat){ ol.innerHTML = "<li style='opacity:.5'>No combat</li>"; return; }
  // Compact turn bar (D79): who acts, movement left, A/B/R slots, Dash/End Turn.
  // Pure rendering of the server's initiative object — no client-side economy.
  const t = i.turn;
  if (bar && t){
    const mine = ownToken(), isDM = state.room && state.room.role === "dm";
    const myTurn = t.token_id === (mine && mine.id);
    const who = ((i.order || [])[i.active] || {}).label || "?";
    const rem = Math.max(0, (t.move_total || 0) - (t.move_spent || 0));
    let h = `<div class="tb-who">▶ ${esc(who)}</div>` +
            `<span class="tb-move" title="movement units left this turn">${rem}/${t.move_total || 0}</span>`;
    for (const slot of ["action", "bonus", "reaction"]){
      const used = t[slot] === "used";
      const click = myTurn || isDM;
      h += `<button class="slot-chip${used ? " spent" : ""}" data-slot="${slot}"${click ? "" : " disabled"}
             title="${slot}${click ? " — click to toggle" : " (table bookkeeping)"}">${SLOT_ABBR[slot]} ${used ? "·" : "✓"}</button>`;
    }
    if (myTurn || isDM)
      h += `<button class="ghost" data-a="dash"${t.action === "used" ? " disabled" : ""} title="Dash: spend the action for extra movement">💨 Dash</button>` +
           `<button class="primary" data-a="endturn">End Turn</button>`;
    bar.innerHTML = h;
    bar.classList.remove("hidden");
    bar.querySelector('[data-a="dash"]').onclick = () => wsSend({ type: "dash", token_id: t.token_id });
    bar.querySelector('[data-a="endturn"]').onclick = () => wsSend({ type: "end_turn" });
    for (const b of bar.querySelectorAll(".slot-chip"))
      b.onclick = () => wsSend({ type: "turn_mark", token_id: t.token_id, slot: b.dataset.slot,
                                 value: (t[b.dataset.slot] === "used") ? "available" : "used" });
  }
  const rd = document.createElement("li"); rd.className = "roundline";
  rd.textContent = `— Round ${i.round || 1} —`; ol.appendChild(rd);
  i.order.forEach((o, idx) => {
    const li = document.createElement("li");
    li.textContent = `${o.label} — ${o.total} (${o.roll}${o.mod>=0?"+":""}${o.mod})`;
    if (idx === i.active) li.classList.add("active");
    ol.appendChild(li);
  });
}
function renderSheet(tok){
  state.sel = tok ? tok.id : null;
  updateMoveControls();
  state.npcEdit = null;
  if (tok && typeof tok.npc === "string"){ try { tok.npc = JSON.parse(tok.npc); } catch { tok.npc = null; } }
  const panel = $("sheet");
  if (!tok){ panel.classList.add("hidden"); return; }
  panel.classList.remove("hidden");
  const m = state.room.members.find(x => x.user_id === tok.owner_user_id);
  const ch = m && m.char;
  const clsTxt = ch && ch.class_levels && ch.class_levels.length
    ? ch.class_levels.map(e => e.class_id[0].toUpperCase() + e.class_id.slice(1) + " " + e.level).join(" / ")
    : ((ch && ch.char_class) || "");
  $("sheet-name").textContent = tok.label + (ch ? ` (${[ch.race, clsTxt, "Lv" + (ch.total_level || ch.level || 1)].filter(Boolean).join(" ")})` : " [NPC]");
  const body = $("sheet-body");
  if (!ch){
    if (tok.npc && state.room.role === "dm"){ renderNpcSheet(tok); return; }
    body.innerHTML = `<div class="meta">No character attached.</div>` +
      (state.room.role === "dm"
        ? `<div class="row"><button id="btn-del-npc" style="color:var(--red)">Remove token</button></div>` : "");
    $("hp-btns").classList.add("hidden"); $("hp-adv").classList.add("hidden");
    const del = $("btn-del-npc"); if (del) del.onclick = () => wsSend({ type:"del_token", token_id: tok.id });
    return;
  }
  const mod = v => { const m2 = Math.floor(((v||10)-10)/2); return (m2>=0?"+":"")+m2; };
  const isDM = state.room.role === "dm", own = tok.owner_user_id === state.me.id;
  const ac = ch.ac_total != null ? ch.ac_total : ch.ac;
  const inv = (ch.items || []);
  const invRows = inv.map(it => {
    const chips = [it.magic ? "✨" : "", it.unidentified ? "❓" : "",
                   it.attuned ? "🔗" : "", (it.charges >= 0 && !it.unidentified) ? `⚡${it.charges}/${it.chargesMax != null ? it.chargesMax : it.charges}` : ""].filter(Boolean).join(" ");
    const btns = [];
    const known = !it.magic || it.identified;
    if (isDM || own) { if (it.heal && known && it.charges !== 0) btns.push(`<button data-a="use" data-id="${it.id}">Use</button>`);
      if (it.attunable) btns.push(`<button data-a="attune" data-id="${it.id}">${it.attuned ? "Untune" : "Attune"}</button>`); }
    if (isDM && it.magic && !it.identified) btns.push(`<button data-a="identify" data-id="${it.id}">Identify</button>`);
    if (isDM && it.recharge) btns.push(`<button data-a="recharge" data-id="${it.id}">Recharge</button>`);
    return `<div class="inv-row"><span class="inv-name">${ITEM_ICONS[it.kind]||"🎒"} ${esc(it.name)}</span> <small>${chips}</small>
      <small style="opacity:.6">${it.kind==="armor" ? ("AC "+(it.ac||(it.acBonus?("+"+it.acBonus):""))) : (it.heal?("+HP "+it.heal):"")}</small>
      ${it.unidentified ? "" : `<small style="opacity:.55"> ${esc(it.desc||"")}</small>`}<span class="inv-btns">${btns.join("")}</span></div>`;
  }).join("");
  const lvlv = ch.level || 1;
  const skills = ch.skills || {};
  const spells = ch.spells || [];
  const slots = ch.spell_slots || {};
  const _ab = a => (ch.stats && ch.stats[a] != null) ? ch.stats[a] : 10;
  const profSkills = Object.keys(skills).filter(k => skills[k] > 0);
  const skillBlock = profSkills.length ? `<details class="sheet-sec" open><summary><h3>Skills</h3></summary>` +
    profSkills.map(k => {
      const meta = SKILLS[k] || [k, ""], bonus = _smod(_ab(meta[1])) + _pb(lvlv) * skills[k];
      return `<div class="skrow"><span>${meta[0]} <small>${skills[k]===2?"★":"✓"}</small> <b>${bonus>=0?"+":""}${bonus}</b></span>` +
             (own ? `<button class="sk-roll" data-skill="${k}">Roll</button>` : "") + `</div>`;
    }).join("") + `</details>` : "";
  let bookBlock = "";
  if (ch.has_spellbook){
    const slotLine = [];
    for (let l=1;l<=9;l++){ const d = slots[String(l)] || slots[l]; if (d && d.max>0) slotLine.push(`<small>L${l} ${Math.max(0,d.max-d.used)}/${d.max}</small>`); }
    const spRows = spells.map(sp => {
      const atk = _pb(lvlv) + _smod(_ab(sp.ability));
      const dc = 8 + _pb(lvlv) + _smod(_ab(sp.ability));
      let btns = "";
      if (own){
        if (sp.cast === "attack") btns += `<button class="roll-sp" data-k="spell_attack" data-id="${sp.id}">Atk +${atk}</button>`;
        if (sp.cast === "save") btns += `<button class="roll-sp" data-k="spell_dc" data-id="${sp.id}">DC ${dc}</button>`;
        if (sp.dmg){ btns += `<button class="roll-sp" data-k="spell_damage" data-id="${sp.id}">Dmg</button>` +
                             `<button class="roll-sp" data-k="spell_damage" data-crit="1" data-id="${sp.id}">×2</button>`; }
        btns += `<button class="primary cast-sp" data-id="${sp.id}">${sp.level>0?"Cast ▸":"Use"}</button>`;
      }
      return `<div class="sprow"><span>${sp.level>0?`<small>${sp.level}L</small>`:"<small>✨</small>"} ${esc(sp.name)}</span> <small style="opacity:.6">${esc(sp.school||"")}${sp.dmg?(" · "+esc(sp.dmg)):""}</small><span class="spbtns">${btns}</span></div>`;
    }).join("");
    bookBlock = `<details class="sheet-sec" open><summary><h3>📖 Spellbook ${slotLine.length?`<small style="opacity:.6"> · ${slotLine.join(" ")}</small>`:`<small style="opacity:.6"> · no slots</small>`}</h3></summary>${spRows||`<div class="meta" style="opacity:.6">No spells learned.</div>`}</details>`;
  } else if (own && spells.length){
    bookBlock = `<details class="sheet-sec"><summary><h3>📖 Spellbook</h3></summary><div class="meta" style="opacity:.7">Add a <b>📖 spellbook</b> item to your character to cast at the table.</div></details>`;
  }
  body.innerHTML = `
    <div class="hpbar"><div style="width:${Math.max(0,ch.hp/ch.max_hp*100)}%;${ch.hp/ch.max_hp<=.25?"background:var(--red)":""}"></div></div>
    <b>HP ${ch.hp}/${ch.max_hp}</b> · AC ${ac} · Speed ${ch.speed} ft
    ${deathHtml(tok)}
    ${hpStatesHtml(tok, ch, own || isDM)}
    <div class="statline">${STATS.map(([k,l]) =>
      `<div class="stat"><small>${l}</small>${v(ch.stats,k)} <small>${mod(v(ch.stats,k))}</small></div>`).join("")}</div>
    ${conditionsHtml(tok)}
    ${defenseHtml(ch.defenses)}
    ${inv.length ? `<div class="inv"><div class="wlabel">Inventory <small style="opacity:.6">(attuned ${(ch.items||[]).filter(x=>x.attunable&&x.attuned).length}/3)</small></div>${invRows}</div>` : ""}
    ${skillBlock}${bookBlock}
    <details><summary style="cursor:pointer;font-size:.8rem;opacity:.7">Notes</summary><div style="white-space:pre-wrap;font-size:.82rem">${esc(ch.notes)}</div></details>`;
  for (const b of body.querySelectorAll(".inv-btns button")) b.onclick = () => {
    const id = b.dataset.id;
    if (b.dataset.a === "use") wsSend({ type:"use_item", token_id: tok.id, item_id: id });
    else if (b.dataset.a === "attune") wsSend({ type:"attune", char_id: ch.id, item_id: id });
    else if (b.dataset.a === "identify") wsSend({ type:"identify", char_id: ch.id, item_id: id });
    else if (b.dataset.a === "recharge") wsSend({ type:"recharge", char_id: ch.id, item_id: id });
  };
  const _vis = () => ($("sr-vis") && $("sr-vis").value) || "public";
  for (const b of body.querySelectorAll(".sk-roll")) b.onclick = () => wsSend({ type:"roll", kind:"skill", skill: b.dataset.skill, visibility:_vis(), adv: ($("sr-adv") && $("sr-adv").value) || null });
  for (const b of body.querySelectorAll(".roll-sp")) b.onclick = () => wsSend({ type:"roll", kind: b.dataset.k, spell_id: b.dataset.id, crit: b.dataset.crit === "1", visibility:_vis(), adv: ($("sr-adv") && $("sr-adv").value) || null });
  for (const b of body.querySelectorAll(".cast-sp")) b.onclick = () => wsSend({ type:"cast", spell_id: b.dataset.id, visibility:_vis(), adv: ($("sr-adv") && $("sr-adv").value) || null });
  wireConditions(tok);
  wireHpStates(tok);
  wireDeath(tok);
  $("hp-btns").classList.toggle("hidden", state.room.role !== "dm" || !tok.character_id);
  $("hp-adv").classList.toggle("hidden", state.room.role !== "dm");
  function v(s,k){ const x = s && s[k]; return typeof x === "number" ? x : 10; }
}
function hpDelta(d){
  const tok = state.tokens.find(t => t.id === state.sel);
  if (!tok) return;
  const dt = d < 0 ? ($("hp-dtype") ? $("hp-dtype").value : "") : "";
  wsSend({ type:"hp", token_id: tok.id, delta: d, damage_type: dt, crit: !!(d < 0 && $("hp-crit") && $("hp-crit").checked) });
  if (tok.npc && state.npcEdit){
    const n = state.npcEdit;
    n.hp = Math.max(0, Math.min(n.max_hp||0, (n.hp||0) + d));
    syncNpcHp();
  }
}

/* ---------- NPC / enemy sheet (DM editor) ---------- */
const _nmod = v => { const m = Math.floor(((+v||10)-10)/2); return (m>=0?"+":"")+m; };

function renderNpcSheet(tok){
  const body = $("sheet-body");
  const n = state.npcEdit = JSON.parse(JSON.stringify(
    Object.assign({ spells:[], spell_slots:{}, stats:{}, attacks:[], abilities:[], resources:[] }, tok.npc||{})));
  n.spell_slots = n.spell_slots || {};
  n.saves = n.saves || {};
  const pb = _pb(n.level || 1);
  $("hp-btns").classList.toggle("hidden", state.room.role !== "dm");
  $("hp-adv").classList.toggle("hidden", state.room.role !== "dm");
  const statCells = STATS.map(([k,l]) =>
    `<div class="stat"><small>${l}</small>` +
    `<input class="npc-stat" data-k="${k}" type="number" min="1" max="30" value="${(n.stats&&n.stats[k])||10}" style="width:100%;text-align:center">` +
    `<small id="nm-${k}">${_nmod((n.stats&&n.stats[k])||10)}</small></div>`).join("");
  const abilRolls = STATS.map(([k,l]) => {
    const sb = _smod((n.stats&&n.stats[k])||10) + (n.saves[k] ? pb : 0);
    return `<span class="abil"><button data-roll="check" data-ability="${k}" title="Ability check">${l}</button>` +
           `<button class="sv" data-roll="save" data-ability="${k}" title="${l} saving throw">${sb>=0?"+":""}${sb}${n.saves[k]?" #":""}</button></span>`;
  }).join("");
  const slotCells = [];
  for (let lv=1; lv<=9; lv++){
    const d = n.spell_slots[String(lv)] || n.spell_slots[lv] || {max:0};
    slotCells.push(`<label class="slotcell">L${lv}<input class="npc-slot" data-lv="${lv}" type="number" min="0" max="9" value="${d.max||0}" style="width:36px"></label>`);
  }
  body.innerHTML = `
    <div class="row"><input id="npc-name" placeholder="NPC name" value="${esc(tok.label)}" maxlength="32">
      <select id="npc-size">${["Tiny","Small","Medium","Large","Huge","Gargantuan"].map(s => `<option value="${s}" ${(tok.size||"Medium")===s?"selected":""}>${s}</option>`).join("")}</select>
      <select id="npc-disp"><option value="">neutral</option>${["friend","neutral","hostile"].map(d => `<option value="${d}" ${(tok.disposition||"")===d?"selected":""}>${d}</option>`).join("")}</select>
    </div>
    <div class="hpbar"><div id="npc-hpbar"></div></div>
    <div class="row">
      <span class="tiny">HP</span><input id="npc-hp" type="number" min="0" value="${n.hp||0}" style="width:50px">/
      <input id="npc-mhp" type="number" min="1" value="${n.max_hp||1}" style="width:50px">
      <span class="tiny">AC</span><input id="npc-ac" type="number" min="1" max="40" value="${n.ac||10}" style="width:46px">
      <span class="tiny">Lv</span><input id="npc-lvl" type="number" min="1" max="30" value="${n.level||1}" style="width:42px">
      <span class="tiny">Spd</span><input id="npc-spd" type="number" min="0" value="${n.speed||30}" style="width:46px">
      <span class="tiny">fly</span><input id="npc-fly" type="number" min="0" value="${n.fly||0}" style="width:46px">
      <span class="tiny">swim</span><input id="npc-swim" type="number" min="0" value="${n.swim||0}" style="width:46px">
      <span class="tiny">climb</span><input id="npc-climb" type="number" min="0" value="${n.climb||0}" style="width:46px">
    </div>
    <div class="statline">${statCells}</div>
    <div class="row chips" id="npc-abil">${abilRolls}</div>
    <div class="row"><label><input type="checkbox" id="npc-prof"> proficient</label>
      <select id="npc-adv"><option value="">—</option><option value="adv">ADV</option><option value="dis">DIS</option></select></div>
    <details class="sheet-sec"><summary><h3>Conditions</h3></summary>
      ${conditionsHtml(tok)}</details>
    <details class="sheet-sec"><summary><h3>Save proficiencies &amp; Defenses</h3></summary>
      <div class="row chips" id="npc-saves">${STATS.map(([k,l]) =>
        `<label title="${l} saving throw"><input type="checkbox" class="npc-save" data-k="${k}" ${n.saves[k]?"checked":""}>${l}</label>`).join("")}</div>
      <div class="row"><input id="npc-def-res" placeholder="resist fire, cold" value="${esc((n.defenses && n.defenses.resist || []).join(", "))}" maxlength="80"></div>
      <div class="row"><input id="npc-def-vuln" placeholder="vulnerable radiant" value="${esc((n.defenses && n.defenses.vulnerable || []).join(", "))}" maxlength="80"></div>
      <div class="row"><input id="npc-def-imm" placeholder="immune poison" value="${esc((n.defenses && n.defenses.immune || []).join(", "))}" maxlength="80"></div>
    </details>
    <details class="sheet-sec"><summary><h3>Spellcasting</h3></summary>
      <div class="wlabel">Spell slots (max/level)</div>
      <div class="row slots">${slotCells.join("")}</div>
      <div class="wlabel">Spellbook</div>
      <div id="npc-spells"></div>
      <div class="row"><button id="npc-spell-add" class="ghost" type="button">＋ Add spell</button></div>
    </details>
    <details class="sheet-sec"><summary><h3>Attacks</h3></summary>
      <div class="tiny" style="margin-bottom:.2rem">pick a target, then Atk</div>
      <div id="npc-attacks"></div>
      <div class="row"><button id="npc-attack-add" class="ghost" type="button">＋ Add attack</button></div>
    </details>
    <details class="sheet-sec"><summary><h3>Actions</h3></summary>
      <div id="npc-abilities"></div>
      <div class="row"><button id="npc-ability-add" class="ghost" type="button">＋ Add action</button></div>
    </details>
    <details class="sheet-sec"><summary><h3>Resources</h3></summary>
      <div class="tiny" style="margin-bottom:.2rem">refill on long rest</div>
      <div id="npc-resources"></div>
      <div class="row"><button id="npc-resource-add" class="ghost" type="button">＋ Add resource</button></div>
    </details>
    <details class="sheet-sec"><summary><h3>Notes</h3></summary>
      <div class="row"><textarea id="npc-notes" rows="3" maxlength="1000" placeholder="Tactics, loot, secrets…" style="width:100%">${esc(n.notes||"")}</textarea></div>
    </details>
    <div class="row">
      <button id="npc-save" class="primary">💾 Save NPC</button>
      <button id="npc-to-best" class="ghost">＋ Bestiary</button>
      <button id="npc-del" style="color:var(--red)">Remove</button>
    </div>`;
  for (const b of body.querySelectorAll(".npc-stat")) b.oninput = () => {
    n.stats = n.stats || {}; n.stats[b.dataset.k] = Math.max(1, Math.min(30, +b.value||10));
    const m = $("nm-"+b.dataset.k); if (m) m.textContent = _nmod(n.stats[b.dataset.k]);
    renderNpcSpells(tok);
  };
  $("npc-hp").oninput = e => { n.hp = Math.max(0, +e.target.value||0); syncNpcHp(); };
  $("npc-mhp").oninput = e => { n.max_hp = Math.max(1, +e.target.value||1); if (n.hp>n.max_hp) n.hp=n.max_hp; syncNpcHp(); };
  $("npc-ac").oninput = e => n.ac = Math.max(1, Math.min(40, +e.target.value||10));
  $("npc-spd").oninput = e => n.speed = Math.max(0, +e.target.value||0);
  $("npc-fly").oninput = e => n.fly = Math.max(0, +e.target.value||0);
  $("npc-swim").oninput = e => n.swim = Math.max(0, +e.target.value||0);
  $("npc-climb").oninput = e => n.climb = Math.max(0, +e.target.value||0);
  $("npc-lvl").oninput = e => { n.level = Math.max(1, Math.min(30, +e.target.value||1)); renderNpcSpells(tok); };
  for (const b of body.querySelectorAll(".npc-slot")) b.oninput = () => {
    const lv = b.dataset.lv; const prev = n.spell_slots[String(lv)] || {used:0};
    n.spell_slots[String(lv)] = { max: Math.max(0, Math.min(9, +b.value||0)), used: Math.min(Math.max(0,Math.min(9,+b.value||0)), prev.used||0) };
  };
  for (const b of $("npc-abil").querySelectorAll("button")) b.onclick = () => wsSend(
    { type:"roll", kind: b.dataset.roll, ability: b.dataset.ability, token_id: tok.id,
      prof: b.dataset.roll === "check" && $("npc-prof").checked, adv: $("npc-adv").value || null });
  for (const b of $("npc-saves").querySelectorAll("input")) b.onchange = () => {
    if (b.checked) n.saves[b.dataset.k] = true; else delete n.saves[b.dataset.k];
    renderNpcSheet(tok);
  };
  const nparse = s => (String(s||"").split(/[,;]+/).map(x=>x.trim().toLowerCase()).filter(x => DMG_TYPES.includes(x)).slice(0,12));
  $("npc-def-res").oninput = e => { n.defenses = n.defenses||{}; n.defenses.resist = nparse(e.target.value); };
  $("npc-def-vuln").oninput = e => { n.defenses = n.defenses||{}; n.defenses.vulnerable = nparse(e.target.value); };
  $("npc-def-imm").oninput = e => { n.defenses = n.defenses||{}; n.defenses.immune = nparse(e.target.value); };
  $("npc-spell-add").onclick = () => {
    n.spells = n.spells || [];
    n.spells.push({ id: eid(), name:"", level:1, school:"", cast:"none", ability:"int", dmg:"", save:"", range:"", duration:"" });
    renderNpcSpells(tok);
  };
  $("npc-attack-add").onclick = () => {
    n.attacks = n.attacks || [];
    n.attacks.push({ id: eid(), name:"Attack", to_hit:0, dmg:"", dc:0, save:"", reach:5 });
    renderNpcAttacks(tok);
  };
  $("npc-ability-add").onclick = () => {
    n.abilities = n.abilities || [];
    n.abilities.push({ name: "Action", desc: "" });
    renderNpcAbilities(tok);
  };
  $("npc-resource-add").onclick = () => {
    n.resources = n.resources || [];
    n.resources.push({ name: "Resource", max: 1, cur: 1 });
    renderNpcResources(tok);
  };
  $("npc-notes").oninput = e => { n.notes = e.target.value; };
  $("npc-save").onclick = () => {
    wsSend({ type:"update_npc", token_id: tok.id, label: ($("npc-name").value||"NPC").slice(0,32),
      level: n.level, stats: n.stats, hp: n.hp, max_hp: n.max_hp, ac: n.ac, speed: n.speed,
      fly: n.fly || 0, swim: n.swim || 0, climb: n.climb || 0,
      attacks: n.attacks, spells: n.spells, spell_slots: n.spell_slots,
      saves: n.saves, defenses: n.defenses,
      abilities: n.abilities, resources: n.resources, notes: n.notes,
      size: $("npc-size").value, disposition: $("npc-disp").value || "neutral" });
    toast("NPC saved");
  };
  $("npc-del").onclick = () => { if (confirm("Remove this NPC token?")) wsSend({ type:"del_token", token_id: tok.id }); };
  $("npc-to-best").onclick = () => saveNpcToBestiary(n, ($("npc-name").value || "NPC").slice(0,32), tok);
  renderNpcSpells(tok);
  renderNpcAttacks(tok);
  renderNpcAbilities(tok);
  renderNpcResources(tok);
  syncNpcHp();
  wireConditions(tok);
}

function renderNpcAbilities(tok){
  const n = state.npcEdit, box = $("npc-abilities"); if (!n || !box) return;
  n.abilities = n.abilities || [];
  box.innerHTML = "";
  n.abilities.forEach((a, i) => {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = `<input class="npc-ab-name" placeholder="Breath Weapon" maxlength="32" value="${esc(a.name||"")}" style="width:34%">
      <input class="npc-ab-desc" placeholder="30ft cone, DC15, 8d6 fire" maxlength="240" value="${esc(a.desc||"")}" style="flex:1">
      <button class="npc-ab-del" style="color:var(--red)" title="Remove">✕</button>`;
    row.querySelector(".npc-ab-name").oninput = e => { a.name = e.target.value; };
    row.querySelector(".npc-ab-desc").oninput = e => { a.desc = e.target.value; };
    row.querySelector(".npc-ab-del").onclick = () => { n.abilities.splice(i, 1); renderNpcAbilities(tok); };
    box.appendChild(row);
  });
}

function renderNpcResources(tok){
  const n = state.npcEdit, box = $("npc-resources"); if (!n || !box) return;
  n.resources = n.resources || [];
  box.innerHTML = "";
  n.resources.forEach((r, i) => {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = `<input class="npc-res-name" placeholder="Breath Weapon" maxlength="32" value="${esc(r.name||"")}" style="width:44%">
      <span class="tiny">used</span>
      <input class="npc-res-cur" type="number" min="0" max="99" value="${r.cur ?? r.max ?? 1}" style="width:46px">
      <span class="tiny">of</span>
      <input class="npc-res-max" type="number" min="0" max="99" value="${r.max ?? 1}" style="width:46px">
      <button class="npc-res-del" style="color:var(--red)" title="Remove">✕</button>`;
    row.querySelector(".npc-res-name").oninput = e => { r.name = e.target.value; };
    row.querySelector(".npc-res-cur").oninput = e => { r.cur = Math.max(0, Math.min(99, +e.target.value||0)); };
    row.querySelector(".npc-res-max").oninput = e => { r.max = Math.max(0, Math.min(99, +e.target.value||0)); };
    row.querySelector(".npc-res-del").onclick = () => { n.resources.splice(i, 1); renderNpcResources(tok); };
    box.appendChild(row);
  });
}

function renderNpcAttacks(tok){
  const n = state.npcEdit, box = $("npc-attacks"); if (!n || !box) return;
  n.attacks = n.attacks || [];
  box.innerHTML = "";
  if (!n.attacks.length){ box.innerHTML = "<div class='meta' style='opacity:.6'>No attacks — add one below.</div>"; return; }
  const targets = state.tokens.filter(t => t.id !== tok.id);
  const opts = targets.map(t => `<option value="${t.id}">${esc(t.label)}</option>`).join("")
                   || `<option value="">— no target —</option>`;
  n.attacks.forEach((a, idx) => {
    const r = document.createElement("div"); r.className = "sprow atkrow";
    r.innerHTML = `
      <input class="na-name" placeholder="Attack" value="${esc(a.name||"")}" maxlength="32" style="min-width:92px">` +
      `<span class="tiny">+<input class="na-hit" type="number" min="-20" max="30" value="${a.to_hit||0}" style="width:44px"></span>` +
      `<input class="na-dmg" placeholder="1d6+3" value="${esc(a.dmg||"")}" maxlength="16" title="Damage dice" style="width:58px">` +
      `<select class="na-tgt" title="Target">${opts}</select>` +
      `<button class="atk-go" data-m="attack" title="Attack roll vs target AC">Atk</button>` +
      (a.dmg?`<button class="atk-go" data-m="damage" title="Roll damage only">Dmg</button>`:"") +
      ((+a.dc>0)?`<button class="atk-go" data-m="dc" title="Post save DC">DC ${+a.dc}</button>`:"") +
      `<span class="tiny">dc</span><input class="na-dc" type="number" min="0" max="30" value="${a.dc||0}" style="width:38px">` +
      `<button class="na-del" title="Remove">✕</button>`;
    const send = mode => { const v = r.querySelector(".na-tgt").value;
      wsSend({ type:"npc_attack", token_id: tok.id, attack: idx, mode, target_id: v ? +v : null }); };
    r.querySelector(".na-name").oninput = e => a.name = e.target.value;
    r.querySelector(".na-hit").oninput = e => a.to_hit = Math.max(-20, Math.min(30, +e.target.value||0));
    r.querySelector(".na-dmg").oninput = e => a.dmg = e.target.value;
    r.querySelector(".na-dc").oninput = e => a.dc = Math.max(0, Math.min(30, +e.target.value||0));
    r.querySelector(".na-del").onclick = () => { n.attacks.splice(idx, 1); renderNpcAttacks(tok); };
    for (const b of r.querySelectorAll(".atk-go")) b.onclick = () => send(b.dataset.m);
    box.appendChild(r);
  });
}

function renderNpcSpells(tok){
  const n = state.npcEdit, box = $("npc-spells"); if (!n || !box) return;
  const pb = _pb(n.level);
  box.innerHTML = "";
  const list = n.spells || [];
  if (!list.length){ box.innerHTML = "<div class='meta' style='opacity:.6'>No spells — add one below.</div>"; return; }
  list.forEach(sp => {
    const abv = (n.stats && n.stats[sp.ability]) || 10;
    const atk = pb + _smod(abv), dc = 8 + pb + _smod(abv);
    const r = document.createElement("div"); r.className = "sprow";
    r.innerHTML = `
      <input class="ns-name" placeholder="Spell" value="${esc(sp.name||"")}" maxlength="48" style="min-width:110px">
      <input class="ns-lvl" type="number" min="0" max="9" value="${sp.level==null?1:sp.level}" title="Level (0=cantrip)" style="width:40px">
      <select class="ns-ab">${STATS.map(([k,l])=>`<option value="${k}" ${sp.ability===k?"selected":""}>${l}</option>`).join("")}</select>
      <select class="ns-cast" title="Casting"><option value="none" ${(!sp.cast||sp.cast==="none")?"selected":""}>—</option><option value="attack" ${sp.cast==="attack"?"selected":""}>atk</option><option value="save" ${sp.cast==="save"?"selected":""}>save</option></select>
      <input class="ns-dmg" placeholder="8d6" value="${esc(sp.dmg||"")}" maxlength="16" title="Damage dice" style="width:52px">
      <button class="roll-sp" data-k="spell_attack" title="Spell attack">Atk${atk>=0?"+":""}${atk}</button>
      <button class="roll-sp" data-k="spell_dc" title="Save DC">DC ${dc}</button>
      ${sp.dmg?`<button class="roll-sp" data-k="spell_damage">Dmg</button><button class="roll-sp" data-k="spell_damage" data-crit="1">×2</button>`:""}
      <button class="primary cast-sp">${(+sp.level>0?"Cast▸":"Use")}</button>
      <button class="ns-del" title="Remove">✕</button>`;
    const send = (o) => wsSend(Object.assign({ token_id: tok.id, spell_id: sp.id }, o));
    r.querySelector(".ns-name").oninput = e => sp.name = e.target.value;
    r.querySelector(".ns-lvl").oninput = e => sp.level = Math.max(0, Math.min(9, +e.target.value||0));
    r.querySelector(".ns-ab").onchange = e => { sp.ability = e.target.value; renderNpcSpells(tok); };
    r.querySelector(".ns-cast").onchange = e => sp.cast = e.target.value;
    r.querySelector(".ns-dmg").oninput = e => sp.dmg = e.target.value;
    for (const b of r.querySelectorAll(".roll-sp")) b.onclick = () =>
      send({ type:"roll", kind: b.dataset.k, crit: b.dataset.crit === "1", adv: ($("npc-adv")&&$("npc-adv").value)||null });
    r.querySelector(".cast-sp").onclick = () => send({ type:"cast", adv: ($("npc-adv")&&$("npc-adv").value)||null });
    r.querySelector(".ns-del").onclick = () => { n.spells.splice(n.spells.indexOf(sp),1); renderNpcSpells(tok); };
    box.appendChild(r);
  });
}

function syncNpcHp(){
  const n = state.npcEdit; if (!n) return;
  const hp = $("npc-hp"), bar = $("npc-hpbar"); if (!hp) return;
  hp.value = n.hp;
  const pct = Math.max(0, (n.hp||0)/(n.max_hp||1)*100);
  if (bar){ bar.style.width = pct+"%"; bar.style.background = pct<=25 ? "var(--red)" : "var(--orange,#e07b39)"; }
}

/* ---------- conditions (shared by character + NPC sheets) ---------- */
function conditionsHtml(tok){
  const isDM = state.room.role === "dm", own = tok.owner_user_id === state.me.id;
  const editable = isDM || own;
  const conds = tok.conds || [];
  const chips = conds.map(c => {
    const dur = c.rounds ? ` <small>(${c.rounds})</small>` : "";
    const rm = editable ? `<button class="cond-rm" data-k="${esc(c.k)}" title="Remove">✕</button>` : "";
    return `<span class="cond-chip"><i style="background:${condColor(c.k)}"></i>${esc(condLabel(c.k))}${dur}${rm}</span>`;
  }).join("");
  const list = Object.entries(CONDITIONS).map(([k, v]) => `<option value="${k}">${v[0]}</option>`).join("");
  const editor = editable ? `<div class="row cond-add"><input id="cond-name" list="cond-list" placeholder="condition…" style="flex:1">` +
    `<datalist id="cond-list">${list}</datalist>` +
    `<input id="cond-rounds" type="number" min="0" max="999" placeholder="∞" title="rounds (blank = until removed)" style="width:52px">` +
    `<button id="cond-add" class="primary">＋</button></div>` : "";
  return `<div class="conds"><div class="wlabel">Conditions</div>` +
    (conds.length ? `<div class="cond-chips">${chips}</div>` : `<div class="meta" style="opacity:.6">None</div>`) +
    editor + `</div>`;
}

function wireConditions(tok){
  const body = $("sheet-body"); if (!body) return;
  for (const b of body.querySelectorAll(".cond-rm"))
    b.onclick = () => wsSend({ type:"cond_remove", token_id: tok.id, key: b.dataset.k });
  const add = $("cond-add");
  if (add) add.onclick = () => {
    const k = ($("cond-name").value || "").trim(); if (!k) return;
    const r = parseInt($("cond-rounds").value, 10);
    wsSend({ type:"cond_add", token_id: tok.id, key:k, rounds: isNaN(r) ? 0 : Math.max(0, Math.min(999, r)) });
    $("cond-name").value = ""; $("cond-rounds").value = "";
  };
}

function defenseHtml(d){
  d = d || {};
  const rows = [["resist", d.resist||[], "#7fb3d5"], ["vulnerable", d.vulnerable||[], "#f5b7b1"], ["immune", d.immune||[], "#a9dfbf"]].filter(x => x[1].length);
  if (!rows.length) return "";
  return `<div class="defenses"><div class="wlabel">Damage Defenses</div>` + rows.map(([k,list,col]) =>
    `<div><small style="opacity:.7">${k}:</small> ${list.map(x => `<span style="background:${col};color:#111;border-radius:4px;padding:0 4px">${esc(x)}</span>`).join(" ")}</div>`).join("") + `</div>`;
}
function hpStatesHtml(tok, ch, canManage){
  const max = ch.hit_dice_max != null ? ch.hit_dice_max : ch.level || 1;
  const spent = Math.max(0, Math.min(max, ch.hit_dice_spent || 0)), avail = max - spent;
  const temp = ch.temp_hp || 0, insp = !!ch.inspiration, exh = ch.exhaustion || 0;
  const stateChips = `<small class="tag">Temp ${temp}</small><small class="tag">Insp ${insp ? "on" : "off"}</small>
    <small class="tag">Exh ${exh}</small><small class="tag">Hit dice ${avail}</small>`;
  const controls = canManage ? `
    <div class="row hp-states">
      <input id="hp-temp" type="number" min="0" max="999" placeholder="temp" style="width:58px">
      <button class="state-btn" id="btn-temp-grant">Grant</button>
      <button class="state-btn" id="btn-temp-clear">Clear</button>
      <button class="state-btn ${insp ? "on" : ""}" id="btn-insp">${insp ? "Insp" : "Insp"}</button>
    </div>
    <div class="row hp-states">
      <input id="hd-count" type="number" min="0" max="${avail}" value="0" style="width:44px">
      <button class="state-btn" id="btn-short">Short rest</button>
    </div>` : "";
  const exhCtl = state.room.role === "dm" ? `
    <div class="row hp-states"><small>Exhaustion</small><button class="state-btn exh-btn" data-a="dec">−</button>
    <button class="state-btn exh-btn" data-a="inc">+</button></div>` : "";
  const res = (ch.resources || []).map(r => `
    <div class="resource-row"><span>${esc(r.name)}</span><small>${r.current}/${r.max} ${r.reset}</small>` +
    (canManage ? `<button class="state-btn res-btn" data-id="${esc(r.id)}" data-a="dec">−</button>
                  <button class="state-btn res-btn" data-id="${esc(r.id)}" data-a="inc">+</button>` : "") +
    `</div>`).join("");
  return `<div class="hp-states-wrap"><div class="wlabel">HP States &amp; Resources</div>
    <div class="row chips">${stateChips}</div>${controls}${exhCtl}
    ${res ? `<div>${res}</div>` : ""}</div>`;
}

function wireHpStates(tok){
  const body = $("sheet-body"); if (!body) return;
  const temp = $("hp-temp");
  if ($("btn-temp-grant")) $("btn-temp-grant").onclick = () => wsSend({ type:"temp_hp", token_id: tok.id, action:"grant", amount: +temp.value || 0 });
  if ($("btn-temp-clear")) $("btn-temp-clear").onclick = () => wsSend({ type:"temp_hp", token_id: tok.id, action:"clear", amount:0 });
  if ($("btn-insp")) $("btn-insp").onclick = () => wsSend({ type:"inspiration", token_id: tok.id, action:"toggle" });
  if ($("btn-short")) $("btn-short").onclick = () => wsSend({ type:"short_rest", token_id: tok.id, hit_dice_count: +$("hd-count").value || 0 });
  for (const b of body.querySelectorAll(".exh-btn")) b.onclick = () => wsSend({ type:"exhaustion", token_id: tok.id, action:b.dataset.a });
  for (const b of body.querySelectorAll(".res-btn")) b.onclick = () => wsSend({ type:"resource", token_id: tok.id, resource_id:b.dataset.id, action:b.dataset.a });
}

/* ---------- death saving throws (character sheet) ---------- */
function deathHtml(tok){
  const d = tok.death; if (!d) return "";
  const isDM = state.room.role === "dm", own = tok.owner_user_id === state.me.id;
  const boxes = n => { let h = ""; for (let i=0;i<3;i++) h += `<span class="dsv${i<n?" on":""}"></span>`; return h; };
  const status = d.dead ? `<b style="color:var(--red)">DEAD</b>` : d.stable ? `<b style="color:var(--green)">Stable</b>` : `<b style="color:var(--red)">Dying</b>`;
  const roll = (own || isDM) && !d.stable && !d.dead ? `<button id="dsave" class="primary">☠ Roll Death Save</button>` : "";
  const clr = isDM ? `<button id="dclear" class="ghost">Clear</button>` : "";
  return `<div class="death"><div class="wlabel">Death Saves</div>
    <div class="dsrow"><span class="tiny">Succ</span><span class="dsucc">${boxes(d.s)}</span>
      <span class="tiny">Fail</span><span class="dfail">${boxes(d.f)}</span>${status}</div>
    <div class="row dsbtns">${roll}${clr}</div></div>`;
}
function wireDeath(tok){
  const b = $("dsave"); if (b) b.onclick = () => wsSend({ type:"death_save", token_id: tok.id });
  const c = $("dclear"); if (c) c.onclick = () => wsSend({ type:"death_clear", token_id: tok.id });
}

function renderOnline(){
  $("online").innerHTML = [...state.online].map(u =>
    `<b>●</b> ${esc(u)}`).join(" &nbsp; ");
}

/* ---------- Quest Log (state from /state, mutations via DM WS ops) ---------- */
function renderQuests(){
  const el = $("quest-list"); if (!el) return;
  const isDm = state.room && state.room.role === "dm";
  const nw = $("quest-new"); if (nw) nw.classList.toggle("hidden", !isDm);
  const qs = state.quests || [];
  el.innerHTML = qs.length ? qs.map(q => {
    const objs = (q.objectives || []).map(o =>
      `<div class="row"><small style="flex:1">${o.done ? "☑" : "☐"} ${esc(o.text)}${o.hidden ? " · hidden hint" : ""}</small>` +
      (isDm ? `<button class="ghost q-obj" data-q="${q.id}" data-o="${esc(o.id)}" data-done="${o.done ? 1 : 0}" style="padding:0 6px">${o.done ? "Undo" : "✓"}</button>` : "") +
      `</div>`).join("");
    const objAdd = isDm ? `<div class="row"><input class="q-objtext" data-q="${q.id}" placeholder="new objective" maxlength="200" style="flex:1">` +
      `<button class="ghost q-objadd" data-q="${q.id}">+ Obj</button></div>` : "";
    const dmBtns = isDm ? `<div class="row">` +
      `<button class="ghost q-done" data-q="${q.id}" data-status="${esc(q.status)}">Complete</button>` +
      `<button class="ghost q-fail" data-q="${q.id}">Fail</button>` +
      `<button class="ghost q-hide" data-q="${q.id}" data-status="${esc(q.status)}">${q.status === "hidden" ? "Show" : "Hide"}</button>` +
      `<button class="ghost q-vis" data-q="${q.id}" data-vis="${esc(q.visibility)}">${q.visibility === "dm" ? "→ Party" : "→ DM only"}</button>` +
      `<button class="ghost q-del" data-q="${q.id}" style="color:var(--red)">Delete</button></div>` : "";
    const col = q.status === "completed" ? "var(--green)" : q.status === "failed" ? "var(--red)" : "inherit";
    return `<div style="border-bottom:1px solid #333;padding:4px 0">` +
      `<div class="row"><b style="color:${col}">${esc(q.title)}</b>` +
      `<small style="opacity:.6">${esc(q.status)}${q.visibility === "dm" ? " · DM-only" : ""}</small></div>` +
      (q.description ? `<div><small>${esc(q.description)}</small></div>` : "") +
      objs + objAdd + dmBtns + `</div>`;
  }).join("") : `<small>${isDm ? "No quests yet — add one below." : "No quests yet."}</small>`;
  if (!isDm) return;
  const $q = (sel) => el.querySelectorAll(sel);
  $q(".q-obj").forEach(b => b.onclick = () =>
    wsSend({ type: "quest_obj_done", quest_id: +b.dataset.q, objective_id: b.dataset.o, done: b.dataset.done !== "1" }));
  $q(".q-objadd").forEach(b => b.onclick = () => {
    const inp = el.querySelector(`.q-objtext[data-q="${b.dataset.q}"]`); if (!inp || !inp.value.trim()) return;
    wsSend({ type: "quest_obj_add", quest_id: +b.dataset.q, text: inp.value.trim() });
  });
  $q(".q-done").forEach(b => b.onclick = () => wsSend({ type: "quest_complete", quest_id: +b.dataset.q }));
  $q(".q-fail").forEach(b => b.onclick = () => wsSend({ type: "quest_fail", quest_id: +b.dataset.q }));
  $q(".q-hide").forEach(b => b.onclick = () =>
    wsSend({ type: "quest_update", quest_id: +b.dataset.q, status: b.dataset.status === "hidden" ? "active" : "hidden" }));
  $q(".q-vis").forEach(b => b.onclick = () =>
    wsSend({ type: "quest_update", quest_id: +b.dataset.q, visibility: b.dataset.vis === "dm" ? "party" : "dm" }));
  $q(".q-del").forEach(b => b.onclick = () => { if (confirm("Delete this quest?")) wsSend({ type: "quest_delete", quest_id: +b.dataset.q }); });
}
function wireQuestUI(){
  const btn = $("btn-q-add");
  if (btn) btn.onclick = () => {
    const t = $("q-title"); if (!t || !t.value.trim()) return;
    wsSend({ type: "quest_add", title: t.value.trim(), visibility: "party" });
    t.value = "";
  };
}
