"""Shared connection, broadcast and map plumbing for the room hub."""
import asyncio
import json

from .. import db, mapmodel

# room_id -> {user_id: set(WebSocket)}
_clients: dict[int, dict[int, set]] = {}
# Socket identity (id()) -> the event loop that OWNS the socket's ASGI session.
# Production (uvicorn) = one loop for everything, so this always hits the fast
# path. Starlette's TestClient (>=1.7) runs each WebSocket session on its own
# loop, and anyio wakeups must not cross loops — delivering to a foreign loop
# there would lose wakeups (lost chat/ping events, intermittent test hangs).
_ws_loops: dict[int, asyncio.AbstractEventLoop] = {}
LOOP: asyncio.AbstractEventLoop | None = None
# Per-room locks guarding map read-modify-write (fog reveal, trap/loot flags,
# map edits) so concurrent walks of different tokens can't clobber each other.
_map_locks: dict[int, asyncio.Lock] = {}


def map_lock(room_id) -> asyncio.Lock:
    return _map_locks.setdefault(room_id, asyncio.Lock())


def clients(room_id):
    return _clients.setdefault(room_id, {})


def attach_ws(ws):
    """Call from the socket's own pump task right after accept()."""
    _ws_loops[id(ws)] = asyncio.get_running_loop()


def detach_ws(ws):
    _ws_loops.pop(id(ws), None)


async def _deliver(ws, msg):
    await ws.send_text(msg)


async def _send(ws, msg):
    cur = asyncio.get_running_loop()
    tgt = _ws_loops.get(id(ws))
    if tgt is None or tgt is cur:
        await _deliver(ws, msg)
        return
    await asyncio.wrap_future(
        asyncio.run_coroutine_threadsafe(_deliver(ws, msg), tgt))


def notify(room_id, kind, payload):
    """Thread-safe fire-and-forget broadcast (called from the REST threadpool)."""
    if LOOP and LOOP.is_running():
        asyncio.run_coroutine_threadsafe(broadcast(room_id, kind, payload), LOOP)


async def send_to(ws, kind, payload):
    try:
        await _send(ws, json.dumps({"type": "event", "kind": kind, "payload": payload}))
    except Exception:
        pass


async def send_user(room_id, user_id, kind, payload):
    for ws in list(clients(room_id).get(user_id, ())):
        await send_to(ws, kind, payload)


async def broadcast(room_id, kind, payload, exclude_ws=None):
    msg = json.dumps({"type": "event", "kind": kind, "payload": payload})
    for uid, socks in list(clients(room_id).items()):
        for ws in list(socks):
            if ws is exclude_ws:
                continue
            try:
                await _send(ws, msg)
            except Exception:
                socks.discard(ws)
                detach_ws(ws)


def sys_msg(room_id, body):
    db.x("INSERT INTO messages (room_id,type,body) VALUES (?,'system',?)", (room_id, body))


def get_map(room_id) -> dict:
    st = db.q1("SELECT map_json FROM room_state WHERE room_id=?", (room_id,))
    return mapmodel.load((st or {}).get("map_json"))


def set_map(room_id, mp):
    db.x("UPDATE room_state SET map_json=? WHERE room_id=?", (json.dumps(mp), room_id))


def fog_patch(mp, newly):
    return {"cells": newly, "terrain": {str(i): mp["cells"][i] for i in newly}}


def save_map_and_notify(room_id, mp):
    set_map(room_id, mp)
    notify(room_id, "map_changed", None)
