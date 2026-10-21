"""D86 — floors: named occupancy/visibility planes inside one room map.

Design (deliberately minimal foundation): every room has a PRIMARY floor
(named "") that predates this feature — every existing token lives there
without any data migration. A DM may add further named floors.

D159 changed the *geometry* meaning (planes are joined through open volume, and
a laid floor is a solid slab) but NOT the storage foundation: floors stay a
single ordered stack on the canonical 10 ft scale (primary = level 0). D159
also made levels genuinely signed — a DM can declare a cellar *below* the
primary (levels -1, -2, …), and the declaration stack is read bottom→top::

    below[-1] … below[0]   PRIMARY(0)   above[0] … above[+1]

Storage is backward-compatible: with no below-floor the room keeps the legacy
flat list (all above primary, exactly the pre-D159 shape); the object form
``{"below": [...], "above": [...]}`` is written only once a below-floor exists.
Every reader accepts both.
"""
import json
import re

from . import db, vertical

MAX_FLOORS = 8
NAME_MAX = 24
_NAME_RE = re.compile(r"^[\w \-.'·—]{1,%d}$" % NAME_MAX, re.UNICODE)


def _rows(room):
    """Normalise a rooms.floors cell into (below, above): both ordered
    primary-outward (below[0] is level -1, above[0] is level +1). Legacy flat
    lists are all-above; the {"below","above"} object carries both."""
    try:
        data = json.loads(room.get("floors") or "[]")
    except (ValueError, TypeError):
        return [], []
    if isinstance(data, dict):
        below = [str(n) for n in (data.get("below") or []) if str(n).strip()]
        above = [str(n) for n in (data.get("above") or []) if str(n).strip()]
        return below, above
    if isinstance(data, list):
        return [], [str(n) for n in data if isinstance(n, (str, int)) and str(n).strip()]
    return [], []


def _dump(below, above):
    """Store the smallest representation that round-trips: the legacy flat list
    while there is nothing below the primary, the object form otherwise."""
    if not below:
        return json.dumps(above)
    return json.dumps({"below": below, "above": above})


def parse(room) -> list:
    """Every NAMED floor (no primary), ordered bottom→top — the membership set.
    Accepts the legacy flat list and the D159 object form."""
    below, above = _rows(room)
    return list(reversed(below)) + list(above)


def order(room) -> list:
    """The full vertical stack INCLUDING the primary "" in its true position,
    ordered bottom→top (levels ascending). With no below-floor this is exactly
    the legacy ``[""] + parse`` — the primary at the very bottom."""
    below, above = _rows(room)
    return list(reversed(below)) + [""] + list(above)


def level_map(room) -> dict:
    """name -> SIGNED vertical level (primary 0, above positive, below negative)."""
    below, above = _rows(room)
    lm = {"": 0}
    for i, name in enumerate(below):
        lm[name] = -(i + 1)
    for i, name in enumerate(above):
        lm[name] = i + 1
    return lm


def exists(room_id, name) -> bool:
    if not name:
        return True                              # primary floor always exists
    room = db.q1("SELECT floors FROM rooms WHERE id=?", (room_id,))
    return room is not None and name in parse(room)


def clean_name(value):
    n = str(value or "").strip()[:NAME_MAX + 1]
    return n if n and _NAME_RE.fullmatch(n) else None


def add(room_id, value, below=False):
    """Declare a new named plane (DM checked by the caller). ``below`` puts it
    immediately under the primary stack (a cellar, level -1/-2/…); otherwise it
    is added on top. -> (ok, ordered_named_floors_or_message)."""
    name = clean_name(value)
    if name is None:
        return False, "Floor name must be 1-24 plain characters"
    room = db.q1("SELECT floors FROM rooms WHERE id=?", (room_id,))
    if room is None:
        return False, "No such room"
    b, a = _rows(room)
    if name in b or name in a:
        return False, "That floor already exists"
    if len(b) + len(a) >= MAX_FLOORS:
        return False, f"At most {MAX_FLOORS} extra floors"
    if below:
        b.append(name)                           # primary-outward: next cellar down
    else:
        a.append(name)                           # next storey up
    db.x("UPDATE rooms SET floors=? WHERE id=?", (_dump(b, a), room_id))
    return True, parse(room)


def rename(room_id, old, value):
    """D102 — rename a named floor. The plane's own map (floor_maps) and the
    tokens standing on it follow the new name here, atomically with the floor
    list. CROSS-PLANE REFERENCES (stair objects on other planes whose
    destination names this floor) are map contents — the caller rewrites those
    in the same breath, or every stair to the old name silently dangles.
    -> (ok, ordered_named_floors_or_message). DM checked by the caller."""
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
    b = [name if f == old else f for f in _rows(room)[0]]
    a = [name if f == old else f for f in _rows(room)[1]]
    db.x("UPDATE rooms SET floors=? WHERE id=?", (_dump(b, a), room_id))
    db.x("UPDATE floor_maps SET floor=? WHERE room_id=? AND floor=?",
         (name, room_id, old))
    db.x("UPDATE tokens SET floor=? WHERE room_id=? AND floor=?",
         (name, room_id, old))
    return True, parse(room)


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
    # D160 — levels are positional (see level_map), so removing a MIDDLE storey
    # would silently renumber every plane beyond it and could newly-JOIN planes
    # that a now-removed slab used to separate. Refuse unless it is the
    # outermost plane on its side, so survivors never move or re-join; the DM
    # removes top-down / bottom-up instead. Maps and tokens are name-keyed, so
    # an outside-in removal leaves their levels, positions and maps untouched.
    below, above = _rows(room)
    side, lst = ("below", below) if name in below else ("above", above)
    if lst and name != lst[-1]:
        return False, (f"'{name}' has another floor "
                       f"{'below' if side == 'below' else 'above'} it "
                       f"('{lst[-1]}') — remove the outer floors first "
                       f"({'bottom-up' if side == 'below' else 'top-down'}) so the "
                       f"remaining floors keep their height and stored maps.")
    b = [f for f in below if f != name]
    a = [f for f in above if f != name]
    db.x("UPDATE rooms SET floors=? WHERE id=?", (_dump(b, a), room_id))
    db.x("DELETE FROM floor_maps WHERE room_id=? AND floor=?", (room_id, name))  # D88
    return True, parse(room)


# ---------------------------------------------------------------------------
# D113 Phase 7: the declared floor ORDER is the vertical stack, on the canonical
# 10 ft scale (primary = 0). This is a GEOMETRY/REPORTING convention only — planes
# are joined by open volume, never by the scale below: a token two floors up is 20
# ft higher, it does NOT collide or cast cover through the scale below (D86/D88).
# D159: levels are signed — a below-floor is negative.
# ---------------------------------------------------------------------------

def level(room_id, name):
    """Vertical level of a floor (signed): the primary floor is 0; each storey
    declared above is +1 per step, each cellar below is -1 per step. Order is the
    stack, so the level of an unknown/absent floor falls back to 0."""
    if not name:
        return 0
    room = db.q1("SELECT floors FROM rooms WHERE id=?", (room_id,))
    if room is None:
        return 0
    return level_map(room).get(name, 0)



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
