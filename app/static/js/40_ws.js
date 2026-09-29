/* ---------- websocket ---------- */
function wsSend(o){ if (state.ws && state.ws.readyState === 1) state.ws.send(JSON.stringify(o)); }
function connectWS(code){
  clearTimeout(state.reconnectTimer);
  if (state.ws) { state.ws.onclose = null; state.ws.close(); }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/${code}`);
  state.ws = ws;
  ws.onmessage = ev => {
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    if (m.type !== "event") return;
    const p = m.payload || {};
    switch (m.kind){
      case "chat": case "dice": appendChat({ id: p.id, username: p.username,
                       body: p.text ?? p.body, type: m.kind }); break;
      case "whisper": appendChat({ type:"whisper", body:p.text }); break;
      case "step": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t){ t.atx = p.x; t.aty = p.y;
                       if (Math.abs(t.atx-t.x) > state.grid.cell*3){ t.x = p.x; t.y = p.y; } }
                     break; }
      case "move": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t){ t.atx = t.x = p.x; t.aty = t.y = p.y; } break; }
      case "initiative": state.init = p; renderInit(); break;
      case "presence": state.online.add(p.username); renderOnline();
        appendChat({ type:"system", body: `${p.username} ${p.online ? "connected" : "disconnected"}` });
        break;
      case "explored": { const g = state.grid;
        if (g && p.cells) for (const i of p.cells){ g.explored[i] = 1;
          if (p.terrain && p.terrain[i] !== undefined) g.cells[i] = p.terrain[i]; }
        break; }
      case "map_changed": refreshRoom(); break;
      case "token_add": { upsertToken(p); break; }
      case "token_leave": { const g = state.tokens.find(t => t.id === p.token_id);
                            if (g){ state.ghosts = state.ghosts.filter(x => x.id !== g.id);
                                    state.ghosts.push({...g, atx:null, aty:null, ghost:true}); }
                            state.tokens = state.tokens.filter(t => t.id !== p.token_id);
                            if (state.sel === p.token_id){ state.sel = null; renderSheet(null); }
                            break; }
      case "token_gone": { state.tokens = state.tokens.filter(t => t.id !== p.token_id);
                           if (state.sel === p.token_id){ state.sel = null; renderSheet(null); }
                           break; }
      case "snapshot": refreshRoom(); break;
      case "error": toast(p.msg || "Error"); break;
    }
  };
  ws.onclose = (e) => {
    if (e.code === 4401){ toast("Session expired"); loadLobby().catch(()=>show("auth")); return; }
    if (state.room){ toast("Reconnecting…"); state.reconnectTimer = setTimeout(()=>connectWS(code), 1500); }
  };
}
function upsertToken(p){
  if (!p || p.id == null) return;
  state.ghosts = state.ghosts.filter(g => g.id !== p.id);
  const t = state.tokens.find(t => t.id === p.id);
  if (t){ Object.assign(t, {label:p.label, color:p.color, owner_user_id:p.owner_user_id,
                            character_id:p.character_id}); t.atx = p.x; t.aty = p.y;
          if (Math.abs(t.x - p.x) > cellSize()*3){ t.x = p.x; t.y = p.y; } }
  else state.tokens.push({...p, atx:null, aty:null});
}
