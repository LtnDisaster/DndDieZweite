"""Room map model: default map, sanitize/validate, fog reveal, role-filtered views."""
import json
import re

DEFAULT_W, DEFAULT_H = 40, 26
MAX_W, MAX_H = 80, 60
MAX_JSON = 256 * 1024
FOG_R = 6
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


def _canon_door(x, y, dir_, w, h):
    """Return a valid (x, y, dir) anchored to the lower-indexed cell, or None."""
    if dir_ == "l":
        x, dir_ = x - 1, "v"
    elif dir_ == "u":
        y, dir_ = y - 1, "h"
    if dir_ not in DOOR_DIRS:
        return None
    bx, by = neighbor(x, y, dir_)
    if not (0 <= x < w and 0 <= y < h and 0 <= bx < w and 0 <= by < h):
        return None
    return x, y, dir_


def default_map(w=DEFAULT_W, h=DEFAULT_H):
    return {"w": w, "h": h, "cell": 50, "cells": [0] * (w * h),
            "explored": [0] * (w * h), "traps": [], "loot": [], "doors": [], "pins": []}


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


def _entity(e, w, h):
    if not isinstance(e, dict):
        return None
    try:
        x, y = int(e["x"]), int(e["y"])
    except (KeyError, ValueError, TypeError):
        return None
    out = {"id": str(e.get("id", ""))[:16] or re.sub(r"\W", "", _label(e.get("label")))[:12] or "x",
           "x": max(0, min(w - 1, x)), "y": max(0, min(h - 1, y)),
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


def _clean_pin(p, w, h):
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
            "x": max(0, min(w - 1, x)), "y": max(0, min(h - 1, y)),
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
    size = w * h
    raw_cells = d.get("cells")
    if not isinstance(raw_cells, list) or len(raw_cells) != size:
        return None
    cells = []
    for v in raw_cells:
        try:
            cells.append(max(0, min(2, int(v))))
        except (ValueError, TypeError):
            return None
    raw_exp = d.get("explored")
    explored = [0] * size
    if isinstance(raw_exp, list) and len(raw_exp) == size:
        for i, v in enumerate(raw_exp):
            explored[i] = 1 if v else 0
    traps = [t for t in (_entity(e, w, h) for e in (d.get("traps") or [])[:100]) if t and "dc" in t]
    loot = [l for l in (_entity(e, w, h) for e in (d.get("loot") or [])[:100]) if l and "dc" not in l]
    doors, seen_edges = [], set()
    for e in (d.get("doors") or [])[:200]:
        if not isinstance(e, dict):
            continue
        try:
            x, y = int(e["x"]), int(e["y"])
        except (KeyError, ValueError, TypeError):
            continue
        canon = _canon_door(x, y, str(e.get("dir", "")).lower(), w, h)
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
        cp = _clean_pin(p, w, h)
        if cp is None:
            continue
        cid = 0
        while cp["id"] in pin_ids:
            cid += 1
            cp["id"] = f"{cp['id'][:14]}{cid}"
        pin_ids.add(cp["id"]); pins.append(cp)
    ids = [t["id"] for t in traps] + [l["id"] for l in loot]
    if len(ids) != len(set(ids)):
        return None
    out = {"w": w, "h": h, "cell": max(20, min(100, int(d.get("cell", 50)))),
           "cells": cells, "explored": explored, "traps": traps, "loot": loot,
           "doors": doors, "pins": pins, "fog_off": bool(d.get("fog_off"))}
    if len(json.dumps(out)) > MAX_JSON:
        return None
    return out


def reveal_cells(mp, cells):
    """Mark arbitrary currently-visible cells explored. Returns new indices.

    Accepts cell indices or ``(x, y)`` coordinates because LOS helpers return
    indices while manual/tooling code often has coordinates.
    """
    newly = []
    size = mp["w"] * mp["h"]
    for cell in cells:
        if isinstance(cell, (tuple, list)):
            x, y = cell
            if not (0 <= x < mp["w"] and 0 <= y < mp["h"]):
                continue
            i = y * mp["w"] + x
        else:
            i = int(cell)
            if not (0 <= i < size):
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
            x, y = i
            if 0 <= x < w and 0 <= y < h:
                seen[y * w + x] = True
        elif 0 <= i < w * h:
            seen[i] = True
    cells = [mp["cells"][i] if seen[i] else None for i in range(w * h)]
    traps = [t for t in mp["traps"] if t.get("discovered") or mp.get("fog_off")]
    loot = [l for l in mp["loot"] if l.get("taken_by") == user_id]
    doors = []
    for dr in mp.get("doors", []):
        if dr.get("secret"):
            continue  # secret passages are never transmitted to players
        bx, by = neighbor(dr["x"], dr["y"], dr["dir"])
        if seen[dr["y"] * w + dr["x"]] or seen[by * w + bx]:
            doors.append(dr)
    pins = []
    for p in mp.get("pins", []):
        vis = p.get("visibility", "dm")
        if (vis in ("players", "revealed") and seen[p["y"] * w + p["x"]]) or vis == "players":
            pins.append({k: p[k] for k in ("id", "x", "y", "type", "color", "title") if k in p})
    return {"w": w, "h": h, "cell": mp["cell"], "cells": cells,
            "explored": mp["explored"], "traps": traps, "loot": loot, "doors": doors,
            "pins": pins, "fog_off": bool(mp.get("fog_off"))}
