/* ---------- 70_content.js — DM CSV rule-package import/export (D95) ----------
   Talks to /api/content/{code}. Transport is multipart-free: a file's RAW BYTES
   are POSTed (the server auto-detects .csv vs .zip), so no new dependency.
   Import runs the caller's mode (preview/apply/replace) per file; the report is
   rendered with file/line/column detail. Export downloads a single kind as CSV
   or the whole room as a ZIP. DM-only (the panel lives in the DM tab). */
(typeof window !== "undefined") && ((window.__BUILDS = window.__BUILDS || {})["70_content.js"] = window.__BUILD__ || "?");

const CT_KINDS = ["species", "class", "subclass", "item", "spell", "background", "feat", "creature"];

async function ctPost(file, mode) {
  const code = state.room.code;
  const url = `/api/content/${code}/import?name=${encodeURIComponent(file.name)}&mode=${mode}`;
  const r = await fetch(url, { method: "POST", body: file,
    headers: { "Content-Type": "application/octet-stream" } });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
  return d;
}

function ctRender(rep, boxId) {
  const box = $(boxId || "ct-report"); if (!box) return;   // D101: prep screen re-uses this renderer
  const parts = [];
  for (const f of (rep.files || [])) {
    const head = document.createElement("div");
    head.className = "journal-item";
    const badge = f.ignored ? "· skipped" : (f.valid ? "· ok" : `· ${f.errors.length} error(s)`);
    head.innerHTML = `<b>${esc(f.file || "?")}</b> <small style="opacity:.7">${esc(badge)}</small>`;
    box.appendChild(head);
    for (const e of (f.errors || []).slice(0, 30)) {
      const row = document.createElement("div");
      row.style.cssText = "padding-left:10px;color:#e74c3c;font-size:.8rem";
      row.textContent = `line ${e.line} · ${e.column}: ${e.msg}`;
      box.appendChild(row);
    }
    for (const w of (f.warnings || []).slice(0, 30)) {
      const row = document.createElement("div");
      row.style.cssText = "padding-left:10px;color:#f1c40f;font-size:.8rem";
      row.textContent = `line ${w.line} · ${w.column}: ${w.msg}`;
      box.appendChild(row);
    }
  }
  for (const [kind, st] of Object.entries(rep.applied || {})) {
    const row = document.createElement("div");
    row.style.cssText = "color:#9bd;font-size:.8rem";
    row.textContent = `${kind}: +${st.inserted} new, ↻${st.replaced} replaced, =${st.unchanged}, ⚠${(st.conflicts || []).length} conflict(s)`;
    box.appendChild(row);
  }
}

async function ctUpload() {
  if (!state.room || state.room.role !== "dm") return;
  const input = $("ct-file"); const files = [...(input.files || [])];
  if (!files.length) { toast("Choose a .csv or .zip first"); return; }
  const mode = $("ct-mode").value;
  const box = $("ct-report"); box.innerHTML = "";
  for (const f of files) {
    try { ctRender(await ctPost(f, mode)); }
    catch (e) {
      const row = document.createElement("div");
      row.style.cssText = "color:#e74c3c";
      row.textContent = `${f.name}: ${e.message}`;
      box.appendChild(row);
    }
  }
  input.value = "";
  if (mode !== "preview") refreshContentKinds();
}

async function ctDownload(kind, all) {
  const code = state.room.code;
  const url = `/api/content/${code}/export` + (all ? "?all=true" : `?kind=${encodeURIComponent(kind)}`);
  const r = await fetch(url);
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || ("HTTP " + r.status)); }
  const cd = r.headers.get("Content-Disposition") || "";
  const m = cd.match(/filename="?([^"]+)"?/);
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = m ? m[1] : (all ? "content.zip" : kind + ".csv");
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

async function refreshContentKinds() {
  const el = $("ct-kinds"); if (!el || !state.room || state.room.role !== "dm") return;
  try {
    const d = await api(`/content/${state.room.code}/kinds`);
    el.textContent = CT_KINDS.map(k => `${k}: ${d.kinds[k] || 0}`).join("  ·  ");
  } catch (e) { el.textContent = "—"; }
}

async function ctCreatureImport(id, button){
  const code = state.room.code;
  button.disabled = true;
  try {
    const r = await fetch(`/api/content/${code}/creature/${encodeURIComponent(id)}/to-bestiary`,
      { method: "POST" });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || ("HTTP " + r.status));
    toast(`${d.projection.name} is in your bestiary`);
    await loadBestiary();
  } catch (e) {
    toast(e.message); button.disabled = false;
  }
}

async function ctCreatures(){
  if (!state.room || state.room.role !== "dm") return;
  const box = $("ct-creatures"), status = $("ct-creature-status");
  box.innerHTML = ""; status.textContent = "Loading…";
  try {
    const d = await api(`/content/${state.room.code}/creature-rows`);
    const rows = d.creatures || [];
    status.textContent = `${rows.length} imported creature row(s)`;
    for (const c of rows){
      const row = document.createElement("div");
      row.className = "journal-item";
      row.style.cssText = "display:flex;justify-content:space-between;gap:8px";
      const b = document.createElement("button");
      b.className = "ghost"; b.type = "button"; b.textContent = "To bestiary";
      b.disabled = !c.ready; b.onclick = () => ctCreatureImport(c.id, b).catch(e => toast(e.message));
      const left = document.createElement("span");
      left.innerHTML = `<b>${esc(c.name)}</b>` +
        (c.companion ? ` <small title="Marked as companion">🐾</small>` : "") +
        ` <small style="opacity:.7">${c.ready ? "NPC block ready" : esc(c.error || "unsupported free-form text")}</small>`;
      row.appendChild(left); row.appendChild(b); box.appendChild(row);
    }
    if (!rows.length) box.innerHTML = '<div class="journal-item">No creature rows in this rule pack.</div>';
  } catch (e){ status.textContent = e.message; }
}

function wireContent() {
  const sel = $("ct-export-kind");
  if (sel && !sel.options.length) for (const k of CT_KINDS) {
    const o = document.createElement("option"); o.value = k; o.textContent = k; sel.appendChild(o);
  }
  if ($("btn-ct-upload")) $("btn-ct-upload").onclick = () => ctUpload().catch(e => toast(e.message));
  if ($("btn-ct-export")) $("btn-ct-export").onclick =
    () => ctDownload($("ct-export-kind").value, false).catch(e => toast(e.message));
  if ($("btn-ct-export-zip")) $("btn-ct-export-zip").onclick =
    () => ctDownload(null, true).catch(e => toast(e.message));
  if ($("btn-ct-creatures")) $("btn-ct-creatures").onclick =
    () => ctCreatures().catch(e => toast(e.message));
}
