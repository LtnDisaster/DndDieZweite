"""Wall and barrier semantics (D69) — the DM-facing question format for terrain:
"does THIS cell stop movement / stop sight / can it be climbed / how high".

All facts come from mapmodel.TERRAIN (the single source of truth); this module
only queries them for a concrete map cell. Door edges are a separate concept
(mapmodel.blocked_edges) and are deliberately NOT mixed in here, so callers can
ask about painted geometry and open/close state independently.
"""
from . import mapmodel


def _value(mp, x, y):
    # x, y are WORLD cells (D72); conversion is mapmodel's, not ours.
    v = mapmodel.terrain_at(mp, x, y)
    return 1 if v is None else v                              # off-map behaves like wall


def blocks_movement(mp, x, y):
    return mapmodel.blocks_movement(_value(mp, x, y))


def blocks_vision(mp, x, y):
    return mapmodel.blocks_vision(_value(mp, x, y))


def climbable(mp, x, y):
    return mapmodel.terrain(_value(mp, x, y))["climbable"]


def height_units(mp, x, y):
    """Raised height in elevation units (0 = flat, 1 = waist, 2 = wall-high).
    Consumers: elevation rules (D70) and future climb cost."""
    return mapmodel.terrain(_value(mp, x, y))["height"]


def name(mp, x, y):
    return mapmodel.terrain(_value(mp, x, y))["name"]
