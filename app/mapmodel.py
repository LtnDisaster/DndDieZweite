"""Room map model: default map, sanitize/validate, fog reveal, role-filtered views."""
import json
import re

DEFAULT_W, DEFAULT_H = 40, 26
MAX_W, MAX_H = 80, 60
MAX_JSON = 256 * 1024
FOG_R = 6
LABEL_RE = re.compile(r"^[\x20-\x7eA-Za-z0-9 .,:;!?'+()\-–—’&%$#/]*$")


def default_map(w=DEFAULT_W, h=DEFAULT_H):
    return {"w": w, "h": h, "cell": 50, "cells": [0] * (w * h),
            "explored": [0] * (w * h), "traps": [], "loot": []}


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
    else:
        tb = e.get("taken_by")
        out["taken_by"] = int(tb) if isinstance(tb, (int, float)) else None
    return out


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
    ids = [t["id"] for t in traps] + [l["id"] for l in loot]
    if len(ids) != len(set(ids)):
        return None
    out = {"w": w, "h": h, "cell": max(20, min(100, int(d.get("cell", 50)))),
           "cells": cells, "explored": explored, "traps": traps, "loot": loot}
    if len(json.dumps(out)) > MAX_JSON:
        return None
    return out


def reveal(mp, x, y, r=FOG_R):
    """Mark explored cells around (x, y). Returns list of newly revealed cell indices."""
    newly = []
    for cy in range(max(0, y - r), min(mp["h"], y + r + 1)):
        for cx in range(max(0, x - r), min(mp["w"], x + r + 1)):
            i = cy * mp["w"] + cx
            if not mp["explored"][i]:
                mp["explored"][i] = 1
                newly.append(i)
    return newly


def visible_map(mp, user_id, is_dm, owned_cells):
    """Per-recipient map: DM sees truth; players only explored/fog-radius cells,
    only discovered traps, and their own taken loot."""
    if is_dm:
        return mp
    w, h = mp["w"], mp["h"]
    seen = [False] * (w * h)
    for i, e in enumerate(mp["explored"]):
        if e:
            seen[i] = True
    for (tx, ty) in owned_cells:
        for cy in range(max(0, ty - FOG_R), min(h, ty + FOG_R + 1)):
            for cx in range(max(0, tx - FOG_R), min(w, tx + FOG_R + 1)):
                seen[cy * w + cx] = True
    cells = [mp["cells"][i] if seen[i] else None for i in range(w * h)]
    traps = [t for t in mp["traps"] if t.get("discovered")]
    loot = [l for l in mp["loot"] if l.get("taken_by") == user_id]
    return {"w": w, "h": h, "cell": mp["cell"], "cells": cells,
            "explored": mp["explored"], "traps": traps, "loot": loot}
