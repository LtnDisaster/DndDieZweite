# Spielbarkeits-Audit 2026-10-18 (NACHTSCHICHT 3.0)

## 1. Ergebnis in Kürze

- **91 WS-Handler + 59 REST-Endpunkte** vollständig als Feature→UI→Test-Matrix
  abgelaufen; tote DOM-IDs und tote JS→REST-Pfade: **keine**.
- **4 echte Defizite gefunden und behoben** (D150: zwei Features ohne UI;
  D152: unendliche Heiltränder; D153: vier Stale-UI-Pfade), eine
  Test-Schulden-Gruppe getilgt (D151, 4 Ops), Hilfe neu gebaut (D149).
- **E2E-Suite A–G gegen die Live-Instanz: alle grün**
  (`scripts/e2e_playability_suite.py` + die zwei vorhandenen A/B-Skripte).
- **Kanon: 1093 passed / 0 failed** (vorher 1065; +28 … davon +9 neue Pins
  D149/D150/D152/D153, Rest unverändert grün). `node --check` über alle
  10 JS-Module sauber.

## 2. Methode

Drei Schichten, jede einzeln blind für eigene Fehler — erst die Überlagerung
ergab das Bild:

1. **Statisch:** jeder `type:`-Handler in `app/room/dispatch.py` gegen alle
   `wsSend({type})`-Sendeorte und `msg.type`-Variablen-Zuweisungen (fing
    falsche Lücken bei secret_event/audio_*/grapple — s. Anhang).
2. **API-Tests:** pytest-Kanon (1065→1093), darunter neue Pins
   `test_d149_help_system.py`, `test_d150_stabilize_give_ui.py`,
   `test_d151_ops_coverage.py`, `test_d152_uncounted_vial_consumes.py`,
   `test_d153_ui_refresh_closure.py`.
3. **Echt-Browser-E2E (Playwright/Chromium):** Szenarien A–G, DM + zwei
   Spieler parallel. Genau hier starben die Features, die oben durchfielen.

## 3. Hilfe (D149)

`app/static/js/65_help.js`: 42 Einträge, 8 Kategorien, Volltextsuche,
Kategorie-Tabs, Kontextchip (aktiver Side-Tab → passende Kategorie). `?`
öffnet, `Esc` schließt, zentral über `setHelp()`/`helpVisible()`. Jeder
Eintrag beschreibt nur Griffe, deren Bedienbarkeit Audit oder E2E belegt
haben (Pinned in test_d149). Der statische index.html-Block ist entfernt.

## 4. UI-Geschlossenheit (D150)

- `stabilize` (D136) hatte **keinen** Sendeort → 🩺-Button im Death-Block
  (`#dstab`), Server prüft Adjazenz/Aktion/Turn/Dame-Limit weiter selbst.
- `inv_transfer` (D137) hatte **keinen** Sendeort → 🫱-Button auf der eigenen
  Inventarzeile mit Picker (`#give-to`/`#give-qty`/`#give-go`).
- Bewusst **keine** erfundene UI: `pickpocket_take`, `forced_move`,
  `knock_prone`, `class_levels` bleiben DM-Direkt-/Intern-Werkzeuge
  (Begründung je Handler im Anhang). Ein Button, der einen internen Op
  verkleidet, wäre ärger als keine UI.

## 5. Test-Schulden (D151)

`turn_mark`, `death_clear`, `quest_fail`, `quest_obj_add`: UI vorhanden,
pytest-Nachweis 0 → `test_d151_ops_coverage.py` (DM- und Besitzerpfade,
Toggle zurück, „Only the DM manages quests").

## 6. Server-Regel-Fund (D152)

`handle_use_item`: Verbrauch (D146) griff nur bei `charges>0`. Der
Content-Pack-Trank (`Healing Draught`, charges=-1) lief durch den
Unlimited-Zweig: **Heilung ohne Verbrauch — unendliche Tränke.** Die
D146-Tests konnten das nicht fangen, sie nutzten `props.charges=1`.
Fix: potion/scroll mit `charges<0` ⇒ exakt eine Dosis (Normalisierung auf
1, danach der getestete D146-Pfad). Stäbe ohne Zähler bleiben unbegrenzt
(gegenregetestet). E2E D war erst danach ehrlich: „Use" konsumierte sichtbar.

## 7. Stale-UI-Funde (D153) — die E2E-Suite allein fand sie

1. **Offenes Sheet wurde nie nachgemalt** (`refreshRoom`): Grants, HP-Änderungen
   und Tod tauchten erst nach erneutem Klick auf. Guard: nur wenn offen,
   kein NPC-Editor aktiv, kein NPC-Token.
2. **Private-Card ohne Death-Block:** D93 zeigte Bundesgenossen nur die
   Mini-Karte — dort fehlte der gesamte Death-Bereich, der neue
   Stabilize-Button war für Spieler faktisch unerreichbar (nur DM traf je
   die Voll-Variante). Jetzt: `deathHtml` + `wireDeath` auf der Mini-Karte;
   `tok.death` ist öffentlicher Table-State, Inventar bleibt privat.
3. **floor-POST ohne Eigen-Refresh:** `floors_changed` geht per ws nur an
   die ANDER Clients — das eigene Sheet zeigte nach „＋" veraltete Optionen.
4. **Presence-Roster wuchs nur:** `case "presence"` tat immer `.add()`;
   Offline wurde nur im Spielprotokoll erwähnt, `#online` blieb grün.
   Jetzt `online ? add : delete`.

Suite: `scripts/e2e_playability_suite.py` (C: Sterben/Todessicherung/DM-Clear/
Stabilize/Initiative/Slot-Chip/Angriff · D: Grant/Use/give · E: Floor
anlegen + Ebene wechseln · F: geteileter Chat/Reload-Persistenz/Presence ·
G: Hilfe). Ausführen gegen jede Live-Instanz via `VTT_E2E_BASE_URL`
(s. Abschnitt 9).

## 8. Regel-Notiz: Massive Damage (health.py:111)

`damage >= max_hp` ⇒ sofort tot — auch bei vollem Leben und exakt
`max_hp` Schaden. SRD-Text lässt bei genau 0 Restschaden sterben **nicht**
instant sterben (nur Rest *über* max). Bewusst nicht geändert
(Kampf-Regel = Hausregen-Terrain, 16-h-Gate unentschieden); D152-fix
berührt das nicht. Fürs E2E unschädlich gemacht (Dropping in zwei
Schritten). **Entscheidung empfohlen**, nicht Autopilot.

## 9. E2E-Infrastruktur-Rezept (bewährt, wiederverwendbar)

```
docker compose build app
docker run -d --name ns3-app --user 0:0 -e VTT_DATA_DIR=/data \
  -v ns3-data:/data -p 127.0.0.1:8010:8000 dnd-vtt:latest
# Runner im Playwright-Image, Repo read-only gemountet, Evidence nach /evid
```

- **App + Volume vor jedem Suite-Lauf neu** — `/api/register` ist pro IP auf
  10/3600 s limitiert (`app/rooms.py:257`), Login 10/60 s.
- Image-Änderungen brauchen **`docker compose build app`** — die Seite kommt
  aus dem COPY-Layer, nicht vom Mount (ein ganzyacher Debug-Zyklus ging auf
  ein Stale-Image).
- App-Service des normalen `compose.yaml` **nicht** anfassen (Port 8000 +
  ./data-Bind + Rootless-uid — Alt-Unfall); Suite läuft auf 8010.

## 10. Evidence

- Kanon final: rc=0, **1093** Tests, 0 FAILED/ERROR
  (`/tmp/opencode/ns3_canon_final.log`).
- E2E final: A/B `PASS` (`ns3_ab_final.log`), C–G `ALL SCENARIOS PASS`
  (`ns3_e2e_final.log`, rc=0); Screenshots in `~/opencode-e2e/`.
- Logs aller Iterationen: `/tmp/opencode/ns3_e2e*.log`, Notizen
  `/tmp/opencode/ns3_notes.md`.

## 11. Manuelle Browser-Liste (priorisiert, 30–60 min)

Grundlage bleibt `MANUAL_BROWSER_CHECKLIST.md`; die neuen Punkte haben
Vorrang, weil genau dort E2E-Automatik an Grenzen stößt (Gefühl/Look):

1. **(5 min) Stabilize am Tisch:** zwei Browser, Patient sterben lassen,
   Helfer reicht nicht ganz (Adjazenz-Grenzfall diagonal + Tür zu) —
   Fehlermeldung lesen, nicht nur das Toast.
2. **(5 min) give-Picker mit vollem Ziel-Rucksack:** qty-Grenzen, gemischte
   Stapel, `🫱 give` an Tab-gewechseltem Empfänger-Fenster.
3. **(5 min) Trank-Verbrauch am Live-Monster-Tag:** Healing Draught ×3 →
   dreimal Use → Zeile weg, Chronik-Stimmen („(depleted)"/„(consumed)") plausibel?
4. **(10 min) Tod-Rundgang:** DM `#dclear` an Leiche, wieder droppen,
   Rettungswürfe bis stable; Death-Save-Boxen zählen sichtbar mit (s:1..3).
5. **(5 min) Floor-Panel am echten Fenster:** „＋" während das Sheet eines
   Tokens offen ist — Liste sofort frisch (D153-Fix), Blick auf Ground/
   crypt-Kacheln im Map-Footer.
6. **(5 min) Anwesenheit:** dritten Rechner/Tunnel beitreten und schließen —
   #online-Punkt verschwindet binnen Sekunden (D153-Fix), Chronik notiert beides.
7. **(10 min) Hilfe-Gefühl:** `?` mitten im Kampf-Tab → Kategorie combat?
   Suche „stabilize", „grapple", „20”; mobile Breite (Hilfe-Overlay lesbar?).
8. **(5 min) Slot-Chip-Feeling:** eigener Zug vs. NPC-Zug — disabled-Chips
   erklären sich über title-Tooltip, End-Turn-Button-Position ok?
9. **(5 min) Reload mitten im Zug (p1):** Reload im Kampf → neu reinsetzen,
   Initiativ-Reihenfolge + Slot-States korrekt übernommen?

## 12. Offene Punkte / Risiken

- **Massive-Damage-Exactness** (Abschnitt 8) — Regelentscheidung offen.
- **Hilfe-Übersetzung:** Hilfe ist englisch, Doku deutsch (bewusst, wie UI).
- **E2E gegen 8010:** Suite braucht freies Volume+Port; CI-Anbindung ist
  möglich (Playwright-Image), aber nicht eingerichtet.
- **E2E-Hilfskonto-Rest:** App/Volume der Night-Shift-Läufe liegen unter
  `/tmp` bzw. eigenem Volume; Teardown nach diesem Lauf erledigt.
- **16-h-Gate / A6-Hausregel:** weiterhin unentschieden, nichts angefasst.

---

## Anhang — Audit-Matrix (Entscheidungsgruppen)

91 WS-Handler, 59 REST-Pfade. Vollständig geprüft; hier die Gruppen:

| Gruppe | Beispiele | Befund |
|---|---|---|
| UI + Test ok | move, dice, chat, quest_*, attune, identify, recharge, fog, doors, light, audio_*, … | unverändert |
| False-Positive (variable `msg.type`) | secret_event, audio_add/stop, grapple, shove, pickpocket | verdrahtet über Variablen (60_main.js:63/105/110, 30_room.js:1531–1534) — Audit-Regel: Sendeort-Suche muss Variablenzuweisungen mitziehen |
| Lücke UI (Phase 3 → D150) | stabilize, inv_transfer | Button + Picker gebaut, E2E D/C grün |
| Bewusst DM-direct/intern | pickpocket_take, forced_move, knock_prone, class_levels | keine UI erfunden; Doku in DECISIONS D150 |
| Test-Schulden | turn_mark, death_clear, quest_fail, quest_obj_add | D151 |
| Server-Bug | use_item (charges=-1) | D152 |
| Stale-UI | refreshRoom-Sheet, Private-Card-Death, fl-add-Eigenrefresh, presence-shrink | D153 + E2E-Suite |
| REST↔UI | alle fetch-Aufrufe gegen Router-Routen (assets.py mitgezählt) | 0 tote Pfade, 0 tote DOM-IDs |
