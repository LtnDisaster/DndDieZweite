/* ---------- 80_prep.js — room preparation + guided character build (D101) ----------
   The landing screen between "joined a room" and "sitting at the table".
   A DM sees the rule-pack status, can import CSVs and sees who is in the
   room; a player picks or creates a character with DROPDOWNS fed by the
   room's imported content, walks the SERVER's build plan (charbuild.plan)
   as plain checkboxes/selects, assigns the character and opens the table.
   This module holds NO class rules — every decision is described by the
   server plan and re-validated by charbuild.apply. The raw ID/JSON entry
   stays available as an opt-in expert mode; unsupported decision types are
   surfaced there explicitly, never silently skipped. */
(typeof window !== "undefined") && ((window.__BUILDS = window.__BUILDS || {})["80_prep.js"] = window.__BUILD__ || "?");

const PREP_OPTION_KINDS = ["species", "class", "subclass", "background", "feat", "spell"];

function prepMap(kind){
  const m = {};
  for (const o of ((state.prep && state.prep.options && state.prep.options[kind]) || [])) m[o.id] = o.name;
  return m;
}
function prepSkillLabel(k){ return (SKILLS[k] && SKILLS[k][0]) || k; }
function prepLedger(c){
  let led = {};
  try { led = c && c.build ? (typeof c.build === "string" ? JSON.parse(c.build) : c.build) : {}; }
  catch { led = {}; }
  return led;
}
function prepChars(){ return (state.room && state.room.characters) || []; }
function prepSelChar(){
  const chars = prepChars();
  if (!chars.length) return null;
  const me = state.room.members.find(m => m.user_id === state.me.id) || {};
  const id = (state.prep.selChar && chars.some(c => c.id === state.prep.selChar))
    ? state.prep.selChar : (me.character_id || chars[0].id);
  return chars.find(c => c.id === id) || chars[0];
}

async function openPrep(code){
  const s = await api(`/rooms/${code}/state`);
  state.room = s; state.chars = s.characters || state.chars;
  state.prep = { code, options: {}, kinds: null, selChar: null, newMode: false,
                 plan: null, wiz: {}, gearReport: null };
  try { state.prep.options = (await api(`/content/${code}/options`)).options || {}; }
  catch { state.prep.options = {}; }
  if (s.role === "dm") {
    try { state.prep.kinds = (await api(`/content/${code}/kinds`)).kinds || {}; }
    catch { state.prep.kinds = null; }
  }
  renderPrep();
  show("prep");
}

async function prepRefresh(){
  if (!state.prep) return;
  const s = await api(`/rooms/${state.prep.code}/state`);
  state.room = s; state.chars = s.characters || state.chars;
  try { state.prep.options = (await api(`/content/${state.prep.code}/options`)).options || state.prep.options; }
  catch { /* keep the last catalogue */ }
  if (s.role === "dm") {
    try { state.prep.kinds = (await api(`/content/${state.prep.code}/kinds`)).kinds; }
    catch { /* keep the last counts */ }
  }
  renderPrep();
}

function prepSelect(el, items, cur, blank){
  el.innerHTML = (blank ? `<option value="">${esc(blank)}</option>` : "") +
    items.map(o => `<option value="${esc(o.id)}" ${String(o.id) === String(cur) ? "selected" : ""}>${esc(o.name || o.id)}</option>`).join("");
}

function renderPrep(){
  const p = state.prep; if (!p || !state.room) return;
  $("prep-title").textContent = state.room.name;
  $("prep-code").textContent = state.room.code;
  $("prep-code").onclick = () => { navigator.clipboard?.writeText(state.room.code); toast("Code copied"); };
  $("prep-role").textContent = state.room.role.toUpperCase();
  $("prep-role").style.background = state.room.role === "dm" ? "var(--gold)" : "#2c3e50";
  $("prep-dm-block").classList.toggle("hidden", state.room.role !== "dm");
  renderPrepKinds();
  renderPrepRoster();
  renderPrepChar();
  renderPrepWizard();
}

function renderPrepKinds(){
  const p = state.prep;
  const box = $("prep-kinds");
  if (box && state.room.role === "dm" && p.kinds){
    const n = Object.values(p.kinds).reduce((a, v) => a + (v || 0), 0);
    box.innerHTML = n
      ? Object.keys(p.kinds).map(k =>
          `<span class='badge' style='margin:1px'>${k}: ${p.kinds[k] || 0}</span>`).join("")
      : "<b>No rule pack imported yet</b> — upload CSV/ZIP below; the dropdowns stay empty until then.";
  }
  const noContent = state.room.role === "dm"
    ? !(p.kinds && Object.values(p.kinds).some(v => v > 0))
    : !((p.options.class || []).length || (p.options.species || []).length || (p.options.background || []).length);
  const hint = $("prep-content-hint");
  if (hint){
    hint.classList.toggle("hidden", !noContent);
    if (noContent) hint.textContent = "This room has no imported content yet — species/class/background choices and the guided build have nothing to list until the DM uploads a rule pack.";
  }
}

function renderPrepRoster(){
  const el = $("prep-roster"); if (!el) return;
  const rows = state.room.members.map(m => {
    const ch = m.char;
    const mine = m.user_id === state.me.id;
    const led = mine ? prepLedger(ch) : {};
    const built = mine ? (led.applied_through ? `built to ${led.applied_through}` : (ch ? "unbuilt" : "")) : "";
    const cls = ch ? (prepMap("class")[ch.char_class] || ch.char_class || "") : "";
    return `<div class="char-card compact"><div class="head">
        <b>${esc(ch ? ch.name : "—")}</b> <small>${esc(m.username)}</small>
        <span>${m.role === "dm" ? "<span class='badge'>DM</span> " : ""}${m.character_id ? "<span class='badge'>at table</span>" : ""}${mine && ch ? `<span class='badge'>${esc(built)}</span>` : ""}</span>
      </div>
      <div class="meta">${esc(ch ? [prepMap("species")[ch.race] || ch.race, cls].filter(Boolean).join(" · ") : "no character")}${ch ? ` · Lv ${ch.level}` : ""}</div></div>`;
  });
  el.innerHTML = rows.join("") || "<div class='meta' style='opacity:.6'>Nobody here yet.</div>";
}

function renderPrepChar(){
  const p = state.prep, ch = prepSelChar();
  const sel = $("prep-char");
  prepSelect(sel, prepChars().map(c => ({ id: c.id, name: c.name })), ch ? ch.id : "", "— no character —");
  sel.disabled = p.newMode;
  $("prep-new").classList.toggle("hidden", !p.newMode);
  $("prep-create").classList.toggle("hidden", !p.newMode);
  $("prep-id-save").classList.toggle("hidden", p.newMode || !ch);
  $("prep-new-toggle").textContent = p.newMode ? "✕ Cancel new character" : "＋ New character";
  for (const [id, kind] of [["prep-species", "species"], ["prep-class", "class"], ["prep-bg", "background"]]){
    const opts = p.options[kind] || [];
    prepSelect($(id), opts, "", `— ${kind}: none in this room's pack —`);
  }
  const msg = $("prep-char-msg");
  if (!ch && !p.newMode){ msg.textContent = "Pick a character or create one — guided build works on the selected character."; }
  else if (ch){
    const led = prepLedger(ch);
    const bg = prepMap("background")[ch.background] || ch.background || "";
    msg.innerHTML = `<b>${esc(ch.name)}</b> · ${esc(prepMap("species")[ch.race] || ch.race || "no species")} · ` +
      `${esc(prepMap("class")[ch.char_class] || ch.char_class || "no class")} · ${esc(bg || "no background")} · ` +
      (led.applied_through ? `built to ${led.applied_through}` : "unbuilt");
    const sp = $("prep-species"), cl = $("prep-class"), bgEl = $("prep-bg");
    const spOpt = (p.options.species || []).some(o => o.name === ch.race || o.id === ch.race);
    if (spOpt) sp.value = (p.options.species.find(o => o.name === ch.race || o.id === ch.race) || {}).id;
    if ((p.options.class || []).some(o => o.id === ch.char_class)) cl.value = ch.char_class;
    if ((p.options.background || []).some(o => o.id === ch.background || o.name === ch.background))
      bgEl.value = (p.options.background.find(o => o.id === ch.background || o.name === ch.background) || {}).id;
  } else msg.textContent = "";
  renderPrepChecklist(ch);
}

function renderPrepChecklist(ch){
  const el = $("prep-check"); if (!el) return;
  const assigned = (state.room.members.find(m => m.user_id === state.me.id) || {}).character_id;
  const led = prepLedger(ch);
  const item = (ok, txt) => `<div>${ok ? "✅" : "⬜"} ${txt}</div>`;
  el.innerHTML =
    item(!!ch, ch ? `Character: ${esc(ch.name)}` : "Character: choose or create one") +
    item(!!ch && !!ch.race && !!ch.char_class && !!ch.background,
         ch ? "Species, class and background chosen" : "Species/class/background from the rule pack") +
    item(!!ch && !!led.applied_through,
         ch ? (led.applied_through ? `Build applied through level ${led.applied_through}` : "Build not applied yet — plan + apply below") : "Build (guided level-up)") +
    item(!!ch && !!led.origin,
         ch ? (led.origin ? `2024 Origin granted (${led.origin.background})` : "2024 Origin pending — 🧬 Origin card below") : "2024 Origin (background ASI + feat)") +
    item(assigned && ch && assigned === ch.id,
         assigned && ch && assigned === ch.id ? "Seated at the table" : "Seat this character at the table") +
    `<div style="margin-top:4px">Equipment: ${ch ? (ch.items || []).length : 0} item(s)${
       ch && (ch.items || []).length ? " — " + esc((ch.items || []).map(i => `${i.qty > 1 ? i.qty + "× " : ""}${i.name}`).slice(0, 6).join(", ")) : ""}</div>`;
}

/* ---------------- guided wizard (plan -> plain controls -> choices) ---------------- */

function renderPrepWizard(){
  const p = state.prep, ch = prepSelChar(), wiz = $("prep-wiz");
  if (!wiz) return;
  $("prep-choices-row").classList.toggle("hidden", !$("prep-expert").checked);
  if (!p.plan){ wiz.innerHTML = p.planError
    ? `<span style="color:#e74c3c">${esc(p.planError)}</span>`
    : "<span style='opacity:.7'>Pick a class and target level, then 🧭 Plan — the server decides which choices the build needs and they appear here as plain fields.</span>";
    return; }
  if (!p.plan.ok){ wiz.innerHTML = `<span style="color:#e74c3c">${esc((p.plan.errors || []).join(", "))}</span>`;
    p.planError = (p.plan.errors || []).join(", "); p.plan = null; return; }
  const n = p.plan.needs || {};
  const parts = [];
  const selCls = (p.plan.class_id && prepMap("class")[p.plan.class_id]) || p.plan.class_id;
  parts.push(`<div>Plan: <b>${esc(selCls)}</b> → level ${p.plan.to} · ${p.plan.levels.length} level(s), ` +
             `+${p.plan.levels.reduce((a, l) => a + (+l.hp_per_level || 0), 0)} HP bookkeeping</div>`);
  if (n.skills){
    const got = (p.wiz.skills || []);
    parts.push(`<div><b>Choose ${n.skill_count} skill(s)</b> <small class="pw-skcnt">${got.length}/${n.skill_count} selected</small></div><div class="row" style="flex-wrap:wrap">` +
      (n.skill_options || []).map(k =>
        `<label class="tiny" style="margin:1px 6px"><input type="checkbox" class="pw-sk" value="${esc(k)}" ${got.includes(k) ? "checked" : ""}> ${esc(prepSkillLabel(k))}</label>`).join("") +
      `</div>`);
  }
  if (n.subclass){
    const names = prepMap("subclass");
    parts.push(`<div><b>Subclass</b></div><div class="row"><select class="pw-sub" style="flex:1">` +
      `<option value="">— choose —</option>` +
      (p.plan.subclass_options || []).map(s =>
        `<option value="${esc(s)}" ${p.wiz.subclass === s ? "selected" : ""}>${esc(names[s] || s)}</option>`).join("") +
      `</select></div>`);
  }
  const feats = prepMap("feat"), spells = prepMap("spell");
  for (const lvl of Object.keys(n.levels || {})){
    const spec = n.levels[lvl], w = p.wiz.levels[lvl] || {};
    parts.push(`<div><b>Choices for level ${lvl}</b></div>`);
    const known = [];
    if (spec.feat_choice || spec.ability_boost_or_feat){
      const cur = w.feat ? "feat:" + w.feat : (w.ability ? "ab:" + w.ability : "");
      const groups = [];
      if (spec.feat_choice){
        const opts = spec.feat_options && spec.feat_options.length
          ? spec.feat_options
          : (p.options.feat || []).map(f => ({ id: f.id, name: f.name, available: true, missing: [] }));
        groups.push(`<optgroup label="Feats">${opts.map(f => {
          const selected = cur === "feat:" + f.id;
          const disabled = !selected && !f.available ? " disabled" : "";
          const hint = f.available ? "" : ` — missing ${f.missing.join(", ")}`;
          return `<option value="feat:${esc(f.id)}" ${selected ? "selected" : ""}${disabled}>${esc(f.name || feats[f.id] || f.id)}${esc(hint)}</option>`;
        }).join("")}</optgroup>`);
      }
      if (spec.ability_boost_or_feat)
        groups.push(`<optgroup label="Ability score +2">${STATS.map(([k, l]) =>
          `<option value="ab:${k}+2" ${cur === "ab:" + k + "+2" ? "selected" : ""}>${l} +2</option>`).join("")}</optgroup>`);
      parts.push(`<div class="row"><select class="pw-lvl" data-lvl="${esc(lvl)}" style="flex:1">` +
        `<option value="">— choose —</option>${groups.join("")}</select></div>`);
      known.push("feat_choice", "ability_boost_or_feat");
    }
    const reqC = +spec.cantrips || 0, reqS = +spec.spells || 0;
    if (reqC || reqS){
      const list = (cls, pool, want, have, names, label) => want ? `<label class="tiny">${label} — pick ${want}</label>` +
        `<select class="${cls}" data-lvl="${esc(lvl)}" multiple size="4" style="flex:1">` +
        (pool || []).map(id => `<option value="${esc(id)}" ${(have || []).includes(id) ? "selected" : ""}>${esc(names[id] || id)}</option>`).join("") +
        `</select>` : "";
      parts.push(`<div class="row">` +
        list("pw-can", spec.pool_cantrips, reqC, w.cantrips, spells, "Cantrips") +
        list("pw-sp", spec.pool_spells, reqS, w.spells, spells, "Spells") + `</div>`);
      known.push("cantrips", "spells");
    }
    const reqE = +spec.expertise || 0;
    if (reqE){
      const have = (w.expertise || []), opts = (spec.expertise_skills || []);
      parts.push(`<label class="tiny">Expertise — choose ${reqE}</label>` +
        `<div class="row" style="flex-wrap:wrap">` + (opts.length
          ? opts.map(k => `<label class="tiny" style="margin:1px 6px"><input type="checkbox" class="pw-exp" data-lvl="${esc(lvl)}" value="${esc(k)}" ${have.includes(k) ? "checked" : ""}> ${esc(prepSkillLabel(k))}</label>`).join("")
          : `<small style="opacity:.6">No proficient skills are currently available.</small>`) + `</div>`);
      known.push("expertise");
    }
    const unsupported = Object.keys(spec).filter(k =>
      !known.includes(k) && !["pool_cantrips", "pool_spells", "expertise_skills", "feat_options"].includes(k));
    if (unsupported.length)
      parts.push(`<div style="color:#f1c40f">Level ${lvl}: unsupported decision type(s) ${esc(unsupported.join(", "))} — use Expert mode; do not skip.</div>`);
  }
  if (n.spell && n.spell.ability)
    parts.push(`<div><small style="opacity:.75">Casting ability: <b>${esc(n.spell.ability.toUpperCase())}</b> (class content row)</small></div>`);
  if (n.spell && n.spell.model === "prepared")
    parts.push(`<div><small style="opacity:.7">Prepared caster: the server pre-parses from the class pool — no spell choice needed.</small></div>`);
  const missing = prepMissing();
  parts.push(`<div><b>${missing.length ? `Still missing: ${esc(missing.join(", "))}` : "All guided choices collected ✔"}</b></div>`);
  wiz.innerHTML = parts.join("");
  for (const c of wiz.querySelectorAll(".pw-sk"))
    c.onchange = () => {
      const set = new Set(p.wiz.skills || []);
      c.checked ? set.add(c.value) : set.delete(c.value);
      p.wiz.skills = [...set];
      const cnt = wiz.querySelector(".pw-skcnt");
      if (cnt) cnt.textContent = `${p.wiz.skills.length}/${p.plan.needs.skill_count} selected`;
      prepWizSummary();
    };
  const sub = wiz.querySelector(".pw-sub");
  if (sub) sub.onchange = () => { p.wiz.subclass = sub.value; prepWizSummary(); };
  for (const s of wiz.querySelectorAll(".pw-lvl"))
    s.onchange = () => {
      const lvl = s.dataset.lvl, ent = Object.assign({}, p.wiz.levels[lvl] || {});
      delete ent.feat; delete ent.ability;
      const v = s.value;
      if (v.startsWith("feat:")) ent.feat = v.slice(5);
      else if (v.startsWith("ab:")) ent.ability = v.slice(3);
      if (ent.feat || ent.ability || (ent.cantrips && ent.cantrips.length) || (ent.spells && ent.spells.length)) p.wiz.levels[lvl] = ent;
      else delete p.wiz.levels[lvl];
      prepWizSummary();
    };
  for (const [cls, key] of [[".pw-can", "cantrips"], [".pw-sp", "spells"]])
    for (const s of wiz.querySelectorAll(cls))
      s.onchange = () => {
        const lvl = s.dataset.lvl, ent = Object.assign({}, p.wiz.levels[lvl] || {});
        const vals = [...s.selectedOptions].map(o => o.value);
        if (vals.length) ent[key] = vals; else delete ent[key];
        if (Object.keys(ent).length) p.wiz.levels[lvl] = ent; else delete p.wiz.levels[lvl];
        prepWizSummary();
      };
  for (const c of wiz.querySelectorAll(".pw-exp"))
    c.onchange = () => {
      const lvl = c.dataset.lvl, ent = Object.assign({}, p.wiz.levels[lvl] || {});
      const set = new Set(ent.expertise || []);
      c.checked ? set.add(c.value) : set.delete(c.value);
      if (set.size) ent.expertise = [...set]; else delete ent.expertise;
      if (Object.keys(ent).length) p.wiz.levels[lvl] = ent; else delete p.wiz.levels[lvl];
      prepWizSummary();
    };
}

function prepMissing(){
  const p = state.prep, n = (p.plan && p.plan.needs) || {}, miss = [];
  if (n.skills){
    const ok = ((p.wiz.skills || []).filter(k => (n.skill_options || []).includes(k))).length;
    if (ok < n.skill_count) miss.push(`skills (${n.skill_count - ok} more)`);
  }
  if (n.subclass && !p.wiz.subclass) miss.push("subclass");
  for (const lvl of Object.keys(n.levels || {})){
    const spec = n.levels[lvl], w = p.wiz.levels[lvl] || {};
    if ((spec.feat_choice || spec.ability_boost_or_feat) && !w.feat && !w.ability) miss.push(`level ${lvl} feat/ability`);
    const rc = +spec.cantrips || 0, rs = +spec.spells || 0;
    if (rc && (w.cantrips || []).length < rc) miss.push(`level ${lvl} cantrips`);
    if (rs && (w.spells || []).length < rs) miss.push(`level ${lvl} spells`);
    const re = +spec.expertise || 0;
    if (re){
      const have = new Set((w.expertise || []).filter(k => (spec.expertise_skills || []).includes(k))).size;
      if (have < re) miss.push(`level ${lvl} expertise (${re - have} more)`);
      else if (have > re) miss.push(`level ${lvl} expertise (remove ${have - re})`);
    }
  }
  return miss;   // an open Expert JSON may still fill gaps — the SERVER is the validator
}

function prepCollect(){
  const p = state.prep;
  const out = {};
  if ((p.wiz.skills || []).length) out.skills = p.wiz.skills;
  if (p.wiz.subclass) out.subclass = p.wiz.subclass;
  const lv = {};
  for (const k of Object.keys(p.wiz.levels || {})) lv[k] = p.wiz.levels[k];
  if (Object.keys(lv).length) out.levels = lv;
  if (p.expertOn){
    let extra = null;
    try { extra = JSON.parse($("prep-choices").value || "{}"); }
    catch (e) { throw new Error("Expert choices JSON: " + e.message); }
    if (extra && typeof extra === "object"){
      for (const k of Object.keys(extra)){
        if (k === "levels" && typeof extra.levels === "object")
          out.levels = Object.assign({}, out.levels || {}, extra.levels);
        else out[k] = extra[k];
      }
    }
  }
  return out;
}

function prepWizSummary(){
  const wiz = $("prep-wiz");
  if (!wiz) return;
  const m = wiz.lastElementChild;
  if (m) m.innerHTML = prepMissing().length ? `Still missing: ${esc(prepMissing().join(", "))}` : "All guided choices collected ✔";
}

async function prepPlan(){
  const p = state.prep, ch = prepSelChar();
  if (!ch) return toast("Select or create a character first");
  const cls = $("prep-class").value || ch.char_class;
  if (!cls) return toast("No class selected — pick one from the room's rule pack");
  const to = Math.max(1, Math.min(20, +$("prep-to").value || 1));
  try {
    p.plan = await api(`/build/${p.code}/${ch.id}/plan?class_id=${encodeURIComponent(cls)}&to=${to}`);
    p.planError = "";
    p.wiz = { skills: [], subclass: "", levels: {} };
    renderPrepWizard();
  } catch (e) { toast(e.message); }
}

async function prepApply(){
  const p = state.prep, ch = prepSelChar(), out = $("prep-out");
  if (!ch) return toast("Select or create a character first");
  const cls = $("prep-class").value || ch.char_class;
  const to = Math.max(1, Math.min(20, +$("prep-to").value || 1));
  let choices = {};
  try { choices = prepCollect(); } catch (e) { out.innerHTML = `<span style="color:#e74c3c">${esc(e.message)}</span>`; return; }
  try {
    const r = await fetch(`/api/build/${p.code}/${ch.id}/apply`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ class_id: cls, to, choices }) });
    const j = await r.json();
    if (j.ok){
      toast(`Built to level ${j.result.level}`);
      out.innerHTML = `<span style="color:#9d9">✔ built to ${j.result.level} · max HP ${j.result.max_hp}</span>`;
      p.plan = null; p.wiz = { skills: [], subclass: "", levels: {} };
      await prepRefresh();
    } else if (j.needs_choice){
      const names = [];
      for (const n of j.needs_choice){
        if (n.kind === "skills") names.push(`${n.count} skills from: ${n.options.map(prepSkillLabel).join(", ")}`);
        else if (n.kind === "subclass") names.push(`subclass (${(n.options || []).join(", ")})`);
        else if (n.kind === "level_choice") names.push(`level ${n.level}: ${n.feat_choice ? "feat" : ""}${n.feat_choice && n.ability_boost_or_feat ? " or " : ""}${n.ability_boost_or_feat ? "ability +2" : ""}`);
        else if (n.kind === "spells") names.push(`level ${n.level}: ${n.cantrips || 0} cantrip(s), ${n.spells || 0} spell(s)`);
        else if (n.kind === "expertise") names.push(`level ${n.level}: ${n.count} expertise choice(s) from: ${(n.options||[]).map(prepSkillLabel).join(", ")}`);
        else names.push(JSON.stringify(n));
      }
      out.innerHTML = `<span style="color:#f1c40f">Server still needs choices:</span><br><small>${esc(names.join(" · "))}</small>`;
      toast("Decisions missing — the guided fields show what's needed");
    } else {
      out.innerHTML = `<span style="color:#e74c3c">${esc(j.error || j.reason || "refused")}</span>`;
    }
  } catch (e) { out.textContent = e.message; }
}

/* ---------------- identity / seat / gear / import ---------------- */

async function prepSaveIdentity(){
  const ch = prepSelChar(); if (!ch) return toast("No character selected");
  const sp = $("prep-species").value, cls = $("prep-class").value, bg = $("prep-bg").value;
  const spName = ((state.prep.options.species || []).find(o => o.id === sp) || {}).name;
  const p = { name: ch.name, race: spName || ch.race, char_class: cls || ch.char_class,
              background: bg, stats: ch.stats || {}, hp: ch.hp, max_hp: ch.max_hp,
              ac: ch.ac, speed: ch.speed, notes: ch.notes || "",
              weapons: (ch.weapons || []).filter(w => w && w.name), items: ch.items || [],
              skills: ch.skills || {}, saves: ch.saves || {}, defenses: ch.defenses || {},
              resources: ch.resources || [] };
  try { await api(`/characters/${ch.id}`, "PUT", p); toast("Identity saved"); await prepRefresh(); }
  catch (e) { toast(e.message); }
}

async function prepCreate(){
  const p = state.prep, name = $("prep-name").value.trim();
  if (!name) return toast("A name is required");
  const sp = $("prep-species").value, cls = $("prep-class").value, bg = $("prep-bg").value;
  const spName = ((p.options.species || []).find(o => o.id === sp) || {}).name || "";
  try {
    const c = await api("/characters", "POST", { name, race: spName, char_class: cls, background: bg });
    p.newMode = false; p.selChar = c.id;
    toast(`${c.name} created`);
    await prepRefresh();
  } catch (e) { toast(e.message); }
}

async function prepAssign(){
  const ch = prepSelChar(); if (!ch) return toast("No character selected");
  try {
    await api(`/rooms/${state.prep.code}/assign`, "POST", { character_id: ch.id });
    toast(`${ch.name} takes a seat at the table`);
    await prepRefresh();
  } catch (e) { toast(e.message); }
}

/* D105: the gear step is server-driven. GET resolves the pack (names only,
   errors included), choice groups arrive as radio fields, and ONE POST with
   the picks is the only grant path — the client never names an item id. */
async function prepGear(){
  const ch = prepSelChar(), out = $("prep-gear-out"); if (!ch) return toast("No character selected");
  try {
    state.prep.gearReport = await api(`/rooms/${state.prep.code}/starting-gear/${ch.id}`);
    renderGearReport();
  } catch (e) { out.innerHTML = `<span style="color:#e74c3c">${esc(e.message)}</span>`; }
}
function renderGearReport(){
  const p = state.prep, j = p.gearReport, out = $("prep-gear-out");
  if (!j){ out.innerHTML = ""; return; }
  const bg = j.background, cl = j.class, parts = [];
  if (!bg) parts.push("<span style='opacity:.7'>No background set — only the class kit can be granted.</span>");
  else if (bg.error) parts.push(`<span style="color:#f1c40f">${esc(bg.error)}</span>`);
  else parts.push(`<b>Background</b> ${bg.items.map(i => `${i.qty} × ${esc(i.name)}`).join(", ") || "<i>nothing listed</i>"}` +
    ((bg.skipped || []).length ? `<br><small style="opacity:.8">Not grantable from this pack (no item definition for): ${esc(bg.skipped.join(", "))}</small>` : ""));
  if (cl && cl.status === "not_in_pack")
    parts.push(`<small style="opacity:.8">Class '${esc(cl.id)}' is not in this room's rule pack — no class kit.</small>`);
  else if (cl && cl.status === "already")
    parts.push("<span style='color:#9d9'>Class kit already granted — the original choices stand, nothing will be added or changed.</span>");
  else if (cl && cl.status === "invalid")
    parts.push(`<span style="color:#e74c3c">Class kit incomplete — nothing will be granted until the pack is fixed: ${esc((cl.errors || []).join("; "))}</span>`);
  else if (cl && ((cl.fixed || []).length || (cl.groups || []).length)){
    parts.push(`<b>Class kit</b> ${(cl.fixed || []).map(i => `${i.qty} × ${esc(i.name)}`).join(", ") || "<i>nothing fixed</i>"}`);
    for (const g of cl.groups || [])
      parts.push(`<div class="row" style="flex-wrap:wrap"><b>${esc(g.label)}:</b> ` +
        g.options.map(o => `<label class="tiny" style="margin:1px 6px"><input type="radio" name="gear-${esc(g.label)}" value="${esc(o.token)}"> ${o.qty} × ${esc(o.name)}${o.resolved ? "" : " ⚠"}</label>`).join("") + "</div>");
  }
  const ready = !!((bg && !bg.error) || (cl && (cl.status === "gear" || cl.status === "needs_choice")));
  out.innerHTML = parts.join("<br>") +
    `<div class="row"><button id="prep-gear-grant" class="primary" ${ready ? "" : "disabled"}>🎒 Grant equipment</button></div>` +
    `<div id="prep-gear-result" class="meta"></div>`;
  const g = $("prep-gear-grant"); if (g) g.onclick = prepGearGrant;
}
async function prepGearGrant(){
  const p = state.prep, ch = prepSelChar(), res = $("prep-gear-result"); if (!ch || !res) return;
  const picks = {};
  for (const r of $("prep-gear-out").querySelectorAll("input[type=radio]:checked"))
    picks[r.name.replace(/^gear-/, "")] = r.value;
  try {
    const j = await api(`/rooms/${p.code}/starting-gear`, "POST", { character_id: ch.id, class_choices: picks });
    const gset = (rows, label) => (rows && rows.length)
      ? `<span style="color:#9d9">${label}: ${rows.map(r => `${r.qty} × ${esc(r.name)}`).join(", ")}</span>` : "";
    const lines = [gset(j.granted, "Background"), gset(j.class_granted, "Class kit")];
    if (j.error) lines.push(`<small style="color:#f1c40f">${esc(j.error)}</small>`);
    if (j.already) lines.push("<i>Background already granted earlier — nothing duplicated.</i>");
    if (j.class_status === "already") lines.push("<i>Class kit already granted earlier — the original choices stand.</i>");
    if (j.class_status === "needs_choice") lines.push(`<span style="color:#f1c40f">Choose first: ${esc((j.needs_choice || []).join(", "))}</span>`);
    if (j.class_status === "invalid") lines.push(`<span style="color:#e74c3c">${esc((j.class_errors || []).join("; "))}</span>`);
    if ((j.skipped || []).length) lines.push(`<small style="opacity:.8">Not grantable from this pack (no item definition for): ${esc(j.skipped.join(", "))}</small>`);
    res.innerHTML = lines.filter(Boolean).join("<br>") || "<small style='opacity:.7'>Nothing to grant.</small>";
    await prepRefresh();
  } catch (e) { res.innerHTML = `<span style="color:#e74c3c">${esc(e.message)}</span>`; }
}

/* ---------------- D108: 2024 character origin (background ASI + Origin feat)
   ---------------- The server owns every decision: it returns the report (three
   allowed abilities + their current values, the Origin feat, all refusal
   reasons), the client only ever picks a DISTRIBUTION — feat id and amounts are
   never sent. UI checks below are guidance, never authority. */
async function prepOrigin(){
  const ch = prepSelChar(), out = $("prep-origin-out"); if (!ch) return toast("No character selected");
  try {
    state.prep.originReport = await api(`/build/${state.prep.code}/${ch.id}/origin`);
    state.prep.originSel = null;
    renderOriginReport();
  } catch (e){ out.innerHTML = `<span style="color:#e74c3c">${esc(e.message)}</span>`; }
}
function renderOriginReport(){
  const p = state.prep, j = p.originReport, out = $("prep-origin-out");
  if (!j){ out.innerHTML = ""; return; }
  const lbl = a => ((STATS.find(s => s[0] === a) || [a, a.toUpperCase()])[1]);
  const parts = [];
  const bgList = (x) => (x || []).map(v => esc(v)).join(", ");
  const bgInfo = [j.background_feature,
    (j.background_languages || []).length ? "Languages: " + bgList(j.background_languages) : "",
    (j.background_tool_prof || []).length ? "Tool proficiencies: " + bgList(j.background_tool_prof) : ""]
    .filter(Boolean).join(" · ");
  if (j.applied){
    const as = Object.entries(j.applied.asi || {}).map(([k, v]) => `${esc(lbl(k))} +${v}`).join(", ");
    out.innerHTML = `<span style="color:#9d9">Origin already granted</span> — ` +
      `background <b>${esc(j.applied.background || j.background_name || "")}</b> · ${as} · ` +
      `${bgInfo || "no background details in the rule pack"} · ` +
      `the build ledger keeps the proof; nothing can be granted twice.`;
    return;
  }
  if ((j.errors || []).length) parts.push(`<span style="color:#f1c40f">${esc(j.errors.join("; "))}</span>`);
  const ab = j.asi_abilities || [];
  if (!j.background){ out.innerHTML = parts.join("<br>") || "<span style='opacity:.7'>Save a background first.</span>"; return; }
  parts.push(`<b>${esc(j.background_name)}</b> · ability scores this origin may raise: ${ab.map(a => esc(lbl(a))).join(", ") || "—"}`);
  if (j.feat) parts.push(`Origin feat: <b>${esc(j.feat.name)}</b> — ${esc(j.feat.effect || "see feat text")}`);
  if (j.background_feature) parts.push(`Background feature: <b>${esc(j.background_feature)}</b>`);
  if ((j.background_languages || []).length) parts.push(`Languages: ${bgList(j.background_languages)}`);
  if ((j.background_tool_prof || []).length) parts.push(`Tool proficiencies: ${bgList(j.background_tool_prof)}`);
  const sel = p.originSel || (p.originSel = {mode: "plus2_plus1", plus2: ab[0] || "", plus1: ab[1] || ab[0] || ""});
  parts.push(`<div class="row" style="flex-wrap:wrap">` +
    `<label class="tiny"><input type="radio" name="org-mode" value="plus2_plus1" ${sel.mode === "plus2_plus1" ? "checked" : ""}> +2 and +1</label>` +
    `<label class="tiny"><input type="radio" name="org-mode" value="three" ${sel.mode === "three" ? "checked" : ""}> +1 to all three</label></div>`);
  if (sel.mode === "plus2_plus1")
    parts.push(`<div class="row">` +
      `<select id="org-p2">${ab.map(a => `<option value="${esc(a)}" ${sel.plus2 === a ? "selected" : ""}>+2 ${esc(lbl(a))}</option>`).join("")}</select>` +
      `<select id="org-p1">${ab.map(a => `<option value="${esc(a)}" ${sel.plus1 === a ? "selected" : ""}>+1 ${esc(lbl(a))}</option>`).join("")}</select></div>`);
  const deltas = sel.mode === "three" ? Object.fromEntries(ab.map(a => [a, 1]))
                                      : {[sel.plus2]: 2, [sel.plus1]: 1};
  const cur = j.current || {};
  const sameSel = sel.mode === "plus2_plus1" && !!sel.plus2 && sel.plus2 === sel.plus1;
  const pv = ab.map(a => {
    const now = cur[a] === undefined ? 10 : cur[a], d = deltas[a] || 0, after = now + d, bad = !!d && after > 20;
    return `${esc(lbl(a))} ${now}${d ? ` → <span style="color:${bad ? "#e74c3c" : "#9d9"}">${after}</span>` : ""}${bad ? " (&gt;20!)" : ""}`;
  });
  if (sameSel) parts.push(`<div><span style="color:#e74c3c">+2 and +1 must go to DIFFERENT abilities</span></div>`);
  parts.push(`<div>Preview: ${pv.join(" · ") || "—"}</div>`);
  const ok = j.ready && !sameSel && !pv.some(s => s.includes("&gt;20"));
  parts.push(`<div class="row"><button id="prep-origin-apply" class="primary" ${ok ? "" : "disabled"}>🧬 Apply origin</button></div>` +
             `<div id="prep-origin-result" class="meta"></div>`);
  out.innerHTML = parts.join("<br>");
  for (const r of out.querySelectorAll("input[name=org-mode]"))
    r.onchange = () => { p.originSel.mode = r.value; renderOriginReport(); };
  const s2 = $("org-p2"), s1 = $("org-p1");
  if (s2) s2.onchange = () => { p.originSel.plus2 = s2.value; renderOriginReport(); };
  if (s1) s1.onchange = () => { p.originSel.plus1 = s1.value; renderOriginReport(); };
  const b = $("prep-origin-apply"); if (b) b.onclick = prepOriginApply;
}
async function prepOriginApply(){
  const p = state.prep, ch = prepSelChar(), res = $("prep-origin-result"); if (!ch || !res) return;
  const sel = p.originSel || {};
  const asi = sel.mode === "three" ? {mode: "three"}
                                  : {mode: "plus2_plus1", plus2: sel.plus2, plus1: sel.plus1};
  try {
    const j = await api(`/build/${p.code}/${ch.id}/origin`, "POST", {asi});
    if (j.ok)
      res.innerHTML = j.result.already
        ? "<i>Origin was granted earlier — the ledger says: nothing added.</i>"
        : `<span style="color:#9d9">Origin granted</span> — ${esc(j.result.feat || "Origin feat")} applied`;
    else res.innerHTML = `<span style="color:#e74c3c">${esc(j.error || "refused")}</span>`;
    await prepRefresh();
  } catch (e){ res.innerHTML = `<span style="color:#e74c3c">${esc(e.message)}</span>`; }
}

async function prepUpload(){
  const files = [...(($("prep-ct-file") || {}).files || [])];
  if (!files.length) return toast("Pick a CSV or ZIP first");
  const box = $("prep-ct-report"); box.innerHTML = "";
  for (const f of files){
    try {
      const rep = await ctPost(f, $("prep-ct-mode").value);
      ctRender(rep, "prep-ct-report");
    } catch (e) {
      const d = document.createElement("div"); d.className = "journal-item";
      d.innerHTML = `<b>${esc(f.name)}</b> <small style="color:#e74c3c">${esc(e.message)}</small>`;
      box.appendChild(d);
    }
  }
  await prepRefresh();
}

function backToPrep(){
  clearTimeout(state.reconnectTimer);
  if (state.ws){ state.ws.onclose = null; state.ws.close(); state.ws = null; }
  const code = state.room && state.room.code;
  state.room = null; editorClose();
  if (code) openPrep(code).catch(() => loadLobby());   // room vanished → lobby, not a red banner
  else loadLobby();
}

function wirePrep(){
  const p = () => state.prep;
  $("prep-back").onclick = () => { state.room = null; loadLobby().catch(() => show("auth")); };
  $("prep-char").onchange = (e) => { if (p()){ p().selChar = +e.target.value || null; p().plan = null; p().gearReport = null;     p().originReport = null; p().originSel = null;
    const oe = $("prep-origin-out"); if (oe) oe.innerHTML = "";
    p().wiz = { skills: [], subclass: "", levels: {} }; renderPrep(); } };
  $("prep-new-toggle").onclick = () => {
    const q = p(); if (!q) return;
    q.newMode = !q.newMode;
    if (q.newMode){ $("prep-name").value = ""; q.plan = null; }
    renderPrep();
  };
  $("prep-create").onclick = prepCreate;
  $("prep-id-save").onclick = prepSaveIdentity;
  $("prep-plan").onclick = prepPlan;
  $("prep-apply").onclick = prepApply;
  $("prep-expert").onchange = (e) => {
    p().expertOn = e.target.checked;
    $("prep-choices-row").classList.toggle("hidden", !e.target.checked);
    if (e.target.checked && !$("prep-choices").value)
      $("prep-choices").value = JSON.stringify(p().wiz || {}, null, 1);
    renderPrepWizard();
  };
  $("prep-assign").onclick = prepAssign;
  $("prep-gear").onclick = prepGear;
  $("prep-origin").onclick = prepOrigin;
  $("prep-table").onclick = () => { const code = state.prep && state.prep.code; if (code) openRoom(code); };
  $("prep-ct-upload").onclick = prepUpload;
  const bp = $("btn-prep");
  if (bp) bp.onclick = backToPrep;
}
