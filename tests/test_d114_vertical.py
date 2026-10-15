"""D114 (Sprint 43) Phase 3: the vertical token VOLUME.

A token keeps ONE home plane + footprint; it gains a vertical body:
`height_ft` (physical vertical extent; blank = the size-category DEFAULT, a
backward-compat house-rule default, NEVER a ceiling) and `elevation_ft`
(its under-edge above the standing surface; 0 = grounded). Legacy tokens
(NULL/0) behave exactly as before. The body is derived in one place
(`app/vertical.py` + `floors.token_*`). This phase is the data model, server
validation, persistence/reload and leak-safe serialisation only — cross-plane
presence is gated by openings in Phase 4/5, so nothing here lets a body "reach"
another plane by itself.
"""
import pytest
from starlette.testclient import TestClient

from app import db, floors, vertical, main
from tests.test_movement_fog import base_room, state_of, ws_connect, recv_until


@pytest.fixture()
def client():
    return TestClient(main.app)


def ptoken(client, player, code):
    st = state_of(client, player, code)
    return next(t["id"] for t in st["tokens"] if t.get("owner_user_id") == st["me"])


def set_height(client, user, code, token_id, expect="token_height", **fields):
    with ws_connect(client, user, code) as ws:
        ws.send_json({"type": "token_height", "token_id": token_id, **fields})
        if expect:
            return recv_until(ws, expect)["payload"]
        return None


# --------------------------------------------------------------------------- #
# 1. legacy tokens: no height fields set, default geometry, one plane
# --------------------------------------------------------------------------- #

def test_legacy_token_carries_no_height_and_spans_one_level(client):
    dm, player, code, ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    tok = db.q1("SELECT * FROM tokens WHERE room_id=?", (rid,))
    assert tok is not None
    assert tok.get("height_ft") is None                       # column present, unset
    assert (tok.get("elevation_ft") or 0) == 0
    assert vertical.token_height_ft(tok) == 5                 # Medium default (house rule)
    assert vertical.token_elevation_ft(tok) == 0
    assert floors.token_levels_spanned(rid, tok) == {0}       # one 10 ft band, no more
    assert floors.token_top_ft(rid, tok) == floors.token_base_ft(rid, tok) + 5


# --------------------------------------------------------------------------- #
# 2. owner authors a tall body; it persists across reload
# --------------------------------------------------------------------------- #

def test_owner_sets_height_and_it_reloads(client):
    dm, player, code, ch = base_room(client)
    tok = ptoken(client, player, code)
    ev = set_height(client, player, code, tok, height_ft=30, elevation_ft=10)
    assert ev == {"token_id": tok, "height_ft": 30, "elevation_ft": 10}
    row = db.q1("SELECT height_ft, elevation_ft FROM tokens WHERE id=?", (tok,))
    assert row["height_ft"] == 30 and row["elevation_ft"] == 10
    # reload (fresh /state) still carries it → real persistence, not a memory blip
    st = next(t for t in state_of(client, player, code)["tokens"] if t["id"] == tok)
    assert st["height_ft"] == 30 and st["elevation_ft"] == 10
    rid = db.q1("SELECT room_id FROM tokens WHERE id=?", (tok,))["room_id"]
    tokrow = db.q1("SELECT * FROM tokens WHERE id=?", (tok,))
    assert floors.token_base_ft(rid, tokrow) == 10            # elevation on the ground plane
    assert floors.token_top_ft(rid, tokrow) == 40             # base + 30 ft body
    assert floors.token_levels_spanned(rid, tokrow) == {1, 2, 3}


# --------------------------------------------------------------------------- #
# 3. server validation — a DEFAULT is not a ceiling; garbage cannot slip through
# --------------------------------------------------------------------------- #

def test_height_validation_clamps_to_a_technical_band(client):
    dm, player, code, ch = base_room(client)
    tok = ptoken(client, player, code)
    ev = set_height(client, player, code, tok, height_ft=99999, elevation_ft=-50)
    assert ev["height_ft"] == vertical.MAX_HEIGHT_FT          # a huge authored body clamps, not rejected
    assert ev["elevation_ft"] == 0                            # below-surface is not modelled
    # blank height falls back to the size DEFAULT (column NULL), not a hard 0
    ev2 = set_height(client, player, code, tok, height_ft=None)
    assert ev2["height_ft"] is None
    tokrow = db.q1("SELECT * FROM tokens WHERE id=?", (tok,))
    assert vertical.token_height_ft(tokrow) == 5              # Medium default again


# --------------------------------------------------------------------------- #
# 4. authority — only owner or DM, never another member
# --------------------------------------------------------------------------- #

def test_non_owner_member_cannot_edit_height(client):
    from tests.test_movement_fog import reg, join_room, make_char
    dm, player, code, ch = base_room(client)
    tok = ptoken(client, player, code)
    other = reg(client, "other")
    join_room(client, other, code)
    make_char(client, other)
    with ws_connect(client, other, code) as ws:
        ws.send_json({"type": "token_height", "token_id": tok, "height_ft": 40})
        assert recv_until(ws, "error", fail_on_error=False)["payload"]["msg"] == "Not your token"
    # the DM may, however, author anyone's body
    assert set_height(client, dm, code, tok, height_ft=40)["height_ft"] == 40


# --------------------------------------------------------------------------- #
# 5. leak parity — an unowned NPC's vertical body never reaches a plain player
# --------------------------------------------------------------------------- #

def test_hidden_npc_vertical_body_is_stripped(client):
    from app.room import visibility as V
    npc = {"id": 9, "label": "Tarrasque", "character_id": None, "owner_user_id": None,
           "controller_user_id": 7, "size": "Gargantuan", "height_ft": 20,
           "elevation_ft": 5, "floor": "Upper", "fw": 4, "fh": 4, "x": 1, "y": 1,
           "color": "#111111"}
    add_player = {k: v for k, v in npc.items()}
    V._hidden_strip(add_player, npc)
    assert "height_ft" not in add_player and "elevation_ft" not in add_player
    # the OPERATOR of that NPC carries the identical shape on both channels
    op = V._player_add_for(npc, {k: v for k, v in npc.items()}, 7)
    assert op.get("height_ft") == 20 and op.get("elevation_ft") == 5
    assert V._snapshot(npc, 7).get("height_ft") == 20         # operator ghost keeps it
    assert "height_ft" not in V._snapshot(npc, 999)           # a stranger never learns it
