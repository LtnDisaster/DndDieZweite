"""D160 — performance probe for the cross-plane sight hot path.

There is no sight CACHE to go stale (delivery recomputes from the live map every
time), so the real cost is recomputation: ``maps_for`` reloads every plane per
delivery, and ``observable_cells`` runs the shaft/column maths per token. These
timings go into docs/QUALITY_GATE_D160.md. The asserts are deliberately loose —
they guard against pathological blow-up, not pin a CI benchmark.
"""
import time

import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app
from app.room import vertical3d
from tests.test_movement_fog import H, base_room


@pytest.fixture()
def client():
    return TestClient(app)


def _add(client, dm, code, n):
    assert client.post(f"/api/rooms/{code}/floors", json={"name": n},
                       headers=H(dm)).status_code == 200


def test_cross_plane_sight_perf(client):
    dm, _, code, _ = base_room(client)
    planes = [f"P{i}" for i in range(8)]                 # the MAX_FLOORS worst case
    for n in planes:
        _add(client, dm, code, n)
    r = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    maps, lm = vertical3d.maps_for(r), vertical3d.level_map(r)
    w, h, cell = maps[""]["w"], maps[""]["h"], maps[""]["cell"]

    t = time.perf_counter()
    for _ in range(20):
        vertical3d.maps_for(r)
    maps_ms = (time.perf_counter() - t) / 20 * 1000

    def tok(plane, cx, cy):
        return {"id": 1, "room_id": r, "floor": plane, "size": "Medium",
                "x": (cx + .5) * cell, "y": (cy + .5) * cell, "z": 0,
                "height_ft": None, "elevation_ft": 0}

    viewer = planes[0]
    per_token = {}
    for n in (1, 50, 200):
        toks = [tok(planes[i % 8], i % w, (i * 3) % h) for i in range(n)]
        t = time.perf_counter()
        for tk in toks:
            vertical3d.observable_cells(r, tk, viewer, maps, lm)
        per_token[n] = (time.perf_counter() - t) * 1000 / n

    print(f"\nD160 PERF maps_for({len(maps)} planes) = {maps_ms:.2f} ms/call")
    for n, ms in per_token.items():
        print(f"D160 PERF observable_cells n={n:3d}: {ms:.4f} ms/token (cached maps)")

    assert maps_ms < 100, "maps_for must not blow up with plane count"
    assert per_token[200] < 5, "per-token cross-plane sight must stay sub-millisecond-ish"
