"""DM token management (add / remove NPC tokens + edit NPC stat blocks)."""
import re

from .. import db, footprint, mapmodel, npc
from . import movement
from .net import broadcast, get_map, send_to, sys_msg
from .visibility import broadcast_token_add, forget_token

WALL = "#95a5a6"


def _clean_size(value, default="Medium"):
    return npc.clean_size(value or default)


def _clean_span(msg, size, tok=None):
    """Custom (fw, fh) from an editor message, clamped; None = square of size.
    A size-category CHANGE always clears a previous custom span (D81)."""
    if tok is not None and size != (tok.get("size") or "Medium"):
        return None, None
    has_w = "width" in msg or "fw" in msg
    has_h = "height" in msg or "fh" in msg
    if not (has_w or has_h):
        return (tok.get("fw") if tok else None), (tok.get("fh") if tok else None)
    w = footprint.clean_span(msg.get("width", msg.get("fw")))
    h = footprint.clean_span(msg.get("height", msg.get("fh")))
    if w is not None and h is None:
        h = w
    if h is not None and w is None:
        w = h
    return w, h


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
    side = footprint.token_span(token)
    desired = footprint.origin_from_pixel(x, y, mp["cell"], mp)
    existing = db.q("SELECT id, x, y, owner_user_id, size, fw, fh FROM tokens WHERE room_id=?",
                    (token.get("room_id"),))
    origin = footprint.find_valid_origin(mp, token, desired, existing)
    if origin is None:
        return None
    return footprint.origin_pixels(origin, side, mp["cell"])


def _room_token_rows(room_id):
    return db.q("SELECT id, x, y, owner_user_id, size, fw, fh FROM tokens WHERE room_id=?",
                (room_id,))


async def handle_token_span(ws, room_id, user, is_dm, msg):
    """Footprint resize operation (D81/15B): owner (or DM) sets width/height.
    The COMPLETE new rectangle must fit at the token's CURRENT anchor — an
    invalid resize is rejected with the old dimensions fully intact. The
    token is never moved to make a resize work."""
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                (msg.get("token_id", -1), room_id))
    if tok is None:
        return
    if not (is_dm or tok["owner_user_id"] == user["id"]):
        await send_to(ws, "error", {"msg": "Not your token"})
        return
    fw = footprint.clean_span(msg.get("width"))
    fh = footprint.clean_span(msg.get("height"))
    if fw is None or fh is None:
        await send_to(ws, "error", {"msg": "Width and height (1-10 cells) are required"})
        return
    if (tok.get("fw"), tok.get("fh")) == (fw, fh):
        return                                   # idempotent, no broadcast storm
    candidate = {**tok, "fw": fw, "fh": fh}
    mp = get_map(room_id)
    origin, _ = footprint.occupied_origin(mp, tok)   # current anchor, WORLD space
    if not footprint.valid_final_position(mp, candidate, origin,
                                          _room_token_rows(room_id)):
        await send_to(ws, "error",
                      {"msg": "That footprint does not fit here — move the token or "
                              "choose smaller dimensions"})
        return
    db.x("UPDATE tokens SET fw=?, fh=? WHERE id=?", (fw, fh, tok["id"]))
    await broadcast(room_id, "token_span", {"token_id": tok["id"], "fw": fw, "fh": fh})


async def handle_token_visual(ws, room_id, user, is_dm, msg):
    """Visual size operation (D82): owner (or DM) sets the RENDER bounds
    (vw/vh, grid cells). Visual bounds are presentation only — they never
    touch occupancy, collision or pathfinding, so no clearance check applies
    and a visual resize can never displace anything. The mechanical footprint
    (fw/fh) stays untouched by this path, and vice versa."""
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                (msg.get("token_id", -1), room_id))
    if tok is None:
        return
    if not (is_dm or tok["owner_user_id"] == user["id"]):
        await send_to(ws, "error", {"msg": "Not your token"})
        return
    vw = footprint.clean_span(msg.get("width"))
    vh = footprint.clean_span(msg.get("height"))
    if vw is None or vh is None:
        await send_to(ws, "error", {"msg": "Width and height (1-10 cells) are required"})
        return
    if (tok.get("vw"), tok.get("vh")) == (vw, vh):
        return                                   # idempotent, no broadcast storm
    db.x("UPDATE tokens SET vw=?, vh=? WHERE id=?", (vw, vh, tok["id"]))
    await broadcast(room_id, "token_visual", {"token_id": tok["id"], "vw": vw, "vh": vh})


async def handle_token_rotate(ws, room_id, user, is_dm, msg):
    """Facing operation (D82): owner (or DM) sets the VISUAL orientation to
    0/90/180/270 degrees. Presentation only: the mechanical footprint is
    explicitly NOT rotated — a 2x4 collision rect never silently becomes
    4x2 because the artwork turned. Mechanical rotation would be a future
    explicit mechanic, not a side effect of this path."""
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                (msg.get("token_id", -1), room_id))
    if tok is None:
        return
    if not (is_dm or tok["owner_user_id"] == user["id"]):
        await send_to(ws, "error", {"msg": "Not your token"})
        return
    rot = footprint.clean_rot(msg.get("degrees", msg.get("rot")))
    if rot is None:
        await send_to(ws, "error", {"msg": "Rotation must be 0, 90, 180 or 270 degrees"})
        return
    if (tok.get("rot") or 0) == rot:
        return                                   # idempotent, no broadcast storm
    db.x("UPDATE tokens SET rot=? WHERE id=?", (rot, tok["id"]))
    await broadcast(room_id, "token_rot", {"token_id": tok["id"], "rot": rot})


async def handle_token_controller(ws, room_id, user, is_dm, msg):
    """DM assigns or clears the generic CONTROLLER of a token (D82). The
    controller may act through the token (movement, its turn, conditions,
    casting, door/object reach) — a companion/familiar foundation, NOT class
    rules. The target must be a member of THIS room (no fake accounts, no
    strangers); the DM can revoke at any time and always outranks a
    controller. Ownership and character-sheet rights stay with the owner."""
    if not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                (msg.get("token_id", -1), room_id))
    if tok is None:
        return
    raw = msg.get("controller_id", msg.get("user_id"))
    cid = None
    if raw not in (None, "", 0):
        try:
            cid = int(raw)
        except (TypeError, ValueError):
            await send_to(ws, "error", {"msg": "Unknown user"})
            return
        if db.q1("SELECT user_id FROM room_members WHERE room_id=? AND user_id=?",
                 (room_id, cid)) is None:
            await send_to(ws, "error", {"msg": "That user is not a member of this room"})
            return
    if (tok.get("controller_user_id")) == cid:
        return                                   # idempotent, no broadcast storm
    db.x("UPDATE tokens SET controller_user_id=? WHERE id=?", (cid, tok["id"]))
    await broadcast(room_id, "token_controller",
                    {"token_id": tok["id"], "controller_user_id": cid})


async def handle_token_mount(ws, room_id, user, is_dm, msg):
    """DM assigns or clears the MOUNT of a token (D82). A rider rides at most
    one mount; the relationship MUST stay acyclic — assigning is rejected when
    it would close a cycle (A rides B riding A, or longer chains). Same-room
    only. This is the pure RELATIONSHIP: carrying movement (a mount moving
    its riders) is a separate mechanic and deliberately not silently half-
    implemented here."""
    if not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                (msg.get("token_id", -1), room_id))
    if tok is None:
        return
    raw = msg.get("mount_id", msg.get("mount_token_id"))
    mid = None
    if raw not in (None, "", 0):
        try:
            mid = int(raw)
        except (TypeError, ValueError):
            await send_to(ws, "error", {"msg": "Unknown mount"})
            return
        if mid == tok["id"]:
            await send_to(ws, "error", {"msg": "A token cannot ride itself"})
            return
        mount = db.q1("SELECT id, mount_token_id FROM tokens WHERE id=? AND room_id=?",
                      (mid, room_id))
        if mount is None:
            await send_to(ws, "error", {"msg": "That mount is not in this room"})
            return
        # the mount's own mount chain must never lead back to this token
        cur, hops = mount["mount_token_id"], 0
        while cur is not None and hops <= 1000:
            if cur == tok["id"]:
                await send_to(ws, "error", {"msg": "That would create a riding cycle"})
                return
            nxt = db.q1("SELECT mount_token_id FROM tokens WHERE id=?", (cur,))
            cur = nxt["mount_token_id"] if nxt else None
            hops += 1
    if tok.get("mount_token_id") == mid:
        return                                   # idempotent, no broadcast storm
    db.x("UPDATE tokens SET mount_token_id=? WHERE id=?", (mid, tok["id"]))
    await broadcast(room_id, "token_mount", {"token_id": tok["id"], "mount_token_id": mid})


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
    fw, fh = _clean_span(msg, size)
    disposition = _clean_disposition(msg.get("disposition") or base.get("disposition"))
    mp = get_map(room_id)
    placed = _place_token(mp, {"room_id": room_id, "id": 0, "size": size,
                               "fw": fw, "fh": fh}, x, y)
    if placed is None:
        await send_to(ws, "error", {"msg": "No valid placement for that footprint"})
        return
    x, y = placed
    tid = db.x("INSERT INTO tokens (room_id,label,color,x,y,npc,size,disposition,fw,fh) "
               "VALUES (?,?,?,?,?,?,?,?,?,?)",
               (room_id, label, color, x, y, db.json_dumps(block), size, disposition, fw, fh))
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
    fw, fh = _clean_span(base, size, tok)
    disposition = _clean_disposition(msg.get("disposition", tok.get("disposition", "")))
    candidate = {**tok, "size": size, "fw": fw, "fh": fh}
    mp = get_map(room_id)
    existing = _room_token_rows(room_id)
    desired = footprint.origin_from_pixel(tok["x"], tok["y"], mp["cell"], mp)
    if (fw, fh) != (tok.get("fw"), tok.get("fh")) or size != tok.get("size"):
        # D81/15B: a footprint CHANGE must fit at the CURRENT anchor — no
        # silent relocation. Only unrelated edits keep the legacy placement.
        if not footprint.valid_final_position(mp, candidate, desired, existing):
            await send_to(ws, "error",
                          {"msg": "That footprint does not fit here — the save kept "
                                  "the previous size"})
            return
        x, y = tok["x"], tok["y"]
    else:
        origin = footprint.find_valid_origin(mp, candidate, desired, existing)
        if origin is None:
            await send_to(ws, "error", {"msg": "No room to resize this token footprint"})
            return
        x, y = footprint.origin_pixels(origin, footprint.token_span(candidate), mp["cell"])
    db.x("UPDATE tokens SET npc=?, label=?, color=?, size=?, disposition=?, x=?, y=?, "
         "fw=?, fh=? WHERE id=?",
         (db.json_dumps(block), label, color, size, disposition, x, y, fw, fh, tok["id"]))
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
