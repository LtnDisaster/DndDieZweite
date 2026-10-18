"""D156 (Night-shift 4.0): the help may only talk about UI that exists.

65_help.js names concrete handles in <b>…</b> (buttons, tabs, chips). Every
label must be findable in the shipped UI sources — or, for the entries that
quote server refusals, in the server code that emits them. This gate turns
'help drifts away from reality' from a slow rot into a red test the first
day a button is renamed and the help is not touched.

The second half pins the D153 rule that a fresh client must still reach the
DM surfaces (tab-scoped panels stay reachable after reload/role churn — the
E2E suite walks the same path).
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
HELP = (STATIC / "js" / "65_help.js").read_text(encoding="utf-8")
APP = ROOT / "app"


def _ui_text():
    parts = []
    for js in (STATIC / "js").glob("*.js"):
        if js.name == "55_diorama.js":       # frozen file — never a UI claim target
            continue
        parts.append(js.read_text(encoding="utf-8"))
    parts.append((STATIC / "index.html").read_text(encoding="utf-8"))
    return "\n".join(parts)


def _server_text():
    parts = []
    for py in APP.rglob("*.py"):
        parts.append(py.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_every_bold_help_label_is_a_real_handle():
    ui, server = _ui_text(), _server_text()
    dead = []
    for label in set(re.findall(r"<b>([^<]{1,40})</b>", HELP)):
        probe = label.split("(")[0].strip(" *·").strip()
        if not probe:
            continue
        if probe in ui or probe in server:
            continue
        dead.append(label)
    assert not dead, f"help names handles that exist nowhere: {dead}"


def test_help_ships_its_three_homes_still():
    # guards the overlay surface itself (search box, category rail, list)
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for dom_id in ("help-search", "help-cats", "help-list"):
        assert f'id="{dom_id}"' in html


def test_dm_tab_surface_survives_a_fresh_client():
    # D153 follow-up: the reload-critical DM handles split between the static
    # shell (tab buttons, init, grant) and JS-injected rows (floor picker);
    # the ids the E2E (G2) clicks must exist in exactly one of both worlds.
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    room = (STATIC / "js" / "30_room.js").read_text(encoding="utf-8")
    for dom_id in ("btn-init-start", "inv-grant", "tab-chat"):
        assert f'id="{dom_id}"' in html, dom_id
    for dom_id in ("fl-new", "fl-add", "fl-pick", "fl-go"):
        assert f'id="{dom_id}"' in room, dom_id
    assert 'data-tab="dm"' in html   # the panel hosting fl-* is tab-scoped
