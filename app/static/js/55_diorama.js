/* ---------- diorama view (client-local 2.5D prototype) ----------
   Renders the SAME authoritative, already per-viewer-filtered state as the
   tactical view (state.grid / state.tokens / state.ghosts). Visibility comes
   from visibleHere() — the same mask the tactical renderer uses; this file
   never requests extra data and never reveals hidden server state.
   Original generic placeholder shapes only — no copied art. Upright token
   billboards ("paper cards") are an original style, not derived from or
   copying any third-party product's visuals. */
const DIO = { wallH: 0.62 };

function dioProj(lx, ly, c){               // lattice (continuous) -> screen
  return [ (lx - ly) * c * 0.5 + state.cam.ox, (lx + ly) * c * 0.25 + state.cam.oy ];
}
function dioUnproj(wx, wy, c){             // screen -> lattice (continuous)
  const a = (wx - state.cam.ox) / (c * 0.5), b = (wy - state.cam.oy) / (c * 0.25);
  return { lx: b/2 + a/2, ly: b/2 - a/2 };
}
function fillPoly(pts, color, stroke){
  ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
  ctx.closePath(); ctx.fillStyle = color; ctx.fill();
  if (stroke){ ctx.strokeStyle = stroke; ctx.lineWidth = 1; ctx.stroke(); }
}
function dioCellQuad(cx, cy, c, lift){
  const L = lift || 0;
  return [ dioProj(cx, cy, c), dioProj(cx+1, cy, c), dioProj(cx+1, cy+1, c), dioProj(cx, cy+1, c) ]
    .map(p => [p[0], p[1] - L]);
}
function drawDiorama(){
  const { w, h } = view(), c = cellSize(), g = state.grid;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#0a0b10"; ctx.fillRect(0, 0, w, h);
  if (!g || !g.cells){
    ctx.fillStyle = "#3a4157"; ctx.font = "bold 14px sans-serif"; ctx.textAlign = "center";
    ctx.fillText("Diorama view: no map yet", w/2, h/2);
    return;
  }
  const tiles = [], cards = [];
  for (let gy = 0; gy < g.h; gy++) for (let gx = 0; gx < g.w; gx++){
    const i = gy * g.w + gx;
    if (!visibleHere(i)) continue;                       // same fog/LOS mask as tactical
    tiles.push({ z: gx + gy, kind: "cell", gx, gy, ter: g.cells[i] });
  }
  for (const d of (g.doors || [])){
    if (!visibleHere(d.y * g.w + d.x)) continue;
    tiles.push({ z: d.x + d.y + 1.5, kind: "door", d });   // edge centre in lattice space
  }
  for (const t of state.tokens){
    const side = SIZE_FOOTPRINT[t.size] || 1;
    const cx = t.x / c, cy = t.y / c;
    let seen = false;                    // parity with the server: ANY footprint cell may reveal
    for (let dy = 0; dy < side && !seen; dy++) for (let dx = 0; dx < side && !seen; dx++){
      const ix = Math.floor(cx) + dx, iy = Math.floor(cy) + dy;
      if (ix < 0 || iy < 0 || ix >= g.w || iy >= g.h) continue;
      if (visibleHere(iy * g.w + ix)) seen = true;
    }
    if (!seen) continue;
    cards.push({ z: cx + cy + side, kind: "token", t, side });
  }
  for (const gh of state.ghosts){
    cards.push({ z: gh.x / c + gh.y / c + 1, kind: "ghost", gh });
  }
  tiles.sort((a, b) => a.z - b.z);
  cards.sort((a, b) => a.z - b.z);
  for (const it of tiles){
    if (it.kind === "cell") dioCell(it, c); else dioDoor(it, c);
  }
  for (const it of cards){
    if (it.kind === "token") dioToken(it, c); else dioGhost(it, c);
  }
  if (state.plan && state.plan.cells){                   // server path preview
    for (const pt of state.plan.cells){
      const i = pt.y * g.w + pt.x;
      if (i < 0 || i >= g.cells.length || g.cells[i] === 1) continue;
      fillPoly(dioCellQuad(pt.x, pt.y, c), "rgba(212,160,23,0.35)");
    }
  }
}
function dioCell(it, c){
  const q = dioCellQuad(it.gx, it.gy, c);
  if (it.ter === 1){
    const H = DIO.wallH * c;
    fillPoly([q[3], q[2], [q[2][0], q[2][1]-H], [q[3][0], q[3][1]-H]], "#333a4e");   // SW face
    fillPoly([q[2], q[1], [q[1][0], q[1][1]-H], [q[2][0], q[2][1]-H]], "#3f4761");   // SE face
    fillPoly(dioCellQuad(it.gx, it.gy, c, H), "#4a5270", "#232838");                 // top
    return;
  }
  fillPoly(q, it.ter === 2 ? "#20281d" : "#151823", "#232735");
}
function dioDoor(it, c){
  const d = it.d;
  const A = d.dir === "v" ? dioProj(d.x+1, d.y, c)   : dioProj(d.x, d.y+1, c);
  const B = d.dir === "v" ? dioProj(d.x+1, d.y+1, c) : dioProj(d.x+1, d.y+1, c);
  if (d.closed){
    const H = DIO.wallH * c * 0.8, col = d.locked ? "#7d4f27" : "#b9814a";
    fillPoly([[A[0], A[1]-H], [B[0], B[1]-H], B, A], col, "#0d0f14");
    if (d.locked){
      ctx.fillStyle = "#f1c40f"; ctx.font = `${Math.max(9, c*0.24)}px sans-serif`;
      ctx.textAlign = "center"; ctx.fillText("🔒", (A[0]+B[0])/2, (A[1]+B[1])/2 - H*0.45);
    }
  } else {
    ctx.save(); ctx.strokeStyle = "#2ecc71"; ctx.lineWidth = 3; ctx.lineCap = "round";
    ctx.beginPath(); ctx.moveTo(A[0], A[1]); ctx.lineTo(B[0], B[1]); ctx.stroke();
    ctx.restore();
  }
}
function dioToken(it, c){
  const t = it.t, side = it.side;
  const base = dioProj(t.x/c + side/2, t.y/c + side/2, c);
  const bw = Math.min(c * 0.6 * side, c * 1.7), bh = bw * 1.3;
  const activeInit = state.init && state.init.combat && state.init.order[state.init.active];
  const isActive = activeInit && activeInit.token_id === t.id;
  ctx.save();
  ctx.globalAlpha = .35; ctx.fillStyle = "#000";
  ctx.beginPath(); ctx.ellipse(base[0], base[1], bw*0.42, bw*0.18, 0, 0, Math.PI*2); ctx.fill();
  ctx.globalAlpha = 1;
  ctx.fillStyle = "#e8e4d8"; ctx.fillRect(base[0]-bw/2, base[1]-bh, bw, bh);
  ctx.fillStyle = t.color; ctx.fillRect(base[0]-bw/2, base[1]-bh, bw, Math.max(6, bh*0.28));
  const dead = t.death && t.death.dead;
  ctx.fillStyle = "#1c1f28"; ctx.font = `bold ${Math.max(11, bw*0.42)}px sans-serif`;
  ctx.textAlign = "center";
  ctx.fillText(dead ? "☠" : (t.label || "?").slice(0, 2).toUpperCase(), base[0], base[1] - bh*0.55);
  ctx.fillStyle = "#3a3f4c"; ctx.font = `${Math.max(9, bw*0.2)}px sans-serif`;
  ctx.fillText((t.label || "").slice(0, 12), base[0], base[1] - bh*0.22);
  const m = state.room.members.find(x => x.user_id === t.owner_user_id);
  const hpPct = m && m.char ? Math.max(0, m.char.hp / m.char.max_hp)
              : (t.npc ? Math.max(0, (t.npc.hp||0) / (t.npc.max_hp||1)) : null);
  if (hpPct !== null){
    ctx.fillStyle = "#111"; ctx.fillRect(base[0]-bw*0.4, base[1]-bh*0.13, bw*0.8, 4);
    ctx.fillStyle = hpPct <= .25 ? "#c0392b" : (m && m.char ? "#27ae60" : "#e07b39");
    ctx.fillRect(base[0]-bw*0.4, base[1]-bh*0.13, bw*0.8*hpPct, 4);
  }
  ctx.lineWidth = (t.id === state.sel || isActive) ? 3 : 1;
  ctx.strokeStyle = t.id === state.sel ? "#d4a017" : (isActive ? "#fff" : "#0d0f14");
  ctx.strokeRect(base[0]-bw/2, base[1]-bh, bw, bh);
  ctx.restore();
}
function dioGhost(it, c){
  const base = dioProj(it.gh.x / c + 0.5, it.gh.y / c + 0.5, c);
  const bw = c*0.5, bh = bw*1.3;
  ctx.save(); ctx.globalAlpha = .3;
  ctx.fillStyle = it.gh.color || "#9aa";
  ctx.fillRect(base[0]-bw/2, base[1]-bh, bw, bh);
  ctx.strokeStyle = "#9aa"; ctx.setLineDash([4,3]);
  ctx.strokeRect(base[0]-bw/2, base[1]-bh, bw, bh); ctx.setLineDash([]);
  ctx.fillStyle = "#cfd3e0"; ctx.font = `bold ${bw*0.4}px sans-serif`; ctx.textAlign = "center";
  ctx.fillText((it.gh.label || "?").slice(0, 2).toUpperCase(), base[0], base[1] - bh*0.5);
  ctx.restore();
}
/* ---------- diorama input: select, door toggle, server path preview/move ----
   Reuses existing authoritative handlers only (door toggle, path_preview,
   move). No client-side rules and no pathfinding here. Movement beyond a
   preview confirm is intentionally the same flow as tactical. */
function dioTokenClick(wx, wy, c){
  let best = null, bd = Infinity;
  for (const t of state.tokens){
    const side = SIZE_FOOTPRINT[t.size] || 1;
    const base = dioProj(t.x/c + side/2, t.y/c + side/2, c);
    const bw = Math.min(c * 0.6 * side, c * 1.7), bh = bw * 1.3;
    const dx = Math.abs(wx - base[0]), dy = wy - (base[1] - bh/2);
    if (dx <= bw/2 + c*0.12 && Math.abs(dy) <= bh/2 + c*0.12){
      const d = dx*dx + dy*dy;
      if (d < bd){ bd = d; best = t; }
    }
  }
  return best;
}
function dioDoorClick(wx, wy, c){
  const g = state.grid; let best = null, bd = c*0.4;
  for (const d of (g.doors || [])){
    if (!visibleHere(d.y * g.w + d.x)) continue;
    const A = d.dir === "v" ? dioProj(d.x+1, d.y, c)   : dioProj(d.x, d.y+1, c);
    const B = d.dir === "v" ? dioProj(d.x+1, d.y+1, c) : dioProj(d.x+1, d.y+1, c);
    const dd = segDist(wx, wy, A, B);
    if (dd < bd){ bd = dd; best = d; }
  }
  return best;
}
function dioramaDown(p){
  const g = state.grid, c = cellSize();
  const wx = p.x - state.cam.ox, wy = p.y - state.cam.oy;
  const t = g ? dioTokenClick(wx, wy, c) : null;
  if (t){ renderSheet(t); return; }
  const d = g ? dioDoorClick(wx, wy, c) : null;
  if (d){ wsSend({ type:"door", x: d.x, y: d.y, dir: d.dir, action:"toggle" }); return; }
  renderSheet(null);
  if (g && state.room && state.room.role !== "dm" && ownToken()){
    const { lx, ly } = dioUnproj(wx, wy, c);
    const cx = Math.floor(lx), cy = Math.floor(ly);
    if (cx < 0 || cy < 0 || cx >= g.w || cy >= g.h) return;
    if (state.plan && state.plan.goal.cx === cx && state.plan.goal.cy === cy) confirmPlan();
    else planMove(cx, cy);          // requests SERVER path preview, same as tactical
  }
}
