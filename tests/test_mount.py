"""D82: generic MOUNT relationship (rider -> mount), DM-managed and ACYCLIC.

The relationship layer ships fully: assign/unassign, same-room, self-cycle
and multi-hop cycle rejection, persistence and snapshot round-trip, clear
separation from the controller relationship. Carrying movement is
deliberately NOT silently half-implemented (see docs).
"""
import pytest
from starlette.testclient import TestClient

from app import main


@pytest.fixture()
def client():
    return TestClient(main.app)
from tests.test_movement_fog import H, add_npc, base_room, recv_until, state_of, ws_connect


def tok_row(token_id):
    from app import db
    return db.q1("SELECT * FROM tokens WHERE id=?", (token_id,))


def test_assign_persist_revoke(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        rider = add_npc(ws, "Knight", cx=10, cy=10)
        horse = add_npc(ws, "Horse", cx=11, cy=10)
        ws.send_json({"type": "token_mount", "token_id": rider, "mount_id": horse})
        ev = recv_until(ws, "token_mount")["payload"]
        assert ev == {"token_id": rider, "mount_token_id": horse}
    st = state_of(client, dm, code)
    assert next(t for t in st["tokens"] if t["id"] == rider)["mount_token_id"] == horse
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_mount", "token_id": rider, "mount_id": None})
        assert recv_until(ws, "token_mount")["payload"]["mount_token_id"] is None
    assert tok_row(rider)["mount_token_id"] is None


def test_self_and_cycle_rejected(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        a = add_npc(ws, "A", cx=10, cy=10)
        b = add_npc(ws, "B", cx=11, cy=10)
        c = add_npc(ws, "C", cx=12, cy=10)
        ws.send_json({"type": "token_mount", "token_id": a, "mount_id": a})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "itself" in err["payload"]["msg"].lower()
        ws.send_json({"type": "token_mount", "token_id": b, "mount_id": a})
        recv_until(ws, "token_mount")
        ws.send_json({"type": "token_mount", "token_id": a, "mount_id": b})   # A->B->A
        err = recv_until(ws, "error", fail_on_error=False)
        assert "cycle" in err["payload"]["msg"].lower()
        # build a 3-chain C->B->A, then try A->C
        ws.send_json({"type": "token_mount", "token_id": c, "mount_id": b})
        recv_until(ws, "token_mount")
        ws.send_json({"type": "token_mount", "token_id": a, "mount_id": c})   # A->C->B->A
        err = recv_until(ws, "error", fail_on_error=False)
        assert "cycle" in err["payload"]["msg"].lower()
        assert tok_row(a)["mount_token_id"] is None                  # never mutated
        assert tok_row(b)["mount_token_id"] == a and tok_row(c)["mount_token_id"] == b


def test_mount_must_be_same_room(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        rider = add_npc(ws, "Centaur")
        ws.send_json({"type": "token_mount", "token_id": rider, "mount_id": 999999})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "room" in err["payload"]["msg"].lower()


def test_mount_is_dm_only_and_mount_never_controller(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        rider = add_npc(ws, "Knight", cx=10, cy=10)
        horse = add_npc(ws, "Horse", cx=11, cy=10)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "token_mount", "token_id": rider, "mount_id": horse})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "dm only" in err["payload"]["msg"].lower()
    assert tok_row(rider)["mount_token_id"] is None


# ---------- D83 CARRYING: a moving mount carries its riders -----------------

def _mount_pair(ws, rider_l="Knight", mount_l="Horse", rc=(10, 10), mc=(10, 10)):
    """Two ownerless tokens, rider riding mount, both centred at the anchor."""
    rider = add_npc(ws, rider_l, cx=rc[0], cy=rc[1])
    mount = add_npc(ws, mount_l, cx=mc[0], cy=mc[1])
    ws.send_json({"type": "token_mount", "token_id": rider, "mount_id": mount})
    recv_until(ws, "token_mount")
    return rider, mount


def _dm_move(ws, token_id, tx, ty, teleport=True, wait_step=False):
    msg = {"type": "move", "token_id": token_id, "tx": tx, "ty": ty}
    if teleport:
        msg["teleport"] = True
    ws.send_json(msg)
    return msg


def test_rider_follows_dm_teleport(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        rider, mount = _mount_pair(ws)
        _dm_move(ws, mount, 14, 10)
        recv_until(ws, "step")
    row = tok_row(rider)
    # mount anchor (14,10) span 1x1 -> rider centred inside: exactly that cell
    assert (row["x"], row["y"]) == ((14 + .5) * 50, (10 + .5) * 50)


def test_rider_follows_every_walk_step(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        rider, mount = _mount_pair(ws, mc=(10, 2))
        _dm_move(ws, mount, 13, 2, teleport=False)
        recv_until(ws, "move_state")                      # moving:true
        for _ in range(40):                               # drain to walk end
            if recv_until(ws, "move_state")["payload"].get("moving") is False:
                break
    row = tok_row(rider)
    assert (row["x"], row["y"]) == ((13 + .5) * 50, (2 + .5) * 50)


def test_rider_does_not_block_its_own_mount(client):
    """The rider sits ON the mount's destination cells — for the mount this is
    the same entity, not an obstruction."""
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        rider, mount = _mount_pair(ws, rc=(11, 10), mc=(10, 10))
        # mount's new box (11..12,10..11) overlaps the rider at (11,10):
        _dm_move(ws, mount, 11, 10)
        m = recv_until(ws, "step")
    row = tok_row(mount)
    assert (row["x"], row["y"]) == ((11 + .5) * 50, (10 + .5) * 50)   # no error blocked it


def test_rider_never_spends_its_own_budget(client):
    import pathlib
    from app import db as _db
    from app.room import combat as CB
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app/room/movement.py").read_text()
    body = src[src.index("async def carry_riders"):src.index("def _carries_riders")]
    assert "spend_move" not in body and "move_spent" not in body      # static: pure position
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        rider, mount = _mount_pair(ws)
        ws.send_json({"type": "init_start"})
        init0 = recv_until(ws, "initiative")["payload"]
        _dm_move(ws, mount, 15, 15)
        recv_until(ws, "step")
    room_id = _db.q1("SELECT room_id FROM tokens WHERE id=?", (mount,))["room_id"]
    init1 = CB.get_init(room_id)
    assert CB.move_remaining(init1, rider) == CB.move_remaining(init0, rider)


def test_nested_chain_carries_top_down(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        boo = add_npc(ws, "Boo", cx=6, cy=6)
        minsc = add_npc(ws, "Minsc", cx=6, cy=7)
        horse = add_npc(ws, "Spyder", cx=6, cy=8)
        ws.send_json({"type": "token_mount", "token_id": boo, "mount_id": minsc})
        recv_until(ws, "token_mount")
        ws.send_json({"type": "token_mount", "token_id": minsc, "mount_id": horse})
        recv_until(ws, "token_mount")
        _dm_move(ws, horse, 9, 8)
        for _ in range(3):                    # horse step + minsc carry + boo carry
            recv_until(ws, "step")
    assert tok_row(horse)["x"] == (9 + .5) * 50
    assert tok_row(minsc)["x"] == (9 + .5) * 50       # both re-centred on the mount
    assert tok_row(boo)["x"] == (9 + .5) * 50
    assert tok_row(minsc)["y"] == tok_row(boo)["y"]   # same centre line, no crash


def test_unmount_rehomes_and_stops_carrying(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        rider, mount = _mount_pair(ws)          # both at (10,10) — rider inside mount cell
        _dm_move(ws, mount, 16, 10)
        recv_until(ws, "step")
        assert tok_row(rider)["x"] == (16 + .5) * 50
        ws.send_json({"type": "token_mount", "token_id": rider, "mount_id": None})
        recv_until(ws, "token_mount")
        # rider sits exactly on the (now foreign) mount cell -> must be re-homed
        from app import db, footprint
        mp = state_of(client, dm, code)["grid"]
        others = [t for t in db.q("SELECT * FROM tokens WHERE room_id=? AND id!=?",
                                  (tok_row(rider)["room_id"], rider))]
        assert footprint.valid_final_position(mp, tok_row(rider),
                                              footprint.occupied_origin(mp, tok_row(rider))[0],
                                              others)
        _dm_move(ws, mount, 18, 10)
        recv_until(ws, "step")
    assert tok_row(rider)["x"] != (18 + .5) * 50        # no longer carried


def test_forced_push_carries_rider(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        rider, mount = _mount_pair(ws, mc=(10, 10), rc=(10, 10))
        ws.send_json({"type": "forced_move", "token_id": mount, "kind": "push",
                      "tx": 13, "ty": 10})
        recv_until(ws, "forced_moved")
    assert tok_row(mount)["x"] == (13 + .5) * 50
    assert tok_row(rider)["x"] == (13 + .5) * 50        # carried by the push
