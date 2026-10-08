/* ---------- canvas: camera, grid, fog, editor ---------- */
(typeof window !== "undefined") && ((window.__BUILDS = window.__BUILDS || {})["50_canvas.js"] = window.__BUILD__ || "?");
function renderFogToggle(){
  const b = $("btn-fog-toggle"); if (!b) return;
  const on = !!(state.grid && state.grid.fog_off);
  b.classList.toggle("active", on);
  const dk = $("btn-dark-toggle");                 // D87: candle shows the dark flag
  if (dk) dk.classList.toggle("active", !!(state.grid && state.grid.dark));
  b.title = on ? "Fog is OFF — all terrain revealed. Click to restore fog of war."
               : "Show all terrain to every player. Hidden foes still need line of sight.";
}
const cv = $("map"), ctx = cv.getContext("2d");
function cellSize(){ return state.grid ? state.grid.cell : 50; }
/* D85 token artwork: t.image is ONLY ever a server-generated "/assets/<id>"
   URL (never client-typed), drawn inside the token's own rotate frame — one
   rotation, aspect preserved, clipped to the body ellipse. Loaded once per
   url; the first paint kicks a re-render when it arrives. */
const _artCache = {};
function tokenArtwork(t, rx, ry){
  if (!t.image) return false;
  let img = _artCache[t.image];
  if (img === undefined){
    img = _artCache[t.image] = new Image();
    img.onload = () => { if (typeof draw === "function") draw(); };
    img.onerror = () => { _artCache[t.image] = null; };
    img.src = t.image;
    return false;
  }
  if (!img || !img.complete || !img.naturalWidth) return false;
  const k = Math.min(2 * rx / img.naturalWidth, 2 * ry / img.naturalHeight);
  const iw = img.naturalWidth * k, ih = img.naturalHeight * k;
  ctx.save(); ctx.beginPath(); ctx.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2); ctx.clip();
  ctx.drawImage(img, -iw / 2, -ih / 2, iw, ih); ctx.restore();
  return true;
}
/* worldW/H = the map ARRAY's pixel size; worldLeft/Top = where that array sits
   in WORLD pixel space (negative after west/north growth, D72). Entities draw
   at their world pixels; the array is drawn shifted by the origin. */
function worldW(){ return state.grid ? state.grid.w * cellSize() : 2000; }
function worldH(){ return state.grid ? state.grid.h * cellSize() : 1300; }
function worldLeft(){ return state.grid ? gridOrigin(state.grid)[0] * cellSize() : 0; }
function worldTop(){ return state.grid ? gridOrigin(state.grid)[1] * cellSize() : 0; }
function stopTick(){ state.tickOn = false; }
function startTick(){ if (!state.tickOn){ state.tickOn = true; requestAnimationFrame(tick); } }
function resize(){
  const r = cv.parentElement.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  cv.width = r.width * dpr; cv.height = r.height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  clampCam();
}
function view(){ const dpr = window.devicePixelRatio || 1; return { w: cv.width/dpr, h: cv.height/dpr }; }
function clampCam(){
  if (state.viewMode === "diorama") return;   // diorama has its own projected extents
  const { w, h } = view(), W = worldW(), H = worldH(), L = worldLeft(), T = worldTop();
  state.cam.ox = W <= w ? (w - W)/2 + L : Math.min(L, Math.max(w - W + L, state.cam.ox));
  state.cam.oy = H <= h ? (h - H)/2 + T : Math.min(T, Math.max(h - H + T, state.cam.oy));
}
/* ---------- view framing (D75) ----------
   A client opening a room must land ON its own action, not on world (0,0).
   Without this a player whose token lives deep in the world stared at pure
   black: every cell of the initial viewport was unknown, and unknown cells
   render as nothing. Cameras are pure client-local presentation — these
   functions never send anything and never mutate world state. */
function myToken(){
  return (state.tokens || []).find(t => state.me && t.owner_user_id === state.me.id) || null;
}
/* camInit bookkeeping (browser diagnostics): exactly what ran, what it
   decided, and when — so a real-browser black screen classifies itself. */
function camInitMark(step, result, why){
  const s = state._camInit = state._camInit || { step: "-", result: "-", why: "" };
  s.step = step; s.result = result; s.why = why || ""; s.at = new Date().toISOString().slice(11, 23);
  s[step] = result;                       // per-step trace: center/fit/init calls
}
function centerOnMyToken(){
  const t = myToken();
  if (!t){ camInitMark("center", "no-token", "player owns no token (Bring a character?)"); return; }
  if (!state.grid){ camInitMark("center", "no-grid", "no map payload yet"); return; }
  const { w, h } = view();
  state.cam.ox = w / 2 - t.x; state.cam.oy = h / 2 - t.y;
  clampCam();
  camInitMark("center", "ok", `token ${t.id} @${Math.round(t.x)},${Math.round(t.y)}`);
}
/* Diorama projection (dioProj) has an unbounded iso bounding box — a 40x26
   map can span y up to ~800+ px, so an unframed diorama shows almost nothing
   of the world (manual regression: "Diorama is a one-way door"). fitDiorama
   centres the camera on the viewer's KNOWN content (visible tiles + tokens). */
function fitDiorama(){
  const g = state.grid, c = cellSize();
  if (!g || !g.cells){ camInitMark("fit", "no-grid", "no map payload yet"); return; }
  const [ox, oy] = gridOrigin(g);
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity, n = 0;
  const iso = (lx, ly) => [ (lx - ly) * c * 0.5, (lx + ly) * c * 0.25 ];  // raw, no cam
  const add = p => { n++; if (p[0] < minX) minX = p[0]; if (p[0] > maxX) maxX = p[0];
                     if (p[1] < minY) minY = p[1]; if (p[1] > maxY) maxY = p[1]; };
  // sample the KNOWN lattice (same mask as the renderer — reveals nothing)
  const step = Math.max(1, Math.round(Math.sqrt(g.w * g.h) / 60));
  for (let gy = 0; gy < g.h; gy += step) for (let gx = 0; gx < g.w; gx += step){
    if (!visibleHere(gy * g.w + gx)) continue;
    add(iso(gx + ox, gy + oy));
  }
  for (const t of (state.tokens || [])){
    const [tx, ty] = [Math.floor(t.x / c), Math.floor(t.y / c)];
    if (!visibleHere(wIdx(g, tx, ty))) continue;
    add(iso(tx + .5, ty + .5));
  }
  if (!n){ centerOnMyTokenD();
    camInitMark("fit", myToken() ? "fallback-token" : "no-known-content",
                myToken() ? "own token" : "nothing known and no own token");
    return; }
  const { w, h } = view();
  state.cam.ox = w / 2 - (minX + maxX) / 2;
  state.cam.oy = h / 2 - (minY + maxY) / 2;
  state.camD.ox = state.cam.ox; state.camD.oy = state.cam.oy;
  camInitMark("fit", "ok", `${n} known samples`);
}
function centerOnMyTokenD(){       // diorama fallback: point at own token
  const t = myToken(); if (!t) return;
  const c = cellSize(), { w, h } = view();
  const p = [ (t.x / c - t.y / c) * c * 0.5, (t.x / c + t.y / c) * c * 0.25 ];
  state.cam.ox = w / 2 - p[0]; state.cam.oy = h / 2 - p[1];
}
function initViewCam(){
  state._camInitCalls = (state._camInitCalls || 0) + 1;
  if (state.viewMode === "diorama" ) { if (typeof fitDiorama === "function") fitDiorama(); }
  else centerOnMyToken();
}
/* Late-token safety net: if framing once ran WITHOUT an own token (player
   joins before taking a seat, token arrives via WS later), frame the moment
   the token shows up — once. Never touches an already-framed camera. */
function maybeInitViewCam(){
  if (state._camInit && state._camInit.result === "ok") return;
  if (state.grid && myToken()) initViewCam();
}
/* ---------- dev diagnostics (D75, ?debug) ----------
   Everything shown is data THIS viewer already legitimately has (its own
   filtered payload) — counts only, never hidden entities or cells. */
const DEBUG = typeof location !== "undefined" && /[?&]debug/.test(location.search);
function dbgErr(e, where){
  state._dbgErr = `${where}: ${e && e.message ? e.message : String(e)} @` +
                  new Date().toISOString().slice(11, 19);
  if (DEBUG && typeof console !== "undefined" && console.error) console.error("[dbg]", state._dbgErr, e);
}
if (DEBUG && typeof window !== "undefined"){
  window.addEventListener("error", ev => dbgErr(ev.error || ev.message, "window"));
  window.addEventListener("unhandledrejection", ev => dbgErr(ev.reason, "promise"));
}
function debugHud(){
  const el = $("dbg"); if (!DEBUG || !el) return;
  const now = Date.now(); if (now - (state._dbgAt || 0) < 400) return; state._dbgAt = now;
  const g = state.grid, c = cellSize(), t = myToken();
  const dpr = (typeof window !== "undefined" && window.devicePixelRatio) || 1;
  const cvSize = `${Math.round(cv.width / dpr)}x${Math.round(cv.height / dpr)}@dpr${dpr}`;
  const fns = `fns[C=${typeof centerOnMyToken === "function" ? "y" : "!"},` +
              `F=${typeof fitDiorama === "function" ? "y" : "!"}]`;
  const cam = `${Math.round(state.cam.ox)},${Math.round(state.cam.oy)}`;
  const w = typeof window !== "undefined" ? window : {};
  const integ = w.__INTEGRITY ? (w.__INTEGRITY.ok ? (w.__INTEGRITY.serverMismatch ? "DRIFT" : "ok") : "FAIL") : "-";
  const bootErr = (w.__BOOTERRORS && w.__BOOTERRORS.length)
    ? w.__BOOTERRORS[w.__BOOTERRORS.length - 1].msg : "";
  const head = `build=${w.__BUILD__ || "?"} integrity=${integ} | ` +
               `view=${state.viewMode} | canvas=${cvSize} | cam(${cam}) ` +
               `T(${Math.round(state.camT.ox)},${Math.round(state.camT.oy)}) ` +
               `D(${Math.round(state.camD.ox)},${Math.round(state.camD.oy)}) | ${fns} | ` +
               `camInit=${JSON.stringify(state._camInit || "-")} x${state._camInitCalls || 0}`;
  if (!g || !g.cells){
    el.textContent = `${head} | grid=n | bring=${state._bringLast || "-"} | NO MAP PAYLOAD` +
                     (bootErr ? ` | BOOTERR: ${bootErr}` : "");
    el.classList.add("dbg-err"); el.title = el.textContent; return;
  }
  const [ox, oy] = gridOrigin(g);
  let known = 0, expl = 0;
  for (let i = 0; i < g.cells.length; i++){
    if (g.cells[i] !== null && g.cells[i] !== undefined) known++;
    if (g.explored && g.explored[i]) expl++;
  }
  const cell = t ? `${t.id}@(${Math.floor(t.x / c)},${Math.floor(t.y / c)}) px${Math.round(t.x)},${Math.round(t.y)}` : "NONE";
  const scr  = t ? `${Math.round(t.x + state.cam.ox)},${Math.round(t.y + state.cam.oy)}` : "-";
  let txt = `${head} | grid=y win[${ox},${oy}] ${g.w}x${g.h}@${c} | tok=${cell} scr=${scr} | ` +
            `known=${known} explored=${expl} painted=${state._dbgPaint || 0} | ` +
            `bring=${state._bringLast || "-"}`;
  if (!t) txt += " | ⚠ NO OWN TOKEN (Bring a character)";
  const lastErr = state._dbgErr || bootErr;
  if (lastErr) txt += ` | ERR: ${lastErr}`, el.classList.add("dbg-err");
  else el.classList.remove("dbg-err");
  el.textContent = txt;
  el.title = txt;
}
function tick(){
  if (!state.tickOn || !state.room) return;
  debugHud();
  let moved = false;
  for (const t of state.tokens)
    if (t.atx != null && (Math.abs(t.atx - t.x) > .5 || Math.abs(t.aty - t.y) > .5)){
      t.x += (t.atx - t.x) * .35; t.y += (t.aty - t.y) * .35; moved = true;
    } else if (t.atx != null){ t.x = t.atx; t.y = t.aty; t.atx = t.aty = null; }
  const k = 14;
  if (state.keys.size){
    if (state.keys.has("ArrowLeft")||state.keys.has("a")) state.cam.ox += k;
    if (state.keys.has("ArrowRight")||state.keys.has("d")) state.cam.ox -= k;
    if (state.keys.has("ArrowUp")||state.keys.has("w")) state.cam.oy += k;
    if (state.keys.has("ArrowDown")||state.keys.has("s")) state.cam.oy -= k;
    clampCam(); moved = true;
  }
  try { draw(); }
  catch (e){ dbgErr(e, "draw"); }              // the loop must not die on a frame error
  requestAnimationFrame(tick);
}
function visibleHere(i){
  const g = state.grid; if (!g || i == null || i < 0) return false;
  if (state.room && state.room.role === "dm") return true;
  return g.cells && g.cells[i] !== null && g.cells[i] !== undefined;
}
/* Single view dispatch point. All existing call sites (tick, fog_changed,
   pings, AoE, ...) keep calling draw() and follow the active client-local
   view. Editing always uses the tactical renderer. */
function draw(){
  if (!ctx || !state.room) return;
  try {
    if (state.viewMode === "diorama" && !state.editing){ drawDiorama(); return; }
    drawTactical();
  } catch (e){ dbgErr(e, state.viewMode); throw e; }   // visible in ?debug, still fatal (no silent breakage)
}
function drawTactical(){
  const { w, h } = view(), c = cellSize(), cam = state.cam;
  const gm = state.editing && state.editMap ? state.editMap : state.grid;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#0a0b10"; ctx.fillRect(0, 0, w, h);
  const ox = gm ? gridOrigin(gm)[0] : 0, oy = gm ? gridOrigin(gm)[1] : 0;
  // visible range in STORAGE cells: world px [-cam] minus the origin offset
  const x0 = Math.max(0, Math.floor(-cam.ox / c) - ox), y0 = Math.max(0, Math.floor(-cam.oy / c) - oy);
  const x1 = Math.min(gm ? gm.w : 0, Math.ceil((w - cam.ox) / c) - ox),
        y1 = Math.min(gm ? gm.h : 0, Math.ceil((h - cam.oy) / c) - oy);
  if (gm){
    let painted = 0;
    for (let gy = y0; gy < y1; gy++) for (let gx = x0; gx < x1; gx++){
      const i = gy * gm.w + gx, sx = (gx + ox)*c + cam.ox, sy = (gy + oy)*c + cam.oy;
      const known = state.editing || visibleHere(i);
      if (!known){ continue; }
      painted++;
      const ter = gm.cells[i];
      if (ter === 1) { ctx.fillStyle = "#3a4157"; ctx.fillRect(sx, sy, c, c);
        ctx.fillStyle = "#232838"; ctx.fillRect(sx+2, sy+2, c-4, c-4); }
      else if (ter === 2){ ctx.fillStyle = "#20281d"; ctx.fillRect(sx, sy, c, c);
        ctx.strokeStyle = "#2e3a29"; ctx.beginPath();
        ctx.moveTo(sx+4, sy+c-6); ctx.lineTo(sx+c/2, sy+c/3); ctx.lineTo(sx+c-4, sy+c-6); ctx.stroke(); }
      else if (ter === 3){ ctx.fillStyle = "#3a2b2b"; ctx.fillRect(sx, sy, c, c);
        ctx.strokeStyle = "#7d4b4b"; ctx.lineWidth = 2; ctx.strokeRect(sx+4.5, sy+4.5, c-9, c-9);
        ctx.lineWidth = 1; }
      else if (ter === 4){ ctx.fillStyle = "#26231b"; ctx.fillRect(sx, sy, c, c);
        ctx.fillStyle = "#4a4232"; ctx.beginPath();
        ctx.arc(sx+c*0.35, sy+c*0.6, c*0.13, 0, 7); ctx.arc(sx+c*0.65, sy+c*0.42, c*0.16, 0, 7); ctx.fill(); }
      else { ctx.fillStyle = "#151823"; ctx.fillRect(sx, sy, c, c); }
      const el = gm.elev && gm.elev[i];
      if (el){ ctx.fillStyle = el > 0 ? "#8fb3ff" : "#b0785a";
        ctx.font = `${Math.max(8, c/4)}px sans-serif`;
        ctx.fillText((el > 0 ? "+" : "") + el, sx+3, sy+c-4); }
      ctx.strokeStyle = "#232735"; ctx.strokeRect(sx+.5, sy+.5, c, c);
    }
    if (state.bg && state.bg.complete && state.bg.naturalWidth){
      ctx.globalAlpha = .9;
      ctx.drawImage(state.bg, cam.ox + ox*c, cam.oy + oy*c, gm.w*c, gm.h*c);
      ctx.globalAlpha = 1;
    }
    const marks = gm ? []
      .concat((gm.traps||[]).map(t=>[t,"⚠","#e74c3c"]),
              (gm.loot||[]).map(l=>[l,"🎁","#d4a017"]),
              // D82: world objects. Players only ever RECEIVE visible objects
              // (mapmodel.visible_map filters them), so any object in the
              // payload may be drawn. State on/off is part of the world.
              (gm.objects||[]).map(o=>[o, _objKind(o)==="lamp" ? "💡" : o.interact ? "🕹" : "•",
                                       o.state && o.state.on ? "#2ecc71" : "#7f8c8d", "obj"])) : [];
    for (const [e, ic, col, kind] of marks){
      const isDM = state.room.role === "dm";
      const known = kind === "obj" || state.editing || isDM || e.discovered || e.taken_by === state.me.id;
      if (!known) continue;                       // still a hidden secret for this viewer
      const sx = e.x*c + cam.ox + c/2, sy = e.y*c + cam.oy + c/2;
      ctx.save();
      ctx.globalAlpha = e.discovered ? .95 : .8;
      ctx.beginPath(); ctx.arc(sx, sy, c*0.30, 0, Math.PI*2);
      ctx.fillStyle = col; ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = "rgba(0,0,0,.45)"; ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.font = `${c*.34}px sans-serif`; ctx.textAlign = "center";
      ctx.fillText(ic, sx, sy + c*.12);           // white glyph reads on any emoji font
      ctx.restore();
      // D89: a lit lamp glows on the map — the light itself is what the
      // server's vision uses; the circle is its honest on-map echo.
      if (kind === "obj" && _objKind(e) === "lamp" && !(e.state && e.state.on === false)){
        ctx.save(); ctx.globalAlpha = .14; ctx.beginPath();
        ctx.arc(sx, sy, c*(.5 + ((e.interact.bright != null ? e.interact.bright
                                 : (e.interact.op && e.interact.op.bright) || 5))), 0, Math.PI*2);
        ctx.fillStyle = "#f5c542"; ctx.fill(); ctx.restore();
      }
      if (e.taken_by != null && e.taken_by !== 0){ ctx.strokeStyle = "#555"; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(sx-c*.2, sy-c*.2); ctx.lineTo(sx+c*.2, sy+c*.2); ctx.stroke(); }
    }
    for (const d of (gm.doors || [])) drawDoor(d, c, cam);
    for (const pin of (gm.pins || [])) drawPin(pin, c, cam, state.editing || state.room.role === "dm" || visibleHere(wIdx(gm, pin.x, pin.y)));
    state._dbgPaint = painted;
  }
  if (state.plan && (state.plan.cells || state.plan.path)){
    const preview = state.plan.cells || state.plan.path.map(p => ({x:p.x, y:p.y}));
    for (const pt of preview){
      const rx = pt.x*c + cam.ox, ry = pt.y*c + cam.oy;
      ctx.fillStyle = "rgba(212,160,23,0.22)"; ctx.fillRect(rx, ry, c, c); }
    const gp = state.plan.anchor || state.plan.goal, pw = state.plan.w || state.plan.side || 1,
          ph = state.plan.h || pw;
    // D84: ring marks the landing FOOTPRINT box (anchor-based); the aim point
    // (state.plan.goal) is the centre the player clicked — both in world cells.
    const gx = (gp.cx + (pw-1)/2)*c + c/2 + cam.ox, gy = (gp.cy + (ph-1)/2)*c + c/2 + cam.oy;
    ctx.strokeStyle = "#d4a017"; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(gx, gy, c*.38*Math.max(pw, ph), 0, Math.PI*2); ctx.stroke();
  }
  if (state.aoe && Date.now() < state.aoe.exp && gm){
    ctx.fillStyle = hexA(state.aoe.color, .26);
    for (const pt of state.aoe.cells){ const rx = pt.x*c + cam.ox, ry = pt.y*c + cam.oy;   // WORLD cells
      ctx.fillRect(rx, ry, c, c); }
  }
  for (const gh of state.ghosts){
    if (!onPlane(gh)) continue;                   // D86: fog memories of the wrong plane stay put
    const gx = gh.x + cam.ox, gy = gh.y + cam.oy;
    if (gx < -40 || gy < -40 || gx > w+40 || gy > h+40) continue;
    ctx.save(); ctx.globalAlpha = .32;
    ctx.beginPath(); ctx.arc(gx, gy, 16, 0, Math.PI*2);
    ctx.fillStyle = gh.color; ctx.fill();
    ctx.setLineDash([4,3]); ctx.strokeStyle = "#9aa"; ctx.lineWidth = 2; ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#cfd3e0"; ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center";
    ctx.fillText((gh.label||"?").slice(0,2).toUpperCase(), gx, gy + 4);
    ctx.restore();
  }
  if (state.ruler && gm){
    const a = [state.ruler.x1*c + cam.ox + c/2, state.ruler.y1*c + cam.oy + c/2];
    const b = [state.ruler.x2*c + cam.ox + c/2, state.ruler.y2*c + cam.oy + c/2];
    ctx.save(); ctx.strokeStyle = "#7fd1ff"; ctx.lineWidth = 3; ctx.setLineDash([7,5]);
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke(); ctx.setLineDash([]);
    const dx = Math.abs(state.ruler.x2 - state.ruler.x1), dy = Math.abs(state.ruler.y2 - state.ruler.y1);
    const diag = Math.min(dx,dy), ortho = Math.max(dx,dy);
    const feet = (ortho - diag)*5 + diag*10;
    ctx.fillStyle = "#7fd1ff"; ctx.font = "bold 13px sans-serif"; ctx.textAlign="center";
    ctx.fillText(`${feet} ft`, (a[0]+b[0])/2, (a[1]+b[1])/2 - 8);
    ctx.restore();
  }
  for (const p of (state.pings || [])){
    const age = Math.max(0, Math.min(1, (p.exp - Date.now()) / 2500));
    const px = p.x + cam.ox, py = p.y + cam.oy;
    ctx.save(); ctx.globalAlpha = age * .75;
    ctx.beginPath(); ctx.arc(px, py, (1-age)*c*.8 + c*.2, 0, Math.PI*2);
    ctx.strokeStyle = p.color || "#f1c40f"; ctx.lineWidth = 4; ctx.stroke();
    ctx.restore();
  }
  for (const t of state.tokens){
    if (!onPlane(t)) continue;                    // D86: other planes are elsewhere
    // tw/th NEVER w/h: this loop's scope owns the viewport dimensions w/h —
    // shadowing them here made the culling check drop every token offscreen (15B).
    const [tw, th] = tokenSpan(t);
    const [vw, vh] = baseVisualSpan(t), vside = Math.max(vw, vh);
    const ox = t.x + ((tw - 1) * c / 2), oy = t.y + ((th - 1) * c / 2);
    const tx = ox + cam.ox, ty = oy + cam.oy;
    // D82: the BODY renders at VISUAL bounds — a rect centered on the
    // mechanical footprint, scaled per axis from the old square silhouette,
    // so the aspect is honest and a default visual (no vw/vh) draws exactly
    // like before. This NEVER changes which cells are occupied.
    const radius = (c / 50) * (vside === 1 ? 16 : 20 + (vside - 1) * 14);
    const rx = vw === vside ? radius : radius * vw / vside;
    const ry = vh === vside ? radius : radius * vh / vside;
    const r = Math.max(rx, ry);
    if (tx < -(r + 40) || ty < -(r + 40) || tx > w + r + 40 || ty > h + r + 40) continue;
    const activeInit = state.init && state.init.combat && state.init.order[state.init.active];
    const isActive = activeInit && activeInit.token_id === t.id;
    const isMoving = state.moving.has(t.id);
    const conds = t.conds || [], dth = t.death;
    // D82: rot rotates the ARTWORK (and the rings hugging it), never the
    // mechanical footprint. Text/bars stay upright outside the transform.
    const rotDeg = (((t.rot | 0) % 360) + 360) % 360;
    const ex = rotDeg % 180 === 90 ? ry : rx;   // post-rotation half-extents
    const ey = rotDeg % 180 === 90 ? rx : ry;   // for upright decorations
    ctx.save(); ctx.translate(tx, ty); ctx.rotate(rotDeg * Math.PI / 180);
    ctx.beginPath(); ctx.ellipse(0, 0, rx, ry, 0, 0, Math.PI*2);
    ctx.fillStyle = t.color; ctx.fill();
    const hasArt = tokenArtwork(t, rx, ry);       // D85: artwork rides the rotate frame
    ctx.lineWidth = t.id === state.sel ? 3 : 2;
    ctx.strokeStyle = isActive ? "#fff" : (t.id===state.sel ? "#d4a017" : "#0d0f14");
    ctx.stroke();
    if (isMoving){ ctx.beginPath(); ctx.ellipse(0, 0, rx + 3, ry + 3, 0, 0, Math.PI*2); ctx.setLineDash([4,3]);
      ctx.strokeStyle="#7fd1ff"; ctx.lineWidth=2; ctx.stroke(); ctx.setLineDash([]); }
    if (state.room.role === "dm" && t.disposition){
      const dcol = {friend:"#2ecc71", hostile:"#e74c3c", neutral:"#3498db"}[t.disposition] || "#3498db";
      ctx.beginPath(); ctx.ellipse(0, 0, rx + 2, ry + 2, 0, 0, Math.PI*2); ctx.strokeStyle=dcol; ctx.lineWidth=2; ctx.stroke();
    }
    if (isActive){ ctx.beginPath(); ctx.ellipse(0, 0, rx + 5, ry + 5, 0, 0, Math.PI*2);
      ctx.strokeStyle = "#d4a017"; ctx.lineWidth = 2; ctx.stroke(); }
    if (conds.some(c => String(c.k).toLowerCase() === "concentrating")){
      ctx.beginPath(); ctx.ellipse(0, 0, rx + 4, ry + 4, 0, 0, Math.PI*2); ctx.setLineDash([3,3]);
      ctx.strokeStyle = "#d4a017"; ctx.lineWidth = 1.5; ctx.stroke(); ctx.setLineDash([]); }
    if (dth && !dth.dead && !dth.stable){                       // dying → red ring
      ctx.beginPath(); ctx.ellipse(0, 0, rx + 4, ry + 4, 0, 0, Math.PI*2);
      ctx.strokeStyle = "#c0392b"; ctx.lineWidth = 2; ctx.stroke(); }
    // D82 facing wedge: a rotated circle/square visual would otherwise be
    // indistinguishable — the gold nose shows where the creature faces.
    if (state.grid && state.grid.dark && (t.light | 0) > 0 && !dth?.dead){
      // D87: an operating light is visible even in the dark it fights
      ctx.beginPath(); ctx.arc(0, 0, Math.min(r + 6, r + (t.light | 0) * 3), 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(255,214,102,.5)"; ctx.lineWidth = 2; ctx.stroke();
    }
    if (rotDeg){ ctx.beginPath(); ctx.moveTo(0, -ry - 9); ctx.lineTo(-6, -ry - 1); ctx.lineTo(6, -ry - 1);
      ctx.closePath(); ctx.fillStyle = "#d4a017"; ctx.fill(); }
    ctx.restore();
    // D82/D84: the collision footprint is shown when USEFUL (selected, map
    // editing, ?debug) as a thin dashed OUTLINE — never the old translucent
    // colour BLOCK, which read as a stuck debug rectangle in normal play.
    if ((tw > 1 || th > 1) && (t.id === state.sel || state.editing || DEBUG)){
      ctx.save(); ctx.setLineDash([5,4]); ctx.globalAlpha = .9;
      ctx.strokeStyle = "rgba(212,160,23,.8)"; ctx.lineWidth = 1.5;
      ctx.strokeRect(ox - c/2 + cam.ox + .5, oy - c/2 + cam.oy + .5, tw*c - 1, th*c - 1);
      ctx.setLineDash([]); ctx.restore(); }
    ctx.fillStyle = dth && dth.dead ? "#ff6b6b" : "#fff"; ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center";
    ctx.fillText(dth && dth.dead ? "☠" : (hasArt ? "" : t.label.slice(0, 2).toUpperCase()), tx, ty + 4);
    ctx.font = "11px sans-serif";
    ctx.fillText(t.label, tx, ty + ey + 14);
    const m = state.room.members.find(x => x.user_id === t.owner_user_id);
    if (m && m.char){
      const ch = m.char, pct = Math.max(0, ch.hp/ch.max_hp);
      ctx.fillStyle = "#111"; ctx.fillRect(tx-16, ty-ey-10, 32, 5);
      ctx.fillStyle = pct <= .25 ? "#c0392b" : "#27ae60";
      ctx.fillRect(tx-16, ty-ey-10, 32*pct, 5);
    } else if (t.npc){
      const pct = Math.max(0, (t.npc.hp||0)/(t.npc.max_hp||1));
      ctx.fillStyle = "#111"; ctx.fillRect(tx-16, ty-ey-10, 32, 5);
      ctx.fillStyle = pct <= .25 ? "#c0392b" : "#e07b39";   // orange = monster (DM view only)
      ctx.fillRect(tx-16, ty-ey-10, 32*pct, 5);
    }
    if (conds.length){
      const shown = conds.slice(0, 5), y = ty + Math.max(42, ey + 18), x0 = tx - (shown.length - 1) * 6;
      shown.forEach((c, i) => { ctx.beginPath(); ctx.arc(x0 + i*12, y, 5, 0, Math.PI*2);
        ctx.fillStyle = condColor(c.k); ctx.fill();
        ctx.lineWidth = 1; ctx.strokeStyle = "#0d0f14"; ctx.stroke(); });
      if (conds.length > 5){ ctx.fillStyle = "#cfd3e0"; ctx.font = "bold 10px sans-serif";
        ctx.textAlign = "left"; ctx.fillText("+" + (conds.length - 5), x0 + shown.length*12, y + 3); }
    }
  }
}
function evtPos(e){ const r = cv.getBoundingClientRect();
  const cx = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
  const cy = (e.touches ? e.touches[0].clientY : e.clientY) - r.top;
  return { x: cx, y: cy }; }
function toCell(px, py){ const c = cellSize();
  return { cx: Math.floor((px - state.cam.ox) / c), cy: Math.floor((py - state.cam.oy) / c) }; }
function canMove(t){
  if (!state.room || !t) return false;
  const m = state.room.members && state.room.members.find(x => x.user_id === t.owner_user_id);
  if (m && m.char && (+m.char.hp || 0) <= 0) return false;
  // D82: an assigned CONTROLLER may operate the token (presentation check —
  // the server's authz.controls() is the real authority).
  return state.room.role === "dm" || t.owner_user_id === state.me.id
      || t.controller_user_id === state.me.id;
}
/* D86 floors: the viewer stands on the plane of their own token. Tokens and
   ghosts on other planes are elsewhere — not rendered, not clickable.
   (The DM has no token and therefore sees every plane.) */
function viewerPlane(){
  if (state.room && state.room.role === "dm") return null;
  const mine = (state.tokens || []).find(t => state.me && t.owner_user_id === state.me.id);
  return (mine && mine.floor) || "";
}
function onPlane(t){
  const p = viewerPlane();
  return p === null || (t.floor || "") === p;
}
function tokenAt(x, y){
  const c = cellSize();
  return [...state.tokens].reverse().find(t => {
    const [w, h] = tokenSpan(t), side = Math.max(w, h);
    const ox = t.x + ((w - 1) * c / 2), oy = t.y + ((h - 1) * c / 2);
    // D82/D83: clicking the visible ARTWORK selects the token — the hit area
    // is the visual rect (centered on the footprint; visualSpan already
    // carries the facing orientation). Presentation only: gameplay collision
    // stays the mechanical footprint, server-side.
    const [sw, sh] = visualSpan(t);
    if (Math.abs(x - ox) <= sw*c/2 + c*.3 && Math.abs(y - oy) <= sh*c/2 + c*.3) return true;
    if (Math.abs(x - ox) <= (w-1)*c/2 + c*.55 && Math.abs(y - oy) <= (h-1)*c/2 + c*.55) return true;
    const radius = (c / 50) * (side === 1 ? 16 : 20 + (side - 1) * 14);
    return (t.x-x)**2 + (t.y-y)**2 < (radius + side*c*.2)**2
        || (ox-x)**2 + (oy-y)**2 < (radius + side*c*.18)**2;
  });
}
function _objKind(o){ const it=o && o.interact; if(!it) return "";
  return (it.op && it.op.kind) || it.kind || ""; }
function objectAt(x, y){
  // WORLD cell lookup in the per-viewer (server-filtered) object list.
  if (!state.grid) return null;
  const c = cellSize(), cx = Math.floor(x / c), cy = Math.floor(y / c);
  return (state.grid.objects || []).find(o => o.x === cx && o.y === cy) || null;
}
function ownToken(){
  if (!state.room) return null;
  const sel = state.tokens.find(t => t.id === state.sel);
  if (sel && canMove(sel)) return sel;
  const mine = state.tokens.filter(t => (t.owner_user_id === state.me.id
                                         || t.controller_user_id === state.me.id) && canMove(t));
  return mine.length === 1 ? mine[0] : null;
}
function moveModeFor(tid){                 // D83: the sheet's active mode for a token
  state.moveMode = state.moveMode || {};
  return state.moveMode[tid] && state.moveMode[tid] !== "walk" ? state.moveMode[tid] : "walk";
}
function sendMove(cx, cy, teleport=false){
  const t = ownToken();
  if (!t){ toast("Select your token first"); return; }
  wsSend({ type:"move", token_id: t.id, tx: cx, ty: cy, teleport, mode: moveModeFor(t.id) });
}
function gridAt(g, cx, cy){                 // WORLD cell lookup (D72)
  if (!g || !g.cells) return null;
  const i = wIdx(g, cx, cy);
  return i < 0 ? null : g.cells[i];
}
let _planSeq = 0;
function tokenCellXY(t){ const c = cellSize(); return { cx: Math.floor(t.x / c), cy: Math.floor(t.y / c) }; }
/* D84: THE CENTER cell of a token — the destination cell in the wire contract
   (the server converts to the canonical anchor via footprint.center_to_anchor;
   the client never pre-converts). */
function tokenCenterCell(t){ const c = cellSize(), [w, h] = tokenSpan(t);
  return { cx: Math.floor(t.x / c) + ((w - 1) >> 1), cy: Math.floor(t.y / c) + ((h - 1) >> 1) }; }
function planSpanForToken(t){ return tokenSpan(t || {}); }
function requestPathPreview(cx, cy, confirmAfter=false){
  const t = ownToken(); if (!t){ toast("Select your token first"); return; }
  const id = ++_planSeq;
  state.planRequest = { id, token_id: t.id, goal: {cx, cy}, confirmAfter };
  wsSend({ type:"path_preview", token_id: t.id, tx: cx, ty: cy, request_id: id, mode: moveModeFor(t.id) });
}
function applyPathPreview(p){
  if (!state.planRequest || state.planRequest.id !== p.request_id) return;
  const confirmAfter = state.planRequest.confirmAfter;
  const dspan = planSpanForToken(state.tokens.find(t => t.id === p.token_id));
  const w = +p.w > 0 ? +p.w : dspan[0], h = +p.h > 0 ? +p.h : dspan[1];
  state.planRequest = null;
  state.plan = { token_id:p.token_id, goal:p.goal, anchor:p.anchor||p.goal,   // D84: goal=CENTER aimed, anchor=landing box
                 path:p.path||[], cells:p.cells||[],
                 cost:p.cost||0, side:Math.max(w,h), w:w, h:h,
                 budget:(p.budget === undefined ? null : p.budget),
                 within:(p.within_budget === undefined ? true : !!p.within_budget) };
  updateMoveHud();
  if (confirmAfter) confirmPlan();
}
function planMove(cx, cy){
  if (state.plan && state.plan.goal.cx === cx && state.plan.goal.cy === cy){ confirmPlan(); return; }
  requestPathPreview(cx, cy, false);
}
function confirmPlan(){
  if (!state.plan) return; const p = state.plan; clearPlan();
  wsSend({ type:"move", token_id: p.token_id, tx: p.goal.cx, ty: p.goal.cy, teleport:false,
           path: p.path || [], mode: moveModeFor(p.token_id) });
}
function clearPlan(){ state.plan = null; state.planRequest = null; updateMoveHud(); }
function updateMoveHud(){
  const hud = $("movehud"); if (!hud) return;
  if (!state.plan){ hud.classList.add("hidden"); return; }
  hud.classList.remove("hidden");
  const pl = state.plan;
  const cost = pl.budget === null ? `${pl.cost} squares`
           : `${pl.cost}/${pl.budget} squares${pl.within ? "" : " · beyond speed"}`;
  $("mh-text").textContent = `→ ${pl.goal.cx},${pl.goal.cy} · ${cost}`;
}

function flushFogEdit(){
  // fogTouched keys are STORAGE array indexes; the wire speaks WORLD cells (D72)
  const cells = Object.keys(state.fogTouched || {}).map(i => {
    const [wx, wy] = s2w(state.editMap, (+i) % state.editMap.w, Math.floor((+i) / state.editMap.w));
    return { x: wx, y: wy, explored: state.fogTouched[i] };
  });
  if (!cells.length) return;
  state.fogTouched = {};
  for (let i = 0; i < cells.length; i += 512) wsSend({ type:"fog_edit", cells: cells.slice(i, i + 512),
                                                       floor: state.viewFloor || "" });  // D88
}
function paint(cx, cy){
  const gm = state.editMap; if (!gm || !gm.cells) return;
  const i = wIdx(gm, cx, cy);               // click cell is WORLD; array is STORAGE (D72)
  if (i < 0) return;
  const b = state.brush;
  if (b === "wall") gm.cells[i] = 1;
  else if (b === "floor") gm.cells[i] = 0;
  else if (b === "rough") gm.cells[i] = 2;
  else if (b === "barrier") gm.cells[i] = 3;
  else if (b === "low") gm.cells[i] = 4;
  else if (b === "erase"){ gm.cells[i] = 0;
    gm.traps = gm.traps.filter(t => !(t.x===cx && t.y===cy));
    gm.loot = gm.loot.filter(l => !(l.x===cx && l.y===cy));
    gm.objects = (gm.objects||[]).filter(o => !(o.x===cx && o.y===cy)); }
  else if (b === "reveal" || b === "refog"){
    gm.explored[i] = b === "reveal" ? 1 : 0;
    state.fogTouched[i] = gm.explored[i];
  }
  else if (b === "raise" || b === "lower"){
    gm.elev = gm.elev && gm.elev.length === gm.w * gm.h ? gm.elev : new Array(gm.w * gm.h).fill(0);
    gm.elev[i] = Math.max(-6, Math.min(6, (gm.elev[i] || 0) + (b === "raise" ? 1 : -1)));
  }
  else if (b === "trap"){
    gm.traps = gm.traps.filter(t => !(t.x===cx && t.y===cy));
    const label = ($("trap-label").value || "").trim().slice(0,80) || "Trap";
    let dc = +$("trap-dc").value; if (!(dc >= 1 && dc <= 30)) dc = 13;
    const dmg = ($("trap-dmg").value || "").trim().slice(0,16) || "1d4";
    gm.traps.push({ id: eid(), x:cx, y:cy, label, dc, dmg, discovered:false });
  }
  else if (b === "loot"){
    gm.loot = gm.loot.filter(l => !(l.x===cx && l.y===cy));
    const label = ($("loot-label").value || "").trim().slice(0,80) || "Loot";
    gm.loot.push({ id: eid(), x:cx, y:cy, label, taken_by:null });
  }
  else if (b === "obj"){
    // D82: authored as pure DATA; the server only ever runs allowlisted ops.
    gm.objects = (gm.objects||[]).filter(o => !(o.x===cx && o.y===cy));
    const label = ($("obj-label").value || "").trim().slice(0,80) || "Object";
    const act = ($("obj-act").value || "").trim().slice(0,40) || "Interact";
    const o = { id: eid(), x:cx, y:cy, label, dm_only: !!$("obj-dm").checked, state: {} };
    if ($("obj-op").value === "toggle"){
      o.interact = { label: act, op: { kind:"toggle" } };
    } else if ($("obj-op").value === "lamp"){                   // D89 static light
      o.interact = { label: act,
                     op: { kind:"lamp", bright: Math.max(1, Math.min(30, +$("obj-bright").value || 5)) } };
      o.state = { on: true };
    } else if ($("obj-op").value === "stair"){                  // D88 connector
      const to = ($("obj-tfl").value || "").trim().slice(0,24);
      if (!to){ toast("Stairs need a target floor name"); return; }
      o.interact = { label: act,
                     op: { kind:"stair", floor: to,
                           x: +$("obj-tx").value || 0, y: +$("obj-ty").value || 0 } };
    } else {
      const d = nearestDoor(gm, cx, cy);
      if (!d){ toast("Link a door first — none within 3 cells"); return; }
      o.interact = { label: act, op: { kind:"door", x:d.x, y:d.y, dir:d.dir } };
    }
    gm.objects.push(o);
  }
  else if (b === "objrm"){
    gm.objects = (gm.objects||[]).filter(o => !(o.x===cx && o.y===cy));
  }
}
function nearestDoor(gm, cx, cy){
  // The nearest door EDGE cell within 3 cells (Chebyshev) — deterministic
  // linking without a picker UI; the linked door lives server-side anyway.
  let best = null, bd = 4;
  for (const d of (gm.doors || [])){
    const bx = d.dir === "v" ? d.x + 1 : d.x, by = d.dir === "h" ? d.y + 1 : d.y;
    const dist = Math.min(Math.max(Math.abs(cx - d.x), Math.abs(cy - d.y)),
                          Math.max(Math.abs(cx - bx), Math.abs(cy - by)));
    if (dist < bd){ bd = dist; best = d; }
  }
  return best;
}

/* ---------- doors (geometry + editor placement) ---------- */
function edgeKey(x1, y1, x2, y2){
  return x1 === x2 ? `h:${x1}:${Math.min(y1, y2)}` : `v:${Math.min(x1, x2)}:${y1}`;
}
function doorBlocked(g){
  const s = new Set();
  for (const d of (g.doors || [])) if (d.closed){
    const bx = d.dir === "v" ? d.x + 1 : d.x, by = d.dir === "h" ? d.y + 1 : d.y;
    s.add(edgeKey(d.x, d.y, bx, by));
  }
  return s;
}
function doorSeg(d, c, cam){
  const x0 = d.x*c + cam.ox, y0 = d.y*c + cam.oy;
  return d.dir === "v" ? [[x0+c, y0+3], [x0+c, y0+c-3]] : [[x0+3, y0+c], [x0+c-3, y0+c]];
}
function segDist(px, py, a, b){
  const dx = b[0]-a[0], dy = b[1]-a[1], l2 = dx*dx + dy*dy || 1;
  const t = Math.max(0, Math.min(1, ((px-a[0])*dx + (py-a[1])*dy) / l2));
  return Math.hypot(px - (a[0]+t*dx), py - (a[1]+t*dy));
}
function doorHit(wx, wy){
  const g = state.grid; if (!g || !g.doors) return null;
  const c = cellSize(), cam = state.cam; let best = null, bd = c*0.32;
  for (const d of g.doors){ const [A, B] = doorSeg(d, c, cam); const dd = segDist(wx, wy, A, B);
    if (dd < bd){ bd = dd; best = d; } }
  return best;
}
function edgeAnchor(x, y, dir){             // WORLD cells (doors store world coords)
  const g = state.editMap; if (!g) return null;
  const bx = dir === "v" ? x+1 : x, by = dir === "h" ? y+1 : y;
  if (!inWorld(g, x, y) || !inWorld(g, bx, by)) return null;
  return { x, y, dir };
}
function edgeFromClick(p){
  const g = state.editMap; if (!g) return null;
  const c = cellSize(), cam = state.cam, { cx, cy } = toCell(p.x, p.y);
  if (!inWorld(g, cx, cy)) return null;
  const lx = p.x - (cx*c + cam.ox), ly = p.y - (cy*c + cam.oy);
  const dl = lx, dr = c-lx, du = ly, dd = c-ly, m = Math.min(dl, dr, du, dd);
  if (m === dr) return edgeAnchor(cx,   cy,   "v");
  if (m === dl) return edgeAnchor(cx-1, cy,   "v");
  if (m === dd) return edgeAnchor(cx,   cy,   "h");
  return          edgeAnchor(cx,   cy-1, "h");
}
function doorEdit(p){
  const g = state.editMap; const e = edgeFromClick(p); if (!e) return;
  const idx = g.doors.findIndex(d => d.x===e.x && d.y===e.y && d.dir===e.dir);
  if (state.brush === "doorrm"){ if (idx >= 0) g.doors.splice(idx, 1); return; }
  if (idx >= 0) return;
  const locked = !!($("door-locked") && $("door-locked").checked);
  const dmOnly = !!($("door-dmonly") && $("door-dmonly").checked);
  const secret = !!($("door-secret") && $("door-secret").checked);
  g.doors.push({ id: eid(), x: e.x, y: e.y, dir: e.dir, closed: true, locked,
                 dm_only: dmOnly, secret, label: "Door" });
}
function pinEdit(p){
  const g = state.editMap; if (!g) return;
  g.pins = g.pins || [];
  const { cx, cy } = toCell(p.x, p.y);
  if (state.brush === "pinrm"){
    const idx = g.pins.findIndex(pin => pin.x === cx && pin.y === cy);
    if (idx >= 0) g.pins.splice(idx, 1);
    return;
  }
  if ($("pin-vis") && $("pin-vis").value === "revealed" && !g.explored[wIdx(g, cx, cy)]) toast("Pin is hidden until that area is explored");
  g.pins.push({ id:eid(), x:cx, y:cy, type:"info", visibility:($("pin-vis")||{}).value || "dm",
                color:($("pin-color")||{}).value || "#f1c40f", title:($("pin-title")||{}).value || "Pin",
                description:($("pin-desc")||{}).value || "" });
}
function drawPin(pin, c, cam, known){
  const sx = pin.x*c + cam.ox + c/2, sy = pin.y*c + cam.oy + c/2;
  ctx.save(); ctx.globalAlpha = known ? .95 : .45;
  ctx.beginPath(); ctx.arc(sx, sy, c*0.22, 0, Math.PI*2);
  ctx.fillStyle = pin.color || "#f1c40f"; ctx.fill();
  ctx.strokeStyle = "rgba(0,0,0,.55)"; ctx.lineWidth = 2; ctx.stroke();
  ctx.fillStyle = "#fff"; ctx.font = `bold ${c*.18}px sans-serif`; ctx.textAlign = "center";
  ctx.fillText((pin.title||"•").slice(0,1).toUpperCase(), sx, sy + c*.06);
  ctx.restore();
}
function drawDoor(d, c, cam){
  const [A, B] = doorSeg(d, c, cam), len = Math.hypot(B[0]-A[0], B[1]-A[1]);
  ctx.save(); ctx.lineCap = "round";
  if (d.secret) ctx.globalAlpha = 0.45;   // DM sees secret doors ghosted (players never receive them)
  ctx.strokeStyle = "#0d0f14"; ctx.lineWidth = 6; seg(A, B);
  if (d.closed){ ctx.strokeStyle = d.dm_only ? "#7a4f9e" : (d.locked ? "#7d4f27" : "#b9814a"); ctx.lineWidth = 4; seg(A, B); }
  else { ctx.strokeStyle = "#6b4d29"; ctx.lineWidth = 3;
    const px = d.dir === "v" ? -1 : 0, py = d.dir === "v" ? 0 : -1;   // leaf swung into its cell
    seg(A, [A[0] + px*len, A[1] + py*len]); }
  if (d.locked){ ctx.fillStyle = "#f1c40f"; ctx.font = `${Math.max(9, c*0.3)}px sans-serif`;
    ctx.textAlign = "center"; ctx.fillText("🔒", (A[0]+B[0])/2, (A[1]+B[1])/2 + c*0.1); }
  ctx.restore();
}
function seg(a, b){ ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke(); }

/* ---------- AoE overlay ---------- */
function hexA(hex, a){
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return `rgba(231,76,60,${a})`;
  const n = parseInt(m[1], 16);
  return `rgba(${(n>>16)&255},${(n>>8)&255},${n&255},${a})`;
}
let _aoeT = null;
function showAoe(p){
  const g = state.grid; if (!g) return;
  // D88/SPRINT-20: a template belongs to the plane it was placed on — paint it
  // only while that plane is the viewed one (the DM browses; server scoped the
  // delivery to the plane's viewers already).
  if (String(p.floor || "") !== String(state.viewFloor || "")) return;
  const cells = aoeCells(p.shape, p.x, p.y, p.size, g, p.dir);
  state.aoe = { cells, color: p.color || "#e74c3c", exp: Date.now() + 7000 };
  draw();
  if (_aoeT) clearTimeout(_aoeT);
  _aoeT = setTimeout(clearAoe, 7200);
}
function clearAoe(){ state.aoe = null; if (_aoeT){ clearTimeout(_aoeT); _aoeT = null; } draw(); }

function showPing(p){
  if (!p || p.x == null || p.y == null) return;
  if (String(p.floor || "") !== String(state.viewFloor || "")) return;   // SPRINT-20 plane guard
  const c = cellSize(), gm = state.grid; if (!gm) return;
  state.pings.push({ x:p.x*c + c/2, y:p.y*c + c/2, color:p.color || "#f1c40f", exp:Date.now()+2500 });
  if (state.pings.length > 20) state.pings.splice(0, state.pings.length - 20);
  draw();
}
function clearPings(){
  const before = state.pings.length;
  state.pings = (state.pings || []).filter(p => Date.now() < p.exp);
  if (before && state.pings.length !== before) draw();
  setTimeout(clearPings, 500);
}

function showPin(pin){
  const title = pin.title || "Map pin";
  toast(pin.description ? `${title}: ${pin.description}` : title);
}
function onDown(e){
  if (!state.room) return;
  const p = evtPos(e);
  if (e.button === 1 || e.button === 2){ state.pan = { x: p.x - state.cam.ox, y: p.y - state.cam.oy }; e.preventDefault(); return; }
  // Armed DM tools take the click in BOTH views (resolved via the view-aware
  // clickCell); only unarmed diorama clicks are select/move gestures.
  const toolArmed = state.rulerArmed || state.aoeArmed || state.pingArmed ||
    (state.spawnCreature && state.room && state.room.role === "dm");
  if (state.viewMode === "diorama" && !state.editing && !toolArmed){ dioramaDown(p); return; }
  if (state.rulerArmed && !state.editing){
    const { cx, cy } = clickCell(p);
    if (!state.ruler || state.ruler.done){ state.ruler = { x1:cx, y1:cy, x2:cx, y2:cy }; state.rulerArmed = false; $("btn-ruler").classList.remove("active"); }
    else { state.ruler.x2 = cx; state.ruler.y2 = cy; state.ruler.done = true; state.rulerArmed = false; $("btn-ruler").classList.remove("active"); }
    draw(); return;
  }
  if (state.editing && state.room.role === "dm"){
    if (state.brush === "door" || state.brush === "doorrm"){ doorEdit(p); return; }
    if (state.brush === "pin" || state.brush === "pinrm"){ pinEdit(p); return; }
    const { cx, cy } = toCell(p.x, p.y); paint(cx, cy); state.drag = { paint:true }; return;
  }
  if (state.aoeArmed && state.room.role === "dm" && !state.editing){
    const { cx, cy } = clickCell(p);
    const shape = $("aoe-shape").value, dir = $("aoe-dir").value;
    const size = Math.max(0, Math.min(30, +$("aoe-size").value || 5));
    const color = ($("aoe-color") && $("aoe-color").value) || "#e74c3c";
    showAoe({ shape, x: cx, y: cy, size, dir, color });
    wsSend({ type:"aoe", shape, x: cx, y: cy, size, dir, color,
             floor: state.viewFloor || "" });            // D88: the plane you view
    state.aoeArmed = false; const b = $("btn-aoe"); if (b) b.classList.remove("active");
    return;
  }
  if (state.pingArmed && !state.editing){
    const { cx, cy } = clickCell(p);
    const color = "var(--gold)" === "var(--gold)" ? "#f1c40f" : "#f1c40f";
    wsSend({ type:"ping", x: cx, y: cy, color, floor: state.viewFloor || "" });  // D88
    state.pingArmed = false; const b = $("btn-ping"); if (b) b.classList.remove("active");
    return;
  }
  if (state.spawnCreature && state.room.role === "dm" && !state.editing){
    const { cx, cy } = clickCell(p); const c = state.spawnCreature, blk = c.block || {}, cs = cellSize();
    wsSend({ type:"add_token", label:c.name, x:(cx+.5)*cs, y:(cy+.5)*cs, level:blk.level, stats:blk.stats,
      hp:blk.hp, max_hp:blk.max_hp, ac:blk.ac, speed:blk.speed, attacks:blk.attacks,
      spells:blk.spells, spell_slots:blk.spell_slots, saves:blk.saves, defenses:blk.defenses,
      abilities:blk.abilities, resources:blk.resources, notes:blk.notes,
      size:blk.size, disposition:blk.disposition });
    state.spawnCreature = null; return;
  }
  const wx = p.x - state.cam.ox, wy = p.y - state.cam.oy;
  const t = tokenAt(wx, wy);
  const c = cellSize(), pin = ((state.editing && state.editMap) || state.grid || {}).pins?.find(pin => {
    const sx = pin.x*c + state.cam.ox, sy = pin.y*c + state.cam.oy;
    return Math.hypot(wx - (sx + c/2), wy - (sy + c/2)) < c*.26;
  });
  if (pin && !state.editing && !t){ showPin(pin); return; }
  if (!t){
    const d = doorHit(wx, wy);
    if (d){ wsSend({ type:"door", x: d.x, y: d.y, dir: d.dir, action:"toggle" }); return; }
    // D82: clicking an INTERACTABLE world object sends the intent; the server
    // validates reach/permission and runs the allowlisted operation. Objects
    // without an interact field are decoration — clicks pass through to move.
    if (!state.editing){
      const ob = objectAt(wx, wy);
      if (ob && ob.interact){ wsSend({ type:"interact", object_id: ob.id,
                                       floor: state.viewFloor || "" }); return; }  // D88
    }
    // Keep the selected movable token while clicking an empty destination.
    // Clearing the sheet here used to clear state.sel before ownToken(), which
    // made DM/NPC click-to-move silently lose its mover.
    if (!state.editing && ownToken()){
      const { cx, cy } = toCell(p.x, p.y);
      if (state.plan && state.plan.goal.cx === cx && state.plan.goal.cy === cy) confirmPlan();
      else planMove(cx, cy);
    } else {
      renderSheet(null);
    }
    return;
  }
  renderSheet(t);
  if (!canMove(t)){ toast("Not your token"); return; }
  state.drag = { id: t.id, dx: t.x - wx, dy: t.y - wy, moved:false };
  e.preventDefault();
}
function onMove(e){
  if (state.pan){ const p = evtPos(e);
    state.cam.ox = p.x - state.pan.x; state.cam.oy = p.y - state.pan.y; clampCam(); return; }
  if (state.ruler && !state.ruler.done && state.room){ const p=evtPos(e), {cx,cy}=toCell(p.x,p.y); state.ruler.x2=cx; state.ruler.y2=cy; draw(); return; }
  const d = state.drag; if (!d) return;
  const p = evtPos(e);
  if (d.paint){ const { cx, cy } = toCell(p.x, p.y);
    if (["wall","floor","rough","erase","reveal","refog"].includes(state.brush)) paint(cx, cy); return; }
  const t = state.tokens.find(t => t.id === d.id);
  if (!t) return;
  const wx = p.x - state.cam.ox, wy = p.y - state.cam.oy;
  t.x = Math.max(worldLeft(), Math.min(worldLeft() + worldW(), wx + d.dx));
  t.y = Math.max(worldTop(), Math.min(worldTop() + worldH(), wy + d.dy));
  t.atx = t.x; t.aty = t.y;
  d.moved = true;
}
function onUp(e){
  const d = state.drag; state.drag = null; state.pan = null;
  if (!d) return;
  if (d.paint){ flushFogEdit(); return; }
  if (!d.moved) return;
  // D84: the destination is the CENTER cell — after a drag that is the cell
  // under the token's OWN centre (not the pointer's cell: grabbing a big
  // token's artwork used to drop its footprint anchor at the cursor,
  // shifting the whole box down-right).
  const t = state.tokens.find(x => x.id === d.id);
  const { cx, cy } = t ? tokenCenterCell(t) : toCell(evtPos(e).x, evtPos(e).y);
  if (state.room.role === "dm") sendMoveTo(d.id, cx, cy, true);
  else planMove(cx, cy);
}
function sendMoveTo(tokenId, cx, cy, teleport){
  wsSend({ type:"move", token_id: tokenId, tx: cx, ty: cy, teleport });
}
function clickCell(p){
  // The cell a click targets IN THE ACTIVE VIEW. Using the orthogonal toCell()
  // in diorama resolves a different cell than the isometric one the player
  // clicked — which made double-click confirms move to a wrong, distant goal.
  if (state.viewMode === "diorama" && state.grid){
    const { lx, ly } = dioUnproj(p.x, p.y, cellSize());
    return { cx: Math.floor(lx), cy: Math.floor(ly) };
  }
  return toCell(p.x, p.y);
}
function clickToken(p){
  if (state.viewMode === "diorama") return dioTokenClick(p.x, p.y, cellSize());
  return tokenAt(p.x - state.cam.ox, p.y - state.cam.oy);
}
function onDbl(e){
  if (state.editing) return;
  const p = evtPos(e), { cx, cy } = clickCell(p);
  const g = state.grid;
  if (g && !inWorld(g, cx, cy)) return;
  if (clickToken(p)) return;
  if (state.room.role === "dm"){
    const mine = state.tokens.filter(t => t.owner_user_id === state.me.id);
    if (mine.length === 1) sendMoveTo(mine[0].id, cx, cy, false);
    return;
  }
  if (state.plan && state.plan.goal.cx === cx && state.plan.goal.cy === cy) confirmPlan();
  else requestPathPreview(cx, cy, true);
}
cv.addEventListener("mousedown", onDown); cv.addEventListener("touchstart", onDown, {passive:false});
cv.addEventListener("dblclick", onDbl);
cv.addEventListener("contextmenu", e => e.preventDefault());
window.addEventListener("mousemove", onMove); window.addEventListener("touchmove", onMove, {passive:false});
window.addEventListener("mouseup", onUp); window.addEventListener("touchend", onUp);
window.addEventListener("resize", resize);
window.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
  if (e.key === "?"){ const h = $("help-overlay");
    if (h){ h.classList.toggle("hidden"); e.preventDefault(); } return; }
  if (e.key === "Escape"){
    const h = $("help-overlay");
    if (h && !h.classList.contains("hidden")){ h.classList.add("hidden"); return; }
    // D84: Escape = explicit deselect (plan, ruler, selection+sheet) — the
    // footprint outline is gone in normal gameplay without hunting a button.
    clearPlan(); state.ruler = null; state.sel = null; renderSheet(null); draw();
  }
  state.keys.add(e.key);
});
window.addEventListener("keyup", e => state.keys.delete(e.key));

/* ---------- map editor (DM) ---------- */
function editorOpen(){
  state.editing = true; state.fogTouched = {};
  state.editMap = JSON.parse(JSON.stringify(state.grid));
  document.querySelectorAll(".brush").forEach(b => b.classList.toggle("active", b.dataset.b === "wall"));
  state.brush = "wall";
  $("editor").classList.remove("hidden");
  $("trap-fields").classList.add("hidden"); $("loot-fields").classList.add("hidden");
  $("door-fields").classList.add("hidden");
  const of = $("obj-fields"); if (of) of.classList.add("hidden");
  $("ed-w").value = state.editMap.w; $("ed-h").value = state.editMap.h;
}
function editorClose(){ flushFogEdit(); state.editing = false; state.editMap = null; $("editor").classList.add("hidden"); }
function edResize(){
  const w = Math.max(8, Math.min(80, +$("ed-w").value || 40));
  const h = Math.max(6, Math.min(60, +$("ed-h").value || 26));
  const old = state.editMap;
  const [ox, oy] = gridOrigin(old);                       // D72: the resize keeps the world anchor
  const inW = (x, y) => x >= ox && y >= oy && x < ox + w && y < oy + h;
  const gm = { w, h, cell: old.cell, origin: [ox, oy], cells: new Array(w*h).fill(0), explored: new Array(w*h).fill(0),
               traps: old.traps.filter(t => inW(t.x, t.y)), loot: old.loot.filter(l => inW(l.x, l.y)),
               // SPRINT-20: pins and the elevation layer used to fall off this
               // snapshot silently — sanitize then legitimately emptied them
               // (resize lost every pin on the plane, every step/cliff height).
               pins: (old.pins||[]).filter(p => inW(p.x, p.y)),
               objects: (old.objects||[]).filter(o => inW(o.x, o.y)),
               doors: (old.doors||[]).filter(d => inW(d.x, d.y) && (d.dir === "v" ? inW(d.x+1, d.y) : inW(d.x, d.y+1))) };
  gm.elev = new Array(w*h).fill(0);
  for (let y = 0; y < Math.min(h, old.h); y++) for (let x = 0; x < Math.min(w, old.w); x++){
    gm.cells[y*w+x] = old.cells[y*old.w+x];
    if (old.elev) gm.elev[y*w+x] = old.elev[y*old.w+x];   // row-wise carry (D70)
  }
  state.editMap = gm;
}
