"""D86 — floors: named occupancy/visibility planes inside one room map.

Design (deliberately minimal foundation): every room has a PRIMARY floor
(named "") that predates this feature — every existing token lives there
without any data migration. A DM may add further named floors. Floors are
INDEPENDENT planes: tokens on different floors never collide, never block
pathfinding, and are not visible to viewers standing on another floor.
Moving between floors is explicit, never a costed walk — D102 tightened it to
two doors: the DM's token_floor operation, and the validated stair object the
players walk to. Positioning within a floor stays the D80-D84 contract.
"""
import json
import re

from . import db, vertical

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


def rename(room_id, old, value):
    """D102 — rename a named floor. The plane's own map (floor_maps) and the
    tokens standing on it follow the new name here, atomically with the floor
    list. CROSS-PLANE REFERENCES (stair objects on other planes whose
    destination names this floor) are map contents — the caller rewrites those
    in the same breath, or every stair to the old name silently dangles.
    -> (ok, floors_or_message). DM checked by the caller."""
    name = clean_name(value)
    if name is None:
        return False, "Floor name must be 1-24 plain characters"
    old = str(old or "")
    if not old:
        return False, "The primary floor cannot be renamed"
    room = db.q1("SELECT floors FROM rooms WHERE id=?", (room_id,))
    if room is None or old not in parse(room):
        return False, "No such floor"
    if name == old:
        return False, "That is its current name"
    if name in parse(room):
        return False, "That floor already exists"
    floors = [name if f == old else f for f in parse(room)]
    db.x("UPDATE rooms SET floors=? WHERE id=?", (json.dumps(floors), room_id))
    db.x("UPDATE floor_maps SET floor=? WHERE room_id=? AND floor=?",
         (name, room_id, old))
    db.x("UPDATE tokens SET floor=? WHERE room_id=? AND floor=?",
         (name, room_id, old))
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


# ---------------------------------------------------------------------------
# D113 Phase 7: the declared floor ORDER is the vertical stack, on the canonical
# 10 ft scale (primary = 0). This is a GEOMETRY/REPORTING convention only —
# planes stay collision/visibility independent (D86/D88): a token two floors up
# is 20 ft higher, it does NOT collide or cast cover through the scale below.
# ---------------------------------------------------------------------------

def level(room_id, name):
    """Vertical level of a floor: the primary floor is 0; each further declared
    floor sits one level (10 ft) above the previous, in declaration order."""
    if not name:
        return 0
    room = db.q1("SELECT floors FROM rooms WHERE id=?", (room_id,))
    if room is None:
        return 0
    names = parse(room)
    return names.index(name) + 1 if name in names else 0


def absolute_height_ft(room_id, floor_name, elev_units=0):
    """Absolute height in feet: the floor's 10 ft/level offset + the ground cell
    elevation (also 10 ft/unit)."""
    return vertical.absolute_ft(vertical.floor_to_ft(level(room_id, floor_name)),
                                elev_units)


# ---------------------------------------------------------------------------
# D114: a token's absolute VERTICAL SEGMENT on the shared 10 ft scale. `z` is the
# maintained mirror of the ground cell's elevation unit, so a token's under-edge
# = its floor's level offset + z·10 + elevation_ft; top = under-edge + height_ft.
# These are pure reporting/geometry helpers — whether that segment actually
# reaches another plane is gated by vertical openings (Phase 4/5), never assumed.
# ---------------------------------------------------------------------------

def token_base_ft(room_id, token):
    """Absolute height (ft) of a token's under edge on its home plane."""
    ground = absolute_height_ft(room_id, (token or {}).get("floor") or "",
                                (token or {}).get("z") or 0)
    return vertical.base_ft(ground, vertical.token_elevation_ft(token))


def token_top_ft(room_id, token):
    """Absolute height (ft) of a token's top edge."""
    return vertical.top_ft(token_base_ft(room_id, token), vertical.token_height_ft(token))


def token_levels_spanned(room_id, token):
    """Floor LEVELS whose 10 ft band the token's body segment overlaps (by height
    alone). Cross-plane PRESENCE additionally needs an opening (Phase 4/5)."""
    return vertical.levels_between(token_base_ft(room_id, token),
                                   token_top_ft(room_id, token))
