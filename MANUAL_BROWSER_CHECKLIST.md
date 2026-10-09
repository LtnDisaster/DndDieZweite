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

## CONDITIONS & TURNS (D80 — Tactical only)

1. **Timed condition:** open your token sheet → Conditions row; add e.g.
   poisoned with rounds 2, anchor "round end". The chip shows "(2r)".
2. **Start combat** (DM ⚔️).
3. **Duration visible:** the chip still counts 2 during round 1.
4. **End turns** until one full round wraps — chip shows "(1r)"; not before
   the wrap, not twice at it.
5. **Exact expiry:** after the next wrap the chip is gone. Repeat with anchor
   "my turn start" — it must change ONLY when your turn begins, and a "my
   turn end" condition must clear the moment your turn ends.
6. **Apply prone** (DM or yourself) — dot on the token, chip "Prone".
7. **Stand Up:** when it is your turn, the Conditions row shows a "Stand Up"
   button — click it.
8. **Budget:** the turn bar goes Move 6/6 → 3/6 immediately; the token did
   not move.
9. **Move with the rest:** walk up to 3 squares — works; a 4th is refused.
10. **Down a creature** (DM sets your HP to 0): any move attempt is refused
    with "cannot move while downed"; the DM can still push/teleport it.
11. **Voluntary movement rejected** also with unconscious/stunned applied.
12. **End combat:** prone outside combat stands for free; long walks stay
    unlimited and no condition duration ticks while exploring.

## RECTANGULAR FOOTPRINTS (D81/15B — Tactical only)

1. Open an existing room.
2. Confirm the OLD tokens are visible (the 15B incident: they were gone).
3. Select an existing token (your own, or any token as DM).
4. The sheet shows a labelled **Footprint** row (W, H, Apply) — no hidden UI.
5. Set Width 3, Height 7 and hit Apply.
6. The token visibly becomes a 3×7 rectangle at the SAME spot instantly.
7. Press F5 (refresh) — it is still 3×7 and the row shows 3 and 7.
8. Move it once — walk/preview account for the whole rectangle.
9. Select an old Large NPC: the row shows 2×2 (its size category) — untouched.
10. Try a footprint that does not fit (e.g. 10×10 in a corridor): refused,
    error message shown, old size and position preserved.

## VISUAL SIZE, ROTATION, WORLD OBJECTS, COMPANIONS (D82 — Tactical only)

1. Open an EXISTING room: nothing looks changed (visual defaults to the
   mechanical footprint — legacy tokens render exactly as before).
2. Select a token: a labelled **Visual Size** row (W, H, Apply) sits below the
   Footprint row, and a **Rotation** row (⟲ degrees ⟳ 0°) below that.
3. Keep Footprint 1×1, set Visual Size 3×7, Apply: the artwork grows tall and
   stays CENTERED on the token's cell; movement preview/collision still use
   exactly the 1×1 (walk it through a one-cell corridor — it fits).
4. Footprint 3×7 with Visual Size 1×1: small circle, but the whole 3×7 still
   collides — select it (or press `?debug` / open the map editor) and the
   collision outline proves the occupied cells.
5. A visual resize NEVER needs clearance (no "does not fit" error) and never
   moves anything; the mechanical resize still refuses an ill-fitting rect
   exactly as in the D81 checklist — the two operations are independent.
6. The collision outline is only visible while the token is SELECTED, while
   map-editing, or with `?debug` — not as a permanent translucent block.
7. Click on the outer artwork of a big visual token (outside its real cells):
   the token gets selected (presentation hit area; gameplay unaffected).
8. Rotation ⟲/⟳: the body rotates in 90° steps — non-square visuals visibly
   swap orientation; square/circle visuals show a small gold facing wedge.
   Labels, HP bars and condition dots stay upright. D83: the FOOTPRINT turns
   with the entity (see the D83 section below for the real checks); F5 keeps
   the facing.
9. DM map editor 🕹️ brush: place a Lever (op "toggle state"), close the
   editor. Players see the marker on explored ground.
10. Player clicks the lever from across the map: "Walk up to it first".
    Adjacent: state flips — marker turns green/grey in BOTH windows, F5 keeps
    it, a 🕹 line appears in the chronicle.
11. Lever with op "door: open/close nearest" placed next to a door edge:
    player clicks the lever → the door swings open with the normal door fog
    reveal; again → closes. A LOCKED door resists ("It won't budge."). A
    DM-only lever is invisible to players and refuses them without leaking
    anything; a lever wired to a SECRET door answers "Nothing happens." and
    the secret door stays invisible.
12. NPC sheet → "Controlled by: led by <player>": that player can move the
    token, preview paths, add conditions, use its turn (combat), cast through
    it and open doors next to it. An unrelated player is refused for all of
    these; the DM changes nothing. F5 keeps the assignment; the sheet header
    shows "· led by <player>".
13. Revoke (—""): the player's move attempts fail immediately; DM still acts.
14. Fog rule: a controlled companion standing in unexplored dark is VISIBLE
    to its controller (it's the token they play) but lifts NO fog around it
    — the surroundings stay black until the DM reveals.
15. NPC sheet → "Mounted on: rides <token>": assign, F5 — persists. Assign
    the reverse direction (mount rides its own rider): "riding cycle" refused.
    Ride itself: refused. Tokens from another room: refused. Carrying moved to
    the D83 section below (Sprint 17).

## ROTATION-ORIENTS / CARRYING / MODES / FORCED (D83 — Tactical only)

GEOMETRY
1. Give a token mechanical Footprint 3×7 (sheet) and an independent Visual
   Size (e.g. 1×5): the artwork and the collision rect differ — select it and
   watch the outline. F5: both persist.
2. Confirm the artwork is CENTERED on the footprint (visual 1×5 on a 3×7:
   symmetric overhang top/bottom, not hanging off a corner).
3. Rotate 90° (⟳): the token stays on the same spot — the FOOTPRINT becomes
   7×3 (select it; the collision outline proves it), the artwork turns with
   it, and the doubled centre did not visibly jump.
4. Rotate 180° back: the footprint is 3×7 again at the EXACT original cells.
5. Walk a rotated 2×4 through a 2-wide corridor: it fits (still 2 wide — the
   box turned back at 0/180 would not; check with ⟲/⟳ that 90 makes it 4×2
   and the corridor preview then refuses).
6. Rotate a wide token tight against a wall/another token: refused with "No
   room to turn there" — old facing AND old position AND old cells intact.
7. Visual 3×7 with mechanical 1×1: the artwork reaches over walls, but path
   previews and finish checks still use only the 1 cell (walk it into a
   one-cell corridor — it fits).

MOUNT CARRYING
8. Mount a rider on a mount (sheet "Mounted on"), then move the MOUNT (walk
   or DM drag): the rider tracks every step, centred inside the mount.
9. Move the mount through cells the rider sits on: never self-blocked.
10. Unmount (—""): the rider is re-homed to a legal adjacent cell instead of
    standing inside its former mount; move the mount again — rider stays put.
11. Nested chain (A on B on C): moving C carries B and A; refresh keeps all
    positions and relationships; cycles still refused (D82 pin).

MOVEMENT MODES
12. NPC with a fly speed: sheet shows Move-mode chips (🚶 walk / 🕊 fly ft).
    Creature WITHOUT a speed: that mode is refused by the server even if the
    client asked ("This creature has no fly speed").
13. In combat on its turn: move while walk selected until the meter is spent;
    switch to fly — fly has its own budget and still works; switch BACK to
    walk: the walk meter is NOT refilled. Dash doubles every mode exactly
    once; nothing else regenerates movement.
14. Fly over a difficult-terrain strip / elevation cliff: costs 1 per square
    and crosses the cliff; the same route on foot costs double / stops.
    Flying still cannot cross walls or closed doors.

FORCED MOVEMENT (DM panel / console)
15. Push a token: it stops at the first illegal cell (wall/closed door/
    occupied); pull moves toward the source; teleport may skip the path but
    never an illegal destination.
16. Target's move meter is UNCHANGED after any forced move (forced ≠ voluntary);
    a DOWNED/incapacitated token can still be pushed or teleported by the DM.
17. DM knocks a token prone ("knock_prone" op / future trap): it shows the
    normal prone condition and must pay the normal Stand Up cost — the same
    one prone system, no second one.

No Diorama verification anywhere (out of scope by decision).
16. Diorama shows none of the new UI/objects (out of scope, by design) and
    old data never shows anything new until the DM assigns it.

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

## Sprint 18 — geometry centre (D84), artwork (D85), floors (D86), darkness (D87)

Geometry (needs a big token — make one 3x7 with footprint W=3 H=7 and rotate 90°):
- Click a FREE cell far away with the big token selected → the dashed ring sits
  exactly where the token's CENTRE will land; the token walks and its centre
  box covers the clicked cell. No "No path there" while the ring is on free air.
- Drag-drop a token: it lands with its CENTRE under the pointer, not shifted.
- Press Escape → sheet closes, selection ring gone.
- The collision footprint appears only while selected / editing / `?debug` and
  is a thin dashed OUTLINE (never a filled colour block).
- Companion view: a player OPERATING a 3x7 token (DM set controller) sees it
  as 3x7 (rotated 90° → 7x3) — never as a small circle; refresh (/state path)
  keeps the same shape.

Artwork (sheet row "Artwork", DM row on NPC tokens too):
- Upload a PNG (<1.5 MB) → the token immediately wears it inside its body
  ellipse, artwork turns WITH rotation (exactly one turn — no double rotation),
  aspect preserved.
- Non-PNG (rename a JPG to .png and try) → clean error toast, no broken token.
- Another account cannot load the asset URL (404); deleting an asset a token
  wears is refused until removed from the token ("— none —" + Apply removes).
- Players can attach only their OWN uploads; DM can attach any (403-less: the
  error toast "Not your asset").

Floors (sheet row "Floor"; DM adds floors via the ＋ field):
- DM adds floor "crypt", moves an NPC there → for the player on the primary
  floor the NPC VANISHES (token_leave, fog-memory ghost stays at the stairs).
- Move the player's own token to "crypt" → the NPC reappears there; they can
  occupy the SAME map cells as tokens on the other floor without blocking.
- Refreshing the page (player) shows only their own plane; the DM sees all.
- Floor name fields refuse path-like junk (`../x`).

Darkness (DM candle button 🕯 in the brush bar):
- Toggle dark ON as DM: for players WITHOUT light only their own token and its
  immediate footprint remain — terrain goes dark beyond that.
- Player sets Light (sheet row) to 6 + Apply → world opens an LOS-limited
  bubble; cells behind walls stay dark (real shadows); set back to 0 → the
  bubble closes again (seen tokens vanish via normal leave).
- DM view is never darkened. Toggle OFF restores classic vision.
- Toggling unrelated map edits (draw a wall) does not silently flip darkness.

## History

- Sprint 20: D90 section added (caster-plane ability truth, plane-scoped AoE/ping,
  resize pin/elev carry). Canonical close: 499 passed + 17 skipped. The
  "browser flow" automation is a Node-vm harness — no real browser runtime
  exists on the test host.

- Sprint 18: D84–D87 section added (centre contract, artwork pipeline, floor
  planes, darkness/light). Canonical run at close: 474 passed + 15 skipped.
- Sprint 17: D83 section (rotation orients the footprint, carrying riders,
  movement modes, forced layer, knock-prone). D82 rotation step adjusted.
- Sprint 16: D82 section added (visual size / rotation / world objects /
  controller / mount, Tactical only). Diorama deliberately unchanged.
- Sprint 12: BUILD CHECK added — `ReferenceError: gridOrigin is not defined`
  in a real browser proved mixed script generations were the black-canvas
  root cause across sprints 10–11 (DECISIONS D78). Bring step added to the
  smoke test (previously missing — the tester had no token and read the
  legitimate fog as a total failure).
- Sprint 11: smoke test created after black-screen/Diorama one-way/room-delete
  manual regressions (see DECISIONS D75–D77, MANUAL_FIX_NOTES.md).

## Sprint 19 — Floor maps, stair connectors, lighting v2 (D88/D89)
- [ ] DM: create floor "crypt", select it in "Viewing plane" — map, grid and canvas show the crypt; token positions unchanged; switch back restores primary view.
- [ ] DM: edit walls/dark/fog while crypt is selected → primary map untouched; a player on primary sees none of it.
- [ ] DM: place a "stair" object (Edit map → Object → stair → target floor/cell); player walks next to it, clicks 🕹 → token moves to crypt at the destination; player's board re-renders the crypt; chronicle shows the 🪜 line.
- [ ] DM: stand an NPC on a stair destination first → player's attempt answers "No room down there." and the token stays.
- [ ] DM: enable darkness on crypt only → crypt is dark (light-governed), primary stays normally lit.
- [ ] DM: place a lamp (Object → lamp) on crypt; a player on crypt sees what its glow circle reaches; player clicks 💡 to extinguish → circle and revealed tokens vanish for everyone on crypt; reload page → lamp stays off.
- [ ] Player: token sheet → Darkvis. 8 in a dark room with no light → that player now sees ~8 cells around their token, nobody else gains sight of it.
- [ ] DM: token light on an NPC another player controls → controller gains no light-vision from it.
- [ ] Old room (created before Sprint 19): map, fog, doors, levers behave exactly as in Sprint 18.

## Sprint 20 — Cross-floor AoE/ping truth, resize carry (D90)
- [ ] DM views "crypt"; arms AoE template and clicks: a PLAYER standing on the crypt sees the template; a player on primary sees nothing. Switch DM view back to primary → previously shown foreign-plane template does NOT linger/paint.
- [ ] Player pings on their own plane: seen by the DM and plane mates only; a player standing on another plane sees nothing. Ping spam (≥6 in 2s) still gets rate-limited.
- [ ] Player token on primary, DM moves an NPC to "crypt" at the SAME map coordinates; player casts an area ability at those cells: chronicle/roll effects hit only the primary token — the crypt NPC is not named, not counted, HP unchanged (check sheet as DM).
- [ ] Player targets the crypt NPC directly (token id known): answer is the ordinary "No target token" — identical to a bogus id.
- [ ] DM sets light/darkvision/artwork/floor on a hidden NPC while a player watches: that player's console/network sees no token_image/light/darkvision/floor events for the unseen token.
- [ ] DM edits map with resize (e.g. 40→30 wide) on a plane that has pins and elevation steps: pins that still fit are where they were (same titles/visibility), elevation heights survive; pins outside the new window drop (by design).
- [ ] Lamp toggled off on a plane → refresh the page (F5): still off. A DM with an OLD editor tab saves the map: lamp stays off.
- [ ] Tactical smoke (mirrors tests/test_browser_flow.py — automated there in a Node vm, NEVER in a real browser so far): open Tactical → own token visible → click a rectangular (≥2 wide) token: it selects → click a valid destination: gold preview appears within budget → confirm → token walks to the anchored final cell → F5 refresh: token still in place and still selectable at that spot.

## Sprint 23 — sheet & combat (D93)
- [ ] DM → Inv tab: name „Langschwert", kind weapon, dmg `1d8`, type slashing, abil STR, ☑ prof → **+ Def** → grant ×1 to a player. Player: 🎒 Inv → Equip into Main hand → sheet opens on the token: Attack section shows `⚔️ Langschwert +7` (STR3+Prof2+… verify vs your sheet), Initiative/Prof chips above the HP bar.
- [ ] Player attacks Dummy token (target select → Attack, Action): dice line names the target AC + HIT/MISS; HIT posts damage `1d8+3`. DM applies via existing HP buttons. Unequip → Attack section empty, attacking errors „No equipped weapon".
- [ ] Combat: DM starts initiative → on player's turn first attack OK, second same turn refused „No action left"; slot=Bonus attacks once more; off-turn attack refused; end combat → attacks free again. Reload (F5) mid-combat: tracker + slots intact.
- [ ] Privacy: second player logs in → clicks first player's token: compact public card (HP/AC/Speed), no items/spells/stats. DM sees the full sheet.
- [ ] Legacy: a character with a classic `weapons` entry still attacks by name exactly like before (no AC verdict).
- [ ] D94: DM hides a monster (out of your vision) → you attack it by id (devtools): error is exactly „No target token" — same as a wrong id. DM still sees/attacks it normally.
