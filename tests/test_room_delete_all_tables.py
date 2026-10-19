"""D157 — room deletion must survive EVERY room-scoped row, not just the
tables that happened to exist when D76 was written.

Manual abnahme found the real defect: a room that ever saw a loot container
or a custom/CSV-imported item could NOT be deleted — "Delete … permanently"
did nothing. Cause: `item_defs` and `containers` carry a FK REFERENCES
rooms(id) WITHOUT ON DELETE CASCADE, while `PRAGMA foreign_keys=ON` is set,
so `DELETE FROM rooms` raised IntegrityError and db.tx() rolled the whole
cascade back -> HTTP 500 with only a transient toast as feedback.

Two properties are pinned here:
  1. functional: a room seeded in every room-scoped table deletes 200 and
     leaves zero orphans behind;
  2. structural: the delete cascade list stays in lockstep with the schema —
     any room child table whose FK is NOT `ON DELETE CASCADE` must appear in
     rooms.ROOM_DELETE_CHILD_TABLES, or the endpoint 500s exactly like D157.
"""
import pytest
from starlette.testclient import TestClient

from app import db, rooms as rooms_mod
from app.main import app
from tests.test_movement_fog import H, reg


@pytest.fixture()
def client():
    return TestClient(app)


def _room(client, tag):
    dm = reg(client, f"dm{tag}")
    code = client.post("/api/rooms", json={"name": f"Room {tag}"}, headers=H(dm)).json()["code"]
    room_id = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    return dm, code, room_id


def test_room_with_children_deletes_and_leaves_no_orphans(client):
    dm, code, room_id = _room(client, "All")
    # seed every room-scoped table the D76 cascade list is responsible for
    db.x("INSERT INTO floor_maps(room_id, floor, map_json) VALUES(?,?,?)",
         (room_id, "crypt", "{}"))
    db.x("INSERT INTO item_defs(id, room_id, name) VALUES(?,?,?)",
         (room_id, room_id, "Custom Ring"))
    db.x("INSERT INTO containers(room_id, object_id, items) VALUES(?,?,?)",
         (room_id, "chest1", "[]"))
    db.x("INSERT INTO content(kind, room_id, id, name) VALUES(?,?,?,?)",
         ("item", room_id, "sword1", "Longsword"))
    db.x("INSERT INTO inv_ops(op_id, room_id, kind) VALUES(?,?,?)",
         ("op-1", room_id, "give"))

    r = client.delete(f"/api/rooms/{code}", headers=H(dm))
    assert r.status_code == 200, f"delete must succeed with children: {r.status_code} {r.text}"

    assert db.q1("SELECT id FROM rooms WHERE code=?", (code,)) is None
    # every room-scoped table forgot the room (floor_maps cascades via schema)
    for table in ("item_defs", "containers", "content", "inv_ops", "floor_maps",
                  "room_state", "room_members", "tokens", "messages", "notes", "quests"):
        left = db.q(f"SELECT COUNT(*) n FROM {table} WHERE room_id=?", (room_id,))[0]["n"]
        assert left == 0, f"{table} left {left} orphan row(s) for the deleted room"


def test_non_cascading_room_fks_are_all_in_the_delete_list():
    """The structural guard. A new room child table with a non-cascading FK
    must be added to rooms.ROOM_DELETE_CHILD_TABLES the day it ships, or this
    test fails — because that is exactly how D157 stayed invisible."""
    c = db.conn()
    handled = set(rooms_mod.ROOM_DELETE_CHILD_TABLES)
    tables = [r["name"] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    required = set()
    for t in tables:
        for fk in c.execute(f"PRAGMA foreign_key_list({t})"):
            if fk["table"] == "rooms" and (fk["on_delete"] or "").upper() != "CASCADE":
                required.add(t)
    missing = required - handled
    assert not missing, (f"room child tables with a non-cascading FK that delete_room "
                         f"does not clear (would 500 like D157): {sorted(missing)}")
