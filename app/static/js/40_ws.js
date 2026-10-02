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
      case "chat": appendChatMessage(p); break;
      case "narrative": {
        const entry = { ...p, type:"narrative" };
        appendChatMessage(entry);
        if (entry.meta?.overlay || entry.style) showNarrativeOverlay(entry);
        break;
      }
      case "dice": appendGameLogMessage({ id:p.id, username:p.username, body:p.text ?? p.body,
                                          type:"dice", visibility:p.visibility, meta:p.meta }); break;
      case "system": appendGameLogMessage({ id:p.id, username:p.username, body:p.text ?? p.body,
                                            type:"system", visibility:p.visibility }); break;
      case "quests_changed": refreshRoom(); break;
      case "whisper": appendGameLogMessage({ type:"whisper", body:p.text }); break;
      case "ambience": applyAudioState(p); break;
      case "sound": playSoundEvent(p); break;
      case "step": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t){ t.atx = p.x; t.aty = p.y;
                       if (Math.abs(t.atx-t.x) > state.grid.cell*3){ t.x = p.x; t.y = p.y; } }
                     break; }
      case "move": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t){ t.atx = t.x = p.x; t.aty = t.y = p.y; } break; }
      case "path_preview": applyPathPreview(p); break;
      case "move_state": {
        if (p.moving) state.moving.add(p.token_id); else state.moving.delete(p.token_id);
        if (p.reason === "trap") toast("Movement stopped: trap triggered");
        updateMoveControls();
        break;
      }
      case "fog_changed": {
        const g = state.grid;
        if (g){
          for (const idx in p.cells){ const i = +idx;
            g.explored[i] = p.cells[idx];
            if (p.terrain && p.terrain[idx] !== undefined) g.cells[i] = p.terrain[idx];
          }
          draw();
        }
        break;
      }
      case "initiative": state.init = p; renderInit(); break;
      case "presence": state.online.add(p.username); renderOnline();
        appendGameLogMessage({ type:"system", body: `${p.username} ${p.online ? "connected" : "disconnected"}` });
        break;
      case "explored": { const g = state.grid;
        if (g && p.cells) for (const i of p.cells){ g.explored[i] = 1;
          if (p.terrain && p.terrain[i] !== undefined) g.cells[i] = p.terrain[i]; }
        break; }
      case "map_changed": refreshRoom(); break;
      case "token_add": { upsertToken(p); renderVoiceTargets(); break; }
      case "token_leave": { const g = state.tokens.find(t => t.id === p.token_id);
                            if (g){ state.ghosts = state.ghosts.filter(x => x.id !== g.id);
                                    state.ghosts.push({...g, atx:null, aty:null, ghost:true}); }
                            state.tokens = state.tokens.filter(t => t.id !== p.token_id);
                            state.moving.delete(p.token_id);
                            if (state.sel === p.token_id){ state.sel = null; renderSheet(null); }
                            renderVoiceTargets(); break; }
      case "token_gone": { state.tokens = state.tokens.filter(t => t.id !== p.token_id);
                           state.moving.delete(p.token_id);
                           if (state.sel === p.token_id){ state.sel = null; renderSheet(null); }
                           renderVoiceTargets(); break; }
      case "snapshot": refreshRoom().then(() => { if (state.sel) renderSheet(state.tokens.find(t => t.id === state.sel) || null); }); break;
      case "cond": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t){ t.conds = p.conds || [];
                       if (state.sel === p.token_id) renderSheet(t); } break; }
      case "death": { const t = state.tokens.find(t => t.id === p.token_id);
                      if (t){ t.death = p.death || null;
                        if (state.sel === p.token_id) renderSheet(t); } break; }
      case "aoe": showAoe(p); break;
      case "ping": showPing(p); break;
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
