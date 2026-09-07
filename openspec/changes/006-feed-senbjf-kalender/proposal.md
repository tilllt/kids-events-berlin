# Change 006: Feed-Adapter + SenBJF-Kalender-Quelle (Berlin.de)

**Status:** In Arbeit (2026-09-07)
**Basis:** Change 002/003/004/005 (App deployed unter kinderkram.cia-spandau.de)

## Why

Der User hat den Landeskalender der Senatsverwaltung für Bildung, Jugend
und Familie vorgeschlagen:
`https://www.berlin.de/land/kalender/index.php?suchmaske&c=79`
Erwartung: viele „Tage der offenen Tür“ — Befund: der Kalender hat aktuell
nur ~4 TdT (Jan–März 2027), Rest sind Lehrerfortbildungen. Der User will
die Quelle trotzdem anlegen: „ich habe den Eindruck, dass sie in Zukunft
mehr benutzt werden soll“ — Schulen tragen dort ihre TdT/Infoabende nach
und nach ein; die Quelle soll das automatisch abgreifen.

Technisch ist das die **erste Feed-Quelle** des Projekts: Der bisher nur
angekündigte `feed`-Adapter-Typ („folgt mit der ersten Feed-Quelle“) wird
damit real implementiert.

## What Changes

### Feed-Adapter (`app/adapters/feed_adapter.py`, neu)
- Generischer RSS-Adapter über `feedparser` (bereits als Projekt-Dep
  vorgesehen, aber noch nicht installiert → pyproject + venv).
- Erfüllt das Pipeline-Interface: `fetch_listing_page` (EIN Fetch, kein
  Pagination-Bedarf), `parse_listing(xml)` → rows, `zu_event(row, det,
  jetzt)` → dict, `braucht_detail = False` (kein Detail-Fetch — RSS trägt
  Beschreibung/Ort bereits), `close()`.
- Felder aus dem RSS: Titel, Link (source_url), Beschreibung,
  Veranstaltungsort (falls im Feed), Startzeit aus `pubDate`.
- `horizont_tage` wie bei anderen Quellen (Fenster-Filter der Pipeline
  greift auch hier).
- robots/ToS-Eintrag in docs/quellen.md.

### Registry (`app/adapters/__init__.py`)
- `build_adapter`: typ `feed` → `FeedAdapter(quelle, url=…)` statt
  ValueError. Der „folgt“-Platzhalter entfällt.

### Quelle SenBJF-Kalender (Produktion, über Admin-API)
- quelle `berlin-senbjf-kalender`, typ `feed`, URL:
  `https://www.berlin.de/land/kalender/index.php?rss&c=79&kategorie[1]=109`
  (RSS mit Kategorie-Filter „Tag der offenen Tür“ — serverseitig
  vorgefiltert, kein Fortbildungs-Rauschen).
- Abgreifen nur TdT-Events mit Titel-Keyword + Zukunftsdatum; Titel
  kanonisch bereinigen (Datums-/BSN-Klammern), deduplizieren (guid).
- NICHT ins termine_manuell-System: Das sind Scrape-Events einer Quelle,
  laufen normal durch die Pipeline (validieren/geokodieren/anreichern),
  erscheinen wie alle Quellen-Events und sind im Termine-Tab editierbar
  (manuell=1-Schutz).

## Konfiguration

- Egress: berlin.de blockt Datacenter-IPs (Hermes-Host 403); der
  kinderkram-Container läuft auf .50 (DSL-Egress) und kommt durch
  (verifiziert HTTP 200). Kein Tunnel nötig.
- robots.txt von berlin.de ist per Datacenter-IP 403 — Vermerk in
  docs/quellen.md; Kalender-RSS unter .50-Egress geprüft.
- Admin-GUI: Quelle wie jede andere anlegen (Name/URL/Aktiv); typ feed
  wird in der GUI als „Feed“ angeboten (bereits im TYP_LABEL).

## Nicht-Ziele

- Kein Detail-Fetch der Berlin.de-Detailseiten (RSS reicht; Detailseiten
  sind hinter demselben Bot-Schutz und brächten nur Adresse/Geodaten,
  die das Pipeline-Enrichment ohnehin versucht).
- Keine Zuordnung zu den 722 WFS-Schulen (BSN steht teils im Titel, teils
  nicht — Schul-Matching ist ein separates Thema).
- Kein Scrape weiterer Senatskalender (c=…), bis der SenBJF-Kalender sich
  als ergiebig erweist.

## Tests

- Fixture `tests/fixtures/berlin-senbjf/rss.xml` (echter RSS-Abruf vom
  2026-09-07, c=79 + kategorie 109).
- Offline-Test: parse_listing → rows mit Titel/URL/Start; zu_event →
  valides Event; Fenster-Filter verwirft Events außerhalb des Horizonts;
  Idempotenz (2. Lauf n_neu=0).
- Registry-Test: build_adapter(typ feed) liefert FeedAdapter.
- Gesamtsuite bleibt grün.
