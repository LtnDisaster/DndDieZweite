"""Sprint 22 (D92): world containers — fill, inspect, loot, put; leaks, planes.

Containers reuse the D82 interactable framework (map-object authoring, fog
transmission, dm_only semantics, same-plane reach) but their CONTENTS live in
SQLite and travel exclusively through authorised inv_container exchanges:
never in map JSON, never in /state, never broadcast. A cross-plane probe
answers like an empty world (silent), out-of-range answers explicitly, a
dm_only chest answers "isn't here". Double- and concurrent-takes of the last
item are serialised on the database — the sum of items never changes.
"""
import threading

import pytest
from starlette.testclient import TestClient

from app import db, inventory as INV, main
from tests.test_movement_fog import (H, base_room, join_room, make_char,
                                     recv_kinds_until, recv_until, reg,
                                     set_grid, state_of, ws_connect)


@pytest.fixture()
def client():
    return TestClient(main.app)


CELL = 50


def _chest(id="chest", x=12, y=12, label="Old Chest", act="Open Chest", **kw):
    o = {"id": id, "x": x, "y": y, "label": label, **kw}
    o["interact"] = {"label": act, "op": {"kind": "container"}}
    return o


def _tok_cell(client, user, code):
    me = user["name"]
    st = state_of(client, user, code)
    uid = st["me"]
    tok = next(t for t in st["tokens"] if t.get("owner_user_id") == uid)
    return int(tok["x"] // CELL), int(tok["y"] // CELL)


def _chest_at_player(client, dm, player, code, cid="chest"):
    cx, cy = _tok_cell(client, player, code)
    set_grid(client, dm, code, lambda g: g["objects"].append(_chest(id=cid, x=cx, y=cy)))
    return cx, cy


def _make_def_fill(ws, code, cid, name, qty, stack=True):
    ws.send_json({"type": "item_def", "action": "create",
                  "defn": {"name": name, "kind": "other", "stackable": stack}})
    recv_until(ws, "whisper")
    # the def id comes back through /state — fetch it, then fill the chest
    return name, qty


def _fill(client, dm, code, cid, name, qty, floor=""):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "item_def", "action": "create",
                      "defn": {"name": name, "kind": "other", "stackable": True}})
        recv_until(ws, "whisper")
    did = next(d["id"] for d in state_of(client, dm, code)["item_defs"]
               if d["name"] == name)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "inv_container", "action": "fill", "object_id": cid,
                      "def_id": did, "qty": qty, "floor": floor})
        return recv_until(ws, "inv_contents")["payload"]


def _items(client, user, code):
    st = client.get(f"/api/rooms/{code}/state", headers=H(user)).json()
    return st["characters"][0]["items"]


# ---------- transmission: contents never leak ----------

def test_chest_visible_without_contents_and_persists(client):
    dm, player, code, _ = base_room(client)
    _chest_at_player(client, dm, player, code)
    _fill(client, dm, code, "chest", "Trail Rations", 4)
    st = state_of(client, player, code)
    ch_obj = next(o for o in st["grid"]["objects"] if o["id"] == "chest")
    assert ch_obj["interact"]["kind"] == "container"
    assert "items" not in ch_obj and "items" not in str(st["item_defs"])
    assert "Trail Rations" not in str(st["grid"])        # nothing in the map
    # contents are DB truth and survive every refetch ("reconnect")
    row = db.q1("SELECT items FROM containers WHERE object_id=?", ("chest",))
    assert db.j(row["items"], [])[0]["qty"] == 4
    assert state_of(client, player, code)["grid"]["objects"]


def test_dm_only_chest_never_revealed(client):
    dm, player, code, _ = base_room(client)
    cx, cy = _tok_cell(client, player, code)
    set_grid(client, dm, code,
             lambda g: g["objects"].append(_chest(id="secret", x=cx, y=cy, dm_only=True)))
    st = state_of(client, player, code)
    assert "secret" not in [o["id"] for o in st["grid"]["objects"]]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_container", "action": "inspect", "object_id": "secret"})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert "isn't here" in ev["payload"]["msg"]      # no contents, no details
    # DM still sees it (server truth for the DM branch)
    assert "secret" in [o["id"] for o in state_of(client, dm, code)["grid"]["objects"]]


# ---------- the loot flow ----------

def test_fill_inspect_take_put_flow(client):
    dm, player, code, ch = base_room(client)
    _chest_at_player(client, dm, player, code)
    contents = _fill(client, dm, code, "chest", "Gold Piece", 5)
    gp = contents["items"][0]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_container", "action": "inspect", "object_id": "chest"})
        got = recv_until(ws, "inv_contents")["payload"]
        assert got["items"][0]["qty"] == 5 and got["label"] == "Old Chest"
        ws.send_json({"type": "inv_container", "action": "move", "object_id": "chest",
                      "char_id": ch["id"], "item_id": gp["id"], "qty": 2})
        after = recv_until(ws, "inv_contents")["payload"]["items"]
        assert after[0]["qty"] == 3                       # chest side
        assert _items(client, player, code)[0]["qty"] == 2   # char side
        # put one back — same message, direction decided server-side
        held = _items(client, player, code)[0]["id"]
        ws.send_json({"type": "inv_container", "action": "move", "object_id": "chest",
                      "char_id": ch["id"], "item_id": held, "qty": 1})
        back = recv_until(ws, "inv_contents")["payload"]["items"]
        assert back[0]["qty"] == 4
    assert _items(client, player, code)[0]["qty"] == 1


def test_double_take_of_last_item_cannot_duplicate(client):
    dm, player, code, ch = base_room(client)
    _chest_at_player(client, dm, player, code)
    gp = _fill(client, dm, code, "chest", "Single Gem", 1)["items"][0]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_container", "action": "move", "object_id": "chest",
                      "char_id": ch["id"], "item_id": gp["id"], "qty": 1})
        recv_until(ws, "inv_contents")
        assert _items(client, player, code)[0]["qty"] == 1
        ws.send_json({"type": "inv_container", "action": "move", "object_id": "chest",
                      "char_id": ch["id"], "item_id": gp["id"], "qty": 1})
        assert "error" == recv_until(ws, "error", fail_on_error=False)["kind"]
    assert _items(client, player, code)[0]["qty"] == 1  # not 2


def test_concurrent_take_threads_serialise_on_db(client):
    # real parallelism at the SSOT layer: one 1× gem, two racing takers
    dm, player, code, ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    INV.container_fill(rid, "race", [{"name": "Gem", "kind": "other", "qty": 1}])
    gem = INV.container_peek(rid, "race")[0]["id"]
    results = []

    def take():
        try:
            results.append(INV.container_move(rid, "race", ch["id"], gem, 1))
        except INV.InvError as ex:
            results.append(f"refused:{ex}")

    ts = [threading.Thread(target=take) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    moved = [r for r in results if isinstance(r, dict)]
    refused = [r for r in results if isinstance(r, str)]
    assert len(moved) == 1 and len(refused) == 1
    cont_qty = sum(i["qty"] for i in INV.container_peek(rid, "race"))
    row = db.q1("SELECT items FROM characters WHERE id=?", (ch["id"],))
    char_qty = sum(i["qty"] for i in db.j(row["items"], []))
    assert cont_qty + char_qty == 1                       # conservation


def test_replayed_take_is_a_noop(client):
    dm, player, code, ch = base_room(client)
    _chest_at_player(client, dm, player, code)
    gp = _fill(client, dm, code, "chest", "Coin Purse", 3)["items"][0]
    with ws_connect(client, player, code) as ws:
        msg = {"type": "inv_container", "action": "move", "object_id": "chest",
               "char_id": ch["id"], "item_id": gp["id"], "qty": 1, "op_id": "loot-1"}
        ws.send_json(msg)
        recv_until(ws, "inv_contents")
        ws.send_json(msg)                                   # wire-level replay
        assert "already applied" in recv_until(ws, "whisper")["payload"]["text"]
    assert _items(client, player, code)[0]["qty"] == 1   # not 2
    assert db.q1("SELECT items FROM containers WHERE object_id=?", ("chest",))


# ---------- reach and planes ----------

def test_out_of_range_refused(client):
    dm, player, code, ch = base_room(client)
    set_grid(client, dm, code, lambda g: g["objects"].append(_chest(id="far", x=2, y=2)))
    _fill(client, dm, code, "far", "Band", 1)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_container", "action": "inspect", "object_id": "far"})
        assert "Walk up" in recv_until(ws, "error", fail_on_error=False)["payload"]["msg"]


def test_cross_plane_probe_answers_like_an_empty_world(client):
    dm, player, code, ch = base_room(client)
    _chest_at_player(client, dm, player, code, cid="here")
    _fill(client, dm, code, "here", "Token", 1)
    client.post(f"/api/rooms/{code}/floors", json={"name": "tower"}, headers=H(dm))
    # DM authors + fills a chest on the TOWER plane
    grid = client.get(f"/api/rooms/{code}/state?floor=tower", headers=H(dm)).json()["grid"]
    grid["objects"].append(_chest(id="up", x=14, y=14))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": grid, "floor": "tower"})
        recv_until(ws, "map_changed")
    _fill(client, dm, code, "up", "Tower Loot", 9, floor="tower")
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_container", "action": "inspect",
                      "object_id": "up", "floor": "tower"})
        ws.send_json({"type": "chat", "text": "ping", "channel": "global"})
        seen = recv_kinds_until(ws, "chat")
        assert "inv_contents" not in seen                  # silent: nothing there
        # sanity: the SAME player CAN inspect the chest on his own plane
        ws.send_json({"type": "inv_container", "action": "inspect", "object_id": "here"})
        got = recv_until(ws, "inv_contents")["payload"]
        assert got["items"][0]["name"] == "Token"


def test_walked_up_after_climbing(client):
    dm, player, code, ch = base_room(client)
    _chest_at_player(client, dm, player, code, cid="here")
    _fill(client, dm, code, "here", "Token", 1)
    cx, cy = _tok_cell(client, player, code)
    # move the chest AWAY from the token — reach is by position, not memory
    set_grid(client, dm, code, lambda g: g["objects"].__setitem__(
        0, {**g["objects"][0], "x": 1, "y": 1}))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_container", "action": "inspect", "object_id": "here"})
        assert "Walk up" in recv_until(ws, "error", fail_on_error=False)["payload"]["msg"]


def test_unknown_object_is_a_silent_noop(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_container", "action": "move", "object_id": "ghost",
                      "char_id": ch["id"], "item_id": "x", "qty": 1})
        ws.send_json({"type": "chat", "text": "ping", "channel": "global"})
        assert "inv_contents" not in recv_kinds_until(ws, "chat")


def test_player_may_not_fill_or_empty_direcly(client):
    dm, player, code, ch = base_room(client)
    _chest_at_player(client, dm, player, code)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_container", "action": "fill", "object_id": "chest",
                      "item": {"name": "Fake Gold", "kind": "other"}, "qty": 99})
        assert "DM only" in recv_until(ws, "error", fail_on_error=False)["payload"]["msg"]
        ws.send_json({"type": "inv_container", "action": "remove", "object_id": "chest",
                      "item_id": "x", "qty": 1})
        assert "DM only" in recv_until(ws, "error", fail_on_error=False)["payload"]["msg"]
