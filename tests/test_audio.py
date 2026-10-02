import time
import uuid

import pytest
from starlette.testclient import TestClient

from app import ratelimit
from app.main import app
from app.room import audio


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


def prime(*sockets):
    for ws in sockets:
        recv_until(ws, "presence", tries=6)
    time.sleep(0.1)


def room_with_dm_and_player(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Audio"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    return dm, player, code


def room_with_two_players(client):
    dm, p1, p2 = reg(client, "dm"), reg(client, "one"), reg(client, "two")
    code = client.post("/api/rooms", json={"name": "Audio"}, headers=H(dm)).json()["code"]
    join_room(client, p1, code)
    join_room(client, p2, code)
    return dm, p1, p2, code


def member_id(client, u, code, username):
    return next(m["user_id"] for m in state_of(client, u, code)["members"]
                if m["username"] == username)


def test_audio_url_parsing_accepts_safe_hosts_and_builds_embeds():
    yt = audio.parse_audio_source("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert yt == {
        "kind": "youtube",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "embed": "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0&modestbranding=1&playsinline=1",
    }
    sp = audio.parse_audio_source("https://open.spotify.com/track/6WRG1I2PVWdd9xEPz4dNhE")
    assert sp["kind"] == "spotify"
    assert sp["embed"].startswith("https://open.spotify.com/embed/track/")
    d = audio.parse_audio_source("/uploads/heartbeat.ogg")
    assert d["kind"] == "direct" and d["url"] == "/uploads/heartbeat.ogg"


def test_audio_url_parsing_rejects_unsafe_urls():
    assert audio.parse_audio_source("javascript:alert(1)") is None
    evil = audio.parse_audio_source("https://evil.com/watch?v=dQw4w9WgXcQ")
    assert evil is not None and evil["kind"] == "direct" and evil["embed"] == ""
    assert audio.parse_audio_source("https://youtube.com@evil.com/watch?v=dQw4w9WgXcQ") is None
    assert audio.parse_audio_source("https:///watch?v=dQw4w9WgXcQ") is None
    assert audio.parse_audio_source("https://open.spotify.com/track/short") is None
    assert audio.parse_audio_source("https://youtube.com/watch?v=too-short") is None
    assert audio.parse_audio_source("https://example.com/a b.mp3") is None


def test_soundboard_requires_direct_urls_and_is_private_to_owner(client):
    a, b, _ = room_with_dm_and_player(client)
    bad = client.post("/api/sounds", headers=H(a), json={
        "name": "Bad", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert bad.status_code == 400
    ok = client.post("/api/sounds", headers=H(a), json={
        "name": "Drip", "url": "https://example.invalid/drip.mp3", "category": "sfx"})
    assert ok.status_code == 200, ok.text
    sid = ok.json()["id"]
    assert sid not in {s["id"] for s in client.get("/api/sounds", headers=H(b)).json()}
    assert client.delete(f"/api/sounds/{sid}", headers=H(b)).status_code == 404
    assert client.delete(f"/api/sounds/{sid}", headers=H(a)).status_code == 200


def test_dm_can_add_play_and_stop_room_ambience(client):
    dm, player, code = room_with_dm_and_player(client)
    with ws_connect(client, player, code) as pws, ws_connect(client, dm, code) as dws:
        prime(dws, pws)
        dws.send_json({"type": "audio_add", "title": "Rain",
                       "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                       "category": "ambience"})
        recv_until(dws, "ambience")
        st = recv_until(pws, "ambience")["payload"]
        assert st["sources"][0]["title"] == "Rain"
        assert st["sources"][0]["embed"].startswith("https://www.youtube-nocookie.com/")
        sid = st["sources"][0]["id"]

        dws.send_json({"type": "audio_play", "source_id": sid})
        recv_until(dws, "ambience")
        st = recv_until(pws, "ambience")["payload"]
        assert st["current_id"] == sid and st["playing"] is True
        assert state_of(client, player, code)["audio"]["playing"] is True

        dws.send_json({"type": "audio_stop"})
        recv_until(dws, "ambience")
        st = recv_until(pws, "ambience")["payload"]
        assert st["current_id"] is None and st["playing"] is False


def test_players_cannot_control_ambience(client):
    dm, player, code = room_with_dm_and_player(client)
    with ws_connect(client, dm, code) as dws, ws_connect(client, player, code) as pws:
        prime(dws, pws)
        pws.send_json({"type": "audio_add", "url": "https://example.com/evil.mp3"})
        assert recv_until(pws, "error")["payload"]["msg"] == "DM only"
    assert state_of(client, dm, code)["audio"]["sources"] == []


def test_selective_sound_trigger_only_reaches_selected_player(client):
    dm, p1, p2, code = room_with_two_players(client)
    p1_id = member_id(client, dm, code, p1["name"])
    snd = client.post("/api/sounds", headers=H(dm), json={
        "name": "Bell", "url": "https://example.invalid/bell.mp3"})
    assert snd.status_code == 200
    sid = snd.json()["id"]
    with ws_connect(client, p1, code) as a, ws_connect(client, p2, code) as b, \
            ws_connect(client, dm, code) as d:
        prime(d, a, b)
        d.send_json({"type": "sound_trigger", "sound_id": sid, "target": p1_id})
        d.send_json({"type": "ping", "x": 0, "y": 0})
        a_events = drain_until(a, "ping")
        b_events = drain_until(b, "ping")
        assert sum(1 for e in a_events if e["kind"] == "sound") == 1
        assert sum(1 for e in b_events if e["kind"] == "sound") == 0
        assert a_events[-1]["kind"] == "ping" and b_events[-1]["kind"] == "ping"


def test_malformed_audio_source_is_rejected_before_persistence(client):
    dm, player, code = room_with_dm_and_player(client)
    with ws_connect(client, player, code) as pws, ws_connect(client, dm, code) as dws:
        prime(dws, pws)
        dws.send_json({"type": "audio_add", "title": "Bad", "url": "javascript:alert(1)"})
        err = recv_until(dws, "error")["payload"]
        assert "audio url" in err["msg"].lower()
    assert state_of(client, dm, code)["audio"]["sources"] == []
