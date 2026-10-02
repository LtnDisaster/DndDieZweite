"""Quest-log WebSocket transport (thin by design, D49/D51).

Every handler is exactly: parse -> authorize (quests are DM-authored) -> call
the pure game operation in ``app.quests`` -> post a notice + broadcast a
payload-less ``quests_changed`` so clients refetch ``/state`` (which filters
per viewer). The live payload never carries quest content, so DM-only quests
cannot leak even by accident; reconstruction always goes through ``/state``.

Future automation will call ``app.quests.*`` directly — NOT these handlers.
"""
from .. import quests as questlog
from .gamelog import post_message
from .net import broadcast, send_to


async def _notice(room_id, user, is_dm, quest, text):
    """Notices are transient presentation; the DM-only flag follows the quest."""
    vis = "dm" if quest and quest.get("visibility") == "dm" else "public"
    await post_message(room_id, user, text, visibility=vis, kind="system", is_dm=is_dm)


async def _need_dm(ws, is_dm):
    if not is_dm:
        await send_to(ws, "error", {"msg": "Only the DM manages quests"})
        return False
    return True


def _qid(msg):
    try:
        return int(msg["quest_id"])
    except (KeyError, ValueError, TypeError):
        return None


async def handle_quest_add(ws, room_id, user, is_dm, msg):
    if not await _need_dm(ws, is_dm):
        return
    q = questlog.create_quest(room_id, msg.get("title"), msg.get("description", ""),
                              msg.get("objectives"), msg.get("visibility", "party"),
                              actor_id=user["id"])
    if q is None:
        await send_to(ws, "error", {"msg": "Quest needs a title"})
        return
    await _notice(room_id, user, is_dm, q, f"📜 QUEST ADDED: {q['title']}")
    await broadcast(room_id, "quests_changed", None)


async def handle_quest_update(ws, room_id, user, is_dm, msg):
    if not await _need_dm(ws, is_dm):
        return
    qid = _qid(msg)
    q = questlog.update_quest(qid, title=msg.get("title"), description=msg.get("description"),
                              status=msg.get("status"), visibility=msg.get("visibility"),
                              actor_id=user["id"])
    if q is None:
        await send_to(ws, "error", {"msg": "No such quest"})
        return
    await broadcast(room_id, "quests_changed", None)


async def handle_quest_obj_add(ws, room_id, user, is_dm, msg):
    if not await _need_dm(ws, is_dm):
        return
    q = questlog.add_objective(_qid(msg), msg.get("text"), msg.get("hidden", False),
                               actor_id=user["id"])
    if q is None:
        await send_to(ws, "error", {"msg": "No such quest"})
        return
    await _notice(room_id, user, is_dm, q, f"📜 OBJECTIVE ADDED: {q['title']}")
    await broadcast(room_id, "quests_changed", None)


async def handle_quest_obj_done(ws, room_id, user, is_dm, msg):
    if not await _need_dm(ws, is_dm):
        return
    obj_id = str(msg.get("objective_id", ""))
    q = questlog.set_objective(_qid(msg), obj_id, bool(msg.get("done")),
                               actor_id=user["id"])
    if q is None:
        await send_to(ws, "error", {"msg": "No such quest"})
        return
    obj = next((o for o in q["objectives"] if o["id"] == obj_id), None)
    if obj:
        await _notice(room_id, user, is_dm, q,
                      f"📜 OBJECTIVE UPDATED: {obj['text']} ({q['title']})")
    await broadcast(room_id, "quests_changed", None)


async def handle_quest_complete(ws, room_id, user, is_dm, msg):
    await _finish(ws, room_id, user, is_dm, msg, questlog.complete_quest,
                  "✅ QUEST COMPLETED: ")


async def handle_quest_fail(ws, room_id, user, is_dm, msg):
    await _finish(ws, room_id, user, is_dm, msg, questlog.fail_quest,
                  "❌ QUEST FAILED: ")


async def _finish(ws, room_id, user, is_dm, msg, op, prefix):
    if not await _need_dm(ws, is_dm):
        return
    q = op(_qid(msg), actor_id=user["id"])
    if q is None:
        await send_to(ws, "error", {"msg": "No such quest"})
        return
    await _notice(room_id, user, is_dm, q, prefix + q["title"])
    await broadcast(room_id, "quests_changed", None)


async def handle_quest_delete(ws, room_id, user, is_dm, msg):
    if not await _need_dm(ws, is_dm):
        return
    if not questlog.delete_quest(_qid(msg), actor_id=user["id"]):
        await send_to(ws, "error", {"msg": "No such quest"})
        return
    await broadcast(room_id, "quests_changed", None)
