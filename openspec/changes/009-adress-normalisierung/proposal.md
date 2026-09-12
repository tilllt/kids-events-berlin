# Change 009 — Adress-Normalisierung vor der WFS-Geokodierung

## Ziel
Quell-Schreibweisen von Adressen („Distelfalterstr. 41", „Konrad-Wolf-Str. 39",
„… 13086 BErlin") sollen die amtliche Adress-Geokodierung nicht mehr blockieren.

## Ausgangslage (gemessen 2026-09-12, Berliner WFS `adressen_berlin`)
- `str_name='Distelfalterstr.' AND hnr='41' AND plz='12683'` → **0 Treffer**
- `str_name='Distelfalterstraße' AND hnr='41' AND plz='12683'` → **1 Treffer**
- Dieselbe Signatur bei „Konrad-Wolf-Str./-Straße 39, 13055" und
  „Rheinstr./Rheinstraße 1, 12159"; die Abfrage **ohne PLZ** funktioniert
  (Langform mit PLZ-Fehler bleibt auflösbar, sofern eindeutig).
- Folge im Bestand: 50 von 211 KKK-Events ohne Position, deren Adresse vorlag —
  über nur **12 verschiedene** Adressen (viele Termine je Angebot).

## Umfang
- `app/geo.py`: `_adresse_normalisieren()` — nur für den Suchschlüssel:
  - Komposita-Suffix „…str." → „…straße" (`Ruheplatzstr.` → `Ruheplatzstraße`)
  - Wortteil „Str." / „Pl." → „Straße" / „Platz" (`Konrad-Wolf-Str.`)
  - Stadt-Token case-insensitiv → „Berlin" (Quell-Tippfehler „BErlin")
  - Länderzusatz „Deutschland" am Ende entfernen, Whitespace normalisieren
- `adresse_amtlich()` normalisiert **vor** `_adresse_teile()` und nutzt die
  normalisierte Form als Cache-Schlüssel und in der CQL-Abfrage → die
  Schreibvarianten teilen sich einen Cache-Eintrag.

## Nicht im Umfang (bewusst)
- **Anzeige-Adresse bleibt die Quellangabe** (Provenienz). Die amtliche
  Schreibweise wandert nicht in die Anzeige; wer das braucht, entscheidet es
  separat.
- Adressen mit eingeschobenen Ortsnamen zwischen Hausnummer und PLZ
  („Immanuelkirchstraße 1 Kapelle 10405 Berlin") bleiben unaufgelöst —
  ein „Titel raten und wegwerfen"-Parser wäre riskanter als der Nutzen.
- Adressen, die es im amtlichen Verzeichnis nicht gibt (z. B.
  „Ruheplatzstraße 12" → dort kein Treffer), bleiben ohne Position.

## Verifikation
- Unit: `tests/test_adresse_normalisierung.py` (6 Fälle inkl. Negativfall und
  Cache-Schlüssel-Gleichheit der Schreibvarianten).
- Produktion: KKK-Lauf vor/nach — Zahl der Events ohne Koordinaten (vorher 77)
  und Bezirksverteilung; familienportal/museumsportal als Regressionsprobe.
- Erwartung: die 12 betroffenen Adressen lösen die Mehrheit ihrer Termine auf;
  offen bleiben die 27 Events ohne Adresse.

## Risiken
- Zu aggressive Ersetzungen könnten Straßennamen verfälschen (z. B. „Am
  Straßenrand"): abgesichert durch Test, dass vollständige Schreibweisen
  unverändert bleiben; `\b`-Grenzen verhindern Treffer innerhalb von „Straße".
- Geocache: Der Schlüssel ändert sich für die Abkürzungsfälle → frischer Lookup
  (gewollt). Für unveränderte Adressen bleibt der bestehende Cache gültig.
