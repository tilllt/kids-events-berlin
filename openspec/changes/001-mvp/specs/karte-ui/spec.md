# Karten-UI (ADDED)

## ADDED Requirements

### Requirement: Kartenansicht mit Event-Markern
- Leaflet + OpenStreetMap-Kacheln (kein API-Key); Marker je Event mit Koordinate, geclustert bei Dichte.
- Popup: Titel, Zeit, Ort, Bezirk, Kostenlos-Status, Link „Zur Quelle“.
- Architektur: `app/static/index.html` + `app/static/app.js` (Vanilla JS), Daten via `GET /api/events.geojson`.

#### Scenario: 200 Events im September in Berlin
- **Akteure:** Nutzer, Browser, API.
- **Eingaben:** Kein Filter, September-Zeitfenster.
- **Ergebnis:** Geclusterte Marker mit sichtbarer Cluster-Zahl; Liste zeigt alle Events; Popup mit Quell-Link.

### Requirement: Filter-Sidebar (Bezirk, Alter, Uhrzeit, Datum, Kostenlos)
- Bezirk (12 + Berlinweit), Altersband (Vorschulalter/Kita, Grundschule, 10+, Jugendliche, Familie, ohne Angabe), Uhrzeit (Vormittag/Nachmittag/Abend/Ganztags), Datum von/bis, Kostenlos-Schalter.
- Filteränderung lädt Karte + Liste neu; aktive Filter einzeln entfernbar; Zustand in URL (teilbar); kompaktes dunkles UI ohne funktionslose Elemente.

#### Scenario: Filterkombination anwenden und teilen
- **Akteure:** Nutzer.
- **Eingaben:** Bezirk=Pankow, Alter=Grundschule, Uhrzeit=Nachmittag.
- **Ergebnis:** Karte und Liste nur passende Events; URL enthält Filter; Zustand bleibt beim Teilen/Neuladen.

### Requirement: Sichtbare Zustände und Fehler
- Lade-, Leer- („Keine Veranstaltungen für diese Filter“ + Reset-Vorschlag) und Fehlerzustand (Meldung + Retry) sichtbar; keine stillen Fehler.

#### Scenario: API-Ausfall
- **Akteure:** Nutzer, Browser.
- **Eingaben:** Backend nicht erreichbar; Nutzer öffnet Seite.
- **Ergebnis:** Sichtbare Fehlermeldung mit Retry-Button; keine leere Karte ohne Erklärung.
