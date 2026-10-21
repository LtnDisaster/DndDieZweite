# D161 — Vollständiger Spielsitzungs-Audit: D&D-5e-2024-Spielbarkeit der DnDTable-App

**Datum:** 2026-10-19/20 · **System:** DnDTable (`~/DndDieZweite`), Build mit allen
Audit-Fixes, eigener Container `d161-app` auf `127.0.0.1:8021` · **Fixture:** isolierter
Audit-Stack (nur Container/Volumes/Ports `d161-*`, nur Loopback, kein geteiltes Produktmaterial).

## Urteil

**JA, MIT EINSCHRÄNKUNGEN.**

Eine vollständige 5e-2024-Sitzung (Registrierung → Charakterbau → Nebel/Kampf/Zauber/
Todesrettungswürfe → Ebenen/Treppe/Flug → Beute/Attunement/Rasten → echter
Container-Neustart → DM-Ad-hoc-Aktionen → Sicherheitstest) ist **durch die echte UI
durchspielbar**; kein P0. Fünf echte P1-Bugs wurden live reproduziert, gefixt und mit
Regressionstests fest genagelt. Die Einschränkungen sind dokumentierte P2-Lücken
(Handantragung von Schaden, kein Sturzschaden, kein Schlossknacken als Spielerzug,
Species-Bonus ohne UI, Rückweg-Treppe zur Primärebene nicht authorisierbar, …) — Details unten.

## Methode

* **UI-first:** Jeder Behauptungspfad läuft durch den echten Browser (Playwright),
  ein Browser-Context pro Nutzer (DM + 4 Spieler), echte WebSocket-Frames und REST-Kanäle.
  Nur wo es nachweislich keine UI-Steuerung gibt, wird ehrlich `api-only` /
  `fixture-only-gap` geurteilt — nie „grün“ erfunden.
* **Server-Wahrheit:** Verdicts vergleichen Client-Anzeige UND Serverzustand
  (`/api/rooms/…/state`, DB-Lesung im Container, gelauschte WS-Frames).
* **Fixture:** SRD-2024-Pack (Klassen/Rassen/Hintergründe/Zauber/Kreaturen/Gegenstände)
  als CSV-Pack per echtem ZIP-Import; 4 Helden per Wizard auf Stufe 2; Karte mit 5 Ebenen,
  Schacht, Türen, Fallen, Loot, Laterne per Map-Editor gemalt.
* **Beweise:** `e2e-evidence/*.png`, `verdicts_*.jsonl`, Logs `A1…A8.log` (Host),
  Skripte `scripts/e2e_d161_{lib,a1..a8}*.mjs`, Persistenz-Dumps `persist_{before,after}.json`.

## Spielbericht (Akte, finale Läufe)

| Akt | Inhalt | Verdicts | UI-OK | Rest |
|---|---|---|---|---|
| I | Konten, Raum, Pack-Import, 5 Ebenen, Map-Editor, 4 Helden im Wizard, Startausrüstung, Sitze | 27 | 27 | — |
| II | Nebel/Türen/Fallen: Leaks, Türen, Anti-Oracle, Fallen auslösen/entdecken | 14 | 11 | 1 api-only, 1 Fixture-Lücke (DM-Fallen-UI), 1 BROKEN = Harness-Flake (Disarm-Klick), Produktweg durch Proben 7–9 belegt |
| III | Kampf: Ausrüsten→AC, Initiative, Meisterschaft-Angriff, Aktionsökonomie, Zauber+Slots, Konzentration, Todesrettungswürfe, Erholungen | 16 | 15 | 1 api-only (Konzentrationssemantik korrekt, aber kein `conc`-Clientfeld) |
| IV | Ebenen: Treppenauf-/abstieg per Klick, Sicht folgt Ebene, Schachtflug (3D-Route), No-Fly-Verweigerung, Ebenen-Isolation | 9 | 7 | 1 Fixture-Lücke = echte Produktlücke P2-8, 1 api-only |
| V | Loot-Aufnahme, Spieler-zu-Spieler-Gabe, DM-Grant, Attunement, Trank, Kurz-/Langerrast | 7 | 5 | 2 api-only (Belegkanal Nuancen) |
| VI | **Echter Container-Neustart**: Sheets/Tokens/Karten/Fallen/Loot/Quests/Initiative + Kampagnenlog (100 msgs) | 2 | 2 | diff-in: `[]` — verlustfrei |
| Ph4 | DM-Stress: 12 Ad-hoc-Aktionen am laufenden Tisch | 12 | 9 | 3 api-only ehrlich |
| Ph5 | Sicherheit: fremde Tokens, DM-only-Kanäle, Flüstern, blinde Würfe, Replay, anonym 401, NPC-Leak | 8 | 6 | 2 api-only (stille DM-only-Ablehnung, Replay-Beobachtung) |

Akt VI ist der härteste Beweis: nach `docker restart` ist der **gespielte** Zustand
Byte-für-Byte (die auf Cellar stehenden Helden, Attunements, Fallengate, Loot-Flags, Rundenlog)
identisch wieder da.

## Behobene P1-Bugs (Fixradius: klein + reproduzierbar, je mit Test)

| # | Bug (live reproduziert) | Fix | Regressionstest |
|---|---|---|---|
| P1-1 | `renderInit` verdrahtete Dash/End-Turn ungeprüft → `TypeError` brach **jeden Raumbeitritt** nicht-aktiver Spieler bei laufender Initiative | Buttons nur bei Existenz verdrahten (`app/static/js/30_room.js`) | `tests/test_d161_turnbar_guest.py` |
| P1-2 | Stufenprojektion schrieb Klassensoloressourcen nur für Zauberer → **Action Surge/Zorn/Ki verschwanden** aus dem Bogen | `class_resources`-Projektion + eigener UPDATE-Zweig (`app/charbuild.py`) | `tests/test_d161_action_surge.py` |
| P1-3 | Einzelziel-Zauber hatten am Bogen **Cast-Knopf ohne Zielsteuerung** → Server antwortete „No target token“; Casting unmöglich | `.ab-tgt`-Zielauswahl + `target_id` im Cast (`30_room.js`) | `tests/test_d161_single_target_cast.py` |
| P1-4 | Leeres Journal versteckte das Notizpanel → **die erste Notiz war durch die UI nie erstellbar** (Neue/Save-Button saßen im versteckten Panel) | leerer Pfad rendert Panel über `renderNote(role)` (Rollen-Editierbarkeit bleibt) | `tests/test_d161_journal_first_note.py` |
| P1-5 | Ziel-Ebene-Primär (`""`) wurde in `_move3d`/`_teleport3d` per `msg["floor"] or current` verschluckt → **Flug/Teleport auf die Primärebene war ein lautloser No-op** (UI-Option „Ground (primary)“ = toter Knopf) | Parsing unterscheidet „kein Feld“ von `""` (`app/room/movement.py`) | `tests/test_d161_vertical_primary_floor.py` |

P1-5 war ein Volltreffer durch den Akt: ohne Fix hätte kein fliegender NPC und kein
DM-Token je zurück auf den Bodenebenen fliegen können — und der Tisch sieht keine Fehlermeldung.

## Dokumentierte Produktlücken (nicht behoben; P2)

* **P2-1** DM-Fallenkanal hat keine Oberfläche (Server erlaubt's, Traphud nur fürs eigene Token).
* **P2-2** Fallen-/Loot-Pinsel ohne Löschpinsel; erneutes Klicken überschreibt still mit den
  aktuellen Feldwerten. (Gegenstände haben `objrm` — Fallen/Loot nicht.)
* **P2-3** Pack-Import „apply“ aktualisiert geänderte Zeilen nicht (gleiche ID ⇒ übersprungen);
  „replace“ tut es. Für Nachlieferungen ist replace Pflicht.
* **P2-4** Kein Spieler-Schlossknacken-Endpunkt — Schlösser sind DM-Würfel-Improvisation.
* **P2-5** Angriffs-/Schadenswürfe werden nur gewürfelt+verlautbart, **nicht automatisch**
  auf HP angewendet; der DM trägt über das HP-Feld ein (Tischphilosophie, aber Reibung).
* **P2-6** Species-Bonus-Endpoint (`POST /species`) ohne jede UI-Steuerung — Artboni landen
  nie im Bogen (live verifiziert: Branns CON blieb auf Basiswert).
* **P2-7** Kein Sturzschaden („No fall damage, no height math“); 2024-Regel fehlt vollständig.
* **P2-8** (neu, Akt IV) **Rückweg-Treppe zur Primärebene ist nicht authorisierbar:** Der Editor
  verlangt zwingend einen Ziel-Ebenennamen („Stairs need a target floor name“), aber die
  Primärebene heißt leer — ein erfundener Name bleibt dangling und der Server antwortet
  ehrlich „Nothing happens.“. Wer in den Keller steigt, kommt per Treppe nicht zurück;
  DM-Planwechsel bleibt als Ausweg. Beweis-Toast im A4-Log.
* **P3** `item_defs.id` globaler PK (Raum-Kollisionen schlucken Grant-Bibliothek still —
  Audit-Fixture hat das erwischt); Wizard wählt Zauberer-Zauber automatisch alphabetisch;
  DM-only-Kanäle lehern stumm ab (kein Feedback an Spieler-Sockets).

## Regelabgleich 5e-2024-Kern

| Regel | Status | Beleg |
|---|---|---|
| Initiative, Rundenmarker, eigene Runde | ✅ | Akt III |
| Aktions-/Bonusökonomie inkl. Dash, Bewegung nur in eigener Runde | ✅ serverseitig | Akt III Off-Turn-Verweigerung |
| Meisterschaften + serverabgeleitete Angriffsprofile | ✅ | Akt III `.atk-mastery`, Profile aus getragener Waffe |
| AC aus getragener Rüstung + Dex (Equip-Pflicht) | ✅ | AC 10→12 nach Rüstungswechsel |
| Zauberfelder/Slots/Upcast, Konzentration (neuer Zauber ersetzt alten) | ✅ | Akt III |
| Todesrettungswürfe 10+/Nat20/Nat1×2, 3✓ stabil / 3✗ tot, Übermaß-Tod | ✅ | Akt III |
| Kurz-/Langerrast (HD, Short-Reset-Ressourcen, Slots/LP wieder voll) | ✅ | Akt III/V |
| Flug mit 3D-Route durch offenen Schacht, Fly-Budget, Decken-Verweigerung | ✅ | Akt IV (nach P1-5) |
| Sturzschaden | ❌ fehlt | P2-7 |
| Schlossknacken als Spieleraktion | ❌ kein Endpunkt | P2-4 |
| Artboni im Charakterbogen | ⚠️ API ja, UI nein | P2-6 |

## Sicherheit & Mehrspielertauglichkeit (Phase 5)

Fremde Token-Bewegung, DM-only-Kanäle, Flüsterrouting (Empfänger-only), blinde
Rettungswürfe (Zahlangabe nur an DM), Idempotenz-Replays, **anonymer Zugriff → 401**
und NPC-Werteblocks, die Spielernachrichten nie erreichen — alle Verdicts grün oder
ehrlich als api-only markiert. Kein Leak gefunden.

## Grenzen & Fixture-Abweichungen

* Der Audit-App-Container lief mit `--user root` (Volume-Rechte nach DB-Wipes nicht
  zurücksetzbar) — Produktionsbetriebsmodus `vtt` bleibt unberührt, Abweichung dokumentiert.
* Playwright-Harness ist Beweismittel, nicht Produkt: Wo sie stolperte (Nebel-Zielliste,
  zugestellte Fallenpfade, HP-Lesung, Disarm-Klickpfad), war der Produktzustand danach
  per Server-Wahrheit korrekt; solche Stellen heißen `api-only`/`fixture-only-gap` oder
  sind als Harness-Flake markiert — nie schöngefärbt.
* Würfe wurden nicht erzwungen (echte d20-Ergebnisse), Schadensantragung als DM-Aktion
  wie am Tisch.

## Anhang

* Skripte: `scripts/e2e_d161_{lib,a1..a8}*` · Proben `probe7…16` (Host `d161/`) ·
  Logs: `A1.log … A8.log`, `final_tests*.log` · Screens: `e2e-evidence/` ·
  Zustand: `/home/alp/d161/` (State, Packs, Persistenz-Dumps).
* Regressive: `tests/test_d161_*.py` (5 Dateien) in der Gesamtsuite;
  Kanon: `python -m pytest` → **1192 Tests, 0 Fehler, Exit 0**
  (`final_tests3.log`, 100 %-Marker im Log; die `-q`-Summenzeile unterdrückt dieses
  Image konsequent, Exit-Code + Dot-Zählung + 100 % sind der Beleg).
