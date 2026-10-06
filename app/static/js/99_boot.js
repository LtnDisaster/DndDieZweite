/* ---------- 99_boot.js — bundle integrity gate (D78) ----------
   Loads LAST, after every application script has been parsed. Before the
   mixed-bundle saga this spot did nothing; now it decides whether booting is
   safe. A stale cached module alongside a fresh one used to kill the render
   loop silently (ReferenceError inside requestAnimationFrame -> black canvas,
   "Bring failed" toasts that were actually presentation errors).

   Four cheap, non-secret checks:
     1. required cross-file globals actually exist,
     2. every expected module stamped itself with the page's build token
        (a pre-D78 cached file has no stamp at all),
     3. every /static/js/* the browser actually fetched carried ?v=<token>,
     4. the server's /api/build token equals the page's token (async).
   On any mismatch: visible red banner + console diagnostics + NO boot.
   Never show hidden game data here — identity/structure only. */
(typeof window !== "undefined") && ((window.__BUILDS = window.__BUILDS || {})["99_boot.js"] = window.__BUILD__ || "?");
(function(){
  const EXPECTED = window.__BUILD__ || "?";
  if (typeof console !== "undefined" && console.log) console.log("BUILD " + EXPECTED);

  const MODULES = ["10_core.js", "20_lobby.js", "30_room.js", "40_ws.js",
                   "50_canvas.js", "55_diorama.js", "60_main.js", "99_boot.js"];
  const REQUIRED = ["gridOrigin", "w2s", "s2w", "wIdx", "api", "toast", "esc", "show",
                    "openRoom", "refreshRoom", "resize", "drawTactical", "drawDiorama",
                    "wsSend", "setViewMode", "myToken", "cellSize", "appBoot"];
  const defined = function(name){
    try { return new Function("return typeof " + name + ";")() !== "undefined"; }
    catch (e){ return false; }
  };

  const missing   = REQUIRED.filter(n => !defined(n));
  const stamps    = window.__BUILDS || {};
  const unstamped = MODULES.filter(f => !(f in stamps));
  const wrongBuild = MODULES.filter(f => f in stamps && EXPECTED !== "?" && stamps[f] !== EXPECTED);
  const staleUrls = [];
  try {
    for (const e of performance.getEntriesByType("resource")){
      const m = String(e.name || "").match(/\/static\/js\/([0-9A-Za-z_]+\.js)(\?.*)?$/);
      if (!m) continue;
      const q = m[2] || "";
      if (EXPECTED !== "?" && q.indexOf("v=" + EXPECTED) < 0)
        staleUrls.push(m[1] + " (" + (q || "no token") + ")");
    }
  } catch (e){ /* no performance API: skip URL audit */ }

  const problems = [];
  if (missing.length)    problems.push("missing functions: " + missing.join(", "));
  if (unstamped.length)  problems.push("stale modules (no build stamp, pre-D78 cache?): " + unstamped.join(", "));
  if (wrongBuild.length) problems.push("modules stamped with a different build: " +
                                       wrongBuild.map(f => f + "=" + stamps[f]).join(", "));
  if (staleUrls.length)  problems.push("asset URLs without the current build token: " + staleUrls.join(", "));

  window.__INTEGRITY = { expected: EXPECTED, missing: missing, unstamped: unstamped,
                         wrongBuild: wrongBuild, staleUrls: staleUrls,
                         ok: problems.length === 0 };

  function banner(lines){
    let b = document.getElementById("bundle-banner");
    if (!b){
      b = document.createElement("div");
      b.id = "bundle-banner";
      b.setAttribute("style", "position:fixed;top:0;left:0;right:0;z-index:9999;" +
        "background:#8b0000;color:#fff;padding:10px 14px;font:13px/1.5 monospace;" +
        "white-space:pre-wrap;box-shadow:0 2px 8px rgba(0,0,0,.6)");
      document.body ? document.body.appendChild(b) : document.addEventListener("DOMContentLoaded", () => document.body.appendChild(b));
    }
    b.textContent = "FRONTEND GENERATION MISMATCH — the application was NOT started.\n" +
                    lines.join("\n") + "\nHard reload to fetch this build completely: Ctrl+Shift+R (macOS: Cmd+Shift+R)";
  }

  if (window.__INTEGRITY.ok){
    appBoot().catch(e => {
      banner(["startup failed: " + (e && e.message ? e.message : String(e))]);
      if (typeof console !== "undefined" && console.error) console.error("[boot] appBoot failed", e);
    });
  } else {
    window.__INTEGRITY_FAIL = problems;
    if (typeof console !== "undefined" && console.error)
      console.error("[boot] bundle integrity FAILED (expected build " + EXPECTED + "):", problems);
    banner(problems.map(p => "• " + p));
  }

  /* Server/page generation cross-check: assets are served from disk while the
     token was computed at process start — files hot-swapped without a restart
     (half-deployed rsync) must surface here, loudly. */
  try {
    fetch("/api/build", { cache: "no-store" }).then(r => r.json()).then(d => {
      window.__INTEGRITY.server = d && d.build;
      if (d && d.build && EXPECTED !== "?" && d.build !== EXPECTED){
        const msg = "page build " + EXPECTED + " but server build " + d.build +
                    " (assets changed without a server restart — restart the app)";
        window.__INTEGRITY.serverMismatch = msg;
        if (typeof console !== "undefined" && console.error) console.error("[boot]", msg);
        if (window.__INTEGRITY.ok)     // page self-consistent, but generation drifted
          banner(["server and page belong to different builds:", msg]);
      }
    }).catch(() => {});
  } catch (e){ /* fetch unavailable: skip cross-check */ }
})();
