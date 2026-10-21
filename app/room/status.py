"""Character status fields: temporary HP, inspiration and exhaustion."""
from .. import db, gear
from .dice import roller_char
from .net import broadcast, send_to, sys_msg


def _int(v, d):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


async def _own_char(room_id, user, is_dm, msg):
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None or tok["character_id"] is None:
        return None, None
    if not is_dm:
        owner = roller_char(room_id, user["id"])
        if owner is None or owner["id"] != tok["character_id"]:
            return None, None
    ch = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],)))
    return tok, ch


async def handle_temp_hp(ws, room_id, user, is_dm, msg):
    tok, ch = await _own_char(room_id, user, is_dm, msg)
    if ch is None:
        return
    current = max(0, min(999, _int(ch.get("temp_hp"), 0)))
    action = str(msg.get("action", "grant")).lower()
    if action == "clear":
        new = 0
    elif action == "set":
        new = max(0, min(999, _int(msg.get("amount"), 0)))
    else:
        new = max(current, max(0, min(999, _int(msg.get("amount"), 0))))
    if new == current:
        return
    db.x("UPDATE characters SET temp_hp=? WHERE id=?", (new, ch["id"]))
    sys_msg(room_id, f"{ch['name']} temporary HP: {new}")
    await broadcast(room_id, "snapshot", None)


async def handle_inspiration(ws, room_id, user, is_dm, msg):
    tok, ch = await _own_char(room_id, user, is_dm, msg)
    if ch is None:
        return
    on = int(bool(ch.get("inspiration")))
    action = str(msg.get("action", "toggle")).lower()
    if action == "gain":
        # D135 (audit F6): the pool is ONE marker. Gaining while inspired
        # follows the SRD: pass it on to a creature in this room, or nothing
        # is gained — never silent stacking, never silent loss.
        if on:
            other = db.q1("SELECT c.* FROM characters c JOIN tokens t "
                          "ON t.character_id=c.id "
                          "WHERE c.id=? AND t.room_id=? LIMIT 1",
                          (msg.get("pass_to_char", -1), room_id))
            if other is None or other["id"] == ch["id"]:
                sys_msg(room_id, f"{ch['name']} already has Heroic Inspiration — "
                                 f"nothing gained.")
                return
            db.x("UPDATE characters SET inspiration=0 WHERE id=?", (ch["id"],))
            db.x("UPDATE characters SET inspiration=1 WHERE id=?", (other["id"],))
            sys_msg(room_id, f"{ch['name']} passes Heroic Inspiration to {other['name']}.")
            await broadcast(room_id, "snapshot", None)
            return
        new = 1
    if action == "on":
        new = 1
    elif action == "off":
        new = 0
    else:
        new = 0 if on else 1
    db.x("UPDATE characters SET inspiration=? WHERE id=?", (new, ch["id"]))
    sys_msg(room_id, f"{ch['name']} inspiration {'gained' if new else 'used'}")
    await broadcast(room_id, "snapshot", None)


async def handle_exhaustion(ws, room_id, user, is_dm, msg):
    if not is_dm:                                   # D162-11: loud, safe refusal
        await send_to(ws, "error", {"msg": "DM only"})
        return
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None or tok["character_id"] is None:
        return
    ch = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],)))
    if ch is None:
        return
    cur = max(0, min(6, _int(ch.get("exhaustion"), 0)))
    action = str(msg.get("action", "set")).lower()
    if action == "inc":
        new = min(6, cur + 1)
    elif action == "dec":
        new = max(0, cur - 1)
    else:
        new = max(0, min(6, _int(msg.get("level"), cur)))
    if new == cur:
        return
    db.x("UPDATE characters SET exhaustion=? WHERE id=?", (new, ch["id"]))
    sys_msg(room_id, f"{ch['name']} exhaustion level {new}")
    if new >= 6:
        # AP-015 (audit F4/K8): "You die if your Exhaustion level is 6."
        # The server decides death itself — no death-save chance is invented.
        from . import death as D
        db.x("UPDATE characters SET hp=0, temp_hp=0 WHERE id=?", (ch["id"],))
        d = D.new()
        d["dead"] = True
        D.apply_thresholds(d)
        db.x("UPDATE tokens SET death=? WHERE id=?", (db.json_dumps(d), tok["id"]))
        sys_msg(room_id, f"{ch['name']} dies from exhaustion (level 6)")
    await broadcast(room_id, "snapshot", None)
