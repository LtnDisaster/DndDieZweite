"""D157 — the deletion DIALOG the user actually clicks, driven for real.

No browser runtime exists in the canonical test image (documented pattern of
test_browser_flow.py), so the genuine shipped client — 10_core.js + 20_lobby.js
— executes in a Node vm while the DOM is stubbed. Pixels are faked; the JS that
arms/gates/confirms the delete, the wire it emits, and the live server that
answers are all real.

Pinned here:
  * the destructive button is disabled until the DM types the room's exact code
    (the anti-misclick guarantee that replaced the 6s auto-disarm trap);
  * on the correct code the client emits exactly `DELETE /rooms/<code>` — and
    against a room seeded with a `containers` child the LIVE fixed server now
    really deletes it (this same path returned 500 before the D157 fix);
  * on a server failure the client shows an inline error and KEEPS the dialog
    open (no silent success, no success toast, no lobby reload).
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app
from tests.test_movement_fog import H, reg

NODE = shutil.which("node")
ROOT = Path(__file__).resolve().parents[1]

_DOM = r"""
{
  window: { addEventListener: () => {}, devicePixelRatio: 1 },
  location: { search: '' },
  setTimeout: () => 0, clearTimeout: () => 0,
  localStorage: { getItem: () => null, setItem: () => {} },
  rec: { sent: [], toasts: [], lobby: 0, reject: null },
  document: (() => {
    const reg = {};
    const mk = (id) => (reg[id] = reg[id] || Object.assign({
      id, dataset: {}, style: {}, textContent: '', value: '', disabled: false, checked: false,
      _opened: 0, _closed: 0,
      classList: { toggle(){}, add(){}, remove(){} },
      addEventListener(){}, appendChild(){}, querySelectorAll(){return [];}, focus(){},
    }));
    return {
      getElementById: (id) => {
        const n = mk(id);
        if (id === 'del-room-dlg'){
          n.showModal = function(){ this._opened++; };
          n.close = function(){ this._closed++; };
        }
        return n;
      },
      createElement: () => ({ dataset:{}, style:{}, classList:{toggle(){},add(){},remove(){}}, appendChild(){} }),
      querySelectorAll: () => [],
    };
  })()
}
"""

_BOOT = ("api = async (p, m, b) => { rec.sent.push([p, m]);"
         " if (rec.reject) throw new Error(rec.reject); return {}; };"
         " toast = (msg) => rec.toasts.push(msg);"
         " loadLobby = async () => { rec.lobby++; };")


def _run_node(script):
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed: {r.stderr[-4000:]}"
    return r.stdout.strip()


def _vm(probe_js, reject=None):
    js = ROOT / "app/static/js"
    files = [str(js / "10_core.js"), str(js / "20_lobby.js")]
    boot = _BOOT + (f" rec.reject = {json.dumps(reject)};" if reject is not None else "")
    script = (
        "const vm=require('vm'),fs=require('fs');"
        f"const files={[str(f) for f in files]};"
        f"const sb=Object.assign({{console}}, {_DOM});"
        "vm.createContext(sb);"
        "for(const f of files) vm.runInContext(fs.readFileSync(f,'utf8'),sb,{filename:f});"
        f"vm.runInContext({json.dumps(boot)},sb);"
        f"vm.runInContext({json.dumps(probe_js)},sb);"
    )
    return json.loads(_run_node(script))


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_delete_dialog_gates_on_room_code_and_deletes_for_real():
    c = TestClient(app)
    dm = reg(c, "dmDlg")
    code = c.post("/api/rooms", json={"name": "ABC"}, headers=H(dm)).json()["code"]
    room_id = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    # seed the exact child row that made the pre-D157 server 500 on delete
    db.x("INSERT INTO containers(room_id, object_id, items) VALUES(?,?,?)",
         (room_id, "chest1", "[]"))

    probe = ("(async () => {"
             "openDeleteRoom({name:'ABC', code:CODE});"
             "const dlg=$('del-room-dlg'), inp=$('del-room-input'), btn=$('del-room-confirm');"
             "inp.value='nope'; inp.oninput(); const wrongDisabled=!!btn.disabled;"
             "inp.value='XYZ'; inp.oninput(); const wrongStillDisabled=!!btn.disabled;"
             f"inp.value=CODE; inp.oninput(); const rightEnabled=!btn.disabled;"
             "await btn.onclick();"
             "console.log(JSON.stringify({opened:dlg._opened, wrongDisabled,"
             " wrongStillDisabled, rightEnabled, sent:rec.sent, toasts:rec.toasts,"
             " lobby:rec.lobby, closed:dlg._closed}));"
             "})();").replace("CODE", json.dumps(code))

    out = _vm(probe)
    assert out["opened"] == 1                                   # dialog shown
    assert out["wrongDisabled"] and out["wrongStillDisabled"]   # never armed on a wrong code
    assert out["rightEnabled"]                                  # enabled on the exact code
    assert out["sent"] == [[f"/rooms/{code}", "DELETE"]]        # the wire the client emits
    assert out["toasts"] == ['Room "ABC" deleted'] and out["lobby"] == 1
    assert out["closed"] == 1                                   # dialog closed on success

    # the client's own request path now really deletes the container-bearing room
    r = c.delete("/api" + out["sent"][0][0], headers=H(dm))
    assert r.status_code == 200, f"server must honour the client request: {r.status_code} {r.text}"
    assert db.q1("SELECT id FROM rooms WHERE code=?", (code,)) is None
    assert db.q("SELECT * FROM containers WHERE room_id=?", (room_id,)) == []


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_delete_dialog_surfaces_error_and_keeps_dialog_open():
    probe = ("(async () => {"
             "openDeleteRoom({name:'ABC', code:'ZZZ'});"
             "const inp=$('del-room-input'), btn=$('del-room-confirm');"
             "inp.value='ZZZ'; inp.oninput();"
             "await btn.onclick();"
             "console.log(JSON.stringify({sent:rec.sent, toasts:rec.toasts, lobby:rec.lobby,"
             " closed:$('del-room-dlg')._closed, err:$('del-room-err').textContent, disabled:!!btn.disabled}));"
             "})();")
    out = _vm(probe, reject="Internal server error")
    assert out["sent"] == [["/rooms/ZZZ", "DELETE"]]            # the attempt was made
    assert out["toasts"] == [] and out["lobby"] == 0            # no false success
    assert out["closed"] == 0                                   # dialog stays open
    assert out["err"] == "Internal server error"                # the failure is shown inline
    assert out["disabled"] is True                              # destructive button re-armed off
