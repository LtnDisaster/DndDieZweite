"""WebSocket entry point: authenticate, parse, dispatch, manage lifecycle.

Gameplay lives in app/room/*. This module keeps only the connection plumbing and
re-exports the few helpers REST/rooms.py reach through ``ws`` (notify, build_seen,
token_cell, _last_seen) so those call sites are unchanged."""
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import auth, db
from .room.dispatch import handle
from .room.movement import _walks
from .room.net import (_clients, broadcast, clients, fog_patch, get_map, notify,
                       send_to, set_map, sys_msg)
from .room.visibility import (_last_seen, build_seen, owned_cells, prune_viewer_last_seen,
                              token_cell)

log = logging.getLogger("vtt.ws")
router = APIRouter()


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
    room_id, is_dm = room["id"], member["role"] == "dm"
    await ws.accept()
    socks = clients(room_id).setdefault(user["id"], set())
    first = not socks
    socks.add(ws)
    mpj = get_map(room_id)
    newly = []
    for tk in db.q("SELECT x, y FROM tokens WHERE room_id=? AND owner_user_id=?", (room_id, user["id"])):
        newly += _reveal(mpj, int(tk["x"] // mpj["cell"]), int(tk["y"] // mpj["cell"]))
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
        if not socks:
            clients(room_id).pop(user["id"], None)
            prune_viewer_last_seen(room_id, user["id"])
            sys_msg(room_id, f"{user['username']} disconnected.")
            await broadcast(room_id, "presence", {"username": user["username"], "online": False})


def _reveal(mp, cx, cy):
    from . import mapmodel
    return mapmodel.reveal(mp, cx, cy)
