"""D124: NPC skill proficiencies are visible where the NPC sheet renders."""
from pathlib import Path

from app import npc

ROOM_JS = Path("app/static/js/30_room.js")
CANVAS_JS = Path("app/static/js/50_canvas.js")


def test_npc_block_preserves_projected_skills():
    block = npc.project_creature({
        "id": "wolfkin", "name": "Wolfkin", "skills": "perception, stealth",
    })
    assert block["skills"]["perception"] == 1
    assert block["skills"]["stealth"] == 1


def test_npc_sheet_renders_skills_read_only():
    src = ROOM_JS.read_text(encoding="utf-8")
    assert 'id="npc-skills"' in src
    assert "n.skills || {}" in src
    assert "SKILLS[k] ? SKILLS[k][0] : k" in src
    assert "★★" in src


def test_bestiary_spawn_forwards_the_whole_npc_block_to_the_existing_server():
    src = CANVAS_JS.read_text(encoding="utf-8")
    assert "npc:blk" in src
    assert "darkvision:Math.max" not in src