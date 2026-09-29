/* ---------- room ---------- */
async function openRoom(code){
  const s = await api(`/rooms/${code}/state`);
  state.room = s; state.init = s.initiative; state.tokens = s.tokens; state.ghosts = s.ghosts || [];
  state.grid = s.grid; state.editing = false; state.editMap = null; state.sel = null; state.plan = null;
  state.online = new Set([state.me.username]);
  state.cam.ox = state.cam.oy = 0;
  $("room-title").textContent = s.name;
  $("room-code").textContent = s.code;
  $("room-code").onclick = () => { navigator.clipboard?.writeText(s.code); toast("Code copied"); };
  $("room-role").textContent = s.role.toUpperCase();
  $("room-role").style.background = s.role === "dm" ? "var(--gold)" : "#2c3e50";
  $("dmtools").classList.toggle("hidden", s.role !== "dm");
  $("init-btns").classList.toggle("hidden", s.role !== "dm");
  $("chat").innerHTML = "";
  for (const m of s.messages) appendChat(m);
  renderParty(); renderInit();   renderOnline();
  renderMyChars(); renderRolls();
  if (s.map){ state.bg = new Image(); state.bg.src = s.map; } else state.bg = null;
  show("room"); resize(); startTick(); connectWS(s.code);
}
async function refreshRoom(){
  const s = await api(`/rooms/${state.room.code}/state`);
  state.room = s; state.init = s.initiative; state.tokens = s.tokens; state.ghosts = s.ghosts || []; state.grid = s.grid;
  if (state.plan && !state.tokens.find(t => t.id === state.plan.tokenId)) state.plan = null;
  updateMoveHud();
  renderParty(); renderInit(); renderMyChars(); renderChatAll(s.messages);
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
      try { await api(`/rooms/${state.room.code}/assign`, "POST", { character_id: c.id });
            await refreshRoom(); toast(`${c.name} takes a seat at the table`); } catch(e){ toast(e.message); }
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
  const ab = $("sr-abil"); ab.innerHTML = "";
  for (const [k,l] of [["str","STR"],["dex","DEX"],["con","CON"],["int","INT"],["wis","WIS"],["cha","CHA"]]){
    const wrap = document.createElement("span"); wrap.className = "abil";
    const m = mods[k];
    wrap.innerHTML = `<button data-k="${k}" title="Ability check">${l} ${m>=0?"+":""}${m}</button>` +
                     `<button class="sv" data-k="${k}" title="Saving throw">S</button>`;
    ab.appendChild(wrap);
  }
  for (const b of ab.querySelectorAll("button")) b.onclick = () => {
    const kind = b.classList.contains("sv") ? "save" : "check";
    wsSend({ type:"roll", kind, ability: b.dataset.k,
             prof: $("sr-prof").checked, adv: $("sr-adv").value || null });
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
                                 ability: ($("sr-atk-abil") && $("sr-atk-abil").value) || null });
    dmg.onclick = () => wsSend({ type:"roll", kind:"damage", weapon:w.name, crit:false });
    crit.onclick = () => wsSend({ type:"roll", kind:"damage", weapon:w.name, crit:true });
    wl.appendChild(row);
  }
}
function renderChatAll(msgs){ $("chat").innerHTML=""; for (const m of msgs) appendChat(m); }
function appendChat(m){
  const p = document.createElement("p");
  const cls = m.type === "system" ? "sys" : m.type === "dice" ? "dice"
    : m.type === "whisper" ? "whisper"
    : (m.username === state.me?.username ? "me" : "");
  p.className = cls;
  p.innerHTML = (m.type === "system" || m.type === "whisper") ? esc(m.body)
    : `<b>${esc(m.username)}</b> ${esc(m.body)}`;
  const c = $("chat"); const stick = c.scrollHeight - c.scrollTop - c.clientHeight < 40;
  c.appendChild(p); if (stick) c.scrollTop = c.scrollHeight;
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
function renderInit(){
  const ol = $("init-list"); ol.innerHTML = "";
  const i = state.init;
  if (!i || !i.combat){ ol.innerHTML = "<li style='opacity:.5'>No combat</li>"; return; }
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
  const panel = $("sheet");
  if (!tok){ panel.classList.add("hidden"); return; }
  panel.classList.remove("hidden");
  const m = state.room.members.find(x => x.user_id === tok.owner_user_id);
  const ch = m && m.char;
  $("sheet-name").textContent = tok.label + (ch ? ` (${ch.race} ${ch.char_class} Lv${ch.level})` : " [NPC]");
  const body = $("sheet-body");
  if (!ch){ body.innerHTML = `<div class="meta">No character attached.</div>
    <div class="row"><button id="btn-del-npc" style="color:var(--red)">Remove NPC token</button></div>`;
    $("hp-btns").classList.add("hidden");
    $("btn-del-npc").onclick = () => wsSend({ type:"del_token", token_id: tok.id });
    return; }
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
  const skillBlock = profSkills.length ? `<div class="skills-sheet"><div class="wlabel">Skills</div>` +
    profSkills.map(k => {
      const meta = SKILLS[k] || [k, ""], bonus = _smod(_ab(meta[1])) + _pb(lvlv) * skills[k];
      return `<div class="skrow"><span>${meta[0]} <small>${skills[k]===2?"★":"✓"}</small> <b>${bonus>=0?"+":""}${bonus}</b></span>` +
             (own ? `<button class="sk-roll" data-skill="${k}">Roll</button>` : "") + `</div>`;
    }).join("") + `</div>` : "";
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
    bookBlock = `<div class="book"><div class="wlabel">📖 Spellbook ${slotLine.length?`<small style="opacity:.6"> · ${slotLine.join(" ")}</small>`:`<small style="opacity:.6"> · no slots</small>`}</div>${spRows||`<div class="meta" style="opacity:.6">No spells learned.</div>`}</div>`;
  } else if (own && spells.length){
    bookBlock = `<div class="book"><div class="wlabel">📖 Spellbook</div><div class="meta" style="opacity:.7">Add a <b>📖 spellbook</b> item to your character to cast at the table.</div></div>`;
  }
  body.innerHTML = `
    <div class="hpbar"><div style="width:${Math.max(0,ch.hp/ch.max_hp*100)}%;${ch.hp/ch.max_hp<=.25?"background:var(--red)":""}"></div></div>
    <b>HP ${ch.hp}/${ch.max_hp}</b> · AC ${ac} · Speed ${ch.speed} ft
    <div class="statline">${STATS.map(([k,l]) =>
      `<div class="stat"><small>${l}</small>${v(ch.stats,k)} <small>${mod(v(ch.stats,k))}</small></div>`).join("")}</div>
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
  for (const b of body.querySelectorAll(".sk-roll")) b.onclick = () => wsSend({ type:"roll", kind:"skill", skill: b.dataset.skill });
  for (const b of body.querySelectorAll(".roll-sp")) b.onclick = () => wsSend({ type:"roll", kind: b.dataset.k, spell_id: b.dataset.id, crit: b.dataset.crit === "1" });
  for (const b of body.querySelectorAll(".cast-sp")) b.onclick = () => wsSend({ type:"cast", spell_id: b.dataset.id });
  $("hp-btns").classList.toggle("hidden", state.room.role !== "dm" || !tok.character_id);
  function v(s,k){ const x = s && s[k]; return typeof x === "number" ? x : 10; }
}
function hpDelta(d){
  const tok = state.tokens.find(t => t.id === state.sel);
  if (tok) wsSend({ type:"hp", token_id: tok.id, delta: d });
}
function renderOnline(){
  $("online").innerHTML = [...state.online].map(u =>
    `<b>●</b> ${esc(u)}`).join(" &nbsp; ");
}
