"""DM-only exploration state edits.

``explored`` is persistent memory. It is deliberately separate from the server's
current LOS calculation: hiding a cell does not blind a player who can see it now.
"""
from .. import db, mapmodel
from .net import broadcast, get_map, map_lock, send_to, set_map


async def handle_fog_edit(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    raw = msg.get("cells")
    if not isinstance(raw, list):
        await send_to(ws, "error", {"msg": "Invalid fog edit"})
        return
    updates = []
    for item in raw[:512]:
        if not isinstance(item, dict):
            continue
        try:
            x, y = int(item["x"]), int(item["y"])
            explored = 1 if bool(item.get("explored", 1)) else 0
        except (KeyError, TypeError, ValueError):
            continue
        updates.append((x, y, explored))
    if not updates:
        return

    async with map_lock(room_id):
        mp = get_map(room_id)
        changed = {}
        terrain = {}
        for x, y, explored in updates:
            if not (0 <= x < mp["w"] and 0 <= y < mp["h"]):
                continue
            idx = y * mp["w"] + x
            if mp["explored"][idx] != explored:
                mp["explored"][idx] = explored
                changed[str(idx)] = explored
                terrain[str(idx)] = mp["cells"][idx] if explored else None
        if not changed:
            return
        set_map(room_id, mp)
    await broadcast(room_id, "fog_changed", {"cells": changed, "terrain": terrain})


async def handle_fog_toggle(ws, room_id, user, is_dm, msg):
    """Room-wide fog-off flag: terrain+static entities visible to everyone.

    Stored inside the persisted map (survives reloads and map edits; the
    editor merge in dispatch keeps it off stale snapshots). NPC live
    visibility is untouched — the LOS pipeline still hides hidden foes.
    """
    if not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    on = bool(msg.get("on"))
    async with map_lock(room_id):
        mp = get_map(room_id)
        if bool(mp.get("fog_off")) == on:
            return
        mp["fog_off"] = on
        set_map(room_id, mp)
    await broadcast(room_id, "map_changed", None)
