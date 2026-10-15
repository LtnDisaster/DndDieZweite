# Funktionsmatrix — tatsächlicher Bestand (D110-Bestandesaufnahme, Stand Sprint 39; fortgeschrieben bis D113/Sprint 42)

Erstellt aus Code-, Test- und UI-Belegen (Datei:Zeile), nicht aus TODO-Texten.
Legende Status:
**A** = implementiert und automatisiert getestet · **B** = implementiert,
Integration unvollständig · **C** = nur teilweise implementiert ·
**D** = geplant, aber noch nicht implementiert (volle Restarbeitsplanung —
**nicht** optional) · **E** = bewusst außerhalb des Feature-Complete-Ziels.

Projektstrategie (D110): **kein „Back Backlog“** — alles Gewollte gehört in
die Restarbeitsplanung; Ziel ist Engine-Fertigstellung + datengetriebene
Erweiterbarkeit, danach CSV-Produktion und Serverbetrieb.

Kanonscher Stand vor D110: 826 passed, 1 skipped, 0 failed. Aktueller Kanon
(D112, Sprint 41): 883 passed, 1 skipped. Aktueller Kanon (D113, Sprint 42
Phases 2–7): **921 passed, 1 skipped, 0 failed** (883 + 9 Konzentration + 9
Flüche + 6 Opposed-Op + 10 Fallen + 4 Vertikal).
Der 1 Skip ist eine Altlast (`tests/test_sprint24_hardening.py:136`, hart
markiert, Server-Gate existiert + ist anderweitig gepinnt) — kein D110-Skip.

## Matrix

| # | Kategorie | Status | Belege (Kern) | Lücken / Anmerkung |
|---|-----------|--------|---------------|--------------------|
| 1 | Login, Rollen, Raumverwaltung | A | `tests/test_auth_token.py`, `test_integration.py`, `test_room_delete.py`, `test_deploy_hygiene.py` (58 Tests; Cookie-Tokens, WS-Origin, Raum-Löschkaskade, Kick) | — |
| 2 | Raumvorbereitung & Charaktererstellung | A | `test_d101_prep.py` (13), `test_charbuild.py` (12); REST `charbuild_api.py:34-56` | — |
| 3 | 2024-Backgrounds, Origin-Feats, Fortschritt | A (Kern) | `test_d108_origin.py` (22), `test_progression.py` (8); Origin genau einmal via Ledger (`charbuild.py:356-426`) | **D:** Background-Felder `skill_prof`/`tool_prof`/`languages`/`feature` importiert, aber nie auf dem Bogen (`content.py:175-177`, null Leser); `feats.requires` wird nie geprüft; `feats.spells_grant` nie angewandt (Kontrast `charbuild.py:111`) |
| 4 | Klassen, Spezies, Talente, Zauber | B/C gemischt | Executor `abilities.py` (Slotkosten, Zielgeometrie, Rettung/Angriff, Schadentypen, Konzentration-FLAG, Upcast), `test_spells.py`, `test_abilities.py`, `test_modifier_matrix.py` | **B:** `classes.weapon_prof/armor_prof/expertise/spellcasting_ability/upcast_scaling` ohne Leser; **C:** Zauber-`duration` ohne Ablauf-Engine, kein `components`-Feld, Konzentrautions-BRUCH bei Schaden fehlt (nur FLAG, `conditions.py:229`) — seit D113 geschlossen (`room/concentration.py`, `conc`-Link); **D:** Spezies rein datenführend (`content.load("species")` existiert nirgends; `characters.size/speed` nie aus Spezies) |
| 5 | Ausrüstung, Inventar, Geld, Last, Attunement | A | Sprint-22-Suiten + `test_money_encumbrance.py` (18), `test_weapons_gear.py` (18), `test_d105_gear_loot.py` (24); integer-Kupfer kann nicht erzeugen/ins Negative laufen | **B:** `speed_bonus_ft` und `darkvision_ft` nur Bogen-Anzeige — Bewegungs-/Sicht-Pfad lesen sie nicht (`room/movement.py:72-73`, `room/visibility.py:66`); `items.hands`/`hit_dice_bonus`/`trigger`/`duration` ohne Konsumenten |
| 6 | Karteneditor, PNG-Assets, Türen, Weltobjekte | A | `test_mapmodel.py`, `test_d103_editor_assets.py`, `test_assets.py` (adverses PNG-Handling), `test_doors_dmonly.py`, `test_interact.py` (Allowlist: toggle/door/stair/lamp) | — |
| 7 | Stockwerke, Treppen, Token-Platzierung | A (D114 Sprint 43) | `test_floors.py`, `test_floor_maps.py`, `test_d102_floors.py`, `test_elevation.py`, `test_token_lifecycle.py`, `test_d114_vertical.py`, `test_d114_openings.py`, `test_d114_phase5_integration.py`, `test_d114_phase6_vertical_movement.py`, `test_d114_phase8_integration.py`; Treppen = validierte Interacts (`room/interact.py`); kanonische 10-ft-Höhenskala (`app/vertical.py`); Tokenvolumen/`openv`/Körperpräsenz in `app/room/vertical3d.py`; 3D-Pfad in `app/path.py`, vertikaler Flug in `app/room/movement.py`, UI/Editor in `30_room.js`/`50_canvas.js` | Skala eindeutig (1 Einheit / 1 Ebene = 10 ft); Volumen, etagenübergreifende Sicht, vertikaler Flug, Volumen-Kollision, UI und `openv`-Editor sind umgesetzt. Bewusst offen: diagonale + vertikale Kombination, Springen/Fallen, vertikales Klettern/Schwimmen, interaktive 3D-Pfadvorschau; Sturzschaden/Höhen-Deckung bleiben E (`docs/VERTICAL_GEOMETRY.md`) |
| 8 | Bewegung, Kollision, Reichweite, Sicht, Fog | A | ~114 Tests (A*, Diagonalen 1/2/1/2, Rechteck-Footprints, Fly/Swim/Climb-Ledger, erzwungene Bewegung, Tür×LOS) | Reichweitenmessung läuft über Footprint-Zellen ×5 ft (D109-Auditfix, TODO Sprint 38) |
| 9 | Licht, Dunkelsicht, DM-View-as | A | `test_lighting.py`, `test_lighting2.py`, `test_d104_lights_preview.py`; View-as = REST `GET /api/rooms/{code}/view_as/{cid}` mit DEMSELBEN `_viewer_token_view` wie `/state` (`rooms.py:767-801`) | View-as ist REST-only (kein WS-Streaming der Geistersicht) — akzeptierte Grenze, Browser-abprüfen |
| 10 | Initiative, Angriffe, Schaden, Conditions | A (Kern) | `test_combat_turn.py`, `test_conditions_lifecycle.py`, `test_sprint23_combat.py`, Death-Save-Flows in `test_integration.py`; 2024-Grapple/Shove/Escape + Kontesto in Zeile 17 | **D:** Condition-Wirkungen blind/invisible/poisoned nicht verdrahtet; Konzentrautions-BRUCH fehlt (→ D113 erledigt, Zeile 19); Exhaustions-Stufen ohne Wirkung (Audit R-P1/R-P2). grappled/restrained verdrahtet: D111 (Bewegungs-Hook) + D112 (Grapple-Zustand mit `dc`) |
| 11 | Alle acht Weapon-Masteries | A | `test_d109_mastery.py` (29), Modell + Abweichungen dokumentiert (`RULES_AUDIT_2024.md` §8) | Marker nur in Initiative, Damage>0-Proxy (dokumentierte Grenzen) |
| 12 | Tod, NPC-Inventar, Loot | A | `test_downed_movement.py`, `test_npc_workflow.py`, `test_d105_gear_loot.py` (atomare, adjacency-gegate Überträge) | Karten-Loot („Loot“-Objekt) ist Buchführungs-Text (`room/traps.py:86-91`) → **D:** echter Loot-Container fehlt |
| 13 | Flüche, private Whispers, Chat-Historie | A (Kern) | `test_d106_curses.py` (26), `test_chat.py`; History-Replay in `/state` (`rooms.py:744`), Whisper insert-then-targeted (`room/chat.py:197-239`) | **D:** automatische Fluchwirkungen (Fluch triggert Mechanik) fehlen — nur Metadaten + DM-Enthüllung |
| 14 | REST-/WS-Berechtigungen | A | 44 explizite 403/401-Assertions + Adversiv-Suiten Sprint19/20/21/24, Cross-Room-Pins in 8 Dateien | — |
| 15 | CSV-Import, Validierung, Generator, Content-Isolation | A | `test_content.py` (19: Datei/Zeile/Spalte, Zeilenisolation, Zip-Guards, Formel-Injection), Generator-Byte-Idempotenz im Kanon-Image (Dockerfile test-Stage) | „Spalte ≠ Mechanik“-Prüfung separat: `docs/CSV_ONLY_READINESS.md` (species/creatures sind datenführend isoliert, s. Zeile 4/12) |
| 16 | Reload, Reconnect, Persistenz | A | ~130 Pins: Reconnect-Snapshots in 12 Dateien, ~105 op_id-Replay-Pins über alle Inventar-/Kampfoperationen, DB-Neustart-Pins (`test_charbuild.py`, `test_d108_origin.py`) | — |
| 17 | Gegeneinanderprobe, 2024-Sonderkampf & Taschendiebstahl (D112) | A | `test_d112_contested.py` (31: Save-/Tie-Einheit, Grapple/Shove/Escape, beide Pickpocket-Modelle, Leak-/Replay-/Nebenläufigkeits-/Cross-Room-/Cross-Plane-/Aktionsökonomie-Pins); `app/room/opposed.py` (Helfer) + `grapple.py` + `pickpocket.py`; Tie Default `defender`, DM-Delegation via `Tie` | kein 2014-Athletik-Wettkampf (bewusst 2024); Kontesto jetzt auch Grammatik-Op (→ Zeile 19) |
| 19 | Konzentration 2024 + automatische Flüche + `opposed`-Op + Fallen + 10-ft-Vertikalskala (D113) | A (Kern) | `test_d113_concentration.py` (9), `test_d113_curses.py` (9), `test_d113_opposed.py` (6), `test_d113_traps.py` (10), `test_d113_vertical.py` (4); `app/room/concentration.py`, `conc`-Link (`conditions.py`), `on_transfer`-Trigger + Fluch-Träger (`effectops.py`, `room/inv.py`), `active`/`arm`/`activate` (`inventory.py`, `gear.clean_curse`), Grammatik v2 (`effectops` V_MIN..V_MAX), Fallen `effects`/`search_dc`/`disarm_dc`/`repeat` + WS `trap` (`room/traps.py`, `mapmodel.py`), Vertikalskala (`app/vertical.py`, `floors.level`) | Sprint 42 (Phasen 2–7) erledigt; offen: nur der menschliche Browser-Durchlauf der Phase-6-Oberflächen (Curse ⚙/🔮, Fallen-Editor/🔍-🔧) |

## Geplant, aber noch nicht implementiert (Kern — Teil der Restarbeitsplanung, nicht optional)

Bereits besprochen und bestätigt gewollt (aus `TODO.md`-Sektion „bewusst
nicht gebaut“, die D110 als Restarbeit umwidmet, plus Audit R-Liste):

| Funktion | Vorhandene Vorarbeit | Komplexität |
|---|---|---|
| Automatische Fluchwirkungen (Auslöser beim Anlegen/Benutzen) | Fluch-Metadaten + Identify vorhanden; Effektgrammatik fehlt | M–L |
| ~~Konzentraitions-BRUCH bei Schaden~~ **erledigt D113** (Zeile 19) | Concentration-FLAG + Con-Rechnung ja | S–M |
| `incapacitated`-Wirkung, Exhaustion-Stufen (Grapple/Shove/Prone-Offensive ist D112 erledigt → Zeile 17) | Condition-Uhr + Prone-/Bewegungs-Sperre ja | M |
| Zauber-Dauer-Ablauf + Komponenten | Dauer nur Text; Uhren existieren (Conditions) | M |
| Spezies→Bogen (Größe/Tempo/Sinne aus CSV) | Größen-Footprints vorhanden (nur für NPC-Block) | M |
| Hintergrund-Fertigkeiten auf den Bogen; `feats.requires`; `feats.spells_grant` | Bogen-Infra + Grant-Pfad vorhanden | S–M |
| Monster-Sonderaktionen aus Daten (heute nur strukturierte Angriffe) | Executor + NPC-Block vorhanden | L |
| Echte Loot-/Kistenobjekte auf der Karte (statt Buchführungstext) | Container-System (D92) vorhanden | M |
| Ausrüstungs-Speed/Darkvision mechanisch verdrahten | Ein `_speeds`-Pflegestück + Sicht-Hook | S |

## Fehlende generische Regelunterstützung (Datengetriebenheits-Blocker)

Diese Punkte sind KEINE Einzelmechaniken, sondern die fehlende
Ausdruckskraft der CSV/Executor-Schicht — Details + Matrix:
`docs/CSV_ONLY_READINESS.md`:

1. **Effektgrammatik des Executors** kennt nur: Schaden/Heilung/Bedingung
   (fixe Runden), Kosten (Slot/Resource), Zielgeometrie, Upcast.
   Es fehlen als Daten ausdrückbar: Bewegungs-Effekte (Schub/Teleport),
   Ressourcen-Änderungen, Würfe/Proben, Dauer mit Rettung-Ende, Reaktionen,
   Auren, Beschwörungen.
2. **Zustandskatalog ist hartcodiert** (`app/conditions.py:20-44`, 18 Keys) —
   keine CSV-Kategorie; neue Zustände brauchen Code.
3. **Gegenstandseffekte = nur `heal` + charges** (`room/items.py:26-61`).
4. **creatures.csv ist datenführend isoliert** — kein Projektionsschritt in
   den NPC-Block/Executor (`content.load("creature")` = null Treffer).

## Bewusst außerhalb des Feature-Complete-Ziels (E)

- Sturzschaden und höhenbedingte Deckung/Vorteile bleiben außerhalb (reine
  Kampf-Mechanik, Engine-Kante bewusst nicht ausgebaut). Vertikale
  TOKEN-GEOMETRIE (Volumen, Öffnungen, etagenübergreifende Sicht/Reichweite,
  vertikaler Flug, Volumen-Kollision, UI/`openv`-Editor) ist seit D114
  (Sprint 43) umgesetzt; bewusst offene Grenzen sind diagonale + vertikale
  Kombination, Springen/Fallen, vertikales Klettern/Schwimmen und eine
  interaktive 3D-Pfadvorschau — siehe `docs/VERTICAL_GEOMETRY.md`.
- Automatische Weltvergrößerung ist Feature-flag OFF (D77: bewusst).
- Diorama-Renderer bleibt Projektions-Prototyp ohne eigene Regeln (D48);
  `55_diorama.js` ist für Sprint-Arbeit tabu.
