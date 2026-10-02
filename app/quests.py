"""Quest Log: structured, persistent adventure progress (D51).

Division of labor (deliberate, D51):

* Journal notes/handouts (`notes` table) = free-form information.
* Quests = structured objectives with an authoritative status.
* Notices (game-log lines) = transient presentation of a change. A
  reconnecting client reconstructs the quest log from ``/state`` — NEVER from
  replaying old notices.

This module is the GAME-LAYER operation surface: pure synchronous functions
over the DB that mutate persistent state and then emit a GameEvent (D52).
It imports no WebSocket/transport concepts, so a future trigger engine can
call ``complete_quest(...)`` exactly like the WS handler does — the same
operation, no faked client messages. Live delivery and filtering are the
transport's job (`app/room/quests.py` + `room_state()`).

Objectives are ``[{"id": "o1", "text": "...", "done": bool, "hidden": bool}]``.
Objective ``hidden`` marks DM-only hints; they are stripped in ``visible_for``.
"""
from . import db, events

STATUSES = ("active", "completed", "failed", "hidden")
VISIBILITIES = ("party", "dm")
# Statuses a non-DM viewer may ever receive (hidden quests stay server-side).
PLAYER_STATUSES = ("active", "completed", "failed")
MAX_QUESTS = 100
MAX_OBJECTIVES = 20


def _clean_objectives(objs) -> list:
    """Normalize an objectives payload to canonical rows. Silently drops junk."""
    out = []
    if not isinstance(objs, list):
        return out
    for o in objs[:MAX_OBJECTIVES]:
        if isinstance(o, dict):
            text = str(o.get("text", "")).strip()[:200]
            oid = str(o.get("id", "")).strip()[:24]
            if not text:
                continue
            out.append({"id": oid or f"o{len(out) + 1}", "text": text,
                        "done": bool(o.get("done")), "hidden": bool(o.get("hidden"))})
        else:
            text = str(o).strip()[:200]
            if text:
                out.append({"id": f"o{len(out) + 1}", "text": text,
                            "done": False, "hidden": False})
    return out


def _row(r) -> dict:
    r = dict(r)
    r["objectives"] = _clean_objectives(db.j(r.get("objectives"), []))
    return r


def row(quest_id) -> dict | None:
    r = db.q1("SELECT * FROM quests WHERE id=?", (int(quest_id),))
    return _row(r) if r else None


def all_for(room_id) -> list:
    return [_row(r) for r in db.q(
        "SELECT * FROM quests WHERE room_id=? ORDER BY id LIMIT ?", (room_id, MAX_QUESTS))]


def visible_for(room_id, is_dm: bool) -> list:
    """Server-side quest filter — THE security boundary for quest visibility.

    Players receive party-visible, non-hidden quests with objective-level
    hidden hints stripped. DM-only quests and hidden content are never even
    serialized into a player payload (live or /state).
    """
    if is_dm:
        return all_for(room_id)
    out = []
    for q in all_for(room_id):
        if q["visibility"] != "party" or q["status"] not in PLAYER_STATUSES:
            continue
        q = dict(q)
        q["objectives"] = [o for o in q["objectives"] if not o.get("hidden")]
        out.append(q)
    return out


def _touch(quest_id):
    db.x("UPDATE quests SET updated_at=datetime('now') WHERE id=?", (int(quest_id),))


def _emit(op_type, q, actor_id):
    events.emit(events.make(op_type, room_id=q["room_id"], actor_id=actor_id,
                            target_id=q["id"], quest_id=q["id"], title=q["title"],
                            status=q["status"], visibility=q["visibility"]))


def create_quest(room_id, title, description="", objectives=None,
                 visibility="party", actor_id=None) -> dict | None:
    title = str(title or "").strip()[:120]
    if not title:
        return None
    vis = str(visibility or "party").lower()
    if vis not in VISIBILITIES:
        vis = "party"
    qid = db.x("INSERT INTO quests (room_id,title,description,objectives,visibility) "
               "VALUES (?,?,?,?,?)",
               (room_id, title, str(description or "")[:2000],
                db.json_dumps(_clean_objectives(objectives)), vis))
    q = row(qid)
    _emit("quest_started", q, actor_id)
    return q


def update_quest(quest_id, *, title=None, description=None, status=None,
                 visibility=None, actor_id=None) -> dict | None:
    q = row(quest_id)
    if q is None:
        return None
    if title is not None:
        t = str(title).strip()[:120]
        if t:
            q["title"] = t
    if description is not None:
        q["description"] = str(description)[:2000]
    if status is not None and str(status).lower() in STATUSES:
        q["status"] = str(status).lower()
    if visibility is not None and str(visibility).lower() in VISIBILITIES:
        q["visibility"] = str(visibility).lower()
    db.x("UPDATE quests SET title=?, description=?, status=?, visibility=?, "
         "updated_at=datetime('now') WHERE id=?",
         (q["title"], q["description"], q["status"], q["visibility"], q["id"]))
    q = row(quest_id)
    _emit("quest_updated", q, actor_id)
    return q


def add_objective(quest_id, text, hidden=False, actor_id=None) -> dict | None:
    q = row(quest_id)
    if q is None:
        return None
    text = str(text or "").strip()[:200]
    if not text or len(q["objectives"]) >= MAX_OBJECTIVES:
        return q
    q["objectives"].append({"id": f"o{len(q['objectives']) + 1}", "text": text,
                            "done": False, "hidden": bool(hidden)})
    db.x("UPDATE quests SET objectives=?, updated_at=datetime('now') WHERE id=?",
         (db.json_dumps(q["objectives"]), q["id"]))
    q = row(quest_id)
    _emit("quest_updated", q, actor_id)
    return q


def set_objective(quest_id, objective_id, done, actor_id=None) -> dict | None:
    q = row(quest_id)
    if q is None:
        return None
    oid = str(objective_id)
    found = False
    for o in q["objectives"]:
        if o["id"] == oid:
            o["done"] = bool(done)
            found = True
    if not found:
        return q
    db.x("UPDATE quests SET objectives=?, updated_at=datetime('now') WHERE id=?",
         (db.json_dumps(q["objectives"]), q["id"]))
    q = row(quest_id)
    _emit("quest_updated", q, actor_id)
    return q


def complete_quest(quest_id, actor_id=None) -> dict | None:
    return _finish(quest_id, "completed", actor_id)


def fail_quest(quest_id, actor_id=None) -> dict | None:
    return _finish(quest_id, "failed", actor_id)


def _finish(quest_id, status, actor_id) -> dict | None:
    q = row(quest_id)
    if q is None:
        return None
    db.x("UPDATE quests SET status=?, updated_at=datetime('now') WHERE id=?",
         (status, q["id"]))
    q = row(quest_id)
    _emit("quest_completed" if status == "completed" else "quest_failed", q, actor_id)
    return q


def delete_quest(quest_id, actor_id=None) -> bool:
    q = row(quest_id)
    if q is None:
        return False
    db.x("DELETE FROM quests WHERE id=?", (q["id"],))
    events.emit(events.make("quest_updated", room_id=q["room_id"], actor_id=actor_id,
                            target_id=q["id"], quest_id=q["id"], title=q["title"],
                            status="deleted", visibility=q["visibility"]))
    return True
