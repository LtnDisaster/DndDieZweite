"""WebSocket entry point: authenticate, parse, dispatch, manage lifecycle.

Gameplay lives in app/room/*. This module keeps only the connection plumbing and
re-exports the few helpers REST/rooms.py reach through ``ws`` (notify, viewer_visible_cells,
token_cell, _last_seen) so those call sites remain thin."""
import json
import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import auth, db, footprint, los, mapmodel
from .room.dispatch import handle
from .room.movement import _walks
from .room.net import (_clients, attach_ws, broadcast, clients, detach_ws,
                       fog_patch, get_map, notify, send_to, set_map, sys_msg)
from .room.visibility import (_last_seen, prune_viewer_last_seen, token_cell,
                              viewer_source_cells, viewer_visible_cells)

log = logging.getLogger("vtt.ws")
router = APIRouter()


def _origin_ok(ws) -> bool:
    """Same-origin gate for the WebSocket handshake.

    Browsers always send Origin on WS handshakes; the session cookie is
    SameSite=Lax (which already blocks cross-site WS cookies in modern
    browsers), but we validate explicitly as a second line of defence.
    Extra origins (e.g. an https hostname behind a proxy) go into
    VTT_ALLOWED_ORIGINS as a comma-separated list. Non-browser clients send
    no Origin and stay protected by the cookie check alone."""
    origin = (ws.headers.get("origin") or "").strip().lower()
    if not origin:
        return True
    extra = {o.strip().lower() for o in
             os.environ.get("VTT_ALLOWED_ORIGINS", "").split(",") if o.strip()}
    if origin in extra:
        return True
    host = (ws.headers.get("host") or "").strip().lower()
    return origin in (f"http://{host}", f"https://{host}")


@router.websocket("/ws/{code}")
async def ws_room(ws: WebSocket, code: str):
    uid = auth.read_token(ws.cookies.get(auth.COOKIE, ""))
    user = db.q1("SELECT id, username FROM users WHERE id=?", (uid,)) if uid else None
    room = db.q1("SELECT * FROM rooms WHERE code=?", (code.upper(),))
    member = db.q1("SELECT * FROM room_members WHERE room_id=? AND user_id=?",
                   (room["id"], uid)) if (room and user) else None
    if user is None or room is None or member is None:
        await ws.close(code=4401)
        return
    if not _origin_ok(ws):
        log.warning("WS rejected cross-origin handshake (room=%s origin=%s)",
                    code, ws.headers.get("origin"))
        await ws.close(code=4403)
        return
    room_id, is_dm = room["id"], member["role"] == "dm"
    await ws.accept()
    attach_ws(ws)   # remember the loop this session lives on (net._send)
    socks = clients(room_id).setdefault(user["id"], set())
    first = not socks
    socks.add(ws)
    mpj = get_map(room_id)
    newly = []
    for tk in db.q("SELECT id, x, y, owner_user_id, size FROM tokens WHERE room_id=? AND owner_user_id=?",
                   (room_id, user["id"])):
        newly += _reveal_token(mpj, tk)
    if newly:
        set_map(room_id, mpj)
        await broadcast(room_id, "explored", fog_patch(mpj, newly))
    if first:
        sys_msg(room_id, f"{user['username']} connected.")
        await broadcast(room_id, "presence", {"username": user["username"], "online": True})
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            try:
                await handle(ws, room_id, user, is_dm, msg)
            except Exception:
                mtype = msg.get("type") if isinstance(msg, dict) else "?"
                log.exception("WS handler failed (room=%s user=%s type=%s)", room_id, user["id"], mtype)
                await send_to(ws, "error", {"msg": "Could not process that action"})
    except WebSocketDisconnect:
        pass
    finally:
        socks.discard(ws)
        detach_ws(ws)
        if db.q1("SELECT 1 AS ok FROM rooms WHERE id=?", (room_id,)) is not None:
            if not socks:
                clients(room_id).pop(user["id"], None)
                prune_viewer_last_seen(room_id, user["id"])
                sys_msg(room_id, f"{user['username']} disconnected.")
                await broadcast(room_id, "presence", {"username": user["username"], "online": False})
        # D76: if the room row is gone it was deleted mid-session — purge_room
        # owns that cleanup; leaving teardown bookkeeping and a disconnect
        # message behind would fail the FK and resurrect zombie registries.


def _reveal_token(mp, token):
    return mapmodel.reveal_cells(mp, los.visible_cells(
        mp, footprint.player_source_cells(mp, [token]), radius=mapmodel.FOG_R))
