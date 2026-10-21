"""D162-3 — falling. SRD 2024: 1d6 bludgeoning per FULL 10 ft, cap 20d6,
<10 ft is free, landing = prone, damage runs through health.damage (so
resistances/temp HP/death saves apply), and a column without any landing fails
CLOSED. Triggers proven here: move-end support check, prone-while-flying,
an incapacitating state landing mid-air, the DM's token_drop. Natural flight
HOLDS (hover or not); hover does not save you when you are knocked prone and
a stunned flyer falls too (GO amendment #1 — each case tested separately).
"""
import asyncio
import json

import pytest
from starlette.testclient import TestClient

from app import db, mapmodel
from app.room import fall
from tests.test_floor_maps import add_floor, set_floor_grid, state_floor
from tests.test_movement_fog import (H, base_room, recv_until, set_grid,
                                     state_of, ws_connect)

CELL = 50
TOK = (8, 6)                      # base_room's PC token cell


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def client():
    return TestClient(main_app())


def main_app():
    from app import main
    return main.app


def tower_air(client, dm, code):
    """A plane of pure open volume at level +1 (D159 default)."""
    add_floor(client, dm, code, "tower", ground=False)


def place(client, dm, code, tok_id, floor, elev_ft=0):
    db.x("UPDATE tokens SET floor=?, elevation_ft=? WHERE id=?", (floor, elev_ft, tok_id))


def tok_row(tok_id):
    return db.q1("SELECT * FROM tokens WHERE id=?", (tok_id,))


def pc_token(client, player, code):
    st = state_of(client, player, code)
    t = next(t for t in st["tokens"] if t.get("owner_user_id") == st["me"])
    return t["id"]


def make_flyer(client, dm, code, x=TOK[0], y=TOK[1], fly=20, hover=False):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Sky", "x": (x + .5) * CELL,
                      "y": (y + .5) * CELL})
        recv_until(ws, "token_add")
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    row = db.q1("SELECT * FROM tokens WHERE room_id=? AND label='Sky'", (rid,))
    blk = db.j(row["npc"], {}) or {}
    blk.update({"name": "Sky", "fly": fly, "hover": hover, "hp": 40, "ac": 12})
    db.x("UPDATE tokens SET npc=? WHERE id=?", (db.json_dumps(blk), row["id"]))
    return row["id"]


def conds_of(tok_id):
    return {c.get("k") for c in (db.j(tok_row(tok_id)["conds"], []) or [])}


def test_faller_plummet_to_the_ground(client):
    dm, player, code, _ = base_room(client)
    tower_air(client, dm, code)
    tok = pc_token(client, player, code)
    place(client, dm, code, tok, "tower")
    fell = run(fall.resolve_fall(db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"], tok))
    assert fell is True
    row = tok_row(tok)
    assert (row["floor"], row["z"]) == ("", 0)          # landed on primary
    assert int(row["x"]) == int((TOK[0] + .5) * CELL)   # same column
    assert "prone" in conds_of(tok)                     # the landing sprawls
    ch = db.q1("SELECT hp FROM characters WHERE id=?", (row["character_id"],))
    assert 24 <= int(ch["hp"]) <= 29                    # 1d6 bludgeoning off 30
    sys_lines = [m["body"] for m in db.q("SELECT body FROM messages ORDER BY id")]
    assert any("falls 10 ft" in b and "lands prone" in b for b in sys_lines)


def test_natural_flight_holds_hover_or_not(client):
    dm, player, code, _ = base_room(client)
    tower_air(client, dm, code)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    flyer = make_flyer(client, dm, code)               # fly 20, NO hover
    place(client, dm, code, flyer, "tower")
    assert run(fall.resolve_fall(rid, flyer)) is False  # plain flight holds
    assert tok_row(flyer)["floor"] == "tower"
    flyer2 = make_flyer(client, dm, code, x=9, y=6, fly=30, hover=True)
    place(client, dm, code, flyer2, "tower")
    assert run(fall.resolve_fall(rid, flyer2)) is False  # hover holds equally


def test_prone_falls_a_plain_flyer_hover_saves_it(client):
    dm, player, code, _ = base_room(client)
    tower_air(client, dm, code)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    # SRD 2024: prone makes a flyer land or fall; HOVER is the exception.
    plain = make_flyer(client, dm, code, fly=20, hover=False)
    place(client, dm, code, plain, "tower")
    from app.room.conditions import knock_prone
    run(knock_prone(rid, tok_row(plain), actor="test"))    # THE choke
    assert tok_row(plain)["floor"] == ""                   # prone + air = fall
    assert "prone" in conds_of(plain)
    hoverer = make_flyer(client, dm, code, x=9, y=6, fly=20, hover=True)
    place(client, dm, code, hoverer, "tower")
    run(knock_prone(rid, tok_row(hoverer), actor="test"))
    assert tok_row(hoverer)["floor"] == "tower"            # hover holds when prone
    pc = pc_token(client, player, code)                 # grounded PC: no fall
    run(knock_prone(rid, tok_row(pc), actor="test"))
    assert tok_row(pc)["floor"] == "" and tok_row(pc)["x"] == (TOK[0] + .5) * CELL


def test_stun_landing_mid_air_makes_a_flyer_fall(client):
    dm, player, code, _ = base_room(client)
    tower_air(client, dm, code)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    flyer = make_flyer(client, dm, code, fly=40)
    place(client, dm, code, flyer, "tower")
    # the DM panel's condition channel — stun lands, THEN the fall resolves
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "cond_add", "token_id": flyer, "key": "stunned"})
        ev = recv_until(ws, "cond")
        assert "stunned" in json.dumps(ev["payload"])
    row = tok_row(flyer)
    assert row["floor"] == ""                           # let go of the air


def test_no_landing_fails_closed(client):
    dm, player, code, _ = base_room(client)
    tower_air(client, dm, code)
    # a VOID hole under the flyer's column — nothing catches it anywhere
    def hole(g):
        g["cells"][TOK[1] * g["w"] + TOK[0]] = 5             # VOID under the column
    set_grid(client, dm, code, hole)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    flyer = make_flyer(client, dm, code, fly=40)
    place(client, dm, code, flyer, "tower")
    assert run(fall.resolve_fall(rid, flyer)) is False
    assert tok_row(flyer)["floor"] == "tower"           # NOTHING moved


def test_under_ten_feet_hurts_nothing(client):
    dm, player, code, _ = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    tok = pc_token(client, player, code)
    db.x("UPDATE tokens SET elevation_ft=5 WHERE id=?", (tok,))   # a 5-ft hop
    assert run(fall.resolve_fall(rid, tok, forced=True)) is False  # <10 ft, solid below
    ch = db.q1("SELECT hp FROM characters WHERE id=?", (tok_row(tok)["character_id"],))
    assert int(ch["hp"]) == 30


def test_elevation_stack_scales_the_dice(client):
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "tower")               # solid plane at +1 ...
    def stack(g):                                      # ... with a +3 ledge here
        g["elev"][TOK[1] * g["w"] + TOK[0]] = 3
    set_floor_grid(client, dm, code, "tower", stack)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    tok = pc_token(client, player, code)
    place(client, dm, code, tok, "tower")              # solid under → no fall
    db.x("UPDATE tokens SET z=3 WHERE id=?", (tok,))   # stand ON the ledge
    assert run(fall.resolve_fall(rid, tok)) is False
    # now hole the tower cell out: the PC is on nothing, 40 ft above the ground
    def void_cell(g):
        g["cells"][TOK[1] * g["w"] + TOK[0]] = 5
    set_floor_grid(client, dm, code, "tower", void_cell)
    assert run(fall.resolve_fall(rid, tok)) is True
    ch = db.q1("SELECT hp FROM characters WHERE id=?", (tok_row(tok)["character_id"],))
    assert 6 <= int(ch["hp"]) <= 27                    # 4d6 off 30 (40 ft)
    assert tok_row(tok)["floor"] == ""


def test_token_drop_channel(client):
    dm, player, code, _ = base_room(client)
    tower_air(client, dm, code)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    flyer = make_flyer(client, dm, code, fly=40)
    place(client, dm, code, flyer, "tower")
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "token_drop", "token_id": flyer})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert "only" in ev["payload"]["msg"].lower()   # loud DM-only (D162-11)
    assert tok_row(flyer)["floor"] == "tower"
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_drop", "token_id": flyer})
        recv_until(ws, "snapshot")
    row = tok_row(flyer)
    assert any("falls 10 ft" in m["body"] for m in db.q("SELECT body FROM messages ORDER BY id"))
    assert row["floor"] == ""                           # the released flyer lands
    assert "prone" not in conds_of(flyer)               # it lands on its feet


def test_walk_end_trigger_is_hooked():
    mv = open("app/room/movement.py", encoding="utf-8").read()
    assert "from .fall import after_move" in mv
    ui = open("app/static/js/30_room.js", encoding="utf-8").read()
    assert "npc-drop" in ui and "token_drop" in ui   # the DM's Drop button
    kn = open("app/room/conditions.py", encoding="utf-8").read()
    assert kn.count("from .fall import after_condition") >= 2
    dc = open("app/room/dice.py", encoding="utf-8").read()
    assert "from .fall import after_condition" in dc
