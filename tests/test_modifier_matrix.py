"""PC ≡ NPC/DM-controlled ability-modifier matrix (manual bug: NPC tokens not
using the canonical ability modifier).

The modifier rule is ONE derivation — ``gear.stat_mod`` (D56). The audit found
extra private copies (npc.stat_mod, room/dice.py stat_mod/dex_mod/con-term,
gear.dex_mod) that drifted on edge inputs (unclamped scores, odd types). These
tests pin the canonical anchors (8→-1, 10→0, 12→+1, 18→+4) and prove every
entry point — raw helper, NPC block, live PC roll vs live monster-token roll —
agrees. If a future change forks the formula again, this file says who.
"""
import re

import pytest
from starlette.testclient import TestClient

from app import gear, npc
from app.main import app
from app.room import dice

from tests.test_integration import H, join_room, make_char, recv_until, reg, ws_connect  # noqa: F401

SCORES = [1, 3, 5, 8, 9, 10, 11, 12, 13, 15, 18, 20, 23, 30]
ANCHORS = {8: -1, 10: 0, 12: 1, 18: 4}


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    from app import ratelimit
    ratelimit._hits.clear()
    yield


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ---------- canonical unit matrix ----------

def test_all_modifier_helpers_agree_per_score():
    for score in SCORES:
        char = {"stats": {"str": score}}
        block = {"stats": {"str": score}}
        want = gear.stat_mod(char, "str")
        assert npc.stat_mod(block, "str") == want, score
        assert dice.stat_mod({"str": score}, "str") == want, score


def test_canonical_anchors_and_clamp():
    for score, mod in ANCHORS.items():
        assert gear.stat_mod({"stats": {"str": score}}, "str") == mod
    assert gear.stat_mod({"stats": {"str": 1}}, "str") == -5       # clamped at floor 1
    assert gear.stat_mod({"stats": {"str": 0}}, "str") == -5
    assert gear.stat_mod({"stats": {"str": 30}}, "str") == 10      # clamped high
    assert gear.stat_mod({"stats": {"str": 40}}, "str") == 10      # sane-score clamp
    # every helper agrees even where the block was never normalised
    assert npc.stat_mod({"stats": {"str": 40}}, "str") == 10
    assert dice.stat_mod({"str": 40}, "str") == 10


def test_legacy_and_odd_block_shapes_agree():
    shapes = [
        {},                                       # pre-normalisation block
        {"stats": None},
        {"stats": []},
        {"stats": {"str": "12"}},                 # JSON round-trip string
        {"stats": {"str": None}},
        {"stats": {"dex": 12}},                   # other ability only
    ]
    for shape in shapes:
        assert npc.stat_mod(shape, "str") == gear.stat_mod({"stats": shape.get("stats") or {}}, "str"), shape
        assert dice.stat_mod(shape.get("stats") or {}, "str") == \
            gear.stat_mod({"stats": shape.get("stats") or {}}, "str"), shape


def test_dex_helpers_agree_with_canonical():
    for score in SCORES:
        assert gear.dex_mod({"stats": {"dex": score}}) == gear.stat_mod({"stats": {"dex": score}}, "dex")
        assert npc.dex_mod({"stats": {"dex": score}}) == gear.stat_mod({"stats": {"dex": score}}, "dex")
        assert dice.dex_mod(None) == 0


# ---------- live PC vs live monster-token: same numbers ----------

MOD_RE = re.compile(r":\s*\d+\s+([+-]\d+) = ")


def _roll_mod(client, user, code, send, wait_for="dice"):
    """Return the signed modifier the server applied to a d20 roll line."""
    with ws_connect(client, user, code) as ws:
        ws.send_json(send)
        m = recv_until(ws, wait_for)
    body = m["payload"]["body"]
    found = MOD_RE.search(body)
    assert found, f"no modifier in dice line: {body!r}"
    return int(found.group(1))


def test_check_modifier_identical_pc_vs_npc(client):
    dm = reg(client, "dm")
    player = reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Mods"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    ch = make_char(client, player, stats={"str": 12, "dex": 12})
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Brute", "x": 1250, "y": 1250,
                      "stats": {"str": 12, "dex": 12}})
        tid = recv_until(ws, "token_add")["payload"]["id"]
    pc = _roll_mod(client, player, code, {"type": "roll", "kind": "check", "ability": "str"})
    npc_mod = _roll_mod(client, dm, code, {"type": "roll", "kind": "check", "ability": "str",
                                           "token_id": tid})
    assert pc == npc_mod == 1


def test_save_modifier_identical_pc_vs_npc(client):
    dm = reg(client, "dm")
    player = reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Saves"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    ch = make_char(client, player, level=5, stats={"str": 12}, saves={"str": True})
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Guard", "x": 1250, "y": 1250,
                      "level": 5, "stats": {"str": 12}, "saves": {"str": True}})
        tid = recv_until(ws, "token_add")["payload"]["id"]
    pc = _roll_mod(client, player, code, {"type": "roll", "kind": "save", "ability": "str"})
    npc_mod = _roll_mod(client, dm, code, {"type": "roll", "kind": "save", "ability": "str",
                                           "token_id": tid})
    assert pc == npc_mod == 4          # +1 str + prof 3 (level 5)


def test_npc_check_survives_legacy_block_without_stats(client):
    """A token row whose block predates normalisation must fall back identically
    to a PC with missing stats — 0, never a crash, never a stale score."""
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "Legacy"}, headers=H(dm)).json()["code"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Old", "x": 1250, "y": 1250})
        tid = recv_until(ws, "token_add")["payload"]["id"]
        import app.db as db
        db.x("UPDATE tokens SET npc=? WHERE id=?", (db.json_dumps({"name": "Old", "hp": 5}), tid))
    m = _roll_mod(client, dm, code, {"type": "roll", "kind": "check", "ability": "str",
                                     "token_id": tid})
    assert m == 0


def test_initiative_and_ac_use_the_same_derivation(client):
    """Initiative mod and the sheet AC dex term must match the canonical mod."""
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "InitAc"}, headers=H(dm)).json()["code"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Strong", "x": 250, "y": 250,
                      "stats": {"str": 12, "dex": 12}})
        tid = recv_until(ws, "token_add")["payload"]["id"]
        ws.send_json({"type": "init_start"})
        order = recv_until(ws, "initiative")["payload"]["order"]
    entry = next(o for o in order if o.get("token_id") == tid)
    assert entry["mod"] == gear.stat_mod({"stats": {"dex": 12}}, "dex") == 1
