/* ---------- wiring ---------- */
function wire(){
  const sf = $("ch-stats");
  sf.innerHTML = STATS.map(([k,l]) =>
    `<label>${l}<input id="st-${k}" type="number" min="1" max="30" value="10"></label>`).join("");

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
  const sendChat = () => { const t = $("chat-in").value.trim();
    if (t){ wsSend({ type:"chat", text:t }); $("chat-in").value=""; } };
  $("btn-chat").onclick = sendChat;
  $("chat-in").addEventListener("keydown", e => { if (e.key === "Enter") sendChat(); });
  const roll = () => wsSend({ type:"roll", expr: $("roll-expr").value, adv: $("roll-adv").value || null,
                              ability: $("roll-abil") ? $("roll-abil").value || null : null,
                              prof: $("roll-prof") ? $("roll-prof").checked : false });
  $("btn-roll").onclick = roll;
  $("roll-expr").addEventListener("keydown", e => { if (e.key === "Enter") roll(); });
  $("mh-go").onclick = confirmPlan;
  $("mh-cancel").onclick = clearPlan;
  for (const b of $("dice-btns").querySelectorAll("button"))
    b.onclick = () => { $("roll-expr").value = "1"+b.dataset.d; roll(); };
  $("btn-init-start").onclick = () => wsSend({ type:"init_start" });
  $("btn-init-next").onclick = () => wsSend({ type:"init_next" });
  $("btn-init-round").onclick = () => wsSend({ type:"init_end_round" });
  $("btn-init-end").onclick = () => wsSend({ type:"init_end" });
  for (const b of $("hp-btns").querySelectorAll("button"))
    b.onclick = () => hpDelta(+b.dataset.hp);
  $("btn-npc-add").onclick = () => {
    const n = $("npc-name").value.trim(); if (n){ wsSend({ type:"add_token", label:n }); $("npc-name").value=""; }
  };
  $("btn-edit-map").onclick = () => { state.editing ? editorClose() : editorOpen(); };
  $("btn-long-rest").onclick = () => wsSend({ type: "long_rest" });
  for (const b of document.querySelectorAll(".brush"))
    b.onclick = () => { state.brush = b.dataset.b;
      document.querySelectorAll(".brush").forEach(x => x.classList.toggle("active", x === b));
      $("trap-fields").classList.toggle("hidden", b.dataset.b !== "trap");
      $("loot-fields").classList.toggle("hidden", b.dataset.b !== "loot"); };
  $("btn-ed-save").onclick = () => {
    if (!state.editMap) return;
    wsSend({ type:"map_edit", map: state.editMap, reset_fog: $("ed-fog").checked });
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

(async function boot(){
  wire();
  try { await loadLobby(); }
  catch { show("auth"); }
})();
