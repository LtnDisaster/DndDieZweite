import time
import uuid

import pytest
from starlette.testclient import TestClient

from app import ratelimit
from app.main import app


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    ratelimit._hits.clear()
    yield


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def reg(client, tag):
    name = f"{tag}{uuid.uuid4().hex[:8]}"
    r = client.post("/api/register", json={"username": name, "password": "secret123"})
    assert r.status_code == 200, r.text
    val = r.headers["set-cookie"].split("vtt_session=", 1)[1].split(";", 1)[0].strip('"')
    return {"name": name, "cookie": f"vtt_session={val}"}


def H(u):
    return {"cookie": u["cookie"]}


def join_room(client, u, code):
    r = client.post("/api/rooms/join", json={"code": code}, headers=H(u))
    assert r.status_code == 200, r.text


def state_of(client, u, code):
    r = client.get(f"/api/rooms/{code}/state", headers=H(u))
    assert r.status_code == 200, r.text
    return r.json()


def ws_connect(client, u, code):
    return client.websocket_connect(f"/ws/{code}", headers={"cookie": u["cookie"]})


def recv_until(ws, kind, tries=20):
    seen = []
    for _ in range(tries):
        ev = ws.receive_json()
        seen.append(ev.get("kind"))
        if ev.get("kind") == kind:
            return ev
    raise AssertionError(f"never saw kind={kind!r}; saw {seen}")


def drain_until(ws, kind, tries=20):
    out = []
    for _ in range(tries):
        ev = ws.receive_json()
        out.append(ev)
        if ev.get("kind") == kind:
            return out
    raise AssertionError(f"never saw kind={kind!r}; saw {[e.get('kind') for e in out]}")


def recv_kinds(ws, kinds, tries=20):
    wanted = list(kinds)
    out = []
    for _ in range(tries):
        ev = ws.receive_json()
        out.append(ev)
        if ev.get("kind") in wanted:
            wanted.remove(ev.get("kind"))
        if not wanted:
            return out
    raise AssertionError(f"never saw all of {kinds}; saw {[e.get('kind') for e in out]}")


def prime(*sockets):
    for ws in sockets:
        recv_until(ws, "presence", tries=6)
    time.sleep(0.1)


def send_recv_pair(sender, receiver, msg, kind, sender_expect=True):
    sender.send_json(msg)
    if sender_expect:
        recv_until(sender, kind)
    ev = recv_until(receiver, kind)
    return ev["payload"]


def member_id(client, u, code, username):
    row = next(m for m in state_of(client, u, code)["members"] if m["username"] == username)
    return row["user_id"]


def three_party_room(client):
    dm, p1, p2 = reg(client, "dm"), reg(client, "one"), reg(client, "two")
    r = client.post("/api/rooms", json={"name": "Chatter"}, headers=H(dm))
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    join_room(client, p1, code)
    join_room(client, p2, code)
    return dm, p1, p2, code


def chat_texts(state):
    return [m["text"] for m in state.get("chat", [])]


def _visible_to(state, text):
    return text in chat_texts(state)


def test_global_chat_is_visible_to_everyone_and_persisted(client):
    dm, p1, p2, code = three_party_room(client)
    with ws_connect(client, dm, code) as dws, ws_connect(client, p1, code) as p1ws:
        prime(dws, p1ws)
        payload = send_recv_pair(dws, p1ws, {"type": "chat", "text": "hello party",
                                             "channel": "global"}, "chat")
        assert payload["text"] == "hello party"
        assert payload["username"] == dm["name"]
        assert payload["visibility"] == "public"
    for u in (dm, p1, p2):
        assert _visible_to(state_of(client, u, code), "hello party")


def test_player_whispers_are_visible_to_recipient_and_sender_only(client):
    dm, p1, p2, code = three_party_room(client)
    p2_id = member_id(client, p1, code, p2["name"])
    with ws_connect(client, p1, code) as p1ws, ws_connect(client, p2, code) as p2ws:
        prime(p1ws, p2ws)
        payload = send_recv_pair(
            p1ws, p2ws,
            {"type": "chat", "text": "secret player note", "channel": "whisper",
             "recipient_id": p2_id}, "chat")
        assert payload["text"] == "secret player note"
        assert payload["visibility"] == "whisper"
    assert _visible_to(state_of(client, p1, code), "secret player note")
    assert _visible_to(state_of(client, p2, code), "secret player note")
    assert not _visible_to(state_of(client, dm, code), "secret player note")


def test_dm_whispers_are_not_secretly_visible_to_uninvited_player(client):
    dm, p1, p2, code = three_party_room(client)
    p1_id = member_id(client, dm, code, p1["name"])
    with ws_connect(client, p1, code) as p1ws, ws_connect(client, dm, code) as dws:
        prime(p1ws, dws)
        payload = send_recv_pair(
            dws, p1ws,
            {"type": "chat", "text": "only for one", "channel": "whisper",
             "recipient_id": p1_id}, "chat")
        assert payload["visibility"] == "whisper"
    assert _visible_to(state_of(client, dm, code), "only for one")
    assert _visible_to(state_of(client, p1, code), "only for one")
    assert not _visible_to(state_of(client, p2, code), "only for one")


def test_dm_channel_routes_players_to_dm_and_dm_without_target_to_dm_only(client):
    dm, p1, p2, code = three_party_room(client)
    p1_id = member_id(client, dm, code, p1["name"])
    with ws_connect(client, p1, code) as p1ws, ws_connect(client, dm, code) as dws:
        prime(p1ws, dws)
        payload = send_recv_pair(p1ws, dws, {"type": "chat", "text": "psst dm",
                                             "channel": "dm"}, "chat")
        assert payload["text"] == "psst dm"
        payload = send_recv_pair(dws, p1ws, {"type": "chat", "text": "dm to one",
                                             "channel": "dm", "recipient_id": p1_id}, "chat")
        assert payload["text"] == "dm to one"
        dws.send_json({"type": "chat", "text": "dm private note", "channel": "dm"})
        assert recv_until(dws, "chat")["payload"]["text"] == "dm private note"
    assert _visible_to(state_of(client, dm, code), "psst dm")
    assert _visible_to(state_of(client, dm, code), "dm private note")
    assert _visible_to(state_of(client, p1, code), "psst dm")
    assert _visible_to(state_of(client, p1, code), "dm to one")
    assert not _visible_to(state_of(client, p2, code), "dm private note")
    assert not _visible_to(state_of(client, p2, code), "psst dm")


def test_dm_can_speak_as_persona_but_cannot_impersonate_room_member(client):
    dm, p1, p2, code = three_party_room(client)
    with ws_connect(client, p1, code) as p1ws, ws_connect(client, dm, code) as dws:
        prime(p1ws, dws)
        payload = send_recv_pair(
            dws, p1ws,
            {"type": "chat", "text": "A voice from the dark.", "channel": "global",
             "sender_kind": "persona", "persona": "The Whispering Crown"}, "chat")
        assert payload["persona"] == "The Whispering Crown"
        assert payload["sender_kind"] == "persona"
        assert payload["display_name"] == "The Whispering Crown"

        dws.send_json({"type": "chat", "text": "I am you.", "channel": "global",
                       "sender_kind": "persona", "persona": p1["name"]})
        err = recv_until(dws, "error")["payload"]
        assert "persona" in err["msg"].lower()


def test_dm_can_speak_as_npc_and_players_cannot(client):
    dm, p1, p2, code = three_party_room(client)
    with ws_connect(client, p1, code) as p1ws, ws_connect(client, dm, code) as dws:
        prime(p1ws, dws)
        dws.send_json({"type": "add_token", "label": "Goblin", "x": 100, "y": 100})
        dws.send_json({"type": "ping", "x": 2, "y": 2})
        recv_until(dws, "ping")
        recv_until(p1ws, "ping")
        tok = next(t for t in state_of(client, dm, code)["tokens"] if t["label"] == "Goblin")
        payload = send_recv_pair(
            dws, p1ws,
            {"type": "chat", "text": "Greeting!", "channel": "global",
             "sender_kind": "npc", "npc_token_id": tok["id"]}, "chat")
        assert payload["sender_kind"] == "npc"
        assert payload["persona"] == "Goblin"
        assert payload["npc_token_id"] == tok["id"]

        p1ws.send_json({"type": "chat", "text": "not your voice", "channel": "global",
                        "sender_kind": "npc", "npc_token_id": tok["id"]})
        payload = recv_until(p1ws, "chat")["payload"]
        assert payload["text"] == "not your voice"
        assert payload["sender_kind"] == "user"
        assert payload["persona"] == ""


def test_narrative_overlay_is_private_or_public_as_selected(client):
    dm, p1, p2, code = three_party_room(client)
    p1_id = member_id(client, dm, code, p1["name"])
    with ws_connect(client, p1, code) as p1ws, ws_connect(client, p2, code) as p2ws, \
            ws_connect(client, dm, code) as dws:
        prime(dws, p1ws, p2ws)
        dws.send_json({"type": "narrative", "text": "Everyone hears the bells.",
                       "target": "all", "style": "overlay"})
        dws.send_json({"type": "ping", "x": 0, "y": 0})
        p1_events = drain_until(p1ws, "ping")
        p2_events = drain_until(p2ws, "ping")
        d_events = drain_until(dws, "ping")
        for events in (p1_events, p2_events, d_events):
            narr = [e["payload"] for e in events if e.get("kind") == "narrative"]
            assert len(narr) == 1 and narr[0]["text"] == "Everyone hears the bells."
            assert narr[0]["visibility"] == "public"

        dws.send_json({"type": "narrative", "text": "Only you hear it.", "target": p1_id,
                       "style": "voice", "sender_kind": "persona",
                       "persona": "The Whisper"})
        dws.send_json({"type": "ping", "x": 0, "y": 0})
        p1_events = drain_until(p1ws, "ping")
        d_events = drain_until(dws, "ping")
        p2_events = drain_until(p2ws, "ping")
        for events in (p1_events, d_events):
            narr = [e["payload"] for e in events if e.get("kind") == "narrative"]
            assert len(narr) == 1 and narr[0]["text"] == "Only you hear it."
            assert narr[0]["persona"] == "The Whisper"
            assert narr[0]["visibility"] == "whisper"
        assert not [e for e in p2_events if e.get("kind") == "narrative"]
    p2_state = state_of(client, p2, code)
    assert _visible_to(p2_state, "Everyone hears the bells.")
    assert not _visible_to(p2_state, "Only you hear it.")
    assert _visible_to(state_of(client, dm, code), "Only you hear it.")


def test_secret_event_delivers_narrative_and_directed_sound_to_one_player(client):
    dm, p1, p2, code = three_party_room(client)
    p1_id = member_id(client, dm, code, p1["name"])
    snd = client.post("/api/sounds", headers=H(dm), json={
        "name": "Heartbeat", "url": "/uploads/heartbeat.ogg", "category": "sfx"})
    assert snd.status_code == 200, snd.text
    sid = snd.json()["id"]
    with ws_connect(client, p1, code) as p1ws, ws_connect(client, p2, code) as p2ws, \
            ws_connect(client, dm, code) as dws:
        prime(dws, p1ws, p2ws)
        dws.send_json({"type": "secret_event", "text": "The floor cracks beneath you.",
                       "target": p1_id, "sound_id": sid, "style": "overlay"})
        dws.send_json({"type": "ping", "x": 0, "y": 0})
        p1_events = drain_until(p1ws, "ping")
        d_events = drain_until(dws, "ping")
        p2_events = drain_until(p2ws, "ping")
        p1_narr = [e["payload"] for e in p1_events if e.get("kind") == "narrative"]
        p1_snd = [e["payload"] for e in p1_events if e.get("kind") == "sound"]
        assert len(p1_narr) == 1 and p1_narr[0]["text"] == "The floor cracks beneath you."
        assert len(p1_snd) == 1 and p1_snd[0]["url"] == "/uploads/heartbeat.ogg"
        assert len([e for e in d_events if e.get("kind") == "narrative"]) == 1
        assert not [e for e in d_events if e.get("kind") == "sound"]
        assert not [e for e in p2_events if e.get("kind") in ("narrative", "sound")]
    assert not _visible_to(state_of(client, p2, code), "The floor cracks beneath you.")


def test_chat_history_replay_filters_private_messages_by_role(client):
    dm, p1, p2, code = three_party_room(client)
    p1_id = member_id(client, dm, code, p1["name"])
    with ws_connect(client, dm, code) as dws:
        prime(dws)
        for msg in (
            {"type": "chat", "text": "public", "channel": "global"},
            {"type": "chat", "text": "player secret", "channel": "whisper", "recipient_id": p1_id},
            {"type": "chat", "text": "dm note", "channel": "dm"},
            {"type": "narrative", "text": "private narration", "target": p1_id,
             "style": "voice"},
        ):
            dws.send_json(msg)
            recv_until(dws, "narrative" if msg["type"] == "narrative" else "chat")
    assert _visible_to(state_of(client, dm, code), "player secret")
    assert _visible_to(state_of(client, dm, code), "dm note")
    assert _visible_to(state_of(client, dm, code), "private narration")
    p1_state = state_of(client, p1, code)
    assert _visible_to(p1_state, "public")
    assert _visible_to(p1_state, "player secret")
    assert _visible_to(p1_state, "private narration")
    assert not _visible_to(p1_state, "dm note")
    p2_state = state_of(client, p2, code)
    assert _visible_to(p2_state, "public")
    assert not _visible_to(p2_state, "player secret")
    assert not _visible_to(p2_state, "dm note")
    assert not _visible_to(p2_state, "private narration")
