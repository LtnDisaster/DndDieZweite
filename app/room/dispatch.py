"""Message dispatch: map a message ``type`` to its handler. Flat registry, no bus."""
from .. import db, floors, mapmodel
from .aoe import handle_aoe
from .abilities import handle_ability_cast
from .audio import (handle_audio_add, handle_audio_pause, handle_audio_play,
                    handle_audio_remove, handle_audio_stop, handle_sound_trigger)
from .chat import handle_chat, handle_narrative
from .combat import (handle_dash, handle_end_turn, handle_hp, handle_init_end,
                     handle_init_end_round, handle_init_next, handle_init_start,
                     handle_turn_mark)
from .conditions import (handle_cond_add, handle_cond_remove,
                            handle_knock_prone, handle_stand)
from .death import handle_death_clear, handle_death_save
from .doors import handle_door
from .encounters import handle_spawn_encounter
from .dice import (handle_cast, handle_long_rest, handle_npc_attack, handle_resource,
                   handle_roll, handle_short_rest)
from .items import handle_attune, handle_identify, handle_recharge, handle_use_item
from .fog import handle_fog_edit, handle_fog_toggle
from .interact import handle_interact
from .movement import handle_move, handle_path_preview, handle_stop_move
from .moveforced import handle_forced_move
from .net import broadcast, get_map, map_lock, send_to, set_map, sys_msg
from .pings import handle_ping
from .progression import handle_class_levels
from .quests import (handle_quest_add, handle_quest_complete, handle_quest_delete,
                     handle_quest_fail, handle_quest_obj_add, handle_quest_obj_done,
                     handle_quest_update)
from .secret_events import handle_secret_event
from .status import handle_exhaustion, handle_inspiration, handle_temp_hp
from .tokens import (handle_add_token, handle_del_token, handle_token_controller,
                     handle_token_mount, handle_token_rotate, handle_token_span,
                     handle_token_visual, handle_update_npc, handle_token_image,
                     handle_token_floor, handle_token_light,
                     handle_token_darkvision)


async def handle_map_edit(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    mp_new = mapmodel.sanitize(msg.get("map"))
    if mp_new is None:
        await send_to(ws, "error", {"msg": "Invalid map data"})
        return
    # D88: which plane is being edited ("" = primary, unchanged semantics).
    # Every extra floor fits the primary frame — one world, one camera.
    fl = str(msg.get("floor") or "")
    if not floors.exists(room_id, fl):
        return await send_to(ws, "error", {"msg": "No such floor"})
    if fl:
        mp_new = mapmodel.fit(mp_new, get_map(room_id))
    async with map_lock(room_id):
        old = get_map(room_id, fl)
        same_size = (mp_new["w"], mp_new["h"]) == (old["w"], old["h"])
        # The fog-off flag is owned by fog_toggle only (room-wide, primary-
        # stored); editor snapshots never carry it and must not reset it.
        mp_new["fog_off"] = bool(get_map(room_id).get("fog_off"))
        # D87: darkness is toggled EXPLICITLY via the map_edit "dark" field —
        # a stale editor snapshot must not silently flip it (fog_off precedent).
        if "dark" not in msg:
            mp_new["dark"] = bool(old.get("dark"))
        dark_changed = bool(old.get("dark")) != bool(mp_new.get("dark"))
        if msg.get("reset_fog"):
            mp_new["explored"] = [0] * (mp_new["w"] * mp_new["h"])
        elif same_size:
            mp_new["explored"] = old["explored"]
        else:
            # Resize without reset_fog: carry the overlapping region row-wise.
            # Copying the old array wholesale (wrong length) used to be dropped
            # silently by sanitize on the next load — fog vanished with no DM
            # intent behind it.
            ow, oh, nw, nh = old["w"], old["h"], mp_new["w"], mp_new["h"]
            carried = [0] * (nw * nh)
            for y in range(min(oh, nh)):
                row = old["explored"][y * ow: y * ow + min(ow, nw)]
                carried[y * nw: y * nw + len(row)] = row
            mp_new["explored"] = carried

        # Editor snapshots can be stale while play changes trap/loot runtime state.
        # Preserve authoritative runtime flags for entities that still exist.
        old_traps = {e.get("id"): e for e in old.get("traps", [])}
        for trap in mp_new.get("traps", []):
            prev = old_traps.get(trap.get("id"))
            if prev is not None:
                trap["discovered"] = bool(prev.get("discovered"))
                trap["triggered"] = bool(prev.get("triggered"))
                trap["triggered_by"] = prev.get("triggered_by")
        old_loot = {e.get("id"): e for e in old.get("loot", [])}
        for loot in mp_new.get("loot", []):
            prev = old_loot.get(loot.get("id"))
            if prev is not None:
                loot["taken_by"] = prev.get("taken_by")
        # D82: object runtime state (the generic boolean carrier) is authoritative
        # world state — a stale editor snapshot must not reset it (trap precedent).
        old_objs = {e.get("id"): e for e in old.get("objects", [])}
        for obj in mp_new.get("objects", []):
            prev = old_objs.get(obj.get("id"))
            if prev is not None:
                obj["state"] = prev.get("state") or {}
        set_map(room_id, mp_new, fl)
    sys_msg(room_id, "DM updated the map." if not fl else f"DM updated the map on {fl}.")
    await broadcast(room_id, "map_changed", None)
    # D89: a map that LIGHTS the world must not sit stale — when the edit
    # introduces or moves static light sources, re-run the per-viewer token
    # visibility decision. (Dark flips re-run below via dark_changed; plain
    # terrain edits keep the classic next-move revalidation semantics.)
    if any(((o.get("interact") or {}).get("op") or {}).get("kind") == "lamp"
           for o in mp_new.get("objects", [])) or \
       any(((o.get("interact") or {}).get("op") or {}).get("kind") == "lamp"
           for o in old.get("objects", [])):
        from .visibility import reevaluate_visibility
        await reevaluate_visibility(room_id)
    if dark_changed:
        from .visibility import reevaluate_visibility
        await reevaluate_visibility(room_id)


HANDLERS = {
    "chat": handle_chat,
    "narrative": handle_narrative,
    "secret_event": handle_secret_event,
    "roll": handle_roll,
    "npc_attack": handle_npc_attack,
    "move": handle_move,
    "stop_move": handle_stop_move,
    "path_preview": handle_path_preview,
    "forced_move": handle_forced_move,
    "fog_edit": handle_fog_edit,
    "fog_toggle": handle_fog_toggle,
    "map_edit": handle_map_edit,
    "add_token": handle_add_token,
    "del_token": handle_del_token,
    "update_npc": handle_update_npc,
    "cond_add": handle_cond_add,
    "cond_remove": handle_cond_remove,
    "stand": handle_stand,
    "knock_prone": handle_knock_prone,
    "token_span": handle_token_span,
    "token_visual": handle_token_visual,      # D82: presentation bounds only
    "token_image": handle_token_image,        # D85: server-validated artwork asset only
    "token_floor": handle_token_floor,        # D86: change the occupancy/visibility plane
    "token_light": handle_token_light,        # D87: light radius in cells (dark rooms)
    "token_darkvision": handle_token_darkvision,   # D89: sense radius (owner-only sight)
    "token_rotate": handle_token_rotate,      # D82: visual facing only, never the footprint
    "token_controller": handle_token_controller,   # D82: DM assigns a generic controller
    "token_mount": handle_token_mount,             # D82: acyclic rider→mount relationship
    "door": handle_door,
    "interact": handle_interact,              # D82: data-driven allowlisted world ops
    "aoe": handle_aoe,
    "death_save": handle_death_save,
    "death_clear": handle_death_clear,
    "init_start": handle_init_start,
    "init_next": handle_init_next,
    "init_end_round": handle_init_end_round,
    "init_end": handle_init_end,
    "end_turn": handle_end_turn,          # D79: owner of the active token or DM
    "dash": handle_dash,
    "turn_mark": handle_turn_mark,
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
    "audio_pause": handle_audio_pause,
    "audio_stop": handle_audio_stop,
    "sound_trigger": handle_sound_trigger,
    "quest_add": handle_quest_add,
    "quest_update": handle_quest_update,
    "quest_obj_add": handle_quest_obj_add,
    "quest_obj_done": handle_quest_obj_done,
    "quest_complete": handle_quest_complete,
    "quest_fail": handle_quest_fail,
    "quest_delete": handle_quest_delete,
    "class_levels": handle_class_levels,
    "ability_cast": handle_ability_cast,
}


async def handle(ws, room_id, user, is_dm, msg):
    if not isinstance(msg, dict):
        return
    fn = HANDLERS.get(msg.get("type"))
    if fn is None:
        return
    await fn(ws, room_id, user, is_dm, msg)
