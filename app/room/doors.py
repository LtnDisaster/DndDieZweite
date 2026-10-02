"""Door interaction (open / close / lock) over WebSockets.

Doors live in the room map (``mp["doors"]``) and are authored in the map editor; this
handler is the live interaction on top of them. The DM may open, close, lock, unlock or
remove any door. A player may only **toggle an unlocked door they are standing next to**
(their token is in one of the two cells the door separates) — locking is DM-only. A
closed (or locked) door blocks movement, which the pathfinder enforces server-side.
"""
from .. import db, footprint, los, mapmodel
from .net import broadcast, fog_patch, get_map, map_lock, send_to, set_map, sys_msg


def _door_of(msg, mp):
    canon = mapmodel._canon_door(int(msg["x"]), int(msg["y"]), str(msg.get("dir", "")).lower(),
                                 mp["w"], mp["h"])
    if canon is None:
        return None
    x, y, dir_ = canon
    bx, by = mapmodel.neighbor(x, y, dir_)
    return mapmodel.find_door(mp, x, y, bx, by)


def _player_cell(room_id, user_id, mp):
    tok = db.q1("SELECT x, y FROM tokens WHERE room_id=? AND owner_user_id=?", (room_id, user_id))
    if tok is None:
        return None
    c = mp["cell"]
    return max(0, min(mp["w"] - 1, int(tok["x"] // c))), max(0, min(mp["h"] - 1, int(tok["y"] // c)))


async def handle_door(ws, room_id, user, is_dm, msg):
    try:
        x, y = int(msg["x"]), int(msg["y"])
    except (KeyError, ValueError, TypeError):
        return
    async with map_lock(room_id):
        mp = get_map(room_id)
        door = _door_of({"x": x, "y": y, "dir": msg.get("dir")}, mp)
        if door is None:
            return
        bx, by = mapmodel.neighbor(door["x"], door["y"], door["dir"])
        action = msg.get("action", "toggle")
        if is_dm:
            if action == "remove":
                mp["doors"] = [d for d in mp["doors"] if d is not door]
                set_map(room_id, mp)
                await broadcast(room_id, "map_changed", None)
                return
            if action == "set":
                if "open" in msg:
                    door["closed"] = not bool(msg.get("open"))
                    if msg.get("open"):
                        door["locked"] = False
                if msg.get("locked") is not None:
                    door["locked"] = bool(msg.get("locked"))
                    if door["locked"]:
                        door["closed"] = True
            else:
                door["closed"] = not door["closed"]
        else:
            if door["locked"]:
                await send_to(ws, "error", {"msg": "The door is locked"})
                return
            cell = _player_cell(room_id, user["id"], mp)
            if cell not in ((door["x"], door["y"]), (bx, by)):
                await send_to(ws, "error", {"msg": "Walk up to the door first"})
                return
            door["closed"] = not door["closed"]
        set_map(room_id, mp)
    opened = not door["closed"]
    newly = []
    if opened:
        async with map_lock(room_id):
            mp = get_map(room_id)
            for tok in db.q("SELECT id, x, y, owner_user_id, size FROM tokens "
                            "WHERE room_id=? AND owner_user_id IS NOT NULL", (room_id,)):
                visible = los.visible_cells(mp, footprint.player_source_cells(mp, [tok]))
                newly += mapmodel.reveal_cells(mp, visible)
            if newly:
                set_map(room_id, mp)
    state = "closes" if door["closed"] else "swings open"
    verb = "locks" if door["locked"] and door["closed"] else state
    sys_msg(room_id, f"🚪 The door {verb}.")
    if newly:
        await broadcast(room_id, "explored", fog_patch(mp, newly))
    await broadcast(room_id, "map_changed", None)
