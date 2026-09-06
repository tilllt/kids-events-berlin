# kids-events-berlin — Projektübersicht (OpenSpec)

## Zweck

LLM-freier Meta-Aggregator für Veranstaltungen mit Kindern in Berlin: mehrere Quellen werden deterministisch gescraped, normalisiert, dedupliziert (kanonischer Event-Merge) und über eine REST-API + Karten-UI (OpenStreetMap) mit Filtern nach Bezirk, Alter und Uhrzeit bereitgestellt.

## Capability-Index

| Capability | Beschreibung |
|---|---|
| `aggregation` | Kern-Pipeline: Event-Modell, idempotente Läufe, Validierung/Fehler-Queue, LLM-frei-Invariante |
| `quellen` | Adapter-Framework: deklarative Konfiguration, Extraktions-Priorität, Fixture-Tests, Anomalie-Alarme |
| `api-events` | REST-API `/api/events` mit Filtern (Bezirk/Alter/Uhrzeit/Datum/kostenlos), GeoJSON, Quellen-Provenienz |
| `karte-ui` | Web-UI: OSM-Karte + Filter-Sidebar + Liste, sichtbare Fehler-/Leer-Zustände |

## Externe Systeme

- Quellen-Websites (jup.berlin, familienportal.berlin.de, voebb.de, Einrichtungs-Kalender …) — HTTP-Fetch, robots.txt beachtet
- OpenStreetMap-Tiles (öffentliche Tile-Server) + Nominatim-Geocoding (nur Cache-Aufbau) — keine API-Keys
- Alarme: ntfy/Matrix (Betriebskontext CIA)
- Deploy: Coolify auf Containerhost .50

## Konventionen

- **LLM-frei-Invariante:** Zur Laufzeit kein LLM-/Embedding-/externer ML-Aufruf; deterministisch & offline-fähig. Ausnahme nur Entwicklungs-Loop (Adapter-Bau, Code-Review).
- Specs und Proposals auf Deutsch (Repo ohne Präzedenz, deutschsprachiger Reviewer); Code-Kommentare/Identifier Englisch.
- Stille Fehler inakzeptabel: jede Ablehnung/Anomalie erzeugt sichtbaren Zustand oder Alarm.
- Neue Verhaltensänderung → Change-Proposal unter `changes/<id>/` (proposal.md + design.md + tasks.md) und nach Umsetzung Archivierung mit Spec-Anwendung.
