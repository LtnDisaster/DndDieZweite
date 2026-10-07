"""Generic world-object interaction (D82).

Objects live in the room map (``mp["objects"]``) and are authored in the map
editor like traps/loot. An INTERACT definition is DATA driving exactly one
allowlisted server operation:

* ``toggle`` — flip the object's generic boolean ``state.on``;
* ``door``   — open/close an EXISTING door through the shared door lifecycle
  (``doors.door_toggled``): same reveal, chronicle and event semantics as a
  direct door click. No door redesign, no new door rules.

Anything else is refused. There is deliberately no eval, no script field and
no expression language — DM automation may later call these same operations,
never generated code. Authorization follows the door precedent: an adjacent
(or overlapping) token the user controls is required; the DM acts freely.
"""
from .. import db, events, footprint, mapmodel
from . import authz, doors
from .net import broadcast, get_map, map_lock, send_to, set_map, sys_msg


def _reach_cells(room_id, user_id, mp):
    """WORLD cells under any token this user owns OR controls (D82: the
    controller relationship is operational authority — authz SSOT)."""
    cells = set()
    for tok in authz.controlled_rows(room_id, user_id):
        cells |= footprint.occupied_cells(mp, tok)
    return cells


def _linked_door(mp, op):
    x, y = op.get("x"), op.get("y")
    dir_ = str(op.get("dir", ""))
    try:
        bx, by = mapmodel.neighbor(int(x), int(y), dir_)
    except (ValueError, TypeError):
        return None
    return mapmodel.find_door(mp, int(x), int(y), bx, by)


async def handle_interact(ws, room_id, user, is_dm, msg):
    oid = str(msg.get("object_id", ""))[:16]
    if not oid:
        return
    kind = None
    flipped_door = None
    async with map_lock(room_id):                              # NOT reentrant!
        mp = get_map(room_id)
        obj = next((o for o in mp.get("objects", []) if o.get("id") == oid), None)
        if obj is None:
            return                                    # unknown id: silent no-op
        it = obj.get("interact")
        if not is_dm:
            if obj.get("dm_only"):
                # dm_only answers BEFORE state details, door precedent (D63)
                await send_to(ws, "error", {"msg": "It won't budge."})
                return
            if not it:
                await send_to(ws, "error", {"msg": "There is nothing to do here."})
                return
            x0, y0 = obj["x"], obj["y"]
            near = {(x0 + dx, y0 + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
            if not _reach_cells(room_id, user["id"], mp) & near:
                await send_to(ws, "error", {"msg": "Walk up to it first"})
                return
        if not it:
            await send_to(ws, "error", {"msg": "There is nothing to do here."})
            return
        op = it.get("op") or {}
        kind = op.get("kind")
        if kind == "toggle":
            st = dict(obj.get("state") or {})
            st["on"] = not st.get("on")
            obj["state"] = st
            set_map(room_id, mp)
        elif kind == "door":
            door = _linked_door(mp, op)
            if door is None:
                await send_to(ws, "error", {"msg": "Nothing happens."})   # dangling link
                return
            if door.get("secret") and not is_dm:
                # never confirm that a secret door exists behind this mechanism
                await send_to(ws, "error", {"msg": "Nothing happens."})
                return
            if door.get("dm_only") and not is_dm:
                await send_to(ws, "error", {"msg": "It won't budge."})
                return
            if door["locked"] and not is_dm:
                await send_to(ws, "error", {"msg": "It won't budge."})    # locked is locked
                return
            door["closed"] = not door["closed"]
            set_map(room_id, mp)
            flipped_door = door            # lifecycle runs BELOW, lock released
        else:
            # unknown op on an old/hand-crafted map: refuse, execute nothing
            await send_to(ws, "error", {"msg": "Nothing happens."})
            return
    if flipped_door is not None:
        await doors.door_toggled(room_id, user["id"], flipped_door)
        return
    await broadcast(room_id, "object_state", {"object_id": obj["id"], "state": obj["state"]})
    sys_msg(room_id, f"🕹 {user['username']} uses the {obj['label']}.")
    events.emit(events.make("object_interacted", room_id=room_id, actor_id=user["id"],
                            object_id=obj["id"], label=obj["label"],
                            on=bool((obj.get("state") or {}).get("on"))))
