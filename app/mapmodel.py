"""Room map model: default map, sanitize/validate, fog reveal, role-filtered views."""
import json
import os
import re

DEFAULT_W, DEFAULT_H = 40, 26
MAX_W, MAX_H = 80, 60
MAX_JSON = 256 * 1024
FOG_R = 6
# Automatic world growth (D67): when a PLAYER token nears an edge, the map is
# grown by a whole chunk, not one cell per step. Chunk (12) exceeds the trigger
# distance (FOG_R + 5 = 11), so one expansion buys at least a full chunk of
# walking before the next trigger. Growth stops at MAX_W/MAX_H (documented cap).
EXPAND_CHUNK = 12
GROW_MARGIN = 5
# D77: AUTO_GROW is a feature flag, OFF by default (manual testing verdict —
# see DECISIONS D77). The expansion machinery stays implemented and tested;
# DNDTABLE_AUTO_GROW=1 re-enables the automatic trigger. DM manual editing
# (map editor resize) is independent of this flag.
AUTO_GROW = os.environ.get("DNDTABLE_AUTO_GROW", "0") == "1"

# Terrain registry (D69): the cell vocabulary and its movement/vision semantics.
# 0 floor, 1 wall (classic), 2 difficult terrain,
# 3 barrier  — blocks movement, does NOT block vision, climbable,
# 4 low_obstacle — passable but costs double (5e knee-high/undergrowth), climbable,
#                does not block vision.
# app/wall.py exposes the same facts as cell/edge queries; path, los, movecost and
# footprint all consult this registry — never a hard-coded cell value again.
TERRAIN = {
    0: {"name": "floor",       "walk": True,  "difficult": False,
        "blocks_movement": False, "blocks_vision": False, "height": 0, "climbable": False},
    1: {"name": "wall",        "walk": False, "difficult": False,
        "blocks_movement": True,  "blocks_vision": True,  "height": 2, "climbable": True},
    2: {"name": "difficult",   "walk": True,  "difficult": True,
        "blocks_movement": False, "blocks_vision": False, "height": 0, "climbable": False},
    3: {"name": "barrier",     "walk": False, "difficult": False,
        "blocks_movement": True,  "blocks_vision": False, "height": 1, "climbable": True},
    4: {"name": "low_obstacle", "walk": True, "difficult": True,
        "blocks_movement": False, "blocks_vision": False, "height": 0, "climbable": True},
}
TERRAIN_MAX = max(TERRAIN)


def terrain(v):
    """Registry entry for a raw cell value (unknown/fog None -> floor)."""
    try:
        return TERRAIN[int(v or 0)]
    except (TypeError, ValueError, KeyError):
        return TERRAIN[0]


def walkable(v):
    return terrain(v)["walk"]


def difficult(v):
    return terrain(v)["difficult"]


def blocks_movement(v):
    return terrain(v)["blocks_movement"]


def blocks_vision(v):
    return terrain(v)["blocks_vision"]


# ---------- world <-> storage coordinates (D72) ----------
# Coordinates on the WIRE and in the DB are ALWAYS world coordinates: token
# pixels, trap/loot/pin/door cells, preview cells, effect anchors. The raw
# per-cell arrays (cells/elev/explored) are STORAGE: a window with origin
# (ox, oy), where storage (0, 0) is world (ox, oy). Origin starts at [0, 0]
# (every legacy map) and only DECREASES — west/north growth prepends cells and
# lowers the origin — so growing the world NEVER moves any entity. The old
# re-anchoring grew the array AND renumbered every stored position; anything
# that missed a shift (mid-walk routes, ghosts, effects, the client camera)
# produced the reported teleporting/jumping world. These helpers are the ONE
# canonical conversion; no other module may derive its own offset.
def origin_of(mp):
    o = mp.get("origin") or [0, 0]
    try:
        return int(o[0]), int(o[1])
    except (TypeError, ValueError, IndexError):
        return 0, 0


def world_bounds(mp):
    """Half-open world rect: x in [x0, x1), y in [y0, y1)."""
    ox, oy = origin_of(mp)
    return ox, oy, ox + mp["w"], oy + mp["h"]


def in_world(mp, x, y):
    x0, y0, x1, y1 = world_bounds(mp)
    return x0 <= x < x1 and y0 <= y < y1


def to_local(mp, x, y):
    """WORLD cell -> STORAGE cell (array space)."""
    ox, oy = origin_of(mp)
    return x - ox, y - oy


def world_of(mp, sx, sy):
    """STORAGE cell -> WORLD cell."""
    ox, oy = origin_of(mp)
    return sx + ox, sy + oy


def flat_idx(mp, x, y):
    """WORLD cell -> flat STORAGE index, or None when outside the world."""
    sx, sy = to_local(mp, x, y)
    if 0 <= sx < mp["w"] and 0 <= sy < mp["h"]:
        return sy * mp["w"] + sx
    return None


def terrain_at(mp, x, y):
    """Raw terrain value at a WORLD cell, or None when out of world."""
    i = flat_idx(mp, x, y)
    return None if i is None else mp["cells"][i]


def elev_at(mp, x, y):
    """Elevation unit at a WORLD cell; 0 (flat) when out of world or no layer."""
    el = mp.get("elev") or []
    i = flat_idx(mp, x, y)
    return int(el[i]) if (el and i is not None and i < len(el)) else 0


def explored_at(mp, x, y):
    i = flat_idx(mp, x, y)
    return i is not None and i < len(mp["explored"]) and bool(mp["explored"][i])

LABEL_RE = re.compile(r"^[\x20-\x7eA-Za-z0-9 .,:;!?'+()\-–—’&%$#/]*$")

# A door sits on an interior edge: dir "v" joins (x,y)<->(x+1,y), "h" joins (x,y)<->(x,y+1).
DOOR_DIRS = ("v", "h")


def neighbor(x, y, dir_):
    return (x + 1, y) if dir_ == "v" else (x, y + 1)


def _edge(a, b):
    return frozenset((tuple(a), tuple(b)))


def door_edge(dr):
    return _edge((dr["x"], dr["y"]), neighbor(dr["x"], dr["y"], dr["dir"]))


def blocked_edges(mp):
    """Set of frozenset cell-pairs that movement may not cross (closed/locked doors)."""
    return {door_edge(dr) for dr in mp.get("doors", []) if dr.get("closed")}


def find_door(mp, x1, y1, x2, y2):
    key = _edge((x1, y1), (x2, y2))
    for dr in mp.get("doors", []):
        if door_edge(dr) == key:
            return dr
    return None


def _canon_door(x, y, dir_, w, h, ox=0, oy=0):
    """Return a valid (x, y, dir) anchored to the lower-indexed cell, or None.
    x/y are WORLD cells; the bounds are the WORLD window [ox, ox+w) (D72)."""
    if dir_ == "l":
        x, dir_ = x - 1, "v"
    elif dir_ == "u":
        y, dir_ = y - 1, "h"
    if dir_ not in DOOR_DIRS:
        return None
    bx, by = neighbor(x, y, dir_)
    if not (ox <= x < ox + w and oy <= y < oy + h and ox <= bx < ox + w and oy <= by < oy + h):
        return None
    return x, y, dir_


def default_map(w=DEFAULT_W, h=DEFAULT_H):
    return {"w": w, "h": h, "cell": 50, "origin": [0, 0], "cells": [0] * (w * h),
            "elev": [0] * (w * h),
            "explored": [0] * (w * h), "traps": [], "loot": [], "doors": [], "pins": [],
            "objects": []}


def fit(mp, base):
    """D88: every floor shares the primary map's DIMENSIONS and world anchor
    (one camera, one world window, one growth story). A floor map is clamped
    to the base: rows copy row-wise, missing cells read as floor, extras are
    dropped. Content is preserved where it still fits."""
    if not mp:
        return dict(base)
    w, h, cell = base["w"], base["h"], base["cell"]
    out = dict(mp)
    out["w"], out["h"] = w, h
    out["origin"] = list(base.get("origin") or [0, 0])
    src = mp.get("cells") or []
    ow = mp.get("w") or w
    cells = [0] * (w * h)
    for y in range(min(h, mp.get("h") or 0)):
        row = src[y * ow: y * ow + min(ow, w)]
        cells[y * w: y * w + len(row)] = row
    out["cells"] = cells
    ex = mp.get("explored") or []
    exn = [0] * (w * h)
    for y in range(min(h, mp.get("h") or 0)):
        row = ex[y * ow: y * ow + min(ow, w)]
        exn[y * w: y * w + len(row)] = row
    out["explored"] = exn
    return out


def load(raw, default=None):
    mp = default_map()
    if default:
        mp = default
    if not raw:
        return mp
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return mp
    return sanitize(d) or mp


def _label(s, dflt="?"):
    s = str(s if s is not None else "")[:80]
    return s if s and LABEL_RE.match(s) else dflt


def _entity(e, w, h, ox=0, oy=0):
    if not isinstance(e, dict):
        return None
    try:
        x, y = int(e["x"]), int(e["y"])
    except (KeyError, ValueError, TypeError):
        return None
    out = {"id": str(e.get("id", ""))[:16] or re.sub(r"\W", "", _label(e.get("label")))[:12] or "x",
           "x": max(ox, min(ox + w - 1, x)), "y": max(oy, min(oy + h - 1, y)),
           "label": _label(e.get("label"))}
    if "dc" in e or "dmg" in e:
        try:
            out["dc"] = max(1, min(30, int(e.get("dc", 12))))
        except (ValueError, TypeError):
            out["dc"] = 12
        dmg = str(e.get("dmg", "1d4"))[:16]
        out["dmg"] = dmg if re.match(r"^\d*d\d+([+-]\d+)?$", dmg.lower()) else "1d4"
        out["discovered"] = bool(e.get("discovered"))
        # Runtime lifecycle, kept apart from visibility on purpose:
        # discovered = revealed to players; triggered = already sprung
        # (one-shot re-entry gate; survives map edits via the merge in
        # dispatch.handle_map_edit). triggered_by records the token id.
        out["triggered"] = bool(e.get("triggered"))
        tb = e.get("triggered_by")
        out["triggered_by"] = int(tb) if isinstance(tb, (int, float)) else None
    else:
        tb = e.get("taken_by")
        out["taken_by"] = int(tb) if isinstance(tb, (int, float)) else None
    return out


INTERACT_OPS = ("toggle", "door")   # the ONLY operations a world object may drive


def _clean_object(o, w, h, ox=0, oy=0):
    """D82: generic interactable world object (lever, switch, chest, plate).

    The interaction is DATA driving one of the INTERACT_OPS — never executable
    code. An unknown op kind drops the interact field (the object stays plain
    decoration); runtime ``state`` is a tiny boolean carrier preserved across
    map edits by dispatch.handle_map_edit, exactly like trap lifecycle flags."""
    if not isinstance(o, dict):
        return None
    try:
        x, y = int(o["x"]), int(o["y"])
    except (KeyError, ValueError, TypeError):
        return None
    out = {"id": str(o.get("id", ""))[:16] or re.sub(r"\W", "", _label(o.get("label")))[:12] or "x",
           "x": max(ox, min(ox + w - 1, x)), "y": max(oy, min(oy + h - 1, y)),
           "label": _label(o.get("label")),
           "dm_only": bool(o.get("dm_only")),
           # an EXPLICIT off ({"on": false}) is world truth (D89 lamps, D82
           # levers) — only absent/garbage state normalizes to the default-on {}
           "state": ({"on": bool(o["state"]["on"])}
                     if isinstance(o.get("state"), dict) and "on" in o["state"]
                     else ({"on": True} if isinstance(o.get("state"), dict) and o["state"].get("on") else {}))}
    it = o.get("interact")
    if isinstance(it, dict):
        op = it.get("op")
        kind = str(op.get("kind", "")).lower() if isinstance(op, dict) else ""
        label = str(it.get("label", "")).strip()[:40] or "Interact"
        if kind == "toggle":
            out["interact"] = {"label": label, "op": {"kind": "toggle"}}
        elif kind == "door":
            try:
                dx, dy = int(op["x"]), int(op["y"])
            except (KeyError, TypeError, ValueError):
                return out                       # dangling link -> plain decoration
            dir_ = str(op.get("dir", "")).lower()
            if dir_ not in DOOR_DIRS:
                return out
            out["interact"] = {"label": label,
                               "op": {"kind": "door", "x": dx, "y": dy, "dir": dir_}}
        elif kind == "stair":
            # D88: validated plane transition — destination is checked at USE
            # time (floor exists, cell free); dangling here = plain decoration.
            try:
                sx, sy = int(op["x"]), int(op["y"])
            except (KeyError, TypeError, ValueError):
                return out
            if "floor" not in op:
                return out
            to = str(op["floor"])[:24].strip()
            out["interact"] = {"label": label,
                               "op": {"kind": "stair", "floor": to, "x": sx, "y": sy}}
        elif kind == "lamp":
            # D89: static light source. The light is DATA (radius) + the
            # existing boolean state carrier (on/off); runtime flips go
            # through the allowlisted interact op, never through map edits.
            try:
                bright = max(0, min(30, int(op["bright"])))
            except (KeyError, TypeError, ValueError):
                bright = 5
            out["interact"] = {"label": label,
                               "op": {"kind": "lamp", "bright": bright}}
        # any other kind: silently dropped — DATA never carries code
    return out


def _clean_pin(p, w, h, ox=0, oy=0):
    if not isinstance(p, dict):
        return None
    try:
        x, y = int(p.get("x")), int(p.get("y"))
    except (ValueError, TypeError):
        return None
    vis = str(p.get("visibility", "dm")).lower()
    if vis not in ("dm", "players", "revealed"):
        vis = "dm"
    color = str(p.get("color", "#f1c40f"))[:7]
    if not re.match(r"^#[0-9a-fA-F]{6}$", color):
        color = "#f1c40f"
    typ = str(p.get("type", "info")).lower()[:16] or "info"
    return {"id": str(p.get("id", ""))[:16] or f"p{len(str(x))}{x}{y}",
            "x": max(ox, min(ox + w - 1, x)), "y": max(oy, min(oy + h - 1, y)),
            "type": typ, "visibility": vis, "color": color,
            "title": str(p.get("title", ""))[:80], "description": str(p.get("description", ""))[:1000]}


def sanitize(d):
    if not isinstance(d, dict):
        return None
    try:
        w, h = int(d["w"]), int(d["h"])
    except (KeyError, ValueError, TypeError):
        return None
    w, h = max(8, min(MAX_W, w)), max(6, min(MAX_H, h))
    # World origin (D72): the storage window's WORLD anchor. Legacy maps have no
    # field -> [0, 0]; west/north growth lowers it. Clamped sane: never positive,
    # never beyond a multiple of the cap (a map cannot have grown that far).
    ox = oy = 0
    raw_o = d.get("origin")
    if isinstance(raw_o, (list, tuple)) and len(raw_o) == 2:
        try:
            ox = max(-4 * MAX_W, min(0, int(raw_o[0])))
            oy = max(-4 * MAX_H, min(0, int(raw_o[1])))
        except (TypeError, ValueError):
            ox = oy = 0
    size = w * h
    raw_cells = d.get("cells")
    if not isinstance(raw_cells, list) or len(raw_cells) != size:
        return None
    cells = []
    for v in raw_cells:
        try:
            cells.append(max(0, min(TERRAIN_MAX, int(v))))
        except (ValueError, TypeError):
            return None
    # Elevation layer (D70): integer height units per cell, missing/invalid -> flat.
    raw_elev = d.get("elev")
    elev = [0] * size
    if isinstance(raw_elev, list) and len(raw_elev) == size:
        try:
            elev = [max(-6, min(6, int(v))) for v in raw_elev]
        except (ValueError, TypeError):
            elev = [0] * size
    raw_exp = d.get("explored")
    explored = [0] * size
    if isinstance(raw_exp, list) and len(raw_exp) == size:
        for i, v in enumerate(raw_exp):
            explored[i] = 1 if v else 0
    traps = [t for t in (_entity(e, w, h, ox, oy) for e in (d.get("traps") or [])[:100]) if t and "dc" in t]
    loot = [l for l in (_entity(e, w, h, ox, oy) for e in (d.get("loot") or [])[:100]) if l and "dc" not in l]
    doors, seen_edges = [], set()
    for e in (d.get("doors") or [])[:200]:
        if not isinstance(e, dict):
            continue
        try:
            x, y = int(e["x"]), int(e["y"])
        except (KeyError, ValueError, TypeError):
            continue
        canon = _canon_door(x, y, str(e.get("dir", "")).lower(), w, h, ox, oy)
        if canon is None:
            continue
        x, y, dir_ = canon
        key = _edge((x, y), neighbor(x, y, dir_))
        if key in seen_edges:
            continue
        seen_edges.add(key)
        locked = bool(e.get("locked"))
        doors.append({"id": str(e.get("id", ""))[:16] or f"d{len(doors)}",
                      "x": x, "y": y, "dir": dir_,
                      "closed": bool(e.get("closed", True)) or locked,
                      "locked": locked,
                      # dm_only: only the DM may operate it (locked stays physical).
                      # secret: never transmitted to players at all (secret passages).
                      "dm_only": bool(e.get("dm_only")),
                      "secret": bool(e.get("secret")),
                      "label": _label(e.get("label"), "Door")})
    pins, pin_ids = [], set()
    for p in (d.get("pins") or [])[:200]:
        cp = _clean_pin(p, w, h, ox, oy)
        if cp is None:
            continue
        cid = 0
        while cp["id"] in pin_ids:
            cid += 1
            cp["id"] = f"{cp['id'][:14]}{cid}"
        pin_ids.add(cp["id"]); pins.append(cp)
    objects, obj_ids = [], set()
    for e in (d.get("objects") or [])[:100]:
        co = _clean_object(e, w, h, ox, oy)
        if co is None:
            continue
        base = co["id"]
        cid = 0
        while co["id"] in obj_ids:
            cid += 1
            co["id"] = f"{base[:14]}{cid}"
        obj_ids.add(co["id"]); objects.append(co)
    ids = [t["id"] for t in traps] + [l["id"] for l in loot]
    if len(ids) != len(set(ids)):
        return None
    out = {"w": w, "h": h, "cell": max(20, min(100, int(d.get("cell", 50)))),
           "origin": [ox, oy], "cells": cells, "elev": elev, "explored": explored,
           "traps": traps,
           "loot": loot, "doors": doors, "pins": pins, "objects": objects,
           "fog_off": bool(d.get("fog_off")),
           "dark": bool(d.get("dark"))}          # D87: sight comes from LIGHT only
    if len(json.dumps(out)) > MAX_JSON:
        return None
    return out


def reveal_cells(mp, cells):
    """Mark arbitrary currently-visible cells explored. Returns new STORAGE indices.

    Accepts flat STORAGE indices or WORLD ``(x, y)`` coordinates because LOS
    helpers return indices while manual/tooling code works in world cells (D72).
    """
    newly = []
    size = mp["w"] * mp["h"]
    for cell in cells:
        if isinstance(cell, (tuple, list)):
            i = flat_idx(mp, cell[0], cell[1])
        else:
            i = int(cell)
            if not (0 <= i < size):
                i = None
        if i is None:
            continue
        if not mp["explored"][i]:
            mp["explored"][i] = 1
            newly.append(i)
    return newly


def visible_map(mp, user_id, is_dm, visible_cells=()):
    """Per-recipient map. DM sees truth; players get explored memory plus current LOS.
    Hidden traps, foreign loot and unrevealed terrain are never transmitted."""
    if is_dm:
        return mp
    w, h = mp["w"], mp["h"]
    # Fog-off room flag: terrain and static entities are transmitted to every
    # member. Live NPC/token positions are NOT handled here — those are
    # filtered per recipient by the LOS pipeline, so hidden foes stay hidden.
    if mp.get("fog_off"):
        seen = [True] * (w * h)
    else:
        seen = [bool(e) for e in mp["explored"]]
    for i in visible_cells:
        if isinstance(i, tuple):
            # WORLD (x, y) — the only coordinate space tooling code speaks (D72)
            j = flat_idx(mp, i[0], i[1])
            if j is not None:
                seen[j] = True
        elif 0 <= i < w * h:
            seen[i] = True
    cells = [mp["cells"][i] if seen[i] else None for i in range(w * h)]
    el = mp.get("elev") or [0] * (w * h)
    elev = [el[i] if seen[i] else None for i in range(w * h)]
    traps = [t for t in mp["traps"] if t.get("discovered") or mp.get("fog_off")]
    loot = [l for l in mp["loot"] if l.get("taken_by") == user_id]
    doors = []
    for dr in mp.get("doors", []):
        if dr.get("secret"):
            continue  # secret passages are never transmitted to players
        bx, by = neighbor(dr["x"], dr["y"], dr["dir"])
        di = flat_idx(mp, dr["x"], dr["y"])
        bi = flat_idx(mp, bx, by)
        if (di is not None and seen[di]) or (bi is not None and seen[bi]):
            doors.append(dr)
    pins = []
    for p in mp.get("pins", []):
        vis = p.get("visibility", "dm")
        pi = flat_idx(mp, p["x"], p["y"])
        if (vis in ("players", "revealed") and pi is not None and seen[pi]) or vis == "players":
            pins.append({k: p[k] for k in ("id", "x", "y", "type", "color", "title") if k in p})
    objects = []
    for o in mp.get("objects", []):
        if o.get("dm_only"):
            continue                              # DM-only objects are never transmitted
        oi = flat_idx(mp, o["x"], o["y"])
        if not (oi is not None and seen[oi]) and not mp.get("fog_off"):
            continue                              # unseen cell: object not yet revealed
        it = o.get("interact")
        # Players learn the object and its action LABEL — never the linked door
        # position or op payload; the server resolves the operation by object id.
        copy = {"id": o["id"], "x": o["x"], "y": o["y"], "label": o["label"],
                "state": o.get("state") or {}}
        if it:
            copy["interact"] = {"label": it["label"], "kind": it["op"]["kind"]}
            if it["op"]["kind"] == "lamp":
                # glow radius is view furniture, not a secret (D89)
                copy["interact"]["bright"] = it["op"].get("bright", 5)
                copy["interact"]["on"] = bool((o.get("state") or {}).get("on", True))
        objects.append(copy)
    return {"w": w, "h": h, "cell": mp["cell"], "origin": origin_of(mp),
            "cells": cells, "elev": elev,
            "explored": mp["explored"], "traps": traps, "loot": loot, "doors": doors,
            "pins": pins, "objects": objects, "fog_off": bool(mp.get("fog_off")),
            "dark": bool(mp.get("dark"))}


# ---------- automatic world growth (D67) ----------

def growth_needed(mp, origin, side=1, vision=FOG_R):
    """Directions the map must grow so a token at WORLD ``origin`` (footprint
    ``side``) is no longer within ``vision + GROW_MARGIN`` cells of an edge.
    Distance is measured from the token's FOOTPRINT, so a Huge token triggers
    earlier than a Medium one at the same anchor. Pure and deterministic.
    Measurement happens in STORAGE space — the edges are the window's edges."""
    x, y = to_local(mp, origin[0], origin[1])
    m = int(vision) + GROW_MARGIN
    dirs = []
    if x <= m:
        dirs.append("west")
    if y <= m:
        dirs.append("north")
    if isinstance(side, (tuple, list)):
        w, h = max(1, int(side[0])), max(1, int(side[1]))
    else:
        w = h = max(1, int(side))
    if mp["w"] - (x + w) <= m:
        dirs.append("east")
    if mp["h"] - (y + h) <= m:
        dirs.append("south")
    return dirs


def grow_map(mp, dirs, chunk=EXPAND_CHUNK):
    """Grow the world in the given directions by ``chunk`` cells (clamped to the
    MAX_W/MAX_H STORAGE cap). Returns ``(grown_map, (dx, dy))`` (cells prepended
    west/north, informational only), or ``(None, (0, 0))`` at the cap.

    D72 invariant: NOTHING that lives in world space moves. Tokens, traps,
    loot, pins and doors keep their coordinates; west/north growth prepends the
    array window and lowers ``origin`` by the same amount, so the WORLD cell
    under any entity is unchanged. Only the per-cell arrays are re-anchored —
    inside this one function, atomically, before anything observes the map.
    New cells are plain floor, flat and unexplored: growth is not exploration
    and leaks no geometry under fog."""
    dirs = [d for d in dirs if d in ("west", "east", "north", "south")]
    w, h = mp["w"], mp["h"]
    want_w = ("west" in dirs) + ("east" in dirs)
    want_h = ("north" in dirs) + ("south" in dirs)
    new_w = min(MAX_W, w + want_w * chunk) if want_w else w
    new_h = min(MAX_H, h + want_h * chunk) if want_h else h
    dx = min(chunk, new_w - w) if "west" in dirs else 0
    dy = min(chunk, new_h - h) if "north" in dirs else 0
    if new_w == w and new_h == h:
        return None, (0, 0)

    def remap(flat, default):
        out = [default] * (new_w * new_h)
        for oy in range(h):
            row = flat[oy * w: oy * w + w]
            out[(oy + dy) * new_w + dx: (oy + dy) * new_w + dx + w] = row
        return out

    grown = dict(mp)
    grown["w"], grown["h"] = new_w, new_h
    ox, oy = origin_of(mp)
    grown["origin"] = [ox - dx, oy - dy]
    grown["cells"] = remap(mp["cells"], 0)
    grown["elev"] = remap(mp.get("elev") or [0] * (w * h), 0)
    grown["explored"] = remap(mp["explored"], 0)
    # traps/loot/pins/doors: WORLD coordinates — unchanged by growth (D72).
    return grown, (dx, dy)
