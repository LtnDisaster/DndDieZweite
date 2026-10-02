"""Message dispatch: map a message ``type`` to its handler. Flat registry, no bus."""
from .. import db, mapmodel
from .aoe import handle_aoe
from .audio import (handle_audio_add, handle_audio_play, handle_audio_remove,
                    handle_audio_stop, handle_sound_trigger)
from .chat import handle_chat, handle_narrative
from .combat import (handle_hp, handle_init_end, handle_init_end_round,
                     handle_init_next, handle_init_start)
from .conditions import handle_cond_add, handle_cond_remove
from .death import handle_death_clear, handle_death_save
from .doors import handle_door
from .encounters import handle_spawn_encounter
from .dice import (handle_cast, handle_long_rest, handle_npc_attack, handle_resource,
                   handle_roll, handle_short_rest)
from .items import handle_attune, handle_identify, handle_recharge, handle_use_item
from .fog import handle_fog_edit
from .movement import handle_move, handle_path_preview, handle_stop_move
from .net import broadcast, get_map, map_lock, send_to, set_map, sys_msg
from .pings import handle_ping
from .secret_events import handle_secret_event
from .status import handle_exhaustion, handle_inspiration, handle_temp_hp
from .tokens import handle_add_token, handle_del_token, handle_update_npc


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
        if (mp_new["w"], mp_new["h"]) == (old["w"], old["h"]) and not msg.get("reset_fog"):
            mp_new["explored"] = old["explored"]
        set_map(room_id, mp_new)
    sys_msg(room_id, "DM updated the map.")
    await broadcast(room_id, "map_changed", None)


HANDLERS = {
    "chat": handle_chat,
    "narrative": handle_narrative,
    "secret_event": handle_secret_event,
    "roll": handle_roll,
    "npc_attack": handle_npc_attack,
    "move": handle_move,
    "stop_move": handle_stop_move,
    "path_preview": handle_path_preview,
    "fog_edit": handle_fog_edit,
    "map_edit": handle_map_edit,
    "add_token": handle_add_token,
    "del_token": handle_del_token,
    "update_npc": handle_update_npc,
    "cond_add": handle_cond_add,
    "cond_remove": handle_cond_remove,
    "door": handle_door,
    "aoe": handle_aoe,
    "death_save": handle_death_save,
    "death_clear": handle_death_clear,
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
    "short_rest": handle_short_rest,
    "resource": handle_resource,
    "temp_hp": handle_temp_hp,
    "inspiration": handle_inspiration,
    "exhaustion": handle_exhaustion,
    "ping": handle_ping,
    "spawn_encounter": handle_spawn_encounter,
    "audio_add": handle_audio_add,
    "audio_remove": handle_audio_remove,
    "audio_play": handle_audio_play,
    "audio_stop": handle_audio_stop,
    "sound_trigger": handle_sound_trigger,
}


async def handle(ws, room_id, user, is_dm, msg):
    if not isinstance(msg, dict):
        return
    fn = HANDLERS.get(msg.get("type"))
    if fn is None:
        return
    await fn(ws, room_id, user, is_dm, msg)
