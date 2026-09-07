# Change 006 — Feed-Adapter + SenBJF-Kalender-Quelle: Status

## Phase 1: Feed-Adapter + Quelle (FERTIG, deployed 2026-09-07)

- [x] feedparser-Dep installieren (pyproject + venv)
- [x] `app/adapters/feed_adapter.py` implementieren (generisch, RSS)
- [x] Registry: typ feed → FeedAdapter
- [x] Fixture + Offline-Tests (8)
- [x] Quelle in Produktion anlegen + Scrape + Verifikation

## Umsetzung

- FeedAdapter: Titel-Datumsklammer-Parsing („15.01.2027 15:30 - 18:00 Uhr“,
  „17.02.2027“) als Berliner Ortszeit; `published` des Servers stampft
  Lokalzeit als +0000 → nicht naiv UTC-konvertieren.
- Quelle `berlin-senbjf-kalender` (typ feed, Horizont 400 Tage — TdT liegen
  Monate voraus):
  `https://www.berlin.de/land/kalender/index.php?rss&c=79&kategorie[1]=109`
- Produktion: 3 Events live (Ev. Schule Neukölln 15.01.27, Jane-Addams
  17.02.27, Emil-Fischer 02.03.27), Lauf stabil idempotent (0/0/0),
  Fehler-Queue leer.
- Ort „Ohne Angabe“ (Feed trägt keinen Venue) — Admin kann im Termine-Tab
  nachtragen (manuell=1-Schutz).

## Pitfalls (dokumentiert)

- Admin-API `source_scrape` hatte einen eigenen feed-Guard („folgt“-Text),
  der feed-Quellen mit 409 blockte, obwohl `build_adapter` sie längst
  unterstützte — Guard entfernt.
- Feed-Pagination: Pipeline ruft Seite 1 auf → `fetch_listing_page(>0)`
  liefert `""` statt Exception (Exception landete in der Fehler-Queue);
  `parse_listing("")` → `[]` ohne Strukturwarnung.
- **Quellen-Duplikate:** SenBJF listet dasselbe Event teils doppelt
  (gleicher Titel+Termin, andere Event-ID) → Zwilling-Dedup der Pipeline
  spielte die IDs gegeneinander aus (ewiges n_geaendert). Fix: Adapter
  dedupliziert (Titel+Start+ganztags) beim Parsen.
