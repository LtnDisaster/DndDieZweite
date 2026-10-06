"""P1 regressions (D75/D77): the PLAYER payload must keep the black screen impossible.

Server side of the "everything is black" manual regression: the per-recipient
grid a player receives must contain a legitimate visible region around their
own token (LOS ring), the DM's full map must stay complete, and the automatic
expansion feature flag must be OFF by default (fixed map stable; machinery
tested in test_map_expand.py with the flag explicitly enabled).
"""
import pytest
from starlette.testclient import TestClient

from app import main
from app import mapmodel


def _user(client, tag):
    import uuid
    name = f"{tag}{uuid.uuid4().hex[:8]}"
    r = client.post("/api/register", json={"username": name, "password": "secret123"})
    assert r.status_code == 200, r.text
    val = r.headers["set-cookie"].split("vtt_session=", 1)[1].split(";", 1)[0].strip('"')
    return {"name": name, "cookie": f"vtt_session={val}"}


def _H(u):
    return {"cookie": u["cookie"]}


def _state(client, u, code):
    r = client.get(f"/api/rooms/{code}/state", headers=_H(u))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    from app import ratelimit
    ratelimit._hits.clear()
    yield


@pytest.fixture()
def client():
    return TestClient(main.app)


def _room_with_pc(client, tag):
    dm = _user(client, f"dm{tag}")
    pl = _user(client, f"pl{tag}")
    code = client.post("/api/rooms", json={"name": tag}, headers=_H(dm)).json()["code"]
    assert client.post("/api/rooms/join", json={"code": code}, headers=_H(pl)).status_code == 200
    ch = client.post("/api/characters", headers=_H(pl), json={
        "name": f"Char{tag}", "race": "Human", "char_class": "Fighter", "level": 5,
        "stats": {"str": 16, "dex": 14, "con": 16, "int": 10, "wis": 12, "cha": 10},
        "hp": 30, "max_hp": 30}).json()
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=_H(pl))
    return dm, pl, code


def test_player_grid_holds_the_visible_ring_around_own_token(client):
    dm, pl, code = _room_with_pc(client, "Ring")
    ds, ps = _state(client, dm, code), _state(client, pl, code)
    dg, pg = ds["grid"], ps["grid"]
    assert all(c is not None for c in dg["cells"]), "DM must receive the complete map"
    mine = next(t for t in ps["tokens"] if t["owner_user_id"] == ps["me"])
    c = dg["cell"]
    cx, cy = int(mine["x"] // c), int(mine["y"] // c)
    ring = [i for i, v in enumerate(pg["cells"]) if v is not None]
    assert ring, "fresh player payload must not be an all-unknown (black) grid"
    near = [i for i in ring
            if abs(i % dg["w"] - cx) <= mapmodel.FOG_R and abs(i // dg["w"] - cy) <= mapmodel.FOG_R]
    assert near, "the player's own token cell region must be known to that player"
    assert pg["origin"] == dg["origin"] == [0, 0]


def test_auto_grow_is_off_by_default_and_a_fixed_map_stays_stable(client):
    """The D77 verdict: no hidden automatic world growth while unverified.
    Walking a token straight to the edge must NOT grow the map..."""
    dm, pl, code = _room_with_pc(client, "NoGrow")
    assert mapmodel.AUTO_GROW is False
    st = _state(client, pl, code)
    tok_id = next(t["id"] for t in st["tokens"] if t["owner_user_id"] == st["me"])
    from tests.test_movement_fog import recv_until, ws_connect
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "move", "token_id": tok_id, "tx": 0, "ty": 13,
                      "teleport": True})
        recv_until(ws, "step", tries=60)
    grid = _state(client, pl, code)["grid"]
    assert grid["w"] == 40 and grid["origin"] == [0, 0], "edge move grew a flagged-off map"


def test_auto_grow_machinery_unchanged_behind_the_flag(client, monkeypatch):
    """...but the flag is the ONLY difference — with it on, the same move grows."""
    monkeypatch.setattr(mapmodel, "AUTO_GROW", True)
    dm, pl, code = _room_with_pc(client, "DoGrow")
    st = _state(client, pl, code)
    tok_id = next(t["id"] for t in st["tokens"] if t["owner_user_id"] == st["me"])
    from tests.test_movement_fog import recv_until, ws_connect
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "move", "token_id": tok_id, "tx": 0, "ty": 13,
                      "teleport": True})
        recv_until(ws, "map_expanded", tries=80)
    grid = _state(client, pl, code)["grid"]
    assert grid["w"] == 52 and grid["origin"][0] == -12


def test_player_sees_own_token_in_payload_regardless_of_fog(client):
    """The controlled token must survive recipient filtering — black-screen
    debugging must never start from 'my token is not even in the payload'."""
    dm, pl, code = _room_with_pc(client, "OwnTok")
    ps = _state(client, pl, code)
    mine = [t for t in ps["tokens"] if t["owner_user_id"] == ps["me"]]
    assert len(mine) == 1
    assert mine[0]["x"] > 0 and mine[0]["y"] > 0
