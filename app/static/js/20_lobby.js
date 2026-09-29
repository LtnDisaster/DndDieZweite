/* Auth + lobby + character editor. */

const ITEM_KINDS = [["armor","armor"],["shield","shield"],["potion","potion"],["scroll","scroll"],
  ["wand","wand"],["staff","staff"],["ring","ring"],["tool","tool"],["wondrous","wondrous"],
  ["spellbook","📖 spellbook"],["other","other"]];

/* ---------- auth ---------- */
async function doAuth(path){
  try {
    await api(path, "POST", { username:$("au-user").value.trim(), password:$("au-pass").value });
    $("auth-err").textContent=""; $("au-pass").value=""; await loadLobby();
  } catch(e){ err("auth-err", e); }
}

/* ---------- lobby ---------- */
async function loadLobby(){
  stopTick();
  state.me = await api("/me");
  state.chars = await api("/characters");
  const rooms = await api("/rooms");
  state.rooms = rooms;
  $("lobby-user").textContent = "🧙 " + state.me.username;
  renderChars();
  const rl = $("room-list");
  rl.innerHTML = rooms.length ? "" : "<p class='err' style='opacity:.6'>No rooms yet — create or join one.</p>";
  for (const r of rooms){
    const d = document.createElement("div"); d.className = "roomrow";
    d.innerHTML = `<span><b>${esc(r.name)}</b> <small>${esc(r.code)}</small></span>
                   <span class='badge'>${esc(r.role)}</span>`;
    d.onclick = () => openRoom(r.code);
    rl.appendChild(d);
  }
  show("lobby");
}
function renderChars(){
  const cl = $("char-list"); cl.innerHTML = "";
  if (!state.chars.length) cl.innerHTML = "<p class='err' style='opacity:.6'>No characters yet.</p>";
  for (const c of state.chars){
    const d = document.createElement("div"); d.className = "char-card";
    const inroom = state.room && state.room.characters.some(x=>x.id===c.id);
    d.innerHTML = `<div class="head"><b>${esc(c.name)}</b>
        <span>${inroom ? "<span class='badge'>in room</span>" : `<button data-a="use">Bring</button>`}
        <button data-a="edit">Edit</button> <button data-a="del">✕</button></span></div>
      <div class="meta">${esc(c.race)} ${esc(c.char_class)} · Lv ${c.level} · HP ${c.hp}/${c.max_hp} · AC ${c.ac}</div>`;
    d.querySelector('[data-a="edit"]').onclick = () => openCharForm(c);
    d.querySelector('[data-a="del"]').onclick = async () => {
      if (!confirm(`Delete ${c.name}?`)) return;
      try { await api("/characters/"+c.id, "DELETE"); await loadLobby(); } catch(e){ toast(e.message); }
    };
    const use = d.querySelector('[data-a="use"]');
    if (use) use.onclick = async () => {
      try {
        if (!state.room) {
          if (!state.rooms || !state.rooms.length) return toast("Join or create a room first");
          await openRoom(state.rooms[0].code);
        }
        await api(`/rooms/${state.room.code}/assign`, "POST", { character_id: c.id });
        await refreshRoom();
      } catch(e){ toast(e.message); }
    };
    cl.appendChild(d);
  }
}
function openCharForm(c){
  state.charEdit = c ? c.id : null;
  $("char-editor").open = true;
  $("ch-name").value = c ? c.name : ""; $("ch-race").value = c ? c.race : "";
  $("ch-class").value = c ? c.char_class : ""; $("ch-level").value = c ? c.level : 1;
  $("ch-hp").value = c ? c.hp : 10; $("ch-mhp").value = c ? c.max_hp : 10;
  $("ch-ac").value = c ? c.ac : 10; $("ch-speed").value = c ? c.speed : 30;
  $("ch-notes").value = c ? c.notes : "";
  for (const [k] of STATS) $("st-"+k).value = c && c.stats && c.stats[k]!=null ? c.stats[k] : 10;
  state.weaponRows = (c && Array.isArray(c.weapons) ? c.weapons : []).map(w => ({...w}));
  renderWeaponRows();
  state.itemRows = (c && Array.isArray(c.items) ? c.items : []).map(i => ({...i}));
  renderItemRows();
  state.skillMap = Object.assign({}, c && c.skills ? c.skills : {});
  renderSkillRows();
  state.spellRows = (c && Array.isArray(c.spells) ? c.spells : []).map(s => ({...s}));
  renderSpellRows();
  state.slotMap = {};
  for (let l = 1; l <= 9; l++){
    const d = c && c.spell_slots && c.spell_slots[l];
    state.slotMap[l] = d ? { max: d.max||0, used: d.used||0 } : { max: 0, used: 0 };
  }
  renderSlotRows();
  $("btn-char-cancel").classList.toggle("hidden", !c);
}
function renderWeaponRows(){
  const box = $("weap-rows"); if (!box) return;
  box.innerHTML = "";
  state.weaponRows.forEach((w, idx) => {
    const r = document.createElement("div"); r.className = "row weap";
    r.innerHTML = `<input class="w-name" placeholder="Name" value="${esc(w.name||"")}" maxlength="40">
      <select class="w-ab">${STATS.map(([k,l]) => `<option value="${k}" ${w.ability===k?"selected":""}>${l}</option>`).join("")}</select>
      <label class="w-prof"><input type="checkbox" class="w-pf" ${w.proficient?"checked":""}>prof</label>
      <input class="w-dmg" placeholder="1d8+3" value="${esc(w.dmg||"")}" maxlength="16">
      <input class="w-bonus" type="number" min="-3" max="10" value="${w.dmgBonus||0}" title="Magic bonus" style="width:44px">
      <label class="w-prof" title="Magic weapon"><input type="checkbox" class="w-magic" ${w.magic?"checked":""}>✨</label>
      <button type="button" class="w-del" title="Remove">✕</button>`;
    r.querySelector(".w-name").oninput = e => w.name = e.target.value;
    r.querySelector(".w-ab").onchange = e => w.ability = e.target.value;
    r.querySelector(".w-pf").onchange = e => w.proficient = e.target.checked;
    r.querySelector(".w-dmg").oninput = e => w.dmg = e.target.value;
    r.querySelector(".w-bonus").oninput = e => w.dmgBonus = +e.target.value || 0;
    r.querySelector(".w-magic").onchange = e => w.magic = e.target.checked;
    r.querySelector(".w-del").onclick = () => { state.weaponRows.splice(idx,1); renderWeaponRows(); };
    box.appendChild(r);
  });
}
function renderItemRows(){
  const box = $("item-rows"); if (!box) return;
  box.innerHTML = "";
  state.itemRows.forEach((it, idx) => {
    const r = document.createElement("div"); r.className = "item-row";
    r.innerHTML = `<div class="row">
      <input class="i-name" placeholder="Item name" value="${esc(it.name||"")}" maxlength="48">
      <select class="i-kind">${ITEM_KINDS.map(([k,l])=>`<option value="${k}" ${it.kind===k?"selected":""}>${l}</option>`).join("")}</select>
      <label title="Basic armor AC"><span class="tiny">ac</span><input class="i-ac" type="number" min="0" max="40" value="${it.ac||0}" style="width:48px"></label>
      <label title="Light armor (add full Dex)"><input type="checkbox" class="i-light" ${it.light?"checked":""}>🪶</label>
      <label title="AC bonus"><span class="tiny">ac+</span><input class="i-acb" type="number" min="-5" max="10" value="${it.acBonus||0}" style="width:44px"></label>
      <input class="i-heal" placeholder="heal 2d4+2" value="${esc(it.heal||"")}" maxlength="16" style="width:96px">
      <label title="Charges (-1 = unlimited)"><span class="tiny">chg</span><input class="i-chg" type="number" min="-1" max="999" value="${it.charges==null?-1:it.charges}" style="width:52px"></label>
      <select class="i-re" title="Recharge"><option value="">recharge:—</option><option value="long" ${it.recharge==="long"?"selected":""}>long rest</option></select>
      <button type="button" class="i-del" title="Remove">✕</button>
    </div>
    <div class="row">
      <label class="tiny"><input type="checkbox" class="i-magic" ${it.magic?"checked":""}>magic</label>
      <label class="tiny"><input type="checkbox" class="i-atu" ${it.attunable?"checked":""}>attunable</label>
      <input class="i-desc" placeholder="description / properties" value="${esc(it.desc||"")}" maxlength="200">
    </div>`;
    r.querySelector(".i-name").oninput = e => it.name = e.target.value;
    r.querySelector(".i-kind").onchange = e => it.kind = e.target.value;
    r.querySelector(".i-ac").oninput = e => it.ac = +e.target.value || 0;
    r.querySelector(".i-light").onchange = e => it.light = e.target.checked;
    r.querySelector(".i-acb").oninput = e => it.acBonus = +e.target.value || 0;
    r.querySelector(".i-heal").oninput = e => it.heal = e.target.value;
    r.querySelector(".i-chg").oninput = e => it.charges = e.target.value==="" ? -1 : (+e.target.value);
    r.querySelector(".i-re").onchange = e => it.recharge = e.target.value || null;
    r.querySelector(".i-magic").onchange = e => it.magic = e.target.checked;
    r.querySelector(".i-atu").onchange = e => it.attunable = e.target.checked;
    r.querySelector(".i-desc").oninput = e => it.desc = e.target.value;
    r.querySelector(".i-del").onclick = () => { state.itemRows.splice(idx,1); renderItemRows(); };
    box.appendChild(r);
  });
}
function renderSkillRows(){
  const box = $("skill-rows"); if (!box) return;
  box.innerHTML = "";
  const lvl = +$("ch-level").value || 1;
  state.skillMap = state.skillMap || {};
  for (const [k, [label, ab]] of Object.entries(SKILLS)){
    const lvlv = state.skillMap[k] || 0;
    const bonus = _smod(($("st-"+ab) && $("st-"+ab).value)) + _pb(lvl) * lvlv;
    const mark = lvlv === 2 ? "★" : lvlv === 1 ? "✓" : "–";
    const row = document.createElement("div"); row.className = "skillrow";
    row.innerHTML = `<span class="sk-name">${label} <small>${ab.toUpperCase()}</small></span>
      <span class="sk-bonus">${bonus>=0?"+":""}${bonus}</span>
      <button type="button" class="sk-cycle ${lvlv===2?"exp":lvlv===1?"prof":""}">${mark}</button>`;
    row.querySelector(".sk-cycle").onclick = () => {
      const next = ((state.skillMap[k] || 0) + 1) % 3;
      if (next) state.skillMap[k] = next; else delete state.skillMap[k];
      renderSkillRows();
    };
    box.appendChild(row);
  }
}
function renderSpellRows(){
  const box = $("spell-rows"); if (!box) return;
  box.innerHTML = "";
  (state.spellRows || []).forEach((sp, idx) => {
    const r = document.createElement("div"); r.className = "spell-row";
    r.innerHTML = `<div class="row">
      <input class="sp-name" placeholder="Spell name" value="${esc(sp.name||"")}" maxlength="48">
      <input class="sp-lvl" type="number" min="0" max="9" value="${sp.level==null?1:sp.level}" title="Level (0=cantrip)" style="width:44px">
      <input class="sp-school" placeholder="school" value="${esc(sp.school||"")}" maxlength="24" style="width:78px">
      <select class="sp-ab">${STATS.map(([k,l])=>`<option value="${k}" ${sp.ability===k?"selected":""}>${l}</option>`).join("")}</select>
      <select class="sp-cast" title="Casting">
        <option value="none" ${(!sp.cast||sp.cast==="none")?"selected":""}>—</option>
        <option value="attack" ${sp.cast==="attack"?"selected":""}>attack</option>
        <option value="save" ${sp.cast==="save"?"selected":""}>save</option></select>
      <input class="sp-dmg" placeholder="8d6" value="${esc(sp.dmg||"")}" maxlength="16" title="Damage dice" style="width:56px">
      <select class="sp-save" title="Save ability"><option value="">save:—</option>${STATS.map(([k,l])=>`<option value="${k}" ${sp.save===k?"selected":""}>${l}</option>`).join("")}</select>
      <button type="button" class="sp-del" title="Remove">✕</button>
    </div>
    <div class="row">
      <input class="sp-range" placeholder="range (e.g. 90 ft)" value="${esc(sp.range||"")}" maxlength="24" style="width:120px">
      <input class="sp-dur" placeholder="duration (e.g. instant)" value="${esc(sp.duration||"")}" maxlength="24" style="width:150px">
    </div>`;
    r.querySelector(".sp-name").oninput = e => sp.name = e.target.value;
    r.querySelector(".sp-lvl").oninput = e => sp.level = Math.max(0, Math.min(9, +e.target.value || 0));
    r.querySelector(".sp-school").oninput = e => sp.school = e.target.value;
    r.querySelector(".sp-ab").onchange = e => sp.ability = e.target.value;
    r.querySelector(".sp-cast").onchange = e => sp.cast = e.target.value;
    r.querySelector(".sp-dmg").oninput = e => sp.dmg = e.target.value;
    r.querySelector(".sp-save").onchange = e => sp.save = e.target.value;
    r.querySelector(".sp-range").oninput = e => sp.range = e.target.value;
    r.querySelector(".sp-dur").oninput = e => sp.duration = e.target.value;
    r.querySelector(".sp-del").onclick = () => { state.spellRows.splice(idx, 1); renderSpellRows(); };
    box.appendChild(r);
  });
}
function renderSlotRows(){
  const box = $("slot-rows"); if (!box) return;
  box.innerHTML = "";
  state.slotMap = state.slotMap || {};
  for (let l = 1; l <= 9; l++){
    state.slotMap[l] = state.slotMap[l] || { max: 0, used: 0 };
    const w = document.createElement("label"); w.className = "slotcell";
    w.innerHTML = `L${l}<input class="slot-max" type="number" min="0" max="9" value="${state.slotMap[l].max}" style="width:40px">`;
    w.querySelector(".slot-max").oninput = e => { state.slotMap[l].max = Math.max(0, Math.min(9, +e.target.value || 0)); };
    box.appendChild(w);
  }
}
function charPayload(){
  const stats = {}; for (const [k] of STATS) stats[k] = Math.max(1, Math.min(30, +$("st-"+k).value || 10));
  const items = (state.itemRows||[]).filter(i => i.name && i.name.trim()).map(i => ({
    id: i.id || eid(), name:i.name, kind:i.kind||"other", ac:i.ac||0, light:!!i.light,
    acBonus:i.acBonus||0, heal:i.heal||"", charges:i.charges==null?-1:i.charges,
    recharge:i.recharge||null, magic:!!i.magic, attunable:!!i.attunable,
    attuned:!!(i.attunable&&i.attuned), identified:!!i.identified||!i.magic, desc:i.desc||"" }));
  const slots = {};
  for (let l = 1; l <= 9; l++){
    const m = state.slotMap && state.slotMap[l] ? (+state.slotMap[l].max || 0) : 0;
    if (m > 0) slots[String(l)] = { max: m, used: Math.min(m, (+state.slotMap[l].used) || 0) };
  }
  const p = { name:$("ch-name").value.trim(), race:$("ch-race").value.trim(),
    char_class:$("ch-class").value.trim(), level:+$("ch-level").value || 1, stats,
    hp:+$("ch-hp").value || 10, max_hp:+$("ch-mhp").value || 10,
    ac:+$("ch-ac").value || 10, speed:+$("ch-speed").value || 30, notes:$("ch-notes").value,
    weapons:(state.weaponRows||[]).filter(w => w.name && w.name.trim()), items,
    skills: state.skillMap || {},
    spells: (state.spellRows||[]).filter(s => s.name && s.name.trim()),
    spell_slots: slots };
  p.hp = Math.min(p.hp, p.max_hp);
  return p;
}
