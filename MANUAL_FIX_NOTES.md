# Sprint 9 — Deployment & UX hardening (2026-10-05) — manual review guide
No git was used; review the working tree file by file. Canonical suite:
`docker compose run --rm test` → **263 passed** (256 + 7 node-vm skips) (host venv: same 263).
`node --check` clean on every JS file; `compileall` clean.

## Three REAL root causes found (not test-only)
1. **Intermittent 401 after login (production bug).** `make_token` embedded
   base64 **`=` padding** in the session cookie; cookie parsers drop values
   containing `=`, so ~1 in 3 tokens died at parse time (the flake looked random
   because payload length decided). `app/auth.py` now emits padding-free
   base64url and `read_token` re-pads → deployed padded tokens still verify,
   nobody gets logged out by the upgrade. Test: `tests/test_auth_token.py`.
1b. **Signing key mutated after first use (production bug).** `_secret()`
   returned the RAW 32 random bytes when creating `secret.key`, but every later
   read did `.read().strip()` — and random bytes can BE whitespace (0x0a, 0x20).
   ~1.6% of fresh installs signed with one key and verified with another
   (first session dead; the test flake made it visible). Key is now stored
   HEX-encoded (whitespace-free by construction); legacy raw files still load
   unchanged via the ValueError fallback. Test:
   `test_secret_is_stable_across_generation`.
2. **Suite hangs / lost WS events under starlette ≥1.7.** Each TestClient WS
   session now runs on its OWN event loop; `broadcast()` used to `await
   ws.send_text()` into foreign loops, where anyio wakeups can be lost (idle
   loops + forever-pending receive — captured via `faulthandler_timeout`).
   `app/room/net.py` gained `attach_ws`/`detach_ws` (socket→loop registry) and
   `_send` (same-loop fast path — production ALWAYS — plus threadsafe
   cross-loop delivery for the test harness). `app/ws.py` calls attach/detach.
   This is why the old full-suite runs hung in `test_chat`/`test_integration`.

## Server changes
- `app/room/net.py` — loop registry + `_send`; broadcast discards+detaches dead
  sockets. `app/ws.py` — `attach_ws` after accept, `detach_ws` in finally; NEW:
  WS handshake Origin gate (`_origin_ok`, 4403) before auth-adjacent accept.
- `app/auth.py` — padding-free tokens (D62); `cookie_secure` honours
  `X-Forwarded-Proto` only with `VTT_TRUST_PROXY=1` (D64).
- `app/mapmodel.py` — door sanitize keeps `dm_only`/`secret`; `visible_map`
  never transmits secret doors to players.
- `app/room/doors.py` — player branch: secret → silent (identical to “no door”),
  dm_only → “It won't budge.” BEFORE any lock-state leak; chronicle line
  suppressed for dm_only/secret moves. (Watch indentation of the state/sys_msg
  block — it sits at function level, outside `if opened:`.)
- `app/rooms.py` + `app/main.py` — uploads under `db.DATA_DIR/uploads`, mounted
  at unchanged `/uploads/`; startup mkdir moved to import time.
- `Dockerfile` (NEW multi-stage: `test` stage + runtime, non-root uid 1000,
  HEALTHCHECK, single uvicorn), `compose.yaml` (NEW: app on 127.0.0.1:8000 +
  bind `./data`, `test` under profile), `requirements*.txt` exact pins — note
  the **previously missing `websockets`** package (uvicorn needs it; docker
  runs would have died on first WS connect!).
- `.dockerignore` (NEW — excludes data/.git/.venv but KEEPS tests/ for the
  test stage), `.gitignore` (archives, Zone.Identifier, compose overrides),
  `pytest.ini` (`-o faulthandler_timeout=120`: any future hang dumps stacks).

## Scripts (NEW)
- `scripts/vtt-backup.sh` — sqlite backup API (WAL-safe live), PRAGMA
  integrity_check BEFORE archiving, bundles secret.key + uploads.
- `scripts/vtt-restore.sh` — refuses silently over a live db (keeps
  `vtt.db.pre-restore.*`), deletes stale `-wal/-shm`, integrity-checks result.
- `scripts/move_uploads.py` — idempotent legacy upload migration (app tree →
  data dir). `scripts/make_release.sh` — clean source tar + forbidden-path guard.

## Client changes
- `style.css` — token block (spacing/side width/z-scale, defines `--muted`),
  one `.wlabel` definition (was duplicated with different values), sticky
  `#side-tabs` with real active state, `details.group` + `.sheet-sec`,
  `.dice-sep`, toast z above movehud, 1100px media, 900px room-grid un-squeeze.
- `index.html` — sidebar tab roles, dice toolbar separated, DM panels in
  collapsible groups (all ids kept), door editor gains DM-only + hidden
  checkboxes, help text (doors/NPC workflow).
- `30_room.js` — NPC sheet re-sectioned (**every `#npc-*` id preserved**, the
  pinned `clsTxt` guard untouched); PC sheet Skills/Spellbook `details.sheet-sec`;
  `applySideTab` maintains `aria-selected`.
- `50_canvas.js` — `doorEdit` sends dm_only/secret; `drawDoor` renders DM-side
  ghosting for secret and purple for dm_only.

## Tests added (21 total)
`tests/test_auth_token.py` (5) · `tests/test_deploy_hygiene.py` (6) ·
`tests/test_doors_dmonly.py` (10). Diagnostic evidence kept in `tmp/byfile/`.

## Not verified / known
- Host lacks docker buildx → classic builder used (`DOCKER_BUILDKIT=0`).
- Browser hand-tests pending (see chat report) — DOM layout changes verified by
  code review + pin tests only.
- `#editor` inside the DM tab remains a JS-toggled block (not `<details>`) by
  design; its show/hide button drives visibility.
