"""D113 (Sprint 42) Phase 7: the canonical 10 ft vertical scale.

One elevation UNIT and one declared FLOOR level both equal exactly 10 ft. This
is a pure geometry/reporting scale — it adds NO height combat and changes NO
movement rule (pathfinding still gates a step on |Δz| <= 1 in units). The tests
pin the scale and the floor-as-height-stack convention, and that the legacy
elevation clamps are untouched.
"""
import pytest
from starlette.testclient import TestClient

from app import db, floors, mapmodel, vertical, main
from tests.test_movement_fog import base_room


@pytest.fixture()
def client():
    return TestClient(main.app)


def rid(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def test_one_unit_and_one_floor_are_ten_feet():
    assert vertical.ELEV_FT == 10 and vertical.FLOOR_FT == 10
    assert vertical.elev_to_ft(0) == 0
    assert vertical.elev_to_ft(1) == 10
    assert vertical.elev_to_ft(-6) == -60            # below primary is negative
    assert vertical.floor_to_ft(0) == 0 and vertical.floor_to_ft(3) == 30
    assert vertical.absolute_ft(vertical.floor_to_ft(2), 3) == 50


def test_declared_floor_order_is_the_height_stack(client):
    dm, player, code, ch = base_room(client)
    r = rid(code)
    assert floors.level(r, "") == 0                   # primary sits at 0 ft
    floors.add(r, "Lower"); floors.add(r, "Upper")
    assert floors.level(r, "Lower") == 1              # 10 ft above primary
    assert floors.level(r, "Upper") == 2              # 10 ft above the previous
    assert floors.absolute_height_ft(r, "Upper", 0) == 20
    assert floors.absolute_height_ft(r, "Upper", 3) == 50   # + ground elevation ×10
    assert floors.absolute_height_ft(r, "", -1) == -10      # a pit one unit below primary


def test_floor_height_follows_declaration_order_after_rename(client):
    dm, player, code, ch = base_room(client)
    r = rid(code)
    floors.add(r, "A"); floors.add(r, "B")
    floors.rename(r, "A", "Attic")                     # order is preserved → levels hold
    assert floors.level(r, "Attic") == 1 and floors.level(r, "B") == 2
    assert floors.absolute_height_ft(r, "B", 0) == 20


def test_legacy_elevation_clamp_is_untouched(client):
    # The scale is reporting only: sanitize still clamps elevation to -6..6 UNITS,
    # it did not turn into feet. A +90 brush value stays +6 units (= 60 ft).
    mp = mapmodel.sanitize({"w": 8, "h": 6, "cell": 50, "cells": [0] * 48, "elev": [90] * 48})
    assert mp["elev"][:3] == [6, 6, 6]
