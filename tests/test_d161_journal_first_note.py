"""D161 (play-session audit, Phase 4): a DM with an EMPTY journal could never
create the first entry.

``loadNotes`` short-circuited on ``!state.notes.length`` by HIDING
``#note-panel`` — but the New/Save buttons live INSIDE that panel, so with
zero entries the editor (and its only entry point) was unreachable: the
first journal note could not be created through the UI at all. Reproduced
live in the DM browser: ``#note-panel`` stayed ``.hidden`` and the note
editors timed out.

Fix: still render the (empty) note panel through ``renderNote(role)`` —
which shows it and applies the DM-only editability, so players still see a
read-only surface.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOM = (ROOT / "app" / "static" / "js" / "30_room.js").read_text(encoding="utf-8")


def _fn(name):
    i = ROOM.index(f"function {name}(")
    j = ROOM.index("\nfunction ", i + 1)
    return ROOM[i:j]


def test_empty_journal_keeps_editor_reachable():
    body = _fn("loadNotes")
    empty = body.split("!state.notes.length")[1].split("; }")[0]
    assert 'classList.add("hidden")' not in empty, \
        "empty journal must not hide the note editor — New/Save live in it"
    assert "renderNote(role)" in empty, \
        "empty path must still apply role-based editability via renderNote"


def test_note_panel_is_hidden_only_when_the_whole_journal_tab_is_inactive():
    # the only legitimate hider of #note-panel was the empty-journal bug
    assert ROOM.count('$("note-panel").classList.add("hidden")') == 0
