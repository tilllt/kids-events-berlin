# API-Events (ADDED)

## ADDED Requirements

### Requirement: Filterbare Event-Liste
- `GET /api/events` mit Query-Parametern: `bezirk` (12 Bezirke + `berlinweit`, mehrfach), `altersband` (z. B. `0-3`,`4-6`,`7-10`,`11-13`,`14+`,`familie`, mehrfach, Überschneidung), `uhrzeit` (`vormittag` <12:00, `nachmittag` 12:00–17:00, `abend` ≥17:00, `ganztags`), `von`/`bis`, `kostenlos`, `quelle`, `q`.
- JSON-Antwort je Event: `id, titel, start, ende, bezirk, altersband, kategorien, kostenlos, ort, adresse, lat, lon, quelle, source_url, beschreibung_kurz`.

#### Scenario: Vormittags-Suche für 4–6-Jährige in Neukölln
- **Akteure:** Web-UI, API.
- **Eingaben:** `GET /api/events?bezirk=neukoelln&altersband=4-6&uhrzeit=vormittag&von=2026-09-12&bis=2026-09-13`.
- **Ergebnis:** Nur passende Events; leere Treffer → `[]` mit HTTP 200.

### Requirement: GeoJSON für die Karte
- `GET /api/events.geojson`: gleiche Filterung als `FeatureCollection` mit `Point`-Geometrie; Events ohne Koordinate unter Property `ohne_position`.

#### Scenario: Karte zeigt nur Events mit Position
- **Akteure:** Karten-UI, API.
- **Eingaben:** Filter Bezirk=Mitte; 3 Events, 1 ohne Geokoordinate.
- **Ergebnis:** 2 Features mit `Point`; drittes Event unter `ohne_position`.

### Requirement: Quellen-Provenienz sichtbar
- Jeder Datensatz führt `quelle` (Adapter-Name), `source_url` (Originalseite), `geholt_am`; keine fremden Volltexte übernehmen.

#### Scenario: Nutzer öffnet Quelldetail
- **Akteure:** Nutzer, Web-UI, API.
- **Eingaben:** Klick auf „Zur Quelle“ bei jup.berlin-Event.
- **Ergebnis:** UI öffnet Originalseite; Link und Quellname korrekt in der API-Antwort.
