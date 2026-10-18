# Regressions- & Edge-Case-Audit 2026-10-18 (NACHTSCHICHT 4.0)

Ausgangspunkt: Stand D153 (1093 Tests, E2E A–G grün). Auftrag: echte,
bisher unentdeckte Fehler finden, bevor der Benutzer manuell testet —
ohne neue Features.

## 1. Gefundene Fehler und reproduzierbare Ursachen

### 1.1 Massive Damage tötete zu früh (D154 — echter Bug, korrigiert)
- **Ort:** `app/room/health.py` (Zweig `hp <= 0`).
- **Ursache:** `if damage >= max_hp: dead` verglich den ROHEN post-resistance
  Schaden mit dem HP-Maximum. Folge: voller 20/20-Held + exakt 20 Schaden
  (Rest 0) ⇒ sofort tot; Temp-HP-Absorption zählte ebenfalls in den
  Tötungsvergleich. 2024SRD: tödlich ist der **Restschaden nach dem Fall
  auf 0** (≥ max_hp).
- **Reproduzierbar:** 20/20, −20 ⇒ `dead:true` (alt) / `dead:false` (neu).
  Alte Testpinne (`test_integration.py::test_massive_damage_on_drop_blow_kills`)
  hatte den Fehler als Verhalten festgeschrieben ⇒ auf die korrekte Grenze
  berichtigt (−20 ⇒ dying, −40 ⇒ dead), Intention des Tests erhalten.
- **Fix:** `prev>0: dead iff remaining-prev >= max_hp`;
  `prev<=0: damage >= max_hp ⇒ dead` (bestehende 0-HP-Regel unverändert,
  Fail/crit-Fail-Logik bleiben).

### 1.2 Hilfe-vs-Realität ohne Guard (D156 — Lücke geschlossen, kein toter
Button gefunden)
Alle 53 `<b>`-Labels der In-App-Hilfe existieren tatsächlich (8 davon sind
zitierte Server-Absagen, vom Server-Code gedeckt). Neu: permanenter
Realitäts-Gate `test_d156_help_ui_truth.py` — ein umbenannter Button ohne
Hilfe-Pflege ist ab jetzt rot statt still.

### 1.3 Reload-Kamera (UI-Erkenntnis, Verhalten bewusst gelassen)
Nach Reload steht die DM-Kamera nicht auf den Tokens; pixelgenaue Klicks
des E2E gingen ins Leere. Kein Datenfehler (User pannt/zoomt selbst);
G2 selektiert deshalb synthetisch. Beobachtet, dokumentiert, nicht
„repariert“ — Kamera-Sprung-on-reload wäre eine Geschmacksentscheidung.

### 1.4 Kurze Rast richtet Sterbende auf (bestehendes Design — jetzt sichtbar)
`short_rest` mit Hit Dice an einem Sterbenden: heilt, setzt `death=NULL`.
2014-RAW verlangte Bewusstsein fürs HD-Verbrauchen. Das ist seit D-Tagen
bestehendes Design (DECISIONS „owner-or-DM, hit-dice based“) UND durch einen
Bestandstest gepinnt. Es zu kippen = neue Hausregel ⇒ **nicht** geändert;
als Abweichungspunkt im Manuell-Katalog (Punkt 3) und als sichtbar
haltender Pin-Test (`test_d155…::test_dying_short_rest_revive_is_pinned_current_design`)
hinterlegt.

## 2. Unternommene Korrekturen

| Datei | Änderung |
|---|---|
| `app/room/health.py` | Restschaden-Regel (D154, s.o.) |
| `tests/test_integration.py` | Massive-Test auf korrekte Grenze gesetzt (+assert dying bei −20) |
| `scripts/e2e_playability_suite.py` | Szenario **G2** (DM-Reload → DM/Game/Inv-Oberflächen erreichbar) |
| `tests/test_d154_massive_damage_boundary.py` | NEU: 7 deterministische Grenzfall-Tests (20/39/40 auf 20/20, 24/25 auf 5/20, Temp-HP, Schaden auf 0 HP) |
| `tests/test_d155_edge_probes.py` | NEU: 12 Sonden (s. 3.) |
| `tests/test_d156_help_ui_truth.py` | NEU: 3 Gates (Hilfe-Label-Wahrheit, Overlay-Homes, Reload-Handles) |

## 3. Edge-Case-Sonden — Ergebnis (alle grün, kein neuer Bug)

1. Voll-HP-Trank verbrennt trotzdem die Dosis (D152-Invariante).
2. Ladungsloser **Scroll** wird verbraucht (D152 → scroll-Pfad).
3. Heilung während „dying“ beendet den Todeszustand (Engine-Invariante,
   Deckel gegen stillen Regression).
4. `turn_mark` ohne Kampf ⇒ „Slots can only be marked on the active turn“.
5. **Gleiche Zelle, anderes Stockwerk ⇒ nicht adjacent** für Stabilize
   (D114-Regel auf dem D136-Pfad, mit positiver Kontrolle).
6. Transfer an Char einer fremden Room ⇒ „Who is that?“ + Quelle bleibt
   unangetastet.
7. **Sender trennt sofort nach Send die WS-Verbindung** ⇒ Transfer genau
   einmal (schreibtransaktion ist serverseitig).
8. Doppel-Send eines Casts (gleicher op_id) ⇒ genau **ein** Slot.
9. Cast ohne Slot ⇒ Refusal, Slots unverändert (2 von 2, nicht 3).
10. `clean_items` mit giftigen Werten (qty=-5, weight="abc", charges=99999,
    heal_dice="not-a-dice") ⇒ clamped, kein Crash, kein Phantom-Healer.
11. Spieler-`npc_attack` ⇒ stilles Authz-Refusal (kein Würfel, kein Leak);
    DM-Pfad wirft weiter.
12. (Pin s. 1.4) Kurze Rast an Sterbendem = dokumentiertes Current-Design.

Zusätzlich code-seitig verifiziert (ohne neue Tests, bestehende decken):
Cast-Refusal-before-slot (D137 Cover), Transfer-Transaktion + replay
(D93/D106), Konzentration pro Damage-Event (D113), D145-Grants
exactly-once, Cross-Floor-Range (`_vertical_range_distance`, D114),
Attune-Cap, Rollenbindung ist Raum-Level (kein Wechsel-Endpoint ⇒ keine
UI-Wechsel-Fläche).

## 4. Finaler Teststand

- **Kanon: rc=0, 0 FAILED / 0 ERROR.** 1093 + 22 neue Pins (d154:7,
  d155:12, d156:3) = **1115 Tests**.
- `node --check` über alle 10 JS-Module sauber (55_diorama.js ungeändert).

## 5. Browser-E2E-Ergebnisse

Isoliert auf eigener Instanz `ns4-app` (Port 127.0.0.1:8010, eigenes
Volume, Playwright-Container, Repo read-only; kein Produktiv-Container,
kein Konflikt mit OpenCode; App+Volume pro Lauf neu — Register-Ratelimit):

- Suite A–G2/G (`scripts/e2e_playability_suite.py`): **rc=0, ALL PASS**
  (`/tmp/opencode/ns4_e2e_final1.log`) — inkl. neuem G2.
- A/B (`e2e_build_wizard.py`, `e2e_creature_projection.py`) gegen
  final Image: **beide PASS** (`/tmp/opencode/ns4_e2e_final2.log`).
- Teardown: `ns4-app` + Volume entfernt, Ports 8000/8010 frei.
- **Nicht ausführbar / nicht versucht (ehrlich):** Audio-Ausgabe (kein
  Audiotreiber im Runner), Drag-Feel/Performance-Gefühl, WebAuthn-Flows,
  richtiger Multi-Monitor/Mobile-Breite, echtes Reconnect bei Netzabriss.
  Diese Punkte stehen auf der Manuell-Liste.

## 6. Verbleibende Risiken

1. **Kurze-Rast-Selbstheilung am Sterbenden** (1.4) — Regelentscheidung
   beim Operator; Pin-Test hält jeden künftigen Flip sichtbar.
2. **Kamera nach Reload** (1.3) — UX-Geschmack; manuell prüfen.
3. Stille Authz-Refusals (npc-*, attune auf falschen Chars) — Absicht
   (kein Leak), aber ohne Rückmeldung; bewusst so gelassen.
4. Hilfe-Realitätsgate prüft Labels, nicht Semantik (ein Button kann
   existieren und etwas anderes tun).
5. E2E läuft nicht in CI (Playwright-Image nicht angebunden) — manuell
   ausführbar wie in Abschnitt 5 beschrieben.

## 7. Hinweise für die manuelle Abnahme (Anschluss an MANUAL_BROWSER_CHECKLIST.md)

1. **Massive-Boundary am lebenden Tisch:** Char 10/10 DM-seitig −10 ⇒
   sterbend (nicht tot); −11 nach Tod ⇒ Fail, kein Tot; erst ≥ +(max) auf 0
   ⇒ tot. (Ersetzt den alten Nachtschicht-3-Vermerk.)
2. **G2 nachziehen:** DM-Browser mitten im Raid neu laden → Re-Enter →
   DM/Game/Inv-Tabs: alle Griffe da? (Automatisch grün; Gefühl prüfen.)
3. **Entscheidung Kurze Rast:** Sterbenden anlegen, eigener Spieler macht
   kurze Rast mit HD → auferstanden. So gewollt (engine-intern pinnt) oder
   auf „bewusstlos = keine Rast“ ziehen? Letzteres = Regelarbeit.
4. Reload mit offenem Sheet während laufendem Kampf (Initiative-Fenster,
   Slot-Chips nach Re-Enter richtig?).
5. zwei Browser + zweites Stockwerk: Stabilize von oben auf unten muss
   scheitern („next to the patient“) — unten wie oben probieren.
6. Trank ×3 im Voll-Leben trinken ⇒ Chronik zeigt Verbrauch pro Schluck,
   HP bleibt voll, letzte Dosis verschwindet sichtbar.
7. Audio/Mobil/Netzabriss (Punkt 5, nicht automatisch prüfbar).
