"""Generic effect geometry tests (D54).

Unit: shapes, directions, clipping, determinism.
Parity: the SERVER module and the CLIENT ``aoeCells`` in 10_core.js must cover
exactly the same cells — proving the geometry is one reusable mathematical
thing, independent of transport, renderer and (deliberately) of any spell
name: fixtures are "Test Burst" / "Training Cone" / "Debug Beam" style only.
"""
import json

from app.effects import effect_cells

W, H = 10, 10
ALL_DIRS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def cells(shape, size, x, y, direction="E"):
    return set(effect_cells(shape, size, x, y, W, H, direction))


def test_point_is_origin_only():
    assert cells("point", 9, 4, 4) == {4 * W + 4}


def test_line_orientation_per_direction():
    from app.effects import DIRV
    for d in ALL_DIRS:
        got = cells("line", 3, 5, 5, d)
        assert len(got) == 4 and 5 * W + 5 in got
        dx, dy = DIRV[d]
        assert (5 + dy * 3) * W + (5 + dx * 3) in got        # far end lies along the direction


def test_cone_directionality():
    east = cells("cone", 3, 5, 5, "E")
    west = cells("cone", 3, 5, 5, "W")
    assert 5 * W + 6 in east and 5 * W + 4 not in east       # opens toward dir
    assert 5 * W + 4 in west and 5 * W + 6 not in west
    assert cells("cone", 3, 5, 5, "NE") != cells("cone", 3, 5, 5, "SW")


def test_circle_and_square_shapes():
    circle = cells("circle", 2, 5, 5)
    square = cells("square", 2, 5, 5)
    assert len(square) == 25                                  # 5×5
    assert circle < square                                    # strictly inside
    assert 5 * W + 7 in circle                                # r+0.4 tolerance at edges
    assert 3 * W + 3 not in circle                            # corners outside


def test_boundary_clipping_and_determinism():
    first = effect_cells("circle", 4, 0, 0, W, H)
    assert all(0 <= c < W * H for c in first)                 # nothing wrapped or negative
    assert first == effect_cells("circle", 4, 0, 0, W, H)     # deterministic + stable order
    assert effect_cells("square", 3, 9, 9, W, H) == effect_cells("square", 3, 9, 9, W, H)
    assert len(effect_cells("square", 3, 0, 0, W, H)) < 49    # clipped by the wall


# ---------- client/server parity (Node vm, same harness as view-mode guards) ----------

from test_view_mode import _node_vm, needs_node  # noqa: E402
from pathlib import Path  # noqa: E402

JS_10 = str(Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "10_core.js")


@needs_node
def test_effect_geometry_matches_client_aoecells():
    matrix = []
    for shape in ("line", "cone", "circle", "square"):
        for size in (1, 2, 5):
            for direction in ("E", "N", "SW" if shape in ("line", "cone") else "E"):
                matrix.append([shape, size, 5, 5, direction])
            matrix.append([shape, 3, 0, 0, "NE"])              # clipped at corner
    extra = (
        "const out=[];"
        f"for (const [s,n,x,y,d] of {json.dumps(matrix)})"
        "  out.push(aoeCells(s,x,y,n," + f"{W},{H},d));"
        "console.log(JSON.stringify(out));"
    )
    client = json.loads(_node_vm([JS_10], extra))
    assert len(client) == len(matrix)
    for (shape, size, x, y, d), got in zip(matrix, client):
        server = effect_cells(shape, size, x, y, W, H, d)
        assert set(server) == set(got), f"{shape} r{size} at {(x,y)} {d}"
