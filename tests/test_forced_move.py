"""Phase 6 (D71): DM-only forced movement — push/pull/shove/knockback/throw/
teleport. Stops at the first illegal cell (wall, cliff, occupied), syncs z,
never a walk (no budget, no _walks entry, NO world growth even for players).
"""
import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app
from app.room import movement
from test_movement_fog import (add_npc, base_room, recv_until, set_grid,
                               state_of, wall_column, ws_connect)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def tok_pos(client, dm, code, tok_id):
    t = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == tok_id)
    return int(t["x"] // 50), int(t["y"] // 50), t.get("z", 0)


def test_push_moves_stops_at_wall_and_is_dm_only(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        tok = next(t["id"] for t in state_of(client, player, code)["tokens"]
                   if t.get("owner_user_id"))
        ws.send_json({"type": "move", "token_id": tok, "tx": 16, "ty": 12, "teleport": True})
        recv_until(ws, "step")
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "push", "tx": 20, "ty": 12})
        done = recv_until(ws, "forced_moved")["payload"]
        assert done["to"] == {"cx": 20, "cy": 12, "z": 0}
    assert tok_pos(client, dm, code, tok)[:2] == (20, 12)
    assert tok not in movement._walks                       # not a walk

    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "move", "token_id": tok, "tx": 16, "ty": 12, "teleport": True})
        recv_until(ws, "step")
    set_grid(client, dm, code, lambda g: wall_column(g, 19))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "shove", "tx": 24, "ty": 12})
        recv_until(ws, "forced_moved")
    assert tok_pos(client, dm, code, tok)[:2] == (18, 12)   # stopped before the wall

    with ws_connect(client, player, code) as ws:            # player cannot force
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "push", "tx": 16, "ty": 12})
        ws.send_json({"type": "chat", "text": "ping", "channel": "global"})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert "DM-only" in ev["payload"]["msg"]
    assert tok_pos(client, dm, code, tok)[:2] == (18, 12)


def test_cliff_and_occupied_stop_a_push_and_force_never_grows_the_world(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        tok = next(t["id"] for t in state_of(client, player, code)["tokens"]
                   if t.get("owner_user_id"))
        ws.send_json({"type": "move", "token_id": tok, "tx": 16, "ty": 12, "teleport": True})
        recv_until(ws, "step")
        npc = add_npc(ws, cx=22, cy=12)
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "throw", "tx": 26, "ty": 12})
        recv_until(ws, "forced_moved")
    assert tok_pos(client, dm, code, tok)[:2] == (21, 12)   # stopped before the NPC

    def cliff(g):
        for y in range(g["h"]):
            g["elev"][y * g["w"] + 17] = 3
    set_grid(client, dm, code, cliff)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "move", "token_id": npc, "tx": 16, "ty": 20, "teleport": True})
        recv_until(ws, "step")
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "knockback",
                      "tx": 16, "ty": 12})
        recv_until(ws, "forced_moved")
    assert tok_pos(client, dm, code, tok)[:2] == (18, 12)   # stopped one cell before the cliff

    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "push", "tx": 39, "ty": 12})
        recv_until(ws, "forced_moved")
    assert tok_pos(client, dm, code, tok)[:2] == (39, 12)
    g = state_of(client, dm, code)["grid"]
    assert (g["w"], g["h"]) == (40, 26)                     # even at the edge: NO growth (D67/D71)


def test_forced_teleport_respects_legality_and_z(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        tok = next(t["id"] for t in state_of(client, player, code)["tokens"]
                   if t.get("owner_user_id"))
    set_grid(client, dm, code, lambda g: (
        g["cells"].__setitem__(14 * g["w"] + 24, 1),
        [g["elev"].__setitem__(y * g["w"] + 26, 2) for y in range(g["h"])]))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "teleport",
                      "tx": 24, "ty": 14})
        ws.send_json({"type": "chat", "text": "marker", "channel": "global"})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert "cannot be moved" in ev["payload"]["msg"]
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "teleport",
                      "tx": 26, "ty": 12})
        done = recv_until(ws, "forced_moved")["payload"]
        assert done["to"]["z"] == 2
    assert tok_pos(client, dm, code, tok) == (26, 12, 2)


# ---------- D83: the operation is a reusable server-side LAYER ----------------
import inspect as _inspect
from app.room import combat as CB

tok_row = lambda tid: db.q1("SELECT * FROM tokens WHERE id=?", (tid,))

def test_handler_delegates_to_single_apply_layer():
    """No parallel ad-hoc forced paths: the WS handler validates and delegates;
    the ONLY position write lives in apply_forced_move (future traps call it
    directly — never through a client)."""
    from app.room import moveforced as MF
    src = _inspect.getsource(MF)
    assert hasattr(MF, "apply_forced_move")
    handler = src[src.index("async def handle_forced_move"):]
    assert "UPDATE tokens" not in handler            # zero writes in the handler
    assert src.count("UPDATE tokens SET x=?, y=?, z=?") == 1


def test_forced_move_consumes_no_budget(client):
    """Pushing a token never charges anyone's move ledger."""
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        victim = add_npc(ws, "Pebble", cx=10, cy=10)
        ws.send_json({"type": "init_start"})
        recv_until(ws, "initiative")
        ws.send_json({"type": "forced_move", "token_id": victim,
                      "kind": "push", "tx": 13, "ty": 10})
        recv_until(ws, "forced_moved")
    room_id = tok_row(victim)["room_id"]
    init = CB.get_init(room_id)
    t = init.get("turn") or {}
    by = (t.get("move_by") or {})
    assert all(int(e["spent"]) == 0 for e in by.values())        # nobody paid
    assert int(t.get("move_spent") or 0) == 0


def test_knock_prone_uses_the_existing_condition(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = add_npc(ws, "Thug", cx=10, cy=10)
        ws.send_json({"type": "knock_prone", "token_id": npc})
        ev = recv_until(ws, "cond")["payload"]
        assert any(c["k"].lower() == "prone" for c in ev["conds"])
        assert "prone" in tok_row(npc)["conds"].lower()
        # idempotent second knock: no second broadcast storm
        ws.send_json({"type": "knock_prone", "token_id": npc})
        ws.send_json({"type": "stand", "token_id": npc})          # DM stands it again
        ev2 = recv_until(ws, "cond")["payload"]
        assert not any(c["k"].lower() == "prone" for c in ev2["conds"])


def test_knock_prone_is_dm_only(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = add_npc(ws, "Rogue", cx=10, cy=10)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "knock_prone", "token_id": npc})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "DM only" in err["payload"]["msg"]
    assert "prone" not in (tok_row(npc)["conds"] or "").lower()
