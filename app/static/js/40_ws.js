/* ---------- websocket ---------- */
(typeof window !== "undefined") && ((window.__BUILDS = window.__BUILDS || {})["40_ws.js"] = window.__BUILD__ || "?");
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
      case "map_expanded": {
        // D72: world coordinates NEVER move — the map window grew. Nothing on
        // screen shifts, so the camera must NOT be compensated (the old pixel
        // shift double-moved every token — the reported teleporting). Just
        // refetch the coherent new state.
        refreshRoom().then(() => {
          if (state.viewMode === "diorama" && typeof fitDiorama === "function") fitDiorama();
        }); break;
      }
      case "token_add": { upsertToken(p); renderVoiceTargets(); break; }
      case "token_leave": { const g = state.tokens.find(t => t.id === p.token_id);
                            if (g){ state.ghosts = state.ghosts.filter(x => x.id !== g.id);
                                    state.ghosts.push({...g, atx:null, aty:null, ghost:true}); }
                            state.tokens = state.tokens.filter(t => t.id !== p.token_id);
                            state.moving.delete(p.token_id);
                            if (state.sel === p.token_id){ state.sel = null; renderSheet(null); }
                            renderVoiceTargets(); break; }
      case "token_gone": { state.tokens = state.tokens.filter(t => t.id !== p.token_id);
                           state.ghosts = state.ghosts.filter(x => x.id !== p.token_id);
                           state.moving.delete(p.token_id);
                           if (state.sel === p.token_id){ state.sel = null; renderSheet(null); }
                           renderVoiceTargets(); break; }
      case "snapshot": refreshRoom().then(() => { if (state.sel) renderSheet(state.tokens.find(t => t.id === state.sel) || null); }); break;
      case "token_span": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t){ t.fw = p.fw; t.fh = p.fh;          // authoritative shape (15B)
                       if (state.sel === p.token_id) renderSheet(t); } break; }
      case "token_visual": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t){ t.vw = p.vw; t.vh = p.vh;          // D82: presentation bounds only
                       if (state.sel === p.token_id) renderSheet(t); } break; }
      case "token_light": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t){ t.light = p.radius | 0;
                       if (state.sel === p.token_id) renderSheet(t); } break; }
      case "grid_reveal": refreshRoom(); break;   // D87: light changes re-lit the world
      case "token_floor": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t){ t.floor = p.floor || "";           // D86: plane change; add/leave follow
                       if (state.room && state.room.role === "dm" && typeof renderViewFloor === "function") renderViewFloor();
                       if (t.owner_user_id === state.me.id) refreshRoom();  // D88: view follows your token
                       if (state.sel === p.token_id) renderSheet(t); } break; }
      case "token_darkvision": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t) t.darkvision = p.radius | 0; } break;   // D89: owner-only sense
      case "floors_changed": { state.floors = p.floors || [""];  // D86: DM curated floor list
                     if (typeof renderViewFloor === "function") renderViewFloor();
                     if (state.sel) renderSheet(state.tokens.find(t => t.id === state.sel)); } break;
      case "token_image": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t){ t.image = p.image || "";           // D85: server-made /assets/ ref
                       if (state.sel === p.token_id) renderSheet(t); } break; }
      case "token_rot": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t){ t.rot = p.rot;                     // D83: the entity turns —
                       if (p.x !== undefined){ t.x = p.x; t.y = p.y; }   // re-centred anchor rides along
                       if (state.sel === p.token_id) renderSheet(t); } break; }
      case "token_controller": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t){ t.controller_user_id = p.controller_user_id ?? null;   // D82 companion
                       if (state.sel === p.token_id) renderSheet(t); } break; }
      case "token_mount": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t){ t.mount_token_id = p.mount_token_id ?? null;           // D82 rider
                       if (state.sel === p.token_id) renderSheet(t); } break; }
      case "cond": { const t = state.tokens.find(t => t.id === p.token_id);
                     if (t){ t.conds = p.conds || [];
                       if (state.sel === p.token_id) renderSheet(t); } break; }
      case "death": { const t = state.tokens.find(t => t.id === p.token_id);
                      if (t){ t.death = p.death || null;
                        if (state.sel === p.token_id) renderSheet(t); } break; }
      case "object_state": { const o = state.grid && (state.grid.objects || []).find(o => o.id === p.object_id);
                     if (o){ o.state = p.state || {}; draw(); }   // D82: authoritative world state
                     break; }
      case "aoe": showAoe(p); break;
      case "ping": showPing(p); break;
      case "room_deleted": {
        // D76: this room is gone — leave immediately and NEVER auto-reconnect
        // into a deleted room (the old behaviour zombie-looped /ws/<code> 404s).
        state.roomDeleted = true;
        clearTimeout(state.reconnectTimer);
        if (state.ws){ state.ws.onclose = null; state.ws.close(); state.ws = null; }
        toast("This room was deleted by its DM");
        state.room = null; editorClose(); loadLobby().catch(() => show("auth"));
        break;
      }
      case "error": toast(p.msg || "Error"); break;
    }
  };
  ws.onclose = (e) => {
    if (e.code === 4401){ toast("Session expired"); loadLobby().catch(()=>show("auth")); return; }
    if (state.room && !state.roomDeleted){ toast("Reconnecting…"); state.reconnectTimer = setTimeout(()=>connectWS(code), 1500); }
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
