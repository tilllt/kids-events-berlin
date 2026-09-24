# Change 027 — Ortslexikon: mehrere Schreibweisen zu EINEM Ort zusammenfassen

Status: Vorschlag (Nutzerfrage 2026-09-24: „Können wir die Ortsvorschläge UI auch
so gestalten dass man mehrere Orte (z.B. mit leicht anderen Schreibweisen) als
einen Ort identifiziert und in ein Dictionary ablegt?")

## Kurzantwort

Ja — und die Hälfte liegt schon im Repo, nur ohne Wirkung:

- **`app/orte.py`** hat die Zusammenführungs-Logik bereits vollständig:
  `normalform()` (füllt „am/von/Schloss“, `str.`/`straße` zusammen),
  `ist_generisch()` („Aula“, „online“ sind keine Orte), `kanonisch_waehlen()`
  (häufigste, bei Gleichstand ausführlichste Schreibweise),
  `automatische_zuordnung()` (nur identische Normalform) und
  `verdachtsfaelle()` (Ähnlichkeit ≥ 0,80 → Prüfliste). **Sie ist aber toter
  Code:** benutzt nur von einem CLI-Bericht (`app/cli.py`) und Tests. Kein
  Speicher, keine Oberfläche.
- **`app/geo.py:ORT_ALIAS`** ist ein fest verdrahtetes Python-Dict (AGB, BStB,
  TREFFPUNKT) — genau das, was der Nutzer editierbar haben will. Es wirkt
  bereits im Scrape (`pipeline.py:284`), aber nur per Code-Änderung pflegbar.
- Der Tab „Orte“ hat **schon** Mehrfachauswahl (Checkbox-Spalte, „Alle
  sichtbaren auswählen“) und Batch-Aktionen — es fehlt die dritte Aktion.

## Speicher (zwei neue Tabellen, SQLite wie alles andere)

```sql
CREATE TABLE orte (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,        -- kanonischer Anzeigename
  adresse TEXT,                     -- für die Geokodierung
  bezirk TEXT, lat REAL, lon REAL,  -- soweit bekannt
  generisch INTEGER NOT NULL DEFAULT 0,   -- „Aula“, „online“: kein Ort
  notiz TEXT,
  erstellt_am TEXT NOT NULL, geaendert_am TEXT
);
CREATE TABLE ort_alias (
  variante TEXT PRIMARY KEY,        -- EXAKTE Quellschreibweise
  ort_id INTEGER NOT NULL REFERENCES orte(id) ON DELETE CASCADE,
  quelle TEXT,                      -- NULL = gilt überall
  erstellt_am TEXT NOT NULL
);
```

**Schlüssel ist die exakte Schreibweise, NICHT die Normalform.** Das ist die
wichtigste Entscheidung: `normalform("Grundschule am Park")` ist derselbe Wert
für zwei Schulen in zwei Bezirken — die Warnung steht wörtlich in
`orte.py:126`. Als Schlüssel würde sie beide auf einen Ort verschmelzen. Die
Normalform bleibt, was sie heute ist: Vorschlagsmaschine für die Prüfliste.

**Migration:** Der heutige `ORT_ALIAS` (AGB/BStB/TREFFPUNKT mit ihren Adressen)
wird beim Start in die Tabellen übernommen — Seed, überschreibt nie
(vgl. `seed_template_tags`). Danach liest nur noch die DB.

## Wirkung im Scrape

`app/geo.py:ort_aufloesen()` fragt in dieser Reihenfolge:

1. **DB-Wörterbuch** (exakte Schreibweise, quelle-spezifisch vor global)
2. eingebautes `ORT_ALIAS` (bleibt als Rückfall)
3. unverändert

Damit greifen Alias → Adresse → Geokodierung → Bezirk → Kartenpunkt
automatisch, **und der Ortsfilter führt den Ort nicht mehr doppelt** (heute
stehen „B.L.O. Ateliers“ und „B.L.O.-Ateliers“ als zwei Orte im Filter).

**Provenienz:** neue Spalte `events.ort_roh` (Migration per ALTER TABLE, wie
gehabt). Der Scrape schreibt weiter die Quellschreibweise hinein; `ort` trägt
den kanonischen Namen. Ohne diese Spalte wäre nach der ersten Umschreibung
nicht mehr nachvollziehbar, was die Quelle gesagt hat — der Grundsatz steht
schon in `orte.py:19`.

## Oberfläche (Tab „Orte“)

1. **„Als einen Ort zusammenfassen“** — neue Aktion neben „Ausgewählte
   übernehmen/verwerfen“. Mehrere Zeilen anhaken → Dialog:
   - Kanonischer Name, vorbelegt mit `kanonisch_waehlen()` der Auswahl
   - Adresse, vorbelegt aus der besten Zeile (Beleg vorhanden)
   - Bezirk (optional), „generisch“ (kein Ort) als Schalter
   → legt `orte` + Aliase an und schreibt die betroffenen Termine um.
2. **Vorschlagsgruppen**: `verdachtsfaelle()` (Ähnlichkeit ≥ 0,80 oder ein Name
   steckt im anderen) werden in der Liste als zusammengehörige Gruppe gezeigt —
   ein Klick übernimmt die ganze Gruppe als einen Ort. Die Schwelle bleibt
   bewusst großzügig (ein überflüssiger Vorschlag kostet einen Klick).
3. **Ortslexikon-Abschnitt**: alle kanonischen Orte mit ihren Varianten und
   Häufigkeit, editierbar — Name/Adresse ändern, Variante ergänzen oder lösen,
   Ort löschen. Zeigt auch, wie viele Termine der Ort hat.

**Sofortnutzen für die offenen Fälle:** „Arkonaplatz“ und „Boxhagener Platz“
(je 9 Termine ohne Bezirk, Change 025) lassen sich damit als Ort mit Adresse
anlegen — Bezirksfilter und Kartenpunkt greifen beim nächsten Lauf, ohne sie
einzeln durchzuklicken.

## Tests

- Store: Alias anlegen/auflösen, `ON DELETE CASCADE`, exakte Schreibweise
  trennt zwei gleichnamige Orte in verschiedenen Bezirken
- `ort_aufloesen` mit Test-DB: DB schlägt eingebautes Dict, quelle-spezifisch
  schlägt global, unbekannt bleibt unverändert
- Pipeline: Termin mit Alias-Schreibweise bekommt kanonischen Ort + Adresse +
  Bezirk, `ort_roh` behält die Quellschreibweise
- API: zusammenfassen (mehrere IDs → eine `orte`-Zeile, N Aliase), Auflösen,
  Liste; Validierung (leerer Name, doppelte Variante in zwei Orten)
- Admin-Seite lädt (der `?v=`-Cache-Test deckt sie ab)

## Offene Entscheidungen (vor dem Bau)

1. **Sofort umschreiben oder erst beim nächsten Scrape?** Umschreiben macht die
   Wirkung sofort sichtbar (wie „übernehmen“), setzt aber `manuell=1` an den
   Terminen — die Quelle schreibt sie dann nicht mehr zurück.
2. **Aliase global oder je Quelle?** „Treffpunkt“ kann bei einer Quelle etwas
   anderes heißen als bei einer anderen; global ist einfacher zu pflegen.
