"""Token CONTROL authority (D82) — the single source of the answer to
"may this user act through this token?".

OWNER      — the logged-in user whose character sheet rides the token.
CONTROLLER — a room member the DM explicitly assigned to act through the
             token (generic companion / familiar / hireling foundation).

A controller may use the token's OPERATIONAL authority: movement, path
preview, the token's own turn (dash/end-turn/turn-mark), conditions and
Stand Up on it, its death saves, casting through it, and adjacency for
doors/world objects. A controller is NOT an owner and NOT an account:
no character-sheet rights, no fog revelation from tokens they do not own
(fog stays owner-scoped), and the DM always keeps full authority. The
assignment is revocable by the DM at any time (`token_controller`).

Every operational authority site asks HERE — the owner idiom is never
re-implemented per-module, so the rule can never drift twice.
"""
from .. import db

TOKEN_COLS = "id, x, y, owner_user_id, controller_user_id, size, fw, fh"


def controls(tok, user_id, is_dm):
    """Owner, assigned controller, or DM."""
    if is_dm:
        return True
    if not tok:
        return False
    return tok.get("owner_user_id") == user_id or tok.get("controller_user_id") == user_id


def controlled_rows(room_id, user_id):
    """Tokens the user owns OR controls — for operational questions
    (adjacency, reach). Fog sources and sheet rights stay owner-scoped."""
    return db.q(f"SELECT {TOKEN_COLS} FROM tokens "
                "WHERE room_id=? AND (owner_user_id=? OR controller_user_id=?)",
                (room_id, user_id, user_id))
