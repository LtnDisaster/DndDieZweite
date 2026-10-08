"""AoE targeting templates — a purely visual relay for the DM (no game resolution).

The DM arms a template (shape + size + direction), clicks the grid, and the shape
parameters are relayed to the viewers standing on the plane the template was
placed on; each client recomputes the covered cells from the same client-side
geometry (``aoeCells``) and paints a short-lived overlay. Nothing is stored or
resolved here on purpose (D3): AoE *effects* stay a manual step at the table —
this only shows the area of effect. DM-only, since it is a DM presentation
tool. SPRINT-20 (closes D88's note): the relay is PLANE-SCOPED — the DM's
claimed floor is validated against the room's floor list (map_edit precedent)
and delivered to the plane's watchers (``send_to_plane_viewed``), so a socket
standing on another plane never repaints its grid with foreign-plane cells."""
from .. import floors
from .net import send_to, send_to_plane_viewed

SHAPES = ("circle", "square", "line", "cone")


async def handle_aoe(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await send_to(ws, "error", {"msg": "Only the DM can place templates"})
        return
    try:
        x, y = int(msg["x"]), int(msg["y"])
        size = max(0, min(30, int(msg.get("size", 5))))
    except (KeyError, ValueError, TypeError):
        return
    shape = msg.get("shape") if msg.get("shape") in SHAPES else "circle"
    fl = str(msg.get("floor") or "")          # SPRINT-20: the plane you view
    if not floors.exists(room_id, fl):
        return await send_to(ws, "error", {"msg": "No such floor"})
    await send_to_plane_viewed(room_id, fl, "aoe", {
        "shape": shape, "x": x, "y": y, "size": size, "floor": fl,
        "dir": msg.get("dir", "E"), "color": str(msg.get("color", "#e74c3c"))[:16],
    })
