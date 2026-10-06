"""Sprint 12 (D78): frontend deployment integrity.

The black-canvas saga was never the grid: browsers mixed one new 50_canvas.js
(calls gridOrigin/w2s) with a stale pre-D72 10_core.js (does not define them)
because index.html loaded every asset under an unchanged URL with no cache
headers. The first ReferenceError killed the render loop silently.

These tests pin the fix at the level the bug lived on:
  * the rendered / must reference every owned asset with the current build token
  * /api/build must expose that token + per-file hashes (diagnostics only)
  * bootstrap and assets must not be cacheable
  * every REQUIRED cross-file global must be DEFINED before (load-order) any
    loaded script CALLS it — the exact incident must fail this check
  * the integrity gate (99_boot.js) must be the last script and must be the
    only thing that starts appBoot().
"""
import pathlib
import re

from starlette.testclient import TestClient

from app import buildinfo
from app.main import app

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"

REQUIRED_GLOBALS = ("gridOrigin", "w2s", "s2w", "wIdx")


def _client():
    return TestClient(app)


# ---------- the static load-order checker (pragmatic, no JS parser) ----------

def load_order(static_dir: pathlib.Path):
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    return re.findall(r'<script src="/static/js/([0-9A-Za-z_]+\.js)', html)


def scan_bundle(static_dir: pathlib.Path, required=REQUIRED_GLOBALS):
    """Return a list of human-readable problems; [] means the bundle is
    coherent with respect to REQUIRED cross-file globals."""
    problems = []
    order = load_order(static_dir)
    if not order:
        return ["index.html loads no /static/js/* scripts"]
    for name in required:
        defines, calls = [], []
        for pos, fname in enumerate(order):
            text = (static_dir / "js" / fname).read_text(encoding="utf-8")
            if re.search(rf"\bfunction\s+{name}\s*\(", text):
                defines.append((pos, fname))
            if re.search(rf"(?<![\w.$]){name}\s*\(", text):
                calls.append((pos, fname))
        if not defines:
            problems.append(f"{name}() is called/needed but defined by no loaded script")
            continue
        if len(defines) > 1:
            problems.append(f"{name}() defined by multiple scripts: {[f for _, f in defines]}")
        first_def = defines[0][0]
        for pos, fname in calls:
            if pos < first_def:
                problems.append(f"{fname} calls {name}() but it is only defined later "
                                f"by {defines[0][1]}")
    return problems


# ---------- the real tree is coherent ----------

def test_real_bundle_satisfies_cross_file_globals():
    assert scan_bundle(STATIC) == []


def test_incident_class_fails_the_checker(tmp_path):
    """Negative control for the exact incident: 50_canvas.js calls gridOrigin()
    while no earlier script defines it — the checker must report it."""
    (tmp_path / "js").mkdir()
    (tmp_path / "index.html").write_text(
        '<script src="/static/js/10_core.js"></script>'
        '<script src="/static/js/50_canvas.js"></script>')
    (tmp_path / "js" / "10_core.js").write_text("const state = {};\n")
    (tmp_path / "js" / "50_canvas.js").write_text(
        "function draw(){ const [ox] = gridOrigin(state.grid); }\n")
    problems = scan_bundle(tmp_path, required=("gridOrigin",))
    assert problems and "gridOrigin" in problems[0]

    # and the fixed shape passes:
    (tmp_path / "js" / "10_core.js").write_text(
        "function gridOrigin(g){ return [0,0]; }\nconst state = {};\n")
    assert scan_bundle(tmp_path, required=("gridOrigin",)) == []


def test_integrity_gate_is_last_and_owns_boot():
    order = load_order(STATIC)
    assert order[-1] == "99_boot.js"
    boot = (STATIC / "js" / "99_boot.js").read_text(encoding="utf-8")
    main = (STATIC / "js" / "60_main.js").read_text(encoding="utf-8")
    assert "appBoot(" in boot
    assert "async function appBoot(" in main
    # 60_main.js must no longer start itself: no boot IIFE any more
    assert "(async function boot" not in main


def test_gate_required_globals_all_defined():
    boot = (STATIC / "js" / "99_boot.js").read_text(encoding="utf-8")
    listed = re.search(r"const REQUIRED = \[([^\]]+)\]", boot)
    assert listed, "99_boot.js must declare its REQUIRED globals list"
    names = re.findall(r'"([A-Za-z_$][\w$]*)"', listed.group(1))
    assert names and all(
        re.search(rf"\b(function|const|let)\s+{n}\b|window\.{n}\s*=",
                  "\n".join(p.read_text(encoding="utf-8")
                            for p in (STATIC / "js").glob("*.js")))
        for n in names
    ), f"99_boot requires undeclared globals: {names}"


# ---------- rendered HTML: one token for one generation ----------

def test_served_index_binds_every_asset_to_the_build_token():
    with _client() as c:
        token = buildinfo.token()
        html = c.get("/").text
    assert "__BUILDTOKEN__" not in html, "placeholder must be fully replaced"
    assert f'window.__BUILD__ = "{token}"' in html
    refs = re.findall(r'/static/(?:js/[0-9A-Za-z_]+\.js|style\.css)\?v=([^"\']+)', html)
    assert len(refs) >= 9, f"expected all owned assets referenced, got {len(refs)}"
    assert all(v == token for v in refs), f"mixed asset tokens in index: {set(refs)}"


def test_api_build_identity_without_leaks():
    with _client() as c:
        r = c.get("/api/build")
        assert r.status_code == 200
        d = r.json()
    assert d["build"] == buildinfo.token()
    assert re.fullmatch(r"[0-9a-f]{12}", d["build"])
    js = {p.name for p in (STATIC / "js").glob("*.js")}
    assert js <= set(d["files"]), f"missing files in /api/build: {js - set(d['files'])}"
    assert {"index.html", "style.css"} <= set(d["files"])
    body = r.text
    assert str(ROOT) not in body and "/" not in "".join(d["files"])


def test_bootstrap_and_assets_are_not_cacheable():
    with _client() as c:
        for path in ("/", "/static/style.css", "/static/js/10_core.js",
                     f"/static/js/99_boot.js?v={buildinfo.token()}"):
            assert c.get(path).headers.get("cache-control") == "no-cache", path


def test_every_module_stamps_itself():
    """A pre-D78 cached module has no stamp at all — the boot gate detects the
    incident class through this; so every shipped module must stamp."""
    order = load_order(STATIC)
    for fname in order:
        text = (STATIC / "js" / fname).read_text(encoding="utf-8")
        assert (f'"{fname}" = window.__BUILD__' in text
                or f'"{fname}" = (window.__BUILD__' in text
                or f'["{fname}"] = window.__BUILD__' in text
                or f'["{fname}"] = (window.__BUILD__' in text), f"{fname} does not stamp"
        assert "window.__BUILDS" in text
