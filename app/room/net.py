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


async def _deliver_close(ws, code):
    await ws.close(code=code)


async def close_to(ws, code=1000):
    """Close a socket on the event loop that OWNS it (same cross-loop rules
    as _send)."""
    cur = asyncio.get_running_loop()
    tgt = _ws_loops.get(id(ws))
    if tgt is None or tgt is cur:
        await _deliver_close(ws, code)
        return
    await asyncio.wrap_future(
        asyncio.run_coroutine_threadsafe(_deliver_close(ws, code), tgt))


async def _room_deleted_and_close(ws, code):
    await send_to(ws, "room_deleted", {"code": code})
    try:
        await ws.close(code=1000)
    except Exception:
        pass


def purge_room_nowait(room_id, code, token_ids=()):
    """The room was deleted (D76) — announce room_deleted, stop every walk,
    close every socket, forget all in-memory traces. No zombie room state.

    Deliberately NOT routed through the global LOOP: under TestClient no
    lifespan runs, and correctness must not hinge on that. Every socket is
    handled on the loop that OWNS it; every walk task is cancelled on the loop
    that created it (Task.get_loop)."""
    from .movement import _walks, _cancel_walk   # late: movement imports net
    from . import visibility                      # late: visibility imports net
    socks = [ws for users in list(_clients.get(room_id, {}).values())
             for ws in list(users)]
    for ws in socks:
        tgt = _ws_loops.get(id(ws))
        if tgt is not None and tgt.is_running():
            asyncio.run_coroutine_threadsafe(_room_deleted_and_close(ws, code), tgt)
    for tid in token_ids:
        task = _walks.get(tid)
        loop = task.get_loop() if task is not None else LOOP
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(_cancel_walk(tid), loop)
    _clients.pop(room_id, None)
    _map_locks.pop(room_id, None)
    visibility._last_seen.pop(room_id, None)


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


def get_map(room_id, floor="") -> dict:
    """D88 — the PRIMARY floor ("") keeps reading room_state.map_json exactly
    as before (zero migration, byte-identical behaviour for every old room).
    A named floor has its own map row; a never-edited named floor returns a
    BLANK map sized to the primary (a fresh plane, not a copy of below)."""
    base = mapmodel.load((db.q1("SELECT map_json FROM room_state WHERE room_id=?",
                                (room_id,)) or {}).get("map_json"))
    if not floor:
        return base
    row = db.q1("SELECT map_json FROM floor_maps WHERE room_id=? AND floor=?",
                (room_id, str(floor)))
    if row is None:
        blank = mapmodel.load(None)
        blank["fog_off"] = False                    # room-wide flag lives on primary
        return mapmodel.fit(blank, base)
    mp = mapmodel.fit(mapmodel.load(row["map_json"]), base)
    mp["fog_off"] = bool(base.get("fog_off"))     # room-wide flag lives on primary
    return mp


def set_map(room_id, mp, floor=""):
    if not floor:
        db.x("UPDATE room_state SET map_json=? WHERE room_id=?", (json.dumps(mp), room_id))
        return
    db.x("INSERT INTO floor_maps(room_id,floor,map_json) VALUES(?,?,?) "
         "ON CONFLICT(room_id,floor) DO UPDATE SET map_json=excluded.map_json",
         (room_id, str(floor), json.dumps(mp)))


def plane_viewers(room_id, floor):
    """user_ids who legitimately STAND on a plane: every DM, and everyone with
    a token (owned or operated) there (D88). Plane-scoped broadcasts (fog,
    object state, door reveals) must never wake sockets that are elsewhere —
    a client would happily paint another plane's cells into its own grid."""
    uids = set()
    for m in db.q("SELECT user_id, role FROM room_members WHERE room_id=?", (room_id,)):
        if m["role"] == "dm":
            uids.add(m["user_id"])
    for t in db.q("SELECT owner_user_id, controller_user_id FROM tokens "
                  "WHERE room_id=? AND floor=?", (room_id, str(floor))):
        if t["owner_user_id"]:
            uids.add(t["owner_user_id"])
        if t["controller_user_id"]:
            uids.add(t["controller_user_id"])
    return uids


async def send_to_plane(room_id, floor, kind, payload):
    for uid in plane_viewers(room_id, floor):
        for sock in list(clients(room_id).get(uid) or ()):
            await send_to(sock, kind, payload)


def plane_watchers(room_id, floor):
    """Who may SEE an event painted on a plane (SPRINT-20, aoe/pings): the
    plane's token holders and every DM (plane_viewers), PLUS the token-less
    observers — the /state convention says nobody stands nowhere: without any
    token you stand on the PRIMARY plane. Strict map-truth channels (fog,
    doors, objects) keep the narrower ``plane_viewers`` set."""
    uids = plane_viewers(room_id, floor)
    if not floor:
        for m in db.q("SELECT user_id FROM room_members WHERE room_id=?", (room_id,)):
            if db.q1("SELECT 1 AS hit FROM tokens WHERE room_id=? AND "
                     "(owner_user_id=? OR controller_user_id=?) LIMIT 1",
                     (room_id, m["user_id"], m["user_id"])) is None:
                uids.add(m["user_id"])
    return uids


async def send_to_plane_viewed(room_id, floor, kind, payload):
    for uid in plane_watchers(room_id, floor):
        for sock in list(clients(room_id).get(uid) or ()):
            await send_to(sock, kind, payload)


def fog_patch(mp, newly):
    return {"cells": newly, "terrain": {str(i): mp["cells"][i] for i in newly}}


def save_map_and_notify(room_id, mp, floor=""):
    set_map(room_id, mp, floor)
    notify(room_id, "map_changed", None)
