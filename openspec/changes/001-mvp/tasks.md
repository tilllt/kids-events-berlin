# Tasks — Change 001 MVP

Reihenfolge mit TDD; nach jeder Aufgabe committen (`feat:`/`test:`/`docs:`).

## Phase 0 — Fundament (erledigt)

- [x] Repo `tilllt/kids-events-berlin` anlegen (privat), README, .gitignore
- [x] OpenSpec-Gerüst: project.md, 4 Live-Specs, Change 001 — CLI-validiert
- [ ] Quellen-Audit-Ergebnis als `docs/quellen.md` einpflegen (aus Recherche 2026-09-06)

## Phase 1 — Kern-Pipeline (lokal, ohne Netz)

1. [ ] `pyproject.toml` (uv, deps: fastapi, uvicorn, httpx, parsel, pytest …) + `app/`-Paketgerüst
2. [ ] `app/model.py`: Event-Modell + `event_id = sha1(quelle + "/" + source_event_id)` — Test: ID deterministisch
3. [ ] `app/store.py`: SQLite (WAL), Tabellen `events`, `runs`; Upsert idempotent — Test: zweiter Lauf ohne Änderung → `n_neu=0`
4. [ ] `app/validate.py`: Pflichtfelder/Zeitlogik/Horizont; Fehler-Queue sichtbar — Test: kaputtes Zeitfeld → Fehler-Queue + run-Metrik
5. [ ] `app/pipeline.py`: Lauf-Orchestrierung + Metriken

## Phase 2 — Adapter jup.berlin

6. [ ] Fixture aufnehmen (Listing `?page=0..N`, Detail-Seiten, je 1 Beispiel) — echte HTML-Abrufe, abgelegt unter `tests/fixtures/jup-berlin/`
7. [ ] `app/adapters/jup_berlin.py`: Listing-Parser (Titel, Datum/Zeit, Venue, Slug) + Detail-Parser (Beschreibung, Kategorien, Bezirk, ggf. Adresse) — Tests gegen Fixtures
8. [ ] Registry + CLI `python -m app scrape jup-berlin` — Test: Lauf gegen Fixture-Adapter (offline) idempotent
9. [ ] Anreicherung regelbasiert: Altersband, Kostenlos, Kategorien-Mapping — Tests mit typischen Formulierungen

## Phase 3 — API + UI

10. [ ] `app/api.py`: GET /api/events mit allen Filtern (bezirk, altersband, uhrzeit, von/bis, kostenlos, quelle, q) — Parametertests
11. [ ] `GET /api/events.geojson` (Point-Geometrie + `ohne_position`) — Test
12. [ ] `app/static/`: index.html + app.js — Leaflet-Karte (OSM), Marker-Cluster, Sidebar-Filter, URL-State; Zustände: laden/leer/Fehler sichtbar
13. [ ] Dev-Smoke: uvicorn + curl API + Seite im Browser; echte jup.berlin-Daten (1 Lauf) — Events mit Koordinaten/Bezirk

## Phase 4 — Betrieb

14. [ ] Dockerfile (multi-stage, slim, non-root), `.dockerignore`, Healthcheck `/api/health`
15. [ ] Scheduler im Container (täglich, konfigurierbar via Env `SCRAPE_CRON`)
16. [ ] Coolify-App auf .50: Repo-Build, Port 3101, SQLite-Volume; Smoke-Test LAN
17. [ ] Monitoring-Hook: Alarm bei 0-Events/Struktur-Anomalie (ntfy) — MVP: Log + Exit-Code, Alarme folgen
18. [ ] `docs/quellen.md` + README aktualisieren; Change 001 archivieren

## Verifikation (Abnahme-Kriterien)

- `pytest` grün (Pipeline offline mit Fixtures)
- Ein Online-Lauf `scrape jup-berlin` liefert > 0 Events, zweiter Lauf `n_neu=0`
- API-Filterkombination Bezirk/Alter/Uhrzeit liefert korrekte Teilmenge
- UI zeigt Karte mit Markern und Filter-URL-State; Leer-/Fehlerzustand sichtbar
- Container läuft unter Coolify auf .50, Port 3101 erreichbar, SQLite-Persistenz über Recreate
