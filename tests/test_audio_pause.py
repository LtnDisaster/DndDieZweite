"""Sprint 8 (P7): pause is a distinct audio state (current_id kept)."""
import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app
from test_movement_fog import base_room, recv_until, ws_connect


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def get_audio(code):
    from app.room.audio import load_state
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    raw = db.q1("SELECT audio_json FROM room_state WHERE room_id=?", (rid,))["audio_json"]
    return load_state(raw)


def test_pause_keeps_source_resume_replays(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "audio_add", "title": "Tavern",
                      "url": "https://open.spotify.com/track/" + "A" * 22})
        recv_until(ws, "ambience")
        sid = get_audio(code)["sources"][0]["id"]
        ws.send_json({"type": "audio_play", "source_id": sid})
        ev = recv_until(ws, "ambience")
        assert ev["payload"]["playing"] is True and ev["payload"]["current_id"] == sid

        ws.send_json({"type": "audio_pause"})
        ev = recv_until(ws, "ambience")
        assert ev["payload"]["playing"] is False
        assert ev["payload"]["current_id"] == sid, "pause must keep current source"

        ws.send_json({"type": "audio_play", "source_id": sid})
        ev = recv_until(ws, "ambience")
        assert ev["payload"]["playing"] is True and ev["payload"]["current_id"] == sid

        # stop stays a distinct, source-clearing action:
        ws.send_json({"type": "audio_stop"})
        ev = recv_until(ws, "ambience")
        assert ev["payload"]["current_id"] is None and ev["payload"]["playing"] is False
    with ws_connect(client, player, code) as ws2:
        ws2.send_json({"type": "audio_pause"})
        assert recv_until(ws2, "error")["payload"]["msg"] == "DM only"
