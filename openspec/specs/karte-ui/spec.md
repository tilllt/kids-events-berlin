# Karten-UI (Web)

## Purpose

Die Web-Oberfläche zeigt Veranstaltungen auf einer OpenStreetMap-Karte und als Liste, mit Filtern nach Bezirk, Alter, Uhrzeit, Datum und Kostenlos. Die UI ist kompakt, deutschsprachig, ohne funktionslose Bedienelemente; Fehler- und Leer-Zustände sind sichtbar (keine stillen Fehler).

## Requirements

### Req 1: Kartenansicht mit Event-Markern

- **Ablauf:** Die Karte nutzt Leaflet mit OpenStreetMap-Kacheln (kein API-Key). Jedes gefilterte Event mit Koordinate erscheint als Marker; bei großer Dichte werden Marker geclustert.
- **Marker-Klick:** Öffnet Popup mit Titel, Zeit, Ort, Bezirk, Kostenlos-Status und Link „Zur Quelle“.
- **Architektur:** `app/static/index.html` + `app/static/app.js` (Vanilla JS, kein Framework nötig); Daten via `GET /api/events.geojson`.

#### Scenario: 200 Events im September in Berlin
- **Akteure:** Nutzer, Browser, API.
- **Eingaben:** Kein Filter gesetzt, September-Zeitfenster.
- **Ergebnis:** Karte zeigt geclusterte Marker (Cluster-Zahl sichtbar); Liste zeigt alle Events; Popup enthält Quell-Link.

### Req 2: Filter-Sidebar (Bezirk, Alter, Uhrzeit, Datum, Kostenlos)

- **Ablauf:** Sidebar mit: Bezirk (12 + „Berlinweit“), Altersband (Vorschulalter/Kita, Grundschule, 10+, Jugendliche, Familie, ohne Angabe), Uhrzeit (Vormittag/Nachmittag/Abend/Ganztags), Datum-von/bis, Kostenlos-Schalter.
- **Verhalten:** Jede Filteränderung lädt Karte + Liste neu (`/api/events` + `.geojson`); aktive Filter sind sichtbar und einzeln entfernbar; Seitenzustand in der URL (teilbar).
- **UI-Regeln:** kompakt, dunkles Farbschema konsistent, keine erfundenen Qualitätsstufen, native Selects durch eigene dunkle ersetzt.

#### Scenario: Filterkombination anwenden und teilen
- **Akteure:** Nutzer.
- **Eingaben:** Bezirk=Pankow, Alter=Grundschule, Uhrzeit=Nachmittag.
- **Ergebnis:** Karte und Liste zeigen nur passende Events; URL enthält die Filter; beim Teilen/Neuladen bleiben sie erhalten.

### Req 3: Sichtbare Zustände und Fehler

- **Ablauf:** Ladezustand („lade…“ mit echter Fortschritts-/Statusanzeige), Leer-Zustand („Keine Veranstaltungen für diese Filter“ + Vorschlag Filter zurücksetzen), Fehler-Zustand (API nicht erreichbar → Meldung + Retry-Button).
- **Invarianz:** Keine stillen Fehler: Jede gescheiterte Anfrage oder leere Antwort erzeugt eine sichtbare Meldung.

#### Scenario: API-Ausfall
- **Akteure:** Nutzer, Browser.
- **Eingaben:** Backend nicht erreichbar; Nutzer öffnet die Seite.
- **Ergebnis:** Sichtbare Fehlermeldung mit Retry-Button; keine leere Karte ohne Erklärung.
