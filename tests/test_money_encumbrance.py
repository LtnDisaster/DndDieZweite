"""Sprint 28 (D99): currencies (integer copper), carrying capacity, companions.

Adversarial pins the whole feature rests on:
* money is ONE server-owned integer of copper — a client sends (amount, coin),
  never a copper total, so no request can mint gold;
* every purse/container op is transactional and replay-guarded, and can NEVER
  drive a balance negative (a shortfall rolls the whole thing back);
* a player transfers only between their own purse and a member's purse of THIS
  room; only the DM grants/deducts; a stranger / other-room char is refused;
* encumbrance is DERIVED (items counted once even when equipped, coins weigh
  their shown split, capacity from effective STR x size x worn carry-bonus) and
  rides the sheet — the client renders it and never recomputes it;
* a companion is a token bound to an owner/controller — created and led only by
  the DM, never assumable by a player through a forged message.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, gear, main
from tests.test_movement_fog import (H, base_room, join_room, make_char,
                                     recv_until, reg, set_grid, state_of,
                                     ws_connect)

CELL = 50


@pytest.fixture()
def client():
    return TestClient(main.app)


def wallet_of(char_id):
    return db.q1("SELECT wallet FROM characters WHERE id=?", (char_id,))["wallet"]


def _money(ws, action, **kw):
    ws.send_json({"type": "inv_money", "action": action, **kw})


def _err(ws):
    ev = recv_until(ws, "error")
    return (ev.get("payload") or {}).get("msg", "")


def _msg_of(ev, key):
    return (ev.get("payload") or {}).get(key)


# ---------- currency math (pure, integer, no rules) ----------

def test_to_cp_is_integer_and_strict():
    assert gear.to_cp(3, "gp") == 300 and gear.to_cp(5, "sp") == 50
    assert gear.to_cp(2, "ep") == 100 and gear.to_cp(1, "pp") == 1000
    for bad in ("xx", "", None):
        with pytest.raises(ValueError):
            gear.to_cp(1, bad)
    for n in (-1, "x", 1.5, True, None):
        with pytest.raises(ValueError):
            gear.to_cp(n, "gp")


def test_breakdown_is_greedy_and_lossless():
    parts = {c["id"]: c["count"] for c in gear.cp_breakdown(123)}
    assert parts["gp"] == 1 and parts["sp"] == 2 and parts["cp"] == 3
    assert sum(c["count"] * gear._BY_ID[c["id"]]["value_cp"]
               for c in gear.cp_breakdown(2052)) == 2052
    assert len(gear.cp_breakdown(0)) == 5 and gear.cp_breakdown(0)[0]["count"] == 0


# ---------- DM grant / deduct ----------

def test_dm_grant_and_deduct_persist(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _money(ws, "grant", char_id=ch["id"], amount=5, coin="gp", op_id="g1")
        recv_until(ws, "inv_changed")
    assert wallet_of(ch["id"]) == 500
    with ws_connect(client, dm, code) as ws:
        _money(ws, "deduct", char_id=ch["id"], amount=200, coin="cp", op_id="d1")
        recv_until(ws, "inv_changed")
    assert wallet_of(ch["id"]) == 300
    der = client.get(f"/api/rooms/{code}/state", headers=H(player)).json()["characters"][0]["derived"]
    assert der["wallet"]["cp"] == 300
    assert {c["id"]: c["count"] for c in der["wallet"]["coins"]}["gp"] == 3
    assert len(der["wallet"]["currencies"]) == 5


def test_negative_balance_is_refused(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _money(ws, "grant", char_id=ch["id"], amount=1, coin="gp", op_id="g1")
        recv_until(ws, "inv_changed")
        _money(ws, "deduct", char_id=ch["id"], amount=10, coin="gp", op_id="d2")
        assert "enough" in _err(ws).lower()
    assert wallet_of(ch["id"]) == 100            # the whole op rolled back


def test_money_replay_changes_nothing(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _money(ws, "grant", char_id=ch["id"], amount=50, coin="sp", op_id="same")
        recv_until(ws, "inv_changed")
        _money(ws, "grant", char_id=ch["id"], amount=50, coin="sp", op_id="same")
        recv_until(ws, "whisper")
    assert wallet_of(ch["id"]) == 500


# ---------- authorisation ----------

def test_player_cannot_grant_and_forged_char_refused(client):
    dm, player, code, ch = base_room(client)
    outsider = reg(client, "out")
    other = make_char(client, outsider)          # belongs to NO member of this room
    with ws_connect(client, player, code) as ws:
        _money(ws, "grant", char_id=ch["id"], amount=5, coin="gp")     # DM only
        assert "DM" in _err(ws)
    with ws_connect(client, dm, code) as ws:
        _money(ws, "grant", char_id=other["id"], amount=5, coin="gp")  # not of this room
        _err(ws)
    assert wallet_of(other["id"]) == 0


# ---------- transfers ----------

def _second_member(client, code):
    user = reg(client, "mate")
    join_room(client, user, code)
    ch = make_char(client, user)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(user))
    return user, ch


def test_transfer_between_members_is_atomic(client):
    dm, player, code, ch = base_room(client)
    mate, mch = _second_member(client, code)
    with ws_connect(client, dm, code) as ws:
        _money(ws, "grant", char_id=ch["id"], amount=100, coin="cp", op_id="seed")
        recv_until(ws, "inv_changed")
    with ws_connect(client, player, code) as ws:
        _money(ws, "transfer", char_id=ch["id"], to_char_id=mch["id"], amount=40, coin="cp", op_id="t1")
        recv_until(ws, "inv_changed")
    assert wallet_of(ch["id"]) == 60 and wallet_of(mch["id"]) == 40
    with ws_connect(client, player, code) as ws:
        _money(ws, "transfer", char_id=ch["id"], to_char_id=mch["id"], amount=9999, coin="cp", op_id="t2")
        assert "enough" in _err(ws).lower()
    assert wallet_of(ch["id"]) == 60 and wallet_of(mch["id"]) == 40
    with ws_connect(client, player, code) as ws:            # replay = no-op
        _money(ws, "transfer", char_id=ch["id"], to_char_id=mch["id"], amount=40, coin="cp", op_id="t1")
        recv_until(ws, "whisper")
    assert wallet_of(ch["id"]) == 60 and wallet_of(mch["id"]) == 40


def test_transfer_to_stranger_refused(client):
    dm, player, code, ch = base_room(client)
    outsider = reg(client, "out")
    other = make_char(client, outsider)
    with ws_connect(client, dm, code) as ws:
        _money(ws, "grant", char_id=ch["id"], amount=50, coin="cp", op_id="s")
        recv_until(ws, "inv_changed")
    with ws_connect(client, player, code) as ws:
        _money(ws, "transfer", char_id=ch["id"], to_char_id=other["id"], amount=10, coin="cp")
        _err(ws)
    assert wallet_of(ch["id"]) == 50


# ---------- container loot (reuse the D82 chest framework) ----------

def _chest(x, y, cid="chest"):
    return {"id": cid, "x": x, "y": y, "label": "Hoard",
            "interact": {"label": "Open", "op": {"kind": "container"}}}


def _chest_at_player(client, dm, player, code, cid="chest"):
    st = state_of(client, player, code)
    tok = next(t for t in st["tokens"] if t.get("owner_user_id") == st["me"])
    cx, cy = int(tok["x"] // CELL), int(tok["y"] // CELL)
    set_grid(client, dm, code, lambda g: g["objects"].append(_chest(cx, cy, cid)))
    return cx, cy


def test_container_fill_then_take(client):
    dm, player, code, ch = base_room(client)
    cid = "hoard" + uuid.uuid4().hex[:6]
    _chest_at_player(client, dm, player, code, cid=cid)
    with ws_connect(client, dm, code) as ws:                       # DM fills (no reach gate)
        ws.send_json({"type": "inv_container", "action": "coins_fill", "object_id": cid,
                      "floor": "", "amount": 1, "coin": "pp", "op_id": "f1"})
        assert _msg_of(recv_until(ws, "inv_contents"), "coins") == 1000
    with ws_connect(client, player, code) as ws:                   # owner loots, adjacent
        ws.send_json({"type": "inv_container", "action": "coins_take", "object_id": cid,
                      "floor": "", "char_id": ch["id"], "amount": 4, "coin": "gp", "op_id": "t1"})
        p = recv_until(ws, "inv_contents")["payload"]
    assert p["coins"] == 600 and wallet_of(ch["id"]) == 400
    with ws_connect(client, player, code) as ws:                   # replay = no-op
        ws.send_json({"type": "inv_container", "action": "coins_take", "object_id": cid,
                      "floor": "", "char_id": ch["id"], "amount": 4, "coin": "gp", "op_id": "t1"})
        recv_until(ws, "whisper")
    assert wallet_of(ch["id"]) == 400


def test_player_cannot_fill_a_hoard(client):
    dm, player, code, ch = base_room(client)
    cid = "hoard" + uuid.uuid4().hex[:6]
    _chest_at_player(client, dm, player, code, cid=cid)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_container", "action": "coins_fill", "object_id": cid,
                      "floor": "", "amount": 5, "coin": "gp"})
        assert "DM" in _err(ws)


# ---------- encumbrance (derived) ----------

def _char(str_score=10, size="medium", items=None, equipment=None, wallet=0):
    return {"stats": {"str": str_score}, "size": size, "items": items or [],
            "equipment": equipment or {}, "wallet": wallet}


def test_encumbrance_counts_quantity_once_and_coins():
    items = [{"id": "a", "name": "Ration", "qty": 3, "weight": 2},
             {"id": "b", "name": "Kit", "qty": 1, "weight": 12}]
    assert gear.inventory_weight(_char(items=items), 100) == pytest.approx(18.02)  # 6+12+coin
    assert gear.carry_capacity(_char(str_score=10)) == 150
    e = gear.encumbrance(_char(str_score=10, items=items, wallet=100), 100)
    assert e["carried"] == pytest.approx(18.02) and not e["overloaded"]


def test_size_modifier_and_carry_bonus():
    assert gear.carry_capacity(_char(str_score=10, size="small")) == 75      # x0.5
    assert gear.carry_capacity(_char(str_score=10, size="large")) == 300     # x2
    assert gear.carry_capacity(_char(str_score=10, size="huge")) == 600      # x4
    bag = {"id": "bag", "name": "Bag", "qty": 1, "weight": 0, "props": {"carry_bonus": 200}}
    assert gear.carry_capacity(_char(str_score=10, items=[bag], equipment={"acc1": "bag"})) == 350
    assert gear.carry_capacity(_char(str_score=10, items=[bag])) == 150       # not worn → inert
    assert gear.carry_capacity(_char(str_score=12, items=[bag], equipment={"acc1": "bag"})) == 12 * 15 + 200


def test_overloaded_flag_only_warns():
    heavy = _char(str_score=8, items=[{"id": "x", "name": "Anvil", "qty": 1, "weight": 200}])
    e = gear.encumbrance(heavy, 0)
    assert e["capacity"] == 120 and e["carried"] == 200 and e["overloaded"]


def test_equipped_weight_not_double_counted_and_overload_on_sheet(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "inv_grant", "char_id": ch["id"], "qty": 1,
                      "item": {"name": "Plate", "kind": "armor", "weight": 65}})
        recv_until(ws, "inv_changed")
    der = client.get(f"/api/rooms/{code}/state", headers=H(player)).json()["characters"][0]["derived"]
    assert der["encumbrance"]["carried"] == pytest.approx(65.0)             # once, not 130
    assert der["encumbrance"]["capacity"] == 240                            # STR 16 x 15
    assert der["encumbrance"]["overloaded"] is False


def test_wallet_and_encumbrance_survive_refetch(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _money(ws, "grant", char_id=ch["id"], amount=3, coin="gp", op_id="z")
        recv_until(ws, "inv_changed")
    a = client.get(f"/api/rooms/{code}/state", headers=H(player)).json()["characters"][0]["derived"]
    b = client.get(f"/api/rooms/{code}/state", headers=H(player)).json()["characters"][0]["derived"]
    assert a["wallet"]["cp"] == b["wallet"]["cp"] == 300
    # 3 gp = 3 coins * 0.02 lb
    assert a["encumbrance"]["carried"] == pytest.approx(0.06)


# ---------- companions (existing tokens + controller, no new engine) ----------

def test_player_cannot_create_a_companion_token(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, player, code) as ws:                  # DM-only: silently ignored
        ws.send_json({"type": "add_token", "label": "Wolf", "x": 500, "y": 500})
    toks = client.get(f"/api/rooms/{code}/state", headers=H(dm)).json()["tokens"]
    assert len(toks) == 1                                          # only the player's own


def test_only_dm_can_assign_a_controller(client):
    dm, player, code, ch = base_room(client)
    tid = client.get(f"/api/rooms/{code}/state", headers=H(dm)).json()["tokens"][0]["id"]
    with ws_connect(client, player, code) as ws:                   # a player can't self-seize
        ws.send_json({"type": "token_controller", "token_id": tid, "controller_id": 999})
        assert "DM" in _err(ws)


def test_controller_must_be_a_room_member(client):
    dm, player, code, ch = base_room(client)
    tid = client.get(f"/api/rooms/{code}/state", headers=H(dm)).json()["tokens"][0]["id"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_controller", "token_id": tid, "controller_id": 987654})
        assert "member" in _err(ws).lower()
