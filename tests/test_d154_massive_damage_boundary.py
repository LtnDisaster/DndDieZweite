"""D154 — massive damage boundary (2024 SRD).

Instant death needs the damage that REMAINS after the blow drops the hero
to 0 HP to at least meet max_hp. Before this fix the server compared the
RAW delta against max_hp — so 20 damage on a full 20/20 hero (remainder 0)
was instantly lethal, and temp HP absorption counted toward the kill.

Every case is deterministic; nothing here relies on a roll.
"""
import pytest
from starlette.testclient import TestClient

from app.main import app
from tests.test_integration import (H, _death_state, make_char, reg,
                                    recv_until, state_of)
from tests.test_movement_fog import ws_connect


@pytest.fixture()
def client():
    return TestClient(app)


def _hero(client, hp, max_hp, temp=0):
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "Massive"},
                       headers=H(dm)).json()["code"]
    ch = make_char(client, dm, name="Victim", hp=hp, max_hp=max_hp)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]},
                headers=H(dm))
    tok = next(t for t in state_of(client, dm, code)["tokens"]
               if t.get("character_id") == ch["id"])
    if temp:
        with ws_connect(client, dm, code) as ws:
            ws.send_json({"type": "temp_hp", "token_id": tok["id"],
                          "action": "set", "amount": temp})
            recv_until(ws, "snapshot")
    return dm, code, ch, tok["id"]


def _hit(client, dm, code, tok_id, delta):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "hp", "token_id": tok_id, "delta": delta})
        recv_until(ws, "snapshot")


def test_exact_max_on_full_hp_only_drops(client):
    dm, code, ch, tok = _hero(client, hp=20, max_hp=20)
    _hit(client, dm, code, tok, -20)
    d = _death_state(client, dm, code, ch["id"])
    assert d and d["dead"] is False and d["s"] == 0 and d["f"] == 0


def test_one_below_massive_boundary_keeps_alive(client):
    dm, code, ch, tok = _hero(client, hp=20, max_hp=20)
    _hit(client, dm, code, tok, -39)
    d = _death_state(client, dm, code, ch["id"])
    assert d and d["dead"] is False


def test_remainder_equal_to_max_kills(client):
    dm, code, ch, tok = _hero(client, hp=20, max_hp=20)
    _hit(client, dm, code, tok, -40)
    d = _death_state(client, dm, code, ch["id"])
    assert d and d["dead"] is True and d["f"] == 3


def test_wounded_boundary_uses_remainder_not_raw(client):
    dm, code, ch, tok = _hero(client, hp=5, max_hp=20)
    _hit(client, dm, code, tok, -24)
    d = _death_state(client, dm, code, ch["id"])
    assert d and d["dead"] is False          # remainder 24-5=19 < 20
    _hit(client, dm, code, tok, -1)          # a hit AT 0 HP: fail, not massive
    d2 = _death_state(client, dm, code, ch["id"])
    assert d2 and d2["dead"] is False and d2["f"] == 1


def test_wounded_massive_boundary(client):
    dm, code, ch, tok = _hero(client, hp=5, max_hp=20)
    _hit(client, dm, code, tok, -25)
    d = _death_state(client, dm, code, ch["id"])
    assert d and d["dead"] is True           # remainder exactly 20


def test_temp_hp_absorbs_before_the_remainder_rule(client):
    # 20/20 + 10 temp: -45 -> 10 absorbed, remainder 45-10-20 = 15 < 20: alive
    dm, code, ch, tok = _hero(client, hp=20, max_hp=20, temp=10)
    _hit(client, dm, code, tok, -45)
    d = _death_state(client, dm, code, ch["id"])
    assert d and d["dead"] is False
    # a fresh hero where the post-temp remainder meets max dies: -50 -> 20
    dm2, code2, ch2, tok2 = _hero(client, hp=20, max_hp=20, temp=10)
    _hit(client, dm2, code2, tok2, -50)
    d2 = _death_state(client, dm2, code2, ch2["id"])
    assert d2 and d2["dead"] is True


def test_damage_at_zero_hp_above_max_still_kills(client):
    dm, code, ch, tok = _hero(client, hp=20, max_hp=20)
    _hit(client, dm, code, tok, -20)         # drop (not dead)
    _hit(client, dm, code, tok, -20)         # damage at 0 == max -> instant death
    d = _death_state(client, dm, code, ch["id"])
    assert d and d["dead"] is True
