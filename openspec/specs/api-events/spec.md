# API-Events (REST)

## Purpose

Die REST-API stellt die aggregierten Veranstaltungen mit Filtern nach Bezirk, Alter, Uhrzeit, Datum und Kostenlos-Status bereit — als JSON-Liste und als GeoJSON für die Karten-Visualisierung. Jeder Datensatz trägt seine Quellen-Provenienz (Quell-Link, Quelle, Abrufzeit).

## Requirements

### Requirement: Filterbare Event-Liste

- **Ablauf:** `GET /api/events` liefert Events im Zeitfenster mit Query-Parametern:
  - `bezirk` (12 Berliner Bezirke + `berlinweit`, mehrfach)
  - `altersband` (z. B. `0-3`, `4-6`, `7-10`, `11-13`, `14+`, `familie`, mehrfach) — Event passt, wenn sein Band sich überschneidet
  - `uhrzeit` (`vormittag` <12:00, `nachmittag` 12:00–17:00, `abend` ≥17:00, `ganztags`) — anhand der lokalen Startzeit (bzw. Tagesverlauf bei Mehrfachterminen)
  - `von`/`bis` (Datum), `kostenlos` (bool), `quelle`, `q` (Textsuche)
- **Antwort:** JSON: `[{ id, titel, start, ende, bezirk, altersband, kategorien, kostenlos, ort, adresse, lat, lon, quelle, source_url, beschreibung_kurz }]`
- **Architektur:** `app/api.py` (FastAPI-Router), `app/store.py` (SQL-Abfragen).

#### Scenario: Vormittags-Suche für 4–6-Jährige in Neukölln
- **Akteure:** Web-UI, API.
- **Eingaben:** `GET /api/events?bezirk=neukoelln&altersband=4-6&uhrzeit=vormittag&von=2026-09-12&bis=2026-09-13`
- **Ergebnis:** Nur Events, die in Neukölln stattfinden, für 4–6-Jährige geeignet sind und vormittags starten; Felder vollständig; leere Treffer → `[]` mit HTTP 200.

### Requirement: GeoJSON für die Karte

- **Ablauf:** `GET /api/events.geojson` liefert dieselbe Filterung als GeoJSON `FeatureCollection` mit `Point`-Geometrie (`lat/lon` aus Venue-Geokodierung).
- **Ohne Koordinate:** Events ohne Punkt erscheinen zusätzlich im Feld `ohne_position` (FeatureCollection-Property), damit die UI sie in der Liste zeigen kann.

#### Scenario: Karte zeigt nur Events mit Position
- **Akteure:** Karten-UI, API.
- **Eingaben:** Filter Bezirk=Mitte; 3 Events, davon 1 ohne Geokoordinate.
- **Ergebnis:** GeoJSON enthält 2 Features mit `Point`; das dritte Event steht unter `ohne_position`.

### Requirement: Quellen-Provenienz sichtbar

- **Ablauf:** Jeder Event-Datensatz führt `quelle` (Adapter-Name), `source_url` (Original-Seite) und `geholt_am` (Abrufzeitpunkt).
- **Zweck:** Nachvollziehbarkeit und korrekte Verlinkung; Aggregation übernimmt keine fremden Volltexte.

#### Scenario: Nutzer öffnet Quelldetail
- **Akteure:** Nutzer, Web-UI, API.
- **Eingaben:** Klick auf „Zur Quelle“ bei einem Event aus jup.berlin.
- **Ergebnis:** UI öffnet die Original-Event-Seite (`source_url`); API-Antwort enthielt den korrekten Link und Quellnamen.
