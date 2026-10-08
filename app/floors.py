"""D86 — floors: named occupancy/visibility planes inside one room map.

Design (deliberately minimal foundation): every room has a PRIMARY floor
(named "") that predates this feature — every existing token lives there
without any data migration. A DM may add further named floors. Floors are
INDEPENDENT planes: tokens on different floors never collide, never block
pathfinding, and are not visible to viewers standing on another floor.
Moving between floors is an explicit token_floor operation (stairs, ladders,
teleports), not a costed move — positioning within a floor stays the D80-D84
contract untouched.
"""
import json
import re

from . import db

MAX_FLOORS = 8
NAME_MAX = 24
_NAME_RE = re.compile(r"^[\w \-.'·—]{1,%d}$" % NAME_MAX, re.UNICODE)


def parse(room) -> list:
    """Floor names of a room row, primary first ('' always available)."""
    try:
        names = json.loads(room.get("floors") or "[]")
    except (ValueError, TypeError):
        names = []
    return [str(n) for n in names if isinstance(n, (str, int)) and str(n).strip()] \
        if isinstance(names, list) else []


def exists(room_id, name) -> bool:
    if not name:
        return True                              # primary floor always exists
    room = db.q1("SELECT floors FROM rooms WHERE id=?", (room_id,))
    return room is not None and name in parse(room)


def clean_name(value):
    n = str(value or "").strip()[:NAME_MAX + 1]
    return n if n and _NAME_RE.fullmatch(n) else None


def add(room_id, value):
    """-> (ok, floors_or_message). DM checked by the caller."""
    name = clean_name(value)
    if name is None:
        return False, "Floor name must be 1-24 plain characters"
    room = db.q1("SELECT floors FROM rooms WHERE id=?", (room_id,))
    if room is None:
        return False, "No such room"
    floors = parse(room)
    if name in floors:
        return False, "That floor already exists"
    if len(floors) >= MAX_FLOORS:
        return False, f"At most {MAX_FLOORS} extra floors"
    floors.append(name)
    db.x("UPDATE rooms SET floors=? WHERE id=?", (json.dumps(floors), room_id))
    return True, floors


def remove(room_id, value):
    name = str(value or "")
    if not name:
        return False, "The primary floor cannot be removed"
    room = db.q1("SELECT floors FROM rooms WHERE id=?", (room_id,))
    if room is None or name not in parse(room):
        return False, "No such floor"
    if db.q1("SELECT 1 AS hit FROM tokens WHERE room_id=? AND floor=? LIMIT 1",
             (room_id, name)) is not None:
        return False, "Tokens still stand on this floor"
    floors = [f for f in parse(room) if f != name]
    db.x("UPDATE rooms SET floors=? WHERE id=?", (json.dumps(floors), room_id))
    db.x("DELETE FROM floor_maps WHERE room_id=? AND floor=?", (room_id, name))  # D88
    return True, floors
