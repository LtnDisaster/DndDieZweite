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
        "spell_slots": kw.get("spell_slots", {}), "saves": kw.get("saves", {}),
        "defenses": kw.get("defenses", {}), "resources": kw.get("resources", []),
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

    # B sees A as the D93 tactical allow-list: no notes, no items, no stats —
    # the whole private half of the row is gone, not just the masked fields.
    b_state = state_of(client, b, code)
    a_for_b = next(m["char"] for m in b_state["members"] if m["char"] and m["char"]["name"] == "Aria")
    assert "notes" not in a_for_b and "items" not in a_for_b and "stats" not in a_for_b
    assert a_for_b["name"] == "Aria" and "ac_total" in a_for_b and "hp" in a_for_b

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


# ---------- game log visibility ----------

def _has_completed_roll(messages):
    return any(m["type"] == "dice" and " = " in m["body"] for m in messages)


def _has_blind_request(messages):
    return any(m["type"] == "dice" and "blind" in m["body"].lower()
               and "requested" in m["body"].lower() for m in messages)


def test_game_log_public_and_self_visibility(client):
    dm, player, other = reg(client, "dm"), reg(client, "pl"), reg(client, "ot")
    r = client.post("/api/rooms", json={"name": "LogVis"}, headers=H(dm))
    assert "code" in r.json(), (r.status_code, r.text)
    code = r.json()["code"]
    join_room(client, player, code); join_room(client, other, code)

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "expr": "1d20", "visibility": "public"})
        recv_until(ws, "dice")
        ws.send_json({"type": "roll", "expr": "1d20", "visibility": "self"})
        recv_until(ws, "dice")

    public_room = code
    pl_msgs = state_of(client, player, public_room)["messages"]
    dm_msgs = state_of(client, dm, public_room)["messages"]
    other_msgs = state_of(client, other, public_room)["messages"]
    assert _has_completed_roll(pl_msgs) and _has_completed_roll(dm_msgs) and _has_completed_roll(other_msgs)


def test_game_log_dm_and_blind_visibility(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "HiddenVis"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)

    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "roll", "expr": "1d20", "visibility": "dm"})
        recv_until(ws, "dice")
    assert _has_completed_roll(state_of(client, dm, code)["messages"])
    assert not _has_completed_roll(state_of(client, player, code)["messages"])

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "expr": "1d20", "visibility": "blind"})
        ev = recv_until(ws, "dice")
        body = ev["payload"]["text"].lower()
        assert "blind" in body and "requested" in body
    pl_msgs = state_of(client, player, code)["messages"]
    dm_msgs = state_of(client, dm, code)["messages"]
    assert _has_blind_request(pl_msgs) and not _has_completed_roll(pl_msgs)
    assert _has_completed_roll(dm_msgs)


def test_non_dm_cannot_choose_dm_roll_visibility(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "VisGuard"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "expr": "1d20", "visibility": "dm"})
        recv_until(ws, "dice")
    pl_msgs = state_of(client, player, code)["messages"]
    dm_msgs = state_of(client, dm, code)["messages"]
    assert _has_completed_roll(pl_msgs) and _has_completed_roll(dm_msgs)


def _latest_dice_body(messages):
    for m in reversed(messages):
        if m["type"] == "dice":
            return m["body"]
    return ""


def test_saving_throws_use_server_saved_proficiency(client, monkeypatch):
    import app.room.dice as D

    monkeypatch.setattr(D, "do_roll",
                        lambda expr, adv: {"expr": expr, "rolls": [5], "kept": 5, "mod": 0,
                                           "total": 5, "adv": adv})
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "Saves"}, headers=H(dm)).json()["code"]
    ch = make_char(client, dm, stats={"dex": 10}, level=1)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(dm))
    tok_id = next(t for t in state_of(client, dm, code)["tokens"]
                  if t.get("character_id") == ch["id"])["id"]

    r = client.put(f"/api/characters/{ch['id']}", headers=H(dm),
                   json={"name": ch["name"], "stats": {"dex": 10}, "level": 1,
                         "hp": 10, "max_hp": 10, "saves": {"dex": True}})
    assert r.status_code == 200 and r.json()["saves"]["dex"] is True
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "roll", "kind": "save", "ability": "dex", "token_id": tok_id,
                      "prof": False})
        recv_until(ws, "dice")
    assert "+2 = 7" in _latest_dice_body(state_of(client, dm, code)["messages"])

    client.put(f"/api/characters/{ch['id']}", headers=H(dm),
               json={"name": ch["name"], "stats": {"dex": 10}, "level": 1,
                     "hp": 10, "max_hp": 10, "saves": {}})
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "roll", "kind": "save", "ability": "dex", "token_id": tok_id,
                      "prof": True})
        recv_until(ws, "dice")
    assert "+0 = 5" in _latest_dice_body(state_of(client, dm, code)["messages"])


def test_npc_saving_throws_use_saved_proficiency(client, monkeypatch):
    import app.room.dice as D

    monkeypatch.setattr(D, "do_roll",
                        lambda expr, adv: {"expr": expr, "rolls": [5], "kept": 5, "mod": 0,
                                           "total": 5, "adv": adv})
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "NpcSaves"}, headers=H(dm)).json()["code"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Brute", "color": "#c39",
                      "npc": {"name": "Brute", "level": 1, "stats": {"dex": 20},
                              "saves": {"dex": True}, "hp": 20, "max_hp": 20, "ac": 13}})
        recv_until(ws, "token_add")
    tok_id = next(t["id"] for t in state_of(client, dm, code)["tokens"] if t["label"] == "Brute")
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "roll", "kind": "save", "ability": "dex", "token_id": tok_id,
                      "prof": False})
        recv_until(ws, "dice")
    assert "+7 = 12" in _latest_dice_body(state_of(client, dm, code)["messages"])


def _me_char(client, user, code):
    s = state_of(client, user, code)
    return next(m["char"] for m in s["members"] if m["user_id"] == s["me"])


def test_rest_temp_hp_resources_and_status(client, monkeypatch):
    import app.room.dice as D

    monkeypatch.setattr(D, "do_roll",
                        lambda expr, adv: {"expr": expr, "rolls": [8], "kept_rolls": [8],
                                           "kept": 8, "mod": 0, "total": 8, "adv": adv})
    dm, player = reg(client, "dm"), reg(client, "pl")
    r = client.post("/api/rooms", json={"name": "Resting"}, headers=H(dm))
    assert r.status_code == 200, (r.status_code, r.text)
    code = r.json()["code"]
    join_room(client, player, code)
    r = client.post("/api/characters", headers=H(player), json={
        "name": "Rested", "level": 2, "stats": {"con": 10}, "hp": 10, "max_hp": 20,
        "hit_die": 8, "resources": [{"id": "feat", "name": "Feature", "current": 0,
                                      "max": 2, "reset": "short"}]})
    assert r.status_code == 200
    ch = r.json()
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))
    tok_id = next(t for t in state_of(client, player, code)["tokens"]
                  if t.get("character_id") == ch["id"])["id"]

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "temp_hp", "token_id": tok_id, "action": "grant", "amount": 5})
        recv_until(ws, "snapshot")
    c = _me_char(client, player, code)
    assert c["temp_hp"] == 5 and c["hp"] == 10

    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "hp", "token_id": tok_id, "delta": -7})
        recv_until(ws, "snapshot")
    c = _me_char(client, player, code)
    assert c["hp"] == 8 and c["temp_hp"] == 0

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "resource", "token_id": tok_id, "resource_id": "feat",
                      "action": "inc"})
        recv_until(ws, "snapshot")
    c = _me_char(client, player, code)
    assert c["resources"][0]["current"] == 1

    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "hp", "token_id": tok_id, "delta": -8})
        recv_until(ws, "snapshot")
    assert _death_state(client, player, code, ch["id"]) == {"s": 0, "f": 0, "stable": False, "dead": False}

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "short_rest", "token_id": tok_id, "hit_dice_count": 1})
        recv_until(ws, "dice")
    c = _me_char(client, player, code)
    assert c["hp"] == 8 and c["hit_dice_spent"] == 1 and c["resources"][0]["current"] == 2
    assert _death_state(client, player, code, ch["id"]) is None

    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "long_rest", "clear_conditions": False})
        recv_until(ws, "dice")
    c = _me_char(client, player, code)
    assert c["hp"] == 20 and c["max_hp"] == 20 and c["temp_hp"] == 0 and c["hit_dice_spent"] == 0

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inspiration", "token_id": tok_id})
        recv_until(ws, "snapshot")
    assert _me_char(client, player, code)["inspiration"] == 1
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "exhaustion", "token_id": tok_id, "action": "inc"})
        recv_until(ws, "snapshot")
    assert _me_char(client, player, code)["exhaustion"] == 1


def test_non_dm_cannot_change_exhaustion(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Exhaust"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    ch = make_char(client, player)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))
    tok_id = next(t for t in state_of(client, player, code)["tokens"]
                  if t.get("character_id") == ch["id"])["id"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "exhaustion", "token_id": tok_id, "level": 3})
    assert _me_char(client, player, code)["exhaustion"] == 0


def _collect_until_kind(ws, until, attempts=50):
    evs = []
    for _ in range(attempts):
        ev = ws.receive_json()
        evs.append(ev)
        if ev.get("kind") == until:
            return evs
    return evs


def test_map_pins_visibility_server_side(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Pins"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    m = {"w": 10, "h": 10, "cell": 50, "cells": [0] * 100, "explored": [0] * 100,
         "traps": [], "loot": [], "doors": [],
         "pins": [{"id": "secret", "x": 1, "y": 1, "title": "Secret", "visibility": "dm"},
                  {"id": "town", "x": 2, "y": 2, "title": "Town", "visibility": "players"}]}
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": m})
        recv_until(ws, "map_changed")
    assert {p["id"] for p in state_of(client, dm, code)["grid"]["pins"]} == {"secret", "town"}
    assert [p["id"] for p in state_of(client, player, code)["grid"]["pins"]] == ["town"]


def test_pings_are_live_and_rate_limited(client):
    dm, p1, p2 = reg(client, "dm"), reg(client, "one"), reg(client, "two")
    code = client.post("/api/rooms", json={"name": "Pings"}, headers=H(dm)).json()["code"]
    join_room(client, p1, code); join_room(client, p2, code)
    with ws_connect(client, p1, code) as a, ws_connect(client, p2, code) as b:
        a.send_json({"type": "ping", "x": 2, "y": 3, "color": "#f1c40f"})
        ev = recv_until(b, "ping")["payload"]
        assert (ev["x"], ev["y"]) == (2, 3) and ev["color"] == "#f1c40f"
        recv_until(a, "ping")
        for _ in range(8):
            a.send_json({"type": "ping", "x": 1, "y": 1})
        a.send_json({"type": "chat", "text": "done"})
        got = _collect_until_kind(b, "chat")
        assert sum(1 for ev in got if ev.get("kind") == "ping") <= 6


def test_encounter_templates_are_private_and_spawn_creates_tokens(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Encounters"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    c = client.post("/api/creatures", headers=H(dm), json={
        "name": "Wolf", "level": 1, "stats": {"str": 14}, "hp": 11, "max_hp": 11,
        "ac": 12, "speed": 30})
    assert c.status_code == 200
    creature = c.json()
    enc = client.post("/api/encounters", headers=H(dm), json={
        "name": "Wolf Ambush", "notes": "three wolves", "entries": [
            {"creature_id": creature["id"], "quantity": 3}]})
    assert enc.status_code == 200
    assert len(client.get("/api/encounters", headers=H(player)).json()) == 0

    with ws_connect(client, player, code) as pws:
        pws.send_json({"type": "spawn_encounter", "encounter_id": enc.json()["id"]})
    assert len([t for t in state_of(client, dm, code)["tokens"] if t["label"].startswith("Wolf")]) == 0
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "spawn_encounter", "encounter_id": enc.json()["id"]})
    labels = sorted(t["label"] for t in state_of(client, dm, code)["tokens"] if t["label"].startswith("Wolf"))
    assert labels == ["Wolf 1", "Wolf 2", "Wolf 3"]


def test_room_journal_notes_are_visibility_filtered(client):
    dm, p1, p2 = reg(client, "dm"), reg(client, "one"), reg(client, "two")
    code = client.post("/api/rooms", json={"name": "Journal"}, headers=H(dm)).json()["code"]
    join_room(client, p1, code); join_room(client, p2, code)
    p1_id = state_of(client, p1, code)["me"]
    base = {"category": "handout", "title": "Found page", "body": "secret", "visibility": "party",
            "recipients": []}
    party = client.post(f"/api/rooms/{code}/notes", headers=H(dm), json=base).json()
    dmnote = client.post(f"/api/rooms/{code}/notes", headers=H(dm), json={**base,
        "title": "DM secret", "visibility": "dm"}).json()
    chosen = client.post(f"/api/rooms/{code}/notes", headers=H(dm), json={**base,
        "title": "Only one", "visibility": "selected", "recipients": [p1_id]}).json()

    assert [n["title"] for n in client.get(f"/api/rooms/{code}/notes", headers=H(dm)).json()] == \
        ["DM secret", "Found page", "Only one"]
    one = client.get(f"/api/rooms/{code}/notes", headers=H(p1)).json()
    assert {n["title"] for n in one} == {"Found page", "Only one"}
    assert {n["title"] for n in client.get(f"/api/rooms/{code}/notes", headers=H(p2)).json()} == {"Found page"}
    assert client.post(f"/api/rooms/{code}/notes", headers=H(p1), json=base).status_code == 403
    assert client.put(f"/api/rooms/{code}/notes/{party['id']}", headers=H(p1),
                      json={**base, "title": "changed"}).status_code == 403
    assert client.delete(f"/api/rooms/{code}/notes/{dmnote['id']}", headers=H(p1)).status_code == 403
    assert client.put(f"/api/rooms/{code}/notes/{chosen['id']}", headers=H(dm),
                      json={**chosen, "visibility": "party"}).status_code == 200
    assert {n["title"] for n in client.get(f"/api/rooms/{code}/notes", headers=H(p2)).json()} == \
        {"Found page", "Only one"}


def test_cover_reduces_attack_result_or_blocks(client, monkeypatch):
    import app.room.dice as D

    monkeypatch.setattr(D, "do_roll",
                        lambda expr, adv: {"expr": expr, "rolls": [15], "kept": 15, "mod": 0,
                                           "total": 15, "adv": adv})
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "Cover"}, headers=H(dm)).json()["code"]
    ch = make_char(client, dm, stats={"str": 18}, level=1, weapons=[
        {"name": "Sword", "ability": "str", "proficient": True, "dmg": "1d6"}])
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(dm))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "roll", "kind": "attack", "weapon": "Sword", "cover": "half"})
        recv_until(ws, "dice")
        assert "= 19" in _latest_dice_body(state_of(client, dm, code)["messages"])
        ws.send_json({"type": "roll", "kind": "attack", "weapon": "Sword", "cover": "three_quarters"})
        recv_until(ws, "dice")
        assert "= 16" in _latest_dice_body(state_of(client, dm, code)["messages"])
        ws.send_json({"type": "roll", "kind": "attack", "weapon": "Sword", "cover": "total"})
        recv_until(ws, "dice")
        assert "total cover" in _latest_dice_body(state_of(client, dm, code)["messages"])


def test_damage_types_resist_immune_and_untyped(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Damage"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    ch = make_char(client, player, name="Resistor", hp=50, max_hp=50,
                   defenses={"resist": ["fire"], "immune": ["poison"], "vulnerable": ["radiant"]})
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))
    pst = state_of(client, player, code)
    tok_id = next(t for t in pst["tokens"] if t["owner_user_id"] == pst["me"])["id"]

    def char_hp():
        return next(m["char"]["hp"] for m in state_of(client, dm, code)["members"] if m["char"])

    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "hp", "token_id": tok_id, "delta": -10, "damage_type": "fire"})
        recv_until(ws, "snapshot"); assert char_hp() == 45
        ws.send_json({"type": "hp", "token_id": tok_id, "delta": -10, "damage_type": "poison"})
        recv_until(ws, "snapshot"); assert char_hp() == 45
        ws.send_json({"type": "hp", "token_id": tok_id, "delta": -10, "damage_type": "radiant"})
        recv_until(ws, "snapshot"); assert char_hp() == 25
        ws.send_json({"type": "hp", "token_id": tok_id, "delta": -10})
        recv_until(ws, "snapshot"); assert char_hp() == 15


def test_npc_size_and_disposition_are_dm_only(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Disposition"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    ch = make_char(client, player)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))
    p_pos = next(t for t in state_of(client, player, code)["tokens"])
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Dragon", "x": p_pos["x"], "y": p_pos["y"],
                      "size": "Huge", "disposition": "hostile",
                      "npc": {"name": "Dragon", "saves": {"dex": True}, "hp": 100, "max_hp": 100}})
        recv_until(ws, "token_add")
    dm_tok = next(t for t in state_of(client, dm, code)["tokens"] if t["label"] == "Dragon")
    assert (dm_tok["size"], dm_tok["disposition"]) == ("Huge", "hostile")
    pl_tok = next(t for t in state_of(client, player, code)["tokens"] if t["label"] == "Dragon")
    assert "disposition" not in pl_tok and "size" not in pl_tok

    with ws_connect(client, player, code) as pws:
        pws.send_json({"type": "update_npc", "token_id": dm_tok["id"], "disposition": "friend"})
    assert next(t for t in state_of(client, dm, code)["tokens"] if t["label"] == "Dragon")["disposition"] == "hostile"


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


# ---------- NPC stat blocks: initiative, traps, fog, spells, visibility ----------

def test_npc_initiative_uses_dex_mod(client):
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "Init"}, headers=H(dm)).json()["code"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Nimble", "x": 250, "y": 250, "stats": {"dex": 20}})
        recv_until(ws, "token_add")
        ws.send_json({"type": "add_token", "label": "Clumsy", "x": 350, "y": 350, "stats": {"dex": 8}})
        recv_until(ws, "token_add")
        ws.send_json({"type": "init_start"})
        order = recv_until(ws, "initiative")["payload"]["order"]
    by = {o["label"]: o for o in order}
    assert by["Nimble"]["mod"] == 5       # (20-10)//2
    assert by["Clumsy"]["mod"] == -1      # (8-10)//2


def test_npc_walk_triggers_trap_without_revealing_fog(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "FogTrap"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    ch = make_char(client, player, name="Scout")            # player token lands at cell (8,6)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))
    before = state_of(client, player, code)
    p_exp_before = sum(before["grid"]["explored"])
    w, h, cell = before["grid"]["w"], before["grid"]["h"], before["grid"]["cell"]

    with ws_connect(client, dm, code) as ws:
        # NPC far from the player, so a fog reveal there would be unambiguously new.
        ws.send_json({"type": "add_token", "label": "Beast", "x": 30.5 * cell, "y": 19.5 * cell,
                      "max_hp": 20, "hp": 20, "stats": {"dex": 10}})
        tok_id = recv_until(ws, "token_add")["payload"]["id"]
        ws.send_json({"type": "map_edit", "map": {
            "w": w, "h": h, "cell": cell, "cells": [0] * (w * h), "explored": [0] * (w * h),
            "traps": [{"id": "t1", "x": 30, "y": 20, "label": "Glyph", "dc": 30, "dmg": "1d1",
                       "discovered": False}], "loot": []}})
        recv_until(ws, "map_changed")
        ws.send_json({"type": "move", "token_id": tok_id, "tx": 30, "ty": 20, "teleport": False})
        recv_until(ws, "whisper", tries=40)                 # DC30 always fails -> 1d1 damage

    npc_tok = next(t for t in state_of(client, dm, code)["tokens"] if t["label"] == "Beast")
    assert npc_tok["npc"]["hp"] == 19 and npc_tok["npc"]["max_hp"] == 20
    # NPC movement must not have lifted fog for the player
    assert sum(state_of(client, player, code)["grid"]["explored"]) == p_exp_before


def test_npc_cast_consumes_slots(client):
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "Cast"}, headers=H(dm)).json()["code"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Mage", "x": 300, "y": 300, "level": 3,
                      "spells": [{"id": "bl", "name": "Bolt", "level": 1, "cast": "attack",
                                  "ability": "int", "dmg": "2d12"}],
                      "spell_slots": {"1": {"max": 1, "used": 0}}})
        tok_id = recv_until(ws, "token_add")["payload"]["id"]
        ws.send_json({"type": "cast", "token_id": tok_id, "spell_id": "bl"})
        assert "Bolt" in recv_until(ws, "dice")["payload"]["text"]
        ws.send_json({"type": "cast", "token_id": tok_id, "spell_id": "bl"})
        assert "No 1-level" in recv_until(ws, "error")["payload"]["msg"]
    mt = next(t for t in state_of(client, dm, code)["tokens"] if t["label"] == "Mage")
    assert mt["npc"]["spell_slots"]["1"]["used"] == 1


def test_npc_stat_block_hidden_from_players(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Hide"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    ch = make_char(client, player)                          # player token at cell (8,6)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Goblin", "x": 8.5 * 50, "y": 7.5 * 50,
                      "max_hp": 7, "hp": 7, "stats": {"str": 12, "dex": 14}})   # in player's LOS
        recv_until(ws, "token_add")
    g = next(t for t in state_of(client, dm, code)["tokens"] if t["label"] == "Goblin")
    assert g["npc"] and g["npc"]["stats"]["str"] == 12       # DM sees the block
    gp = next(t for t in state_of(client, player, code)["tokens"] if t["label"] == "Goblin")
    assert gp["npc"] is None                                 # player sees the token, not the numbers


def test_player_cannot_manage_npc(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Guard"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    base = len(state_of(client, dm, code)["tokens"])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "add_token", "label": "Hacked", "x": 250, "y": 250})
        ws.send_json({"type": "cast", "token_id": 999999, "spell_id": "x"})
    assert len(state_of(client, dm, code)["tokens"]) == base   # add_token is DM-only


# ---------- conditions / status effects ----------

def test_conditions_module():
    from app import conditions as C
    assert C.clean_conds([{"k": "prone", "rounds": 2}, {"k": "PRONE"}, {"k": ""},
                          {"k": "poisoned", "rounds": -5}]) == \
        [{"k": "prone", "rounds": 2, "until": ""}, {"k": "poisoned", "rounds": 0, "until": ""}]  # dedupe, clamp
    lst = C.add([], "stunned", 3)
    assert C.add(lst, "stunned", 1) == [{"k": "stunned", "rounds": 1, "until": ""}]   # refresh, not duplicate
    out, changed = C.step_rounds([{"k": "stunned", "rounds": 1}, {"k": "prone", "rounds": 0}])
    assert changed and out == [{"k": "prone", "rounds": 0, "until": ""}]   # expired dropped, permanent kept
    assert C.step_rounds(out)[1] is False                                   # nothing left to tick
    assert C.is_concentrating([{"k": "Concentrating", "rounds": 0}])        # case-insensitive
    assert C.remove([{"k": "prone", "rounds": 0}], "PRONE") == []


def test_conditions_dm_add_and_round_expiry(client):
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "Conds"}, headers=H(dm)).json()["code"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Goblin", "x": 250, "y": 250})
        tok_id = recv_until(ws, "token_add")["payload"]["id"]
        ws.send_json({"type": "cond_add", "token_id": tok_id, "key": "prone", "rounds": 2})
        ev = recv_until(ws, "cond")["payload"]
        assert {"k": "prone", "rounds": 2, "until": ""} in ev["conds"] and ev["token_id"] == tok_id
        ws.send_json({"type": "cond_add", "token_id": tok_id, "key": "concentrating"})  # permanent
        recv_until(ws, "cond")
        ws.send_json({"type": "init_start"})
        recv_until(ws, "initiative")
        ws.send_json({"type": "init_end_round"})
        recv_until(ws, "initiative")
    g = next(t for t in state_of(client, dm, code)["tokens"] if t["label"] == "Goblin")
    cd = {c["k"]: c["rounds"] for c in g["conds"]}
    assert cd == {"prone": 1, "concentrating": 0}                          # one round ticked down, one kept
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "init_end_round"})
        recv_until(ws, "initiative")
    g = next(t for t in state_of(client, dm, code)["tokens"] if t["label"] == "Goblin")
    cd = {c["k"]: c["rounds"] for c in g["conds"]}
    assert "prone" not in cd and cd.get("concentrating") == 0              # prone expired, concentration persists


def test_conditions_player_flags_self_not_others(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Self"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    ch = make_char(client, player)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))
    with ws_connect(client, dm, code) as ws:                                # a foe in the player's LOS
        ws.send_json({"type": "add_token", "label": "Goblin", "x": 8.5 * 50, "y": 7.5 * 50})
        recv_until(ws, "token_add")
    mine = next(t for t in state_of(client, player, code)["tokens"] if t.get("character_id") == ch["id"])
    foe = next(t for t in state_of(client, player, code)["tokens"] if t["label"] == "Goblin")
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "cond_add", "token_id": mine["id"], "key": "poisoned"})
        assert {"k": "poisoned", "rounds": 0, "until": ""} in recv_until(ws, "cond")["payload"]["conds"]
        ws.send_json({"type": "cond_add", "token_id": foe["id"], "key": "prone"})  # not the player's token
        assert "Not your token" in recv_until(ws, "error")["payload"]["msg"]
    foe_after = next(t for t in state_of(client, dm, code)["tokens"] if t["label"] == "Goblin")
    assert foe_after["conds"] == []                                          # forbidden write was a no-op


# ---------- death saving throws ----------

def _death_state(client, u, code, char_id):
    return next(t for t in state_of(client, u, code)["tokens"]
                if t.get("character_id") == char_id)["death"]


def test_death_save_flow(client, monkeypatch):
    import app.room.death as D

    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Dying"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    ch = make_char(client, player, hp=20, max_hp=20)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))
    tok_id = next(t for t in state_of(client, player, code)["tokens"]
                  if t.get("character_id") == ch["id"])["id"]

    def fake_do_roll(expr, adv):
        assert expr == "1d20"
        nat = rolls.pop(0)
        return {"expr": expr, "rolls": [nat], "kept": nat, "mod": 0, "total": nat, "adv": adv}

    rolls = [10, 9, 1, 20]
    monkeypatch.setattr(D, "do_roll", fake_do_roll)

    with ws_connect(client, dm, code) as ws:                                 # damage reduces to 0
        ws.send_json({"type": "hp", "token_id": tok_id, "delta": -10})
        recv_until(ws, "snapshot")
        ws.send_json({"type": "hp", "token_id": tok_id, "delta": -10})
        recv_until(ws, "snapshot")
    assert _death_state(client, player, code, ch["id"]) == \
        {"s": 0, "f": 0, "stable": False, "dead": False}                     # fresh dying state

    with ws_connect(client, player, code) as ws:                             # 10 -> success
        ws.send_json({"type": "death_save", "token_id": tok_id})
        d = recv_until(ws, "death")["payload"]["death"]
        assert d == {"s": 1, "f": 0, "stable": False, "dead": False}
        ws.send_json({"type": "death_save", "token_id": tok_id})             # 9 -> one failure
        d = recv_until(ws, "death")["payload"]["death"]
        assert d == {"s": 1, "f": 1, "stable": False, "dead": False}
        ws.send_json({"type": "death_save", "token_id": tok_id})             # nat 1 -> two failures
        d = recv_until(ws, "death")["payload"]["death"]
        assert d == {"s": 1, "f": 3, "stable": False, "dead": True}
        ws.send_json({"type": "death_save", "token_id": tok_id})
        assert "Not making death saves" in recv_until(ws, "error")["payload"]["msg"]

    with ws_connect(client, dm, code) as ws:                                 # healing clears death
        ws.send_json({"type": "hp", "token_id": tok_id, "delta": 5})
        recv_until(ws, "snapshot")
    assert _death_state(client, player, code, ch["id"]) is None
    assert next(m["char"] for m in state_of(client, player, code)["members"]
                if m["user_id"] == player_id(client, player, code))["hp"] == 5

    with ws_connect(client, dm, code) as ws:                                 # drop again
        ws.send_json({"type": "hp", "token_id": tok_id, "delta": -5})
        recv_until(ws, "snapshot")
    with ws_connect(client, player, code) as ws:                             # nat 20 wakes them
        ws.send_json({"type": "death_save", "token_id": tok_id})
        assert recv_until(ws, "death")["payload"]["death"] is None
        ws.send_json({"type": "death_save", "token_id": tok_id})
        assert "Not making death saves" in recv_until(ws, "error")["payload"]["msg"]
    me = state_of(client, player, code)
    assert next(m["char"] for m in me["members"] if m["user_id"] == me["me"])["hp"] == 1


def player_id(client, user, code):
    return next(m["user_id"] for m in state_of(client, user, code)["members"]
                if m["username"] == user["name"])


def test_massive_damage_on_drop_blow_kills(client):
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "Massive"}, headers=H(dm)).json()["code"]
    ch = make_char(client, dm, hp=20, max_hp=20)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(dm))
    tok_id = next(t for t in state_of(client, dm, code)["tokens"]
                  if t.get("character_id") == ch["id"])["id"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "hp", "token_id": tok_id, "delta": -20})
        recv_until(ws, "snapshot")
    d = _death_state(client, dm, code, ch["id"])
    assert d and d["dead"] is True


def test_npns_never_make_death_saves(client):
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "NpcDown"}, headers=H(dm)).json()["code"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Brute", "x": 250, "y": 250, "max_hp": 10, "hp": 10})
        tok_id = recv_until(ws, "token_add")["payload"]["id"]
        ws.send_json({"type": "hp", "token_id": tok_id, "delta": -100})
        recv_until(ws, "snapshot")
        ws.send_json({"type": "death_save", "token_id": tok_id})             # no-op for an NPC
    t = next(t for t in state_of(client, dm, code)["tokens"] if t["label"] == "Brute")
    assert t["death"] is None and t["npc"]["hp"] == 0                        # just sits at 0 HP


# ---------- NPC attacks ----------

def test_npc_attack_resolves_vs_target_ac(client):
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "Smash"}, headers=H(dm)).json()["code"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Squire", "x": 300, "y": 300, "ac": 10})
        def_id = recv_until(ws, "token_add")["payload"]["id"]
        ws.send_json({"type": "add_token", "label": "Brute", "x": 400, "y": 300, "max_hp": 20, "hp": 20,
                      "attacks": [{"id": "bite", "name": "Bite", "to_hit": 30, "dmg": "1d6"},
                                  {"id": "roar", "name": "Roar", "dc": 12, "save": "con"}]})
        atk_id = recv_until(ws, "token_add")["payload"]["id"]
        hit = dmg = None
        for _ in range(10):                                                  # +30 hits unless a nat 1
            ws.send_json({"type": "npc_attack", "token_id": atk_id, "attack": "bite",
                          "mode": "attack", "target_id": def_id})
            hit = recv_until(ws, "dice")["payload"]["text"]
            assert "Brute" in hit and "Bite" in hit and "AC 10" in hit and ("HIT" in hit or "MISS" in hit)
            if "HIT" in hit:
                dmg = recv_until(ws, "dice")["payload"]["text"]              # a hit rolls damage
                break
    assert dmg is not None, "+30 never hit across 10 tries"
    assert "Bite damage" in dmg


def test_npc_attack_targetless_damage_and_dc(client):
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "Smash2"}, headers=H(dm)).json()["code"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Brute", "x": 400, "y": 300,
                      "attacks": [{"id": "bite", "name": "Bite", "to_hit": 5, "dmg": "1d6"},
                                  {"id": "roar", "name": "Roar", "dc": 12, "save": "con"}]})
        atk_id = recv_until(ws, "token_add")["payload"]["id"]
        ws.send_json({"type": "npc_attack", "token_id": atk_id, "attack": "bite", "mode": "attack"})
        t1 = recv_until(ws, "dice")["payload"]["text"]
        ws.send_json({"type": "npc_attack", "token_id": atk_id, "attack": "bite", "mode": "damage"})
        t2 = recv_until(ws, "dice")["payload"]["text"]
        ws.send_json({"type": "npc_attack", "token_id": atk_id, "attack": "roar", "mode": "dc"})
        t3 = recv_until(ws, "dice")["payload"]["text"]
    assert "Brute" in t1 and "AC" not in t1                                   # no target → just a to-hit roll
    assert "Bite damage" in t2
    assert "Roar" in t3 and "DC 12" in t3 and "CON" in t3


def test_non_dm_cannot_use_npc_attack(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Guard2"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Brute", "x": 8.5 * 50, "y": 7.5 * 50,
                      "attacks": [{"id": "bite", "name": "Bite", "to_hit": 5, "dmg": "1d6"}]})
        recv_until(ws, "token_add")
    foe = next(t for t in state_of(client, dm, code)["tokens"] if t["label"] == "Brute")
    kinds = []
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "npc_attack", "token_id": foe["id"], "attack": "bite", "mode": "attack"})
        ws.send_json({"type": "chat", "text": "hi"})
        for _ in range(12):
            ev = ws.receive_json()
            kinds.append(ev.get("kind"))
            if ev.get("kind") == "chat":
                break
    assert "dice" not in kinds                                                 # player can't drive a monster


# ---------- doors ----------

def test_door_toggle_permissions(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Doors"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    ch = make_char(client, player)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))
    grid = state_of(client, dm, code)["grid"]
    grid["doors"] = [
        {"id": "adj", "x": 8, "y": 6, "dir": "v", "closed": False, "locked": False},  # beside the player
        {"id": "lock", "x": 2, "y": 2, "dir": "v", "closed": True, "locked": True},   # far, locked
        {"id": "far", "x": 20, "y": 20, "dir": "v", "closed": False, "locked": False}  # far, unlocked
    ]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": grid})
        recv_until(ws, "map_changed")

    def door(door_id):
        return next(d for d in state_of(client, dm, code)["grid"]["doors"] if d["id"] == door_id)

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 8, "y": 6, "dir": "v", "action": "toggle"})
        recv_until(ws, "map_changed")
        assert door("adj")["closed"] is True                                   # player shut the door beside them
        ws.send_json({"type": "door", "x": 2, "y": 2, "dir": "v"})
        assert "locked" in recv_until(ws, "error")["payload"]["msg"]           # can't open a locked door
        ws.send_json({"type": "door", "x": 20, "y": 20, "dir": "v"})
        assert "Walk up" in recv_until(ws, "error")["payload"]["msg"]          # must be adjacent
    with ws_connect(client, dm, code) as ws:                                   # DM locks it
        ws.send_json({"type": "door", "x": 8, "y": 6, "dir": "v", "action": "set", "locked": True})
        recv_until(ws, "map_changed")
        assert door("adj")["locked"] and door("adj")["closed"]
    with ws_connect(client, player, code) as ws:                               # player now blocked
        ws.send_json({"type": "door", "x": 8, "y": 6, "dir": "v", "action": "toggle"})
        assert "locked" in recv_until(ws, "error")["payload"]["msg"]


# ---------- AoE templates (visual relay) ----------

def test_aoe_relay_is_dm_only(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "AoE"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "aoe", "shape": "circle", "x": 5, "y": 6, "size": 3, "dir": "E"})
        p = recv_until(ws, "aoe")["payload"]
        assert p["shape"] == "circle" and p["x"] == 5 and p["size"] == 3
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "aoe", "shape": "circle", "x": 5, "y": 6, "size": 3})
        assert "Only the DM" in recv_until(ws, "error")["payload"]["msg"]


# ---------- bestiary engine ----------

def test_creature_crud_and_spawn(client):
    dm, other = reg(client, "dm"), reg(client, "other")
    body = {"name": "Goblin", "level": 1, "stats": {"dex": 14}, "max_hp": 7, "hp": 7, "ac": 15,
            "speed": 30, "attacks": [{"id": "b", "name": "Bite", "to_hit": 4, "dmg": "1d6"}],
            "tags": "humanoid"}
    r = client.post("/api/creatures", json=body, headers=H(dm))
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert r.json()["block"]["attacks"][0]["to_hit"] == 4          # block normalised + stored
    assert any(c["id"] == cid for c in client.get("/api/creatures", headers=H(dm)).json())
    assert client.get("/api/creatures", headers=H(other)).json() == []          # private to the owner
    assert client.delete(f"/api/creatures/{cid}", headers=H(other)).status_code == 404
    up = dict(body, name="Goblin Boss", max_hp=20, hp=20)
    assert client.put(f"/api/creatures/{cid}", json=up, headers=H(dm)).json()["block"]["max_hp"] == 20

    code = client.post("/api/rooms", json={"name": "Spawn"}, headers=H(dm)).json()["code"]
    block = client.get("/api/creatures", headers=H(dm)).json()[0]["block"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": block["name"], "x": 250, "y": 250,
                      "level": block["level"], "stats": block["stats"], "hp": block["hp"],
                      "max_hp": block["max_hp"], "ac": block["ac"], "speed": block["speed"],
                      "attacks": block["attacks"], "spells": block["spells"],
                      "spell_slots": block["spell_slots"]})
        tid = recv_until(ws, "token_add")["payload"]["id"]
    spawned = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == tid)
    assert spawned["npc"]["attacks"][0]["name"] == "Bite"          # spawn produced a full monster
    assert client.delete(f"/api/creatures/{cid}", headers=H(dm)).json() == {"ok": True}
    assert client.get("/api/creatures", headers=H(dm)).json() == []

