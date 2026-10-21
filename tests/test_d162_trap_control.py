"""D162-5/6 — the DM trap channel gets a surface, traps/loot get a delete.

D161 P2-1/P2-2: the server always let the DM search/disarm/spring ANY cell —
but the traphud needs ownToken(), so a DM with no token had NO control at all;
and traps/loot could only be "removed" by re-painting over them (silent
overwrite) or demolishing the whole cell with erase. D162 adds: the 🎲 DM tab
trap panel (search/disarm/spring/remove for any cell) plus editor brushes
traprm/lootrm, and the live map_remove op — DM-only, LOUD refusal, scoped to
exactly one plane, whisper confirmation, map_changed broadcast."""
import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_floor_maps import add_floor, set_floor_grid, state_floor
from tests.test_movement_fog import (base_room, recv_until, set_grid, state_of,
                                     ws_connect)


@pytest.fixture()
def client():
    return TestClient(main.app)


def place_trap(client, dm, code, x, y, floor="", label="Needle"):
    def mutate(g):
        g["traps"] = (g.get("traps") or []) + [
            {"id": f"t{label}{x}{y}{floor}", "x": x, "y": y, "label": label,
             "dc": 12, "dmg": "1d4", "discovered": False}]
    if floor:
        set_floor_grid(client, dm, code, floor, mutate)
    else:
        set_grid(client, dm, code, mutate)


def traps_of(client, dm, code, floor=""):
    grid = (state_floor(client, dm, code, floor) if floor
            else state_of(client, dm, code))["grid"]
    return grid.get("traps") or []


def test_player_map_remove_is_loudly_refused(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "map_remove", "kind": "trap", "x": 5, "y": 5})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert ev["kind"] == "error" and "only" in ev["payload"]["msg"].lower()


def test_dm_removes_trap_and_it_persists(client):
    dm, player, code, _ = base_room(client)
    place_trap(client, dm, code, 5, 5)
    assert traps_of(client, dm, code)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_remove", "kind": "trap", "x": 5, "y": 5})
        assert recv_until(ws, "whisper")["payload"]["msg"].lower().count("trap")
        recv_until(ws, "map_changed")
    assert traps_of(client, dm, code) == []
    # authoritative reload: a fresh connection and a plain REST read agree
    with ws_connect(client, dm, code) as ws2:
        pass
    assert traps_of(client, dm, code) == []


def test_removal_is_plane_scoped(client):
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "crypt")
    place_trap(client, dm, code, 6, 6, floor="", label="Up")
    place_trap(client, dm, code, 6, 6, floor="crypt", label="Down")
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_remove", "kind": "trap", "x": 6, "y": 6})  # primary only
        recv_until(ws, "map_changed")
    assert traps_of(client, dm, code) == []
    assert len(traps_of(client, dm, code, "crypt")) == 1     # crypt untouched


def test_removal_of_empty_cell_answers_error(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_remove", "kind": "loot", "x": 2, "y": 2})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert ev["kind"] == "error" and "nothing" in ev["payload"]["msg"].lower()


def test_runtime_flags_of_survivors_are_kept(client):
    dm, player, code, _ = base_room(client)
    def mutate(g):
        g["traps"] = [
            {"id": "tA", "x": 5, "y": 5, "label": "A", "dc": 12, "dmg": "1d4",
             "discovered": True, "triggered": True, "disarmed": True},
            {"id": "tB", "x": 6, "y": 6, "label": "B", "dc": 12, "dmg": "1d4",
             "discovered": False}]
    set_grid(client, dm, code, mutate)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_remove", "kind": "trap", "x": 5, "y": 5})
        recv_until(ws, "map_changed")
    tr = traps_of(client, dm, code)
    assert [t["id"] for t in tr] == ["tB"]                   # only tA removed


def test_loot_removal_flow(client):
    dm, player, code, _ = base_room(client)
    def mutate(g):
        g["loot"] = [{"id": "lA", "x": 7, "y": 7, "label": "Coin purse",
                      "taken_by": None, "container": 0}]
    set_grid(client, dm, code, mutate)
    grid = state_of(client, dm, code)["grid"]
    assert grid.get("loot")
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_remove", "kind": "loot", "x": 7, "y": 7})
        recv_until(ws, "map_changed")
    assert state_of(client, dm, code)["grid"].get("loot", []) == []


def read(p):
    return open(p, encoding="utf-8").read()


def test_editor_got_the_delete_brushes():
    canvas = read("app/static/js/50_canvas.js")
    assert 'b === "traprm"' in canvas and 'b === "lootrm"' in canvas
    html = read("app/static/index.html")
    assert 'data-b="traprm"' in html and 'data-b="lootrm"' in html


def test_dm_trap_panel_wired():
    html = read("app/static/index.html")
    assert 'id="trappanel"' in html and 'data-tab="dm"' in html
    for b in ["tdm-search", "tdm-disarm", "tdm-trigger", "tdm-remove"]:
        assert f'id="{b}"' in html
    js = read("app/static/js/60_main.js")
    assert '"map_remove"' in js and 'type: "trap"' in js
    room = read("app/static/js/30_room.js")
    assert "renderTrapPanel" in room
