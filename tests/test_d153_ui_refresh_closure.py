"""D153 (Night-shift 3 E2E): four stale-UI paths the browser suite found by
walking the real buttons — every one of them passed the static audit and the
API tests, and every one left the player looking at dead data:

  1. refreshRoom never re-rendered an OPEN sheet — grants, HP and death
     changes only appeared after clicking the token twice.
  2. The private ally card rendered no death block, so the D150 Stabilize
     button was unreachable for players in practice.
  3. POST /floors updated the state but not the actor's open sheet; the ws
     floors_changed broadcast only reaches the OTHER clients.
  4. presence always did state.online.add() — an offline dot never left the
     #online roster. Only the game log mentioned the disconnect.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOM = (ROOT / "app" / "static" / "js" / "30_room.js").read_text(encoding="utf-8")
WSJS = (ROOT / "app" / "static" / "js" / "40_ws.js").read_text(encoding="utf-8")


def _fn(src, name):
    i = src.index(f"function {name}(")
    return src[i:i + 2600]


def test_refresh_room_repaints_an_open_sheet():
    body = _fn(ROOM, "refreshRoom")
    assert "renderSheet(t)" in body, "stale sheet: open sheet must be repainted"
    # but never over an edited NPC sheet (the editor would eat the keystrokes)
    guard = body[body.index("renderSheet(t)") - 400:body.index("renderSheet(t)")]
    assert "npcEdit" in guard


def test_floor_add_repaints_the_actors_sheet():
    i = ROOM.index('state.floors = j.floors || state.floors;\n                   renderFloorPanel()')
    block = ROOM[i:i + 700]
    assert "renderSheet(st)" in block


def test_presence_set_shrinks_on_disconnect():
    i = WSJS.index('case "presence"')
    block = WSJS[i:i + 360]
    assert "state.online.delete(p.username)" in block
    assert re.search(r"if \(p\.online\)", block)


def test_inv_window_has_its_own_use_path():
    i = ROOM.index('data-a="use" data-id="${it.id}">Use</button>')
    button = ROOM[i - 260:i]
    assert "charges" in button            # same guard as the sheet
    wiring = ROOM[ROOM.index('a === "use"'):]
    assert "use_item" in wiring[:220] and "op_id" in wiring[:220]


def test_no_cjk():
    for src in (ROOM, WSJS):
        assert not re.findall(r"[\u4e00-\u9fff]+", src)
