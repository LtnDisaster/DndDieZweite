"""D162-7 — rolled damage waits for a DM (audit P2-5).

The attack line said HIT and the dice were real — yet HP never moved, because
only the manual hp channel touched health. Now EVERY item-attack hit on a
target registers a pending_damage row, the DM gets Apply/Decline on the dice
line itself, and:
  * Apply claims atomically (two DMs, one application — proven),
  * a failing mutation returns the claim (retry applies exactly once),
  * a crashed mid-apply is swept back to pending at next init_db (GO #3),
  * Decline changes nothing but the row status,
  * players get a LOUD "DM only" (D162-11 posture).
Damage still flows ONLY through health.damage (resistances/temp HP/death
saves — the D34 choke)."""
import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_d109_mastery import (attack, char_items, equip, grant_item,
                                     mk_def)
from tests.test_movement_fog import (base_room, recv_until, state_of,
                                     ws_connect)

DICE_PROPS = {"damage_dice": "1d6", "attack_bonus": 20, "damage_type": "slashing"}


@pytest.fixture()
def client():
    return TestClient(main.app)


def armed_pc(client, dm, player, code, ch_id):
    did = mk_def(client, dm, code, dict(DICE_PROPS), "Testblade")
    grant_item(client, dm, code, ch_id, did)
    item = next(i for i in char_items(client, player, code)
                if i.get("def_id") == did or i.get("name") == "Testblade")
    equip(client, player, code, ch_id, item["id"])
    return item["id"]


def my_tok(client, player, code):
    st = state_of(client, player, code)
    return next(t["id"] for t in st["tokens"] if t.get("owner_user_id") == st["me"])


def add_npc(client, dm, code, label="Guard"):
    """A tough NPC token right next to the PC's cell (8,6) — melee reach safe,
    100 HP keeps the fake rolls away from death-save flakiness."""
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": label, "x": 475, "y": 325})
        recv_until(ws, "token_add")
    st = state_of(client, dm, code)
    tok = next(t for t in st["tokens"] if t["label"] == label)
    row = db.q1("SELECT npc FROM tokens WHERE id=?", (tok["id"],))
    blk = db.j(row["npc"], {}) or {}
    blk.update({"name": label, "hp": 100, "max_hp": 100, "ac": 25})
    db.x("UPDATE tokens SET npc=? WHERE id=?", (db.json_dumps(blk), tok["id"]))
    return tok


def roll_hit(client, player, code, item_id, target_id):
    """One attack with every die faked to 20 (nat 20 → crit hit for sure);
    returns the damage line payload."""
    with ws_connect(client, player, code) as ws:
        attack(ws, item_id, my_tok(client, player, code), target=target_id)
        for _ in range(30):
            ev = ws.receive_json()
            if ev["kind"] == "dice" and "damage" in str(ev["payload"].get("body", "")):
                return ev["payload"]
    raise AssertionError("no damage line arrived")


def npc_hp(npc_id):
    blk = db.j(db.q1("SELECT npc FROM tokens WHERE id=?", (npc_id,))["npc"], {}) or {}
    return int(blk.get("hp") or 0)


def pending_rows(code, status=None):
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    sql = "SELECT * FROM pending_damage WHERE room_id=?" + (" AND status=?" if status else "")
    args = (rid, status) if status else (rid,)
    return db.q(sql, args)


@pytest.fixture()
def staged(client, monkeypatch):
    """Room with an armed PC and an adjacent NPC; returns (dm, player, code, ch, npc, item_id)."""
    monkeypatch.setattr("app.room.dice.random.randint", lambda a, b: 20)
    dm, player, code, ch = base_room(client)
    npc = add_npc(client, dm, code)
    item_id = armed_pc(client, dm, player, code, ch["id"])
    return dm, player, code, ch, npc, item_id


def test_hit_registers_pending_and_apply_moves_hp(client, staged):
    dm, player, code, ch, npc, item_id = staged
    dmg = roll_hit(client, player, code, item_id, npc["id"])
    assert dmg["meta"]["pending"], "the damage line carries the pending id"
    row = pending_rows(code, "pending")[0]
    assert row["amount"] >= 40                        # crit 2d6 faked at 20 each
    assert row["status"] == "pending" and row["dmg_type"] == "slashing"
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "damage_confirm", "op": "apply",
                       "pending_id": row["id"]})
        assert "Applied" in recv_until(dws, "whisper")["payload"]["text"]
    row2 = pending_rows(code)[0]
    assert row2["status"] == "applied" and row2["hp_after"] is not None
    assert pending_rows(code, "pending") == []
    assert npc_hp(npc["id"]) < 100                     # the HP actually moved


def test_double_apply_applies_once(client, staged):
    dm, player, code, ch, npc, item_id = staged
    pid = roll_hit(client, player, code, item_id, npc["id"])["meta"]["pending"]
    with ws_connect(client, dm, code) as w1, ws_connect(client, dm, code) as w2:
        w1.send_json({"type": "damage_confirm", "op": "apply", "pending_id": pid})
        w2.send_json({"type": "damage_confirm", "op": "apply", "pending_id": pid})
        t1 = recv_until(w1, "whisper")["payload"]["text"]
        t2 = recv_until(w2, "whisper")["payload"]["text"]
    assert ("Applied" in t1) + ("Applied" in t2) == 1          # exactly ONE applied
    assert "already resolved" in (t1 + t2).lower()
    assert pending_rows(code)[0]["status"] == "applied"


def test_failed_mutation_gives_the_claim_back(client, staged, monkeypatch):
    dm, player, code, ch, npc, item_id = staged
    pid = roll_hit(client, player, code, item_id, npc["id"])["meta"]["pending"]
    import app.room.pending as P
    boom = {"n": 0}
    real = P.hp_damage

    async def flaky(*a, **kw):
        boom["n"] += 1
        if boom["n"] == 1:
            raise RuntimeError("simulated mid-apply failure")
        return await real(*a, **kw)
    monkeypatch.setattr(P, "hp_damage", flaky)
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "damage_confirm", "op": "apply", "pending_id": pid})
        err = recv_until(dws, "error", fail_on_error=False)
        assert err["kind"] == "error" and "NOT applied" in err["payload"]["msg"]
    assert pending_rows(code, "pending"), "the claim returned to pending"
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "damage_confirm", "op": "apply", "pending_id": pid})
        assert "Applied" in recv_until(dws, "whisper")["payload"]["text"]
    assert pending_rows(code)[0]["status"] == "applied"        # retry applied ONCE


def test_decline_changes_nothing_but_the_row(client, staged):
    dm, player, code, ch, npc, item_id = staged
    pid = roll_hit(client, player, code, item_id, npc["id"])["meta"]["pending"]
    hp0 = npc_hp(npc["id"])
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "damage_confirm", "op": "decline", "pending_id": pid})
        recv_until(dws, "whisper")
    assert pending_rows(code)[0]["status"] == "declined"
    assert npc_hp(npc["id"]) == hp0


def test_player_confirmation_is_refused_loudly(client, staged):
    dm, player, code, ch, npc, item_id = staged
    pid = roll_hit(client, player, code, item_id, npc["id"])["meta"]["pending"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "damage_confirm", "op": "apply", "pending_id": pid})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert "only" in ev["payload"]["msg"].lower()
    assert pending_rows(code, "pending")                       # untouched


def test_crash_sweep_returns_claimed_but_unnudged_rows():
    from app import db as _db
    _db.init_db()
    pid = _db.x("INSERT INTO pending_damage(room_id, token_id, amount, status) "
                "VALUES (?,?,?,'applied')", (999998, 1, 5))
    _db.init_db()                                              # restart-equivalent
    assert _db.q1("SELECT status FROM pending_damage WHERE id=?", (pid,))["status"] == "pending"
    pid2 = _db.x("INSERT INTO pending_damage(room_id, token_id, amount, status, hp_after) "
                 "VALUES (?,?,?,'applied',20)", (999998, 1, 10))
    _db.init_db()
    assert _db.q1("SELECT status FROM pending_damage WHERE id=?", (pid2,))["status"] == "applied"


def test_ui_button_wired():
    js = open("app/static/js/30_room.js", encoding="utf-8").read()
    assert "damage_confirm" in js and "m.meta.pending" in js
