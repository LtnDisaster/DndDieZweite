"""DM encounter spawning from saved bestiary templates."""
import hashlib

from .. import db, footprint, npc
from .net import broadcast, get_map, sys_msg
from .visibility import broadcast_token_add

PALETTE = ["#c0392b", "#2980b9", "#27ae60", "#8e44ad", "#d35400", "#16a085", "#b71540"]


def _color(name):
    return PALETTE[int(hashlib.md5(name.encode()).hexdigest(), 16) % len(PALETTE)]


def _spawn_origin(mp, room_id, token, x, y):
    existing = db.q("SELECT id, x, y, owner_user_id, size FROM tokens WHERE room_id=?", (room_id,))
    desired = footprint.origin_from_pixel(x, y, mp["cell"], mp["w"], mp["h"])
    origin = footprint.find_valid_origin(mp, token, desired, existing)
    return footprint.origin_pixels(origin, footprint.side_for_size(token.get("size")), mp["cell"]) if origin else None


async def handle_spawn_encounter(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    eid = msg.get("encounter_id")
    enc = db.q1("SELECT * FROM encounters WHERE id=? AND user_id=?", (eid, user["id"]))
    if enc is None:
        return
    entries = db.j(enc.get("entries"), [])
    mp = get_map(room_id)
    cx = max(0, min(mp["w"] - 1, int(mp["w"] // 2)))
    cy = max(0, min(mp["h"] - 1, int(mp["h"] // 2)))
    n = 0
    for e in entries:
        cr = db.q1("SELECT * FROM creatures WHERE id=? AND user_id=?",
                   (e.get("creature_id"), user["id"]))
        if cr is None:
            continue
        block = npc.clean_npc(db.j(cr.get("block"), {}) or {})
        try:
            qty = max(1, min(50, int(e.get("quantity", 1))))
        except (TypeError, ValueError):
            qty = 1
        base = str(e.get("name") or cr["name"])[:32]
        for i in range(qty):
            label = base if qty == 1 else f"{base} {i + 1}"
            x = ((cx + (n % 4)) + .5) * mp["cell"]
            y = ((cy + (n // 4)) + .5) * mp["cell"]
            size = npc.clean_size(block.get("size"))
            placed = _spawn_origin(mp, room_id, {"id": 0, "room_id": room_id, "size": size,
                                                 "owner_user_id": None}, x, y)
            if placed is None:
                continue
            x, y = placed
            tid = db.x("INSERT INTO tokens (room_id,label,color,x,y,npc,size,disposition) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (room_id, label, _color(base), x, y, db.json_dumps(block),
                        size, npc.clean_disposition(block.get("disposition"))))
            tok = db.q1("SELECT * FROM tokens WHERE id=?", (tid,))
            await broadcast_token_add(room_id, tok)
            n += 1
            if n >= 100:
                break
        if n >= 100:
            break
    if n:
        sys_msg(room_id, f"📜 Encountered {n} creature(s).")
