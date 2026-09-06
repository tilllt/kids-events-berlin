# Design — Change 001 MVP

## Entscheidungen

1. **Monolith statt Dienste-Split (MVP):** Ein Python-Container (FastAPI) serviert API + statische UI und treibt per Hintergrund-Scheduler die Scrape-Läufe; SQLite-Datei als Volume. Begründung: kleinster betreibbarer Umfang; später (Phase 4) kann ein Worker abgespalten werden. Alternative verworfen: getrennte Worker-/API-Container — mehr Coolify-Komplexität ohne MVP-Nutzen.
2. **LLM-frei als Laufzeit-Invariante:** Keine ML-Abhängigkeit in den Runtime-Dependencies; Extraktion deterministisch (JSON-LD → hEvent → CSS → Regex-Einzelfelder). Eskalationspfad später: kleines lokales Modell mit dokumentierter Fehlerquote, niemals Blackbox-API pro Event.
3. **SQLite statt Postgres:** Single-Writer (Scheduler), WAL-Modus, ein Volume — keine DB-Operation nötig. Migration: Schema-Versionstabelle.
4. **jup.berlin als Pilotquelle:** Server-gerendertes HTML mit stabilen Slugs, Bezirk-/Kostenlos-Filter, Pagination `?page=N` (verifiziert 2026-09-06). Ein Event kann über mehrere Listings-Tage laufen → Dedupe über `source_event_id` (Slug) beim Upsert, Serien-Erkennung später.
5. **Kartendaten ohne API-Key:** Leaflet + öffentliche OSM-Tiles; Geokodierung nur beim Cache-Aufbau (Nominatim, gedrosselt, gecacht); offline Punkt-in-Polygon für Bezirke ist Phase-2-Upgrade.
6. **Uhrzeit-Filter über Startzeit-Bänder** (vormittag < 12, nachmittag 12–17, abend ≥ 17, ganztags); Events ohne Uhrzeit (00:00) werden als `ganztags` behandelt — dokumentierte Regel statt Raten.
7. **Review-Queue statt LLM-Kuration:** Merge-Kandidaten unterhalb der Auto-Schwelle (0.60–0.85) werden als `status=review` markiert und über die API sichtbar; keine automatische „intelligente“ Entscheidung.

## Alternativen (verworfen)

- **Scrapy-Farm / separate Crawler:** Overhead ohne Bedarf; Quellenzahl (10–30) ist mit httpx+parsel pro Adapter beherrschbar.
- **Postgres + PostGIS:** erst bei echter Multi-Writer-/Geodaten-Last; MVP-SQLite reicht, GeoJSON-Berechnung im Python-Layer.
- **Framework-UI (React/Vue):** Vanilla-JS-Seite mit Leaflet hält den Container schlank und wartbar; UI-Skills (claude-design) für das spätere Feintuning.
- **LLM-basierte Klassifikation von Anfang an:** widerspricht der LLM-frei-Invariante und der Kosten-/Determinismus-Anforderung.

## Offene Punkte

- Bezirkszuordnung: Quell-Angabe (jup!) vs. Geokodierung — Konsistenzregel festlegen, wenn zweite Quelle mit Adressen dazukommt.
- Wie viele Events/Tag halten die Quellen-API aus? Rate-Limit-Werte werden beim ersten Adapter empirisch kalibriert.
- Domain/öffentliche URL der App (DNS liegt beim User; Traefik-File-Provider auf .50 routet).
