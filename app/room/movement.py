"""Grid movement: DM teleport and animated A* walks, with fog reveal + trap/loot checks.

Map read-modify-write (reveal, trap/loot flag flip, persist) is serialised per room
by net.map_lock so concurrent walks of different tokens can't clobber each other."""
import asyncio

from .. import db, mapmodel
from ..path import find_path
from .net import broadcast, fog_patch, get_map, map_lock, send_to, set_map
from .traps import at_cell, hit_trap, take_loot
from .visibility import broadcast_token_step

STEP_DELAY = 0.11
# token_id -> walk asyncio.Task
_walks: dict[int, asyncio.Task] = {}


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
    tx, ty = max(0, min(mp["w"] - 1, tx)), max(0, min(mp["h"] - 1, ty))
    sx = max(0, min(mp["w"] - 1, int(tok["x"] // cell)))
    sy = max(0, min(mp["h"] - 1, int(tok["y"] // cell)))
    if msg.get("teleport") and is_dm:
        if (sx, sy) == (tx, ty):
            return
        x, y = (tx + .5) * cell, (ty + .5) * cell
        db.x("UPDATE tokens SET x=?, y=? WHERE id=?", (x, y, tok["id"]))
        tok["x"], tok["y"] = x, y
        await broadcast_token_step(room_id, tok, x, y, tx, ty)
        async with map_lock(room_id):
            mp = get_map(room_id)
            newly = mapmodel.reveal(mp, tx, ty)
            if newly:
                set_map(room_id, mp)
        if newly:
            await broadcast(room_id, "explored", fog_patch(mp, newly))
        return
    if (sx, sy) == (tx, ty):
        return
    old = _walks.get(tok["id"])
    if old:
        old.cancel()
    path = find_path(mp["w"], mp["h"], mp["cells"], (sx, sy), (tx, ty))
    if path is None:
        await send_to(ws, "error", {"msg": "No path there"})
        return
    _walks[tok["id"]] = asyncio.create_task(walk(room_id, tok["id"], path))


async def walk(room_id, token_id, path):
    cell = get_map(room_id)["cell"]
    try:
        for i, (cx, cy) in enumerate(path):
            tok = db.q1("SELECT * FROM tokens WHERE id=?", (token_id,))
            if tok is None or tok["room_id"] != room_id:
                return
            x, y = (cx + .5) * cell, (cy + .5) * cell
            db.x("UPDATE tokens SET x=?, y=? WHERE id=?", (x, y, token_id))
            tok["x"], tok["y"] = x, y
            await broadcast_token_step(room_id, tok, x, y, cx, cy)
            async with map_lock(room_id):
                mp = get_map(room_id)
                newly = mapmodel.reveal(mp, cx, cy)
                map_dirty = False
                trap = at_cell(mp["traps"], cx, cy)
                if trap and not trap.get("discovered"):
                    await hit_trap(room_id, tok, trap)
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
            if i < len(path) - 1:
                await asyncio.sleep(STEP_DELAY)
    except asyncio.CancelledError:
        pass
    finally:
        _walks.pop(token_id, None)
