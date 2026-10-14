/* ---------- room ---------- */
(typeof window !== "undefined") && ((window.__BUILDS = window.__BUILDS || {})["30_room.js"] = window.__BUILD__ || "?");
async function openRoom(code){
  const s = await api(`/rooms/${code}/state`);
  state.room = s; state.roomDeleted = false;   // fresh visit — re-arms auto-reconnect
  // D88/D102: the SERVER is the view SSOT — the DM starts at primary (s comes
  // without ?floor=), a PLAYER is delivered on their token's plane; a player
  // on a named floor must have viewFloor match, or plane-guarded events
  // (reveals, pings, AoE, editor saves) all address the wrong plane.
  state.viewFloor = s.view_floor || "";
  state.init = s.initiative; state.tokens = s.tokens; state.ghosts = s.ghosts || [];
  state.floors = s.floors || [""];
  state.grid = s.grid; state.editing = false; state.editMap = null; state.sel = null;
  state.preview = null; state.lightMoveId = null;   // D104: no preview survives a room switch
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
  if ($("floorpanel")) $("floorpanel").classList.toggle("hidden", s.role !== "dm");
  renderViewFloor();   // D102: plane row + floor panel exist from the first render
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
  if (s.role === "dm"){ await loadBestiary(); await loadEncounters(); refreshContentKinds(); }
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

function renderViewFloor(){
  // D88: the selector only earns its place once the room has planes to browse
  const row = $("view-floor-row"), sel = $("view-floor");
  if (row && sel){
    const many = state.room && state.room.role === "dm" && (state.floors || [""]).length > 1;
    row.classList.toggle("hidden", !many);
    if (many){
      const cur = state.viewFloor || "";
      sel.innerHTML = (state.floors || [""]).map(f =>
        `<option value="${f.replace(/"/g,"&quot;")}" ${f===cur?"selected":""}>${f===""?"⬛ primary":f}</option>`).join("");
      sel.onchange = () => { state.viewFloor = sel.value; refreshRoom(); };
    }
  }
  if (typeof renderFloorPanel === "function") renderFloorPanel();   // D102
  if (typeof renderLightsPanel === "function") renderLightsPanel(); // D104: lamps of the VIEWED plane
}

/* ---------- D102 floor manager (DM side panel) ---------- */
function renderFloorPanel(){
  const panel = $("floorpanel"), list = $("floor-list");
  if (!panel || !list) return;
  if (!(state.room && state.room.role === "dm")) return;
  const cur = state.viewFloor || "";
  list.innerHTML = (state.floors || [""]).map(f => {
    const act = f === cur;
    const label = f === "" ? "⬛ Ground (primary)" : esc(f);
    const tools = f === ""
      ? `<span class="tiny" title="The primary floor always exists — it cannot be removed or renamed">fixed</span>`
      : `<button class="ghost fl-ren" data-f="${esc(f)}" title="Rename floor">✏️</button>`
        + `<button class="ghost fl-del" data-f="${esc(f)}" title="Delete floor (refused while tokens stand on it)">🗑</button>`;
    return `<div class="row"${act ? ' style="background:rgba(241,196,15,.10)"' : ""}>`
      + `<button class="ghost fl-view" data-f="${esc(f)}" title="Browse this plane — nobody is moved">${label}${act ? " ← viewing" : ""}</button>`
      + tools + `</div>`;
  }).join("");
  for (const b of list.querySelectorAll(".fl-view"))
    b.onclick = () => { state.viewFloor = b.dataset.f; refreshRoom(); };
  for (const b of list.querySelectorAll(".fl-del"))
    b.onclick = () => editFloor("DELETE", b.dataset.f, null);
  for (const b of list.querySelectorAll(".fl-ren"))
    b.onclick = () => startFloorRename(b.dataset.f, b);
  const add = $("btn-floor-add"), inp = $("floor-new");
  if (add && inp) add.onclick = () => {
    const name = inp.value.trim(); if (!name) return;
    fetch(`/api/rooms/${encodeURIComponent(state.room.code)}/floors`,
          { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name }) })
      .then(r => r.ok ? r.json() : r.json().catch(() => ({}))
        .then(j => { throw new Error((j && j.detail) || "Cannot add floor"); }))
      .then(j => { inp.value = ""; state.floors = j.floors || state.floors;
                   renderFloorPanel(); renderViewFloor(); })
      .catch(err => toast(err.message || "Cannot add floor"));
  };
}
function startFloorRename(old, btn){
  const row = btn.closest(".row"); if (!row) return;
  row.innerHTML = `<input id="fl-rename-in" maxlength="24" value="${esc(old)}">`
    + `<button class="ghost" id="fl-rename-ok" title="Rename">✓</button>`
    + `<button class="ghost" id="fl-rename-no" title="Cancel">✗</button>`;
  const inp = $("fl-rename-in"); if (inp) inp.focus();
  const done = () => { const v = inp.value.trim();
                       if (v && v !== old) editFloor("PATCH", old, v);
                       else renderFloorPanel(); };
  $("fl-rename-ok").onclick = done;
  $("fl-rename-no").onclick = renderFloorPanel;
  inp.onkeydown = e => { if (e.key === "Enter") done(); if (e.key === "Escape") renderFloorPanel(); };
}
function editFloor(method, old, newName){
  const prev = state.viewFloor || "";
  // Set the view BEFORE asking: the server broadcasts land while the fetch is
  // still in flight, and a refresh must never request the floor that is about
  // to stop existing under the name the server is leaving behind.
  if (method === "PATCH" && prev === old) state.viewFloor = newName;
  if (method === "DELETE" && prev === old) state.viewFloor = "";
  const url = `/api/rooms/${encodeURIComponent(state.room.code)}/floors/${encodeURIComponent(old)}`;
  fetch(url, { method,
               headers: method === "PATCH" ? { "Content-Type": "application/json" } : undefined,
               body: method === "PATCH" ? JSON.stringify({ name: newName }) : undefined })
    .then(r => r.ok ? r.json() : r.json().catch(() => ({}))
      .then(j => { throw new Error((j && j.detail) || "Floor operation failed"); }))
    .then(j => { state.floors = j.floors || state.floors;
                 renderFloorPanel(); renderViewFloor(); refreshRoom(); })
    .catch(err => { toast(err.message || "Floor operation failed");
                    state.viewFloor = prev;
                    renderFloorPanel(); renderViewFloor(); });
}

/* ---------- D104 light manager (DM side panel) + peek (DM preview) ---------- */
function _lamps(){
  const g = state.grid; if (!g) return [];
  return (g.objects || []).filter(o => ((o.interact || {}).op || {}).kind === "lamp");
}
function _pvEsc(s){ return String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;"); }
function renderLightsPanel(){
  const panel = $("lightpanel"), list = $("light-list");
  if (!panel || !list) return;
  if (!(state.room && state.room.role === "dm")) return;
  const fl = state.viewFloor || "";
  const lamps = _lamps();
  list.innerHTML = lamps.length ? ""
    : `<div class="row"><small class="meta" style="opacity:.6">No lamps on ${fl ? "“" + _pvEsc(fl) + "”" : "the primary plane"}.</small></div>`;
  for (const o of lamps){
    const on = !((o.state || {}).on === false);
    const b = ((o.interact || {}).op || {}).bright | 0;
    const row = document.createElement("div"); row.className = "row";
    row.innerHTML =
      `<label style="display:flex;align-items:center;gap:5px;flex:1;min-width:0">` +
      `<input type="checkbox" ${on ? "checked" : ""} title="active / inactive">` +
      `<span>${on ? "💡" : "🌑"}</span>` +
      `<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_pvEsc(o.label || "Lamp")}</span></label>` +
      `<input type="number" min="0" max="30" value="${b}" style="width:54px" title="Bright radius in cells — walls block the glow">` +
      `<button class="ghost pv-move" title="Move: then click the destination cell">➜</button>` +
      `<button class="ghost pv-del" title="Remove this lamp">✕</button>`;
    const [chk, num] = row.querySelectorAll("input");
    chk.onchange = () => wsSend({type:"lamp", action:"update", floor: fl, id: o.id, on: chk.checked});
    num.onchange = () => wsSend({type:"lamp", action:"update", floor: fl, id: o.id, bright: +num.value});
    row.querySelector(".pv-move").onclick = () => {
      state.lightMoveId = o.id; toast("Click the lamp's destination cell"); };
    row.querySelector(".pv-del").onclick = () => {
      if (!confirm(`Remove lamp “${o.label || "Lamp"}”?`)) return;
      wsSend({type:"lamp", action:"remove", floor: fl, id: o.id}); };
    list.appendChild(row);
  }
  const add = $("btn-lamp-add");
  if (add) add.onclick = () => {
    const cv = $("map"); if (!cv || !toCell) return;
    const { cx, cy } = toCell(cv.clientWidth / 2, cv.clientHeight / 2);
    wsSend({type:"lamp", action:"add", floor: fl, x: cx, y: cy, bright: 5, label: "Lamp"});
  };
}
function renderPeek(){
  const sel = $("peek-who");
  if (!sel || !(state.room && state.room.role === "dm")) return;
  const cands = (state.room.members || []).filter(m => m.role !== "dm" && m.character_id);
  sel.innerHTML = cands.map(m => {
    const nm = m.char && m.char.name ? m.char.name : m.username;
    return `<option value="${m.character_id}">${_pvEsc(nm)}${m.char && m.char.name ? " (" + _pvEsc(m.username) + ")" : ""}</option>`;
  }).join("") || `<option value="">no player characters</option>`;
  const b = $("btn-peek");
  if (b) b.onclick = startPeek;
}
function renderPreviewBar(){
  const bar = $("previewbar"); if (!bar) return;
  const rf = $("pv-refresh"), ex = $("pv-exit");
  if (rf) rf.onclick = refreshPeek;
  if (ex) ex.onclick = endPreview;
  bar.classList.toggle("hidden", !state.preview);
  if (!state.preview) return;
  const p = state.preview;
  $("pv-text").textContent = `👁 DM preview: sight of ${p.as.character || p.as.username}`
    + ` · ${p.view_floor ? "floor “" + p.view_floor + "”" : "⬛ primary"}`
    + (p.dark ? " · 🕯 dark" : "");
}
async function startPeek(){
  const sel = $("peek-who"); if (!sel || !sel.value) return;
  if (state.editing){ toast("Save or cancel the map editor first"); return; }
  try {
    const p = await api(`/rooms/${state.room.code}/view_as/${sel.value}`);
    p._cid = +sel.value;
    state.preview = p;
    state.sel = null; if (typeof clearPlan === "function") clearPlan();
    state.lightMoveId = null;
    if (state.viewMode === "diorama") setViewMode("tactical");
    renderPreviewBar(); draw();
    toast(`Previewing ${p.as.character || p.as.username} — view-only`);
  } catch(e){ toast(e.message); }
}
async function refreshPeek(){
  if (!state.preview) return;
  const cid = state.preview._cid;
  try {
    const p = await api(`/rooms/${state.room.code}/view_as/${cid}`);
    p._cid = cid; state.preview = p; renderPreviewBar(); draw();
  } catch(e){ toast(e.message); endPreview(); }   // character vanished: honest exit
}
function endPreview(){ if (!state.preview) return;
  state.preview = null; renderPreviewBar(); draw(); }

async function refreshRoom(){
  const s = await api(`/rooms/${state.room.code}/state`
                      + (state.viewFloor ? `?floor=${encodeURIComponent(state.viewFloor)}` : ""));
  state.room = s; state.init = s.initiative; state.tokens = s.tokens; state.ghosts = s.ghosts || []; state.grid = s.grid;
  state.floors = s.floors || [""];
  state.viewFloor = s.view_floor || ""; renderViewFloor();   // D88: server is the view SSOT
  if (typeof renderFogToggle === "function") renderFogToggle();
  if (state.plan && !state.tokens.find(t => t.id === state.plan.token_id)) state.plan = null;
  updateMoveHud();
  renderParty(); renderInit(); renderMyChars();
  if (typeof renderPeek === "function") renderPeek();             // D104: character list
  if (typeof renderPreviewBar === "function") renderPreviewBar(); // D104: a preview survives refreshes
  state.quests = s.quests || []; renderQuests();
  state.itemDefs = s.item_defs || []; renderInv();   // D92: inventory window
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
function _spanRowHtml(tok){
  const s = tokenSpan(tok);        // effective span: fw/fh win, category square fallback
  return `<div class="row" title="Footprint in grid cells — Apply resizes the token in place">`
    + `<span class="tiny"><b>Footprint</b></span><span class="tiny">W</span>`
    + `<input id="span-w" type="number" min="1" max="10" value="${s[0]}" style="width:46px">`
    + `<span class="tiny">H</span><input id="span-h" type="number" min="1" max="10" value="${s[1]}" style="width:46px">`
    + `<button id="span-apply">Apply</button></div>`;
}
function wireSpanRow(tok){
  const btn = $("span-apply"); if (!btn) return;
  const send = () => {
    const w = parseInt($("span-w").value, 10), h = parseInt($("span-h").value, 10);
    if (!(Number.isInteger(w) && Number.isInteger(h) && w >= 1 && w <= 10 && h >= 1 && h <= 10)){
      toast("Footprint: whole numbers from 1 to 10"); return;
    }
    wsSend({ type:"token_span", token_id: tok.id, width: w, height: h });
  };
  btn.onclick = send;
  $("span-w").onkeydown = e => { if (e.key === "Enter") send(); };
  $("span-h").onkeydown = e => { if (e.key === "Enter") send(); };
}
function _visualRowHtml(tok){
  const s = visualSpan(tok);   // D82: vw/vh win, otherwise the mechanical span — RENDER ONLY
  return `<div class="row" title="Visual size in grid cells — how big the token is DRAWN. Occupancy and collision stay the Footprint.">`
    + `<span class="tiny"><b>Visual Size</b></span><span class="tiny">W</span>`
    + `<input id="vis-w" type="number" min="1" max="10" value="${s[0]}" style="width:46px">`
    + `<span class="tiny">H</span><input id="vis-h" type="number" min="1" max="10" value="${s[1]}" style="width:46px">`
    + `<button id="vis-apply">Apply</button></div>`;
}
function wireVisualRow(tok){
  const btn = $("vis-apply"); if (!btn) return;
  const send = () => {
    const w = parseInt($("vis-w").value, 10), h = parseInt($("vis-h").value, 10);
    if (!(Number.isInteger(w) && Number.isInteger(h) && w >= 1 && w <= 10 && h >= 1 && h <= 10)){
      toast("Visual size: whole numbers from 1 to 10"); return;
    }
    wsSend({ type:"token_visual", token_id: tok.id, width: w, height: h });
  };
  btn.onclick = send;
  $("vis-w").onkeydown = e => { if (e.key === "Enter") send(); };
  $("vis-h").onkeydown = e => { if (e.key === "Enter") send(); };
}
function _artRowHtml(tok){
  state.assets = state.assets === undefined ? null : state.assets;
  const cur = tok.image || "";
  const opts = (state.assets || []).filter(a => /^[0-9a-f]{16}$/.test(a.id))
    .map(a => `<option value="${a.id}"${"/assets/" + a.id === cur ? " selected" : ""}>${esc(a.name)}</option>`).join("");
  return `<div class="row" title="Token artwork (D85): a PNG from your library, validated and re-encoded by the server. Apply without a selection removes the artwork.">`
    + `<span class="tiny"><b>Artwork</b></span>`
    + `<select id="art-pick" style="max-width:130px"><option value="">— none —</option>${opts}</select>`
    + `<input id="art-file" type="file" accept="image/png" style="display:none">`
    + `<button id="art-upload" title="Upload a new PNG (max 1.5 MB)">PNG…</button>`
    + `<button id="art-apply">Apply</button></div>`;
}
function _loadAssets(tok){
  if (state.assetsLoading) return;
  state.assetsLoading = true;
  fetch(`/api/assets?room=${encodeURIComponent(state.room.code)}`)
    .then(r => r.ok ? r.json() : {assets: []})
    .then(j => { state.assets = (j.assets || []).filter(a => /^[0-9a-f]{16}$/.test(a.id)); })
    .catch(() => { state.assets = []; })
    .finally(() => { state.assetsLoading = false;
                     if (state.sel === tok.id) renderSheet(tok); });
}
function _uploadAsset(file){
  return file.arrayBuffer().then(buf =>
    fetch(`/api/assets?name=${encodeURIComponent(String(file.name || "token").replace(/\.png$/i, ""))}`,
          { method: "PUT", body: buf, headers: { "Content-Type": "image/png" } })
      .then(r => r.ok ? r.json() : r.json().catch(() => ({}))
        .then(j => { throw new Error(j && j.detail || `Upload failed (${r.status})`); })));
}
function wireArtRow(tok){
  const sel = $("art-pick"); if (!sel) return;
  if (state.assets == null) _loadAssets(tok);
  $("art-upload").onclick = () => $("art-file").click();
  $("art-file").onchange = e => {
    const f = e.target.files && e.target.files[0]; if (!f) return;
    _uploadAsset(f).then(a => {
      state.assets = null;                       // stale list — refetch on next paint
      wsSend({ type: "token_image", token_id: tok.id, asset_id: a.id });
    }).catch(err => toast(err.message || "Upload failed"));
  };
  $("art-apply").onclick = () => wsSend({ type: "token_image", token_id: tok.id,
                                          asset_id: sel.value || null });
}
function _lightRowHtml(tok){
  const lum = (tok.light | 0), dv = (tok.darkvision | 0);
  return `<div class="row" title="Light (D87): radius in cells this token emits. Only meaningful when the DM turned on darkness — in dark rooms sight comes from light alone.">`
    + `<span class="tiny"><b>Light</b></span><input id="lt-r" type="number" min="0" max="30" value="${lum}" style="width:46px">`
    + `<span class="tiny">cells</span><button id="lt-apply">Apply</button></div>`
    + `<div class="row" title="Darkvision (D89): how far this token sees in darkness. A sense, not a torch — invisible to other players' fog, lights nothing.">`
    + `<span class="tiny"><b>Darkvis.</b></span><input id="dv-r" type="number" min="0" max="30" value="${dv}" style="width:46px">`
    + `<span class="tiny">cells</span><button id="dv-apply">Apply</button></div>`;
}
function wireLightRow(tok){
  const b = $("lt-apply"); if (!b) return;
  const send = () => {
    const r = parseInt($("lt-r").value, 10);
    if (!Number.isInteger(r) || r < 0 || r > 30){ toast("Light radius: 0 to 30 cells"); return; }
    wsSend({ type: "token_light", token_id: tok.id, radius: r });
  };
  b.onclick = send;
  $("lt-r").onkeydown = e => { if (e.key === "Enter") send(); };
  const dvb = $("dv-apply");                                   // D89 darkvision
  if (dvb){
    const senddv = () => {
      const r = parseInt($("dv-r").value, 10);
      if (!Number.isInteger(r) || r < 0 || r > 30){ toast("Darkvision: 0 to 30 cells"); return; }
      wsSend({ type: "token_darkvision", token_id: tok.id, radius: r });
    };
    dvb.onclick = senddv;
    $("dv-r").onkeydown = e => { if (e.key === "Enter") senddv(); };
  }
}
function _floorRowHtml(tok){
  const fls = state.floors && state.floors.length ? state.floors : [""];
  const cur = tok.floor || "";
  const isDM = state.room && state.room.role === "dm";
  const label = cur === "" ? "Ground (primary)" : esc(cur);
  if (!isDM)
    // D102: plane changes are the DM's and the stairs' — players READ their
    // plane; the validated stair object remains their route.
    return `<div class="row" title="Floor (D86): planes are independent — different floors never collide and are not visible to each other. Take the stairs (or wait for the DM) to change planes.">`
      + `<span class="tiny"><b>Floor</b></span><span>${label}</span></div>`;
  const opts = fls.map(f => `<option value="${esc(f)}"${f === cur ? " selected" : ""}>${f === "" ? "Ground (primary)" : esc(f)}</option>`).join("");
  return `<div class="row" title="Floor (D86): planes are independent — different floors never collide and are not visible to each other. Changing floor is an explicit move, not a walked one (D102: DM only — players use stairs).">`
    + `<span class="tiny"><b>Floor</b></span><select id="fl-pick" style="max-width:120px">${opts}</select>`
    + `<button id="fl-go">Go</button>`
    + `<input id="fl-new" placeholder="new floor" maxlength="24" style="width:90px">`
    + `<button id="fl-add" title="Add a floor to this room">＋</button></div>`;
}
function wireFloorRow(tok){
  const go = $("fl-go"); if (!go) return;
  go.onclick = () => wsSend({ type: "token_floor", token_id: tok.id,
                              floor: $("fl-pick").value || null });
  const add = $("fl-add");
  if (add) add.onclick = () => {
    const name = $("fl-new").value.trim(); if (!name) return;
    fetch(`/api/rooms/${encodeURIComponent(state.room.code)}/floors`,
          { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name }) })
      .then(r => r.ok ? r.json() : r.json().catch(() => ({}))
        .then(j => { throw new Error(j && j.detail || "Cannot add floor"); }))
      .then(j => { state.floors = j.floors || state.floors; renderSheet(tok); })
      .catch(err => toast(err.message || "Cannot add floor"));
  };
}
function _rotRowHtml(tok){
  const rot = (((tok.rot | 0) % 360) + 360) % 360;
  return `<div class="row" title="Facing (D83): the entity turns — its mechanical footprint and visual bounds turn with it, re-centred on the same spot. An impossible turn is refused.">`
    + `<span class="tiny"><b>Rotation</b></span>`
    + `<button id="rot-left" title="Rotate 90° left">⟲</button><span class="tiny">${rot}°</span>`
    + `<button id="rot-right" title="Rotate 90° right">⟳</button>`
    + `<button id="rot-reset" title="Face north (0°)">0°</button></div>`;
}
/* D83: movement-mode chips — only modes the creature actually HAS are shown.
   One active mode per move; the server prices each mode from its own budget
   and refuses switching tricks. */
function _moveModeRowHtml(tok){
  const sp = tokenSpeeds(tok);
  const modes = ["walk","fly","swim","climb"].filter(m => m === "walk" || sp[m] > 0);
  if (modes.length < 2) return "";
  state.moveMode = state.moveMode || {};
  const act = state.moveMode[tok.id] || "walk";
  return `<div class="row" title="Movement mode for your next move/preview (D83). Each mode has its own per-turn budget; switching never refunds spent units.">`
    + `<span class="tiny"><b>Move mode</b></span>`
    + modes.map(m => `<button data-mode="${m}" style="${m===act?"outline:2px solid #d4a017":""}">`
        + `${m==="walk"?"🚶":m==="fly"?"🕊":m==="swim"?"🌊":"🧗"} ${m} ${sp[m]||sp.walk}ft</button>`).join("")
    + `</div>`;
}
function wireMoveModeRow(tok){
  document.querySelectorAll("[data-mode]").forEach(b => {
    b.onclick = () => { state.moveMode = state.moveMode || {};
                        state.moveMode[tok.id] = b.dataset.mode;
                        renderSheet(tok); };
  });
}
function wireRotRow(tok){
  const l = $("rot-left"); if (!l) return;
  const cur = () => (((tok.rot | 0) % 360) + 360) % 360;
  const send = d => wsSend({ type:"token_rotate", token_id: tok.id, degrees: ((cur() + d) % 360 + 360) % 360 });
  l.onclick = () => send(270);
  $("rot-right").onclick = () => send(90);
  $("rot-reset").onclick = () => { if (cur() !== 0) send(360 - cur()); };
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
  // D93: peers only ever receive the tactical allow-list (items/stats/spells
  // are sheet-private) — such a row renders as a compact public card.
  if (ch && ch.items === undefined && state.room.role !== "dm"){
    $("sheet-body").innerHTML = `<div class="hpbar"><div style="width:${Math.max(0,(ch.hp||0)/Math.max(1,ch.max_hp)*100)}%"></div></div>` +
      `<b>HP ${ch.hp}/${ch.max_hp}</b>${ch.temp_hp ? ` (+${ch.temp_hp} temp)` : ""} · AC ${ch.ac_total != null ? ch.ac_total : ch.ac} · Speed ${ch.speed} ft` +
      `<div class="meta">Private sheet — ask ${esc(ch.name)} at the table.</div>`;
    $("hp-btns").classList.add("hidden"); $("hp-adv").classList.add("hidden");
    return;
  }
  const clsTxt = ch && ch.class_levels && ch.class_levels.length
    ? ch.class_levels.map(e => e.class_id[0].toUpperCase() + e.class_id.slice(1) + " " + e.level).join(" / ")
    : ((ch && ch.char_class) || "");
  const ctlM = tok.controller_user_id ? state.room.members.find(x => x.user_id === tok.controller_user_id) : null;
  $("sheet-name").textContent = tok.label + (ch ? ` (${[ch.race, clsTxt, "Lv" + (ch.total_level || ch.level || 1)].filter(Boolean).join(" ")})` : " [NPC]")
    + (ctlM ? ` · led by ${ctlM.username}` : "");
  const body = $("sheet-body");
  if (!ch){
    if (tok.npc && state.room.role === "dm"){ renderNpcSheet(tok); return; }
    body.innerHTML = `<div class="meta">No character attached.</div>` +
      `<div class="row"><button id="btn-loot-npc" title="Take gear from this fallen creature — stand next to it">💰 Loot search</button></div>` +
      (state.room.role === "dm"
        ? `<div class="row"><button id="btn-del-npc" style="color:var(--red)">Remove token</button></div>` : "");
    $("hp-btns").classList.add("hidden"); $("hp-adv").classList.add("hidden");
    const del = $("btn-del-npc"); if (del) del.onclick = () => wsSend({ type:"del_token", token_id: tok.id });
    const lo = $("btn-loot-npc"); if (lo) lo.onclick = () => openLootChest(tok.id);
    return;
  }
  const mod = v => { const m2 = Math.floor(((v||10)-10)/2); return (m2>=0?"+":"")+m2; };
  const isDM = state.room.role === "dm", own = tok.owner_user_id === state.me.id;
  const spanRow = (isDM || own) ? _spanRowHtml(tok) + _visualRowHtml(tok) + _artRowHtml(tok) + _floorRowHtml(tok) + _lightRowHtml(tok) + _rotRowHtml(tok) + _moveModeRowHtml(tok) : "";
  const ac = ch.ac_total != null ? ch.ac_total : ch.ac;
  const inv = (ch.items || []);
  const invRows = inv.map(it => {
    const chips = [it.magic ? "✨" : "", it.unidentified ? "❓" : "",
                   it.attuned ? "🔗" : "", (it.charges >= 0 && !it.unidentified) ? `⚡${it.charges}/${it.chargesMax != null ? it.chargesMax : it.charges}` : ""].filter(Boolean).join(" ");
    const btns = [];
    const known = !it.magic || it.identified;
    if (isDM || own) { if (it.heal && known && it.charges !== 0) btns.push(`<button data-a="use" data-id="${it.id}">Use</button>`);
      if (it.attunable) btns.push(`<button data-a="attune" data-id="${it.id}">${it.attuned ? "Untune" : "Attune"}</button>`);
      // D98: a versatile weapon carried in the main hand can be re-gripped; the grip
      // decides the actual damage dice (validated atomically server-side).
      if ((isDM || own) && it.props && it.props.versatile && ch.equipment && ch.equipment.main_hand === it.id)
        btns.push(`<button data-a="grip" data-id="${it.id}" data-grip="${it.grip === "two" ? "one" : "two"}" title="grip determines the damage dice">${it.grip === "two" ? "✋ two→one" : "🤲 one→two"}</button>`); }
    if (isDM && it.magic && !it.identified) btns.push(`<button data-a="identify" data-id="${it.id}">Identify</button>`);
    if (isDM && it.recharge) btns.push(`<button data-a="recharge" data-id="${it.id}">Recharge</button>`);
    return `<div class="inv-row"><span class="inv-name">${ITEM_ICONS[it.kind]||"🎒"} ${esc(it.name)}${it.qty > 1 ? " ×" + it.qty : ""}</span> <small>${chips}</small>
      <small style="opacity:.6">${it.kind==="armor" ? ("AC "+(it.ac||(it.acBonus?("+"+it.acBonus):""))) : (it.heal?("+HP "+it.heal):"")}</small>
      ${it.unidentified ? "" : `<small style="opacity:.55"> ${esc(it.desc||"")}</small>`}<span class="inv-btns">${btns.join("")}</span></div>`;
  }).join("");
  const lvlv = ch.level || 1;
  const skills = ch.skills || {};
  const spells = ch.spells || [];
  const slots = ch.spell_slots || {};
  const _ab = a => (ch.stats && ch.stats[a] != null) ? ch.stats[a] : 10;
  const der = ch.derived || {};
  const sgn = n => (n >= 0 ? "+" : "") + n;
  // D93: bonuses are SERVER numbers (derived) — the client renders, never recomputes.
  const skillBlock = (() => {
    const keys = der.skill_bonuses ? Object.keys(der.skill_bonuses)
                                   : Object.keys(skills).filter(k => skills[k] > 0);
    if (!keys.length) return "";
    return `<details class="sheet-sec" open><summary><h3>Skills</h3></summary>` +
      keys.map(k => {
        const meta = SKILLS[k] || [k, ""];
        const bonus = der.skill_bonuses ? der.skill_bonuses[k]
                                        : _smod(_ab(meta[1])) + _pb(lvlv) * (skills[k] || 0);
        const tag = der.skill_prof ? (der.skill_prof[k] ? (skills[k] === 2 ? "★" : "✓") : "")
                                   : (skills[k] === 2 ? "★" : "✓");
        return `<div class="skrow"><span>${meta[0]} <small>${tag}</small> <b>${sgn(bonus)}</b></span>` +
               (own ? `<button class="sk-roll" data-skill="${k}">Roll</button>` : "") + `</div>`;
      }).join("") + `</details>`;
  })();
  const saveBlock = (own && der.save_bonuses) ? `<details class="sheet-sec"><summary><h3>Saving Throws</h3></summary>` +
    ["str","dex","con","int","wis","cha"].map(a =>
      `<div class="skrow"><span>${a.toUpperCase()} <b>${sgn(der.save_bonuses[a])}</b>${(ch.saves||{})[a]?" ✓":""}</span>` +
      `<button class="sv-roll" data-ab="${a}">Roll</button></div>`).join("") + `</details>` : "";
  // D96: chronological build (Stufe 1..20). A GENERIC, server-validated tool —
  // the client renders the chronology and POSTs choices; the backend (charbuild)
  // owns every rule and re-checks them, so this UI holds no class logic.
  const buildBlock = ((own || isDM) && ch.id) ? (() => {
    let led = {}; try { led = ch.build ? (typeof ch.build === "string" ? JSON.parse(ch.build) : ch.build) : {}; } catch { led = {}; }
    const hist = (led.history || []).map(h => `<div>L${h.level}: ${esc((h.features || []).join(", "))}</div>`).join("");
    return `<details class="sheet-sec"><summary><h3>⬆️ Build / Level-up</h3></summary>` +
      `<div class="meta" style="opacity:.75">${esc(led.class_id || clsTxt || "—")}` +
        (led.applied_through ? ` · built to ${led.applied_through}` : " · unbuilt") +
        (led.subclass ? ` · ${esc(led.subclass)}` : "") + `</div>` +
      (hist ? `<div class="meta" style="opacity:.8">${hist}</div>` : "") +
      `<div class="row"><input id="bld-class" placeholder="class id" value="${esc(led.class_id || "")}" style="max-width:120px">` +
      `<input id="bld-to" type="number" min="1" max="20" value="${(led.applied_through || 0) + 1}" style="width:52px" title="build TO level">` +
      `<button id="bld-plan" class="ghost" type="button">🧭 Plan</button>` +
      `<button id="bld-apply" class="primary" type="button">⬆ Apply</button></div>` +
      `<textarea id="bld-ch" spellcheck="false" title="choices JSON" placeholder='{"skills":[...],"subclass":"...","levels":{"4":{"ability":{"dex":2}}}}'` +
      ` style="width:100%;min-height:48px;font-size:.72rem">${esc(JSON.stringify(led.decisions || {}))}</textarea>` +
      `<div id="bld-out" class="meta" style="opacity:.85"></div></details>`;
  })() : "";

  const attackBlock = ((own || isDM) && (der.attack_profiles || []).length) ?
    (() => { const tg = state.tokens.filter(t => t.id !== tok.id);
      return `<details class="sheet-sec" open><summary><h3>Attacks <small style="opacity:.6">server-derived</small></h3></summary>` +
      der.attack_profiles.map(p =>
        `<div class="skrow"><span>⚔️ ${esc(p.name)}${p.versatile ? ` <small style="opacity:.5">(${p.grip})</small>` : ""}${p.gated ? ` <small title="requires attunement — bonuses inert">🔒</small>` : ""} <b>${sgn(p.to_hit)}</b> ` +
        `<small style="opacity:.6">${p.dmg}${p.dmg_bonus ? (p.dmg_bonus >= 0 ? "+" : "") + p.dmg_bonus : ""}${p.dmg_type ? " " + p.dmg_type : ""}` +
        `${p.extra_dmg ? " +" + p.extra_dmg + (p.extra_dmg_type ? " " + p.extra_dmg_type : "") : ""}` +
        `${p.range_ft ? " · " + p.range_ft + " ft" + (p.range_long_ft ? "/" + p.range_long_ft : "") : (p.reach_ft ? " · reach " + p.reach_ft + " ft" : "")}</small></span>` +
        (own ? `<select class="atk-adv"><option value="">—</option><option value="adv">adv</option><option value="dis">dis</option></select>` +
               `<select class="atk-slot"><option value="action">Action</option><option value="bonus">Bonus</option></select>` +
               `<select class="atk-tgt"><option value="">no target</option>${tg.map(t => `<option value="${t.id}">${esc(t.label)}</option>`).join("")}</select>` +
               `<button class="atk-go primary" data-id="${p.item_id}">Attack</button>` : "") + `</div>`).join("") +
      `</details>`; })() : "";
  let bookBlock = "";
  if (ch.has_spellbook || (spells && spells.length)){
    const slotLine = [];
    let maxSlot = 0;
    for (let l=1;l<=9;l++){ const d = slots[String(l)] || slots[l]; if (d && d.max>0){ maxSlot=l; slotLine.push(`<small>L${l} ${Math.max(0,d.max-d.used)}/${d.max}</small>`); } }
    const castable = new Set(ch.abilities || []);
    const spRows = spells.map(sp => {
      const atk = _pb(lvlv) + _smod(_ab(sp.ability));
      const dc = 8 + _pb(lvlv) + _smod(_ab(sp.ability));
      const registered = castable.has(sp.id);
      const taring = sp.targeting || "single";
      let btns = "";
      if (own){
        if (sp.cast === "attack") btns += `<button class="roll-sp" data-k="spell_attack" data-id="${sp.id}">Atk +${atk}</button>`;
        if (sp.cast === "save") btns += `<button class="roll-sp" data-k="spell_dc" data-id="${sp.id}">DC ${dc}</button>`;
        if (registered && (taring === "area" || taring === "point")){
          btns += `<small style="opacity:.6" title="Cast an area/point spell from the tactical map">🎯 map</small>`;
        } else if (registered){
          let sel = "";
          if (sp.level > 0 && maxSlot >= sp.level){
            const opts = []; for (let l=sp.level;l<=maxSlot;l++) opts.push(`<option value="${l}"${l===sp.level?" selected":""}>L${l}</option>`);
            sel = `<select class="cast-lvl" title="upcast slot level">${opts.join("")}</select>`;
          }
          btns += sel + `<button class="primary cast-ab" data-id="${sp.id}">${sp.level>0?"Cast ▸":"Use"}</button>`;
        } else {
          btns += `<button class="primary cast-sp" data-id="${sp.id}">${sp.level>0?"Cast ▸":"Use"}</button>`;
        }
      }
      return `<div class="sprow"><span>${sp.level>0?`<small>${sp.level}L</small>`:"<small>✨</small>"} ${esc(sp.name)}</span> <small style="opacity:.6">${esc(sp.school||"")}${sp.dmg?(" · "+esc(sp.dmg)):""}</small><span class="spbtns">${btns}</span></div>`;
    }).join("");
    bookBlock = `<details class="sheet-sec" open><summary><h3>📖 Spellbook ${slotLine.length?`<small style="opacity:.6"> · ${slotLine.join(" ")}</small>`:`<small style="opacity:.6"> · no slots</small>`}</h3></summary>${spRows||`<div class="meta" style="opacity:.6">No spells learned.</div>`}</details>`;
  }
  // D99: wallet + encumbrance + companions. Every number arrives pre-derived on
  // the sheet (der.wallet / der.encumbrance) — the client renders and issues only
  // authorised intents (DM grant/deduct, owner→member transfer); it NEVER sends a
  // balance. A "companion" is a token already visible to this viewer (owner or
  // controller = the same player, or bound to this character) — never a second
  // model, never a token the viewer is not allowed to see or on a hidden plane.
  const _wal = der.wallet || {};
  const _cur = _wal.currencies || [];
  const _coinOpts = _cur.map(c => `<option value="${c.id}">${c.id}</option>`).join("");
  const _coinStr = (_wal.coins || []).filter(c => c.count).map(c => `${c.count} ${c.id}`).join(" ") || "empty";
  const _legend = _cur.map(c => `${c.id}=${c.value_cp}cp`).join(" · ");
  const _memOpts = (state.room.members || []).filter(mm => mm.char && mm.char.id !== ch.id)
    .map(mm => `<option value="${mm.char.id}">${esc(mm.username)}</option>`).join("");
  const _walletBlock = `<details class="sheet-sec"><summary><h3>🪙 Wallet <small style="opacity:.6">${esc(_coinStr)}</small></h3></summary>
    <div class="meta" style="opacity:.7">Rates: ${esc(_legend)}</div>
    ${own ? `<div class="wlabel" style="margin-top:.4rem">Transfer to a room member</div>
      <div class="inv-row"><input class="money-amt" type="number" min="1" placeholder="amt" style="width:5rem">
      <select class="money-coin">${_coinOpts}</select>
      <select class="money-to">${_memOpts || '<option value="">(no one else)</option>'}</select>
      <button class="money-send ghost">Send ▸</button></div>` : ""}
    ${isDM ? `<div class="wlabel" style="margin-top:.4rem">DM · grant / deduct</div>
      <div class="inv-row"><input class="money-amt" type="number" min="1" placeholder="amt" style="width:5rem">
      <select class="money-coin">${_coinOpts}</select>
      <button class="money-grant primary">Grant</button>
      <button class="money-deduct ghost">Deduct</button></div>` : ""}</details>`;
  const _enc = der.encumbrance || {};
  const _pct = Math.max(0, Math.min(100, _enc.percent || 0));
  const _weightBlock = `<details class="sheet-sec"><summary><h3>⚖️ Encumbrance <small style="opacity:.6">${_enc.carried||0} / ${_enc.capacity||0} lb</small></h3></summary>
    <div class="hpbar"><div style="width:${_pct}%;${_enc.overloaded?"background:var(--red)":""}"></div></div>
    <div class="meta">${(_enc.carried||0)} of ${(_enc.capacity||0)} lb (${_enc.percent||0}%)${_enc.overloaded ? ' · <b style="color:var(--red)">OVERLOADED</b>' : ""}</div>
    <div class="meta" style="opacity:.55">Limit from effective Strength, size and worn carry-bonuses. Coins weigh ${( _enc.coin_weight||0.02 )} lb each. No movement penalty is applied yet.</div></details>`;
  const _ownerUid = tok.owner_user_id;
  const _rel = (t) => (_ownerUid && (t.owner_user_id === _ownerUid || t.controller_user_id === _ownerUid))
                     || (ch && t.character_id === ch.id) || (isDM && t.owner_user_id === _ownerUid);
  const _comp = (state.tokens || []).filter(t => t.id !== tok.id && _rel(t));
  const _memName = (uid) => { const mm = (state.room.members || []).find(x => x.user_id === uid); return mm ? mm.username : ""; };
  const _compRows = _comp.map(t => {
    const youOwn = t.owner_user_id === state.me.id, youCtl = t.controller_user_id === state.me.id;
    const badge = youOwn ? "yours" : (youCtl ? "you control" : (t.controller_user_id ? "led by " + esc(_memName(t.controller_user_id)) : "uncontrolled"));
    const mount = t.mount_token_id ? (state.tokens.find(x => x.id === t.mount_token_id) || {}).label : "";
    const ctlOpts = (state.room.members || []).map(mm => `<option value="${mm.user_id}"${(t.controller_user_id||0)===mm.user_id?" selected":""}>${esc(mm.username)}</option>`).join("");
    const mountOpts = `<option value="">on foot</option>` + (state.tokens||[]).filter(x => x.id !== t.id)
      .map(x => `<option value="${x.id}"${(t.mount_token_id||0)===x.id?" selected":""}>${esc(x.label||"token")}</option>`).join("");
    return `<div class="inv-row" data-cmp="${t.id}"><b>${esc(t.label||"Companion")}</b>
      <small style="opacity:.7"> · ${badge}${mount?` · rides ${esc(mount)}`:""}</small>
      <button class="cmp-goto ghost" data-id="${t.id}" title="Select on the map">📍</button>
      ${isDM ? `<select class="cmp-ctl" data-id="${t.id}" title="assign controller"><option value="">unled</option>${ctlOpts}</select>
      <select class="cmp-mount" data-id="${t.id}" title="mount">${mountOpts}</select>
      <button class="cmp-del ghost" data-id="${t.id}" title="remove">✕</button>` : ""}</div>`;
  }).join("");
  const _compBlock = `<details class="sheet-sec"><summary><h3>🐾 Companions <small style="opacity:.6">${_comp.length||0}</small></h3></summary>
    ${_compRows || `<div class="meta" style="opacity:.6">No companions bound to this sheet.</div>`}
    ${isDM ? `<div class="inv-row" style="margin-top:.3rem"><input id="cmp-name" placeholder="companion label" maxlength="32" style="flex:1">
      <button id="cmp-add" class="ghost">＋ Add for ${esc(ch.name||"")} ▸</button></div>
      <div class="meta" style="opacity:.5">Adds a token this player controls (owner). You can then assign a controller or a mount above. Only the DM may hand out control — a player can never seize another's companion.</div>` : ""}</details>`;
  body.innerHTML = spanRow + `
    <div class="hpbar"><div style="width:${Math.max(0,ch.hp/ch.max_hp*100)}%;${ch.hp/ch.max_hp<=.25?"background:var(--red)":""}"></div></div>
    <b>HP ${ch.hp}/${ch.max_hp}</b>${ch.temp_hp ? ` (+${ch.temp_hp} temp)` : ""} · AC ${ac} · Speed ${ch.speed} ft
    ${(der.speed_effective && der.speed_effective !== ch.speed) ? `<small style="opacity:.7"> (→ ${der.speed_effective} ft worn)</small>` : ""}${der.darkvision_ft ? ` · <span title="darkvision from equipped items">👁 ${der.darkvision_ft} ft</span>` : ""}
    ${der.prof_bonus != null ? `<div class="meta" style="opacity:.75">Initiative ${sgn(der.initiative)} · Proficiency ${sgn(der.prof_bonus)} · Hit dice ${Math.max(0,(ch.hit_dice_max||0)-(ch.hit_dice_spent||0))}/${ch.hit_dice_max||0}</div>` : ""}
    ${deathHtml(tok)}
    ${hpStatesHtml(tok, ch, own || isDM)}
    <div class="statline">${STATS.map(([k,l]) =>
      `<div class="stat"><small>${l}</small>${v(ch.stats,k)} <small>${der.stat_mods ? sgn(der.stat_mods[k]) : mod(v(ch.stats,k))}</small></div>`).join("")}</div>
    ${conditionsHtml(tok)}
    ${defenseHtml(ch.defenses)}
    ${inv.length ? `<div class="inv"><div class="wlabel">Inventory <small style="opacity:.6">(attuned ${(ch.items||[]).filter(x=>x.attunable&&x.attuned).length}/${der.attune_max || 3})</small></div>${invRows}</div>` : ""}
    ${attackBlock}${skillBlock}${saveBlock}${bookBlock}${buildBlock}
    ${_walletBlock}${_weightBlock}${_compBlock}
    <details><summary style="cursor:pointer;font-size:.8rem;opacity:.7">Notes</summary><div style="white-space:pre-wrap;font-size:.82rem">${esc(ch.notes)}</div></details>`;
  for (const b of body.querySelectorAll(".inv-btns button")) b.onclick = () => {
    const id = b.dataset.id;
    if (b.dataset.a === "use") wsSend({ type:"use_item", token_id: tok.id, item_id: id, op_id: invOpId() });
    else if (b.dataset.a === "grip") wsSend({ type:"inv_grip", char_id: ch.id, item_id: id, grip: b.dataset.grip, op_id: invOpId() });
    else if (b.dataset.a === "attune") wsSend({ type:"attune", char_id: ch.id, item_id: id });
    else if (b.dataset.a === "identify") wsSend({ type:"identify", char_id: ch.id, item_id: id });
    else if (b.dataset.a === "recharge") wsSend({ type:"recharge", char_id: ch.id, item_id: id });
  };
  // D99 wiring — money (authorised intents only) + companion controls (reuse the
  // existing token_controller / token_mount / del_token / add_token handlers).
  const _money = (action, row, extra) => {
    const a = parseFloat(row.querySelector(".money-amt").value);
    if (!(a > 0)) { toast("Enter an amount"); return; }
    const msg = { type:"inv_money", action, char_id: ch.id, amount: a,
                  coin: row.querySelector(".money-coin").value, op_id: invOpId() };
    if (extra) Object.assign(msg, extra);
    wsSend(msg);
  };
  for (const b of body.querySelectorAll(".money-send")) b.onclick = () => {
    const to = +b.closest(".inv-row").querySelector(".money-to").value || -1;
    _money("transfer", b.closest(".inv-row"), { to_char_id: to });
  };
  for (const b of body.querySelectorAll(".money-grant")) b.onclick = () => _money("grant", b.closest(".inv-row"));
  for (const b of body.querySelectorAll(".money-deduct")) b.onclick = () => _money("deduct", b.closest(".inv-row"));
  for (const b of body.querySelectorAll(".cmp-goto")) b.onclick = () => {
    const t = (state.tokens || []).find(x => x.id === +b.dataset.id); if (t) renderSheet(t); };
  for (const b of body.querySelectorAll(".cmp-ctl")) b.onchange = () =>
    wsSend({ type:"token_controller", token_id:+b.dataset.id, controller_id:(+b.value)||null });
  for (const b of body.querySelectorAll(".cmp-mount")) b.onchange = () =>
    wsSend({ type:"token_mount", token_id:+b.dataset.id, mount_id:(+b.value)||null });
  for (const b of body.querySelectorAll(".cmp-del")) b.onclick = () => {
    if (confirm("Remove this companion?")) wsSend({ type:"del_token", token_id:+b.dataset.id }); };
  const _ca = $("cmp-add");
  if (_ca) _ca.onclick = () => {
    const name = ($("cmp-name") && $("cmp-name").value || "Companion").slice(0, 32);
    wsSend({ type:"add_token", label:name, owner_user_id:_ownerUid || null, size:"Small",
             x:(tok.x||400)+40, y:(tok.y||300)+40 });
  };
  const _vis = () => ($("sr-vis") && $("sr-vis").value) || "public";
  for (const b of body.querySelectorAll(".sk-roll")) b.onclick = () => wsSend({ type:"roll", kind:"skill", skill: b.dataset.skill, visibility:_vis(), adv: ($("sr-adv") && $("sr-adv").value) || null });
  for (const b of body.querySelectorAll(".roll-sp")) b.onclick = () => wsSend({ type:"roll", kind: b.dataset.k, spell_id: b.dataset.id, crit: b.dataset.crit === "1", visibility:_vis(), adv: ($("sr-adv") && $("sr-adv").value) || null });
  for (const b of body.querySelectorAll(".cast-sp")) b.onclick = () => wsSend({ type:"cast", spell_id: b.dataset.id, visibility:_vis(), adv: ($("sr-adv") && $("sr-adv").value) || null, op_id: invOpId() });
  for (const b of body.querySelectorAll(".cast-ab")) b.onclick = () => {
    const sel = b.closest(".spbtns") && b.closest(".spbtns").querySelector(".cast-lvl");
    const msg = { type:"ability_cast", token_id: tok.id, ability_id: b.dataset.id, op_id: invOpId() };
    if (sel && sel.value) msg.cast_level = +sel.value;
    wsSend(msg);
  };
  for (const b of body.querySelectorAll(".sv-roll")) b.onclick = () => wsSend({ type:"roll", kind:"save", ability: b.dataset.ab, visibility:_vis(), adv: ($("sr-adv") && $("sr-adv").value) || null });
  for (const b of body.querySelectorAll(".atk-go")) b.onclick = () => {
    const row = b.closest(".skrow");
    wsSend({ type:"roll", kind:"attack", item_id: b.dataset.id, token_id: tok.id,
             target_id: row.querySelector(".atk-tgt").value || null,
             adv: row.querySelector(".atk-adv").value || null,
             slot: row.querySelector(".atk-slot").value,
             visibility:_vis(), op_id: invOpId() });
  };
  const _bld = () => { const c = $("bld-class"); return c ? { cls: c.value, to: +$("bld-to").value, raw: $("bld-ch").value } : null; };
  const bp = $("bld-plan");
  if (bp) bp.onclick = async () => { const b = _bld(), out = $("bld-out"); if (!b) return;
    try { const p = await api(`/build/${state.room.code}/${ch.id}/plan?class_id=${encodeURIComponent(b.cls)}&to=${b.to}`);
      const n = p.needs || {}, hints = [];
      if (n.skills) hints.push(`skills ${n.skill_count}/${n.skill_options.length}: ${n.skill_options.join(", ")}`);
      if (n.subclass) hints.push(`subclass: ${(p.subclass_options || []).join(", ")}`);
      if (Object.keys(n.levels || {}).length) hints.push(`level choices: ${Object.keys(n.levels).join(", ")}`);
      if (n.spell) hints.push(`${n.spell.model} caster — choose at spell levels e.g. {"levels":{"${n.spell.first}":{"cantrips":["${(n.spell.pool_cantrips||[])[0]||"id"}"],"spells":["${(n.spell.pool_spells||[])[0]||"id"}"]}}}`);
      out.innerHTML = (p.ok ? `<span style="color:#9d9">plan ok · ${p.levels.length} levels</span>`
                            : `<span style="color:#e74c3c">${esc((p.errors || []).join(", "))}</span>`)
                  + (hints.length ? `<br>need: ${esc(hints.join(" | "))}` : "");
    } catch (e) { out.textContent = e.message; } };
  const ba = $("bld-apply");
  if (ba) ba.onclick = async () => { const b = _bld(), out = $("bld-out"); if (!b) return;
    let choices = {}; try { choices = b.raw ? JSON.parse(b.raw) : {}; } catch (e) { out.textContent = "choices JSON: " + e.message; return; }
    try { const r = await fetch(`/api/build/${state.room.code}/${ch.id}/apply`,
          { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ class_id: b.cls, to: b.to, choices }) });
      const j = await r.json();
      // D101 bug fix: refreshRoom() alone re-fetched the state but never RE-RENDERED
      // the open sheet — the panel kept showing "unbuilt" + old skills until a full
      // browser reload. Same re-render the snapshot WS handler does (40_ws.js).
      if (j.ok) { toast("Built to level " + j.result.level); await refreshRoom();
        if (state.sel) renderSheet(state.tokens.find(t => t.id === state.sel) || null); }
      else if (j.needs_choice) out.innerHTML = `<span style="color:#f1c40f">choices still needed</span><br><small>${esc(JSON.stringify(j.needs_choice))}</small>`;
      else out.innerHTML = `<span style="color:#e74c3c">${esc(j.error || j.reason || "refused")}</span>`;
    } catch (e) { out.textContent = e.message; } };
  wireConditions(tok);
  wireHpStates(tok);
  wireDeath(tok);
  wireSpanRow(tok);
  wireVisualRow(tok); wireArtRow(tok); wireFloorRow(tok); wireLightRow(tok);
  wireRotRow(tok); wireMoveModeRow(tok);
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
  body.innerHTML = _spanRowHtml(tok) + _visualRowHtml(tok) + _artRowHtml(tok) + _floorRowHtml(tok) + _lightRowHtml(tok) + _rotRowHtml(tok) + _moveModeRowHtml(tok) + `
    <div class="row"><input id="npc-name" placeholder="NPC name" value="${esc(tok.label)}" maxlength="32">
      <select id="npc-size">${["Tiny","Small","Medium","Large","Huge","Gargantuan"].map(s => `<option value="${s}" ${(tok.size||"Medium")===s?"selected":""}>${s}</option>`).join("")}</select>
      <select id="npc-disp"><option value="">neutral</option>${["friend","neutral","hostile"].map(d => `<option value="${d}" ${(tok.disposition||"")===d?"selected":""}>${d}</option>`).join("")}</select>
    </div>
    <div class="row"><select id="npc-controller" title="D82: this room member may act through this token (move, its turn, cast). DM always keeps full authority; revocable any time. NOT ownership, NOT an account." style="max-width:100%">
      <option value="0">Controlled by: —</option>
      ${state.room.members.map(x => `<option value="${x.user_id}" ${(tok.controller_user_id||0)===x.user_id?"selected":""}>led by ${esc(x.username)}</option>`).join("")}
    </select></div>
    <div class="row"><select id="npc-mount" title="D82: this token rides the selected token (rider→mount, acyclic, same room). Carrying movement is not yet automated — see docs." style="max-width:100%">
      <option value="0">Mounted on: —</option>
      ${state.tokens.filter(x => x.id !== tok.id).map(x => `<option value="${x.id}" ${(tok.mount_token_id||0)===x.id?"selected":""}>rides ${esc(x.label)}</option>`).join("")}
    </select></div>
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
    <div class="row"><button id="npc-inventory" title="Manage this creature's carried gear (lives on the server, players never see it while it stands)">🎒 Inventory</button>
      <button id="npc-loot" title="Take gear from this fallen creature" class="${(n.hp||0) > 0 ? "hidden" : ""}">💰 Loot</button></div>
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
  $("npc-inventory").onclick = () => openNpcChest(tok.id);
  const _nl = $("npc-loot"); if (_nl) _nl.onclick = () => openLootChest(tok.id);
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
  const ctl = $("npc-controller");
  if (ctl) ctl.onchange = () => wsSend({ type:"token_controller", token_id: tok.id,
                                         controller_id: (+ctl.value) || null });
  const mnt = $("npc-mount");
  if (mnt) mnt.onchange = () => wsSend({ type:"token_mount", token_id: tok.id,
                                         mount_id: (+mnt.value) || null });
  $("npc-to-best").onclick = () => saveNpcToBestiary(n, ($("npc-name").value || "NPC").slice(0,32), tok);
  wireSpanRow(tok);
  wireVisualRow(tok); wireArtRow(tok); wireFloorRow(tok); wireLightRow(tok);
  wireRotRow(tok); wireMoveModeRow(tok);
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
    const anchor = c.until === "start" ? "→turn start" : c.until === "end" ? "→turn end" : "";
    const dur = c.rounds ? ` <small>(${c.rounds}${anchor || "r"})</small>` : "";
    const rm = editable ? `<button class="cond-rm" data-k="${esc(c.k)}" title="Remove">✕</button>` : "";
    return `<span class="cond-chip"><i style="background:${condColor(c.k)}"></i>${esc(condLabel(c.k))}${dur}${rm}</span>`;
  }).join("");
  const list = Object.entries(CONDITIONS).map(([k, v]) => `<option value="${k}">${v[0]}</option>`).join("");
  const editor = editable ? `<div class="row cond-add"><input id="cond-name" list="cond-list" placeholder="condition…" style="flex:1">` +
    `<datalist id="cond-list">${list}</datalist>` +
    `<input id="cond-rounds" type="number" min="0" max="999" placeholder="∞" title="rounds (blank = until removed)" style="width:52px">` +
    `<select id="cond-until" title="timed conditions count down once per round, or per your own turn (D80)" style="width:92px">` +
    `<option value="">round end</option><option value="start">my turn start</option><option value="end">my turn end</option></select>` +
    `<button id="cond-add" class="primary">＋</button></div>` : "";
  const prone = conds.some(c => String(c.k).toLowerCase() === "prone");
  const stand = (own || isDM) && prone
    ? `<div class="row"><button id="cond-stand" class="primary">Stand Up</button>` +
      `<span class="meta" style="opacity:.6">costs half your movement in combat</span></div>` : "";
  return `<div class="conds"><div class="wlabel">Conditions</div>` +
    (conds.length ? `<div class="cond-chips">${chips}</div>` : `<div class="meta" style="opacity:.6">None</div>`) +
    stand + editor + `</div>`;
}

function wireConditions(tok){
  const body = $("sheet-body"); if (!body) return;
  for (const b of body.querySelectorAll(".cond-rm"))
    b.onclick = () => wsSend({ type:"cond_remove", token_id: tok.id, key: b.dataset.k });
  const st = $("cond-stand");
  if (st) st.onclick = () => wsSend({ type:"stand", token_id: tok.id });
  const add = $("cond-add");
  if (add) add.onclick = () => {
    const k = ($("cond-name").value || "").trim(); if (!k) return;
    const r = parseInt($("cond-rounds").value, 10);
    wsSend({ type:"cond_add", token_id: tok.id, key:k, rounds: isNaN(r) ? 0 : Math.max(0, Math.min(999, r)),
             until: ($("cond-until") || {}).value || "" });
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
  for (const b of body.querySelectorAll(".res-btn")) b.onclick = () => wsSend({ type:"resource", token_id: tok.id, resource_id:b.dataset.id, action:b.dataset.a, op_id: invOpId() });
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

/* ---------- inventory / equipment / containers (D92) ---------- */
const INV_SLOTS = [["main_hand","Main hand"],["off_hand","Off hand"],["armor","Armor"],
                   ["acc1","Accessory 1"],["acc2","Accessory 2"],["acc3","Accessory 3"]];
const INV_KINDS = ["other","weapon","armor","shield","potion","scroll","wand","staff","ring",
                   "tool","wondrous","spellbook"];

function invOpId(){ return "op" + Date.now().toString(36) + Math.random().toString(36).slice(2,8); }

function setSideTab(tab){
  localStorage.setItem(sideTabKey(), tab); applySideTab();
}

function invTargetChar(){
  const isDM = state.room && state.room.role === "dm";
  if (isDM){
    const sel = $("inv-char");
    if (!sel) return null;
    const m = state.room.members.find(x => x.char && String(x.char.id) === sel.value);
    return m ? m.char : null;
  }
  const m = state.room.members.find(x => x.user_id === state.me.id);
  return m && m.char;
}

function renderInv(){
  const box = $("inv");
  if (!box || !state.room) return;
  const isDM = state.room.role === "dm";
  const row = $("inv-charrow");
  if (row) row.classList.toggle("hidden", !isDM);
  if (isDM){
    const sel = $("inv-char"), pool = state.room.members.filter(x => x.char);
    if (sel){
      const keep = sel.value;
      sel.innerHTML = pool.map(m => `<option value="${m.char.id}">${esc(m.char.name)} (${esc(m.username)})</option>`).join("")
                     || "<option value=''>no characters</option>";
      if (pool.some(m => String(m.char.id) === keep)) sel.value = keep;
      sel.onchange = renderInv;
    }
  }
  const ch = invTargetChar();
  const dmBox = $("inv-dm");
  if (dmBox) dmBox.classList.toggle("hidden", !isDM || !ch);
  const who = $("inv-who");
  if (who) who.textContent = ch ? "— " + ch.name : "";
  const eq = $("inv-equip"), items = $("inv-items");
  if (!ch){
    if (eq) eq.innerHTML = "";
    if (items) items.innerHTML = `<div class="meta">${isDM ? "Pick a character to manage." : "No character yet."}</div>`;
    renderInvChest(); wireInvStatic(); return;
  }
  const inv = ch.items || [], equip = ch.equipment || {};
  const slotOpt = sel => INV_SLOTS.map(s => `<option value="${s[0]}">${sel && s[1] ? "" : ""}${s[1]}</option>`).join("");
  if (eq){
    eq.innerHTML = `<div class="inv-eq">${INV_SLOTS.map(s => {
      const it = inv.find(i => i.id === equip[s[0]]);
      return `<div class="row eq-row"><span class="eq-lab">${s[1]}</span>` +
        (it ? `<span>${ITEM_ICONS[it.kind] || "🎒"} ${esc(it.name)}</span>` +
              `<button data-uneq="${s[0]}">Unequip</button>` : `<span class="meta">—</span>`) + `</div>`;
    }).join("")}</div>`;
    eq.querySelectorAll("button[data-uneq]").forEach(b => b.onclick = () =>
      wsSend({ type: "inv_equip", char_id: ch.id, slot: b.dataset.uneq, item_id: null,
               op_id: invOpId() }));
  }
  if (items){
    items.innerHTML = inv.map(it => {
      const known = !it.unidentified;
      const btns = [];
      btns.push(`<select data-slot="${it.id}" title="equip into">${slotOpt(true)}</select>` +
                `<button data-a="equip" data-id="${it.id}">Equip</button>`);
      if (it.stackable && it.qty > 1 && state.invSplit !== it.id)
        btns.push(`<button data-a="split" data-id="${it.id}">Split</button>`);
      if (it.stackable && it.qty > 1 && state.invSplit === it.id)
        btns.push(`<input id="split-q" type="number" min="1" max="${it.qty - 1}" value="1" style="width:52px">` +
                  `<button data-a="splitgo" data-id="${it.id}">Go</button>` +
                  `<button data-a="splitcancel">✕</button>`);
      if (it.stackable)
        btns.push(`<button data-a="combine" data-id="${it.id}" ${state.invCombine === it.id ? "class='active'" : ""}>${state.invCombine === it.id ? "pick other" : "Combine"}</button>`);
      if (isDM) btns.push(`<button data-a="remove" data-id="${it.id}" style="color:var(--red)">Remove</button>`);
      // D106: curse controls are DM-only UI over DM-only data; the sheet owner
      // gets no buttons here at all — the server decides what an owner sees.
      if (isDM && it.curse && it.curse.revealed)
        btns.push(`<button data-a="conceal" data-id="${it.id}">☠ conceal</button>`);
      if (isDM && it.curse && !it.curse.revealed)
        btns.push(`<button data-a="reveal" data-id="${it.id}">☠ reveal</button>`);
      if (isDM && it.curse && it.curse.whisper)
        btns.push(`<button data-a="whisper" data-id="${it.id}" title="whisper the stored curse text to the current owner">☠ whisper</button>`);
      if (isDM && it.curse)
        btns.push(`<button data-a="cursee" data-id="${it.id}">☠ edit</button>` +
                  `<button data-a="cursex" data-id="${it.id}" style="color:var(--red)">☠ ✕</button>`);
      if (isDM && !it.curse)
        btns.push(`<button data-a="cursee" data-id="${it.id}">☠ curse</button>`);
      // owner (revealed by the DM) and DM both see the released fields; the
      // whisper text only reaches its target through the private chat channel.
      const curse = it.curse ? "☠ " + esc(it.curse.name || "A curse") +
                    (it.curse.desc ? " — " + esc(it.curse.desc) : "") +
                    (isDM && it.curse.whisper ? " 📜" : "") : "";
      const sub = [known ? esc(it.desc || "") : "unidentified", curse,
                   it.weight ? it.weight + " lb" : ""].filter(Boolean).join(" · ");
      return `<div class="inv-row"><span class="inv-name">${ITEM_ICONS[it.kind] || "🎒"} ${esc(it.name)}${it.qty > 1 ? " ×" + it.qty : ""}</span>` +
        `<small style="opacity:.55"> ${sub}</small><span class="inv-btns">${btns.join("")}</span></div>`;
    }).join("") || `<div class="meta">Empty.</div>`;
    items.querySelectorAll("button[data-a]").forEach(b => b.onclick = () => {
      const id = b.dataset.id, a = b.dataset.a;
      if (a === "equip"){
        const slot = items.querySelector(`select[data-slot="${id}"]`)?.value || "main_hand";
        wsSend({ type: "inv_equip", char_id: ch.id, slot, item_id: id, op_id: invOpId() });
      } else if (a === "split"){ state.invSplit = id; renderInv(); }
      else if (a === "splitcancel"){ state.invSplit = null; renderInv(); }
      else if (a === "splitgo"){
        const q = +(($("split-q") || {}).value || 1);
        state.invSplit = null;
        wsSend({ type: "inv_adjust", char_id: ch.id, action: "split", item_id: id, qty: q, op_id: invOpId() });
      } else if (a === "combine"){
        if (!state.invCombine || state.invCombine === id){ state.invCombine = id; renderInv(); return; }
        const other = state.invCombine; state.invCombine = null;
        wsSend({ type: "inv_adjust", char_id: ch.id, action: "combine", item_id: id, other_id: other, op_id: invOpId() });
      } else if (a === "remove"){
        const it = inv.find(i => i.id === id);
        const q = window.confirm(`Remove ALL ${it ? it.qty : ""} × ${it ? it.name : ""}?`) ? (it ? it.qty : 1) : 0;
        if (q > 0) wsSend({ type: "inv_remove", char_id: ch.id, item_id: id, qty: q, op_id: invOpId() });
      } else if (a === "cursee" || a === "cursex" || a === "reveal" || a === "conceal" || a === "whisper"){
        // D106: every authority lives server-side; the client only names the
        // instance — never a recipient, never a disclosure truth of its own.
        if (a === "cursee") curseEdit({ char_id: ch.id }, inv.find(i => i.id === id) || { id });
        else if (a === "cursex"){
          if (window.confirm("Remove the curse from this item?"))
            wsSend({ type: "curse", action: "clear", char_id: ch.id, item_id: id, op_id: invOpId() });
        }
        else wsSend({ type: "curse", action: a, char_id: ch.id, item_id: id, op_id: invOpId() });
      }
    });
  }
  renderInvChest(); wireInvStatic();
}

function wireInvStatic(){
  const isDM = state.room && state.room.role === "dm";
  if (!isDM) return;
  const defs = state.itemDefs || [];
  const ds = $("inv-def");
  if (ds){
    const keep = ds.value;
    ds.innerHTML = defs.map(d => `<option value="${d.id}">${esc(d.name)} (${d.qty ? "" : d.stackable ? "stk" : "one"})</option>`).join("")
                   || "<option value=''>no definitions — create below</option>";
    if (defs.some(d => d.id === keep)) ds.value = keep;
  }
  const ks = $("inv-newkind");
  if (ks && !ks.options.length) ks.innerHTML = INV_KINDS.map(k => `<option>${k}</option>`).join("");
  const grant = $("inv-grant");
  if (grant) grant.onclick = () => {
    const ch = invTargetChar(); if (!ch) return;
    const qty = +(($("inv-qty") || {}).value || 1);
    const defId = (($("inv-def") || {}).value || "");
    if (!defId) { toast("Create an item definition first."); return; }
    wsSend({ type: "inv_grant", char_id: ch.id, def_id: defId, qty, op_id: invOpId() });
  };
  const _v = id => { const el = $(id); return el ? (el.value || "") : ""; };
  const _ck = id => !!($(id) && $(id).checked);
  const _num = id => { const el = $(id); if (!el || el.value === "") return null;
    const n = +el.value; return Number.isFinite(n) ? n : null; };
  function collectDef(){
    const name = _v("inv-newname").trim(); if (!name) return null;
    const props = {};
    const put = (k, val) => { if (val !== "" && val !== null && val !== false && !(Array.isArray(val) && !val.length)) props[k] = val; };
    put("damage_dice", _v("inv-newdmg").trim().toLowerCase());
    put("damage_dice_two_handed", _v("inv-newdmg2").trim().toLowerCase());
    if (_ck("inv-newvers")) props.versatile = true;
    if (_ck("inv-new2h")) props.two_handed = true;
    if (_ck("inv-newfin")) props.finesse = true;
    put("reach_ft", _num("inv-newreach"));
    put("range_ft", _num("inv-newrgn"));
    put("range_long_ft", _num("inv-newrgl"));
    const ab = _v("inv-newatab"); if (ab) { props.ability = ab; }
    if (_ck("inv-newprof")) props.proficient = true;
    put("attack_bonus", _num("inv-newatabonus"));
    put("damage_bonus", _num("inv-newdmbonus"));
    put("damage_type", _v("inv-newdtype"));
    put("extra_damage_dice", _v("inv-newextra").trim().toLowerCase());
    put("extra_damage_type", _v("inv-newextrat").trim().toLowerCase());
    put("ac_base", _num("inv-newacbase"));
    put("ac_bonus", _num("inv-newacbonus"));
    put("ac_max_dex", _num("inv-newacmaxdex"));
    put("attribute_bonus", _v("inv-newattrb").trim());
    put("attribute_set", _v("inv-newattrset").trim());
    put("darkvision_ft", _num("inv-newdark"));
    put("speed_bonus_ft", _num("inv-newspeed"));
    put("skill_prof", _v("inv-newskill").trim());
    put("expertise", _v("inv-newexpert").trim());
    put("save_prof", _v("inv-newsave").trim());
    put("charges", _num("inv-newcharges"));
    if (_ck("inv-newrecharge")) props.recharge = "long";
    if (_ck("inv-newmagic")) props.magic = true;
    if (_ck("inv-newattune")) props.attune = true;
    const defn = { name, kind: _v("inv-newkind") || "other",
      stackable: _ck("inv-newstack"), weight: +(_v("inv-newweight") || 0),
      desc: _v("inv-newdesc"), props };
    const eid = _v("inv-editid"); if (eid) defn.id = eid;
    return defn;
  }
  function clearDefForm(){
    ["inv-newname","inv-newdmg","inv-newdmg2","inv-newreach","inv-newrgn","inv-newrgl",
     "inv-newatabonus","inv-newdmbonus","inv-newextra","inv-newextrat","inv-newacbase",
     "inv-newacbonus","inv-newacmaxdex","inv-newattrb","inv-newattrset","inv-newdark",
     "inv-newspeed","inv-newskill","inv-newexpert","inv-newsave","inv-newcharges",
     "inv-newdesc","inv-editid"].forEach(id => { if ($(id)) $(id).value = ""; });
    ["inv-newvers","inv-new2h","inv-newfin","inv-newprof","inv-newrecharge","inv-newmagic",
     "inv-newattune","inv-newstack"].forEach(id => { if ($(id)) $(id).checked = false; });
    if ($("inv-newweight")) $("inv-newweight").value = "0";
    ["inv-newdtype","inv-newatab","inv-newkind"].forEach(id => { if ($(id)) $(id).selectedIndex = 0; });
  }
  function fillDefForm(d){
    clearDefForm();
    const setv = (id, v) => { if ($(id) && v != null) $(id).value = v; };
    const setck = (id, v) => { if ($(id)) $(id).checked = !!v; };
    const p = d.props || {};
    $("inv-editid").value = d.id || "";
    setv("inv-newname", d.name); setv("inv-newdesc", d.desc); setv("inv-newweight", d.weight);
    setv("inv-newkind", d.kind); if ($("inv-newkind")) $("inv-newkind").value = d.kind || "other";
    setck("inv-newstack", d.stackable);
    setv("inv-newdmg", p.damage_dice); setv("inv-newdmg2", p.damage_dice_two_handed);
    setck("inv-newvers", p.versatile); setck("inv-new2h", p.two_handed); setck("inv-newfin", p.finesse);
    setv("inv-newreach", p.reach_ft); setv("inv-newrgn", p.range_ft); setv("inv-newrgl", p.range_long_ft);
    if (p.ability && $("inv-newatab")) $("inv-newatab").value = p.ability;
    setck("inv-newprof", p.proficient);
    setv("inv-newatabonus", p.attack_bonus); setv("inv-newdmbonus", p.damage_bonus);
    if (p.damage_type && $("inv-newdtype")) $("inv-newdtype").value = p.damage_type;
    setv("inv-newextra", p.extra_damage_dice); setv("inv-newextrat", p.extra_damage_type);
    setv("inv-newacbase", p.ac_base); setv("inv-newacbonus", p.ac_bonus); setv("inv-newacmaxdex", p.ac_max_dex);
    if (p.attribute_bonus) setv("inv-newattrb", Object.entries(p.attribute_bonus).map(([a, b]) => a + (b >= 0 ? "+" : "") + b).join(","));
    if (p.attribute_set) setv("inv-newattrset", p.attribute_set.ability + "," + p.attribute_set.value);
    setv("inv-newdark", p.darkvision_ft); setv("inv-newspeed", p.speed_bonus_ft);
    if (Array.isArray(p.skill_prof)) setv("inv-newskill", p.skill_prof.join(","));
    if (Array.isArray(p.expertise)) setv("inv-newexpert", p.expertise.join(","));
    if (Array.isArray(p.save_prof)) setv("inv-newsave", p.save_prof.join(","));
    setv("inv-newcharges", p.charges); setck("inv-newrecharge", p.recharge === "long");
    setck("inv-newmagic", p.magic); setck("inv-newattune", p.attune);
    const ed = $("inv-defeditor"); if (ed) ed.open = true;
  }
  const save = $("inv-mkdef");
  if (save) save.onclick = () => {
    const defn = collectDef();
    if (!defn) { toast("Name it first."); return; }
    wsSend({ type: "item_def", action: defn.id ? "update" : "create", defn, op_id: invOpId() });
  };
  const nc = $("inv-newclear");
  if (nc) nc.onclick = clearDefForm;
  const ld = $("inv-loaddef");
  if (ld) ld.onclick = () => {
    const id = ($("inv-def") || {}).value || "";
    const d = (state.itemDefs || []).find(x => x.id === id);
    if (!d) { toast("Pick a definition to edit."); return; }
    fillDefForm(d);
  };
}

/* D106: DM curse administration for one concrete item instance. Three small
   channels ride the ONE "curse" transport: set/clear (metadata), reveal/conceal
   (disclosure to the current owner) and whisper (private delivery, recipient
   resolved server-side). The editor is intentionally prompt-based to match the
   inventory panel's minimal style; all truth is authored by the server reply
   "curse_updated", never by what was typed in. */
function curseEdit(scope, it){
  const c = it.curse || {};
  const name = window.prompt("Curse name (DM only)", c.name || "");
  if (name === null) return;
  const desc = window.prompt("Secret description (DM only — players never see this until revealed)", c.desc || "");
  if (desc === null) return;
  const whisper = window.prompt("Whisper text for the owner (stays secret, delivered only via \"☠ whisper\")", c.whisper || "");
  if (whisper === null) return;
  if (!name && !desc && !whisper){ toast("Give the curse a name, a description or a whisper text."); return; }
  wsSend({ type: "curse", action: "set", ...scope, item_id: it.id,
           name, desc, whisper, op_id: invOpId() });
}

function applyCurseUpdate(p){
  // DM-only authoritative patch: the server tells us the stored truth for
  // exactly this instance; local panels render THAT, so they can never drift
  // ahead of (or behind) the stored metadata.
  let items = null;
  if (p.char_id != null){
    const m = ((state.room && state.room.members) || []).find(
      x => x.char && String(x.char.id) === String(p.char_id));
    items = m && m.char.items;
  } else if (state.invChest && String(state.invChest.object_id) === String(p.object_id)){
    items = state.invChest.items;
  }
  const it = (items || []).find(i => String(i.id) === String(p.item_id));
  if (it){ if (p.curse) it.curse = p.curse; else delete it.curse; }
  renderInv();
}

function openInvContainer(ob){  state.invChest = { object_id: ob.id, label: ob.label || "Container",
                     floor: state.viewFloor || "", items: [], coins: 0, loading: true };
  setSideTab("inv"); renderInvChest();
  wsSend({ type: "inv_container", action: "inspect", object_id: ob.id, floor: state.viewFloor || "" });
}

function showInvContents(p){
  // p.npc_token marks a D105 NPC container ("tok:<id>"); the source (who may
  // do WHAT with it — world chest vs DM manage vs looting) was decided at
  // open time and survives the server reply.
  const prev = state.invChest && state.invChest.object_id === p.object_id ? state.invChest : null;
  state.invChest = { object_id: p.object_id, label: p.label || "Container",
                     floor: p.floor || "", items: p.items || [], coins: p.coins || 0,
                     token_id: p.npc_token != null ? p.npc_token : (prev && prev.token_id) || null,
                     src: p.npc_token != null ? ((prev && prev.src) || "loot") : "chest" };
  setSideTab("inv"); renderInvChest();
}
/* D105: open the same chest panel for an NPC container. Inventory management
   (src npc) is DM-only server-side; looting (src loot) works for anyone who
   stands next to the body — the server says "It isn't here." while it stands. */
function openNpcChest(tokId){
  const tok = state.tokens.find(t => t.id === tokId);
  state.invChest = { object_id: "tok:" + tokId, token_id: tokId, src: "npc",
                     label: ((tok && tok.label) || "NPC"), floor: (tok && tok.floor) || "",
                     items: [], coins: 0, loading: true };
  setSideTab("inv"); renderInvChest();
  wsSend({ type: "npc_inv", action: "inspect", token_id: tokId });
}
function openLootChest(tokId){
  const tok = state.tokens.find(t => t.id === tokId);
  state.invChest = { object_id: "tok:" + tokId, token_id: tokId, src: "loot",
                     label: ((tok && tok.label) || "Fallen creature"), floor: (tok && tok.floor) || "",
                     items: [], coins: 0, loading: true };
  setSideTab("inv"); renderInvChest();
  wsSend({ type: "loot", action: "inspect", token_id: tokId });
}

function renderInvChest(){
  const box = $("inv-chest");
  if (!box) return;
  const cs = state.invChest;
  if (!cs){ box.classList.add("hidden"); box.innerHTML = ""; return; }
  box.classList.remove("hidden");
  const isDM = state.room && state.room.role === "dm";
  const ch = invTargetChar();
  const src = cs.src || "chest";
  const _dst = src === "chest" ? { type: "inv_container", object_id: cs.object_id, floor: cs.floor }
                               : { type: src === "npc" ? "npc_inv" : "loot", token_id: cs.token_id };
  // D106: DM curse authoring also works on world chests and NPC carcasses;
  // reveal/whisper are deliberately NOT offered here — they need a player
  // owner, which a container does not have (the server enforces the same).
  const _curseScope = src === "chest" ? { object_id: cs.object_id, floor: cs.floor }
                                      : { token_id: cs.token_id };
  const rows = (cs.items || []).map(it =>
    `<div class="inv-row"><span class="inv-name">${ITEM_ICONS[it.kind] || "🎒"} ${esc(it.name)} ×${it.qty}</span>` +
    `<small style="opacity:.55"> ${[esc(it.desc || ""),
      (isDM && it.curse) ? "☠ " + esc(it.curse.name || "a curse") + (it.curse.whisper ? " 📜" : "") : ""
    ].filter(Boolean).join(" · ")}</small><span class="inv-btns">` +
    (src === "npc" ? "" :
      `<input id="tk-q-${it.id}" type="number" min="1" max="${it.qty}" value="1" style="width:52px">` +
      `<button data-tk="${it.id}" ${ch ? "" : "disabled"}>${src === "loot" ? "Loot" : "Take"}</button>`) +
    (isDM ? `<button data-ce="${it.id}">${it.curse ? "☠ edit" : "☠ curse"}</button>` +
            (it.curse ? `<button data-cx="${it.id}" style="color:var(--red)">☠ ✕</button>` : "") : "") +
    (isDM && src !== "loot" ? `<button data-rm="${it.id}" style="color:var(--red)">Remove</button>` : "") +
    `</span></div>`).join("") || `<div class="meta">${cs.loading ? "opening…" : (src === "loot" ? "Nothing to loot." : "Empty.")}</div>`;
  const own = (ch && ch.items || []).filter(i => !i.unidentified);
  const _coinOpts = ["cp", "sp", "ep", "gp", "pp"].map(c => `<option value="${c}">${c}</option>`).join("");
  const _coinCtl = `<input id="coin-amt" type="number" min="1" value="1" style="width:60px"><select id="coin-sel">${_coinOpts}</select>`;
  const _coinRow = (cs.coins > 0)
    ? `<div class="inv-row"><span class="inv-name">🪙 <b>${cs.coins} cp</b></span><span class="inv-btns">${_coinCtl}` +
      (src === "npc" ? (isDM ? `<button id="coin-out" title="Take coin out (gone from this container)">Remove</button><button id="coin-fill">Add</button>` : "") :
        `<button id="coin-take" ${ch ? "" : "disabled"}>${src === "loot" ? "Loot" : "Take"}</button>` +
        (isDM && src === "chest" ? `<button id="coin-fill">Add</button>` : "")) + `</span></div>`
    : (isDM && src !== "loot" ? `<div class="inv-row"><span class="inv-name"><small style="opacity:.6">🪙 no coin — </small></span><span class="inv-btns">${_coinCtl}<button id="coin-fill">Add coin</button></span></div>` : "");
  box.innerHTML = `<h3>📦 ${esc(cs.label)} <button id="chest-close" class="ghost" title="close">✕</button></h3>` +
    _coinRow + rows +
    (cs.loading || src === "loot" || !(isDM || src === "chest") ? "" : `<div class="row">` +
      (src === "chest" ? `<select id="put-item" title="take from this character's inventory">` +
        (own.map(i => `<option value="${i.id}">${esc(i.name)} ×${i.qty}</option>`).join("") || "<option value=''>nothing to put</option>") +
        `</select><input id="put-q" type="number" min="1" value="1" style="width:52px">` +
        `<button id="chest-put" ${ch && own.length ? "" : "disabled"}>Put</button>` : "") +
      (isDM ? `<select id="fill-def" title="definition to put in">` +
        ((state.itemDefs || []).map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join("") || "<option value=''>no defs</option>") +
        `</select><input id="fill-q" type="number" min="1" value="1" style="width:52px"><button id="chest-fill">Fill</button>` : "") +
      `</div>`);
  const cl = $("chest-close");
  if (cl) cl.onclick = () => { state.invChest = null; renderInvChest(); };
  box.querySelectorAll("button[data-tk]").forEach(b => b.onclick = () => {
    const q = +(($("tk-q-" + b.dataset.tk) || {}).value || 1);
    wsSend({ ..._dst, action: src === "loot" ? "take" : "move", char_id: ch.id,
             item_id: b.dataset.tk, qty: q, op_id: invOpId() });
  });
  box.querySelectorAll("button[data-rm]").forEach(b => b.onclick = () => {
    wsSend({ ..._dst, action: "remove", item_id: b.dataset.rm, qty: 9999, op_id: invOpId() });
  });
  box.querySelectorAll("button[data-ce]").forEach(b => b.onclick = () =>
    curseEdit(_curseScope, (cs.items || []).find(i => String(i.id) === b.dataset.ce) || { id: b.dataset.ce }));
  box.querySelectorAll("button[data-cx]").forEach(b => b.onclick = () => {
    if (window.confirm("Remove the curse from this item?"))
      wsSend({ type: "curse", action: "clear", ..._curseScope, item_id: b.dataset.cx, op_id: invOpId() });
  });
  const put = $("chest-put");
  if (put) put.onclick = () => {
    const id = (($("put-item") || {}).value || ""); if (!id) return;
    wsSend({ type: "inv_container", action: "move", object_id: cs.object_id, floor: cs.floor,
             char_id: ch.id, item_id: id, qty: +(($("put-q") || {}).value || 1), op_id: invOpId() });
  };
  const fill = $("chest-fill");
  if (fill) fill.onclick = () => {
    const id = (($("fill-def") || {}).value || ""); if (!id) return;
    wsSend({ ..._dst, action: "fill", def_id: id, qty: +(($("fill-q") || {}).value || 1), op_id: invOpId() });
  };
  const _coin = (action) => wsSend({ ..._dst, action, char_id: ch && ch.id,
    amount: +(($("coin-amt") || {}).value || 1),
    coin: (($("coin-sel") || {}).value || "cp"), op_id: invOpId() });
  const ct = $("coin-take"); if (ct) ct.onclick = () => _coin("coins_take");
  const cf = $("coin-fill"); if (cf) cf.onclick = () => _coin("coins_fill");
  const co = $("coin-out"); if (co) co.onclick = () => _coin("coins_remove");
}
