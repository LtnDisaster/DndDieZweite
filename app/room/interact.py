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
from .. import db, events, floors as FLOOR, footprint, mapmodel
from . import authz, doors
from .moveforced import apply_forced_move
from .net import (broadcast, get_map, map_lock, send_to, send_to_plane,
                  set_map, sys_msg)
from .visibility import send_property_to_interested


def _reach_cells(room_id, user_id, mp, floor=""):
    """WORLD cells under any token this user owns OR controls (D82: the
    controller relationship is operational authority — authz SSOT).
    D88: reach is SAME-PLANE."""
    cells = set()
    for tok in authz.controlled_rows(room_id, user_id):
        if (tok.get("floor") or "") != floor:
            continue
        cells |= footprint.occupied_cells(mp, tok)
    return cells


# (plane_viewers lives in net.py — fog, doors and object state share it)


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
    # D88: objects live on a plane. A player may only act on planes they
    # stand on — a wrong-plane claim answers like nothing being there.
    fl = str(msg.get("floor") or "")
    if not FLOOR.exists(room_id, fl):
        return
    kind = None
    flipped_door = None
    stair = None
    lamp = None
    async with map_lock(room_id):                              # NOT reentrant!
        mp = get_map(room_id, fl)
        obj = next((o for o in mp.get("objects", []) if o.get("id") == oid), None)
        if obj is None:
            return                                    # unknown id: silent no-op
        it = obj.get("interact")
        near = set()
        if not is_dm:
            planes = {(t.get("floor") or "") for t in authz.controlled_rows(room_id, user["id"])}
            if fl not in planes:
                return                                  # elsewhere: nothing is here
            if obj.get("dm_only"):
                # dm_only answers BEFORE state details, door precedent (D63)
                await send_to(ws, "error", {"msg": "It won't budge."})
                return
            if not it:
                await send_to(ws, "error", {"msg": "There is nothing to do here."})
                return
            x0, y0 = obj["x"], obj["y"]
            near = {(x0 + dx, y0 + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
            if not _reach_cells(room_id, user["id"], mp, fl) & near:
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
            set_map(room_id, mp, fl)
            flipped_door = door            # lifecycle runs BELOW, lock released
        elif kind == "stair":
            # D88 CONNECTOR: validated plane transition through a world object.
            # The destination is validated by apply_forced_move on the TARGET
            # plane (terrain + occupants); "occupied or walled" refuses, so a
            # stair can never materialise anyone inside anything.
            to_fl = str(op.get("floor") or "")
            if not FLOOR.exists(room_id, to_fl):
                await send_to(ws, "error", {"msg": "Nothing happens."})   # dangling
                return
            try:
                dest = (int(op["x"]), int(op["y"]))
            except (KeyError, ValueError, TypeError):
                await send_to(ws, "error", {"msg": "Nothing happens."})
                return
            actor = None
            if is_dm:
                actor = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                              (msg.get("token_id", -1), room_id))
                if actor is None:
                    await send_to(ws, "error", {"msg": "Which token?"})
                    return
            else:
                cands = [t for t in authz.controlled_rows(room_id, user["id"])
                         if (t.get("floor") or "") == fl]
                own = [t for t in cands if t.get("owner_user_id") == user["id"]]
                pool = sorted(own or cands, key=lambda t: t["id"])
                pick = next((t for t in pool
                             if set(footprint.occupied_cells(mp, t)) & near), pool[0] if pool else None)
                if pick is None:
                    await send_to(ws, "error", {"msg": "Walk up to it first"})
                    return
                # full row: the mover needs label/size/footprint, not the authz slice
                actor = db.q1("SELECT * FROM tokens WHERE id=?", (pick["id"],))
            stair = (dict(actor), to_fl, dest)          # executes BELOW the lock
        elif kind == "lamp":
            # D89: flip a static light. Same boolean state carrier a toggle
            # uses — lamps additionally re-run the vision decision after the
            # lock, because "who sees what" just changed for the whole plane.
            obj["state"] = {"on": not bool((obj.get("state") or {}).get("on", True))}
            set_map(room_id, mp, fl)
            lamp = obj
        else:
            # unknown op on an old/hand-crafted map: refuse, execute nothing
            await send_to(ws, "error", {"msg": "Nothing happens."})
            return
    if flipped_door is not None:
        await doors.door_toggled(room_id, user["id"], flipped_door, fl)
        return
    if stair is not None:
        actor, to_fl, dest = stair
        stair_name = str(obj.get("label") or "stairs")
        ok = await apply_forced_move(
            room_id, actor, "teleport", dest, floor=to_fl,
            chronicle=f"🪜 {actor['label']} takes the {stair_name}"
                      f" to {to_fl or 'the ground floor'}.")
        if ok is None:
            await send_to(ws, "error", {"msg": "No room down there."})
            return
        moved = db.q1("SELECT * FROM tokens WHERE id=?", (actor["id"],))
        await send_property_to_interested(room_id, moved, "token_floor",
                                          {"token_id": moved["id"], "floor": to_fl})
        if moved["owner_user_id"] == user["id"] or moved.get("controller_user_id") == user["id"]:
            await send_to(ws, "grid_reveal", None)     # your view follows you
        return
    await send_to_plane(room_id, fl, "object_state",
                        {"object_id": obj["id"], "state": obj["state"]})
    if lamp is not None:
        lit = "lights" if (obj.get("state") or {}).get("on", True) else "goes dark"
        sys_msg(room_id, f"💡 The {obj['label']} {lit}.")
        from .visibility import reevaluate_visibility
        await reevaluate_visibility(room_id)
        return
    sys_msg(room_id, f"🕹 {user['username']} uses the {obj['label']}.")
    events.emit(events.make("object_interacted", room_id=room_id, actor_id=user["id"],
                            object_id=obj["id"], label=obj["label"],
                            on=bool((obj.get("state") or {}).get("on"))))
