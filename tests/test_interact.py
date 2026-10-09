"""D82: generic interactable world objects.

Pins: the object schema is DATA with an ALLOWLIST of operations (unknown ops
never reach the executor, sanitization drops them); players receive label+kind
only — never the linked door position; dm_only and secret links refuse players
without leaking; adjacency gates players (door precedent); toggle flips and
PERSISTS the generic state (surviving stale editor map_edit merges); the door
link reuses the ONE door lifecycle (reveal + chronicle + event); and no
executable code path exists anywhere in the feature.
"""
import pathlib
import re

import pytest
from starlette.testclient import TestClient

from app import main, mapmodel


@pytest.fixture()
def client():
    return TestClient(main.app)
from tests.test_movement_fog import base_room, recv_until, set_grid, state_of, ws_connect

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _mp():
    return mapmodel.default_map()


def _obj(id="lever", x=12, y=12, label="Rusty Lever", act="Pull Lever", op=None, **kw):
    o = {"id": id, "x": x, "y": y, "label": label, **kw}
    if op is not None:
        o["interact"] = {"label": act, "op": op}
    return o


def _door(id="d1", x=9, y=7, dir_="v", **kw):
    return {"id": id, "x": x, "y": y, "dir": dir_, "closed": kw.get("closed", True),
            "locked": kw.get("locked", False), "dm_only": kw.get("dm_only", False),
            "secret": kw.get("secret", False), "label": "Door"}


# ---------- the schema is data, not code ----------

def test_sanitize_keeps_allowlisted_ops_and_drops_everything_else():
    mp = _mp()
    mp["objects"] = [
        _obj(op={"kind": "toggle"}),
        _obj(id="sw", op={"kind": "door", "x": 9, "y": 7, "dir": "v"}),
        _obj(id="bad", op={"kind": "python-eval", "expr": "__import__('os')"}),
        _obj(id="baddoor", op={"kind": "door", "x": 9, "y": 7, "dir": "sideways"}),
        _obj(id="plain"),
    ]
    mp["doors"] = [_door()]
    out = mapmodel.sanitize(mp)
    by_id = {o["id"]: o for o in out["objects"]}
    assert by_id["lever"]["interact"]["op"] == {"kind": "toggle"}
    assert by_id["sw"]["interact"]["op"] == {"kind": "door", "x": 9, "y": 7, "dir": "v"}
    assert "interact" not in by_id["bad"]           # unknown op -> decoration
    assert "interact" not in by_id["baddoor"]       # bad door anchor -> decoration
    assert "interact" not in by_id["plain"]
    assert all("expr" not in str(o) for o in out["objects"])


def test_sanitize_clamps_and_uniquifies():
    mp = _mp()
    mp["objects"] = [_obj(x=9999, y=-9999), _obj(x=1, y=1), _obj(x=2, y=2)]   # duplicate ids
    out = mapmodel.sanitize(mp)
    ids = [o["id"] for o in out["objects"]]
    assert len(ids) == len(set(ids))
    o0 = out["objects"][0]
    assert 0 <= o0["x"] < out["w"] and 0 <= o0["y"] < out["h"]


def test_players_get_label_and_kind_only_never_the_link():
    mp = _mp()
    mp["objects"] = [_obj(id="lev", x=5, y=5, op={"kind": "door", "x": 15, "y": 15, "dir": "v"}),
                     _obj(id="secret", x=6, y=6, op={"kind": "toggle"}, dm_only=True)]
    mp["explored"][5 * mp["w"] + 5] = 1
    view = mapmodel.visible_map(mp, user_id=7, is_dm=False, visible_cells=())
    by_id = {o["id"]: o for o in view["objects"]}
    assert "lev" in by_id
    assert by_id["lev"]["interact"] == {"label": "Pull Lever", "kind": "door"}
    assert "op" not in str(by_id["lev"])            # door position NEVER travels (D59-style)
    assert "secret" not in by_id                    # dm_only never transmitted


# ---------- the live operation ----------

def _place(client, dm, code, objects, doors=None):
    def mutate(g):
        g.setdefault("objects", []).extend(objects)
        if doors:
            g.setdefault("doors", []).extend(doors)
    set_grid(client, dm, code, mutate)


def test_toggle_requires_reach_then_flips_and_persists(client):
    dm, player, code, _ = base_room(client)                    # pc token sits at (8,6)
    _place(client, dm, code, [_obj(id="far", x=15, y=15, op={"kind": "toggle"}),
                              _obj(id="near", x=8, y=7, op={"kind": "toggle"})])
    pst = state_of(client, player, code)
    mine = next(t["id"] for t in pst["tokens"] if t["owner_user_id"] == pst["me"])
    assert any(o["id"] == "near" and o["interact"]["kind"] == "toggle"
               for o in pst["grid"]["objects"])                # visible + labeled
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "interact", "object_id": "far"})  # far away
        err = recv_until(ws, "error", fail_on_error=False)
        assert "walk up" in err["payload"]["msg"].lower()
        ws.send_json({"type": "interact", "object_id": "nonexistent"})   # unknown id: silent
        ws.send_json({"type": "interact", "object_id": "near"})
        ev = recv_until(ws, "object_state")
        assert ev["payload"] == {"object_id": "near", "state": {"on": True}}
    st = state_of(client, dm, code)
    obj = next(o for o in st["grid"]["objects"] if o["id"] == "near")
    assert obj["state"] == {"on": True}                        # persisted in the map
    # toggling again flips back (state rides /state too)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "interact", "object_id": "near"})
        assert recv_until(ws, "object_state")["payload"]["state"] == {"on": False}


def test_dm_only_object_refuses_players(client):
    dm, player, code, _ = base_room(client)
    _place(client, dm, code, [_obj(id="hidden_console", x=8, y=7,
                                   op={"kind": "toggle"}, dm_only=True)])
    assert not any(o["id"] == "hidden_console"
                   for o in state_of(client, player, code)["grid"]["objects"])
    with ws_connect(client, player, code) as ws:               # even knowing the id
        ws.send_json({"type": "interact", "object_id": "hidden_console"})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "won't budge" in err["payload"]["msg"].lower()


def test_plain_object_has_nothing_to_do(client):
    dm, player, code, _ = base_room(client)
    _place(client, dm, code, [_obj(id="deco", x=8, y=7)])      # no interact
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "interact", "object_id": "deco"})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "nothing to do" in err["payload"]["msg"].lower()


def test_door_link_flips_through_the_shared_door_lifecycle(client):
    dm, player, code, _ = base_room(client)
    _place(client, dm, code, [_obj(id="lev", x=8, y=7, op={"kind": "door", "x": 9, "y": 7, "dir": "v"})],
           doors=[_door(x=9, y=7)])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "interact", "object_id": "lev"})
        recv_until(ws, "map_changed")                          # the door's own broadcast
    st = state_of(client, dm, code)
    door = next(d for d in st["grid"]["doors"] if d["id"] == "d1")
    assert door["closed"] is False                             # opened by the lever
    assert any("door swings open" in m.get("body", "") for m in st["messages"])
    # close it again via the same lever
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "interact", "object_id": "lev"})
        recv_until(ws, "map_changed")
    st = state_of(client, dm, code)
    assert next(d for d in st["grid"]["doors"] if d["id"] == "d1")["closed"] is True


def test_locked_and_secret_links_refuse_players_without_leaks(client):
    dm, player, code, _ = base_room(client)
    _place(client, dm, code,
           [_obj(id="locklev", x=8, y=7, op={"kind": "door", "x": 9, "y": 7, "dir": "v"}),
            _obj(id="seclev", x=7, y=7, op={"kind": "door", "x": 9, "y": 8, "dir": "v"})],
           doors=[_door(x=9, y=7, locked=True), _door(id="d2", x=9, y=8, secret=True)])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "interact", "object_id": "locklev"})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "won't budge" in err["payload"]["msg"].lower()
        ws.send_json({"type": "interact", "object_id": "seclev"})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "nothing happens" in err["payload"]["msg"].lower()
    st = state_of(client, player, code)
    assert not any(d["id"] == "d2" for d in st["grid"]["doors"])     # no secret leak
    door = next(d for d in state_of(client, dm, code)["grid"]["doors"] if d["id"] == "d1")
    assert door["closed"] and door["locked"]                          # untouched


def test_runtime_state_survives_a_stale_editor_snapshot(client):
    dm, player, code, _ = base_room(client)
    _place(client, dm, code, [_obj(id="lev", x=8, y=7, op={"kind": "toggle"})])
    stale = state_of(client, dm, code)["grid"]                 # editor snapshot, pre-toggle
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "interact", "object_id": "lev"})
        recv_until(ws, "object_state")
    with ws_connect(client, dm, code) as dws:                  # DM saves the STALE map
        dws.send_json({"type": "map_edit", "map": stale})
        recv_until(dws, "map_changed")
    obj = next(o for o in state_of(client, dm, code)["grid"]["objects"] if o["id"] == "lev")
    assert obj["state"] == {"on": True}                        # merge kept the runtime state


def test_no_executable_code_path_anywhere():
    """Static guard: the feature is DATA -> allowlisted ops. Nothing here may
    evaluate strings as code, and the op kinds are exactly the allowlist."""
    for rel in ("app/room/interact.py", "app/mapmodel.py"):
        src = (ROOT / rel).read_text()
        # (?<![.\w]) lets legit `re.compile(` pass but catches bare eval/exec/
        # compile/__import__ calls — the execution paths this feature forbids.
        assert not re.search(r"(?<![.\w])(eval|exec|compile|__import__)\s*\(", src), rel
    assert mapmodel.INTERACT_OPS == ("toggle", "door", "stair", "lamp", "container")  # D88/89 + D92
