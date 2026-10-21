"""D163-8: loot tables are CSV — and now rollable at the table.

A content kind (`loottables.csv`, columns id,name,die,entries) becomes a DM
action: "roll_loot" with the table id. The server loads the ROOM's table,
rolls one entry by weight (or the table's own die), resolves the quantity
(number or dice string) and posts the result through the ONE chat pipeline
(`chat.post_chat` -> a "chat" event + the messages row) so every client sees
the roll live and in history. Nothing here invents a treasure economy — the
table decides what exists.
"""
import json
import random

from .. import content as C
from . import chat as CHAT
from .dice import do_roll
from .net import send_to


async def handle_roll_loot(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await send_to(ws, "error", {"msg": "Only the DM rolls loot"})
        return
    tid = str(msg.get("table_id") or "").strip()[:24]
    row = next((r for r in C.load("loottable", room_id)
                if str(r.get("id")) == tid), None)
    if row is None:
        await send_to(ws, "error", {"msg": "No loot table with that id"})
        return
    try:
        entries = json.loads(row.get("entries") or "[]")
    except ValueError:
        await send_to(ws, "error", {"msg": "Loot table entries are unreadable"})
        return
    if not entries:
        await send_to(ws, "error", {"msg": "Loot table has no entries"})
        return
    die = str(row.get("die") or "").strip()
    if die:
        r = do_roll(die, None)
        total = r["total"] if r else None
    else:
        total = random.randint(1, sum(int(e.get("weight", 1)) for e in entries))
    if total is None:
        await send_to(ws, "error", {"msg": "Loot table die is not rollable"})
        return
    acc, pick = 0, None
    for e in entries:
        acc += int(e.get("weight", 1))
        if total <= acc:
            pick = e
            break
    pick = pick or entries[-1]
    qty = str(pick.get("qty") or "1")
    n = None
    if qty.isdigit():
        n = int(qty)
    else:
        r = do_roll(qty, None)
        n = r["total"] if r else None
    if n is None:
        await send_to(ws, "error", {"msg": f"Loot quantity '{qty}' is not rollable"})
        return
    label = str(pick.get("label") or "?")[:80]
    table = str(row.get("name") or row.get("id") or "loot")[:60]
    await CHAT.post_chat(room_id, user, text=f"🎲 {table}: {n} × {label}",
                         channel="global", visibility="public",
                         meta={"source": "loot", "table_id": row.get("id", "")})
