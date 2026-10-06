"""DM token management (add / remove NPC tokens + edit NPC stat blocks)."""
import re

from .. import db, footprint, mapmodel, npc
from . import movement
from .net import broadcast, get_map, send_to, sys_msg
from .visibility import broadcast_token_add, forget_token

WALL = "#95a5a6"


def _clean_size(value, default="Medium"):
    return npc.clean_size(value or default)


def _clean_disposition(value):
    return npc.clean_disposition(value)


def _clean_color(color):
    color = str(color if color is not None else WALL)
    return color if re.match(r"^#[0-9a-fA-F]{6}$", color) else WALL


def _clean_pos(msg):
    try:
        x, y = float(msg.get("x", 500)), float(msg.get("y", 300))
    except (TypeError, ValueError):
        x, y = 500.0, 300.0
    return x, y


def _place_token(mp, token, x, y):
    side = footprint.side_for_size(token.get("size"))
    desired = footprint.origin_from_pixel(x, y, mp["cell"], mp)
    existing = db.q("SELECT id, x, y, owner_user_id, size FROM tokens WHERE room_id=?",
                    (token.get("room_id"),))
    origin = footprint.find_valid_origin(mp, token, desired, existing)
    if origin is None:
        return None
    return footprint.origin_pixels(origin, side, mp["cell"])


async def handle_add_token(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    label = str(msg.get("label", "NPC"))[:32]
    color = _clean_color(msg.get("color"))
    x, y = _clean_pos(msg)
    base = msg.get("npc") if isinstance(msg.get("npc"), dict) else msg
    block = npc.clean_npc({
        "name": label,
        "level": base.get("level"), "stats": base.get("stats"),
        "hp": base.get("hp"), "max_hp": base.get("max_hp"), "ac": base.get("ac"),
        "speed": base.get("speed"), "spells": base.get("spells"),
        "attacks": base.get("attacks"), "spell_slots": base.get("spell_slots"),
        "saves": base.get("saves"), "defenses": base.get("defenses"),
        "abilities": base.get("abilities"), "resources": base.get("resources"),
        "notes": base.get("notes"),
    })
    size = _clean_size(msg.get("size") or base.get("size"))
    disposition = _clean_disposition(msg.get("disposition") or base.get("disposition"))
    mp = get_map(room_id)
    placed = _place_token(mp, {"room_id": room_id, "id": 0, "size": size}, x, y)
    if placed is None:
        await send_to(ws, "error", {"msg": "No valid placement for that footprint"})
        return
    x, y = placed
    tid = db.x("INSERT INTO tokens (room_id,label,color,x,y,npc,size,disposition) VALUES (?,?,?,?,?,?,?,?)",
               (room_id, label, color, x, y, db.json_dumps(block), size, disposition))
    tok = db.q1("SELECT * FROM tokens WHERE id=?", (tid,))
    sys_msg(room_id, f"DM added token '{label}'.")
    await broadcast_token_add(room_id, tok)


async def handle_update_npc(ws, room_id, user, is_dm, msg):
    """DM edits an NPC token's stat block (abilities, HP/AC, spells, slots)."""
    if not is_dm:
        return
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None or tok["owner_user_id"] is not None or tok["character_id"] is not None:
        return  # only DM-owned monster tokens (no owner, no attached PC) carry a block
    merged = npc.load(tok) or {}
    base = msg.get("npc") if isinstance(msg.get("npc"), dict) else msg
    merged.update({k: base[k] for k in
                   ("level", "stats", "hp", "max_hp", "ac", "speed", "fly", "swim", "climb",
                    "attacks", "spells",
                    "spell_slots", "saves", "defenses",
                    "abilities", "resources", "notes") if k in base})
    label = str(msg.get("label", tok["label"]))[:32]
    merged["name"] = label
    block = npc.clean_npc(merged)
    color = _clean_color(msg.get("color", tok["color"]))
    size = _clean_size(base.get("size", tok.get("size", "Medium")))
    disposition = _clean_disposition(msg.get("disposition", tok.get("disposition", "")))
    candidate = {**tok, "size": size}
    mp = get_map(room_id)
    existing = db.q("SELECT id, x, y, owner_user_id, size FROM tokens WHERE room_id=?", (room_id,))
    desired = footprint.origin_from_pixel(tok["x"], tok["y"], mp["cell"], mp)
    origin = footprint.find_valid_origin(mp, candidate, desired, existing)
    if origin is None:
        await send_to(ws, "error", {"msg": "No room to resize this token footprint"})
        return
    x, y = footprint.origin_pixels(origin, footprint.side_for_size(size), mp["cell"])
    db.x("UPDATE tokens SET npc=?, label=?, color=?, size=?, disposition=?, x=?, y=? WHERE id=?",
         (db.json_dumps(block), label, color, size, disposition, x, y, tok["id"]))
    await broadcast(room_id, "snapshot", None)


async def handle_del_token(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None:
        return                      # already deleted — idempotent, no error, no ghost
    if tok["owner_user_id"] is not None:
        db.x("UPDATE room_members SET character_id=NULL WHERE user_id=? AND room_id=?",
             (tok["owner_user_id"], room_id))
    db.x("DELETE FROM tokens WHERE id=?", (tok["id"],))
    sys_msg(room_id, f"DM removed token '{tok['label']}'.")
    await movement._cancel_walk(tok["id"])
    # Gone is a TRANSIENT sync event, not a stored state: forget_token clears the
    # server-side last-seen memory and broadcasts token_gone; the row itself is
    # gone, so no reload/snapshot can ever resurrect it (D73).
    await forget_token(room_id, tok["id"])
    await broadcast(room_id, "snapshot", None)
