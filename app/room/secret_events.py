"""Composed DM secret events: selective narrative plus optional targeted audio."""
import secrets
import time

from .. import db
from . import audio, chat
from .net import send_to, send_user


def _sound_targets(room_id, visibility, recipients):
    if visibility == "public":
        return sorted(_valid_members(room_id))
    return list(recipients)


def _valid_members(room_id):
    return {r["user_id"] for r in db.q("SELECT user_id FROM room_members WHERE room_id=?", (room_id,))}


async def handle_secret_event(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    if not chat._rate_ok(room_id, user["id"], "secret", limit=12, window=10.0):
        await send_to(ws, "error", {"msg": "Secret events are being sent too quickly."})
        return
    text = chat.clean_text(msg.get("text"))
    if not text:
        return
    visibility, recipients = chat._resolve_narrative_target(room_id, msg.get("target", "all"))
    if visibility is None:
        await send_to(ws, "error", {"msg": "Unknown event recipient."})
        return
    sender = await chat._clean_sender(room_id, user, is_dm, msg)
    if sender["error"]:
        await send_to(ws, "error", {"msg": sender["error"]})
        return
    style = chat.clean_style(msg.get("style")) or "overlay"
    await chat.post_chat(
        room_id, user, text=text, channel="narrative", visibility=visibility,
        recipients=recipients, persona=sender["persona"], sender_kind=sender["kind"],
        npc_token_id=sender["npc_token_id"], style=style, kind="narrative", event="narrative",
        meta={"secret_event": True, "overlay": True, "private": visibility != "public"})

    try:
        sid = int(msg.get("sound_id") or msg.get("sound") or 0)
    except (TypeError, ValueError):
        sid = 0
    if sid:
        sound = db.q1("SELECT * FROM soundboard WHERE id=? AND user_id=?", (sid, user["id"]))
        if sound:
            parsed = audio.parse_audio_source(sound["url"])
            if parsed and parsed["kind"] == "direct":
                payload = {
                    "event_id": secrets.token_hex(6),
                    "sound_id": sound["id"],
                    "title": audio._clean_text(sound["name"], 80),
                    "category": sound["category"],
                    "kind": "direct",
                    "url": parsed["url"],
                    "at": time.time(),
                    "secret": True,
                }
                for uid in _sound_targets(room_id, visibility, recipients):
                    await send_user(room_id, uid, "sound", payload)
