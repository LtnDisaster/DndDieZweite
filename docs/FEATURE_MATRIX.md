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
(D112, Sprint 41): 883 passed, 1 skipped. Kanon D113 (Sprint 42 Phases 2–7):
921 passed, 1 skipped. Kanon D114 (Sprint 43): 948 passed, 1 skipped.
**Aktueller Kanon autonom / D128: 985 passed, 0 skipped, 0 failed.** Kanon D129 (AP-015, Exhaustion): 994 passed, 0 skipped. **Aktueller Kanon autonom / D130 (AP-016, Save Ends): 1000 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D131 (AP-017, casting_time): 1007 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D132 (AP-018, value_gp/cr): 1013 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D133 (AP-019, Loot-Container): 1018 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D134 (AP-020, Incapacitated): 1022 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D135 (AP-021, Inspiration): 1029 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D136 (AP-022, Stabilize): 1033 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D137 (AP-023, Cover/Spell): 1037 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D138 (AP-024/025, Prepare-Gate): 1040 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D139 (AP-026, Species-Origin): 1043 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D140 (AP-027, Swim/Climb-Surcharge): 1045 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D142 (AP-028, Ghost-Persistenz): 1047 passed, 0 skipped, 0 failed.** (D143: Infra — Makefile/Lock/Live-Smoke; Kanon unchanged.) **Aktueller Kanon autonom / D144 (AP-030, Speed-abhaengiger Aufschlag): 1050 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D145 (AP-031, Species-Boni): 1055 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D146 (AP-032, Consumables): 1060 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D147 (AP-033, Attune-Identify): 1063 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D148 (AP-034, Multi-Socket-Beweis): 1065 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D157+D158 (Raum-Löschung + Etagen-Aufzug): 1125 passed, 0 skipped, 0 failed.** **Aktueller Kanon autonom / D159 (Offene Volumen: Luft-Default, signed/below-Levels, freie 3D-Flugbewegung, Anzeige-Filter): 1137 passed, 0 skipped, 0 failed** (inkl. `test_d159_open_volumes.py` + `test_d159_view_frontend.py`; realer Chromium-E2E `scripts/e2e_d159_open_volumes.mjs` rc=0).
(D128 war im gepushten Stand implementiert und getestet, aber undokumentiert;
die Recovery-Sitzung 2026-10-17 bestätigte 985 als Baseline und reichte die
Doku nach — siehe `docs/RECOVERY_2026-10-17.md` und DECISIONS D128.)

AP-001 beseitigte den letzten dauerhaften Skip. AP-003 verdrahtete die
bestehende `duration`-Angabe als Startwert für Bedingungen. AP-004 nahm
`classes.spellcasting_ability` als optionale Casting-Meta in Build-Ledger,
Apply-Resultat und Wizard/Sheet-Anzeige auf. AP-005 machte `classes.expertise`
zu einer geführten Checkbox-Wahl mit exakter Servervalidierung. AP-006 prüfte
diese Kette erstmals in echtem headless Chromium. AP-007 machte
`feats.requires` zu einer echten fail-closed-Prüfung mit Wizard-Status. AP-008
machte `creatures.csv` über `npc.project_creature()` zu einem echten Zulieferer
des bestehenden Bestiariums. AP-009 führte Monster-`darkvision_ft` über den
NPC-Block auf die bestehende D89-Token-Sinnensäule. AP-010 macht die bestehenden
NPC-Skills im Monster-Sheet sichtbar und übergibt den kompletten Block beim Spawn
an die bestehende Server-Normalisierung. AP-011 erweiterte die eine
Effektgrammatik um `resource.mode=restore`, ohne einen zweiten Ressourcen-Zähler
anzulegen. AP-012 führte Geschwindigkeit, Dunkelsicht und Größe der Spezies über
dieselbe Sheet-Projektion in die bestehenden Movement-, LOS- und Footprint-Pfade.
AP-013 ließ `companion` aus `creatures.csv` als boolsche NPC-Block-Markierung durch
Content-API, Spawn, Editor, Sheet und Bestiarium laufen, ohne eine zweite
Ownership-Engine zu erzeugen.

## Matrix

| # | Kategorie | Status | Belege (Kern) | Lücken / Anmerkung |
|---|-----------|--------|---------------|--------------------|
| 1 | Login, Rollen, Raumverwaltung | A | `tests/test_auth_token.py`, `test_integration.py`, `test_room_delete.py`, `test_deploy_hygiene.py` (58 Tests; Cookie-Tokens, WS-Origin, Raum-Löschkaskade, Kick) | — |
| 2 | Raumvorbereitung & Charaktererstellung | A | `test_d101_prep.py` (13), `test_charbuild.py` (12); REST `charbuild_api.py:34-56` | — |
| 3 | 2024-Backgrounds, Origin-Feats, Fortschritt | A (Kern) | `test_d108_origin.py` (23), `test_progression.py` (8); Origin genau einmal via Ledger (`charbuild.py:356-426`); Nachtschicht 2026-10-16: `skill_prof`, Tools/Sprachen/Feature und `feats.spells_grant` auf dem bestehenden Build-Pfad (`test_engine_gear_grants.py`) | **D:** `feats.requires` wird nie geprüft (bewusst, bis ein belastbares 2024-Rangmodell existiert); Tool-/Sprach- und Hintergrund-Feature-Projektion sind Anzeige/Provenienz, keine eigenständige Adjudikation |
| 4 | Klassen, Spezies, Talente, Zauber | B/C gemischt | Executor `abilities.py` (Slotkosten, Zielgeometrie, Rettung/Angriff, Schadentypen, Konzentration-FLAG, Upcast), `test_spells.py`, `test_abilities.py`, `test_modifier_matrix.py`; Nachtschicht 2026-10-16: `feats.spells_grant`, geforderte `classes.expertise`-Auswahl als Wizard-Checkbox auf der Skill-Achse, `classes.weapon_prof/armor_prof`, Subclass-Features und species-Projektion als Build-Ledger/UI-Beleg; D118: `classes.spellcasting_ability` optional als Casting-Meta im Build-Ledger und in der Wizard-/Sheet-Anzeige | **B:** `classes.spell_replace`/`upcast_scaling` ohne vollständigen mechanischen Leser; Casting-Ability ist provenienzbasiert ohne Execution-Override, während Expertise exakt serverseitig erzwungen wird; Klassen-/Spezieswerte werden bewusst nicht in einen zweiten Bewegungs-/Größen-/Proficiency-Kern übersetzt; **C:** Zauber-`duration` startet Bedingungen, aber außerhalb der Kampfuhr gibt es keinen autonomen Ablauf; kein `components`-Feld, Konzentrautions-BRUCH bei Schaden ist seit D113 über `room/concentration.py` geschlossen |
| 5 | Ausrüstung, Inventar, Geld, Last, Attunement | A | Sprint-22-Suiten + `test_money_encumbrance.py` (18), `test_weapons_gear.py` (18), `test_d105_gear_loot.py` (24); integer-Kupfer kann nicht erzeugen/ins Negative laufen; Nachtschicht 2026-10-16: `speed_bonus_ft`, `darkvision_ft`, `hit_dice_bonus` and `hands` reach movement/LOS/rest/two-hand paths through existing gear/roll engines (`test_engine_gear_grants.py`) | `trigger` is handled by the D111 curse path, but item `duration` startet `condition`-Runden über die bestehende Engine; `feats.requires` weiterhin nicht erzwungen |
| 6 | Karteneditor, PNG-Assets, Türen, Weltobjekte | A | `test_mapmodel.py`, `test_d103_editor_assets.py`, `test_assets.py` (adverses PNG-Handling), `test_doors_dmonly.py`, `test_interact.py` (Allowlist: toggle/door/stair/lamp) | — |
| 7 | Stockwerke, Treppen, Token-Platzierung | A (D114 Sprint 43 + D159) | `test_floors.py`, `test_floor_maps.py`, `test_d102_floors.py`, `test_elevation.py`, `test_token_lifecycle.py`, `test_d114_vertical.py`, `test_d114_openings.py`, `test_d114_phase5_integration.py`, `test_d114_phase6_vertical_movement.py`, `test_d114_phase8_integration.py`, `test_d159_open_volumes.py`, `test_d159_view_frontend.py`; Treppen = validierte Interacts (`room/interact.py`); kanonische 10-ft-Höhenskala (`app/vertical.py`); Tokenvolumen/`openv`/Körperpräsenz/`slab`/`air` in `app/room/vertical3d.py`; signierte/below-Ebenen in `app/floors.py`; 3D-Pfad in `app/path.py`, vertikaler Flug in `app/room/movement.py`, UI/Editor in `30_room.js`/`50_canvas.js` | Skala eindeutig (1 Einheit / 1 Ebene = 10 ft); Volumen, etagenübergreifende Sicht, vertikaler + diagonaler (komponierter) Flug, Volumen-Kollision, UI und `openv`-Editor umgesetzt. D159: Ground (E0) Default-Boden, nie bearbeitete Nicht-Primary-Ebenen = Luft(`air`,6), gelegte Fläche = massive `slab`-Platte (deckt Säule + blockiert Sicht/Vertikalbewegung), `openv`/`air`/`void` öffnen, signed/below-Levels (E−1…), `floor_levels`-Tags + Anzeige-Filter „All visible“/„This floor only“ (rein darstellend). Bewusst offen: Springen/Fallen, vertikales Klettern/Schwimmen, interaktive 3D-Pfadvorschau; Sturzschaden/Höhen-Deckung bleiben E (`docs/VERTICAL_GEOMETRY.md`) |
| 8 | Bewegung, Kollision, Reichweite, Sicht, Fog | A | ~114 Tests (A*, Diagonalen 1/2/1/2, Rechteck-Footprints, Fly/Swim/Climb-Ledger, erzwungene Bewegung, Tür×LOS) | Reichweitenmessung läuft über Footprint-Zellen ×5 ft (D109-Auditfix, TODO Sprint 38) |
| 9 | Licht, Dunkelsicht, DM-View-as | A | `test_lighting.py`, `test_lighting2.py`, `test_d104_lights_preview.py`; View-as = REST `GET /api/rooms/{code}/view_as/{cid}` mit DEMSELBEN `_viewer_token_view` wie `/state` (`rooms.py:767-801`) | View-as ist REST-only (kein WS-Streaming der Geistersicht) — akzeptierte Grenze, Browser-abprüfen |
| 10 | Initiative, Angriffe, Schaden, Conditions | A (Kern) | `test_combat_turn.py`, `test_conditions_lifecycle.py`, `test_sprint23_combat.py`, Death-Save-Flows in `test_integration.py`; 2024-Grapple/Shove/Escape + Kontesto in Zeile 17; Condition-Hooks sind über Angriffe, Checks, Saves, Bewegung und Speed-Änderung in den bestehenden Engines verdrahtet | Exhaustion wirkt kumulativ (D129: −2 auf alle W20-Würfe, −5 ft walk je Stufe, Tod bei Stufe 6, Long Rest −1). Grapple/Condition-Dauer folgt dem bestehenden Runden-/Initiativ-Zähler; eine vollautomatische Uhr außerhalb des Kampfes ist bewusst nicht als zweite Engine angelegt |
| 11 | Alle acht Weapon-Masteries | A | `test_d109_mastery.py` (29), Modell + Abweichungen dokumentiert (`RULES_AUDIT_2024.md` §8) | Marker nur in Initiative, Damage>0-Proxy (dokumentierte Grenzen) |
| 12 | Tod, NPC-Inventar, Loot | A | `test_downed_movement.py`, `test_npc_workflow.py`, `test_d105_gear_loot.py` (atomare, adjacency-gegate Überträge) | Karten-Loot („Loot“-Objekt) ist Buchführungs-Text (`room/traps.py:86-91`) → **D:** echter Loot-Container fehlt |
| 13 | Flüche, private Whispers, Chat-Historie | A (Kern) | `test_d106_curses.py` (26), `test_chat.py`; History-Replay in `/state` (`rooms.py:744`), Whisper insert-then-targeted (`room/chat.py:197-239`) | **D:** automatische Fluchwirkungen (Fluch triggert Mechanik) fehlen — nur Metadaten + DM-Enthüllung |
| 14 | REST-/WS-Berechtigungen | A | 44 explizite 403/401-Assertions + Adversiv-Suiten Sprint19/20/21/24, Cross-Room-Pins in 8 Dateien | — |
| 15 | CSV-Import, Validierung, Generator, Content-Isolation | A | `test_content.py` (19: Datei/Zeile/Spalte, Zeilenisolation, Zip-Guards, Formel-Injection), Generator-Byte-Idempotenz im Kanon-Image (Dockerfile test-Stage) | „Spalte ≠ Mechanik“-Prüfung separat: `docs/CSV_ONLY_READINESS.md` (species/creatures sind datenführend isoliert, s. Zeile 4/12) |
| 16 | Reload, Reconnect, Persistenz | A | ~130 Pins: Reconnect-Snapshots in 12 Dateien, ~105 op_id-Replay-Pins über alle Inventar-/Kampfoperationen, DB-Neustart-Pins (`test_charbuild.py`, `test_d108_origin.py`) | — |
| 17 | Gegeneinanderprobe, 2024-Sonderkampf & Taschendiebstahl (D112) | A | `test_d112_contested.py` (31: Save-/Tie-Einheit, Grapple/Shove/Escape, beide Pickpocket-Modelle, Leak-/Replay-/Nebenläufigkeits-/Cross-Room-/Cross-Plane-/Aktionsökonomie-Pins); `app/room/opposed.py` (Helfer) + `grapple.py` + `pickpocket.py`; Tie Default `defender`, DM-Delegation via `Tie` | kein 2014-Athletik-Wettkampf (bewusst 2024); Kontesto jetzt auch Grammatik-Op (→ Zeile 19) |
| 19 | Konzentration 2024 + automatische Flüche + `opposed`-Op + Fallen + 10-ft-Vertikalskala (D113) | A (Kern) | `test_d113_concentration.py` (9), `test_d113_curses.py` (9), `test_d113_opposed.py` (6), `test_d113_traps.py` (10), `test_d113_vertical.py` (4); `app/room/concentration.py`, `conc`-Link (`conditions.py`), `on_transfer`-Trigger + Fluch-Träger (`effectops.py`, `room/inv.py`), `active`/`arm`/`activate` (`inventory.py`, `gear.clean_curse`), Grammatik v2 (`effectops` V_MIN..V_MAX), Fallen `effects`/`search_dc`/`disarm_dc`/`repeat` + WS `trap` (`room/traps.py`, `mapmodel.py`), Vertikalskala (`app/vertical.py`, `floors.level`) | Sprint 42 (Phasen 2–7) erledigt; offen: nur der menschliche Browser-Durchlauf der Phase-6-Oberflächen (Curse ⚙/🔮, Fallen-Editor/🔍-🔧) |
| 20 | Gear-/Build-Integration der Nachtschicht (D115) | A | `test_engine_gear_grants.py` (11); `movement._speeds`, `visibility._token_darkvision_cells`, short-rest hit-dice gear bonus, `gear.wields_two_handed`, optional class expertise, `charbuild._replay_origin`, `_feat_grants`, class/species/subclass projectors; UI: `80_prep.js`, `30_room.js` | bewusst keine neue Adjudikation: `feats.requires`, Species-/Klassen-Mechanik und Item-/Spell-Duration bleiben bestehende Grenzen |

## Geplant, aber noch nicht implementiert (Kern — Teil der Restarbeitsplanung, nicht optional)

Bereits besprochen und bestätigt gewollt (aus `TODO.md`-Sektion „bewusst
nicht gebaut“, die D110 als Restarbeit umwidmet, plus Audit R-Liste):

| Funktion | Vorhandene Vorarbeit | Komplexität |
|---|---|---|
| Automatische Fluchwirkungen (Auslöser beim Anlegen/Benutzen) | Fluch-Metadaten + Identify vorhanden; Effektgrammatik fehlt | M–L |
| ~~Konzentraitions-BRUCH bei Schaden~~ **erledigt D113** (Zeile 19) | Concentration-FLAG + Con-Rechnung ja | S–M |
| (Erledigt: `incapacitated`-Wirkung D134 → Hook `no_actions` auf Angriff/Wirk/Escape/Dash; Grapple/Shove/Prone-Offensive D112 → Zeile 17; Exhaustion D129 → Zeile 10) | Condition-Uhr + Prone-/Bewegungs-Sperre ja | — |
| Zauber-Dauer-Ablauf + Komponenten | Dauer nur Text; Uhren existieren (Conditions) | M |
| Spezies→Bogen: nur Projektion, keine mechanische Bewegung | species row now becomes a read-only `build.species` ledger/UI snapshot; footprint and speed engines deliberately unchanged | M |
| ~~Hintergrund-Fertigkeiten und `feats.spells_grant`~~ **erledigt Nachtschicht 2026-10-16** | existing origin/build chronology; background tools/languages/feature are visible | S |
| `feats.requires` | prerequisite text remains content metadata; no reliable rank model | S |
| Monster-Sonderaktionen aus Daten (heute nur strukturierte Angriffe) | Executor + NPC-Block vorhanden | L |
| Echte Loot-/Kistenobjekte auf der Karte (statt Buchführungstext) | Container-System (D92) vorhanden | M |
| ~~Ausrüstungs-Speed/Darkvision mechanisch verdrahten~~ **erledigt Nachtschicht 2026-10-16** | `movement._speeds` + darkvision LOS consume `gear.effective_gear` | S |

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
4. **creatures.csv → NPC-Projektion** ist DM-preview + Bestiarium-Import
   realisiert; direkter Spawn aus der Raumzeile und komplexe Sonderaktionen
   bleiben offen (D122).

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
