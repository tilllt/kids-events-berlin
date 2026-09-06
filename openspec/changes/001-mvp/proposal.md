# Change 001: MVP — Meta-Aggregator Kinder-Events Berlin

**Status:** In Arbeit (Repo-Grundlage, 2026-09-06)
**Basis:** Neues Repo `tilllt/kids-events-berlin` ohne Präzedenz

## Why

Es gibt keinen zentralen, filterbaren und LLM-freien Überblick über Veranstaltungen mit Kindern in Berlin. Die relevanten Daten liegen verstreut über offizielle Portale (jup! Berlin, Familienportal, berlin.de-Kalender), Bibliotheks-/Einrichtungs-Kalender und Magazine (HIMBEER/berlinmitkind). Ziel des MVP: eine erste, nachweislich deterministische Pipeline mit der Kernquelle jup.berlin, einer filterbaren API (Bezirk/Alter/Uhrzeit) und einer OSM-Karten-UI, deployt über Coolify auf dem Containerhost.

## What Changes

Gegenüber dem Ist-Zustand (nur Konzept, kein Code) entsteht ein lauffähiges System:

- **Aggregation:** Es gibt eine Kern-Pipeline, die Roh-Events von Adaptern in ein normalisiertes Event-Modell überführt, validiert und idempotent in einem SQLite-Store ablegt; jeder Lauf protokolliert Metriken, jede Ablehnung landet sichtbar in einer Fehler-Queue und erzeugt bei 0-Events-/Fehler-Läufen einen Alarm. Zur Laufzeit ruft die Pipeline keine LLM-/Embedding-Dienste auf.
- **Quellen/Adapter:** Es gibt ein Adapter-Framework mit deklarativer Konfiguration (robots/ToS dokumentiert, Rate-Limit, Pagination, erwarteter Mengenbereich) und dem ersten produktiven Adapter für `jup.berlin/events` (Listing + Detail-Seiten); jeder Adapter besitzt Fixture-Snapshot-Regressionstests, Struktur-Anomalien (>20 % Abweichung) und 0-Events-Läufe lösen Alarme aus.
- **API:** `GET /api/events` liefert filterbare Event-Listen (bezirk, altersband, uhrzeit, von/bis, kostenlos, quelle, q); `GET /api/events.geojson` dieselbe Filterung als GeoJSON mit `Point`-Geometrie und `ohne_position`-Liste; jeder Datensatz führt Quelle, source_url und Abrufzeit.
- **Karten-UI:** Eine deutsche Web-Oberfläche zeigt gefilterte Events als geclusterte OSM-Marker (Leaflet, kein API-Key) und als Liste; Filter-Sidebar für Bezirk/Alter/Uhrzeit/Datum/Kostenlos mit URL-Zustand; Lade-, Leer- und Fehlerzustände sichtbar.
- **Anreicherung (Umfang MVP):** Altersband und Uhrzeit regelbasiert aus Titel/Beschreibung/Startzeit; Bezirk aus Quell-Angabe oder Venue-Geokodierung (Nominatim-Cache); Dedupe über normalisierten Titel + Datum + Venue (Merge-Schwellen mit Review-Queue-Vermerk), kanonischer Merge mit Quellen-Provenienz.

## Specs-Delta

- `ADDED specs/aggregation/spec.md` — Kern-Pipeline, Modell, Validierung, LLM-frei-Invariante
- `ADDED specs/quellen/spec.md` — Adapter-Framework + Erstanwendung jup.berlin
- `ADDED specs/api-events/spec.md` — Filter-API + GeoJSON + Provenienz
- `ADDED specs/karte-ui/spec.md` — OSM-Karte, Filter, sichtbare Zustände

## Downgrade

Downgrade = Repository-Stand vor diesem Change (Konzept-Dokumente, kein laufender Code). Datenbank-Dateien unter `data/` sind nicht versioniert und können gelöscht werden; der Container kann ohne Datenverlust außerhalb des Stacks neu gebaut werden.
