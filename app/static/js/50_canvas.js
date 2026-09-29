/* ---------- canvas: camera, grid, fog, editor ---------- */
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
  const g = state.grid; if (!g) return false;
  if (state.room.role === "dm") return true;
  return g.explored[i] && g.cells[i] !== null && g.cells[i] !== undefined;
}
function draw(){
  if (!ctx || !state.room) return;
  const { w, h } = view(), c = cellSize(), cam = state.cam;
  const gm = state.editing && state.editMap ? state.editMap : state.grid;
  const visSet = (!state.editing && state.room && state.room.role !== "dm") ? ownVisSet() : undefined;
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
      if (visSet && !visSet.has(i)){ ctx.fillStyle = "rgba(4,5,9,0.62)"; ctx.fillRect(sx, sy, c, c); }
    }
    if (state.bg && state.bg.complete && state.bg.naturalWidth){
      ctx.globalAlpha = .9;
      ctx.drawImage(state.bg, cam.ox, cam.oy, gm.w*c, gm.h*c);
      ctx.globalAlpha = 1;
    }
    const icons = gm ? [(gm.traps||[]).map(t=>[t,"⚠","#e74c3c"]), (gm.loot||[]).map(l=>[l,"🎁","#d4a017"])] : [];
    for (const list of icons) for (const [e, ic, col] of list){
      const known = state.editing || (state.room.role === "dm" && !state.editing)
        || (e.discovered || e.taken_by === state.me.id);
      if (!known && state.room.role !== "dm") continue;
      if (state.room.role !== "dm" && !known) continue;
      const sx = e.x*c + cam.ox + c/2, sy = e.y*c + cam.oy + c/2;
      ctx.font = `${c*.5}px sans-serif`; ctx.textAlign = "center";
      ctx.globalAlpha = e.discovered ? .9 : .7;
      ctx.fillText(ic, sx, sy + c*.18);
      ctx.globalAlpha = 1;
      if (e.taken_by != null && e.taken_by !== 0){ ctx.strokeStyle = "#555";
        ctx.beginPath(); ctx.moveTo(sx-8, sy-8); ctx.lineTo(sx+8, sy+8); ctx.stroke(); }
    }
  }
  if (state.plan && state.plan.path){
    for (const pt of state.plan.path){
      const rx = pt.x*c + cam.ox, ry = pt.y*c + cam.oy;
      ctx.fillStyle = "rgba(212,160,23,0.22)"; ctx.fillRect(rx, ry, c, c); }
    const gp = state.plan.goal, gx = gp.cx*c + cam.ox + c/2, gy = gp.cy*c + cam.oy + c/2;
    ctx.strokeStyle = "#d4a017"; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(gx, gy, c*.38, 0, Math.PI*2); ctx.stroke();
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
  for (const t of state.tokens){
    const tx = t.x + cam.ox, ty = t.y + cam.oy;
    if (tx < -40 || ty < -40 || tx > w+40 || ty > h+40) continue;
    const activeInit = state.init && state.init.combat && state.init.order[state.init.active];
    const isActive = activeInit && activeInit.token_id === t.id;
    ctx.beginPath(); ctx.arc(tx, ty, 16, 0, Math.PI*2);
    ctx.fillStyle = t.color; ctx.fill();
    ctx.lineWidth = t.id === state.sel ? 3 : 2;
    ctx.strokeStyle = isActive ? "#fff" : (t.id===state.sel ? "#d4a017" : "#0d0f14");
    ctx.stroke();
    if (isActive){ ctx.beginPath(); ctx.arc(tx, ty, 21, 0, Math.PI*2);
      ctx.strokeStyle = "#d4a017"; ctx.lineWidth = 2; ctx.stroke(); }
    ctx.fillStyle = "#fff"; ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center";
    ctx.fillText(t.label.slice(0, 2).toUpperCase(), tx, ty + 4);
    ctx.font = "11px sans-serif";
    ctx.fillText(t.label, tx, ty + 30);
    const m = state.room.members.find(x => x.user_id === t.owner_user_id);
    if (m && m.char){
      const ch = m.char, pct = Math.max(0, ch.hp/ch.max_hp);
      ctx.fillStyle = "#111"; ctx.fillRect(tx-16, ty-26, 32, 5);
      ctx.fillStyle = pct <= .25 ? "#c0392b" : "#27ae60";
      ctx.fillRect(tx-16, ty-26, 32*pct, 5);
    }
  }
}
function evtPos(e){ const r = cv.getBoundingClientRect();
  const cx = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
  const cy = (e.touches ? e.touches[0].clientY : e.clientY) - r.top;
  return { x: cx, y: cy }; }
function toCell(px, py){ const c = cellSize();
  return { cx: Math.floor((px - state.cam.ox) / c), cy: Math.floor((py - state.cam.oy) / c) }; }
function canMove(t){ return state.room && (state.room.role === "dm" || t.owner_user_id === state.me.id); }
function tokenAt(x, y){
  return [...state.tokens].reverse().find(t => (t.x-x)**2 + (t.y-y)**2 < 18**2);
}
function ownToken(){
  if (!state.room) return null;
  const sel = state.tokens.find(t => t.id === state.sel);
  if (sel && canMove(sel)) return sel;
  const mine = state.tokens.filter(t => t.owner_user_id === state.me.id);
  return mine.length === 1 ? mine[0] : (sel || null);
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
const PDIRS = [[1,0,10],[-1,0,10],[0,1,10],[0,-1,10],[1,1,14],[1,-1,14],[-1,1,14],[-1,-1,14]];
function findPathJS(g, sx, sy, gx, gy, maxSteps){
  maxSteps = maxSteps || 400;
  const gc = gridAt(g,gx,gy); if (gc === null || gc === 1) return null;
  const sc = gridAt(g,sx,sy); if (sc === null) return null;
  if (sx === gx && sy === gy) return [];
  const walk = (v) => v === 0 || v === 2;
  const hcost = (x,y) => { const dx=Math.abs(gx-x), dy=Math.abs(gy-y); return 10*(dx+dy) - 6*Math.min(dx,dy); };
  const open = [[hcost(sx,sy), 0, sx, sy]], gmap = new Map([[sx+","+sy, 0]]);
  const came = new Map(); let tie = 0, found = false;
  while (open.length){
    open.sort((a,b)=> a[0]-b[0] || a[1]-b[1]);
    const [, , x, y] = open.shift();
    if (x === gx && y === gy){ found = true; break; }
    for (const [dx,dy,base] of PDIRS){
      const nx = x+dx, ny = y+dy, nc = gridAt(g,nx,ny);
      if (!walk(nc)) continue;
      if (dx && dy && (!walk(gridAt(g,x,ny)) || !walk(gridAt(g,nx,y)))) continue;
      const cost = (nc === 2 ? base*2 : base);
      const ng = gmap.get(x+","+y) + cost, k = nx+","+ny;
      if (ng < (gmap.get(k) ?? 1e18)){ gmap.set(k, ng); came.set(k, x+","+y);
        tie++; open.push([ng + hcost(nx,ny), tie, nx, ny]); }
    }
  }
  if (!found) return null;
  const path = []; let node = gx+","+gy;
  while (node !== sx+","+sy){ const [x,y] = node.split(",").map(Number); path.push({x,y}); node = came.get(node); if (node == null) return null; }
  path.reverse();
  return path.length <= maxSteps ? path : null;
}
function pathCost(g, path){ let c = 0; for (const p of path) c += (gridAt(g,p.x,p.y) === 2 ? 2 : 1); return c; }
function tokenCellXY(t){ const c = cellSize(); return { cx: Math.floor(t.x / c), cy: Math.floor(t.y / c) }; }
function planMove(cx, cy){
  const t = ownToken(); if (!t){ toast("Select your token first"); return; }
  const g = state.grid; if (!g){ return; }
  const s = tokenCellXY(t);
  if (s.cx === cx && s.cy === cy){ clearPlan(); return; }
  const path = findPathJS(g, s.cx, s.cy, cx, cy);
  if (!path){ toast("No path there"); clearPlan(); return; }
  state.plan = { tokenId: t.id, goal: {cx, cy}, path, cost: pathCost(g, path) };
  updateMoveHud();
}
function confirmPlan(){
  if (!state.plan) return; const p = state.plan; clearPlan();
  wsSend({ type:"move", token_id: p.tokenId, tx: p.goal.cx, ty: p.goal.cy, teleport:false });
}
function clearPlan(){ state.plan = null; updateMoveHud(); }
function updateMoveHud(){
  const hud = $("movehud"); if (!hud) return;
  if (!state.plan){ hud.classList.add("hidden"); return; }
  hud.classList.remove("hidden");
  $("mh-text").textContent = `→ ${state.plan.goal.cx},${state.plan.goal.cy} · ${state.plan.cost} steps`;
}
function ownVisSet(){
  const g = state.grid; const set = new Set();
  if (!g) return set;
  if (state.room && state.room.role === "dm"){ return null; }
  for (const t of state.tokens) if (t.owner_user_id === state.me.id){
    const { cx, cy } = tokenCellXY(t);
    for (let dy=-VISION_R; dy<=VISION_R; dy++) for (let dx=-VISION_R; dx<=VISION_R; dx++){
      const nx=cx+dx, ny=cy+dy; if (nx>=0 && ny>=0 && nx<g.w && ny<g.h) set.add(ny*g.w+nx);
    }
  }
  return set;
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
function onDown(e){
  if (!state.room) return;
  const p = evtPos(e);
  if (e.button === 1 || e.button === 2){ state.pan = { x: p.x - state.cam.ox, y: p.y - state.cam.oy }; e.preventDefault(); return; }
  if (state.editing && state.room.role === "dm"){
    const { cx, cy } = toCell(p.x, p.y); paint(cx, cy); state.drag = { paint:true }; return;
  }
  const wx = p.x - state.cam.ox, wy = p.y - state.cam.oy;
  const t = tokenAt(wx, wy);
  if (!t){ renderSheet(null);
    if (!state.editing && state.room.role !== "dm" && ownToken()){
      const { cx, cy } = toCell(p.x, p.y);
      if (state.plan && state.plan.goal.cx === cx && state.plan.goal.cy === cy) confirmPlan();
      else planMove(cx, cy);
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
  const d = state.drag; if (!d) return;
  const p = evtPos(e);
  if (d.paint){ const { cx, cy } = toCell(p.x, p.y);
    if (["wall","floor","rough","erase"].includes(state.brush)) paint(cx, cy); return; }
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
  if (!d || d.paint) return;
  const p = evtPos(e);
  if (!d.moved) return;
  const { cx, cy } = toCell(p.x, p.y);
  if (state.room.role === "dm") sendMoveTo(d.id, cx, cy, true);
  else planMove(cx, cy);
}
function sendMoveTo(tokenId, cx, cy, teleport){
  wsSend({ type:"move", token_id: tokenId, tx: cx, ty: cy, teleport });
}
function onDbl(e){
  if (state.editing) return;
  const p = evtPos(e), { cx, cy } = toCell(p.x, p.y);
  const wx = p.x - state.cam.ox, wy = p.y - state.cam.oy;
  if (tokenAt(wx, wy)) return;
  if (state.room.role === "dm"){
    const mine = state.tokens.filter(t => t.owner_user_id === state.me.id);
    if (mine.length === 1) sendMoveTo(mine[0].id, cx, cy, false);
    return;
  }
  planMove(cx, cy);
  if (state.plan && state.plan.goal.cx === cx && state.plan.goal.cy === cy) confirmPlan();
}
cv.addEventListener("mousedown", onDown); cv.addEventListener("touchstart", onDown, {passive:false});
cv.addEventListener("dblclick", onDbl);
cv.addEventListener("contextmenu", e => e.preventDefault());
window.addEventListener("mousemove", onMove); window.addEventListener("touchmove", onMove, {passive:false});
window.addEventListener("mouseup", onUp); window.addEventListener("touchend", onUp);
window.addEventListener("resize", resize);
window.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
  if (e.key === "Escape") clearPlan();
  state.keys.add(e.key);
});
window.addEventListener("keyup", e => state.keys.delete(e.key));

/* ---------- map editor (DM) ---------- */
function editorOpen(){
  state.editing = true;
  state.editMap = JSON.parse(JSON.stringify(state.grid));
  document.querySelectorAll(".brush").forEach(b => b.classList.toggle("active", b.dataset.b === "wall"));
  state.brush = "wall";
  $("editor").classList.remove("hidden");
  $("trap-fields").classList.add("hidden"); $("loot-fields").classList.add("hidden");
  $("ed-w").value = state.editMap.w; $("ed-h").value = state.editMap.h;
}
function editorClose(){ state.editing = false; state.editMap = null; $("editor").classList.add("hidden"); }
function edResize(){
  const w = Math.max(8, Math.min(80, +$("ed-w").value || 40));
  const h = Math.max(6, Math.min(60, +$("ed-h").value || 26));
  const old = state.editMap;
  const gm = { w, h, cell: old.cell, cells: new Array(w*h).fill(0), explored: new Array(w*h).fill(0),
               traps: old.traps.filter(t => t.x < w && t.y < h), loot: old.loot.filter(l => l.x < w && l.y < h) };
  for (let y = 0; y < Math.min(h, old.h); y++) for (let x = 0; x < Math.min(w, old.w); x++)
    gm.cells[y*w+x] = old.cells[y*old.w+x];
  state.editMap = gm;
}
