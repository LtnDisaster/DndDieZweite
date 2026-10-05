"""Sprint 9 (P2/P3/P5): deployment hygiene.

Cookie flags and when X-Forwarded-Proto may be trusted, WebSocket Origin
enforcement, uploads living in the persistent VTT_DATA_DIR tree (surviving
container replacement — the /uploads URL contract stays), and the health
endpoint that the Docker HEALTHCHECK polls.
"""
import os

import pytest
from starlette.testclient import WebSocketDisconnect, TestClient

from app import auth, db
from app.main import app
from test_movement_fog import base_room


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ---------- session cookie ----------

def test_login_cookie_is_httponly_lax_and_plain_by_default(client):
    r = client.post("/api/register", json={"username": "hyg1", "password": "secret123"})
    sc = r.headers["set-cookie"]
    assert "HttpOnly" in sc and "samesite" in sc.lower() and "lax" in sc.lower()
    assert "Secure" not in sc            # plain http dev box: no Secure flag


def test_secure_flag_forced_or_under_trusted_proxy(client, monkeypatch):
    monkeypatch.setenv("VTT_COOKIE_SECURE", "1")
    r = client.post("/api/register", json={"username": "hyg2", "password": "secret123"})
    assert "Secure" in r.headers["set-cookie"]

    monkeypatch.delenv("VTT_COOKIE_SECURE")
    monkeypatch.setenv("VTT_TRUST_PROXY", "0")
    r = client.post("/api/register", json={"username": "hyg3", "password": "secret123"},
                    headers={"x-forwarded-proto": "https"})
    # untrusted: a spoofed header on a direct connection must NOT set Secure
    assert "Secure" not in r.headers["set-cookie"]

    monkeypatch.setenv("VTT_TRUST_PROXY", "1")
    r = client.post("/api/register", json={"username": "hyg4", "password": "secret123"},
                    headers={"x-forwarded-proto": "https"})
    assert "Secure" in r.headers["set-cookie"]


# ---------- WebSocket origin gate ----------

def _ws_connect(client, user, code, origin=None):
    headers = {"cookie": user["cookie"]}
    if origin:
        headers["origin"] = origin
    return client.websocket_connect(f"/ws/{code}", headers=headers)


def test_ws_rejects_cross_origin_and_accepts_same_origin(client):
    dm, player, code, ch = base_room(client)
    with pytest.raises((WebSocketDisconnect, RuntimeError)):
        with _ws_connect(client, player, code, origin="http://evil.example"):
            pass
    with _ws_connect(client, player, code, origin="http://testserver"):
        pass   # same-origin (TestClient host) must work normally


def test_ws_honours_allowed_origins_env(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    monkeypatch.setenv("VTT_ALLOWED_ORIGINS", "https://vtt.example.org")
    with _ws_connect(client, player, code, origin="https://vtt.example.org"):
        pass


# ---------- persistent uploads ----------

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 48


def test_upload_lands_under_data_dir_and_serves_same_url(client):
    dm, player, code, ch = base_room(client)
    r = client.put(f"/api/rooms/{code}/map?name=keep_me",
                   headers={"cookie": dm["cookie"]}, content=PNG)
    assert r.status_code == 200
    url = r.json()["map"]
    assert url.startswith("/uploads/")
    fname = url.removeprefix("/uploads/")
    path = os.path.join(db.DATA_DIR, "uploads", fname)
    assert os.path.isfile(path), "uploads must live under VTT_DATA_DIR"
    assert not os.path.exists(os.path.join("app", "static", "uploads", fname)), \
        "must no longer write into the replaceable app tree"
    got = client.get(url)
    assert got.status_code == 200 and got.content == PNG


def test_health_endpoint_ok(client):
    assert client.get("/api/health").json() == {"ok": True}
