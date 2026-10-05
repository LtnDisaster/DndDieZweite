import os
import pathlib
import sys
import tempfile

# Point the app at an isolated data dir BEFORE importing it, so tests never touch
# the developer's real ./data (db + secret.key). db reads VTT_DATA_DIR at import.
_TMP = tempfile.mkdtemp(prefix="vtt-test-")
os.environ.setdefault("VTT_DATA_DIR", _TMP)

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pytest  # noqa: E402

import bcrypt  # noqa: E402

from app import abilities, db, events, ratelimit, ws  # noqa: E402
from app.room import audio, chat, net  # noqa: E402

db.init_db()


@pytest.fixture(autouse=True, scope="session")
def _fast_bcrypt():
    """Tests exercise REAL bcrypt hashing, but at cost factor 4 (~5 ms).

    Production keeps the bcrypt default (rounds=12). On this Python build,
    back-to-back rounds=12 hashes through TestClient's portal occasionally
    deadlocks inside bcrypt's C call (faulthandler: thread stuck in
    auth.hash_pw). The 100x cheaper test cost keeps the real code path and
    removes the stall window; correctness of hash/verify is unaffected.
    """
    real = bcrypt.gensalt
    bcrypt.gensalt = lambda *a, **k: real(rounds=4)
    yield
    bcrypt.gensalt = real


@pytest.fixture(autouse=True)
def _reset_ws_state():
    """Clear transient in-memory hub state between tests (no cross-test bleed)."""
    for mod, name in ((ws, "_clients"), (ws, "_walks"), (ws, "_last_seen"),
                      (net, "_clients"), (net, "_map_locks"), (ws, "_map_locks")):
        d = getattr(mod, name, None)
        if isinstance(d, dict):
            d.clear()
    ratelimit._hits.clear()
    audio.clear_rate_state()
    chat.clear_rate_state()
    events.clear()
    abilities.clear_registry()
    yield
