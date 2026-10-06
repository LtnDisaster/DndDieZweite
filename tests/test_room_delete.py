"""Room deletion (D76): authorization, cascade lifecycle, ws lifecycle.

Manual testing found no usable way to get rid of junk rooms — and the server
had no endpoint at all. A deletion must be DM-owner-only (a crafted player
request 403s), must clean persistent AND in-memory state (no zombie rooms),
must tell connected clients via room_deleted, and must be idempotent-safe.
"""
import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app
from app.room import net

from tests.test_integration import H, join_room, make_char, reg, state_of, ws_connect  # noqa: F401
from tests.test_movement_fog import recv_until  # error-aware variant


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    from app import ratelimit
    ratelimit._hits.clear()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def _room(client, tag):
    dm = reg(client, f"dm{tag}")
    code = client.post("/api/rooms", json={"name": f"Room {tag}"}, headers=H(dm)).json()["code"]
    return dm, code


def _dm_id(username):
    return db.q1("SELECT id FROM users WHERE username=?", (username,))["id"]


def test_owner_can_delete_and_everything_goes_away(client):
    dm, code = _room(client, "Del")
    pl = reg(client, "plDel")
    join_room(client, pl, code)
    ch = make_char(client, pl)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(pl))
    r = client.delete(f"/api/rooms/{code}", headers=H(dm))
    assert r.status_code == 200, r.text

    room = db.q1("SELECT * FROM rooms WHERE code=?", (code,))
    assert room is None
    for table in ("tokens", "messages", "room_state", "notes", "quests", "room_members"):
        leftover = db.q(f"SELECT * FROM {table} WHERE room_id IN "
                        f"(SELECT id FROM rooms WHERE code=?)", (code,))
        assert leftover == [], f"{table} rows survived the delete"
    # gone from the member list of both parties
    rooms_dm = [x["code"] for x in client.get("/api/rooms", headers=H(dm)).json()]
    rooms_pl = [x["code"] for x in client.get("/api/rooms", headers=H(pl)).json()]
    assert code not in rooms_dm and code not in rooms_pl
    # rejoin impossible: room is gone, not merely un-joined
    assert client.post("/api/rooms/join", json={"code": code}, headers=H(pl)).status_code == 404
    assert client.get(f"/api/rooms/{code}/state", headers=H(dm)).status_code == 404


def test_player_cannot_delete_room_even_by_crafting_the_request(client):
    dm, code = _room(client, "NoDel")
    pl = reg(client, "plNoDel")
    join_room(client, pl, code)
    r = client.delete(f"/api/rooms/{code}", headers=H(pl))
    assert r.status_code == 403
    assert db.q1("SELECT id FROM rooms WHERE code=?", (code,)) is not None
    # a stranger isn't even allowed to learn it exists
    stranger = reg(client, "stNoDel")
    assert client.delete(f"/api/rooms/{code}", headers=H(stranger)).status_code == 403
    assert client.delete("/api/rooms/ZZZZZZ", headers=H(dm)).status_code == 404


def test_double_delete_is_safe(client):
    dm, code = _room(client, "DblDel")
    assert client.delete(f"/api/rooms/{code}", headers=H(dm)).status_code == 200
    assert client.delete(f"/api/rooms/{code}", headers=H(dm)).status_code == 404


def test_clients_receive_room_deleted_and_room_state_is_purged(client):
    dm, code = _room(client, "WsDel")
    pl = reg(client, "plWsDel")
    join_room(client, pl, code)
    with ws_connect(client, dm, code) as wsdm, ws_connect(client, pl, code) as wspl:
        room_id = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
        assert client.delete(f"/api/rooms/{code}", headers=H(dm)).status_code == 200
        recv_until(wsdm, "room_deleted", fail_on_error=False)
        recv_until(wspl, "room_deleted", fail_on_error=False)
    # purge (walk cancels, closes, registry cleanup) is scheduled on the room
    # loop — poll briefly until the registries forgot the room
    import time
    deadline = time.time() + 3
    while time.time() < deadline and (room_id in net._clients or room_id in net._map_locks):
        time.sleep(0.05)
    assert room_id not in net._clients, "zombie room clients left in memory"
    assert room_id not in net._map_locks, "zombie map lock left in memory"
