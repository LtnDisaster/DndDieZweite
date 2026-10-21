# Samstag-Abnahmeleitfaden (Browser, Sa 17.10.2026)

Ein kompletter Durchspiel-Durchgang in ~30 Minuten. Jede Stufe listet die
Erwartung — Häkchen erst setzen, wenn die UI es wirklich zeigt.
Kanon im Hintergrund: `tests/test_d110_e2e.py` fährt genau diese Kette
automatisiert durch; die Browserabnahme ist der Gegenbeweis, dass die echte
UI dieselben Pfade nutzt.

Vorbereitung: Server läuft (`docker compose up` bzw. die übliche Instanz),
zwei Browser-Fenster (oder normal + privat) = **P1** und **P2**, dazu der
DM-Account. Ein drittes Fenster (DM-„View-as“) ist optional, aber empfohlen.

## A — Vorbereitung (ca. 5 min)

1. DM: neuen Raum anlegen, Raumcode notieren.
2. P1/P2: registrieren + mit Code beitreten.
3. **Regelwerk einspielen:** DM → Content (📚) → ZIP der Demo-Packs
   (`app/content_pack/*.csv`) → *Import* → Vorschau → Apply.
   ☐ 8 Dateien erkannt, 0 abgelehnte Zeilen.
4. P1/P2: Prep-Screen (🎭) → je einen SC bauen:
   * Rasse wählen (z. B. Eladrin), Hintergrund (Urchin / Scholar),
     Klasse (Scout / Warden), Level 1 → Plan → Apply.
   ☐ Origin-Dialog erscheint, ASI-Wahl (+2/+1 oder +1/+1/+1) wird
     angenommen, Werte steigen sichtbar.
   ☐ Nach Apply: Bogen zeigt HP, Fertigkeitsmarken, Slot (Warden).
5. Startausrüstung (🎒-Button): ☐ Rückfrage nach Waffen-/Kit-Wahl
   (Scout: Bogen oder Schwert + Diebes-/Gambler-Kit), danach Einträge
   mit Mastery/Attunement-Flag im Inventar.

## B — Erkundung (ca. 7 min)

1. DM: Karteneditor (🖊) → Wandpinsel: kurze Mauer vor P1.
   P1: Klick auf Zielfeld dahinter → ☐ Pfad-Vorschau blockiert, Weg um die
   Ecke frei. ☐ Bewegung klappt nur auf freien Pfad.
2. DM: Tür in P1-Nähe setzen; P1: draufklicken → ☐ Tür animiert auf/zu,
   beide sehen sie offen/zu (Sichtbarkeit).
3. DM: Nebel (Fog) an, weit entfernten NPC-Token anlegen.
   ☐ P1/P2 sehen den NPC nicht (Nebel). ☐ DM sieht ihn.
   DM: View-as P1 (👁) → ☐ Geistersicht zeigt exakt das, was P1 zeigt.
4. Licht: DM dunkelt Raum ab (☾) → ☐ P1 sieht ohne Lampe nur noch Umgebung;
   DM gibt P1 Laterne (Inventar) → ☐ Lichtkegel. Dunkelsicht-Träger:
   ☐ private Sicht ohne LAMPE-Leak an Mitspieler.
5. Stockwerke: DM legt „crypt“ an (🧭) → Token runter teleportieren →
   ☐ P1-Sicht folgt dem Token ins Stockwerk; ☐ Spieler kann NICHT selbst
   springen (Button/kein Effekt für Spieler).

## C — Kampf (ca. 8 min)

1. DM: NPC (Goblin, hp 7) direkt neben P1 spawnen (⚔ oder Editor).
2. DM: Initiative (🎲→⚔) → ☐ Reihenfolge, „Dein Zug“-Highlight.
3. P1 im Zug: Angriffswaffe antippen, auf Goblin klicken.
   ☐ Würfelchat: Treffer-/Schadenszeile, AC-Referenz, Mastery-Auswahl
   (wenn gewählt) mit eigener Zeile (Cleave-Ziel nachwählbar?).
   ☐ Nicht-Im-Zug kann nicht angreifen (Fehler im Chat).
4. P2: Topple-Mastery (Versatile Sword) → ☐ gerettete Rettung = „resists“,
   missglückte = Prone-Symbol am Token.
5. Bedingungen: ☐ Prone-Icon sichtbar, aufstehen kostet Bewegung;
   ☐ Condition-Runden ticken am Rundenende weg.
6. Kritisch: DM setzt P1 auf 0 HP → ☐ Death-Save-Dialog, Retten möglich.

## D — Loot (ca. 3 min)

1. DM: Goblin auf 0 HP → ☐ Toten-Markierung, Loot-Icon.
2. P1 danebenstellen → ☐ Loot-Fenster öffnet sich NICHT von weitem,
   nebenan: Inhalt + Geld des NPCs.
3. ☐ Dinge nehmen → wandern ins Inventar, Menge am NPC sinkt.
4. ☐ Heilen am toten NPC auf >0 HP sperrt Loot wieder.
5. Doppelklick auf „Take“: ☐ keine Duplikate.

## E — Flüche & Geheimnisse (ca. 3 min)

1. DM: Inventar eines Gegenstands → Fluch-Dialog (☠): Name + Text +
   Whisper-Nachricht setzen. ☐ Spieler sieht den Fluchnamen NICHT.
2. DM: *reveal* → ☐ Whisper kommt nur beim Besitzer an, andere Fenster sehen
   nichts — auf dem Bogen stehen Name+Beschreibung, nie der Geheimtext.
3. DM: *whisper* → ☐ gespeicherter Text kommt nur beim Besitzer an, der
   Enthüllungs-Status bleibt unverändert (D110-Fix: Whisper entüllt nicht
   mehr heimlich zurück).
4. ☐ History: nach Reload (F5) sieht der unbeteiligte Spieler den
   Fluch-Whisper nicht (Chat-Historie filtert serverseitig).

## F — Reload & Persistenz (ca. 3 min)

1. F5 auf allen Fenstern → ☐ alles da: Positionen, Inventar, Fluch-Status,
   Kampfstand, Nebel, Stockwerke, Chat-Historie.
2. DM: View-as erneut → ☐ identische Ausschnitte.
3. P1: doppelten Klick auf Apply/Origin/Ausrüsten → ☐ keine doppelten
   Grants, keine Stat-Drift.
4. ☐ Leeres Fenster (DM raus + rein): Raum weiterhin heil.

## Abnahme-Protokoll (Summen)

* ☐ A–F komplett ohne Blocker bestanden
* ☐ Auffälligkeiten notiert (Screenshots/Fehlermeldungen im Chat)
* ☐ Server-Log sauber (keine Tracebacks)
* ☐ Kanon-Lauf: `docker compose run --build --rm test` — Ergebnis: ______
* ☐ Danach Entscheidung in die Restarbeit: Lückenliste
  `docs/FEATURE_COMPLETE_GAPS.md` priorisieren (S40ff.).

Wenn eine Zeile scheitert: nicht im Browser „reparieren“ — hier ankreuzen
und melden; der zugehörige Automatisierungsfall in
`tests/test_d110_e2e.py` reproduziert sie.
