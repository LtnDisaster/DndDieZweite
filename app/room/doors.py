"""Door interaction (open / close / lock) over WebSockets.

Doors live in the room map (``mp["doors"]``) and are authored in the map editor; this
handler is the live interaction on top of them. The DM may open, close, lock, unlock or
remove any door. A player may only **toggle an unlocked door they are standing next to**
(their token is in one of the two cells the door separates) — locking is DM-only. A
closed (or locked) door blocks movement, which the pathfinder enforces server-side.
"""
from .. import db, events, footprint, los, mapmodel
from . import authz
from .net import (broadcast, fog_patch, get_map, map_lock, send_to,
                  send_to_plane, set_map, sys_msg)


def _door_of(msg, mp):
    canon = mapmodel._canon_door(int(msg["x"]), int(msg["y"]), str(msg.get("dir", "")).lower(),
                                 mp["w"], mp["h"])
    if canon is None:
        return None
    x, y, dir_ = canon
    bx, by = mapmodel.neighbor(x, y, dir_)
    return mapmodel.find_door(mp, x, y, bx, by)


def _player_cells(room_id, user_id, mp, floor=""):
    """Cells occupied by ANY token this user owns OR controls (D82: a
    companion counts for door reach — operational authority, authz SSOT).
    D88: reach is SAME-PLANE — a token on another floor reaches nothing here."""
    cells = set()
    c = mp["cell"]
    for tok in authz.controlled_rows(room_id, user_id):
        if (tok.get("floor") or "") != floor:
            continue
        cx = max(0, min(mp["w"] - 1, int(tok["x"] // c)))
        cy = max(0, min(mp["h"] - 1, int(tok["y"] // c)))
        cells.add((cx, cy))
    return cells


async def handle_door(ws, room_id, user, is_dm, msg):
    try:
        x, y = int(msg["x"]), int(msg["y"])
    except (KeyError, ValueError, TypeError):
        return
    # D88: a door belongs to a plane. Players act on it only from a token on
    # the SAME plane (their view-floor claim is validated against their own
    # tokens, never trusted); the DM acts on any plane.
    fl = str(msg.get("floor") or "")
    if not is_dm:
        planes = {(t.get("floor") or "") for t in authz.controlled_rows(room_id, user["id"])}
        if fl not in planes:
            return                          # like a door that is not there
    async with map_lock(room_id):
        mp = get_map(room_id, fl)
        door = _door_of({"x": x, "y": y, "dir": msg.get("dir")}, mp)
        if door is None:
            return
        bx, by = mapmodel.neighbor(door["x"], door["y"], door["dir"])
        action = msg.get("action", "toggle")
        if is_dm:
            if action == "remove":
                mp["doors"] = [d for d in mp["doors"] if d is not door]
                set_map(room_id, mp, fl)
                events.emit(events.make("door_removed", room_id=room_id, actor_id=user["id"],
                                        x=door["x"], y=door["y"], dir=door["dir"]))
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
            if door.get("secret"):
                # A player must not even learn that a secret door exists here:
                # respond exactly like "no door at this edge" (silent return).
                return
            if door.get("dm_only"):
                # Checked BEFORE the lock branch so a dm_only+locked door cannot
                # leak its lock state through the message either.
                await send_to(ws, "error", {"msg": "It won't budge."})
                return
            if door["locked"]:
                await send_to(ws, "error", {"msg": "The door is locked"})
                return
            cells = _player_cells(room_id, user["id"], mp, fl)
            if not cells & {(door["x"], door["y"]), (bx, by)}:
                await send_to(ws, "error", {"msg": "Walk up to the door first"})
                return
            door["closed"] = not door["closed"]
        set_map(room_id, mp, fl)
    await door_toggled(room_id, user["id"], door, fl)


async def door_toggled(room_id, actor_id, door, floor=""):
    """Shared post-flip lifecycle for an ALREADY-FLIPPED, PERSISTED door: LOS
    reveal on open, chronicle line, event fact, map_changed broadcast.
    Used by handle_door and by world-object levers (D82) — one door lifecycle,
    no second implementation. map_lock must NOT be held by the caller here."""
    opened = not door["closed"]
    newly = []
    if opened:
        async with map_lock(room_id):
            mp = get_map(room_id, floor)
            for tok in db.q("SELECT id, x, y, owner_user_id, size, fw, fh, rot, mount_token_id FROM tokens "
                            "WHERE room_id=? AND owner_user_id IS NOT NULL AND floor=?",
                            (room_id, str(floor))):
                visible = los.visible_cells(mp, footprint.player_source_cells(mp, [tok]))
                newly += mapmodel.reveal_cells(mp, visible)
            if newly:
                set_map(room_id, mp, floor)
    state = "closes" if door["closed"] else "swings open"
    verb = "locks" if door["locked"] and door["closed"] else state
    if not (door.get("dm_only") or door.get("secret")):
        # dm-only/secret door moves must not leak into the shared chronicle.
        sys_msg(room_id, f"🚪 The door {verb}.")
    # Fact emitted AFTER the committed change (D52): the door state lives in the map.
    events.emit(events.make("door_opened" if opened else "door_closed", room_id=room_id,
                            actor_id=actor_id, x=door["x"], y=door["y"], dir=door["dir"],
                            locked=bool(door["locked"])))
    if newly:
        await send_to_plane(room_id, floor, "explored", fog_patch(mp, newly))
    await broadcast(room_id, "map_changed", None)
