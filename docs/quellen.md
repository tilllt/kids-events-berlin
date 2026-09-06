# Quellen-Audit: Veranstaltungen mit Kindern in Berlin

> Recherche-Stand: **2026-09-06** (zweite Runde: Live-Feed-Suche + Struktur-Verifikation, 2026-09-06; erste Runde: CMS-Fingerprints aus HTML-Proben). Prüfmethode: echte HTTP-Abrufe; Befunde unten mit Datum.

## Kurzfassung — Priorisierung & Entscheidung (2026-09-06)

| Quelle | Typ | Status | Weg |
|---|---|---|---|
| jup.berlin/events | offiziell (SenBJF/jfsb), Drupal 10 | **produktiv (MVP)** | bestehender Adapter; `rss.xml` = nur News, kein Event-Feed (geprüft) |
| zlb.de/veranstaltungen | ZLB, TYPO3 | **aufnehmen (Stufe 2)** | saubere Teaser-Klassen: `article.eventTeaser`, `h3.eventTeaser__title`, Datum im Teaser — kein Feed (geprüft) |
| berlinmitkind.de (HIMBEER) | WordPress + Events Manager | **aufnehmen (Stufe 2)** | Event-Liste AJAX (`em-events-search`); Detailseiten JSON-LD `@type:Event`; `/termine/rss` = Blog-Feed, kein Event-Feed (geprüft) |
| familienportal.berlin.de/veranstaltungen | offiziell (Land) | **aufnehmen (Stufe 2)** | erreichbar (200, 103 KB); Datumsangaben + h3-Artikelstruktur; Feed: keiner gefunden |
| kinderkulturkalender-berlin.de | LKJ Berlin, Drupal | **nicht aufnehmen** | Einträge laufen über die jup!-Datenbasis → Duplikat; kein Doppel-Scrape |
| FEZ Berlin | TYPO3 | offen | Programm-URL noch zu klären |
| Museumsportal Berlin | Angular-SPA | beobachten | API-Reverse nötig (Folgeaufwand) |
| Grips/Parkaue-Spielpläne | SPA/API | später | |
| Kindaling, berlinfamily.de, rausgegangen | kommerziell/parked | **verwerfen** | |

**Prinzip (User-Vorgabe):** Feed-first (RSS/Atom/iCal) vor HTML-Selektoren; existierende Bibliotheken (feedparser, icalendar, parsel, extruct); Regeln als editierbare YAML-Daten, keine pro-Quelle-Parser.

## Detail-Befunde je Quelle

### jup.berlin/events — ✅ produktiv
- Drupal 10, Server-HTML, Listing `<article class="event teaser">`, Filter-Parameter `borough/categories/forfree/date_start/date_end`, Pagination `?page=N`.
- Detailseiten: Beschreibung, Adresse mit PLZ, Koordinaten (`lat/lon`), `field-forfree`.
- **Feed-Check (2026-09-06):** `https://jup.berlin/rss.xml` → 200, aber nur 1 Item = News-Artikel („Takeover Bellevue“), kein Event-Feed. `…/events/rss.xml` und `…/events/feed` → 404. → bleibt beim bestehenden Adapter.
- robots: Drupal-Standard, Crawling erlaubt.

### familienportal.berlin.de/veranstaltungen — Stufe 2, aufnehmen
- **Erreichbarkeit (2026-09-06):** 200, 103 KB, Titel „Veranstaltungen für Familien | Berliner Familienportal“. Der frühere Audit-Fetch-Fehler war transient/UA-bedingt.
- Struktur: h2/h3-Artikelblöcke mit Datumsangaben (`06.09.2026` …); Feed-Link: keiner gefunden.
- robots: offen (nur `/suche//`, `/suche/s/` disallowed).
- Adapter: Regeldatei (Selektoren beim Implementieren präzisiert, Fixture-Pflicht).

### kinderkulturkalender-berlin.de — nicht aufnehmen (Duplikat)
- Drupal, sehr listenreich. Einträge laufen über die jup!-Datenbasis → als eigene Quelle würde sie jup!-Events duplizieren. **Entscheidung:** nicht in Registry; Merge-Regel (Titel+Datum±1+Venue) bleibt für echte Quellen-Überschneidungen.
- robots: offen.

### Berliner Bibliotheken / ZLB (zlb.de) — Stufe 2, aufnehmen
- **Struktur (2026-09-06):** `https://www.zlb.de/veranstaltungen` → 200 (239 KB); Event-Teaser als `<article class="eventTeaser …" is="event-teaser">` mit `<h3 class="eventTeaser__title">` und Datumsangaben im Teaser (`06.09.2026`). TYPO3.
- Feed: weder auf Startseite noch auf der Veranstaltungsliste `<link rel="alternate">` (RSS/Atom) → keine Stufe 1.
- robots: Events erlaubt; `Disallow /aDISWeb/`, `*.ics`.
- VÖBB zentral: keine `/veranstaltungen`-URL; Einzelangebote im aDISWeb — **nicht** als eigene Quelle (ZLB-Liste deckt den Bibliotheks-Einstieg ab).

### berlinmitkind.de (= HIMBEER) — Stufe 2, aufnehmen
- WordPress + Events-Manager. Kalender `/termine/` rendert Suchmaske (`em-events-search`), Event-Liste lädt per AJAX; Detailseiten mit **JSON-LD `@type: Event`** (extruct-Pfad).
- **Feed-Check (2026-09-06):** `/feed/`, `/termine/feed/`, `/termine/rss` → alle Blog-/Kategorie-Feeds (10 Items, redaktionelle Titel, `pubDate` = Veröffentlichung, keine Event-Zeiten); `/events/feed/` → 404. → kein EM-Event-Feed aktiv → Stufe 2 (AJAX-Endpunkt + JSON-LD-Details).
- robots: `User-agent: *` ohne Disallow; nur AI-Crawler geblockt.

### FEZ Berlin — offen
- TYPO3; Programm-URL (früher `/programm` → 404) noch zu klären; robots offen.

### Museumsportal Berlin — beobachten
- Angular-SPA; Events per API (Reverse-Engineering nötig); robots offen, AI-Crawler geblockt.

### Theater (Grips, Parkaue) — später
- JS-SPA bzw. „spiritec“-API; deterministisch nur mit API-Reverse — spätere Phase.

### Verworfen
- **Kindaling** (kommerziell, Ticketing/Affiliate, ToS-Risiko), **berlinfamily.de** (parked), **rausgegangen.de** (Erwachsenen-Fokus).

## Offene Punkte
1. FEZ: aktuelle Programm-/Kalender-URL finden.
2. berlinmitkind: konkreten AJAX-Endpunkt (admin-ajax `action=…`) + Parameter aus der Listenseite extrahieren.
3. familienportal: exakte Teaser-Selektoren beim Adapter-Bau bestimmen (Fixture).
4. daten.berlin.de: offene Datensätze (Familienzentren-Standorte) als Venue-Stammdaten prüfen (später).

## Methodik & Wartungsregel
- Proben/Feeds: Live-Abrufe (UA `kids-events-berlin/0.2 (research)`) — Fixtures versioniert unter `tests/fixtures/<quelle>/`.
- Neue Quelle → Entscheidung Feed (Stufe 1) oder Regeln (Stufe 2) nach Live-Check; Eintrag in `configs/quellen.yaml` (+ ggf. `configs/regeln/<quelle>.yaml`); Fixture-Test Pflicht.
- Quelle fällt um oder baut um → Fixture-Test rot + Anomalie-Alarm; Regeln per Volume-Overlay korrigierbar (Anleitung in `docs/quellen-regeln.md`).
