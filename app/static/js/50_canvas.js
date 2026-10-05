/* ---------- canvas: camera, grid, fog, editor ---------- */
function renderFogToggle(){
  const b = $("btn-fog-toggle"); if (!b) return;
  const on = !!(state.grid && state.grid.fog_off);
  b.classList.toggle("active", on);
  b.title = on ? "Fog is OFF — all terrain revealed. Click to restore fog of war."
               : "Show all terrain to every player. Hidden foes still need line of sight.";
}
const cv = $("map"), ctx = cv.getContext("2d");
function cellSize(){ return state.grid ? state.grid.cell : 50; }
function worldW(){ return state.grid ? state.grid.w * cellSize() : 2000; }
function worldH(){ return state.grid ? state.grid.h * cellSize() : 1300; }
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
  const { w, h } = view(), W = worldW(), H = worldH();
  state.cam.ox = W <= w ? (w - W)/2 : Math.min(0, Math.max(w - W, state.cam.ox));
  state.cam.oy = H <= h ? (h - H)/2 : Math.min(0, Math.max(h - H, state.cam.oy));
}
function tick(){
  if (!state.tickOn || !state.room) return;
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
  draw();
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
  if (state.viewMode === "diorama" && !state.editing){ drawDiorama(); return; }
  drawTactical();
}
function drawTactical(){
  const { w, h } = view(), c = cellSize(), cam = state.cam;
  const gm = state.editing && state.editMap ? state.editMap : state.grid;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#0a0b10"; ctx.fillRect(0, 0, w, h);
  const x0 = Math.max(0, Math.floor(-cam.ox / c)), y0 = Math.max(0, Math.floor(-cam.oy / c));
  const x1 = Math.min(gm ? gm.w : 0, Math.ceil((w - cam.ox) / c)), y1 = Math.min(gm ? gm.h : 0, Math.ceil((h - cam.oy) / c));
  if (gm){
    for (let gy = y0; gy < y1; gy++) for (let gx = x0; gx < x1; gx++){
      const i = gy * gm.w + gx, sx = gx*c + cam.ox, sy = gy*c + cam.oy;
      const known = state.editing || visibleHere(i);
      if (!known){ continue; }
      const ter = gm.cells[i];
      if (ter === 1) { ctx.fillStyle = "#3a4157"; ctx.fillRect(sx, sy, c, c);
        ctx.fillStyle = "#232838"; ctx.fillRect(sx+2, sy+2, c-4, c-4); }
      else if (ter === 2){ ctx.fillStyle = "#20281d"; ctx.fillRect(sx, sy, c, c);
        ctx.strokeStyle = "#2e3a29"; ctx.beginPath();
        ctx.moveTo(sx+4, sy+c-6); ctx.lineTo(sx+c/2, sy+c/3); ctx.lineTo(sx+c-4, sy+c-6); ctx.stroke(); }
      else { ctx.fillStyle = "#151823"; ctx.fillRect(sx, sy, c, c); }
      ctx.strokeStyle = "#232735"; ctx.strokeRect(sx+.5, sy+.5, c, c);
    }
    if (state.bg && state.bg.complete && state.bg.naturalWidth){
      ctx.globalAlpha = .9;
      ctx.drawImage(state.bg, cam.ox, cam.oy, gm.w*c, gm.h*c);
      ctx.globalAlpha = 1;
    }
    const marks = gm ? []
      .concat((gm.traps||[]).map(t=>[t,"⚠","#e74c3c"]),
              (gm.loot||[]).map(l=>[l,"🎁","#d4a017"])) : [];
    for (const [e, ic, col] of marks){
      const isDM = state.room.role === "dm";
      const known = state.editing || isDM || e.discovered || e.taken_by === state.me.id;
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
      if (e.taken_by != null && e.taken_by !== 0){ ctx.strokeStyle = "#555"; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(sx-c*.2, sy-c*.2); ctx.lineTo(sx+c*.2, sy+c*.2); ctx.stroke(); }
    }
    for (const d of (gm.doors || [])) drawDoor(d, c, cam);
    for (const pin of (gm.pins || [])) drawPin(pin, c, cam, state.editing || state.room.role === "dm" || visibleHere(pin.y*gm.w + pin.x));
  }
  if (state.plan && (state.plan.cells || state.plan.path)){
    const preview = state.plan.cells || state.plan.path.map(p => ({x:p.x, y:p.y}));
    for (const pt of preview){
      const rx = pt.x*c + cam.ox, ry = pt.y*c + cam.oy;
      ctx.fillStyle = "rgba(212,160,23,0.22)"; ctx.fillRect(rx, ry, c, c); }
    const gp = state.plan.goal, gx = (gp.cx + ((state.plan.side || 1)-1)/2)*c + c/2 + cam.ox,
          gy = (gp.cy + ((state.plan.side || 1)-1)/2)*c + c/2 + cam.oy;
    ctx.strokeStyle = "#d4a017"; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(gx, gy, c*.38*(state.plan.side || 1), 0, Math.PI*2); ctx.stroke();
  }
  if (state.aoe && Date.now() < state.aoe.exp && gm){
    ctx.fillStyle = hexA(state.aoe.color, .26);
    for (const i of state.aoe.cells){ const rx = (i % gm.w)*c + cam.ox, ry = Math.floor(i/gm.w)*c + cam.oy;
      ctx.fillRect(rx, ry, c, c); }
  }
  for (const gh of state.ghosts){
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
    const side = SIZE_FOOTPRINT[t.size] || 1;
    const ox = t.x + ((side - 1) * c / 2), oy = t.y + ((side - 1) * c / 2);
    const tx = ox + cam.ox, ty = oy + cam.oy;
    if (tx < -80 || ty < -80 || tx > w+80 || ty > h+80) continue;
    const activeInit = state.init && state.init.combat && state.init.order[state.init.active];
    const isActive = activeInit && activeInit.token_id === t.id;
    const isMoving = state.moving.has(t.id);
    const radius = (c / 50) * (side === 1 ? 16 : 20 + (side - 1) * 14);
    const r = radius;
    ctx.beginPath(); ctx.arc(tx, ty, r, 0, Math.PI*2);
    ctx.fillStyle = t.color; ctx.fill();
    ctx.lineWidth = t.id === state.sel ? 3 : 2;
    ctx.strokeStyle = isActive ? "#fff" : (t.id===state.sel ? "#d4a017" : "#0d0f14");
    ctx.stroke();
    if (isMoving){ ctx.beginPath(); ctx.arc(tx, ty, r + 3, 0, Math.PI*2); ctx.setLineDash([4,3]);
      ctx.strokeStyle="#7fd1ff"; ctx.lineWidth=2; ctx.stroke(); ctx.setLineDash([]); }
    if (side > 1){ ctx.save(); ctx.globalAlpha=.18; ctx.fillStyle=t.color;
      ctx.fillRect(ox - c/2 + cam.ox, oy - c/2 + cam.oy, side*c, side*c); ctx.restore(); }
    if (state.room.role === "dm" && t.disposition){
      const dcol = {friend:"#2ecc71", hostile:"#e74c3c", neutral:"#3498db"}[t.disposition] || "#3498db";
      ctx.beginPath(); ctx.arc(tx, ty, r + 2, 0, Math.PI*2); ctx.strokeStyle=dcol; ctx.lineWidth=2; ctx.stroke();
    }
    if (isActive){ ctx.beginPath(); ctx.arc(tx, ty, r + 5, 0, Math.PI*2);
      ctx.strokeStyle = "#d4a017"; ctx.lineWidth = 2; ctx.stroke(); }
    const conds = t.conds || [], dth = t.death;
    if (conds.some(c => String(c.k).toLowerCase() === "concentrating")){
      ctx.beginPath(); ctx.arc(tx, ty, r + 4, 0, Math.PI*2); ctx.setLineDash([3,3]);
      ctx.strokeStyle = "#d4a017"; ctx.lineWidth = 1.5; ctx.stroke(); ctx.setLineDash([]); }
    if (dth && !dth.dead && !dth.stable){                       // dying → red ring
      ctx.beginPath(); ctx.arc(tx, ty, r + 4, 0, Math.PI*2);
      ctx.strokeStyle = "#c0392b"; ctx.lineWidth = 2; ctx.stroke(); }
    ctx.fillStyle = dth && dth.dead ? "#ff6b6b" : "#fff"; ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center";
    ctx.fillText(dth && dth.dead ? "☠" : t.label.slice(0, 2).toUpperCase(), tx, ty + 4);
    ctx.font = "11px sans-serif";
    ctx.fillText(t.label, tx, ty + r + 14);
    const m = state.room.members.find(x => x.user_id === t.owner_user_id);
    if (m && m.char){
      const ch = m.char, pct = Math.max(0, ch.hp/ch.max_hp);
      ctx.fillStyle = "#111"; ctx.fillRect(tx-16, ty-r-10, 32, 5);
      ctx.fillStyle = pct <= .25 ? "#c0392b" : "#27ae60";
      ctx.fillRect(tx-16, ty-r-10, 32*pct, 5);
    } else if (t.npc){
      const pct = Math.max(0, (t.npc.hp||0)/(t.npc.max_hp||1));
      ctx.fillStyle = "#111"; ctx.fillRect(tx-16, ty-r-10, 32, 5);
      ctx.fillStyle = pct <= .25 ? "#c0392b" : "#e07b39";   // orange = monster (DM view only)
      ctx.fillRect(tx-16, ty-r-10, 32*pct, 5);
    }
    if (conds.length){
      const shown = conds.slice(0, 5), y = ty + 42, x0 = tx - (shown.length - 1) * 6;
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
  return state.room.role === "dm" || t.owner_user_id === state.me.id;
}
function tokenAt(x, y){
  const c = cellSize();
  return [...state.tokens].reverse().find(t => {
    const side = SIZE_FOOTPRINT[t.size] || 1;
    const ox = t.x + ((side - 1) * c / 2), oy = t.y + ((side - 1) * c / 2);
    const radius = (c / 50) * (side === 1 ? 16 : 20 + (side - 1) * 14);
    return (t.x-x)**2 + (t.y-y)**2 < (radius + side*c*.2)**2
        || (ox-x)**2 + (oy-y)**2 < (radius + side*c*.18)**2;
  });
}
function ownToken(){
  if (!state.room) return null;
  const sel = state.tokens.find(t => t.id === state.sel);
  if (sel && canMove(sel)) return sel;
  const mine = state.tokens.filter(t => t.owner_user_id === state.me.id && canMove(t));
  return mine.length === 1 ? mine[0] : null;
}
function sendMove(cx, cy, teleport=false){
  const t = ownToken();
  if (!t){ toast("Select your token first"); return; }
  wsSend({ type:"move", token_id: t.id, tx: cx, ty: cy, teleport });
}
function gridAt(g, cx, cy){
  if (!g || !g.cells) return null;
  if (cx < 0 || cy < 0 || cx >= g.w || cy >= g.h) return null;
  return g.cells[cy * g.w + cx];
}
let _planSeq = 0;
function tokenCellXY(t){ const c = cellSize(); return { cx: Math.floor(t.x / c), cy: Math.floor(t.y / c) }; }
function planSideForToken(t){ return SIZE_FOOTPRINT[(t && t.size) || "Medium"] || 1; }
function requestPathPreview(cx, cy, confirmAfter=false){
  const t = ownToken(); if (!t){ toast("Select your token first"); return; }
  const id = ++_planSeq;
  state.planRequest = { id, token_id: t.id, goal: {cx, cy}, confirmAfter };
  wsSend({ type:"path_preview", token_id: t.id, tx: cx, ty: cy, request_id: id });
}
function applyPathPreview(p){
  if (!state.planRequest || state.planRequest.id !== p.request_id) return;
  const confirmAfter = state.planRequest.confirmAfter;
  const side = SIZE_FOOTPRINT[p.size] || planSideForToken(state.tokens.find(t => t.id === p.token_id));
  state.planRequest = null;
  state.plan = { token_id:p.token_id, goal:p.goal, path:p.path||[], cells:p.cells||[],
                 cost:p.cost||0, side:side||1 };
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
           path: p.path || [] });
}
function clearPlan(){ state.plan = null; state.planRequest = null; updateMoveHud(); }
function updateMoveHud(){
  const hud = $("movehud"); if (!hud) return;
  if (!state.plan){ hud.classList.add("hidden"); return; }
  hud.classList.remove("hidden");
  $("mh-text").textContent = `→ ${state.plan.goal.cx},${state.plan.goal.cy} · ${state.plan.cost} steps`;
}

function flushFogEdit(){
  const cells = Object.keys(state.fogTouched || {}).map(i => ({
    x: (+i) % state.editMap.w, y: Math.floor((+i) / state.editMap.w), explored: state.fogTouched[i]
  }));
  if (!cells.length) return;
  state.fogTouched = {};
  for (let i = 0; i < cells.length; i += 512) wsSend({ type:"fog_edit", cells: cells.slice(i, i + 512) });
}
function paint(cx, cy){
  const gm = state.editMap; if (!gm || !gm.cells) return;
  if (cx < 0 || cy < 0 || cx >= gm.w || cy >= gm.h) return;
  const i = cy * gm.w + cx, b = state.brush;
  if (b === "wall") gm.cells[i] = 1;
  else if (b === "floor") gm.cells[i] = 0;
  else if (b === "rough") gm.cells[i] = 2;
  else if (b === "erase"){ gm.cells[i] = 0;
    gm.traps = gm.traps.filter(t => !(t.x===cx && t.y===cy));
    gm.loot = gm.loot.filter(l => !(l.x===cx && l.y===cy)); }
  else if (b === "reveal" || b === "refog"){
    gm.explored[i] = b === "reveal" ? 1 : 0;
    state.fogTouched[i] = gm.explored[i];
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
function edgeAnchor(x, y, dir){
  const g = state.editMap; if (!g) return null;
  const bx = dir === "v" ? x+1 : x, by = dir === "h" ? y+1 : y;
  if (x < 0 || y < 0 || x >= g.w || y >= g.h || bx >= g.w || by >= g.h) return null;
  return { x, y, dir };
}
function edgeFromClick(p){
  const g = state.editMap; if (!g) return null;
  const c = cellSize(), cam = state.cam, { cx, cy } = toCell(p.x, p.y);
  if (cx < 0 || cy < 0 || cx >= g.w || cy >= g.h) return null;
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
  if ($("pin-vis") && $("pin-vis").value === "revealed" && !g.explored[cy*g.w + cx]) toast("Pin is hidden until that area is explored");
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
  const cells = aoeCells(p.shape, p.x, p.y, p.size, g.w, g.h, p.dir);
  state.aoe = { cells, color: p.color || "#e74c3c", exp: Date.now() + 7000 };
  draw();
  if (_aoeT) clearTimeout(_aoeT);
  _aoeT = setTimeout(clearAoe, 7200);
}
function clearAoe(){ state.aoe = null; if (_aoeT){ clearTimeout(_aoeT); _aoeT = null; } draw(); }

function showPing(p){
  if (!p || p.x == null || p.y == null) return;
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
    wsSend({ type:"aoe", shape, x: cx, y: cy, size, dir, color });
    state.aoeArmed = false; const b = $("btn-aoe"); if (b) b.classList.remove("active");
    return;
  }
  if (state.pingArmed && !state.editing){
    const { cx, cy } = clickCell(p);
    const color = "var(--gold)" === "var(--gold)" ? "#f1c40f" : "#f1c40f";
    wsSend({ type:"ping", x: cx, y: cy, color });
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
  t.x = Math.max(0, Math.min(worldW(), wx + d.dx));
  t.y = Math.max(0, Math.min(worldH(), wy + d.dy));
  t.atx = t.x; t.aty = t.y;
  d.moved = true;
}
function onUp(e){
  const d = state.drag; state.drag = null; state.pan = null;
  if (!d) return;
  if (d.paint){ flushFogEdit(); return; }
  const p = evtPos(e);
  if (!d.moved) return;
  const { cx, cy } = toCell(p.x, p.y);
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
  if (g && (cx < 0 || cy < 0 || cx >= g.w || cy >= g.h)) return;
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
    clearPlan(); state.ruler = null; draw();
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
  $("ed-w").value = state.editMap.w; $("ed-h").value = state.editMap.h;
}
function editorClose(){ flushFogEdit(); state.editing = false; state.editMap = null; $("editor").classList.add("hidden"); }
function edResize(){
  const w = Math.max(8, Math.min(80, +$("ed-w").value || 40));
  const h = Math.max(6, Math.min(60, +$("ed-h").value || 26));
  const old = state.editMap;
  const gm = { w, h, cell: old.cell, cells: new Array(w*h).fill(0), explored: new Array(w*h).fill(0),
               traps: old.traps.filter(t => t.x < w && t.y < h), loot: old.loot.filter(l => l.x < w && l.y < h),
               doors: (old.doors||[]).filter(d => d.x < w && d.y < h && (d.dir === "v" ? d.x+1 < w : d.y+1 < h)) };
  for (let y = 0; y < Math.min(h, old.h); y++) for (let x = 0; x < Math.min(w, old.w); x++)
    gm.cells[y*w+x] = old.cells[y*old.w+x];
  state.editMap = gm;
}
