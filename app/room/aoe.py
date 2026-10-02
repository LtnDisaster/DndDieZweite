"""AoE targeting templates — a purely visual relay for the DM (no game resolution).

The DM arms a template (shape + size + direction), clicks the grid, and the shape
parameters are relayed verbatim to everyone; each client recomputes the covered cells
from the same client-side geometry (``aoeCells``) and paints a short-lived overlay.
Nothing is stored or resolved here on purpose (D3): AoE *effects* stay a manual step at
the table — this only shows the area of effect. DM-only, since it is a DM presentation
tool."""
from .net import broadcast, send_to

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
    await broadcast(room_id, "aoe", {
        "shape": shape, "x": x, "y": y, "size": size,
        "dir": msg.get("dir", "E"), "color": str(msg.get("color", "#e74c3c"))[:16],
    })
