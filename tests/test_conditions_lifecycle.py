"""Sprint 14 (D80): conditions wired into the combat turn lifecycle.

Pins the authoritative behavior:
  * every condition has exactly ONE clock: round ("") or own turn ("start"/
    "end") — it can never tick through both;
  * expiry happens exactly at the defined lifecycle point (turn start /
    turn end / round wrap), never earlier, never twice;
  * exploration (no combat) never advances any duration;
  * downed (0 HP) and the incapacitated family cannot move voluntarily —
    DM forced movement (moveforced) stays the separate authority path;
  * standing from prone is an explicit server operation: free outside
    combat, costs half the turn's BASE movement inside (independent of
    Dash), rejected without enough movement — prone only removed on success;
  * conditions are pure token-DB state: reconnect replays them.
"""
import pytest
from starlette.testclient import TestClient

from app import conditions as C
from app import db, main
from app.room import combat as CB
from test_movement_fog import (base_room, recv_until, state_of, ws_connect)
from test_combat_turn import my_token_id, start_combat, pass_until_mine


@pytest.fixture()
def client():
    return TestClient(main.app)


def room_id(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def conds_of(token_id):
    return C.load(db.q1("SELECT conds FROM tokens WHERE id=?", (token_id,)))


def crounds(token_id, key):
    """Countdown of one condition right now, or None when it is gone."""
    return next((c["rounds"] for c in conds_of(token_id) if c["k"] == key), None)


def cond_add(client, who, code, token_id, key, rounds=0, until=""):
    with ws_connect(client, who, code) as ws:
        ws.send_json({"type": "cond_add", "token_id": token_id,
                      "key": key, "rounds": rounds, "until": until})
        return recv_until(ws, "cond")["payload"]["conds"]


def cond_remove(client, who, code, token_id, key):
    with ws_connect(client, who, code) as ws:
        ws.send_json({"type": "cond_remove", "token_id": token_id, "key": key})
        return recv_until(ws, "cond")["payload"]["conds"]


def stand(client, who, code, token_id, want=True):
    """want=True -> returns the cond broadcast; want=False -> returns the error event."""
    with ws_connect(client, who, code) as ws:
        ws.send_json({"type": "stand", "token_id": token_id})
        ev = recv_until(ws, "cond" if want else "error", fail_on_error=want)
        return ev["payload"]


def init_next(client, dm, code):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "init_next"})
        recv_until(ws, "initiative")
    return CB.get_init(db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"])


def walk_to(client, player, code, token_id, tx, ty):
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": token_id, "tx": tx, "ty": ty,
                      "teleport": False})
        recv_until(ws, "move_state")
        recv_until(ws, "move_state")


# ---------- the round clock: unchanged semantics, exact expiry ----------

def test_round_clock_expires_exactly_after_its_rounds(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    cond_add(client, dm, code, mine, "poisoned", rounds=2)
    start_combat(client, dm, code)
    init = CB.get_init(room_id(code))
    seen = []
    for _ in range(8):
        if init["round"] >= 3:
            break
        init = init_next(client, dm, code)
        seen.append((init["round"], crounds(mine, "poisoned")))
    # ticks only at the two wraps: round 2 -> 1, round 3 -> gone; nothing before
    first_wrap = next(i for i, (r, _) in enumerate(seen) if r == 2)
    assert all(v == 2 for (r, v) in seen[:first_wrap])
    assert seen[first_wrap][1] == 1
    assert all(v == 1 for (r, v) in seen[first_wrap:
                                        next(i for i, (r, _) in enumerate(seen) if r == 3)])
    assert crounds(mine, "poisoned") is None


# ---------- the turn clocks: exact lifecycle point, one tick per unit ----------

def test_turn_start_anchor_ticks_only_on_own_turn_starts(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    init = pass_until_mine(client, dm, code, mine)
    cond_add(client, dm, code, mine, "poisoned", rounds=2, until="start")
    obs = []                                     # (round, my-turn?, rounds now)
    for _ in range(8):
        if init["round"] >= 3 and init["turn"]["token_id"] == mine:
            break
        init = init_next(client, dm, code)
        obs.append((init["round"], init["turn"]["token_id"] == mine,
                    crounds(mine, "poisoned")))
    my_start_r2 = next(i for i, (r, m, _) in enumerate(obs) if r == 2 and m)
    assert all(v == 2 for (_, _, v) in obs[:my_start_r2])          # round wrap did NOT tick it
    assert obs[my_start_r2][2] == 1                                # exactly one tick at my start
    assert all(v in (1, None) for (_, _, v) in obs[my_start_r2 + 1:])
    last = next(i for i, (r, m, _) in enumerate(obs) if r == 3 and m)
    assert obs[last][2] is None                                    # expired at my 2nd start


def test_turn_end_anchor_expires_at_end_of_own_turn(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, mine)      # my turn is active
    cond_add(client, dm, code, mine, "frightened", rounds=1, until="end")
    assert crounds(mine, "frightened") == 1      # NOT gone mid-turn
    init_next(client, dm, code)                  # my turn ENDS -> hook fires
    assert crounds(mine, "frightened") is None


def test_one_clock_per_condition_no_double_stepping(client):
    """Round-clock and turn-clock conditions coexist on ONE token; at every
    single lifecycle step each advances exactly when (and only when) its own
    hook fires: blinded (rounds=3) only at wraps, frightened (rounds=2,
    until=end) only at the ends of MY turn."""
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, mine)
    cond_add(client, dm, code, mine, "blinded", rounds=3)                  # ticks at wrap
    cond_add(client, dm, code, mine, "frightened", rounds=2, until="end")  # ticks at MY turn end
    init = CB.get_init(room_id(code))
    round_old = init["round"]
    r_old, f_old = crounds(mine, "blinded"), crounds(mine, "frightened")
    for _ in range(9):
        leaving_was_mine = init["turn"]["token_id"] == mine
        init = init_next(client, dm, code)
        wrapped = init["round"] > round_old
        r_new, f_new = crounds(mine, "blinded"), crounds(mine, "frightened")
        if r_old is None:
            assert r_new is None
        else:
            assert r_new == (None if (wrapped and r_old == 1)
                             else (r_old - 1 if wrapped else r_old))
        if f_old is None:
            assert f_new is None
        else:
            assert f_new == (None if (leaving_was_mine and f_old == 1)
                             else (f_old - 1 if leaving_was_mine else f_old))
        round_old, r_old, f_old = init["round"], r_new, f_new
    assert crounds(mine, "frightened") is None        # gone after 2 of my turn ends
    assert crounds(mine, "blinded") is None           # ≥3 wraps inside 9 two-slot steps


# ---------- durations never tick outside combat ----------

def test_exploration_never_advances_durations(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    cond_add(client, dm, code, mine, "poisoned", rounds=2)
    cond_add(client, dm, code, mine, "blinded", rounds=2, until="start")
    walk_to(client, player, code, mine, 20, 6)          # a long walk, no combat
    assert crounds(mine, "poisoned") == 2
    assert crounds(mine, "blinded") == 2


# ---------- downed / incapacitated: voluntary movement blocked server-side ----------

def test_downed_cannot_move_but_forced_movement_still_works(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "hp", "token_id": mine, "delta": -999})
        recv_until(ws, "snapshot")
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": mine, "tx": 10, "ty": 6})
        err = recv_until(ws, "error", fail_on_error=False)["payload"]["msg"]
    assert "downed" in err.lower()
    tok = db.q1("SELECT x, y FROM tokens WHERE id=?", (mine,))
    assert (int(tok["x"] // 50), int(tok["y"] // 50)) == (8, 6)      # did not move
    with ws_connect(client, dm, code) as ws:                          # DM authority path
        ws.send_json({"type": "forced_move", "token_id": mine, "kind": "teleport",
                      "tx": 12, "ty": 6})
        recv_until(ws, "forced_moved")
    tok = db.q1("SELECT x, y FROM tokens WHERE id=?", (mine,))
    assert (int(tok["x"] // 50), int(tok["y"] // 50)) == (12, 6)


def test_incapacitated_family_blocks_and_unblocks_movement(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    conds = cond_add(client, player, code, mine, "unconscious")
    assert any(c["k"] == "unconscious" for c in conds)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": mine, "tx": 10, "ty": 6})
        err = recv_until(ws, "error", fail_on_error=False)["payload"]["msg"]
    assert "unconscious" in err.lower()
    cond_remove(client, player, code, mine, "unconscious")
    walk_to(client, player, code, mine, 10, 6)                        # moves again
    tok = db.q1("SELECT x, y FROM tokens WHERE id=?", (mine,))
    assert (int(tok["x"] // 50), int(tok["y"] // 50)) == (10, 6)


# ---------- prone / Stand Up ----------

def test_stand_outside_combat_is_free_and_moves_nothing(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    err = stand(client, player, code, mine, want=False)["msg"]
    assert "not prone" in err.lower()                                 # legal-only button/server
    cond_add(client, player, code, mine, "prone")
    pos_before = db.q1("SELECT x, y FROM tokens WHERE id=?", (mine,))
    new = stand(client, player, code, mine)
    assert not any(c["k"] == "prone" for c in new["conds"])
    pos_after = db.q1("SELECT x, y FROM tokens WHERE id=?", (mine,))
    assert (pos_before["x"], pos_before["y"]) == (pos_after["x"], pos_after["y"])
    init = CB.get_init(room_id(code))
    assert init.get("turn") is None                                    # no combat accounting


def test_combat_stand_costs_half_the_turn_base(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, mine)
    cond_add(client, player, code, mine, "prone")
    stand(client, player, code, mine)                                 # success
    init = CB.get_init(room_id(code))
    assert init["turn"]["move_spent"] == 3                            # 6 base -> 3
    assert init["turn"]["move_total"] == 6
    assert not any(c["k"] == "prone" for c in conds_of(mine))
    tok = db.q1("SELECT x, y FROM tokens WHERE id=?", (mine,))
    assert (int(tok["x"] // 50), int(tok["y"] // 50)) == (8, 6)        # stood in place
    walk_to(client, player, code, mine, 11, 6)                        # remaining 3 still work
    tok = db.q1("SELECT x, y FROM tokens WHERE id=?", (mine,))
    assert (int(tok["x"] // 50), int(tok["y"] // 50)) == (11, 6)


def test_stand_rejected_without_enough_movement_keeps_prone(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, mine)
    cond_add(client, player, code, mine, "prone")
    walk_to(client, player, code, mine, 12, 6)                        # prone does not block walking; spends 4
    err = stand(client, player, code, mine, want=False)["msg"]
    assert "movement" in err.lower()
    assert any(c["k"] == "prone" for c in conds_of(mine))             # still lying there


def test_stand_uses_base_not_dash_total(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, mine)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "dash", "token_id": mine})
        recv_until(ws, "initiative")
    cond_add(client, player, code, mine, "prone")
    stand(client, player, code, mine)
    init = CB.get_init(room_id(code))
    assert init["turn"]["move_total"] == 12                           # dashed
    assert init["turn"]["move_spent"] == 3                            # cost was half the BASE


def test_stand_needs_own_turn(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    init = CB.get_init(room_id(code))
    if init["turn"]["token_id"] == mine:
        init_next(client, dm, code)
    assert CB.get_init(room_id(code))["turn"]["token_id"] != mine
    cond_add(client, player, code, mine, "prone")                     # applying is legal anytime
    err = stand(client, player, code, mine, want=False)["msg"]
    assert "your turn" in err.lower()
    assert any(c["k"] == "prone" for c in conds_of(mine))


def test_downed_cannot_stand(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    cond_add(client, player, code, mine, "prone")
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "hp", "token_id": mine, "delta": -999})
        recv_until(ws, "snapshot")
    err = stand(client, player, code, mine, want=False)["msg"]
    assert "downed" in err.lower()
    assert any(c["k"] == "prone" for c in conds_of(mine))             # removed only on success


# ---------- condition state is server state (§8) ----------

def test_reconnect_replays_conditions_with_full_state(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    cond_add(client, dm, code, mine, "poisoned", rounds=3, until="end")
    cond_add(client, player, code, mine, "prone")
    snap = next(t for t in state_of(client, player, code)["tokens"] if t["id"] == mine)
    by_key = {c["k"]: c for c in snap["conds"]}
    assert by_key["poisoned"]["rounds"] == 3 and by_key["poisoned"]["until"] == "end"
    assert "prone" in by_key
    assert crounds(mine, "poisoned") == 3                             # DB is the truth


# ---------- Sprint 13 economy still intact next to all this ----------

def test_end_turn_resets_after_conditions_ran(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, mine)
    cond_add(client, dm, code, mine, "frightened", rounds=1, until="end")
    cond_add(client, player, code, mine, "prone")
    stand(client, player, code, mine)                                 # spends 3 of 6
    with ws_connect(client, player, code) as ws:                      # Sprint 13: End Turn
        ws.send_json({"type": "end_turn"})
        recv_until(ws, "initiative")
    init = CB.get_init(room_id(code))
    assert init["turn"]["token_id"] != mine
    assert init["turn"]["move_spent"] == 0 and init["turn"]["move_total"] == 6
    assert all(init["turn"][s] == "available" for s in ("action", "bonus", "reaction"))
    assert crounds(mine, "frightened") is None                        # end hook fired on the way
