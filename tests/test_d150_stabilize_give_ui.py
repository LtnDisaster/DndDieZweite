"""D150 (Nachtschicht 3.0, Phase 3): UI closure for two server-only features.

Phase 1's audit found mechanics with tests and handlers but no way to reach
them from the table: D136's Stabilize (death.py) and player-to-player item
hand-off (inv_transfer). Both got a client path. These tests pin the wire
format at the exact level the bugs would live on: the JS must speak the
field names the handlers read — and the Stabilize button must not be
self-targetable (server rule: "You can't stabilize yourself").
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROOM = (ROOT / "app" / "static" / "js" / "30_room.js").read_text(encoding="utf-8")


def _call(type_name):
    m = re.search(rf'wsSend\(\{{ type:"{type_name}"[^}}]*\}}\)', ROOM)
    assert m, f"no wsSend call for {type_name}"
    return m.group(0)


def test_stabilize_button_reaches_the_handler_contract():
    assert 'id="dstab"' in ROOM and 'data-a="give"' in ROOM
    death_block = ROOM[ROOM.index("function deathHtml"):ROOM.index("function wireDeath")]
    assert "mt.id !== tok.id" in death_block        # no self-stabilise offered
    send = _call("stabilize")
    assert "token_id" in send and "target_token_id" in send
    server = (ROOT / "app" / "room" / "death.py").read_text(encoding="utf-8")
    assert '"target_token_id"' in server            # names still agree
    assert "You can't stabilize yourself" in server  # the rule we mirror


def test_give_reaches_the_transfer_contract():
    send = _call("inv_transfer")
    assert "char_id" in send and "to_char_id" in send
    assert "item_id" in send and "qty" in send and "op_id" in send
    server = (ROOT / "app" / "room" / "inv.py").read_text(encoding="utf-8")
    assert '"to_char_id"' in server and "char_id" in server


def test_picker_lives_in_the_sheet_and_resets():
    assert "_giveRowHtml" in ROOM
    assert "give-go" in ROOM and "give-x" in ROOM
    # the pending picker never survives its own send
    tail = ROOM[ROOM.index('$("give-go")'):ROOM.index('$("give-go")') + 700]
    assert "state.giveId = null" in tail


def test_private_card_shares_the_death_block():
    # D153: E2E found the party path dead — the private ally card rendered no
    # death block, so #dstab was DM-only in practice. The card must now carry
    # deathHtml + its wiring; nothing else from the sheet may leak to peers.
    i = ROOM.index('ch.items === undefined && state.room.role !== "dm"')
    card = ROOM[i:i + 900]
    assert "deathHtml(tok)" in card and "wireDeath(tok)" in card
    assert "state.giveId" not in card and "inv-row" not in card


def test_help_advertises_the_new_paths_only_because_they_exist():
    help_t = (ROOT / "app" / "static" / "js" / "65_help.js").read_text(encoding="utf-8")
    assert "🫱 give" in help_t and "Stabilize" in help_t


def test_room_js_has_no_cjk():
    assert not re.findall(r"[\u4e00-\u9fff]+", ROOM)
