# Quality Gate D160 — DnDTable, vertikale 3D-Geometrie & Etagensystem

Abschluss-Prüfbericht der autonom gesteuerten Test-Kampagne **D160**. Ziel war
kein neues Feature, sondern das bestehende vertikale System aus D114/D158/D159
adversarial zu prüfen: echte Server- und Browser-Pfade, reproduzierbare Fehler
zu beheben und den Stand ehrlich einzuordnen (kein Greenwashing).

## 1. Methodik

- **Unit/Integration (Backend):** neue `tests/test_d160_*.py` + alle bestehenden
  Vertikal-/Etagen-/Sicht-Suiten gegen `dnddiezweite-test:latest` im Wegwerf-
  Container (Bind-Mount, `--init`, kein Cache).
- **Echter Browser:** Zwei gleichzeitige Chromium-Clients (DM + ein Spieler) gegen
  eine frisch aus dem aktuellen Baum gebaute Wegwerf-Instanz (`dndrf:latest`) auf
  Loopback `127.0.0.1:8013`, Harness `scripts/e2e_d160.mjs` (Node/Playwright,
  wie D159; Python-Playwright im Image praktisch unbrauchbar).
- **Sicht-Autorität:** Cross-Plane-Sicht wird über die maßgebliche Pro-Viewer-
  `GET /api/rooms/{code}/state` (`_viewer_token_view`) beurteilt — exakt der Code,
  aus dem das Browser-Rendering gespeist wird. Screenshots stammen vom echten DM-
  Client.
- Grenzen: keine Git-/Produktions-/Netzwerk-Nebenwirkungen, nur eigene Container,
  danach Teardown (Container + Volume weg, Port 8013 frei).

## 2. Testergebnisse (Kanon)

| Größe | Wert | Quelle |
|---|---|---|
| gesammelt | **1169** | `pytest --co` (Zählung `::`-Zeilen) |
| bestanden | **1169** | `pytest -q` → `RC=0`, nur `.`-Marks (1169), keine `F`/`E`/`s` |
| fehlgeschlagen / Fehler / übersprungen | **0 / 0 / 0** | Fortschrittszeichen-Zählung |
| Exit-Code | **0** | Voll-Lauf im Test-Container |

Die Zahl wurde über zwei unabhängige Wege (Fortschritts-Marks und
Collect-Zählung) identisch bestätigt. Das Test-Image gibt bei Pipe-Ausgabe keine
finale `… passed`-Zeile mehr aus; die Zahl ist deshalb aus Fortschrittszeichen +
Collect abgeleitet, nicht erfunden.

### Neue D160-Tests (32)

- `test_d160_floors.py` (3): Etagen-Löschen nur äußerste Ebene, signed-Stack und
  Level bleiben unverändert, Tokenposition **und gespeicherte Karten** verbleibender
  Etagen bleiben unverändert (Q2-Regression).
- `test_d160_geometry.py` (20): E0↔E+3 nur mit offener Säule, level-gap fail-closed,
  massive `slab` vs. offenes Volumen, Shaft-Projektion (keine 3D-Diagonale),
  wandgesperrtes Zwischenlevel, Insert-Below ohne Umnummerieren, OOB fail-closed,
  Groß-Token-ganze-Säule, Flug ≥3 Geschosse, Keller-Flug braucht Öffnung,
  blockiertes/belegtes Ziel, Höhe/Reach, Lampen öffnen keine Säule, keine
  Stale-Sicht nach Karten-Edit, ruhender Flieger wird nicht revalidiert (Doku der
  Grenze), Reload/2-Client-Konvergenz, integrierter cross-plane Flug.
- `test_d160_authority.py` (8): Move eines Fremd-Tokens verweigert, cross-floor ohne
  Flug-Geschwindigkeit verweigert, Spieler darf Etagen nicht ändern, DM auf
  unregistrierte Etage verweigert, Flug auf unregistrierte Etage verweigert,
  DM-Teleport kann nicht in eine Wand, versiegeltes-Etage-Token nie im
  Spieler-`/state`, Flieger darf nicht außerhalb seiner Runde ziehen.
- `test_d160_perf.py` (1): `maps_for` und `observable_cells` unter Last (siehe §5).

### Behobener Fehler (Bug)

**Q2 — Stillschweigendes Umnummerieren beim Löschen einer mittleren Etage.**
Bisher konnte eine mittlere Etage gelöscht werden; die darüberliegenden Ebenen
rückten positional nach und ihre **bereits gespeicherten Karten wurden den
falschen Etagen zugeordnet**. Behebung in `app/floors.py`: Entfernen nur der
äußersten Ebene je Seite erlaubt (unten→`below` von unten, oben→`above` von
oben); sonst `400` mit verständlichem Grund. UI (`30_room.js`) zeigt den
Server-`detail` per Toast statt still abzulehnen. **Fail-before/pass-after
nachgewiesen:** ohne Guard `DELETE→200` + Umnummerierung, mit Guard `DELETE→400`,
Stack/Tokenposition/Karten unverändert.

## 3. Echte Browser-Laufzeittests (Dual-Chromium, `EXIT=0`)

Alle harten Szenarien A–F bestanden, H bestanden, G bestanden. Belege in
`./e2e-evidence/e2e-d160-*.png`.

- **A** Raum anlegen → löschen (`200`) → danach unlesbar (`404`); Spieler darf
  DM-Raum nicht löschen (`403`). *Hinweis: Löschung über authentifizierte
  `fetch`, nicht über den Lobby-Button (UI-Klick-Pfad separat nicht getestet).*
- **B** signed Stack `Cellar −1 … C +3` (Reihenfolge + Level), auf Ebene `B` eine
  Wand gemalt, gespeichert, **Reload** → Wand persistiert (Plane-Get bestätigt).
- **C** Token auf `E+3` (`floor C`), DM-Badge `E+3`; **Spieler sieht es über die
  offene Säule** (maßgeblicher Pro-Viewer-`/state`, ~40 ms). Live-WS-Push beim
  Karten-Edit wurde als „noch nicht nachgeschoben“ beobachtet (siehe §6).
- **D** Säule auf `E+2` versiegelt (Platte) → Token **verschwindet** aus der
  Spieler-Sicht; wieder geöffnet → **wieder sichtbar** (jeweils Server-Gate, ms-belegt).
- **E** Anzeige-Filter (`viewfilter`) ändert nur `state.viewFilter`, verschiebt die
  **betrachtete Ebene nicht**; Kontrolle ist dem Spieler verborgen.
- **F** versiegeltes-Etage-Token ist DM-only und **nicht** im Spieler-`/state`.
- **G** `init_start` → 5 Tokens in Initiative-Reihenfolge (Runde 1).
- **H** Reload mitten im Edit lässt Server-Zustand intakt.
- **PROBE** (Diagnose): ein gleich-ebener Token im 6-Felder-Sichtbereich wird
  korrekt zugestellt (basic LOS funktioniert).

## 4. Nur statisch / per Inspektion geprüft (nicht Laufzeit-gereift)

- `boundary_open`/`column_open`/`body_planes`/`observable_cells`: Logik per
  Unit-Tests und Live-Introspektion bestätigt; **ein integrierter Diagonal-Sicht-
  Ray** über mehrere Geschosse ist bewusst **nicht** gebaut (`ray_clear_3d` bleibt
  Primitives, nicht Zustellpfad) — Shaft = Senkrechtprojektion + 2D-LOS je Ebene.
- Berechtigungs-Matrix (`authz.controls`, Server-Move/-Teleport/-Floor-Wechsel)
  nur insoweit laufzeitgeprüft, wie von A–G/F abgedeckt.

## 5. Performance (gemessen, kein Verdacht)

- `maps_for(9 planes)` ≈ **6.27 ms/Aufruf**
- `observable_cells` mit gecachten Karten, pro Token:
  1 Token **0.0208 ms**, 50 Tokens **0.1211 ms**, 200 Tokens **0.1052 ms**
- Keine persistente Sicht-Cache; Delivery rechnet pro Event — messbar, aber
  linearen Umfangs. Kein Perf-Regressionssignal.

## 6. Beobachtungen (korrektes Verhalten — dokumentiert, keine Bugs)

Diese Punkte wurden im E2E diagnostiziert und sind **beabsichtigtes Verhalten**;
sie werden festgehalten, damit ein späterer Leser sie nicht als Fehler liest:

1. **Spielervisus = fester 6-Felder-Radius in einer nicht-dunklen Karte**
   (`FOG_R = VISION_R = 6`); Darkvision wirkt nur in dunklen Karten (`mp.dark`).
   ⇒ Ein Spieler ohne eigene Token sieht nur seine eigene(n); **Kontrolle ≠
   Besitz** für die Sichtquelle (Sichtquellen sind besitzerbezogen). Harness setzt
   daher einen **besessenen** Helden und stellt ihn je Säule nah heran.
2. **Eine bearbeitete Ebene legt eine massive Platte** über ihre Zelle und deckt
   damit eine Säule. ⇒ Shaft-Sicht braucht eine **explizit offene** Zwischenzelle
   (`air`/`openv`/`void`). Harness öffnet die Säulenspalte gezielt.
3. **Cross-plane Token wird durch einen Karten-Edit sofort im maßgeblichen
   Pro-Viewer-`/state` sichtbar**, der **inkrementelle Live-WS** schickt ihn ggf.
   erst nach einem Client-Refresh nach. Das ist ein möglicher Komfort-/UX-Nachzieher
   am Live-Pfad, **kein** Sicht-/Sicherheitsfehler: das Autorisierungs-Gate
   (`_viewer_token_view`) entscheidet korrekt. → optionaler Folgepunkt.

## 7. Bewusst offen / nicht geprüft (D160 nicht verlangt)

- Integrierter 3D-Diagonal-Sicht-Ray (statt offener Säule + Pro-Ebene-LOS).
- Springen/Fallen/Sturzschaden, vertikales Klettern/Schwimmen, Höhen-Deckung.
- Nachträgliche Kartenänderung unter einem **ruhenden** fliegenden Token wird nicht
  revalidiert (ruhender Flieger bleibt stehen) — als Grenze durch einen Test
  dokumentiert, nicht behoben.
- Lobby-Lösch-Button per echtem Klick (A nutzt authentifizierte `fetch`).
- Combattanten-Reichweite/-Timing über Höhen im echten Browser (G prüft nur die
  Initiative-Reihenfolge).

## 8. Spieltest-Bereitschaft

Für einen menschlichen Browser-Spieltest ist das vertikale System **bereit**:
Etagensystem (signed/below), offene Volumen/Luft, Shaft-/Säulensicht, freier
3D-Flug, Anzeige-Filter, Reload- und Löschpfade sind real in zwei Chromium-Clients
verifiziert. Die offenen Punkte in §7 sind keine Blocker für einen ersten
Spielbetrieb, sondern dokumentierte Folgearbeiten.

## 9. Reproduktion

Voll-Suite:
```
docker run --rm --init -v "$PWD":/srv -w /srv dnddiezweite-test:latest \
  python -m pytest -q -p no:cacheprovider
```
Browser-E2E (Wegwerf-Instanz, danach Teardown):
```
docker run -d --name rf-d160 --user 0:0 -e VTT_DATA_DIR=/data \
  -v rf-d160:/data -p 127.0.0.1:8013:8000 dndrf:latest
docker run --rm --network host -v "$PWD/scripts":/work -v "$PWD/e2e-evidence":/shots \
  -e VTT_E2E_BASE_URL=http://127.0.0.1:8013 -e VTT_E2E_EVIDENCE=/shots \
  mcr.microsoft.com/playwright:v1.64.0-noble bash -lc \
  "cd /tmp && cp /work/e2e_d160.mjs . && \
   PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm i playwright@1.64.1 && node e2e_d160.mjs"
docker rm -f rf-d160; docker volume rm rf-d160
```

## 10. Fazit

1169 Tests grün (`RC=0`), ein echter Browserpfad über zwei Chromium-Clients
(A–H) grün, ein realer Datenintegritätsfehler (Q2) mit Fail-before-Test behoben,
Perf gemessen. Beobachtungen (§6) sind korrektes, jetzt dokumentiertes Verhalten.
D160 ist als Qualitäts-/Regressionstore **bestanden**.
