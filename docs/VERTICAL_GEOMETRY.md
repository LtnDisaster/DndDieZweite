# D114 / Sprint 43 — vertikale Token-Geometrie und Öffnungen

**Status Backend Phasen 0–6: umgesetzt.**
**Status UI/Editor Phase 7 und Live-Integration Phase 8: umgesetzt.**
**Verbleibende Einschränkungen: Abschnitt 9.**

## 1. Ziel

Token sind keine flachen Marker mehr, sondern vertikale Volumina. Ebenen sind
nicht länger vollständig getrennte Welten, sondern können durch Öffnungen zu
einem Stapel verbunden werden. Dabei entscheiden drei Fragen getrennt:

1. Wo hat ein Tokenkörper physisch Platz?
2. Wo kann man ihn sehen?
3. Wo kann man ihn physisch erreichen?

Diese Fragen werden bewusst nicht mit einem einzigen `floor`-Vergleich beantwortet.

## 1A. D159 — offene Volumen als Standard, signed Levels, massive Platten

D159 präzisiert die Defaults, ohne die openv-Geometrie von oben anzufassen.

- **Terrain `air`(6):** neues, registriertes Terrain. Es ist NICHT begehbar
  (`walkable=False`), blockiert weder Bewegung noch Sicht
  (`blocks_movement=False`, `blocks_vision=False`), ist `body_open`/offenes
  Volumen, aber keine Platte (`slab=False`). Es unterscheidet sich von `void`(5)
  (Loch/Abgrund) dadurch, dass Luft frei durchflogen werden kann.
- **Default je Ebene:** die Primary (E0) bleibt Standard-Boden. Eine nie
  bearbeitete, nicht-Primary-Ebene liefert `net.get_map()` als
  `blank_map(base, AIR)` — also durchgehend Luft, NICHT mehr eine unsichtbare
  Kopie der Primary. Bereits gespeicherte Zellen bleiben byte-identisch;
  D159 interpretiert nichts um.
- **Massive Platte (`slab`):** eine gelegte Fläche (walkbar oder wall) ist eine
  Platte und deckelt ihre Säule. Die gemeinsame Grenze zweier benachbarter
  Level ist offen, wenn unten `openv=1` steht ODER die obere Zelle keine Platte
  ist (also `air`/`void`/`barrier`):
  `boundary_open(lower,upper,cell) = openv(lower,cell) OR NOT slab(terrain(upper,cell))`.
  `column_open`, `vertical_path_clear`, `body_planes`, `cross_plane_sight`
  arbeiten über signierte, benachbarte Level und schlagen bei einer Lücke ohne
  registrierte Ebene fail-closed fehl.
- **Signed Levels:** `floors.level_map` liefert vorzeichenbehaftete Level
  (Primary 0, darüber positiv, darunter negativ). Ein Keller ist eine echte
  Etage `below` (E−1, E−2 …). Speicher abwärtskompatibel: flache Legacy-Liste =
  alles über Primary; erst der erste Below-Floor schreibt
  `{"below":[…],"above":[…]}`. `floors.order` liefert den Stapel bottom→top
  inklusive Primary an ihrer true-Position.
- **Freie 3D-Flugbewegung:** es gibt weiterhin GENAU EINE Engine
  (`path.find_path_3d` + `_move3d` + `vertical3d.vertical_path_clear`). Ein
  mehrgeschossiger Flug ist die Kette benachbarter offener Grenzen; diagonaler
  Flug die Komposition aus Horizontal- und Vertikalschritten.
  Kollision/Budget/Kreaturengröße/Berechtigung bleiben serverseitig autoritativ.
- **Frontend (rein darstellend):** `state.floor_levels`, `floorBadge`
  (`E0`/`E+1`/`E−1`), Etagen-Rail und -Panel mit signierten Tags, Below-Add,
  Air-Pinsel, sowie der Anzeige-Filter „All visible“ / „This floor only“
  (`onPlane`). Cross-Plane-Token tragen ein Floor-Badge mit Delta. Der Filter
  verändert niemals Sicht, Zustellung oder Position — er ist rein visuell.

## 2. Tokenkörper

Ein Token trägt:

- `height_ft`: vertikale Ausdehnung des Körpers.
- `elevation_ft`: Unterkante über der Standfläche.
- `floor`: Home-Ebene des Tokens.

Beide Werte sind optional bzw. additive Migrationen. `height_ft = NULL` nutzt
einen dokumentierten Größenkategorie-Default:

| Größe | Default-Höhe |
|---|---:|
| Tiny | 5 ft |
| Small | 5 ft |
| Medium | 5 ft |
| Large | 10 ft |
| Huge | 15 ft |
| Gargantuan | 20 ft |

Das sind Defaults, keine maximalen Werte. Ein Drache kann mit `30 ft` oder mehr
authorisiert werden, solange er im technischen Validationsband `0..200 ft` bleibt.
Negative Elevation wird auf `0` gekürzt.

`app/vertical.py` bleibt die einzige Höhen-Skala:

- eine `elev`-Einheit = 10 ft,
- eine deklarierte Ebenenstufe = 10 ft.

## 3. `openv`

Jede Ebenenkarte enthält ein `openv`-Array gleicher Länge wie `cells`.

```text
openv[zelle] = 1 → Öffnung in der Decke über dieser Zelle
openv[zelle] = 0 → feste Decke
```

Die Öffnung verbindet die Karte mit der um genau einen Level höher deklarierten
Ebene. Die Bits gehören immer zur unteren Ebene.

Default:

- fehlend → alle Zellen `0`,
- falsche Länge → alle Zellen `0`,
- ungültige Werte → alle Zellen `0`.

Damit bleibt eine alte Karte ohne `openv` vollständig fail-closed.

Spieler sehen unerforschte Zellen nur als `openv=0`; DM sehen die Wahrheit.

## 4. Zwei verschiedene Begriffe

### `body_planes`

Die Ebenen, in denen der Körper physisch vorhanden ist.

Eine höhere Ebene kommt nur hinzu, wenn:

1. die Körperhöhe sie erreicht,
2. jede zwischenliegende Decke an allen Footprint-Zellen offen ist,
3. alle Footprint-Zellen auf der Zielebene offenes Volumen sind — `void` ist
   freie Luft, `wall` und `barrier` blockieren den Körper.

Ein 2×2-Körper braucht also eine vollständige 2×2-Öffnung. Ein einzelnes Loch
reicht nicht.

### `observable_cells`

Die Zellen, an denen ein Token gesehen werden kann:

- gleiche Ebene oder Körperpräsenz → volles Footprint,
- sonst nur Footprint-Zellen mit offener senkrechter Verbindung zur Home-Ebene.

Ein Schacht erlaubt also Blick, aber nicht Körperpräsenz.

## 5. Systeme nach D114

| System | Entscheidung |
|---|---|
| Fog/Sichtquellen | Körperpräsenz |
| Token-Delivery | Körperpräsenz + normale LOS |
| `/state` | Körperpräsenz + normale LOS |
| Zielerfassung | `observable_cells` + LOS |
| Angriffreichweite | gemeinsame Körper-Ebene oder Schacht mit vertikalen Fuß |
| Grapple/Nachbarschaft | nur `body_cells` |
| Interaktion | nur `body_cells` |
| Shove/Push | kein Push über Ebenen |
| Bewegung/Flug | Phase 6: `find_path_3d` + `vertical3d.volume_final_valid` |

### Beispiel: aufragender Körper

Ein Medium-Token steht unten bei Zelle `(5,5)`, `height_ft=30` und `openv(5,5)=1`:

- unten: Körper vorhanden,
- oben: Körper vorhanden,
- oben stehende Nachbartokens können gesehen werden,
- Angriffe auf Nachbartokens oben bleiben normale 2D-Melee-Reichweite.

### Beispiel: offener Schacht

Ein Token steht oben, ein NPC hängt unten im Schacht:

- der NPC kann durch den Schacht gesehen werden,
- er ist aber nicht oben physisch,
- melee Reichweite berücksichtigt die Ebenentiefe,
- Grapple ist nicht möglich.

### Beispiel: feste Decke

Ohne `openv=1`:

- kein Blick,
- keine Körperpräsenz,
- keine Interaktion,
- keine Zielerfassung,
- altes Verhalten bleibt bestehen.

## 6. Sicherheitsgarantien

- Ein unbekannter/unregistrierter Floor-Name verbindet nichts.
- Fehlendes `openv` erzeugt keine Etage-übergreifende Sicht.
- Fog maskiert unerforschte Öffnungen.
- Ein verborgenes NPC-Token kann einem Angreifer nicht als „existiert, aber
  unangreifbar“ erscheinen; unsichtbar verhält sich weiterhin wie nicht vorhanden.
- Token delivery, Präsenzereignisse, plane-scoped Events und Snapshot nutzen
  dieselbe Körperpräsenz-Regel.
- `token_height` und Änderung von `openv` lösen sofortige Sichtneuberechnung aus.

## 7. Flug und vertikale Bewegung

Vertikale Bewegung nutzt dieselbe kanonische Bewegungsskala wie horizontale
Bewegung:

- eine 5-ft-Zelle kostet `1` Bewegungseinheit,
- ein voller deklariertener Ebenenwechsel sind `10 ft = 2` Einheiten,
- Diagonalen folgen weiterhin der bestehenden 5e-Wechselregel.

`app/movecost.py::vertical_cost()` ist die einzige Quelle dieser vertikalen
Kosten. `app/path.py::find_path_3d()` sucht über Zustände `(floor, origin)` und
nutzt für horizontale Schritte die bestehende 2D-Regel. Ein Etagenwechsel darf
nur genau eine deklarierte Levelstufe betragen und wird durch
`vertical3d.vertical_path_clear()` geprüft. Der Zielzustand wird vollständig als
Volumen durch `vertical3d.volume_final_valid()` geprüft.

Ein `move`-Wechselbefehl wechselt die Ebene nur bei einem **expliziten**
`floor`-Feld mit anderem Wert. Ein fehlendes `floor`-Feld bedeutet weiterhin die
aktuelle Ebene. Ein gültiger Flugweg kann horizontale Annäherung, Etagenwechsel
und horizontale Zielbewegung kombinieren; `walk3d()` führt diese Schritte
animiert aus, sendet `token_floor`, verbraucht das Move-Budget und prüft bei
jedem Schritt die aktuelle Welt erneut.

Unterstützt:

- `mode="fly"` durch eine vollständige Footprint-Öffnung,
- `void` als freie Flugluft,
- Kollision gegen alle anderen Körper als Ganzkörper-Volumen,
- DM-Teleport auf eine andere Ebene nach Volumensprüfung,
- kanonischer Budgetabzug pro Ebene und Schritt.

## 8. UI, Editor und Canvas

Phase 7 bringt die Server-Autorität in die bestehende Oberfläche, ohne eine
zweite Sichtregel einzuführen:

- Token-Sheet-Felder für `height_ft` und `elevation_ft`.
- Ein vertikaler Flugknopf für Tokens mit Flugbewegung; die Zielebene wird
  ausgewählt, der Server sucht Route, Volumen und Kosten.
- Ein DM-Editor-Pinsel für `openv`; `⬆️⬇️` kennzeichnet eine Öffnung in der
  Taktikansicht.
- Die Editor-Resize-Routine trägt `openv` mit.
- Tokenanzeigen zeigen `↑<ft>` für Elevation und `↕<ft>` für eine ausdrücklich
  gesetzte Körperhöhe.
- Spieler und DM-Charaktervorschau rendern/clicken genau die Rows, die der
  Server als beobachtbar geliefert hat.
- Das DM-Ebenenbrowsing bleibt lokal auf `state.viewFloor`; andere Ebenen
  schwimmen nicht über einer Karte.

Der Canvas filtert keine eigene Sicht und errät keine Körperhöhen. Die
Sicherheitsgrenze bleibt `_viewer_token_view()` auf dem Server.

## 9. Offene Grenzen

Diese Punkte sind bewusst nicht als unterstützt zu behandeln:

- diagonale Schritte kombiniert mit einem Etagenwechsel;
- Springen, Fallen oder Sturzschaden als eigenständige 3D-Mechanik;
- vertikales Klettern oder Schwimmen außerhalb von `fly`;
- keine interaktive 3D-Pfadvorschau im Canvas — der Sheet-Flugknopf sendet den
  Move direkt an den bestehenden 3D-Serverpfad;
- kein direktes Überspringen mehrerer Ebenen ohne durchgehende, erlaubte Route;
- keine Bewegung großer Footprints durch eine einzellige Öffnung;
- keine automatische Erkennung von Treppen, Schächten oder Räumen aus Terrain;
- Stufen bleiben die bestehende geprüfte zweidimensionale Etagenverbindung;
- Thieves'-Tools-Proficiency bleibt weiterhin nicht modelliert;
- die Akzeptanzstrecke ist ein echter Node-JS-Harness, aber kein echter Browser
  mit Chromium/Playwright.

## 10. Dateien

- `app/vertical.py`: Skala und Größen-Defaults.
- `app/floors.py`: absolute Tokenbasis, Oberkante und gespannte Ebenen.
- `app/room/vertical3d.py`: einzige Etage-übergreifende Schlussstelle.
- `app/mapmodel.py`: `openv`-Schema, `body_open`, Validate, Fog-Maske.
- `app/path.py`: `find_path_3d` über `(floor, origin)`-Zustände.
- `app/movecost.py`: `vertical_cost` im bestehenden 5-ft-Budget.
- `app/footprint.py`: mode-aware Terrain- und Zielprüfung.
- `app/db.py`: additive Tokenspalten.
- `app/room/tokens.py`: `token_height`-Handler.
- `app/room/movement.py`: `handle_move`, `_move3d`, `_teleport3d`, `walk3d`.
- `app/room/visibility.py`: Sichtquellen und Live-Delivery.
- `app/rooms.py`: `/state`-Snapshot.
- `app/room/dice.py`: Zielerfassung und Angriffreichweite.
- `app/room/grapple.py`: physische Nachbarschaft.
- `app/room/interact.py`: physische Interaktionsreichweite.
- `app/room/net.py`: Ebenenpublikum inklusive Körperpräsenz.
- `app/static/js/10_core.js`: clientliche Höhen-Helfer.
- `app/static/js/30_room.js`: Höhenfelder und vertikaler Flugknopf.
- `app/static/js/40_ws.js`: `token_height` und Tokenaktualisierung.
- `app/static/js/50_canvas.js`: `openv`-Pinsel, Renderer und plane-lokale
  DM-Browsing-Logik.
- `app/static/index.html`: `openv`-Brush.

### D159-Ergänzung (Dateien)
- `app/mapmodel.py`: Terrain `air`(6), `slab()`, `is_open_volume()`,
  `blank_map(base, AIR)`, Clamp-Max 6.
- `app/floors.py`: signierte `level_map`, `order` (bottom→top inkl. Primary),
  Below-Speicher `{"below","above"}`, `add(below=…)`.
- `app/room/vertical3d.py`: `boundary_open`/`column_open` über signierte
  Level, `slab`-Platte, `ray_clear_3d` (Primitiv).
- `app/room/net.py`: nie bearbeitete Nicht-Primary-Ebene → `blank_map(AIR)`.
- `app/rooms.py`: `/state` + Floor-Routes liefern `floor_levels`;
  `FloorIn.below`.
- `app/static/js/10_core.js`: `floor_levels`, `floorBadge`/`floorDelta`/
  `floorStack`, `viewFilterMode`, State-Felder `viewFilter`/`floor_levels`.
- `app/static/js/30_room.js`: Rail/Panel mit signierten Tags, Below-Add,
  `renderViewFilter`/`setViewFilter`.
- `app/static/js/40_ws.js`: `floors_changed` trägt `floor_levels`.
- `app/static/js/50_canvas.js`: Air-Renderer, Air-Pinsel, plane-abhängiger
  „erase“, Cross-Plane-Badge, Anzeige-Filter in `onPlane`.
- `app/static/index.html`: `floor-below`-Checkbox, `air`-Brush,
  `#viewfilter` (All visible / This floor only).
- `tests/test_d159_open_volumes.py`, `tests/test_d159_view_frontend.py`.
