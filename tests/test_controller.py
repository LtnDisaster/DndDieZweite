"""D82: generic token CONTROLLER relationship (companion foundation).

The DM can assign a room member as controller of a token; that member may
act through it (movement, conditions, door/object reach, its turn) exactly
per the existing owner authority — but a controller is NOT an owner and NOT
an account. Pins: assign/persist/broadcast/revoke; member-only targets;
operational authority for the controller; unrelated players stay out; the
controller always SEES the token (delivery) while fog revelation stays
owner-scoped (the companion does not lift fog for anyone).
"""
import pytest
from starlette.testclient import TestClient

from app import main


@pytest.fixture()
def client():
    return TestClient(main.app)
from tests.test_footprint_rect import tok_row
from tests.test_movement_fog import (H, add_npc, base_room, join_room, make_char,
                                     recv_until, state_of, ws_connect, reg)


def three_way(client):
    dm, ctrl, other = reg(client, "dm"), reg(client, "ctrl"), reg(client, "oth")
    code = client.post("/api/rooms", json={"name": "Companions"}, headers=H(dm)).json()["code"]
    for u in (ctrl, other):
        join_room(client, u, code)
        ch = make_char(client, u)
        client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(u))
    return dm, ctrl, other, code


def member_id(client, viewer, code, user):
    """user_id of `user` (a reg() dict) as seen in the room member list."""
    return next(m["user_id"] for m in state_of(client, viewer, code)["members"]
                if m["username"] == user["name"])


def test_assign_persists_broadcasts_and_revokes(client):
    dm, ctrl, other, code = three_way(client)
    cid = member_id(client, dm, code, ctrl)
    with ws_connect(client, dm, code) as ws:
        npc = add_npc(ws, "Rex")
        ws.send_json({"type": "token_controller", "token_id": npc, "controller_id": cid})
        ev = recv_until(ws, "token_controller")["payload"]
        assert ev == {"token_id": npc, "controller_user_id": cid}
    tok = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == npc)
    assert tok["controller_user_id"] == cid                     # survives reload
    with ws_connect(client, dm, code) as ws:                    # revoke
        ws.send_json({"type": "token_controller", "token_id": npc, "controller_id": None})
        assert recv_until(ws, "token_controller")["payload"]["controller_user_id"] is None
    tok = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == npc)
    assert tok["controller_user_id"] is None


def test_assign_is_dm_only_and_member_scoped(client):
    dm, ctrl, other, code = three_way(client)
    with ws_connect(client, dm, code) as ws:
        npc = add_npc(ws, "Guard")
    with ws_connect(client, ctrl, code) as ws:
        ws.send_json({"type": "token_controller", "token_id": npc, "controller_id": 99999})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "dm only" in err["payload"]["msg"].lower()
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_controller", "token_id": npc, "controller_id": 99999})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "member" in err["payload"]["msg"].lower()        # no fake accounts
    assert tok_row(npc)["controller_user_id"] is None


def test_controller_acts_unrelated_denied(client):
    dm, ctrl, other, code = three_way(client)
    cid = member_id(client, dm, code, ctrl)
    with ws_connect(client, dm, code) as ws:
        npc = add_npc(ws, "Rex")
        ws.send_json({"type": "token_controller", "token_id": npc, "controller_id": cid})
        recv_until(ws, "token_controller")
        # bring it into the controller's own fog-visible area first (fog rules
        # for PREVIEW/WALK are unchanged by D82 and belong to their own tests)
        ws.send_json({"type": "move", "token_id": npc, "tx": 8, "ty": 8, "teleport": True})
        recv_until(ws, "step")
    with ws_connect(client, ctrl, code) as ws:                  # controller moves it
        ws.send_json({"type": "path_preview", "token_id": npc, "tx": 8, "ty": 10})
        recv_until(ws, "path_preview")
        ws.send_json({"type": "move", "token_id": npc, "tx": 8, "ty": 10})
        recv_until(ws, "step")
        # steps are paced async tasks — wait for the walk to actually settle
        for _ in range(30):
            ev = ws.receive_json()
            if ev.get("kind") == "move_state" and not ev["payload"].get("moving"):
                break
        ws.send_json({"type": "cond_add", "token_id": npc, "key": "prone", "rounds": 1})
        recv_until(ws, "cond")
    with ws_connect(client, other, code) as ws:                 # unrelated stays out
        ws.send_json({"type": "move", "token_id": npc, "tx": 5, "ty": 5})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "own token" in err["payload"]["msg"].lower()
        ws.send_json({"type": "cond_add", "token_id": npc, "key": "prone", "rounds": 1})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "not your token" in err["payload"]["msg"].lower()
    after = tok_row(npc)
    assert (int(after["x"] // 50), int(after["y"] // 50)) == (8, 10)    # controller's move won


def test_controller_door_reach(client):
    dm, ctrl, other, code = three_way(client)
    cid = member_id(client, dm, code, ctrl)
    st = state_of(client, dm, code)
    grid = st["grid"]
    grid["doors"] = [{"id": "d1", "x": 15, "y": 12, "dir": "h", "closed": True,
                      "locked": False, "dm_only": False, "secret": False, "label": "Door"}]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": grid})
        recv_until(ws, "map_changed")
        npc = add_npc(ws, "Rex", cx=15, cy=13)                  # south of the door
        ws.send_json({"type": "token_controller", "token_id": npc, "controller_id": cid})
        recv_until(ws, "token_controller")
    with ws_connect(client, ctrl, code) as ws:
        ws.send_json({"type": "door", "x": 15, "y": 12, "dir": "h", "action": "toggle"})
        recv_until(ws, "map_changed")
    door = next(d for d in state_of(client, dm, code)["grid"]["doors"] if d["id"] == "d1")
    assert door["closed"] is False                              # companion opened it


def test_companion_visible_to_controller_but_never_lifts_fog(client):
    dm, ctrl, other, code = three_way(client)
    cid = member_id(client, dm, code, ctrl)
    with ws_connect(client, dm, code) as ws:
        npc = add_npc(ws, "Scout", cx=17, cy=17)                # deep unexplored corner
        ws.send_json({"type": "token_controller", "token_id": npc, "controller_id": cid})
        recv_until(ws, "token_controller")
    ctrl_seen = {t["id"] for t in state_of(client, ctrl, code)["tokens"]}
    oth_seen = {t["id"] for t in state_of(client, other, code)["tokens"]}
    assert npc in ctrl_seen and npc not in oth_seen             # delivery follows control
    g0 = state_of(client, other, code)["grid"]
    c0 = state_of(client, ctrl, code)["grid"]
    with ws_connect(client, ctrl, code) as ws:                  # controller walks it around
        ws.send_json({"type": "move", "token_id": npc, "tx": 16, "ty": 17})
        recv_until(ws, "step")
    g1 = state_of(client, other, code)["grid"]
    c1 = state_of(client, ctrl, code)["grid"]
    idx = lambda g, x, y: g["explored"][(y - g["origin"][1]) * g["w"] + (x - g["origin"][0])]
    assert idx(g0, 17, 17) == 0 and idx(g1, 17, 17) == 0 and idx(g1, 16, 17) == 0
    assert idx(c1, 16, 17) == 0                                 # D82: controller token
    assert idx(c1, 17, 17) == 0                                 # reveals NO fog, for anyone
    assert g1["explored"] == g0["explored"]                     # whole map untouched


def test_unassigned_npc_not_player_movable(client):
    """The relationship must not accidentally allow arbitrary NPC control."""
    dm, ctrl, other, code = three_way(client)
    with ws_connect(client, dm, code) as ws:
        npc = add_npc(ws, "Nobody's")
    with ws_connect(client, ctrl, code) as ws:
        ws.send_json({"type": "move", "token_id": npc, "tx": 16, "ty": 13})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "own token" in err["payload"]["msg"].lower()


def test_hidden_companion_leaks_no_controller(client):
    dm, ctrl, other, code = three_way(client)
    cid = member_id(client, dm, code, ctrl)
    with ws_connect(client, dm, code) as ws:
        npc = add_npc(ws, "Ghost", cx=17, cy=17)                # unseen by "other"
        ws.send_json({"type": "token_controller", "token_id": npc, "controller_id": cid})
        recv_until(ws, "token_controller")
    oth_tokens = state_of(client, other, code)["tokens"]
    assert not any(t["id"] == npc for t in oth_tokens)          # not even visible there
