"""D104 — DM light management over the ONE existing light model (D89 lamps).

A lamp is a world OBJECT (interact op kind "lamp", ``bright`` in cells,
``state.on``) living in its PLANE's map — created by the editor's 🕹️ tool and
toggled in play by anyone who can reach it. What always lacked was the DM
management surface: move a lamp, retune its radius, rename it, flip it without
roleplaying an interaction, delete it from a list instead of hunting its cell.

This handler is that surface and nothing more: it mutates the SAME objects
list the editor saves, honours the same canon (bright clamped 0..30, world
window clamp, 16-char ids), saves with the plane it lives on (D102 rule: a
save carries the floor of the map it holds), ends with the SAME
reevaluate_visibility the lamp interact and the map edit already run, and is
DM-only exactly like map_edit. Silent administration: players experience the
WORLD result through map_changed — no fake action in their chronicle.
"""
from uuid import uuid4

from .. import floors as FLOOR, mapmodel
from .net import broadcast, get_map, map_lock, send_to, set_map


def _canon_bright(v):
    try:
        b = int(v)
    except (TypeError, ValueError):
        return None
    return max(0, min(30, b))            # same cap as the object canon (D89)


def _lamp(obj):
    op = ((obj or {}).get("interact") or {}).get("op") or {}
    return op.get("kind") == "lamp"


async def handle_lamp(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return await send_to(ws, "error", {"msg": "DM only"})
    action = str(msg.get("action") or "")
    if action not in ("add", "update", "remove"):
        return await send_to(ws, "error", {"msg": "Unknown lamp action"})
    fl = str(msg.get("floor") or "")
    if not FLOOR.exists(room_id, fl):
        return await send_to(ws, "error", {"msg": "No such floor"})
    bright = _canon_bright(msg["bright"]) if "bright" in msg else None
    on = None if "on" not in msg else bool(msg.get("on"))
    label = str(msg.get("label") or "")
    try:
        x, y = int(msg["x"]), int(msg["y"])
    except (KeyError, TypeError, ValueError):
        x = y = None
    lid = str(msg.get("id") or "")[:16]
    async with map_lock(room_id):                       # NOT reentrant
        mp = get_map(room_id, fl)
        objs = mp.setdefault("objects", [])
        ox, oy = mapmodel.origin_of(mp)
        if action == "add":
            if x is None:
                return await send_to(ws, "error", {"msg": "Lamp needs a position"})
            b = 5 if bright is None else bright          # same default as the canon
            oid = uuid4().hex[:12]
            while any(o.get("id") == oid for o in objs):
                oid = uuid4().hex[:12]
            obj = {"id": oid,
                   "x": max(ox, min(ox + mp["w"] - 1, x)),
                   "y": max(oy, min(oy + mp["h"] - 1, y)),
                   "label": mapmodel._label(label, "Lamp"),
                   "dm_only": False, "state": {"on": True},
                   "interact": {"label": "Tend the Light",
                                "op": {"kind": "lamp", "bright": b}}}
            objs.append(obj)
        else:
            obj = next((o for o in objs if o.get("id") == lid and _lamp(o)), None)
            if obj is None:
                # an id that is not a lamp of THIS plane answers like nothing
                # being here — the panel must not delete chests/levers through
                # a light-management channel
                return await send_to(ws, "error", {"msg": "No such lamp"})
            if action == "remove":
                objs.remove(obj)
            else:
                if bright is not None:
                    obj["interact"]["op"]["bright"] = bright
                if label:
                    obj["label"] = mapmodel._label(label, obj.get("label", "Lamp"))
                if on is not None:
                    obj["state"] = {"on": on}
                if x is not None:
                    obj["x"] = max(ox, min(ox + mp["w"] - 1, x))
                    obj["y"] = max(oy, min(oy + mp["h"] - 1, y))
        set_map(room_id, mp, fl)                         # plane-correct save (D102)
    await broadcast(room_id, "map_changed", None)
    # the world's LIGHT changed — every viewer's token decision must be re-run
    # NOW, not on the next move (the lamp interact and map edit do the same)
    from .visibility import reevaluate_visibility
    await reevaluate_visibility(room_id)
    await send_to(ws, "lamp_ok", {"action": action,
                                  "id": obj.get("id"), "floor": fl})
