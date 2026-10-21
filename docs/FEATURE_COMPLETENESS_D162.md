# Feature-Vollständigkeit D&D 5e 2024 — Abschlussbericht D162 („Operation: Keine Ausreden mehr“)

**Datum:** 2026-10-20 · **Scope:** alle 11 D162-Aufgaben (die 8 P2-Lücken des
D161-Audits `docs/PLAY_SESSION_AUDIT_D161.md` + `item_defs`-Raumkollision +
Wizard-Zauberwahl + laute DM-only-Ablehnung) · **Kernfrage:** Welche 2024-Regel-
Aktionen sind weiterhin nicht über die UI möglich?

## Ergebnis in einem Satz

Alle acht P2-Lücken sind über echte UI-Pfade geschlossen und mit echten
Browserläufen belegt (`scripts/e2e_d162.mjs`, grüner Gesamtdurchlauf rc=0,
Belege `e2e-evidence/d161-0*-V*.png`); die Kernfrage beantwortet: **keine im Audit
gefundene Spieleraktion ist noch UI-unfähig** — offengebliebene Stumheiten sind
ausschließlich die gewollten Leak-Schutz-Stummen (siehe „Bewusst offen“).

## Lücke für Lücke (Audit-ID → Befund)

| Lücke | Implementierung | Nachweis | Verdict |
|---|---|---|---|
| P2-8 Treppenrückweg zur Primärebene | Editor-Etagenwahl `#obj-tfl` am Stair-Objekt (`fillStairFloors`), `handle_map_edit` validiert Ziel-Etage | `test_d162_stair_primary.py`; E2E V3: Ebenen `crypt`/`Ground`/`tower` real im Dropdown; Treppen crypt(5,5)→tower(10,8) und tower(10,8)→ground(3,3) gesetzt, Begehung im Browser | UI-OK |
| P2-6 Species-Boni ohne UI | `#prep-species-card` im Build-Blatt, idempotenter Grant, Artboden-Schutz (`protect_species_floor`) | `test_d162_species_ui.py`; E2E V2: dex 15→16 über Kartenklick, zweiter Klick laut verweigert, `PUT dex=3` clamped auf 16 | UI-OK |
| P2-7 Sturzschaden fehlt | `app/room/fall.py`: 1d6 Wuchtschaden je volle 10 ft (Cap 20d6), <10 ft = 0, Landung prone; Hooks walk/cond/dice + DM-Button `#npc-drop` (`token_drop`) | `test_d162_fall.py` (9, inkl. statischer UI-Pins); E2E V7: Fly-Modus übers Tower-Volumen → 🪂-Drop → Landung ground mit Fallschaden (hp 60→57 bzw. 57→55) | UI-OK |
| P2-4 Kein Spieler-Schlossknacken | `lock_dc` (5–25, Default 15) im Tür-Editor, Shift-Klick → `action:"pick"`, `_pick_lock` = Dex-Check über `opposed.check_roll`; ohne Diebeswerkzeug nachteilig ohne Prof, mit Werkzeug + Background-`tool_prof` Prof | `test_d162_lockpick.py` (9); E2E V5: DC-5-Tür nach Shift-Klicks im Rahmen entsperrt, Flüstern „Dex 19+3 = 22 vs DC 5 (thieves' tools) → the lock clicks open!“ | UI-OK |
| P2-1 DM-Fallenkanal ohne Oberfläche | `#trappanel` (`tdm-*`): search/disarm/trigger/remove, live auf der Karte | `test_d162_trap_control.py` (8); E2E V4: Panel-Entfernen 1→0, Trigger live | UI-OK |
| P2-2 Fallen-/Loot-Pinsel ohne Löschen | Lösch-Pinsel `traprm`/`lootrm` + `handle_map_remove` | `test_d162_trap_control.py` (Server) + statischer UI-Pin; E2E V4: `traprm`-Brush entfernt Falle per Kartenklick | UI-OK |
| P2-5 Angriffsschaden würfeln ohne Anwendung | `app/room/pending.py`: Item-Waffen-Treffer erzeugen Bestätigungszeile im Game Log; Apply = atomarer HP-Claim (Doppelklick-safe), Decline verwirft, Sweep räumt ab | `test_d162_damage_confirm.py` (7); E2E V6: DM-Apply-Klick senkt Wight-HP real (60→53), WS-Frame `damage_confirm` getrackt | UI-OK |
| P2-3 Pack-apply überschreibt nicht | `content.apply_rows(mode="upsert")` = wie replace, aber Report mit `updated`-Liste; API/UI-Modus `upsert` | `test_d162_upsert.py` (4); E2E V9: `gem_ring` 99→150 gp neu bewertet + `coin_sovereign` neu, Report `↑1 updated`, Re-Run = 0 Änderungen (idempotent), Export bestätigt Zeilenwahrheit | UI-OK |
| (Audit Ph4/Anhang) `item_defs` raumkollidieren | Composite-PK `(room_id,id)`, `migrate_item_defs` mit Backup + Fail-Closed, Schreibpfade raumbezogen | `test_d162_itemdefs.py` (4); G9-Pins in `test_d100_integration.py` dokumentiert geflippt | API-OK (bewusst ohne UI-Fläche) |
| (Audit Ph3) Wizard prepared/cantrip-Auswahl | prepared/cantrip-Pools im Build, Überzahl laut fehlerhaft | `test_d162_spell_choice.py`; E2E V1: Pools 3 Cantrips/4 Spells im UI-Pick, Bau bis Stufe 2 | UI-OK |
| (Audit Ph5) DM-only-Aktionen antworten stumm | 14 stumme Pfade antworten jetzt `error: "DM only"` (Toast) | `test_d162_error_feedback.py` (17); E2E V8: Spieler-`init_start` → sichtbarer „DM only“-Toast | UI-OK |

## Kernfrage beantwortet: bleibt 2024er-API/UI-unfähig?

Nein — keine der im Audit belegten Aktionen. Bewusst offen bleiben, jeweils
dokumentiert und **nicht** als Lücke behandelt:

1. **Leak-Schutz-Stummen (Sicherheit, unverändert):** Verweigerungen, die einem
   Spieler etwas über DM-Wahrheit verraten würden (geheime Türen, Fallen auf
   fremder Ebene, Fremd-/Adjanz-Besitzverweigerungen), bleiben stumm — Lautheit
   wäre hier ein Leak. `test_d162_error_feedback.py` pinnt beide Klassen
   getrennt (14 loud, Stumme unverändert).
2. **Verbesserung, nicht Vollständigkeit:** Passive Wahrnehmung als dauerhaft
   sichtbarer Wert, Führungen für Improvisierte Aktionen und weitere Werkzeug-Kits
   (im Pack existiert nur Diebeswerkzeug) sind Oberflächen-Feinschliff ohne
   Audit-Fund — kein Tisch bleibt daran hängen, es wäre nur bequemer.
3. **Migrationen ohne UI-Fläche:** `item_defs`-PK-Wanderung ist Serverhygiene;
   eine „Migration per UI“ wäre ein Risiko, kein Feature.

## Bewusste Regelentscheidungen (Kanone in DECISIONS.md, Abschnitt D162)

- Sturz: 1d6 pro volle 10 ft, Cap 20d6, unter 10 ft nichts, prone nur bei
  Nicht-Landen-Können; Schaden ausschließlich über `health.damage`.
- Lockpicking: Dex-Check `opposed.check_roll`; Diebeswerkzeug + `tool_prof` →
  Prof, ohne Werkzeug → disadvantage statt Prof; `lock_dc` klemmt auf 5–25.
- Damage-Confirm: nur Item-Waffen-Treffer mit Ziel erzeugen Pending; Apply ist
  atomar (Zweiter Klick findet nichts), Fehler gibt Claim zurück.
- Upsert: identische Zeilen = keine Änderung und kein `updated`-Eintrag.

## Dokumentierte Test-Umkehrungen (Pins, keine Abschwächung)

- `tests/test_d100_integration.py` G9-Pins: `item_defs`-PK ist jetzt
  `(room_id,id)` — Flip mit Grund Kommentar.
- `tests/test_d129_exhaustion.py`: stumme Exhaustion-DM-Ablehnung → lautes
  „DM only“ (gewollter Verhaltenwechsel, Alt-Pass bleibt).

## Kanon + Belege

- Kanon: 1192 → **1259 passed, 0 skipped, 0 failed (rc=0)** (147 Dateien;
  zweifach bestätigt: Fortschritts-Marks `/tmp/opencode/d162_full4.log` +
  Collect `d162_co.log`). Neue Dateien: `test_d162_stair_primary.py`,
  `test_d162_species_ui.py`, `test_d162_fall.py` (9), `test_d162_lockpick.py`
  (9), `test_d162_trap_control.py` (8), `test_d162_damage_confirm.py` (7),
  `test_d162_upsert.py` (4), `test_d162_itemdefs.py` (4),
  `test_d162_spell_choice.py`, `test_d162_error_feedback.py` (17),
  `test_d162_erase.py`.
- E2E: `scripts/e2e_d162.mjs` gegen Wegwerf-Container `d162-app`
  (127.0.0.1:8022), grüner Durchlauf „ALL SCENARIOS PASSED“ (rc=0,
  `/tmp/opencode/D162E2E44.log`); Live-Höhen je Szenario in `D162E2E4/7/11/32/
  39/41/43.log`; Screenshots `e2e-evidence/d161-0*-V*.png`.
- Teardown-Hinweis: `d162-app`/Volume `d162-data` bleiben bis auf Weiteres für
  Reproduktion stehen; State `/home/alp/d161/d162_state.json`.
