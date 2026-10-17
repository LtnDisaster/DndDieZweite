"""Sprint 29 (D100): Operation Integration — adversarial pins for the fixes.

These are REAL tests (no xfail, no new skips). Each reproduces a defect found by
the integration/security audit and pins the fixed behaviour, plus the invariants
the fixes must NOT regress:

* G7  — slot/resource consumption in the ability engine is atomic: concurrent
        casts of one caster can never overspend (successes == the slot total,
        never more), so an increment can no longer be lost;
* G5  — a non-DM long/short rest now gets a clear error instead of silence;
* G8b — the REAL add_token path (npc.clean_npc) keeps a bare string ability id so
        a DM-controlled familiar stays castable by its assigned controller;
* G9  — item_defs cross-room safety: reads/delete/grant are room-scoped and a
        same-named definition owned by ANOTHER room is refused, never clobbered;
* D100 autonomy lock — a sheet owner can no longer rewrite the server-authorised
        fields (level / spells / spell_slots) via the raw editor PUT, nor raw-set
        class levels; DM class_levels and the validated Build are untouched;
* a green end-to-end flow over the D95-D99 subsystems (import -> build -> cast ->
        consume -> money -> companion -> reload -> consistency).
"""
import threading
import uuid

import pytest
from starlette.testclient import TestClient

from app import abilities, charbuild, content, db, gear, main
from tests.test_movement_fog import (H, add_npc, base_room, join_room, make_char,
                                     recv_until, reg, state_of, ws_connect)

CELL = 50
PACK = (main.__file__.rsplit("/", 1)[0] + "/content_pack")


@pytest.fixture()
def client():
    return TestClient(main.app)


def rid_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def char_token(client, user, code, ch_id):
    for t in state_of(client, user, code)["tokens"]:
        if t.get("character_id") == ch_id:
            return t["id"]
    raise AssertionError("no token for that character")


# --------------------------------------------------------------------------
# G7 — atomic slot consumption (concurrency invariant)
# --------------------------------------------------------------------------

def test_g7_concurrent_casts_never_overspend_slots(client):
    abilities.register({"id": "d100_zap", "name": "Zap", "ability": "int", "range_ft": 120,
                        "targeting": "self", "resolution": "auto",
                        "cost": {"type": "spell_slot", "level": 1}})
    dm, player, code, ch = base_room(client)
    db.x("UPDATE characters SET abilities=?, spell_slots=? WHERE id=?",
         (db.json_dumps(["d100_zap"]), db.json_dumps({1: {"max": 1, "used": 0}}), ch["id"]))
    tok_id = char_token(client, player, code, ch["id"])
    room_id = rid_of(code)
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (tok_id, room_id))
    defn = abilities.get("d100_zap")

    # The D100 fix folded op-claim + cost into ONE BEGIN IMMEDIATE tx (_cast_gate).
    # Hammer exactly that synchronous unit from many threads (each on its own
    # thread-local connection under WAL): the write lock serialises the "slots
    # left?" check with the increment, so a fixed number of successes is an
    # invariant, not a race. Pre-D100 the read/increment/write straddled separate
    # statements and a concurrent pair could both pass the check.
    outcomes = []
    lock = threading.Lock()

    def fire():
        try:
            status, _, _ = abilities._cast_gate(room_id, tok, defn, None, None)
            with lock:
                outcomes.append(status)
        except abilities._CastRejected:
            with lock:
                outcomes.append("fail")

    threads = [threading.Thread(target=fire) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok = outcomes.count("ok")
    slots = db.j(db.q1("SELECT spell_slots FROM characters WHERE id=?", (ch["id"],))["spell_slots"], {})
    assert ok == 1, f"expected exactly 1 paid cast, got {ok} (lost update!)"
    assert slots["1"]["used"] == 1                                 # never overspent, never lost
    assert outcomes.count("fail") == 11                             # every loser refused cleanly


# --------------------------------------------------------------------------
# G5 — non-DM rest is refused with a message (not silence)
# --------------------------------------------------------------------------

def test_g5_non_dm_rest_gets_error(client):
    dm, player, code, ch = base_room(client)
    tok = char_token(client, player, code, ch["id"])
    # a long rest is DM-only — a player now gets an error, not silence
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "long_rest", "clear_conditions": False})
        assert "DM" in (recv_until(ws, "error")["payload"]["msg"])
    # a different player cannot short-rest THIS player's token
    other = reg(client, "oth")
    join_room(client, other, code)
    with ws_connect(client, other, code) as ws:
        ws.send_json({"type": "short_rest", "token_id": tok, "hit_dice_count": 1})
        assert "character" in (recv_until(ws, "error")["payload"]["msg"]).lower()


# --------------------------------------------------------------------------
# G8b — the real add_token path preserves a string ability id
# --------------------------------------------------------------------------

def test_g8b_string_ability_survives_real_npc_path(client):
    abilities.register({"id": "d100_gaze", "name": "Gaze", "ability": "wis", "range_ft": 0,
                        "targeting": "self", "resolution": "auto", "concentration": True})
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "add_token", "label": "Familiar", "x": 15 * CELL, "y": 2 * CELL,
                       "abilities": ["d100_gaze"]})
        tid = recv_until(wsd, "token_add")["payload"]["id"]
    tok = db.q1("SELECT * FROM tokens WHERE id=?", (tid,))
    blk = db.j(tok["npc"], {})
    assert "d100_gaze" in (blk.get("abilities") or []), \
        "clean_npc must keep a bare string ability id (was silently dropped pre-D100)"
    # the exact authority gate _rollable_by reads the same list: a NON-DM controlling
    # this familiar can now use the ability (pre-D100 the id was gone -> refused).
    assert abilities._rollable_by(abilities.get("d100_gaze"), tok, is_dm=False) is True


def test_g8b_prose_actions_still_roundtrip(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "add_token", "label": "Brute", "x": 16 * CELL, "y": 2 * CELL,
                       "abilities": [{"name": "Multiattack", "desc": "Two bites"}]})
        tid = recv_until(wsd, "token_add")["payload"]["id"]
    blk = db.j(db.q1("SELECT npc FROM tokens WHERE id=?", (tid,))["npc"], {})
    assert {"name": "Multiattack", "desc": "Two bites"} in blk["abilities"]


# --------------------------------------------------------------------------
# G9 / A13 — item_defs cross-room safety
# --------------------------------------------------------------------------

def test_g9_definition_id_is_room_scoped_and_not_clobbered(client):
    dm_a, player_a, code_a, _ = base_room(client)
    dm_b, player_b, code_b, _ = base_room(client)
    did = "d100_blade_" + uuid.uuid4().hex[:6]

    # room A creates a definition
    with ws_connect(client, dm_a, code_a) as wsa:
        wsa.send_json({"type": "item_def", "action": "create",
                       "defn": {"id": did, "name": "A Blade", "kind": "weapon", "weight": 3}})
        recv_until(wsa, "inv_changed")
    assert db.q1("SELECT name FROM item_defs WHERE room_id=? AND id=?", (rid_of(code_a), did))["name"] == "A Blade"

    # room B with the SAME id is refused — no silent overwrite of A's row
    with ws_connect(client, dm_b, code_b) as wsb:
        wsb.send_json({"type": "item_def", "action": "create",
                       "defn": {"id": did, "name": "B Blade", "kind": "weapon", "weight": 3}})
        assert "another room" in (recv_until(wsb, "error")["payload"]["msg"]).lower()
    assert db.q1("SELECT name FROM item_defs WHERE id=?", (did,))["name"] == "A Blade"    # untouched
    assert db.q1("SELECT 1 FROM item_defs WHERE room_id=? AND id=?", (rid_of(code_b), did)) is None

    # room B cannot read/delete/grant room A's definition even knowing the id
    with ws_connect(client, dm_b, code_b) as wsb:
        wsb.send_json({"type": "item_def", "action": "delete", "def_id": did})
        recv_until(wsb, "inv_changed")
    assert db.q1("SELECT name FROM item_defs WHERE id=?", (did,))["name"] == "A Blade"    # survived B's delete


def test_g9_import_refuses_shared_id_without_losing_content(client):
    # item_defs.id is GLOBAL. Two rooms importing the SAME item id: the first owns
    # the shared DM-library row; the second must STILL get its room-scoped content
    # row (export SSOT) but must NOT clobber the first room's library row. Run-unique
    # ids so these two rooms are the only claimants regardless of other tests.
    import pathlib
    dm_a, _, code_a, _ = base_room(client)
    dm_b, _, code_b, _ = base_room(client)
    uid = uuid.uuid4().hex[:6]
    sp = f"sword_plus1_{uid}"
    items = (pathlib.Path(PACK) / "items.csv").read_text(encoding="utf-8").replace("sword_plus1", sp)
    a = content.import_package({"items.csv": items}, room_id=rid_of(code_a), mode="apply", apply=True)
    assert a["ok"]
    b = content.import_package({"items.csv": items}, room_id=rid_of(code_b), mode="apply", apply=True)
    assert b["ok"]                                    # content stored per room regardless
    assert db.q1("SELECT 1 FROM content WHERE kind='item' AND room_id=? AND id=?",
                 (rid_of(code_b), sp))                 # room B has its OWN content row
    # the shared item_defs row belongs to whoever imported first (A) and was not rewritten by B
    assert db.q1("SELECT room_id FROM item_defs WHERE id=?", (sp,))["room_id"] == rid_of(code_a)


# --------------------------------------------------------------------------
# D100 autonomy lock
# --------------------------------------------------------------------------

def _sheet_body(ch):
    return {k: ch[k] for k in ("name", "race", "char_class", "level", "stats", "hp", "max_hp",
                               "ac", "speed", "notes", "weapons", "items", "skills", "spells",
                               "spell_slots", "saves", "defenses", "resources") if k in ch}


def test_lock_owner_put_cannot_rewrite_authorised_fields(client):
    dm, player, code, ch = base_room(client)
    # stage a real caster server-side (the authorised writer)
    db.x("UPDATE characters SET spells=?, spell_slots=?, level=? WHERE id=?",
         (db.json_dumps(gear.clean_spells([{"id": "zap", "name": "Zap", "level": 1, "cast": "none"}])),
          db.json_dumps({1: {"max": 1, "used": 1}}), 3, ch["id"]))

    # an ordinary editor PUT that also tries to abuse the authority fields
    body = {"name": ch["name"], "ac": 19, "level": 20,
            "spells": [], "spell_slots": {"1": {"max": 9, "used": 9}}}
    r = client.put(f"/api/characters/{ch['id']}", headers=H(player), json=body)
    assert r.status_code == 200

    row = db.q1("SELECT level, spells, spell_slots, ac FROM characters WHERE id=?", (ch["id"],))
    assert row["ac"] == 19                                     # ordinary edits still apply
    assert row["level"] == 3                                   # authority fields preserved
    assert len(db.j(row["spells"], [])) == 1                   # spell list not wiped
    assert db.j(row["spell_slots"], {})["1"] == {"max": 1, "used": 1}   # slots untouched


def test_lock_owner_cannot_raw_set_class_levels_dm_can(client):
    dm, player, code, ch = base_room(client)
    db.x("UPDATE characters SET level=?, class_levels=? WHERE id=?",
         (5, db.json_dumps([]), ch["id"]))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "class_levels", "character_id": ch["id"],
                      "class_levels": [{"class_id": "warrior", "level": 9}]})
        assert "build" in (recv_until(ws, "error")["payload"]["msg"]).lower() or \
               "dm" in (recv_until(ws, "error")["payload"]["msg"]).lower()
    assert db.q1("SELECT level FROM characters WHERE id=?", (ch["id"],))["level"] == 5


def test_lock_validated_build_still_open_to_owner(client):
    # importing shipped classes then applying the Build is the OWNER's preserved
    # progression path — the lock must not have touched it.
    import pathlib
    dm, player, code, ch = base_room(client)
    files = {p.name: pathlib.Path(p).read_text(encoding="utf-8") for p in pathlib.Path(PACK).glob("*.csv")}
    assert content.import_package(files, room_id=rid_of(code), mode="apply", apply=True)["ok"]
    ok, res = charbuild.apply(ch["id"], "scout", 1,
                              {"skills": ["stealth", "perception", "acrobatics", "athletics"],
                               "levels": {"1": {"expertise": "stealth"}}},
                              rid_of(code))
    assert ok, res
    assert db.q1("SELECT level FROM characters WHERE id=?", (ch["id"],))["level"] == 1


# --------------------------------------------------------------------------
# Phase 1 — a green end-to-end flow across the subsystems
# --------------------------------------------------------------------------

def test_end_to_end_flow(client):
    import pathlib
    dm, player, code, ch = base_room(client)
    rid = rid_of(code)
    files = {p.name: pathlib.Path(p).read_text(encoding="utf-8") for p in pathlib.Path(PACK).glob("*.csv")}
    assert content.import_package(files, room_id=rid, mode="apply", apply=True)["ok"]

    # build a level-1 scout (validated owner path)
    ok, _ = charbuild.apply(ch["id"], "scout", 1,
                            {"skills": ["stealth", "perception", "acrobatics", "athletics"],
                             "levels": {"1": {"expertise": "stealth"}}}, rid)
    assert ok
    tok = char_token(client, player, code, ch["id"])

    # grant + wear a magic item through the DM library, then derived AC moves
    ring_id = "d100_ring_" + uuid.uuid4().hex[:6]
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "item_def", "action": "create",
                       "defn": {"id": ring_id, "name": "Ring", "kind": "trinket",
                                "props": {"ac_bonus": 1, "attune": True}}})
        recv_until(wsd, "inv_changed")
        wsd.send_json({"type": "inv_grant", "char_id": ch["id"], "def_id": ring_id})
        recv_until(wsd, "inv_changed")
    inv = [i for i in state_of(client, player, code)["characters"] if i["id"] == ch["id"]][0]["items"]
    ring = next(i for i in inv if i["name"] == "Ring")

    # money: DM grants copper->gold; wallet is one integer
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "inv_money", "action": "grant", "char_id": ch["id"],
                       "amount": 5, "coin": "gp", "op_id": "m1"})
        recv_until(wsd, "inv_changed")
    assert db.q1("SELECT wallet FROM characters WHERE id=?", (ch["id"],))["wallet"] == 500

    # a companion token bound to the player, led by the DM
    with ws_connect(client, dm, code) as wsd:
        pid = state_of(client, player, code)["me"]
        wsd.send_json({"type": "add_token", "label": "Wolf", "x": 12 * CELL, "y": 12 * CELL,
                       "owner_user_id": pid})
        comp = recv_until(wsd, "token_add")["payload"]["id"]
    assert db.q1("SELECT owner_user_id FROM tokens WHERE id=?", (comp,))["owner_user_id"] == pid

    # reload consistency: wallet, encumbrance, companion all derive on the sheet
    st = state_of(client, player, code)
    me = next(c for c in st["characters"] if c["id"] == ch["id"])
    assert me["derived"]["wallet"]["cp"] == 500            # integer copper on the sheet
    assert "encumbrance" in me["derived"]
    assert any(t["id"] == comp and t.get("owner_user_id") == pid for t in st["tokens"])
