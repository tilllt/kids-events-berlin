# kids-events-berlin

LLM-freier Meta-Aggregator für **Veranstaltungen mit Kindern in Berlin**: sammelt Events aus mehreren Quellen (offizielle Portale, Bibliotheken, Kultureinrichtungen), normalisiert und dedupliziert sie und stellt sie als filterbare Karten-/Listen-Ansicht bereit.

**Stand:** Konzept-Phase → MVP im Aufbau (Repo neu angelegt 2026-09-06). Konzept-Dokument: [docs/konzept.md](docs/konzept.md) (Ursprung: `.hermes/plans/2026-09-06_074541-kids-events-berlin-meta-aggregator.md`).

## Leitprinzipien

- **LLM-frei zur Laufzeit (Invariante):** Kein LLM-/Embedding-Aufruf im Betrieb. Deterministische Extraktion (JSON-LD → hEvent → CSS-Selektoren), Regel-Lexika für Alter/Kategorie, deterministische Dedupe (Shingling/Jaccard + Blocking), Review-Queue für unsichere Fälle. LLM-Einsatz nur im Entwicklungs-Loop erlaubt.
- **Fehler sichtbar:** Stille Fehler inakzeptabel. 0-Events-/Struktur-Anomalien je Quelle erzeugen Alarme (ntfy/Matrix); Fixture-Snapshot-Tests je Adapter.
- **Fakten statt Volltext:** Nur Titel/Zeit/Ort/Link + eigener Abstract; Quellen stets verlinkt; robots.txt/ToS je Quelle dokumentiert.
- **OpenSpec:** Jede Verhaltensänderung als Change-Proposal dokumentieren (siehe `openspec/`).

## Feature-Schwerpunkte (MVP)

- Filter nach **Bezirk**, **Alter**, **Uhrzeit**, Datum, kostenlos/bezahlt
- **Karten-Visualisierung** (OpenStreetMap/Leaflet) + Listen-Ansicht
- Kanonischer Event-Merge über mehrere Quellen (ein Event, viele Quell-Links)

## Architektur (Überblick)

```
Quellen → [Adapter je Quelle] → Fetch/Cache → Parse → Normalize → Enrich → Dedupe/Merge → Validate → Publish
                                                                                                  ├─ REST-API (/api/events, GeoJSON)
                                                                                                  └─ Web-UI (Karte + Liste, statisch, OSM)
```

- **Sprache/Runtime:** Python 3.12+, httpx + parsel; SQLite (WAL)
- **Deploy:** Coolify auf dem CIA-Containerhost (.50); Dockerfile-Image aus diesem Repo
- Ausführliches Konzept: `docs/konzept.md`

## Quellen

Aktueller Audit-Stand: [docs/quellen.md](docs/quellen.md) — Recherche 2026-09-06. Verifizierte Kernquelle: `jup.berlin/events` (offizielles Berliner Jugendportal). In Audit: familienportal.berlin.de, berlin.de-Familienkalender, VÖBB/Bibliotheken, FEZ, berlinmitkind.de (HIMBEER) u. a.

## Entwicklung

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest
uvicorn app.main:app --reload   # lokaler Dev-Server
```

## Wartungsregeln

1. Neues Feature / Verhaltensänderung → Change-Proposal unter `openspec/changes/<id>/` + Spec-Update im selben Commit.
2. Neue Quelle → Adapter mit Fixture-Test + Eintrag in `docs/quellen.md` (robots/ToS dokumentieren).
3. CI-Checks nach Push prüfen; keine unfertigen Artefakte.

## Provenienz

Projekt-Dokumente (Konzept, Quellen-Audit) KI-unterstützt erstellt (Hermes), fachlich vom Maintainer geprüft. Quellen-Aussagen mit Besuchsdatum belegt.
