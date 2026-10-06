# Manual Browser Checklist

Run the **BUILD CHECK first**. A mixed/stale frontend bundle reproduces every
old symptom (black canvas, weird toasts) — deeper gameplay testing is
BLOCKED until steps B1–B5 pass. Report, don't continue, on any failure.

## BUILD CHECK (blocking — D78)

1. Open the application (fresh rebuild, private window recommended).
2. Open the browser console (F12): first line must report `BUILD <token>`.
3. Open `/api/build` in the same browser: it must show the SAME token.
4. DevTools → Network: every `10_core.js`, `20_lobby.js`, `30_room.js`,
   `40_ws.js`, `50_canvas.js`, `55_diorama.js`, `60_main.js`, `99_boot.js`
   and `style.css` request must carry `?v=<that token>`.
5. No red **FRONTEND GENERATION MISMATCH** banner anywhere on the page.

## SMOKE TEST (blocking)

1. DM creates/opens a room.
2. Player joins (same or second browser).
3. Player creates or selects a character (lobby editor) and clicks **Bring** —
   expect the "takes a seat at the table" toast. If the toast instead says the
   view could not initialize, the character IS seated (server truth) — report
   it as a presentation bug, not a Bring failure.
4. Player sees map, **not complete blackness** (area around own token; rest
   may be fog). If black: check console for `ReferenceError` (bundle!) and
   open the page again with `?debug`.
5. Player sees **own token** (view opens centered on it — D75).
6. Player moves in Tactical (click → gold preview → confirm).
7. Player clicks **Diorama** (topbar switch).
8. Player still sees map/token in Diorama (view auto-frames the visible world).
9. Player moves in Diorama (click own token, click destination, confirm).
10. Player switches back to **Tactical**.
11. Token is at the **same world position** as before switching.
12. Fog remains coherent (no new black regions, no wrong-cell fog).
13. Player clicks **← Lobby** and is back at room selection.
14. DM clicks **Delete** on a disposable test room in the lobby, confirms the
    armed button (`Delete "<name>" permanently?`).
15. The room is gone from both lists; joining by its old code fails.

## COMBAT LOOP (D79 — after smoke passes)

1. **Exploration movement:** before any combat, walk your token a clearly
   long route (> speed) — it must complete. No combat budget applies.
2. **Start combat:** DM clicks ⚔️ Start. The Initiative panel shows the round
   line, the order, and the compact turn bar (active name, move x/y, A/B/R).
3. **Active token movement:** when it's your turn, move — the turn bar's
   movement counter drops by exactly the route cost shown in the preview
   (e.g. 3 of 6 for 3 straight steps).
4. **Budget display:** remaining/total visible at a glance; the path preview
   shows `cost/budget` and marks an unaffordable route.
5. **Over-budget attempt:** confirm a too-long route — the token walks until
   the budget runs out and stops with "Out of movement — Dash or End Turn"
   (never silently beyond).
6. **Dash:** click 💨 Dash — the Action chip flips to spent and the movement
   total grows by one speed (e.g. 6 → 12); you can now walk the extra range.
7. **Second Dash:** must be refused ("No action left this turn").
8. **End Turn:** click End Turn (or DM clicks Next) — initiative advances.
9. **Next combatant:** the turn bar shows the new active token with a FULL
   budget (x/6) and fresh A/B/R.
10. **Tactical → Diorama → Tactical** mid-turn: move spent, A/B/R, token
    position and initiative must be exactly as before the round trip.
11. **End combat:** DM clicks End — turn bar disappears, combat ends.
12. **Exploration again:** walk a long route — no budget applies any more.

## Extended manual checks (after smoke passes)

- Two clients: one stays Diorama while the other stays Tactical (views are
  independent, world state shared).
- DM: Tactical and Diorama both fine; map editor opens in Tactical.
- DM drags a player token deep into the world → the player's view does NOT
  jump; the player's next own-action recenters via ← Lobby → reopen.
- Token teleports show no coordinate drift after resize/growth (fixed map:
  auto growth is flag-off by default, D77).
- Room deletion with an open player WS: player lands in lobby with a toast,
  browser does not spam reconnects (check network tab: no reconnect loop).
- `?debug` URL suffix (dev mode): topbar HUD shows build token +
  `integrity=ok`, view mode, canvas size, cam/camT/camD, camInit trace,
  `grid=y/n` + window/origin/dims, own token cell/screen pos,
  known/explored/painted, `bring=<last result/error>`, last client error.
  Black screen triage: `integrity=FAIL` or any `ERR:` line → bundle/client
  bug (console shows the exact ReferenceError). `grid=n`/payload issues →
  server/WS. `known>0, painted=0` → camera/framing. `known=0` without own
  token → legitimate fog (Bring first). Never expose hidden data.

## History

- Sprint 12: BUILD CHECK added — `ReferenceError: gridOrigin is not defined`
  in a real browser proved mixed script generations were the black-canvas
  root cause across sprints 10–11 (DECISIONS D78). Bring step added to the
  smoke test (previously missing — the tester had no token and read the
  legitimate fog as a total failure).
- Sprint 11: smoke test created after black-screen/Diorama one-way/room-delete
  manual regressions (see DECISIONS D75–D77, MANUAL_FIX_NOTES.md).
