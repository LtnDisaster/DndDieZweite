"""End-to-end integration tests over REST + WebSocket using Starlette's TestClient.

Design notes (verified empirically before writing):
- A single ``TestClient(app)`` is shared by all "users"; an explicit ``Cookie``
  request header overrides the client's cookie jar, so multiple identities coexist.
- WebSocket auth is passed via a ``headers={"cookie": ...}`` dict.
- ``broadcast``/``send_to`` are awaited on the socket's own loop, so these tests
  need no server lifespan / ``net.LOOP``: a bare ``TestClient`` (no ``with``) is used
  and REST ``notify`` (which does need LOOP) is intentionally not relied upon here.
- The DB file is shared for the whole session; usernames are unique per call.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import ratelimit
from app.main import app


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    """Auth endpoints rate-limit by client host ('testclient'); clear between tests."""
    ratelimit._hits.clear()
    yield


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ---------- helpers ----------

def reg(client, tag):
    name = f"{tag}{uuid.uuid4().hex[:8]}"
    r = client.post("/api/register", json={"username": name, "password": "secret123"})
    assert r.status_code == 200, r.text
    val = r.headers["set-cookie"].split("vtt_session=", 1)[1].split(";", 1)[0].strip('"')
    return {"name": name, "cookie": f"vtt_session={val}"}


def H(u, extra=None):
    h = {"cookie": u["cookie"]}
    if extra:
        h.update(extra)
    return h


def make_char(client, u, **kw):
    body = {
        "name": kw.get("name", "Hero"), "race": "H", "char_class": "Fighter", "level": kw.get("level", 1),
        "stats": kw.get("stats", {"str": 16, "dex": 12, "con": 14, "int": 10, "wis": 10, "cha": 10}),
        "hp": kw.get("hp", 10), "max_hp": kw.get("max_hp", 50), "ac": kw.get("ac", 15),
        "speed": 30, "notes": kw.get("notes", ""), "weapons": kw.get("weapons", []),
        "items": kw.get("items", []),
        "skills": kw.get("skills", {}), "spells": kw.get("spells", []),
        "spell_slots": kw.get("spell_slots", {}),
    }
    r = client.post("/api/characters", json=body, headers=H(u))
    assert r.status_code == 200, r.text
    return r.json()


def join_room(client, u, code):
    r = client.post("/api/rooms/join", json={"code": code}, headers=H(u))
    assert r.status_code == 200, r.text


def state_of(client, u, code):
    r = client.get(f"/api/rooms/{code}/state", headers=H(u))
    assert r.status_code == 200, r.text
    return r.json()


def ws_connect(client, u, code):
    return client.websocket_connect(f"/ws/{code}", headers={"cookie": u["cookie"]})


def recv_until(ws, kind, tries=12):
    """Read events until one of ``kind``; ignore interleaved presence/snapshot/etc."""
    seen = []
    for _ in range(tries):
        ev = ws.receive_json()
        seen.append(ev.get("kind"))
        if ev.get("kind") == kind:
            return ev
    raise AssertionError(f"never saw kind={kind!r}; saw {seen}")


# ---------- auth / authz ----------

def test_auth_flows(client):
    assert client.get("/api/me").status_code == 401

    u = reg(client, "auth")
    me = client.get("/api/me", headers=H(u))
    assert me.status_code == 200 and me.json()["username"] == u["name"]

    # wrong password
    assert client.post("/api/login", json={"username": u["name"], "password": "WRONGpw"}).status_code == 401
    # correct password re-issues a cookie
    ok = client.post("/api/login", json={"username": u["name"], "password": "secret123"})
    assert ok.status_code == 200 and "vtt_session" in ok.headers.get("set-cookie", "")
    # duplicate username
    assert client.post("/api/register", json={"username": u["name"], "password": "secret123"}).status_code == 409
    # invalid username charset
    assert client.post("/api/register", json={"username": "bad name!!", "password": "secret123"}).status_code == 400
    # too-short password fails schema validation
    assert client.post("/api/register", json={"username": "okname", "password": "x"}).status_code == 422


def test_membership_and_kick(client):
    dm, player, other = reg(client, "dm"), reg(client, "pl"), reg(client, "ot")
    code = client.post("/api/rooms", json={"name": "KickRoom"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    join_room(client, other, code)

    # outsider cannot read state
    assert client.get(f"/api/rooms/{code}/state", headers=H(other)).status_code == 200  # other joined
    outsider = reg(client, "outs")
    assert client.get(f"/api/rooms/{code}/state", headers=H(outsider)).status_code == 403

    pl_state = state_of(client, player, code)
    other_id = next(m["user_id"] for m in pl_state["members"] if m["username"] == other["name"])
    assert client.delete(f"/api/rooms/{code}/members/{other_id}", headers=H(player)).status_code == 403

    # DM kicks player -> player no longer a member
    pl_id = next(m["user_id"] for m in state_of(client, dm, code)["members"]
                 if m["username"] == player["name"])
    assert client.delete(f"/api/rooms/{code}/members/{pl_id}", headers=H(dm)).status_code == 200
    assert client.get(f"/api/rooms/{code}/state", headers=H(player)).status_code == 403
    # DM cannot kick self
    dm_id = next(m["user_id"] for m in state_of(client, dm, code)["members"] if m["role"] == "dm")
    assert client.delete(f"/api/rooms/{code}/members/{dm_id}", headers=H(dm)).status_code == 400


# ---------- hidden info (notes + unidentified-magic masking) ----------

def test_hidden_info_masking(client):
    dm, a, b = reg(client, "dm"), reg(client, "pa"), reg(client, "pb")
    code = client.post("/api/rooms", json={"name": "MaskRoom"}, headers=H(dm)).json()["code"]
    join_room(client, a, code); join_room(client, b, code)

    secret = "SECRET: hidden tunnel + 200gp cache"
    ca = make_char(client, a, name="Aria", notes=secret, items=[
        {"id": "ring1", "name": "Ring of Feather Fall", "kind": "other", "magic": True,
         "identified": False, "desc": "Falls slowly."},
    ])
    make_char(client, b, name="Bran", notes="Bran private")
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ca["id"]}, headers=H(a))

    # A sees own notes fully
    a_state = state_of(client, a, code)
    a_self = next(m["char"] for m in a_state["members"] if m["char"] and m["char"]["name"] == "Aria")
    assert a_self["notes"] == secret
    assert a_self["items"][0]["name"] == "Ring of Feather Fall"

    # B sees A masked: notes stripped + magic item masked
    b_state = state_of(client, b, code)
    a_for_b = next(m["char"] for m in b_state["members"] if m["char"] and m["char"]["name"] == "Aria")
    assert a_for_b["notes"] == ""
    assert a_for_b["items"][0]["name"] == "Unidentified item"
    assert a_for_b["items"][0]["desc"] == "A mysterious item."
    assert a_for_b["items"][0]["unidentified"] is True

    # DM is NOT masked (sees the real item), even though it is still unidentified.
    dm_state = state_of(client, dm, code)
    a_for_dm = next(m["char"] for m in dm_state["members"] if m["char"] and m["char"]["name"] == "Aria")
    assert a_for_dm["notes"] == secret
    assert a_for_dm["items"][0]["name"] == "Ring of Feather Fall"
    assert a_for_dm["items"][0]["desc"] == "Falls slowly."
    assert a_for_dm["items"][0]["magic"] is True and a_for_dm["items"][0]["identified"] is False


# ---------- WebSocket guards, malformed messages, chat ----------

def test_ws_dm_only_guard(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Wsguard"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "map_edit", "map": {"w": 10, "h": 8, "cell": 50,
                                                  "cells": [0] * 80, "explored": [0] * 80,
                                                  "traps": [], "loot": []}})
        ev = recv_until(ws, "error")
    assert ev["payload"]["msg"] == "DM only"


def test_ws_malformed_then_chat(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Mal"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    with ws_connect(client, player, code) as ws:
        ws.send_text("this is not json {{{")     # non-JSON -> ignored
        ws.send_json([1, 2, 3])                    # JSON but not a dict -> ignored
        ws.send_json({"type": "does_not_exist"})   # unknown type -> ignored
        ws.send_json({"type": "chat", "text": "alive"})
        ev = recv_until(ws, "chat")
    assert ev["payload"]["text"] == "alive"


def test_ws_map_edit_dm_ok(client):
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "EditMap"}, headers=H(dm)).json()["code"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": {"w": 12, "h": 10, "cell": 50,
                                                  "cells": [0] * 120, "explored": [0] * 120,
                                                  "traps": [], "loot": []}})
        recv_until(ws, "map_changed")
    assert state_of(client, dm, code)["grid"]["w"] == 12


# ---------- LOS / fog / token visibility ----------

def test_visibility_and_fog(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Vis"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    ch = make_char(client, player, name="Scout", notes="peek")
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))

    # DM places an NPC far from the player's token via the WS hub.
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "FarGoblin", "x": 1900, "y": 1200})
        recv_until(ws, "token_add")

    p_state = state_of(client, player, code)
    d_state = state_of(client, dm, code)

    # Player only sees their own token; the far NPC is hidden.
    assert any(t["owner_user_id"] == p_state["me"] for t in p_state["tokens"])
    assert all(t["owner_user_id"] == p_state["me"] for t in p_state["tokens"])
    assert "FarGoblin" not in [t["label"] for t in p_state["tokens"]]

    # DM sees the NPC.
    assert "FarGoblin" in [t["label"] for t in d_state["tokens"]]

    # Fog: DM grid fully revealed; player grid has unrevealed (None) cells.
    p_none = sum(1 for c in p_state["grid"]["cells"] if c is None)
    d_none = sum(1 for c in d_state["grid"]["cells"] if c is None)
    assert d_none == 0
    assert p_none > 0


# ---------- items: atomic potion use + attunement cap ----------

def test_use_item_atomic(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "UseItem"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    ch = make_char(client, player, name="Dancer", hp=10, max_hp=50, items=[
        {"id": "pot1", "name": "Healing Potion", "kind": "potion", "heal": "2d4+2",
         "charges": 1, "identified": True},
    ])
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))
    tok = next(t for t in state_of(client, player, code)["tokens"] if t["owner_user_id"] == state_of(client, player, code)["me"])

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "use_item", "token_id": tok["id"], "item_id": "pot1"})
        recv_until(ws, "whisper")

    after = state_of(client, player, code)
    me_char = next(m["char"] for m in after["members"] if m["user_id"] == after["me"] and m["char"])
    assert me_char["hp"] > 10
    assert me_char["items"][0]["charges"] == 0


def test_attunement_cap(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Attune"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    items = [{"id": f"ring{i}", "name": f"Ring {i}", "kind": "other", "magic": True,
              "identified": True, "attunable": True} for i in range(4)]
    ch = make_char(client, player, name="Attuner", items=items)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))

    with ws_connect(client, player, code) as ws:
        for i in range(3):
            ws.send_json({"type": "attune", "char_id": ch["id"], "item_id": f"ring{i}"})
        ws.send_json({"type": "attune", "char_id": ch["id"], "item_id": "ring3"})  # 4th -> refused
        ev = recv_until(ws, "whisper")
    assert "at most" in ev["payload"]["text"]

    final = next(m["char"] for m in state_of(client, player, code)["members"]
                 if m["user_id"] == state_of(client, player, code)["me"] and m["char"])
    assert sum(1 for i in final["items"] if i["attuned"]) == 3


# ---------- initiative: round-based fighting phase ----------

def test_initiative_rounds(client):
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "Rounds"}, headers=H(dm)).json()["code"]
    ch = make_char(client, dm, name="Leader")
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(dm))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Goblin"})     # 2nd combatant so active can advance
        recv_until(ws, "token_add")
        ws.send_json({"type": "init_start"})
        ev = recv_until(ws, "initiative")
        assert ev["payload"]["combat"] is True and ev["payload"]["round"] == 1 and ev["payload"]["active"] == 0
        ws.send_json({"type": "init_next"})
        assert recv_until(ws, "initiative")["payload"]["active"] == 1
        ws.send_json({"type": "init_end_round"})
        ev = recv_until(ws, "initiative")
        assert ev["payload"]["round"] == 2 and ev["payload"]["active"] == 0
        ws.send_json({"type": "init_end"})
        ev = recv_until(ws, "initiative")
        assert ev["payload"]["combat"] is False and ev["payload"]["round"] == 0


# ---------- skills + spellcasting (slots, gating) ----------

def test_skill_check_and_cast(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Cast"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    ch = make_char(
        client, player, name="Wisty", level=3,
        stats={"str": 10, "dex": 12, "con": 12, "int": 12, "wis": 18, "cha": 10},
        skills={"perception": 1},
        items=[{"id": "bk", "name": "Grimoire", "kind": "spellbook", "magic": True, "identified": True}],
        spells=[{"id": "fb", "name": "Fire Bolt", "level": 1, "cast": "attack", "ability": "wis", "dmg": "3d10"}],
        spell_slots={"1": {"max": 2, "used": 0}},
    )
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))

    # gating flag reaches the client state
    st = state_of(client, player, code)
    me_char = next(m["char"] for m in st["members"] if m["user_id"] == st["me"] and m["char"])
    assert me_char["has_spellbook"] is True

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "skill", "skill": "perception"})
        assert "Perception" in recv_until(ws, "dice")["payload"]["text"]
        ws.send_json({"type": "cast", "spell_id": "fb"})          # slot 1 used
        assert "Fire Bolt" in recv_until(ws, "dice")["payload"]["text"]
        ws.send_json({"type": "cast", "spell_id": "fb"})          # slot 2 used
        recv_until(ws, "dice")
        ws.send_json({"type": "cast", "spell_id": "fb"})          # 3rd -> none left
        assert "No 1-level" in recv_until(ws, "error")["payload"]["msg"]

    st = state_of(client, player, code)
    me_char = next(m["char"] for m in st["members"] if m["user_id"] == st["me"] and m["char"])
    assert me_char["spell_slots"]["1"]["used"] == 2 and me_char["spell_slots"]["1"]["max"] == 2


# ---------- traps: place via map_edit, trigger by walking ----------

def test_trap_placement_and_trigger(client):
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "Traps"}, headers=H(dm)).json()["code"]
    ch = make_char(client, dm, name="Walker")
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(dm))
    st = state_of(client, dm, code)
    tok_id = next(t for t in st["tokens"] if t["owner_user_id"] == st["me"])["id"]
    w, h, cell = 40, 26, 50
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": {
            "w": w, "h": h, "cell": cell, "cells": [0] * (w * h), "explored": [0] * (w * h),
            "traps": [{"id": "t1", "x": 8, "y": 7, "label": "Pit", "dc": 20, "dmg": "1d1", "discovered": False}],
            "loot": []}})
        recv_until(ws, "map_changed")
        ws.send_json({"type": "move", "token_id": tok_id, "tx": 8, "ty": 7, "teleport": False})
        assert "Pit" in recv_until(ws, "whisper", tries=25)["payload"]["text"]

    # trap persisted as discovered in the map
    mp = client.get(f"/api/rooms/{code}/state", headers=H(dm)).json()
    assert mp["grid"]["traps"] and mp["grid"]["traps"][0]["discovered"] is True
