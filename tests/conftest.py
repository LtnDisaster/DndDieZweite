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

from app import db, ws  # noqa: E402
from app.room import net  # noqa: E402

db.init_db()


@pytest.fixture(autouse=True)
def _reset_ws_state():
    """Clear transient in-memory hub state between tests (no cross-test bleed)."""
    for mod, name in ((ws, "_clients"), (ws, "_walks"), (ws, "_last_seen"),
                      (net, "_clients"), (net, "_map_locks"), (ws, "_map_locks")):
        d = getattr(mod, name, None)
        if isinstance(d, dict):
            d.clear()
    yield
