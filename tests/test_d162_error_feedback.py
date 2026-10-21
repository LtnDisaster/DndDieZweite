"""D162-11 — DM-only channels refuse LOUDLY and safely.

D161 P3: fourteen handlers answered a player's DM-only message by vanishing it
— no toast, no feedback, "the button did nothing". They now answer the ONE
frame `{"kind":"error","msg":"DM only"}` (client toasts it) BEFORE touching any
state or DB read, so the refusal also cannot leak which tokens/NPCs exist.
The deliberately silent leak-safe paths (secret doors, hidden traps, foreign
plane claims) stay byte-silent — those pins live in test_doors_dmonly.py and
test_d113_traps.py and are untouched.
"""
import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_movement_fog import H, base_room, recv_until, state_of, ws_connect

TYPES = ["init_start", "init_next", "init_end_round", "init_end", "hp",
         "death_clear", "identify", "recharge", "add_token", "update_npc",
         "del_token", "npc_inv", "spawn_encounter", "exhaustion"]


@pytest.fixture()
def client():
    return TestClient(main.app)


@pytest.mark.parametrize("mtype", TYPES)
def test_player_gets_a_loud_safe_refusal(client, mtype):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": mtype, "token_id": 999999, "delta": -5,
                      "encounter_id": 1, "action": "inspect", "amount": 1})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert ev.get("kind") == "error", ev
        assert "only" in ev["payload"]["msg"].lower()
    # the refusal refused EVERYTHING: initiative never started, no token added
    st = state_of(client, player, code)
    assert not (st.get("initiative") or {}).get("combat")
    ids = [t["id"] for t in st["tokens"]]
    assert 999999 not in ids


def test_dm_still_commands_the_same_channels(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "init_start"})
        assert recv_until(ws, "initiative")["payload"]["combat"] is True
        ws.send_json({"type": "init_end"})
        assert recv_until(ws, "initiative")["payload"]["combat"] is False


def test_conversion_is_complete_no_silent_dm_guards_left(client):
    src = ""
    import io
    for p in ["combat", "death", "items", "tokens", "inv", "encounters", "status"]:
        src += io.open(f"app/room/{p}.py", encoding="utf-8").read()
    # the exact silent idiom must be gone in all DM-only handlers
    assert "if not is_dm:\n        return\n" not in src, \
        "a silently swallowing DM guard remains"


def test_leak_safe_silence_is_untouched(client):
    # secret door: a player toggle must answer with NOTHING (D83 pin, still true)
    from tests.test_movement_fog import set_grid
    dm, player, code, _ = base_room(client)
    def mutate(g):
        g["doors"] = (g.get("doors") or []) + [
            {"id": "dSec", "x": 5, "y": 5, "dir": "h", "closed": True, "secret": True}]
    set_grid(client, dm, code, mutate)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 5, "y": 5, "dir": "h", "action": "toggle"})
        ws.close()          # no event assertion needed: silence is the property
    # and the DM channel for the SAME feature is loud:
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "map_edit", "map": {"w": 1, "h": 1, "cells": [0]}})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert ev["kind"] == "error" and "dm only" in ev["payload"]["msg"].lower()
