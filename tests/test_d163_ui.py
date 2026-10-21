"""D163 — the UI surfaces the new CSV mechanics ride (static pins, D162-style).

Behaviour lives in test_d163_lootquest.py (roll_loot via WS) and
test_d163_prepare.py (spell_prepare via WS); this file pins that a REAL
surface exists for each: a DM button that sends the action, checkboxes that
drive preparation, and the guided 2024 ASI pickers in the build sheet.
"""


def read(p):
    return open(p, encoding="utf-8").read()


def test_dm_loot_roll_panel_wired():
    html = read("app/static/index.html")
    for i in ["loot-group", "loot-tbl", "btn-loot-refresh", "btn-loot-roll"]:
        assert f'id="{i}"' in html
    js = read("app/static/js/60_main.js")
    assert 'type: "roll_loot"' in js                  # real WS action
    assert "export?kind=loottable" in js              # list comes from CSV content
    # the dispatch maps the action for every client, not just the API
    from app.room import dispatch
    assert dispatch.HANDLERS["roll_loot"].__module__.endswith("loot")


def test_prepared_list_checkbox_sends_spell_prepare():
    room = read("app/static/js/30_room.js")
    assert 'class="prep-sp"' in room and 'type: "spell_prepare"' in room


def test_asi_2024_ui_in_build_sheet():
    prep = read("app/static/js/80_prep.js")
    assert "pw-asi-mode" in prep and "plus2_plus1" in prep
    assert "pw-asi-t" in prep                         # the three-x-+1 picker too
