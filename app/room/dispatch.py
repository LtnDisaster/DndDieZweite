"""Message dispatch: map a message ``type`` to its handler. Flat registry, no bus."""
from .. import db, mapmodel
from .combat import (handle_hp, handle_init_end, handle_init_end_round,
                     handle_init_next, handle_init_start)
from .dice import handle_cast, handle_long_rest, handle_roll
from .items import handle_attune, handle_identify, handle_recharge, handle_use_item
from .movement import handle_move
from .net import broadcast, get_map, map_lock, send_to, set_map, sys_msg
from .tokens import handle_add_token, handle_del_token


async def handle_chat(ws, room_id, user, is_dm, msg):
    text = str(msg.get("text", ""))[:2000].strip()
    if not text:
        return
    mid = db.x("INSERT INTO messages (room_id,user_id,type,body) VALUES (?,?,'chat',?)",
               (room_id, user["id"], text))
    await broadcast(room_id, "chat", {"id": mid, "username": user["username"], "text": text})


async def handle_map_edit(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    mp_new = mapmodel.sanitize(msg.get("map"))
    if mp_new is None:
        await send_to(ws, "error", {"msg": "Invalid map data"})
        return
    async with map_lock(room_id):
        old = get_map(room_id)
        if (mp_new["w"], mp_new["h"]) == (old["w"], old["h"]):
            mp_new["explored"] = old["explored"]
        set_map(room_id, mp_new)
    sys_msg(room_id, "DM updated the map.")
    await broadcast(room_id, "map_changed", None)


HANDLERS = {
    "chat": handle_chat,
    "roll": handle_roll,
    "move": handle_move,
    "map_edit": handle_map_edit,
    "add_token": handle_add_token,
    "del_token": handle_del_token,
    "init_start": handle_init_start,
    "init_next": handle_init_next,
    "init_end_round": handle_init_end_round,
    "init_end": handle_init_end,
    "hp": handle_hp,
    "use_item": handle_use_item,
    "attune": handle_attune,
    "identify": handle_identify,
    "recharge": handle_recharge,
    "cast": handle_cast,
    "long_rest": handle_long_rest,
}


async def handle(ws, room_id, user, is_dm, msg):
    if not isinstance(msg, dict):
        return
    fn = HANDLERS.get(msg.get("type"))
    if fn is None:
        return
    await fn(ws, room_id, user, is_dm, msg)
