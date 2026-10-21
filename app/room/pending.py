"""D162-7 — the pending-damage ledger (audit P2-5 closed honestly).

An attack line says "HIT!" and rolls the damage dice — but HP was only ever
touched when a DM typed the number into the manual hp channel. That left the
dice message and the combat state without a connection. This is the LEDGER in
between: one row per rolled-and-not-yet-applied damage, keyed to the damage
message, resolved by an explicit DM decision (Apply / Decline).

Governance (GO amendment #3):
  * the claim is a single atomic ``UPDATE … WHERE status='pending'`` — two DMs
    clicking Apply concurrently can never apply the damage twice; the loser
    reads ``already resolved``;
  * if the HP mutation itself throws, the row goes BACK to pending and the
    DM is told to retry (a retry is then safe: the claim is re-acquirable);
  * if the process dies between claim and mutation, ``init_db`` sweeps
    claimed-but-unnudged rows (``applied`` with no ``hp_after``) back to
    pending on next start — visible in test;
  * damage is applied ONLY through health.damage (D34): resistance, immunity,
    temp HP, death saves, massive damage are inherited, not reimplemented.
"""
from .. import db
from .health import damage as hp_damage
from .net import send_to, sys_msg


def _update(sql, args=()):
    """UPDATE with a TRUE rowcount (db.x returns lastrowid, which is useless
    for UPDATEs — the claim guard depends on the rowcount, so this goes
    through the connection directly)."""
    c = db.conn()
    n = c.execute(sql, args).rowcount
    c.commit()
    return n


def create(room_id, token_id, amount, dmg_type, attacker, label, crit=False):
    """Register a rolled-but-unapplied damage; returns the pending id."""
    return db.x("INSERT INTO pending_damage(room_id, token_id, amount, dmg_type, "
                "attacker, label, crit) VALUES (?,?,?,?,?,?,?)",
                (room_id, token_id, int(amount), str(dmg_type or "")[:24],
                 str(attacker or "")[:40], str(label or "")[:60], 1 if crit else 0))


def bind_ref(pending_id, message_id):
    db.x("UPDATE pending_damage SET ref_id=? WHERE id=?", (message_id, pending_id))


async def handle_damage_confirm(ws, room_id, user, is_dm, msg):
    """DM-only resolution of one pending row. Loud refusal otherwise."""
    if not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    pid = msg.get("pending_id")
    op = str(msg.get("op") or "").lower()
    if op not in ("apply", "decline"):
        return await send_to(ws, "error", {"msg": "op must be apply or decline"})
    row = db.q1("SELECT * FROM pending_damage WHERE id=? AND room_id=?", (pid, room_id))
    if row is None:
        return await send_to(ws, "error", {"msg": "No such pending damage"})
    if op == "decline":
        n = _update("UPDATE pending_damage SET status='declined', "
                    "resolved_at=datetime('now') WHERE id=? AND status='pending'", (pid,))
        await send_to(ws, "whisper", {"text":
            "— declined." if n else "— already resolved earlier."})
        return
    # ---- the CLAIM: one atomic conditional UPDATE serialises every DM,
    # every tab and every retry. 0 rows claimed = somebody already resolved it.
    claimed = _update("UPDATE pending_damage SET status='applied' "
                      "WHERE id=? AND status='pending'", (pid,))
    if not claimed:
        return await send_to(ws, "whisper",
                             {"text": "That damage was already resolved."})
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (row["token_id"], room_id))
    if tok is None:
        _update("UPDATE pending_damage SET status='declined', "
                "resolved_at=datetime('now') WHERE id=?", (pid,))
        return await send_to(ws, "whisper", {"text":
            "The victim token is gone — damage declined."})
    try:
        res = await hp_damage(room_id, tok, row["amount"], crit=bool(row["crit"]),
                              damage_type=row["dmg_type"] or None) or {}
    except Exception:
        # the mutation failed mid-way: hand the claim back, say so LOUDLY —
        # a retry re-claims and re-applies exactly once.
        _update("UPDATE pending_damage SET status='pending' WHERE id=? AND "
                "status='applied' AND hp_after IS NULL", (pid,))
        return await send_to(ws, "error",
                             {"msg": "Applying that damage failed — it was NOT "
                                     "applied; try again."})
    hp_after = res.get("hp")
    _update("UPDATE pending_damage SET hp_after=?, resolved_at=datetime('now') "
            "WHERE id=?", (hp_after, pid))
    sys_msg(room_id, f"🗡 {tok['label']} takes {row['amount']} "
                     f"{row['dmg_type'] or ''} damage from {row['attacker']}"
                     f"{'' if row['crit'] == 0 else ' (crit)'} — applied.")
    await send_to(ws, "whisper", {"text":
        f"Applied {row['amount']} damage → {tok['label']} at {hp_after} HP."})
