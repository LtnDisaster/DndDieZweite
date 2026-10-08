/* ---------- wiring ---------- */
(typeof window !== "undefined") && ((window.__BUILDS = window.__BUILDS || {})["60_main.js"] = window.__BUILD__ || "?");
/* ---------- chat / narration / ambience wiring ---------- */
function resolveChatTargetName(name){
  const needle = String(name || "").trim().toLowerCase();
  const member = ((state.room && state.room.members) || [])
    .find(m => m.user_id !== (state.me && state.me.id) &&
               (String(m.username || "").toLowerCase() === needle ||
                String(m.char && m.char.name || "").toLowerCase() === needle));
  return member ? member.user_id : null;
}
function parseChatCommand(raw){
  let channel = $("chat-channel") ? $("chat-channel").value : "global";
  let target = $("chat-target") && !$("chat-target").classList.contains("hidden") ? $("chat-target").value : "";
  let text = String(raw || "").trim();
  let m;
  if ((m = text.match(/^\/(?:w|whisper)\s+(\S+)\s+(.*)$/i))){
    const tid = resolveChatTargetName(m[1]);
    if (tid == null) return { error:"Unknown whisper recipient." };
    return { channel:"whisper", target:tid, text:m[2].trim() };
  }
  if ((m = text.match(/^\/dm\s+(.*)$/i))){
    return { channel:"dm", target, text:m[1].trim() };
  }
  if ((m = text.match(/^\/(?:g|global)\s+(.*)$/i))){
    return { channel:"global", target:null, text:m[1].trim() };
  }
  return { channel, target, text };
}
function chatPersonaPayload(prefix){
  if (!state.room || state.room.role !== "dm") return {};
  const sender = $(prefix + "-sender") ? $(prefix + "-sender").value : "user";
  const persona = $(prefix + "-persona") ? $(prefix + "-persona").value.trim() : "";
  const npc = $(prefix + "-npc") ? $(prefix + "-npc").value : "";
  if (sender === "npc") return { sender_kind:"npc", npc_token_id: npc || null };
  if (sender === "persona") return { sender_kind:"persona", persona };
  return {};
}
function syncPersonaControls(prefix){
  const sender = $(prefix + "-sender");
  if (!sender) return;
  const v = sender.value;
  $(prefix + "-persona").classList.toggle("hidden", v !== "persona");
  $(prefix + "-npc").classList.toggle("hidden", v !== "npc");
}
function sendChat(){
  const raw = $("chat-in").value.trim();
  if (!raw) return;
  const parsed = parseChatCommand(raw);
  if (parsed.error){ toast(parsed.error); return; }
  if (!parsed.text) return;
  const payload = { type:"chat", text:parsed.text, channel:parsed.channel,
                    recipient_id: parsed.target ? parseInt(parsed.target, 10) : null };
  Object.assign(payload, chatPersonaPayload("chat"));
  wsSend(payload);
  $("chat-in").value = "";
}
function sendNarrative(secret=false){
  const text = $("narr-text").value.trim();
  if (!text) return;
  const target = $("narr-target").value || "all";
  const style = $("narr-style").value || "overlay";
  const payload = { type: secret ? "secret_event" : "narrative", text, target, style };
  Object.assign(payload, chatPersonaPayload("narr"));
  if (secret){
    const sid = $("secret-sound").value;
    if (sid) payload.sound_id = parseInt(sid, 10);
  }
  wsSend(payload);
  $("narr-text").value = "";
  if (secret) $("secret-sound").value = "";
}
async function addSound(){
  const name = $("sound-name").value.trim();
  const url = $("sound-url").value.trim();
  if (!name || !url) return toast("Name and direct audio URL required");
  try {
    await api("/sounds", "POST", { name, url, category:"sfx" });
    $("sound-name").value = ""; $("sound-url").value = "";
    await loadSounds(); toast("Sound saved");
  } catch(e){ toast(e.message); }
}
function triggerAmbience(kind, extra={}){ wsSend({ type:kind, ...extra }); }
function updateMoveControls(){
  const b = $("btn-stop-move"); if (!b) return;
  b.classList.toggle("hidden", !(state.room && state.room.role === "dm" && state.sel && state.moving.has(state.sel)));
}

function wireRoomAtmosphere(){
  const toggle = $("toggle-chronicle");
  if (toggle) toggle.onclick = () => setChronicleOpen(!state.chatOpen);
  for (const id of ["chat-sender", "narr-sender"]){
    const el = $(id); if (el) el.onchange = () => syncPersonaControls(id.replace("-sender", ""));
  }
  const channel = $("chat-channel");
  if (channel) channel.onchange = syncChatTarget;
  const audioAdd = $("btn-audio-add");
  if (audioAdd) audioAdd.onclick = () => {
    const url = $("audio-url-in").value.trim();
    if (!url) return toast("Audio URL required");
    triggerAmbience("audio_add", { title:$("audio-title-in").value.trim(), url,
                                  category:$("audio-cat").value });
    $("audio-title-in").value = ""; $("audio-url-in").value = "";
  };
  const stop = $("btn-ambience-stop");
  if (stop) stop.onclick = () => triggerAmbience("audio_stop");
  const localPlay = $("btn-audio-play");
  if (localPlay) localPlay.onclick = () => setAudioPlayback();
  const mute = $("btn-audio-mute");
  if (mute) mute.onclick = () => {
    state.audio.local.muted = !state.audio.local.muted;
    saveAudioPrefs();
    setAudioPlayback();
  };
  const vol = $("audio-vol");
  if (vol){
    vol.oninput = () => {
      state.audio.local.volume = Math.max(0, Math.min(1, parseFloat(vol.value) || 0));
      if (state.audio.element) state.audio.element.volume = state.audio.local.volume;
      renderAudio();
    };
    vol.onchange = () => saveAudioPrefs();
  }
  const narr = $("btn-narrate");
  if (narr) narr.onclick = () => sendNarrative(false);
  const secret = $("btn-secret-event");
  if (secret) secret.onclick = () => sendNarrative(true);
  const soundAdd = $("btn-sound-add");
  if (soundAdd) soundAdd.onclick = () => addSound();
}

function wire(){
  const sf = $("ch-stats");
  sf.innerHTML = STATS.map(([k,l]) =>
    `<label>${l}<input id="st-${k}" type="number" min="1" max="30" value="10"></label>`).join("");
  const recalcBonusRows = () => { renderSkillRows(); renderSaveRows(); };
  for (const [k] of STATS) $("st-"+k).oninput = recalcBonusRows;
  $("ch-level").oninput = recalcBonusRows;

  $("btn-login").onclick = () => doAuth("/login");
  $("btn-register").onclick = () => doAuth("/register");
  $("btn-logout").onclick = async () => { await api("/logout","POST"); location.reload(); };
  $("btn-char-save").onclick = async () => {
    try {
      const p = charPayload();
      if (!p.name) return toast("Name required");
      if (state.charEdit) await api("/characters/"+state.charEdit, "PUT", p);
      else await api("/characters", "POST", p);
      $("char-editor").open = false; await loadLobby();
    } catch(e){ toast(e.message); }
  };
  $("btn-char-cancel").onclick = () => { $("char-editor").open = false; };
  $("btn-weap-add").onclick = () => {
    state.weaponRows.push({ name:"", ability:"str", proficient:false, dmg:"1d6", dmgBonus:0, magic:false });
    renderWeaponRows();
  };
  $("btn-item-add").onclick = () => {
    state.itemRows.push({ id:eid(), name:"", kind:"other", ac:0, light:false, acBonus:0,
                          heal:"", charges:-1, recharge:null, magic:false, attunable:false,
                          attuned:false, identified:true, desc:"" });
    renderItemRows();
  };
  $("btn-resource-add").onclick = () => {
    state.resourceRows = state.resourceRows || [];
    state.resourceRows.push({ id:eid(), name:"", current:1, max:1, reset:"long" });
    renderResourceRows();
  };
  $("btn-spell-add").onclick = () => {
    state.spellRows = state.spellRows || [];
    state.spellRows.push({ id:eid(), name:"", level:1, school:"", cast:"none", ability:"int",
                           dmg:"", save:"", range:"", duration:"" });
    renderSpellRows();
  };
  const summ = document.querySelector("#char-editor summary");
  if (summ) summ.onclick = () => { if (!$("char-editor").open) setTimeout(() => openCharForm(null), 0); };
  $("btn-room-create").onclick = async () => {
    try { const r = await api("/rooms","POST",{ name: $("rm-name").value.trim() || "Adventure" });
      $("rm-name").value=""; await openRoom(r.code); } catch(e){ err("lobby-err", e); }
  };
  $("btn-room-join").onclick = async () => {
    try { const r = await api("/rooms/join","POST",{ code: $("rm-code").value.trim() });
      $("rm-code").value=""; await openRoom(r.code); } catch(e){ err("lobby-err", e); }
  };
  $("btn-back").onclick = () => {
    clearTimeout(state.reconnectTimer);
    if (state.ws){ state.ws.onclose=null; state.ws.close(); state.ws=null; }
    state.room = null; editorClose(); loadLobby();
  };
  $("btn-chat").onclick = sendChat;
  $("chat-in").addEventListener("keydown", e => { if (e.key === "Enter") sendChat(); });
  const _withMod = (base) => {
    const raw = parseInt($("roll-mod") ? $("roll-mod").value : "", 10);
    const mod = Number.isFinite(raw) ? Math.max(-500, Math.min(500, raw)) : 0;
    return mod ? `${base}${mod > 0 ? "+" : ""}${mod}` : base;
  };
  const roll = (expr=null) => wsSend({ type:"roll", expr: _withMod(expr || $("roll-expr").value),
                              adv: $("roll-adv").value || null,
                              visibility: ($("roll-vis") && $("roll-vis").value) || "public",
                              ability: $("roll-abil") ? $("roll-abil").value || null : null,
                              prof: $("roll-prof") ? $("roll-prof").checked : false });
  $("btn-roll").onclick = () => roll();
  for (const b of document.querySelectorAll(".qd")) b.onclick = () => roll(b.dataset.expr);
  $("tab-chat").onclick = () => switchFeed("chat");
  $("tab-log").onclick = () => switchFeed("log");
  if ($("tab-dice")) $("tab-dice").onclick = () => switchFeed("dice");
  $("roll-expr").addEventListener("keydown", e => { if (e.key === "Enter") roll(); });
  $("mh-go").onclick = confirmPlan;
  $("mh-cancel").onclick = clearPlan;
  for (const b of $("dice-btns").querySelectorAll("button"))
    b.onclick = () => { $("roll-expr").value = "1"+b.dataset.d; roll(); };
  $("btn-init-start").onclick = () => wsSend({ type:"init_start" });
  $("btn-init-next").onclick = () => wsSend({ type:"init_next" });
  $("btn-init-round").onclick = () => wsSend({ type:"init_end_round" });
  $("btn-init-end").onclick = () => wsSend({ type:"init_end" });
  $("hp-dtype").innerHTML = `<option value="">untyped</option>` + DMG_TYPES.map(x => `<option value="${x}">${x}</option>`).join("");
  $("btn-hp-apply").onclick = () => { const v = parseInt($("hp-amount").value || "0", 10); if (v) hpDelta(v); };
  for (const b of $("hp-btns").querySelectorAll("button"))
    b.onclick = () => hpDelta(+b.dataset.hp);
  $("btn-npc-add").onclick = () => {
    const n = $("dm-npc-name").value.trim(); if (n){ wsSend({ type:"add_token", label:n }); $("dm-npc-name").value=""; }
  };
  $("btn-edit-map").onclick = () => { state.editing ? editorClose() : editorOpen(); };
  const osel = $("obj-op");                                    // D88/D89 op fields
  if (osel) osel.onchange = () => {
    const sf = $("obj-stair-fields"), lf = $("obj-lamp-fields");
    if (sf) sf.classList.toggle("hidden", osel.value !== "stair");
    if (lf) lf.classList.toggle("hidden", osel.value !== "lamp"); };
  $("btn-long-rest").onclick = () => wsSend({ type: "long_rest",
    clear_conditions: !!($("long-rest-conds") && $("long-rest-conds").checked) });
  $("btn-aoe").onclick = () => { state.aoeArmed = !state.aoeArmed;
    $("btn-aoe").classList.toggle("active", state.aoeArmed); };
  $("btn-ping").onclick = () => { state.pingArmed = !state.pingArmed;
    $("btn-ping").classList.toggle("active", state.pingArmed); };
  $("btn-ruler").onclick = () => {
    state.rulerArmed = !state.rulerArmed;
    if (!state.rulerArmed) state.ruler = null;
    $("btn-ruler").classList.toggle("active", state.rulerArmed);
    draw();
  };
  $("btn-stop-move").onclick = () => { if (state.sel) wsSend({ type:"stop_move", token_id: state.sel }); };
  $("view-tactical").onclick = () => setViewMode("tactical");
  $("view-diorama").onclick = () => setViewMode("diorama");
  renderViewToggle();
  const helpOverlay = () => $("help-overlay");
  const setHelp = on => { const h = helpOverlay(); if (h) h.classList.toggle("hidden", !on); };
  const helpBtn = $("btn-help");
  if (helpBtn) helpBtn.onclick = () => setHelp(helpOverlay().classList.contains("hidden"));
  const helpClose = $("btn-help-close");
  if (helpClose) helpClose.onclick = () => setHelp(false);
  const hOverlay = helpOverlay();
  if (hOverlay) hOverlay.onclick = e => { if (e.target === hOverlay) setHelp(false); };
  for (const b of document.querySelectorAll("#side-tabs button"))
    b.onclick = () => { localStorage.setItem(sideTabKey(), b.dataset.tab); applySideTab(); };
  const dt = $("btn-dark-toggle");
  if (dt) dt.onclick = () => {                     // D87: DM darkness switch
    if (!state.grid || state.room.role !== "dm") return;
    const dark = !state.grid.dark;
    wsSend({ type: "map_edit", map: { ...state.grid, dark }, dark,
             floor: state.viewFloor || "" });                  // D88: the plane you view
  };
  const ft = $("btn-fog-toggle");
  if (ft) ft.onclick = () => {
    if (!state.room || state.room.role !== "dm") return;
    wsSend({ type: "fog_toggle", on: !(state.grid && state.grid.fog_off) });
  };
  for (const b of document.querySelectorAll(".brush")) {
    if (b.id === "btn-fog-toggle" || b.id === "btn-dark-toggle") continue;
    b.onclick = () => { state.brush = b.dataset.b;
      document.querySelectorAll(".brush").forEach(x => x.classList.toggle("active", x === b));
      $("trap-fields").classList.toggle("hidden", b.dataset.b !== "trap");
      $("loot-fields").classList.toggle("hidden", b.dataset.b !== "loot");
      const of = $("obj-fields"); if (of) of.classList.toggle("hidden", b.dataset.b !== "obj");
      $("door-fields").classList.toggle("hidden", b.dataset.b !== "door");
      const pf = $("pin-fields"); if (pf) pf.classList.toggle("hidden", !["pin","pinrm"].includes(b.dataset.b)); };
  }
  renderFogToggle();
  $("btn-ed-save").onclick = () => {
    if (!state.editMap) return;
    wsSend({ type:"map_edit", map: state.editMap, reset_fog: $("ed-fog").checked,
             floor: state.viewFloor || "" });                  // D88: edits land on the viewed plane
    toast("Map saved");
  };
  $("btn-ed-cancel").onclick = editorClose;
  $("btn-ed-resize").onclick = edResize;
  $("map-file").onchange = async (e) => {
    const f = e.target.files[0]; if (!f || !state.room) return;
    try { const r = await fetch(`/api/rooms/${state.room.code}/map?name=${encodeURIComponent(f.name.replace(/\.[^.]+$/,""))}`,
        { method:"PUT", body: f, headers:{"Content-Type":"application/octet-stream"} });
      if (!r.ok){ const d = await r.json().catch(()=>({})); throw new Error(d.detail||"Upload failed"); }
      toast("Map updated"); await refreshRoom();
      if (state.room.map){ state.bg = new Image(); state.bg.src = state.room.map; }
    } catch(er){ toast(er.message); }
    e.target.value = "";
  };
}

/* Boot is NOT started here any more (D78): 99_boot.js runs the bundle
   integrity gate after every script exists and only then calls appBoot(). */
async function appBoot(){
  wire();
  wireEncounters();
  wireNotes();
  wireQuestUI();
  wireRoomAtmosphere();
  clearPings();
  if (typeof DEBUG !== "undefined" && DEBUG) document.body.classList.add("dbg-on");
  try { await loadLobby(); }
  catch { show("auth"); }
}
