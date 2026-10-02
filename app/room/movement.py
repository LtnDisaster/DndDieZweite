"""Grid movement: DM teleport and animated A* walks, with LOS reveal + trap/loot checks.

Map read-modify-write (reveal, trap/loot flag flip, persist) is serialised per room
by net.map_lock so concurrent walks of different tokens can't clobber each other.
"""
import asyncio

from .. import db, footprint, los, mapmodel
from ..path import find_path, path_footprint_cost
from .net import broadcast, fog_patch, get_map, map_lock, send_to, set_map
from .traps import at_cell, hit_trap, take_loot
from .visibility import broadcast_token_step, viewer_visible_cells

STEP_DELAY = 0.11
# token_id -> walk asyncio.Task
_walks: dict[int, asyncio.Task] = {}


async def _cancel_walk(token_id):
    task = _walks.pop(token_id, None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _announce_move(room_id, token_id, moving, reason=None):
    payload = {"token_id": token_id, "moving": bool(moving)}
    if reason:
        payload["reason"] = reason
    await broadcast(room_id, "move_state", payload)


def _room_tokens(room_id, exclude_id=None):
    return [t for t in db.q("SELECT id, x, y, owner_user_id, size FROM tokens WHERE room_id=?",
                            (room_id,)) if t["id"] != exclude_id]


def _reveal_player_token(mp, tok):
    if tok["owner_user_id"] is None:
        return [], mp
    return los.visible_cells(mp, footprint.player_source_cells(mp, [tok]), radius=mapmodel.FOG_R), mp


async def handle_move(ws, room_id, user, is_dm, msg):
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None:
        return
    if not (is_dm or tok["owner_user_id"] == user["id"]):
        await send_to(ws, "error", {"msg": "You can only move your own token"})
        return
    mp = get_map(room_id)
    cell = mp["cell"]
    try:
        tx, ty = int(msg["tx"]), int(msg["ty"])
    except (KeyError, ValueError, TypeError):
        return
    origin, side = footprint.occupied_origin(mp, tok)
    tx, ty = max(0, min(mp["w"] - side, tx)), max(0, min(mp["h"] - side, ty))
    tokens = _room_tokens(room_id, tok["id"])

    if msg.get("teleport") and is_dm:
        if origin == (tx, ty):
            return
        if not footprint.valid_final_position(mp, tok, (tx, ty), tokens):
            await send_to(ws, "error", {"msg": "Invalid teleport destination for this footprint"})
            return
        x, y = footprint.origin_pixels((tx, ty), side, cell)
        db.x("UPDATE tokens SET x=?, y=? WHERE id=?", (x, y, tok["id"]))
        tok["x"], tok["y"] = x, y
        await broadcast_token_step(room_id, tok, x, y, tx, ty)
        # Only a player-owned token lifts fog; NPC/DM tokens never reveal for players.
        if tok["owner_user_id"] is not None:
            async with map_lock(room_id):
                mp = get_map(room_id)
                visible, _ = _reveal_player_token(mp, tok)
                newly = mapmodel.reveal_cells(mp, visible)
                if newly:
                    set_map(room_id, mp)
            if newly:
                await broadcast(room_id, "explored", fog_patch(mp, newly))
        return

    if origin == (tx, ty):
        return
    path = find_path(mp["w"], mp["h"], mp["cells"], origin, (tx, ty),
                     blocked_edges=mapmodel.blocked_edges(mp), footprint=side)
    if path is None:
        await send_to(ws, "error", {"msg": "No path there"})
        return
    if not footprint.valid_final_position(mp, tok, (tx, ty), tokens):
        await send_to(ws, "error", {"msg": "That token footprint cannot finish there"})
        return

    await _cancel_walk(tok["id"])
    _walks[tok["id"]] = asyncio.create_task(walk(room_id, tok["id"], path))
    await _announce_move(room_id, tok["id"], True)


async def walk(room_id, token_id, path):
    cell = get_map(room_id)["cell"]
    stop_reason = None
    try:
        for i, (cx, cy) in enumerate(path):
            tok = db.q1("SELECT * FROM tokens WHERE id=?", (token_id,))
            if tok is None or tok["room_id"] != room_id:
                return
            x, y = (cx + .5) * cell, (cy + .5) * cell
            db.x("UPDATE tokens SET x=?, y=? WHERE id=?", (x, y, token_id))
            tok["x"], tok["y"] = x, y
            await broadcast_token_step(room_id, tok, x, y, cx, cy)
            reveals = tok["owner_user_id"] is not None
            async with map_lock(room_id):
                mp = get_map(room_id)
                visible, _ = _reveal_player_token(mp, tok)
                newly = mapmodel.reveal_cells(mp, visible) if reveals else []
                map_dirty = False
                trap = at_cell(mp["traps"], cx, cy)
                if trap and not trap.get("discovered"):
                    stop_reason = "trap" if await hit_trap(room_id, tok, trap) else stop_reason
                    map_dirty = True
                loot = at_cell(mp["loot"], cx, cy)
                if loot and loot.get("taken_by") is None:
                    if await take_loot(room_id, tok, loot):
                        map_dirty = True
                if newly or map_dirty:
                    set_map(room_id, mp)
            if newly:
                await broadcast(room_id, "explored", fog_patch(mp, newly))
            if map_dirty:
                await broadcast(room_id, "map_changed", None)
            if stop_reason:
                break
            if i < len(path) - 1:
                await asyncio.sleep(STEP_DELAY)
        await _announce_move(room_id, token_id, False, stop_reason)
    finally:
        if _walks.get(token_id) is asyncio.current_task():
            _walks.pop(token_id, None)


async def handle_stop_move(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    try:
        tid = int(msg.get("token_id", -1))
    except (TypeError, ValueError):
        return
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (tid, room_id))
    if tok is None:
        return
    await _cancel_walk(tid)
    mp = get_map(room_id)
    origin, side = footprint.occupied_origin(mp, tok)
    tok = db.q1("SELECT * FROM tokens WHERE id=?", (tid,)) or tok
    await broadcast_token_step(room_id, tok, tok["x"], tok["y"], origin[0], origin[1])
    await _announce_move(room_id, tid, False, "manual")


def _preview_allowed_cells(mp, room_id, user, is_dm):
    if is_dm:
        return None
    allowed = {(i % mp["w"], i // mp["w"]) for i, explored in enumerate(mp["explored"]) if explored}
    allowed.update((i % mp["w"], i // mp["w"]) for i in
                   viewer_visible_cells(room_id, user["id"], mp))
    return allowed


async def handle_path_preview(ws, room_id, user, is_dm, msg):
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None:
        await send_to(ws, "error", {"msg": "Unknown token"})
        return
    if not (is_dm or tok["owner_user_id"] == user["id"]):
        await send_to(ws, "error", {"msg": "You can only preview your own token"})
        return
    try:
        tx, ty = int(msg["tx"]), int(msg["ty"])
    except (KeyError, ValueError, TypeError):
        await send_to(ws, "error", {"msg": "Invalid path preview"})
        return
    mp = get_map(room_id)
    origin, side = footprint.occupied_origin(mp, tok)
    tx, ty = max(0, min(mp["w"] - side, tx)), max(0, min(mp["h"] - side, ty))
    allowed = _preview_allowed_cells(mp, room_id, user, is_dm)
    if not footprint.valid_final_position(mp, tok, (tx, ty), _room_tokens(room_id, tok["id"]), allowed):
        await send_to(ws, "error", {"msg": "No path there"})
        return
    path = find_path(mp["w"], mp["h"], mp["cells"], origin, (tx, ty),
                     blocked_edges=mapmodel.blocked_edges(mp), footprint=side,
                     allowed_cells=allowed)
    if path is None:
        await send_to(ws, "error", {"msg": "No path there"})
        return
    request_id = msg.get("request_id")
    try:
        request_id = int(request_id) if request_id is not None else None
    except (TypeError, ValueError):
        request_id = None
    await send_to(ws, "path_preview", {
        "request_id": request_id,
        "token_id": tok["id"],
        "size": tok["size"] or "Medium",
        "goal": {"cx": tx, "cy": ty},
        "path": [{"x": x, "y": y} for (x, y) in path],
        "cells": footprint.path_preview_cells(mp["w"], mp["h"], side, [origin] + path),
        "cost": path_footprint_cost(mp["w"], mp["h"], mp["cells"], origin, path, side),
    })
