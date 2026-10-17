# CSV-Regelpakete — Handbuch für Inhalt-Autor:innen (DM)

Diese Anleitung beschreibt, wie du Spielinhalt (Waffen, Rüstungen, Zauber,
Völker, Klassen, Unterklassen, Hintergründe, Talente, Kreaturen) als
hand-editierbare **CSV-Dateien** anlegst, prüfst, importierst und wieder
exportierst. Der Importer ist `app/content.py`, die Oberfläche ist das
**Regelwerk-Panel** im Raum (nur für die Spielleitung).

---

## 1. Grundprinzipien

1. **Der Code bleibt, der Inhalt wird Daten.** Mechaniken (Würfeln, Angriff,
   Schaden, Heilung,-Zauber-Slots, Stufen) wohnen weiterhin in den vorhandenen
   Engines (`gear`, `abilities`, `progression`, `health`, `dice`). Eine CSV sagt
   nur, **was existiert** und mit welchen **Parametern**.
2. **Nie Code aus einer Datei.** Eine CSV enthält **keinen** Python-/JS-/SQL-
   Code und führt solchen auch nicht aus. Spalten, die keine Engine umsetzen
   kann, landen als Text in `manual` bzw. `needs_manual` und werden **nur
   angezeigt**, nie heimlich interpretiert.
3. **Raum-bezug.** Inhalt gehört zu **einem** Raum. Raum-ID `0` ist reserviert
   als globale Bibliothek, die jeder Raum mitliest. Ein Import überschreibt
   keinen Inhalt anderer Räume.
4. **Runder Halt.** Der Import ist **idempotent**: denselben Inhalt ein zweites
   Mal zu importieren erzeugt keine Duplikate (Zeilen bleiben `unchanged`).
5. **Export ist die Wahrheit.** Die vollständige, validierte Zeile liegt als
   JSON in der Tabelle `content`. Was du exportierst, ist exakt das, was importiert
   wurde — inklusive aller Spalten.

> **Lizenz:** Das mitgelieferte Technik-Pack (`app/content_pack/`) benutzt
> **eigene, generische Namen und Texte**. Echte Regelpakete (mit ggf.
> geschütztem Text) liefern die Autor:innen selbst; siehe `ATTRIBUTION.md`.

---

## 2. Dateien und Formate

Eine CSV ist **UTF-8**, erste Zeile = Kopfzeile mit den Spaltennamen,
Komma-getrennt; Felder mit Sonderzeichen werden mit `"` maskiert (normales CSV).
Pro Art gibt es **einen** kanonischen Dateinamen:

| Datei | Art (`kind`) | eine Zeile ist |
|---|---|---|
| `species.csv` | `species` | ein Volk / eine Abstammung |
| `classes.csv` | `class` | **eine Stufe** einer Klasse (1…20) |
| `subclasses.csv` | `subclass` | ein Unterklasse-Merkmal auf einer Stufe |
| `items.csv` | `item` | ein Gegenstand (Waffe/Rüstung/Trank/…) |
| `spells.csv` | `spell` | ein Zauber |
| `backgrounds.csv` | `background` | ein Hintergrund |
| `feats.csv` | `feat` | ein Talent |
| `creatures.csv` | `creature` | eine Kreatur |
| `conditions.csv` | `condition` | eine Zustands-/Marker-**Definition** (Hooks + Lebenszyklus-Effekte, D111) |

Unbekannte Dateien (z. B. `notizen.csv`) werden **übersprungen**, nicht als
Fehler gewertet — sie erscheinen aber markiert im Bericht.

Ein ganzes Paket kannst du als **ZIP** hochladen: Der Server erkennt eine ZIP
automatisch (an der Signatur `PK\003\004`) und importiert jede bekannte
`*.csv` darin.

---

## 3. Allgemeine Wertformate

| Format | Beispiel | gilt für |
|---|---|---|
| **Pflicht-ID** | `sword_plus1` | nur `a-z 0-9 _ -`, beginnt mit alphanumerisch, ≤ 32 Zeichen |
| **Wahr/Falsch** | `1` / `0` (auch `true/false`) | alle `bool`-Spalten |
| **Würfel** | `1d8`, `2d6+3`, `-1d4` | `damage_dice`, `heal_dice`, `damage_dice_two_handed` |
| **Bonus-Würfel** | `+1d8` (flacher addiert ist hier verboten) | `extra_damage_dice`, `upcast_step` |
| **Attributs-Boni** | `str+2,con+1` (Summen werden zusammengezählt) | `ability_bonuses`, `attribute_bonus` |
| **Attributssatz** | `int=15,wis=13` (setzt Wert, nicht Modifikator) | `attribute_set` |
| **Liste** | Komma **oder** Semikolon-getrennt: `dex; int` bzw. `dex, int` | `saves`, `skill_prof`, `expertise`, `class_list`, `spells_grant` … |
| **Ganzzahl mit Bereich** | `range_normal_ft = 150` | `int:min-max`, `fint` (Dezimal), Bereich gilt streng |
| **Bild** | `/assets/<16 Hex-Zeichen>` (nur hochgeladene Assets) | `image` |
| **Freitext** | Beschreibung | `features`, `traits`, `effect`, `desc`, `manual` |

**Leerfeld** = „Standardwert“ der Spalte (z. B. `speed_ft` leer → 30). Eine
unbekannte Spalte ist ein **Hinweis (Warnung)**, kein Fehler — du kannst eigene
Notizspalten frei lassen; sie werden beim Export mitgenommen.

---

## 4. Spalten nach Art

Legende: **F** = Pflicht. Typ in Klammern.

### 4.1 `species.csv` — Volk
| Spalte | Typ | Bedeutung |
|---|---|---|
| `id` **F** | id | stabile interne ID |
| `name` **F** | Text | Anzeigename |
| `size` | tiny/small/medium/large/huge/gargantuan | Größe; setzt beim Charakter-Seating den bestehenden `tokens.size`-Footprint (D126) |
| `speed_ft`,`fly_ft`,`swim_ft`,`climb_ft` | 0–999 | Bewegung in ft; speist die bestehende `gear.clean_speeds()`-Ableitung (D126) |
| `darkvision_ft` | 0–999 | Dunkelsicht; speist die bestehende LOS-Zellen-Ableitung (D126) |
| `ability_bonuses` | Attributs-Boni | z. B. `dex+2` |
| `languages` | Text | Sprachen (Freitext/Provenance) |
| `traits` | Text | Merkmale (Anzeige; keine eigene Adjudikations-Engine) |
| `image` | asset | Porträt |
| `manual` | Text | Hinweis, was die Engine **nicht** automatisch umsetzt |

### 4.2 `classes.csv` — Klasse (eine Zeile pro Stufe)
Eine Klasse = bis zu 20 Zeilen mit gleicher `id`, aber unterschiedlichem `level`.
Werte, die nur auf Stufe 1 gelten (Grund-Trefferwürfel, Rettungen, Fertigkeitsoptionen),
trägst du in die Stufe-1-Zeile; Stufenmerkmale in ihre jeweilige Stufe.

| Spalte | Typ | Bedeutung |
|---|---|---|
| `id` **F** | id | Klassen-ID (gleich über alle Stufen) |
| `level` **F** | 1–20 | diese Stufe |
| `name` | Text | Klassenname |
| `hit_die` | 4–12 | Trefferwürfel (Standard 8) |
| `hp_base` | 1–99 | Start-TP auf Stufe 1 |
| `hp_per_level` | 1–12 | TP-Zuwachs pro weiterer Stufe (fix, ohne Würfel) |
| `saves` | Attributliste | gerettete Attribute, z. B. `dex; int` |
| `skill_options` | Fertigkeitsliste | wählbare Fertigkeiten |
| `skill_count` | 0–8 | wie viele davon wählbar |
| `weapon_prof`,`armor_prof` | Text | Waffen-/Rüstungsübungen (Anzeige) |
| `features` | Text | Stufenmerkmal(e) dieser Stufe |
| `expertise` | bool | auf Stufe 1: Expertise verfügbar |
| `subclass_family` | Text | ID-Familie der wählbaren Unterklassen |
| `subclass_choice` | bool | auf dieser Stufe wird eine Unterklasse gewählt |
| `ability_boost_or_feat` | bool | Attributs-ERHÖHUNG **oder** Talent wählbar (z. B. Stufe 4/8) |
| `feat_choice` | bool | ein Talent wird gewählt |
| `class_resource` | Text | Klassenressource `id` oder `id:spec` mit `spec` ∈ `level`·`half_level`·`third_level`·`<ganze Zahl>` (z. B. `sorcery_points:level`) |
| `class_resource_reset` | `short`/`long` | Regeneration dieser Klassenressource (kurz/langer Rast) |
| `spellcasting_ability` | Attribut | Zauberattribut (Attributwert + TB → SL) |
| `cantrips_known`,`spells_known` | 0–20 / 0–99 | **kumulierte** totals auf dieser Klassenstufe (Differenz zur Vorstufe = neuer Wahlpunkt) |
| `prepared` | bool | prepared-Caster (bereitet aus der Klassenliste); sonst known-Caster (wählt) |
| `spell_first_level` | 0–20 | **erste zaubernde Klassenstufe** (0 = nicht zaubernd, z. B. Paladin ab 2) |
| `spell_replace` | bool | auf dieser Stufe darf ein bekannter Zauber getauscht werden |
| `slot_progression` | Text | **Slot-Tabelle** dieser Klassenstufe als `grad:anzahl;…` (z. B. `1:4;2:3;3:2`). Wird vom Build **gelesen**, aber **nie** aus der Gesamtstufe abgeleitet (D58). Halbe/Voll-Caster setzen eigene Tabellen. |
| `upcast_scaling` | bool | Hinweis, dass Zauber mit Slotstufe skalieren (die eigentliche Regel steht pro Zauber in `upcast_step`) |
| `manual` | Text | was händisch entschieden werden muss |

**Startausrüstung (D105, nur Zeile `level=1` maßgeblich):**

- `starting_items` — feste Gegenstände, kommagetrennt: `id` oder `id xN`
  (N = 1…999, Kleinbuchstaben, Item-Id ≤ 24 Zeichen).
  Beispiel: `dagger_surge, potion_heal x2`
- `starting_choices` — Wahlgruppen, je eine Antwort: `Label=alt|alt xN;Label2=…`
  Jede Alternative ist ein fester Token wie oben; mindestens zwei pro Gruppe;
  Gruppenlabels enthalten kein `=`, `|`, `,` und kommen nicht doppelt vor.
  Beispiel: `weapon=bow_long|sword_versatile; kit=goggles_night|gloves_thief`

Auflösung läuft ausschließlich über die Startausrüstungs-Route
(`POST /api/rooms/{code}/starting-gear`): Jedes Token muss auf eine
**Item-Definition dieses Raums** (Pack-Import-Projektion) resolve-bar sein.
Die Klassenvergabe ist **alls-oder-nichts** — ein kaputtes Token blockiert
die komplette Klassen-Startausrüstung, schreibt aber keinen Idempotenz-Claim
(das Pack darf repariert und erneut grantet werden). Eine einmal vergebene
Klassenausrüstung bleibt genau einmal vergeben: spätere Anfragen — auch mit
anderen Choices — beantworten nur `already`. Ein Client kann niemals eigene
Item-Ids einschleusen; die Alternativen-Liste des CSV ist die Allowlist.

### 4.3 `subclasses.csv` — Unterklasse (Zeile pro Merkmal-Stufe)
| Spalte | Typ | Bedeutung |
|---|---|---|
| `id` **F** | id | Unterklasse-ID (über Stufen gleich) |
| `class_id` **F** | id | zu welcher Klasse (`classes.id`) |
| `level` **F** | 1–20 | ab welcher Stufe dieses Merkmal |
| `name` | Text | Name |
| `features` | Text | Merkmalstext |
| `spells_grant` | Zaubergewährung | zusätzliche Zauber (IDs) |
| `needs_choice` | bool | Merkmal verlangt eine Wahl |
| `manual` | Text | Hinweis |

### 4.4 `items.csv` — Gegenstand
Die **breiteste** Art. Kampfrelevante Werte sind typisiert (siehe Abschnitt 8);
alles rein Beschreibende gehört nach `desc`/`manual`.

| Spalte | Typ | Bedeutung / Engine-Wirkung |
|---|---|---|
| `id` **F**, `name` **F** | | ID, Name |
| `category` | Text | freie Ordnung |
| `kind` | armor/shield/potion/scroll/wand/staff/ring/tool/wondrous/spellbook/weapon/other | Gegenstandsart |
| `weight` | 0–9999 (Dezimal) | Gewicht in Pfund (Traglast — **aktiv seit Phase E**, siehe Abschnitt 8) |
| `qty` | 1–9999 | Standard-Stapelgröße |
| `value_gp` | 0–999999 (Dezimal) | Wert in GM (Richtwert für Preis/Beute — **aktiv seit Phase E**) |
| `damage_dice` | Würfel | Schadenswürfel der Waffe |
| `damage_dice_two_handed` | Würfel | Schaden beidhändig |
| `versatile` | bool | Vielseitig (ein-/beidhändig; die **Führung** entscheidet den Würfel — siehe unten) |
| `two_handed` | bool | Zweihändig (belegt beide Hände) |
| `hands` | 0–2 | Handbelegung als **Anzeige** (0 = automatisch aus `two_handed`/`versatile`) |
| `finesse` | bool | Finesse (nutzt automatisch den besseren WERT aus STÄ/GES) |
| `properties` | Text | weitere Eigenschaften (Anzeige) |
| `range_normal_ft`,`range_long_ft` | 0–600 | Reichweite normal/lang (Fernkampf) |
| `reach_ft` | 0–60 | Reichweite (Nahkampf) |
| `attack_bonus` | -10…10 | Bonus auf **Angriffs-**Würfe mit diesem Gegenstand |
| `damage_bonus` | -10…10 | Bonus auf **Schadens-**Würfel |
| `damage_type` | Schadnstyp | Grund-Schadnstyp |
| `ac_base` | 0–40 | setzt Rüstungsklasse (nicht additiv) |
| `ac_bonus` | -5…10 | **additiver** AC-Bonus |
| `ac_max_dex` | -1…99 | max. Geschicklichkeitsbonus zu AC (-1 = unbegrenzt) |
| `attribute_set` | Attributssatz | setzt Attributswert (z. B. Rüstungs-Gurt) |
| `attribute_bonus` | Attributs-Boni | erhöht Attribut |
| `skill_prof` | Fertigkeiten | gewährt Übung |
| `save_prof` | Attribute | gewährt Rettungs-Übung |
| `expertise` | Fertigkeiten | gewährt Expertise |
| `darkvision_ft` | 0–999 | gewährt Dunkelsicht |
| `speed_bonus_ft` | -99…999 | Tempo-Modifikator |
| `carry_bonus` | 0–9999 | **erhöht die Traglast** in Pfund (nur solange getragen/eingestimmt; z. B. *Bag of Loading*) |
| `extra_damage_dice` | Bonus-Würfel | **zusätzlicher** Schadenswürfel (z. B. `+1d8`) |
| `extra_damage_type` | Schadnstyp | Typ des Zusatzschadens |
| `heal_dice` | Würfel | beim Konsum heilend (Trank) |
| `hit_dice_bonus` | -10…10 | Bonus auf Trefferwürfel |
| `charges` | -1…999 | Aufladungen (-1 = unendlich) |
| `recharge` | `` / `long` | Regeneration |
| `attune` | bool | erfordert Einstimmung |
| `magic` | bool | magischer Gegenstand |
| `duration`,`trigger` | Text | `trigger` (`use`/`equip`/`unequip`/`on_hit`/`on_damaged`) **weckt** die `effects`-Kette (D111); `duration` bleibt Anzeige |
| `effects` | JSON | **Effektgrammatik v1** (`docs/EFFECT_GRAMMAR.md`) — `use` am Verbrauch, `equip`/`unequip` getragen, `on_hit` als Waffe, `on_damaged` getroffen; replay-geschützt |
| `light` | bool | leuchtend |
| `image`,`desc`,`manual` | | Bild, Beschreibung, Hinweis |

### 4.5 `spells.csv` — Zauber
| Spalte | Typ | Bedeutung |
|---|---|---|
| `id` **F**, `name` **F** | | ID, Name |
| `level` | 0–9 | Zauberstufe (0 = Cantrip) |
| `school` | Text | Schule (Anzeige) |
| `casting_ability` | **ein** Attribut | Zauberattribut |
| `targeting` | self/single/point/area | Zielmodus |
| `shape`,`size_ft` | point/line/cone/circle/square, 0–600 | bei `area` |
| `range_ft` | 0–600 | Reichweite |
| `casting_time`,`duration` | Text | Aufwand/Dauer (Anzeige) |
| `concentration` | bool | Konzentration |
| `resolution` | auto/save/attack | Auflösung |
| `save` | **ein** Attribut | Zielrettung |
| `on_save` | none/half/negate | Effekt bei geretteter RW |
| `damage_dice` | Würfel | Schadenswürfel |
| `damage_type` | Schadnstyp | Typ |
| `heal_dice` | Würfel | heilend statt schädigend |
| `upcast_step` | Bonus-Würfel | Aufwärts-Zaubern: z. B. `+1d6` pro Slotstufe über der Basis (`upcast_scaling=1` nötig) |
| `upcast_scaling` | bool | aktiviert die Slot-Skalierung aus `upcast_step` |
| `scale_tiers` | Schwellen `stufe:+würfel;…` | **Cantrip**-Wachstum nach **Charakterstufe**, z. B. `5:+1d8;11:+1d8;17:+1d8` (additiv) |
| `class_list` | Klassenliste | welche Klassen (`classes.id`) den kennen |
| `scaling_note` | Text | Hinweis zur Cantrip-/Slot-Skalierung (Anzeige) |
| `manual` | Text | Hinweis |

Zauber registrieren sich als **wirkbare Ability** (`abilities.register`) und
verbrauchen beim Wirken Slots (Bestehende D41-Mechanik). **Skalierung ist jetzt
generisch und wird automatisch angewandt (D97):** `upcast_step` erhöht die
Würfelanzahl pro Slotstufe über der Basis; `scale_tiers` erhöht sie für Cantrips
nach Charakterstufe. Die Engine faltet die Zusatzwürfel in den **einen** Basis-Würfelterm —
die Zusatzwürfel müssen deshalb **dieselbe Würfelseitenzahl** wie der Basisterm haben
(`8d6` + `+1d6` ✓, `1d8` + `+1d6` ✗ → dann bleibt es beim Grundwurf und der `manual`-
Hinweis greift; nichts wird vorgetäuscht). Flache Boni (`+2`) sind im Würfelterm erlaubt.

`effects` (D111): versionierte JSON-Op-Kette (Schaden/Heilung/Temp-HP/
Zustand/Rettung/Probe/Zwangsbewegung/Ressource) — gültig nur gegen die
Grammatik (`docs/EFFECT_GRAMMAR.md`); unbekannte Ops/Felder → **Zeile wird
beim Import verworfen**, defekte Zellen auf Items werden beim Laden verworfen.

### 4.6 `backgrounds.csv` — Hintergrund
`id`**F**, `name`**F**, `skill_prof`, `tool_prof`, `languages`, `starting_items`
(Komma-Liste von Gegenstands-IDs), `feature`, `manual`.

### 4.7 `feats.csv` — Talent
`id`**F**, `name`**F**, `requires` (Voraussetzung, Anzeige), `ability_boost`
(Attributs-Boni), `skill_prof`, `spells_grant`, `effect` (Text), `manual`,
`effects` (D111: JSON-Op-Kette → das Talent wird als `feat_<id>` wirksam).

### 4.8a `conditions.csv` — Zustand (D111)
`id`**F**, `name`**F**, `glyph`, `color`, `group` (`condition`/`marker`),
die acht Hook-Flags (`blocks_movement`, `speed_delta`, `my_attacks_dis`,
`my_checks_dis`, `my_saves_dis`, `attacks_against_me_adv`,
`attacks_against_me_dis`, `auto_fail_saves`), `effects` (Hook-Dict
`on_start`/`on_round`/`on_expire`, siehe `docs/EFFECT_GRAMMAR.md`), `manual`.
Eine Zeile mit SRD-Key **überschreibt** den verdrahteten Builtin-Hook;
Instanzen (Uhren, `cond_add`) bleiben unverändert.

### 4.8 `creatures.csv` — Kreatur
`id`**F**, `name`**F**, `size`, `type`, `ac` (Standard 10), `hp`,
`speed_ft`/`fly_ft`, die sechs Werte `str`…`cha` (1–30), `cr`, `skills`,
`saves`, `attacks`, `spells`, `abilities`, `darkvision_ft`, `tags`, `companion`
(bool, Begleiter-Markierung), `image`, `manual`.

Seit D122 können DMs im Regelwerk-Panel die NPC-Projektion einer importierten
Zeile prüfen und sie in ihr Bestiarium übernehmen. Unterstützte Werte werden in
den bestehenden `npc.clean_npc()`-Block übersetzt; einfache Angriffe folgen dem
Muster `Bite +4 to hit; 1d6+2 piercing`. Nicht unterstützter Freitext bleibt
sichtbar und deaktiviert den Import.

---

## 5. Import

Im Regelwerk-Panel wählst du Datei(en) bzw. ein ZIP und einen **Modus**:

| Modus | Wirkung |
|---|---|
| **Vorschau** (`preview`) | nur prüfen, **nichts** geschrieben. Liefert Fehler mit **Datei, Zeile, Spalte**. |
| **Anwenden** (`apply`) | schreibt fehlerfreie Dateien. Bereits vorhandene, **unterschiedliche** ID = **Konflikt** (wird **nicht** überschrieben). |
| **Ersetzen** (`replace`) | schreibt und überschreibt bestehende IDs. |

Regeln:
* Scheitert **eine Zeile**, wird **nur die betroffene Datei** nicht geschrieben
  (die guten Zeilen dieser Datei werden sicherheitshalber zurückgehalten).
  Andere Dateien im selben Paket sind davon nicht betroffen.
* Der Fehlerbericht nennt pro Datei `file`, `line` (Zeile inkl. Kopfzeile,
  1-basiert) und `column` (Spaltenname) sowie eine Meldung.
* Limits (Schutz vor Missbrauch/Zip-Bombe): Datei ≤ 400 KB, ≤ 5000 Zeilen,
  ZIP ≤ 40 Dateien, ≤ 4 MB entpackt.

---

## 6. Export

* **Einzelne Art** → CSV (`items.csv` usw.).
* **Alle** → ZIP mit allen bekannten Dateien.
* **Formel-Injection-Schutz:** Werte, die mit `= + - @` (oder Tab/CR) beginnen,
  werden beim Export mit einem führenden `'` neutralisiert, damit eine
  Tabellenkalkulation sie nicht als Formel ausführt. Beim **Import** wird genau
  dieser Schutz rückgängig gemacht — Export→Import bleibt **rundschluss-treu**.

---

## 7. Was die Engine wirklich umsetzt (vs. Anzeige)

**Mechanisch getragen:**
* Gegenstände projizieren in die DM-Bibliothek (`item_defs`); bewaffnete
  Charaktere erhalten daraus server-seitige Angriff Profile:
  `attack_bonus`, `damage_bonus`, `damage_dice`(+`_two_handed`), `finesse`,
  `two_handed`, `versatile`, `range_ft`(aus `range_normal_ft`)/`range_long_ft`,
  `reach_ft`, `extra_damage_dice`/`_type`, `damage_type`.
* `ac_base`/`ac_bonus`/`ac_max_dex` fließen in die AC-Berechnung (`gear.compute_ac`).
* Zaubern: `level` → Slot-Kosten; `targeting/shape/size_ft/range_ft`,
  `resolution/save/on_save`, `damage_dice`/`_type`, `heal_dice`, `concentration`.
* **Effektgrammatik v1 (D111):** `effects`-Zellen in `spells`/`feats`/`items`
  und die `conditions.csv`-Kette (Hook-Flags + `on_start`/`on_round`/
  `on_expire`) werden von der bestehenden Engine ausgeführt — gültig ist,
  was `docs/EFFECT_GRAMMAR.md` hergibt; unbekannte Ops verwirft der Import.
* `heal_dice` an Konsumgegenständen heilt.
* **Ausrüstung & magische Gegenstände (D98, Phase D):** Getragene/geführte Werte
  werden **abgeleitet** (Overlay in `gear`), nie gespeichert — Ausrüsten, Ablegen,
  Einstimmen oder ein Neustart kann nichts doppelt anwenden oder veraltet lassen.
  Die **fünf Bonus-Arten** werden streng unterschieden:
  - *nur diese Waffe:* `attack_bonus`, `damage_bonus`, `extra_damage_dice/_type`
    (erscheinen im server-seitigen Angriffsprofil genau dieser Waffe).
  - *allgemein für den Charakter:* `attribute_bonus` (Erhöhung) und
    `attribute_set` (fester Wert, **senkt nie**) — speisen **jede** abgeleitete
    Größe (Proben, Rettungen, Initiative, AC-Geschicklichkeit).
  - *nur während ausgerüstet:* alles Obige zählt nur, wenn der Gegenstand in einem
    Ausrüstungssitz steckt (Legacy-Blätter ohne Sitz bleiben unverändert).
  - *nur bei Einstimmung:* `attune`-Gegenstände sind ohne aktive Einstimmung
    **inert** (auch die Waffe schlägt dann ohne ihren Bonus).
  - *einmalig beim Verbrauch:* `heal_dice` (Trank) — über `op_id` replay-geschützt.
  Übung/Expertise/Rettungs-Übung (`skill_prof`/`expertise`/`save_prof`) aus
  Gegenständen **zählen** (ohne doppelte Übungs-Bonus-Anwendung); `darkvision_ft`
  und `speed_bonus_ft` erscheinen im Bogen (Dunkelsicht · effektives Tempo).
  Eine **vielseitige** Waffe wählt pro Instanz die Führung (`inv_grip`), die den
  tatsächlichen Schadenswürfel bestimmt (Einhand `damage_dice`, Zweihand
  `damage_dice_two_handed`); Zweihand-Führung räumt die Nebenhand atomar.
  **Reichweiten:** bis `range_normal_ft` normal, darüber bis `range_long_ft`
  server-seitig **Nachteil** (Vorteil hebt ihn auf), darüber ungültig.
* **Zauberfortschritt (D97, Phase C):** Der Build (`charbuild`) liest die
  Klassen-Zeilen und setzt daraus die **wirkbaren Zauber** (`abilities`), den
  **Zauberbuch-Anzeigepool** (`spells`) und die **Slot-Tabelle** (`spell_slots`) —
  known-Caster wählen, prepared-Caster nutzen die Klassenliste. `slot_progression`
  ist die **Tabelle pro Klassenstufe** und wird **nie** aus der Gesamtstufe
  abgeleitet (D58). `scale_tiers` (Cantrip) und `upcast_step` (Slot) skalieren den
  Wurf **automatisch** (gleiche Würfelseitenzahl). `class_resource` +
  `class_resource_reset` erzeugen eine Klassenressource (z. B. Sorcery Points), die
  den Rast-Handler nutzt. Wirken im Bogen nutzt die **eine** Ability-Engine.
* **Noch händisch am Tisch (ehrlich, nicht vorgetäuscht):** Neue Zauber **auswählen**
  ist ein `needs_choice`-Schritt im Build; `spell_replace` (bekannten Zauber tauschen),
  das **tägliche Vorbereiten** prepared-Caster (neue Zauber nach langem Rast), sowie das
  **Flächen-/Punkt-Zielen** solcher Zauber (wird von der taktischen Karte aus gewirkt,
  nicht aus dem Bogen) bleiben Sache der Spielleitung.

**Nur Anzeige (`manual`/`needs_choice`), weil keine Engine es auswertet:**
`properties`, `duration`, `hit_dice_bonus`, Kreaturen-Angriffe und der
`manual`-Text selbst. (`trigger` ist seit **D111** mechanisch, sofern eine
`effects`-Kette dahintersteht — ohne Kette bleibt es Anzeige.) Diese Werte sind **richtig gespeichert** und sichtbar — die
Spielleitung entscheidet am Tisch.
(*Hinweis: Übungs-/Attributs-/Dunkelsicht-/Tempo-Gaben **von Gegenständen** waren
früher hier — seit D98 werden sie getragen, siehe oben. `weight`/`value_gp` und
Traglast sind seit **D99** aktiv ausgewertet, siehe Abschnitt 8.*)

**Bonus-Arten & Stapeln:** `attack_bonus`, `damage_bonus` und `ac_bonus` sind
**flache Modifikatoren**; `extra_damage_dice` ist ein **Würfel-Bonus**. Sie
addieren sich getrennt nach Art auf Grundwert + Attributsmodifikator; mehrere
gleiche flache AC-Boni werden durch `gear.compute_ac` nach dessen Regel
zusammengeführt. Magische Gegenstände (`magic`) mit `attune` gelten als
einstimmungsbedürftig.

---

## 8. Geld, Währung und Traglast (seit Phase E/D99 ausgewertet)

### 8.1 Währung — intern immer Kupfer (Ganzzahl)

Die Geldbörse eines Charakters ist **eine einzige nicht-negative Ganzzahl in
Kupferstücken (cp)** — niemals Fließkommazahlen, niemals ein Münzfeld pro Sorte
(das könnte pro Sorte negativ werden). Die Aufteilung in Münzen ist **nur Anzeige**
(gierig von der größten Sorte abwärts, damit sich Electrum zu 50 cp immer glatt
teilt). Der **Client sendet nie einen Kupferbetrag**, sondern nur *Ganzzahl +
Sorte*; die Server-Engine rechnet über `to_cp` um. **Kein Request kann Geld
erzeugen.**

Die Umrechnungskurse sind **datengetrieben** und fest hinterlegt
(`gear.CURRENCIES`, später per Content konfigurierbar):

| ID | Name | Wert in cp | Münzgewicht (lb) |
|---|---|---|---|
| `cp` | Kupfer (Copper) | 1 | 0.02 |
| `sp` | Silber (Silver) | 10 | 0.02 |
| `ep` | Electrum | 50 | 0.02 |
| `gp` | Gold (Gold) | 100 | 0.02 |
| `pp` | Platin (Platinum) | 1000 | 0.02 |

Erlaubte Werte: `amount` = positive Ganzzahl (0…1.000.000), `coin` ∈ {`cp`,`sp`,
`ep`,`gp`,`pp`}; Bruchstücke und Unbekanntes lehnt der Import/Handler ab. Eine
Überweisung ist **atomar** und **replay-geschützt** (`op_id`); ein negatives
Guthaben wird **vor** dem Speichern abgelehnt (der ganze Vorgang rollt zurück).

### 8.2 Gegenstandswert & -gewicht

* `value_gp` — **Wert** des Gegenstands in Gold (Preis-/Beute-Richtwert). Münzen
  oder Rohstoff-Barren bekommen Wert **und** Gewicht.
* `weight` — **Eigengewicht** in Pfund (lb). Das Inventargewicht zählt jede
  **Stapelart genau einmal** (`qty × weight`); **ausgerüstete** Gegenstände liegen
  bereits im Inventar und zählen deshalb **nicht doppelt**. Münzen wiegen gemäß
  derselben Anzeige-Aufteilung (`0.02 lb` je Stück, 50 Stück = 1 lb).

### 8.3 Traglast (Tragefähigkeit)

Die Grenze ist **abgeleitet**, nie gespeichert:

```
Traglast (lb) = effektive STÄ × CARRY_PER_STR × Größenfaktor  +  carry_bonus (getragene Gegenstände)
```

* `CARRY_PER_STR = 15` (Pfund pro Stärkepunkt; 5e-Variante „Stärkewert × 15").
* **Größenfaktor** (`SIZE_CARRY`) nach Größe des Charakters:

  | Größe | Faktor |
  |---|---|
  | tiny | ½ |
  | small | ½ |
  | medium | 1 |
  | large | 2 |
  | huge | 4 |
  | gargantuan | 8 |

  Die Größe kommt aus dem (optionalen) Größenwert des Charakters; Standard ist
  `medium`.
* **Magischer Traglastbonus:** die Spalte/Prop `carry_bonus` (siehe 4.4) erhöht die
  Grenze **nur**, solange der Gegenstand getragen **und** — falls `attune` —
  eingestimmt ist (D98-Overlay).
* **Überladung** ist eine **Warnung** im Bogen; eine **Bewegungsstrafe** wird
  bewusst **nicht** angewandt, solange diese Regel nicht vollständig definiert und
  getestet ist.

### 8.4 Begleiter / Reittiere (Tokens, kein CSV)

Begleiter sind **keine CSV-Art**, sondern vorhandene **Tokens** mit
`owner_user_id` und/oder `character_id` (vom **DM** beim Anlegen gesetzt). Steuerung
vergeben **nur DMs** über den generischen **`token_controller`** (Ziel muss Raum-
mitglied sein); Reiten bleibt die azyklische **`token_mount`**-Beziehung. Ein
Spieler kann daher **fremde Begleiter nicht übernehmen** und sieht nur Tokens, die
ihm ohnehin sichtbar sind. `creatures.csv` markiert mit `companion` einen NPC-Block
(D127) als Anzeige/Hinweis; die eigentliche Bindung/Steuerung läuft über die
Token-Oberfläche, nie über eine zweite Engine.

---

## 9. Beispiele (komplett, Import-geprüft)

Jedes Beispiel ist im Test `tests/test_content_examples.py` hinterlegt und muss
vom echten Importer **ohne Fehler** akzeptiert werden. Spalten sind jeweils auf
das Wesentliche gekürzt (nicht gesetzte Spalten = Standard).

**1 · Schwert +1** (`items.csv`)
```
id,name,kind,damage_dice,attack_bonus,damage_bonus,damage_type,magic
sword_p1,Sword +1,weapon,1d8,1,1,slashing,1
```

**2 · Vielseitig 1d8/1d10** (`items.csv`)
```
id,name,kind,damage_dice,damage_dice_two_handed,versatile
sv,Versatile Sword,weapon,1d8,1d10,1
```

**3 · Zweihandaxt** (`items.csv`)
```
id,name,kind,damage_dice,two_handed,damage_type
gt,Great Axe,weapon,1d12,1,slashing
```

**4 · Ring +2 AC** (`items.csv`)
```
id,name,kind,ac_bonus,magic,attune
rn,Ring of Warding,ring,2,1,1
```

**5 · +1 Angriff, zusätzlicher 1d8-Schaden** (`items.csv`)
```
id,name,kind,damage_dice,attack_bonus,extra_damage_dice,extra_damage_type,magic
dg,Dagger of the Surge,weapon,1d4,1,+1d8,lightning,1
```

**6 · Gegenstand gewährt Fertigungsübung** (`items.csv`)
```
id,name,kind,skill_prof,magic,attune
gl,Gloves of the Thief,wondrous,stealth; sleight_of_hand,1,1
```

**7 · Gegenstand gewährt Dunkelsicht** (`items.csv`)
```
id,name,kind,darkvision_ft,magic,attune
gn,Goggles of the Night,wondrous,60,1,1
```

**8 · Heiltrank** (`items.csv`)
```
id,name,kind,heal_dice
ph,Healing Draught,potion,2d4+2
```

**8b · Fernkampf mit normaler und maximaler Reichweite** (`items.csv`)
```
id,name,kind,damage_dice,range_normal_ft,range_long_ft,two_handed,damage_type
lb,Long Bow,weapon,1d8,150,600,1,piercing
```
Bis 150 ft normal, 151–600 ft mit Nachteil, darüber kein Ziel (serverseitig).

**8c · Gegenstand mit Attributsbonus (allgemein)** (`items.csv`)
```
id,name,kind,attribute_bonus,magic,attune
hb,Headband of Intellect,wondrous,int+2,1,1
```
`int+2` hebt INT und damit **jede** abgeleitete Größe, solange getragen+eingestimmt.

**8d · Gegenstand setzt ein Attribut auf einen festen Wert** (`items.csv`)
```
id,name,kind,attribute_set,magic,attune
gg,Gloves of the Giant,wondrous,str=15,1,1
```
`str=15` (Notation `attribut=wert`): Stärke wird 15, ein höherer Wert bleibt.

**8e · Gegenstand mit mehreren Effekten** (`items.csv`)
```
id,name,kind,damage_dice,attack_bonus,extra_damage_dice,extra_damage_type,damage_type,magic,attune
ff,Flame Tongue,weapon,2d6,1,+1d4,fire,slashing,1,1
```
+1 Angriff/Schaden mit dieser Waffe **und** zusätzlicher 1d4-Feuerschaden; Einstimmung nötig.

**9 · Schurken-artige Klasse Stufe 1–20** (`classes.csv`)
```
id,level,hit_die,hp_base,hp_per_level,saves,skill_count,features,expertise
scout,1,8,14,5,dex; int,4,Expertise; Sly Strike,1
scout,2,,,,,,,,
...   # Stufe 3/5/… Merkmale; Stufe 4/8 ability_boost_or_feat=1
scout,4,,1,,,,,,,,
```

**10 · Unterklasse mit Merkmalen auf Stufen** (`subclasses.csv`)
```
id,class_id,level,name,features
trad_s,scout,3,Stalker,Careful Step
trad_s,scout,9,Vanishing,Hide as bonus
trad_s,scout,13,Evasive,No damage on move
```

**11 · Attributs- oder Talentwahl + Talent** (`classes.csv` + `feats.csv`)
```
# classes.csv
id,level,hit_die,ability_boost_or_feat,feat_choice
hero,4,8,1,1
hero,8,8,1,1
# feats.csv
id,name,ability_boost,skill_prof,effect
feat_keen,Keen Mind,wis+1,perception; investigation,+1 Wisdom
```

**12 · Zauberliste einer Klasse** (`spells.csv`)
```
id,name,level,casting_ability,resolution,save,on_save,damage_dice,damage_type,class_list
bolt,Bolt,2,int,save,dex,half,8d6,fire,adept; warden
spark,Spark,0,int,attack,,,,1d8,fire,adept
```

**13 · Cantrip mit Stufen-Skalierung** (`spells.csv`)
```
id,name,level,casting_ability,targeting,resolution,damage_dice,damage_type,scale_tiers,scaling_note
spark,Spark,0,int,single,attack,1d8,fire,5:+1d8;11:+1d8;17:+1d8,grows with character level (applied D97)
```
`scale_tiers` hebt die **Würfelanzahl** des Basiswurfs (`1d8`) nach **Charakterstufe**;
die Stufen sind additiv. (Gleiche Würfelseitenzahl vorausgesetzt, sonst greift `manual`.)

**13b · Klasse mit Zauberfortschritt** (`classes.csv`) — Voll-, Halb- und Known-Caster
```
id,level,spellcasting_ability,spell_first_level,cantrips_known,spells_known,prepared,slot_progression,class_resource,class_resource_reset
adept,1,int,1,3,6,1,1:2,,,                 # prepared-Vollcaster, Stufe 1: zwei 1er-Slots
warden,1,wis,2,0,0,,,,,,,,                 # Halb-Caster, zaubert erst ab Stufe 2
warden,2,wis,2,2,2,,1:2,,,,                # Halb-Caster Stufe 2: nur zwei 1er-Slots (kein 2er!)
seer,1,cha,1,3,3,,1:2,sorcery_points:level,short   # known-Caster + Sorcery Points (kurzer Rast)
seer,3,cha,1,3,4,,1:4;2:2,sorcery_points:level,short # Stufe 3: +1 bekannter Zauber -> Wahlpunkt
```
`slot_progression` = Slot-Tabelle **dieser** Klassenstufe; `spell_first_level` =
erste zaubernde Stufe; `cantrips_known`/`spells_known` = **kumulierte** Totale
(Differenz = neuer Wahlpunkt im Build); `class_resource:spec` = Klassenressource mit
Reset. Der Build prüft die Wahlpflichte (`needs_choice`) und schreibt Wirk-, Slot- und
Ressourcenspalten — ohne zweite Engine.

**14 · Zauber mit Slots + Upcasting** (`spells.csv`)
```
id,name,level,casting_ability,targeting,shape,size_ft,resolution,save,on_save,damage_dice,damage_type,upcast_step,upcast_scaling
bolt,Bolt,2,int,area,circle,20,save,dex,half,8d6,fire,+1d6,1
```

**15 · Geld + Traglast (Wert und Gewicht)** (`items.csv`)
```
id,name,kind,weight,value_gp
gp,Gold Pouch,other,0.02,50
```

**15b · Magischer Traglastbonus** (`items.csv`)
```
id,name,kind,weight,carry_bonus,magic,attune
bag_load,Bag of Loading,wondrous,0.5,250,1,1
```
*(Gewirkt als getragener Gegenstand: `carry_bonus` hebt die Traglast um 250 lb —
siehe Abschnitt 8.3.)*

**16 · Import → Fehler sehen → korrigieren → Export.**
1. `ring,Ring,notakind` in `items.csv` → Vorschau meldet `items.csv`, Zeile 3,
   Spalte `kind`.
2. auf `ring` korrigiert → **Anwenden**.
3. **Export** (`items.csv`) liefert beide Zeilen zurück.

---

## 10. Empfohlener Arbeitsablauf

1. Vorlage aus dem Export oder dem `app/content_pack/` kopieren.
2. Werte pflegen (Liste = Komma **oder** Semikolon; Würfel/Attributs-Boni wie oben).
3. **Vorschau** laufen lassen, alle Fehler (Datei/Zeile/Spalte) beheben.
4. **Anwenden**. Bei bewusster Überschreibung: **Ersetzen**.
5. **Export**, um die gespeicherte Wahrheit zu vergleichen / zu versionieren.

## 11. Eignung für D&D 5e (2024) — Stand D109 (Ursprungs- und Mastery-Schicht umgesetzt)

Verbindliche Regelbasis ist **5e (2024)** nach dem offiziell lizenzierten
**SRD 5.2.1** (Quelle + Attribution in `ATTRIBUTION.md`). Das D107-Audit wurde
in D108 gegen das SRD korrigiert; Matrix und priorisierte R-Liste:
[`RULES_AUDIT_2024.md`](RULES_AUDIT_2024.md). Für Inhalts-Autor:innen kurz:

* **Neu und aktiv (D108):** der **Charakterursprung**. `backgrounds.csv` hat
  jetzt `asi_abilities` (genau drei Kürzel aus `str/dex/con/int/wis/cha`) und
  `origin_feat` (eine Feat-ID); `feats.csv` hat `category`
  (`origin`/`general`/`fighting_style`/`epic_boon`). Nur ein Feat mit
  `category=origin` darf ein Background gewähren. Ein Background ohne diese
  beiden Felder ist **nicht** 2024-tauglich — der Origin-Flow verweigert dann
  sichtbar ("not a 2024 background"); er rät nichts.
  Der Ablauf (Server autoritativ): `GET /api/build/{code}/{cid}/origin`
  (Report), `POST …/origin` mit NUR der Verteilung
  `{"asi":{"mode":"plus2_plus1","plus2":"int","plus1":"wis"}}` oder
  `{"asi":{"mode":"three"}}`. Feat-ID und Beträge kommen aus der CSV, niemals
  aus dem Client. Der Grant landet im Build-Ledger und wird genau einmal
  angewandt.
* **`ability_boost` bleibt erlaubt:** 2024-General-Feats WERFEN Attributs-
  erhöhungen zu (bis max. 20, z. B. +1 WERF). Für `origin`-Feats sieht das SRD
  keine Wertboni vor — Origin-Feats sollten `ability_boost` leer lassen.
* **Bereits 2024-tauglich:** `classes.csv` (ASI-Kadenz je Level-Zeile frei
  wählbar — auch Fighter 1/2/6; ASI ist regeltechnisch ein Level-4+-Feat),
  `spells.csv` (`scale_tiers` rechnet gegen die **Gesamtcharakterstufe** —
  genau die 2024-Regel: Cantrip-Skalung auf Stufe 5/11/17), Slot-/Known-/
  Resource-Spalten, `subclasses.csv`, `creatures.csv` (Formate).
* **Noch 2014/alt, aber nur Daten (nicht automatisch angewandt):**
  `species.csv: ability_bonuses` — 2024 erhöhen Species keine Werte; die Engine
  wendet die Spalte nie mechanisch an. Der Mensch liest sie als Bookkeeping.
* **Neu und aktiv (D109): Weapon-Masteries.** Die 2024er Masteries sind
  Cleave, Graze, Nick, Push, Sap, Slow, Topple, Vex — getrennt von den
  Waffeneigenschaften (Ammunition, Finesse, Heavy, Light, Loading, Range,
  Reach, Thrown, Two-Handed, Versatile).
  – `items.csv` (bzw. die `props` der Waffe): neue Spalte/Prop **`mastery`**
    (`cleave|graze|nick|push|sap|slow|topple|vex`, leer = keine). Das Feld
    beschreibt NUR die Waffe; ob ein Charakter eine Mastery nutzen darf, ist
    sein Build-Ledger (`characters.build.masteries.grants`) — beides muss
    zusammenkommen, und der Angriff muss die Mastery aktiv anfordern.
  – `classes.csv`: **`mastery_gain`** (Integer pro Level-Zeile, geschenkt beim
    Anwenden dieses Levels; Demo: Scout/Warden Level 1 = 1) und
    **`mastery_options`** (kommagetrennte Auswahl-IDs, leer = frei aus allen
    acht). Beides additiv; leere Werte = Schema bleibt 2014-kompatibel.
  – Vergabe: beim Level-Anwenden (`apply`) wandern die Grants als
    `pending`-Vorschläge ins Ledger; die tatsächliche Auswahl erfolgt
    sichtbar über `POST /api/build/{code}/{cid}/mastery`
    (`{"pick":"graze"}`) oder per DM-Grant `POST …/mastery/grant`.
    Bestehende Charaktere werden NIE rückwirkend geändert (D108-Prinzip).
  – Off-Hand: eine Waffe darf den Off-Hand-Slot nur belegen, wenn sie
    `light` ist (2024-Zwei-Waffen-Regel, Voraussetzung für Nick).
* **Lizenz:** 2024-Mechanik in eigenen Worten zu beschreiben ist ok; fremde
  SRD-5.2.1-Regeltexte 1:1 zu kopieren nur unter der CC-By-4.0-Attribution
  (siehe `ATTRIBUTION.md`). Die ausgelieferten Demo-Packs bleiben projekt-
  original mit Hausregel-Hinweisen.
