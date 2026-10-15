"""D113 Phase 7 — the ONE canonical vertical scale.

One `elev` map layer UNIT (mapmodel's -6..6 per-cell elevation) and one declared
FLOOR level (floors.py, primary = 0) both equal EXACTLY 10 ft. This module is a
pure scale/reporting contract: it introduces NO height combat (no fall damage,
no elevation cover, no fly/swim/climb cost — those stay the D70/D83 deliberate
out-of-scope edge), NO new movement rule, and touches the Diorama renderer not
at all. Pathfinding keeps gating a step on |Δz| <= 1 in UNITS (unchanged); the
feet value here is what a unit MEANS, not a second geometry.
"""

ELEV_FT = 10          # one elevation unit = 10 ft
FLOOR_FT = 10         # one declared floor level = 10 ft


def elev_to_ft(units):
    """Feet for an elevation unit count (sign preserved; below-primary is negative)."""
    return int(units) * ELEV_FT


def floor_to_ft(level):
    """Feet for a floor LEVEL (primary is level 0 → 0 ft)."""
    return int(level) * FLOOR_FT


def absolute_ft(floor_ft, elev_units):
    """A creature's absolute height: the floor's offset plus the ground elevation
    of the cell it stands on, both already on the 10 ft scale."""
    return int(floor_ft) + elev_to_ft(elev_units)


# ---------------------------------------------------------------------------
# D114 — the vertical token VOLUME. A token keeps ONE home plane + footprint
# (footprint.py stays the only horizontal geometry); its body is a vertical
# segment [base_ft, top_ft]. These helpers are the single derivation of that
# segment; nothing else may re-derive feet from size/elevation.
# ---------------------------------------------------------------------------

# House-rule DEFAULT heights (backward-compat only — a DEFAULT, never a ceiling):
# a Medium creature fits inside one 10 ft floor, a Gargantuan reaches ~two. A DM
# may author any value within the technical band (a 30 ft dragon spans 3 floors).
SIZE_HEIGHT_FT = {"Tiny": 5, "Small": 5, "Medium": 5, "Large": 10,
                  "Huge": 15, "Gargantuan": 20}
MAX_HEIGHT_FT = 200          # technical server validation ceiling
MAX_ELEVATION_FT = 200


def size_default_height_ft(size):
    """The backward-compat default body height for a size category (house rule)."""
    return SIZE_HEIGHT_FT.get(str(size or "Medium").title(), 5)


def clean_height_ft(value):
    """Client-authored token height (ft) -> int in 0..MAX_HEIGHT_FT, or None when
    unset/invalid (None = fall back to the size default)."""
    if value is None or value == "":
        return None
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(0, min(MAX_HEIGHT_FT, v))


def clean_elevation_ft(value):
    """Client-authored under-edge offset (ft) -> int in 0..MAX_ELEVATION_FT
    (0 = grounded). Negative offsets are not modelled (a body sits on/above
    its surface, never below it)."""
    if value is None or value == "":
        return 0
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(MAX_ELEVATION_FT, v))


def token_height_ft(token):
    """The token's vertical extent in feet: explicit `height_ft`, else the size
    default. Legacy tokens (column NULL) get the size default → same footprint
    behaviour they always had."""
    t = token or {}
    h = t.get("height_ft")
    if h is not None:
        try:
            return max(0, min(MAX_HEIGHT_FT, int(h)))
        except (TypeError, ValueError):
            pass
    return size_default_height_ft(t.get("size"))


def token_elevation_ft(token):
    """The token's under-edge above its standing surface (0 = grounded)."""
    try:
        return max(0, min(MAX_ELEVATION_FT, int((token or {}).get("elevation_ft") or 0)))
    except (TypeError, ValueError):
        return 0


def base_ft(ground_ft, elevation_ft):
    """Absolute height of the token's UNDER edge."""
    return int(ground_ft) + int(elevation_ft)


def top_ft(base, height):
    """Absolute height of the token's TOP edge."""
    return int(base) + int(height)


def levels_between(base, top):
    """Floor LEVELS (primary 0 and up) whose 10 ft band [L*10,(L+1)*10) overlaps
    the vertical segment [base, top). A negative base (a pit cell) clamps to the
    primary level — there is no level below 0, and volume never INVENTS a plane;
    whether the volume actually reaches a level is gated by openings (Phase 4/5)."""
    lo = base if base > 0 else 0
    if top <= lo:
        return {0}
    return set(range(max(0, lo // FLOOR_FT), max(0, (top - 1) // FLOOR_FT) + 1))
