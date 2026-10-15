"""D112 (Sprint 41): the generic opposed/DC resolution primitive, complete
pickpocketing, and D&D 2024 Grapple / Shove / Escape.

Every d20 is forced through ``app.room.dice`` (the one dice engine) so every
outcome is deterministic; modifiers come from ``gear``. This file pins: the
opposed win/lose/tie shapes, per-participant ability/skill choice and
advantage/disadvantage, auto-failing saves; the two pickpocket transfer models
(DM-mediated + DM-authorised auto-steal) with the info-leak guard, replay
(before/after success and failure), a concurrent double-steal, a cursed item's
owner-change, and cross-room / cross-plane rejection; Grapple/Shove success +
resist, size + reach gates, shove→prone and shove→forced-move, grapple-end-on-
distance and escape; the "no free die / no cost for a pre-invalid action"
discipline. The D105/D106 loot and D109/D110/D111 invariants are covered by the
sibling suites that run alongside this one.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import conditions as CND, db, gear, inventory as INV, main
from app.room import dice as RD, opposed
from tests.test_movement_fog import (H, add_npc, base_room, join_room, make_char,
                                     recv_until, reg, state_of, ws_connect)
from tests.test_d109_mastery import always, conds_of, drain
from tests.test_d105_gear_loot import _fill_npc
from tests.test_sprint23_combat import _to_player_turn


@pytest.fixture()
def client():
    return TestClient(main.app)


def rid_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

def pc_tok(client, user, code):
    st = state_of(client, user, code)
    return next(t["id"] for t in st["tokens"] if t.get("owner_user_id") == st["me"])


def place(client, dm, code, tok, tx, ty):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "move", "token_id": tok, "tx": tx, "ty": ty, "teleport": True})
        drain(ws)


def npc(client, dm, code, cx, cy, hp=10, label="Foe", **block):
    """A living NPC token (grapple/pickpocket target) at cell (cx,cy), on floor ''."""
    with ws_connect(client, dm, code) as ws:
        tok = add_npc(ws, label=label, cx=cx, cy=cy)
        ws.send_json({"type": "update_npc", "token_id": tok, "label": label,
                      "hp": hp, "max_hp": hp, "ac": 12, **block})
        drain(ws)
    return tok


def two_players(client):
    dm, p1, code, ch1 = base_room(client)
    p2 = reg(client, "p2")
    join_room(client, p2, code)
    ch2 = make_char(client, p2)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch2["id"]}, headers=H(p2))
    return dm, p1, p2, code, ch1, ch2


def _npc_items(room_id, foe):
    return INV.container_peek(room_id, f"tok:{foe}", curse=True)


def _char_items(cid):
    row = db.q1("SELECT items FROM characters WHERE id=?", (cid,))
    return gear.clean_items(db.j(row["items"], []), keep_curse=True)


def _npc_pick(client, dm, code, foe, name="Coin purse"):
    payload = _fill_npc(client, dm, code, foe, name, 1)
    item_id = payload["items"][0]["id"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "pickable", "action": "set", "token_id": foe,
                      "item_id": item_id, "op_id": "pk" + uuid.uuid4().hex[:8]})
        drain(ws)
    return item_id, name


# ---------------------------------------------------------------------------
# unit: the pure comparison + per-participant rolls (no WebSocket)
# ---------------------------------------------------------------------------

def test_opposed_win_lose_tie_shapes():
    assert opposed.opposed_wins(15, 12) is True
    assert opposed.opposed_wins(12, 15) is False
    assert opposed.opposed_wins(12, 12, tie="defender") is False   # tie → defender
    assert opposed.opposed_wins(12, 12, tie="attacker") is True    # tie → attacker
    with pytest.raises(opposed.Tie):
        opposed.opposed_wins(12, 12, tie="dm")                     # tie → DM decides
    assert opposed.beats_dc(15, 15) is True
    assert opposed.beats_dc(14, 15) is False


def _seq(monkeypatch, vals):
    it = iter(vals)
    monkeypatch.setattr(RD.random, "randint", lambda a, b: next(it))


def test_save_honours_advantage_and_disadvantage(monkeypatch):
    plain = {"sheet": {"stats": {"dex": 10}, "level": 1}, "saves": {},
             "conds": [], "room_id": 1, "name": "X"}
    _seq(monkeypatch, [7, 18])
    dis = dict(plain, conds=CND.add([], "restrained"))    # my_saves_dis → disadvantage
    r = opposed.save_roll(dis, "dex")
    assert r["adv"] == "dis" and r["kept"] == 7           # the lower die wins

    _seq(monkeypatch, [7, 18])
    a = opposed.save_roll(plain, "dex", adv="adv")
    assert a["adv"] == "adv" and a["kept"] == 18          # the higher die wins


def test_auto_failing_save_is_a_save_failure():
    p = {"sheet": {"stats": {"dex": 20}, "level": 1}, "saves": {},
         "conds": CND.add([], "unconscious"), "room_id": 1, "name": "X"}
    r = opposed.save_roll(p, "dex")
    assert r["auto_fail"] and r["total"] == 0


def test_better_save_picks_the_higher_option():
    p = {"sheet": {"stats": {"str": 8, "dex": 20}, "level": 1}, "saves": {"dex": True},
         "conds": [], "room_id": 1, "name": "X"}
    assert opposed.better_save(p, ("str", "dex")) == "dex"


def test_melee_attack_number_takes_the_better_source():
    pc = {"sheet": {"stats": {"str": 20}, "level": 5, "skills": {"athletics": 1},
                    "saves": {}, "items": [], "equipment": {}},
          "skills": {"athletics": 1}, "saves": {}, "conds": [], "room_id": 1, "name": "X"}
    sheet = gear.as_sheet(dict(pc["sheet"]))
    expected = max(gear.ability_attack_bonus(sheet, "str"),
                   gear.skill_bonus(sheet, {"athletics": 1}, "athletics")[0])
    bonus, src = opposed.melee_attack_number(pc)
    assert bonus == expected and src in ("athletics", "unarmed")


# ---------------------------------------------------------------------------
# Grapple / Shove (2024): attacker check sets a DC, target saves STR or DEX
# ---------------------------------------------------------------------------

def test_grapple_lands_when_save_fails(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    always(client, monkeypatch, 10)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"str": 10, "dex": 8}, saves={})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "grapple", "token_id": pc, "target_id": foe, "op_id": "g1"})
        drain(ws)
    entry = CND.has(conds_of(foe), "grappled")
    assert entry is not None and entry["src"] == pc and entry["dc"] == 16   # 10 + (prof 3 + str 3)


def test_grapple_resisted_when_save_succeeds(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    always(client, monkeypatch, 10)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, level=1,
              stats={"str": 10, "dex": 20}, saves={"dex": True})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "grapple", "token_id": pc, "target_id": foe, "op_id": "g1"})
        drain(ws)
    assert CND.has(conds_of(foe), "grappled") is None


def test_grapple_size_gate(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    always(client, monkeypatch, 20)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    big = npc(client, dm, code, 13, 12, hp=10, size="Huge", stats={"str": 10})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "grapple", "token_id": pc, "target_id": big, "op_id": "g1"})
        err = recv_until(ws, "error")
    assert "too large" in err["payload"]["msg"]
    assert CND.has(conds_of(big), "grappled") is None


def test_grapple_reach_gate(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    always(client, monkeypatch, 20)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 10, 10)
    foe = npc(client, dm, code, 16, 16, hp=10, stats={"str": 10})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "grapple", "token_id": pc, "target_id": foe, "op_id": "g1"})
        err = recv_until(ws, "error")
    assert "reach" in err["payload"]["msg"]


def test_shove_knocks_prone(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    always(client, monkeypatch, 10)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"str": 10, "dex": 8}, saves={})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "shove", "token_id": pc, "target_id": foe,
                      "mode": "prone", "op_id": "s1"})
        drain(ws)
    assert CND.has(conds_of(foe), "prone") is not None


def test_shove_push_moves_target_away(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    always(client, monkeypatch, 10)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"str": 10, "dex": 8}, saves={})
    before = db.q1("SELECT x FROM tokens WHERE id=?", (foe,))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "shove", "token_id": pc, "target_id": foe,
                      "mode": "push", "op_id": "s1"})
        drain(ws)
    after = db.q1("SELECT x FROM tokens WHERE id=?", (foe,))
    assert int(after["x"] // 50) == int(before["x"] // 50) + 1


def test_grapple_ends_when_forced_out_of_reach(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    always(client, monkeypatch, 10)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"str": 10, "dex": 8}, saves={})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "grapple", "token_id": pc, "target_id": foe, "op_id": "g1"})
        drain(ws)
    assert CND.has(conds_of(foe), "grappled") is not None
    with ws_connect(client, dm, code) as dws:                 # DM teleports it 3 cells away
        dws.send_json({"type": "forced_move", "token_id": foe, "kind": "teleport",
                       "tx": 15, "ty": 12})
        drain(dws)
    assert CND.has(conds_of(foe), "grappled") is None


def test_grapple_ends_when_grappler_walks_away(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    always(client, monkeypatch, 10)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"str": 10, "dex": 8}, saves={})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "grapple", "token_id": pc, "target_id": foe, "op_id": "g1"})
        drain(ws)
    assert CND.has(conds_of(foe), "grappled") is not None
    place(client, dm, code, pc, 16, 12)                        # grappler walks to 16,12
    assert CND.has(conds_of(foe), "grappled") is None


def test_escape_success_and_failure(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    pc = pc_tok(client, player, code)
    grappler = npc(client, dm, code, 13, 12, hp=10, stats={"str": 10})

    def grapple_victim(dc):
        tok = db.q1("SELECT * FROM tokens WHERE id=?", (pc,))
        conds = CND.add(CND.load(tok), "grappled", 0, "", src=grappler, dc=dc)
        db.x("UPDATE tokens SET conds=? WHERE id=?", (db.json_dumps(conds), pc))

    always(client, monkeypatch, 20)
    grapple_victim(15)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "escape", "token_id": pc, "op_id": "e1"})
        drain(ws)
    assert CND.has(conds_of(pc), "grappled") is None            # 20 + athletics >= 15

    always(client, monkeypatch, 1)
    grapple_victim(15)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "escape", "token_id": pc, "op_id": "e2"})
        drain(ws)
    assert CND.has(conds_of(pc), "grappled") is not None        # held


def test_escape_when_grappler_gone(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    pc = pc_tok(client, player, code)
    tok = db.q1("SELECT * FROM tokens WHERE id=?", (pc,))
    conds = CND.add(CND.load(tok), "grappled", 0, "", src=999999, dc=30)
    db.x("UPDATE tokens SET conds=? WHERE id=?", (db.json_dumps(conds), pc))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "escape", "token_id": pc, "op_id": "e1"})
        drain(ws)
    assert CND.has(conds_of(pc), "grappled") is None            # automatic


# ---------------------------------------------------------------------------
# Action economy: no free die, no cost for a pre-invalid action
# ---------------------------------------------------------------------------

def test_invalid_grapple_costs_no_action(client):
    dm, player, code, _ = base_room(client)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 10, 10)
    foe = npc(client, dm, code, 16, 16, hp=10, stats={"str": 10})     # out of reach
    _to_player_turn(client, dm, code, pc)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "grapple", "token_id": pc, "target_id": foe, "op_id": "g1"})
        recv_until(ws, "error")
    init = db.j(db.q1("SELECT initiative FROM room_state WHERE room_id=?",
                      (rid_of(code),))["initiative"], {})
    assert (init.get("turn") or {}).get("action") == "available"


def test_valid_grapple_spends_the_action(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    always(client, monkeypatch, 10)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"str": 10, "dex": 8}, saves={})
    _to_player_turn(client, dm, code, pc)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "grapple", "token_id": pc, "target_id": foe, "op_id": "g1"})
        recv_until(ws, "initiative")                                 # slot spend broadcast
    init = db.j(db.q1("SELECT initiative FROM room_state WHERE room_id=?",
                      (rid_of(code),))["initiative"], {})
    assert (init.get("turn") or {}).get("action") == "used"


# ---------------------------------------------------------------------------
# Pickpocket — Model B: auto-steal of a DM-authorised (pick) instance
# ---------------------------------------------------------------------------

def test_pickpocket_autosteal_success_transfers_atomically(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    always(client, monkeypatch, 20)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"wis": 10})
    item_id, name = _npc_pick(client, dm, code, foe)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "pickpocket_take", "token_id": pc, "target_id": foe,
                      "item_id": item_id, "notice_dc": 8, "op_id": "t1"})
        w = recv_until(ws, "whisper")
        drain(ws)
    assert name in w["payload"]["text"]
    assert any(i["name"] == name for i in _char_items(ch["id"]))
    assert all(i["name"] != name for i in _npc_items(rid_of(code), foe))


def test_pickpocket_notice_dc_blocks_theft(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    always(client, monkeypatch, 20)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"wis": 10})
    item_id, name = _npc_pick(client, dm, code, foe)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "pickpocket_take", "token_id": pc, "target_id": foe,
                      "item_id": item_id, "notice_dc": 30, "op_id": "t1"})
        drain(ws)
    assert not any(i["name"] == name for i in _char_items(ch["id"]))
    assert any(i["name"] == name for i in _npc_items(rid_of(code), foe))


def test_pickpocket_opposed_perception_dim_target(client, monkeypatch):
    # No notice_dc → the engine rolls the target's Perception (2024 removed
    # passive). A dim creature (WIS 8) fails to notice a clean hand.
    dm, player, code, ch = base_room(client)
    always(client, monkeypatch, 20)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"wis": 8})
    item_id, name = _npc_pick(client, dm, code, foe)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "pickpocket_take", "token_id": pc, "target_id": foe,
                      "item_id": item_id, "op_id": "t1"})
        drain(ws)
    assert any(i["name"] == name for i in _char_items(ch["id"]))


def test_pickpocket_opposed_perception_wise_target_notices(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    always(client, monkeypatch, 20)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"wis": 20})
    item_id, name = _npc_pick(client, dm, code, foe)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "pickpocket_take", "token_id": pc, "target_id": foe,
                      "item_id": item_id, "op_id": "t1"})
        drain(ws)
    assert not any(i["name"] == name for i in _char_items(ch["id"]))
    assert any(i["name"] == name for i in _npc_items(rid_of(code), foe))


def test_pickpocket_leak_guard_unauthorised_item(client, monkeypatch):
    # An item the DM never flagged 'pick' answers exactly like a failed check:
    # no transfer, and the item name is never spoken to the thief.
    dm, player, code, ch = base_room(client)
    always(client, monkeypatch, 20)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"wis": 8})
    payload = _fill_npc(client, dm, code, foe, "Signet ring", 1)   # NOT flagged pick
    item_id, name = payload["items"][0]["id"], payload["items"][0]["name"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "pickpocket_take", "token_id": pc, "target_id": foe,
                      "item_id": item_id, "notice_dc": 5, "op_id": "t1"})
        w = recv_until(ws, "whisper")
        drain(ws)
    assert name not in w["payload"]["text"]
    assert not any(i["name"] == name for i in _char_items(ch["id"]))
    assert any(i["name"] == name for i in _npc_items(rid_of(code), foe))


def test_pickpocket_replay_after_success_moves_once(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    always(client, monkeypatch, 20)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"wis": 8})
    item_id, name = _npc_pick(client, dm, code, foe)
    with ws_connect(client, player, code) as ws:
        for _ in range(2):
            ws.send_json({"type": "pickpocket_take", "token_id": pc, "target_id": foe,
                          "item_id": item_id, "notice_dc": 8, "op_id": "t-dup"})
            drain(ws)
    have = sum(i["qty"] for i in _char_items(ch["id"]) if i["name"] == name)
    assert have == 1                                               # never duplicated


def test_pickpocket_replay_after_failure_rerolls_nothing(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    always(client, monkeypatch, 20)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"wis": 8})
    item_id, name = _npc_pick(client, dm, code, foe)
    with ws_connect(client, player, code) as ws:
        for _ in range(2):                                         # noticed → no move; op spent
            ws.send_json({"type": "pickpocket_take", "token_id": pc, "target_id": foe,
                          "item_id": item_id, "notice_dc": 30, "op_id": "t-fail"})
            drain(ws)
    assert not any(i["name"] == name for i in _char_items(ch["id"]))


def test_pickpocket_two_requests_cannot_duplicate(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    always(client, monkeypatch, 20)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"wis": 8})
    item_id, name = _npc_pick(client, dm, code, foe)              # qty 1
    with ws_connect(client, player, code) as ws:                  # two distinct op-ids
        ws.send_json({"type": "pickpocket_take", "token_id": pc, "target_id": foe,
                      "item_id": item_id, "notice_dc": 8, "op_id": "a"})
        drain(ws)
        ws.send_json({"type": "pickpocket_take", "token_id": pc, "target_id": foe,
                      "item_id": item_id, "notice_dc": 8, "op_id": "b"})
        drain(ws)
    have = sum(i["qty"] for i in _char_items(ch["id"]) if i["name"] == name)
    assert have == 1                                               # exactly one copy exists


def test_pickpocket_cursed_item_keeps_curse_on_owner_change(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    always(client, monkeypatch, 20)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"wis": 8})
    payload = _fill_npc(client, dm, code, foe, "Doomed blade", 1)
    item_id = payload["items"][0]["id"]
    with ws_connect(client, dm, code) as dws:                     # DM curses it, then flags it
        dws.send_json({"type": "curse", "action": "set", "token_id": foe, "item_id": item_id,
                       "name": "Doom", "desc": "whispers", "op_id": "c1"})
        drain(dws)
        dws.send_json({"type": "pickable", "action": "set", "token_id": foe,
                       "item_id": item_id, "op_id": "pk1"})
        drain(dws)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "pickpocket_take", "token_id": pc, "target_id": foe,
                      "item_id": item_id, "notice_dc": 8, "op_id": "t1"})
        drain(ws)
    stolen = next(i for i in _char_items(ch["id"]) if i["name"] == "Doomed blade")
    assert stolen.get("curse", {}).get("name") == "Doom"          # metadata survives
    assert stolen["curse"].get("revealed") is False               # old owner's knowledge did not travel


def test_pickpocket_pc_victim_autosteal(client, monkeypatch):
    dm, p1, p2, code, ch1, ch2 = two_players(client)
    always(client, monkeypatch, 20)
    thief = pc_tok(client, p1, code)
    victim = pc_tok(client, p2, code)
    place(client, dm, code, thief, 12, 12)
    place(client, dm, code, victim, 13, 12)
    added = INV.grant(rid_of(code), ch2["id"],
                      [{"name": "Lockpick", "kind": "other", "qty": 1}])
    item_id = added[0]["item_id"]
    with ws_connect(client, dm, code) as dws:                     # DM authorises that item
        dws.send_json({"type": "pickable", "action": "set", "char_id": ch2["id"],
                       "item_id": item_id, "op_id": "pk1"})
        drain(dws)
    with ws_connect(client, p1, code) as ws:
        ws.send_json({"type": "pickpocket_take", "token_id": thief, "target_id": victim,
                      "item_id": item_id, "notice_dc": 8, "op_id": "t1"})
        drain(ws)
    assert any(i["name"] == "Lockpick" for i in _char_items(ch1["id"]))
    assert not any(i["name"] == "Lockpick" for i in _char_items(ch2["id"]))


# ---------------------------------------------------------------------------
# Pickpocket — Model A: DM-mediated (concealed check, nothing auto-moves)
# ---------------------------------------------------------------------------

def test_pickpocket_dm_mediated_moves_nothing(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    always(client, monkeypatch, 20)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"wis": 8})
    item_id, name = _npc_pick(client, dm, code, foe)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "pickpocket", "token_id": pc, "target_id": foe, "op_id": "t1"})
        w = recv_until(ws, "whisper")
        drain(ws)
    assert "covertly" in w["payload"]["text"]
    assert name not in w["payload"]["text"]                        # victim's gear never revealed
    assert not any(i["name"] == name for i in _char_items(ch["id"]))
    assert any(i["name"] == name for i in _npc_items(rid_of(code), foe))   # still on the NPC


def test_pickable_handler_toggles_flag(client):
    dm, player, code, _ = base_room(client)
    foe = npc(client, dm, code, 16, 12, hp=10)
    payload = _fill_npc(client, dm, code, foe, "Trinket", 1)
    item_id = payload["items"][0]["id"]
    rid = rid_of(code)

    def flag():
        return next(i for i in _npc_items(rid, foe) if i["id"] == item_id)["pick"]

    assert flag() is False
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "pickable", "action": "set", "token_id": foe,
                      "item_id": item_id, "op_id": "pk1"})
        drain(ws)
    assert flag() is True
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "pickable", "action": "clear", "token_id": foe,
                      "item_id": item_id, "op_id": "pk2"})
        drain(ws)
    assert flag() is False


# ---------------------------------------------------------------------------
# Cross-room / cross-plane rejection
# ---------------------------------------------------------------------------

def test_special_melee_rejects_foreign_room_target(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    _dm2, _pl2, code2, _ch2 = base_room(client)                 # a whole other room
    foreign = pc_tok(client, _pl2, code2)
    always(client, monkeypatch, 20)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "grapple", "token_id": pc, "target_id": foreign, "op_id": "g1"})
        err = recv_until(ws, "error")
    assert "No target" in err["payload"]["msg"]


def test_pickpocket_rejects_cross_plane_target(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    always(client, monkeypatch, 20)
    pc = pc_tok(client, player, code)
    place(client, dm, code, pc, 12, 12)
    foe = npc(client, dm, code, 13, 12, hp=10, stats={"wis": 8})
    db.x("UPDATE tokens SET floor='crypt' WHERE id=?", (foe,))   # different plane
    item_id, name = _npc_pick(client, dm, code, foe)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "pickpocket_take", "token_id": pc, "target_id": foe,
                      "item_id": item_id, "notice_dc": 8, "op_id": "t1"})
        err = recv_until(ws, "error", fail_on_error=False)
    assert "No target" in err["payload"]["msg"]
    assert any(i["name"] == name for i in _npc_items(rid_of(code), foe))   # never moved
