# Quellen-Audit: Veranstaltungen mit Kindern in Berlin

> Recherche-Stand: **2026-09-06** (zweite Runde: Live-Feed-Suche + Struktur-Verifikation, 2026-09-06; erste Runde: CMS-Fingerprints aus HTML-Proben). Prüfmethode: echte HTTP-Abrufe; Befunde unten mit Datum.

## Kurzfassung — Priorisierung & Entscheidung (2026-09-06)

| Quelle | Typ | Status | Weg |
|---|---|---|---|
| jup.berlin/events | offiziell (SenBJF/jfsb), Drupal 10 | **produktiv (MVP)** | bestehender Adapter; `rss.xml` = nur News, kein Event-Feed (geprüft) |
| zlb.de/veranstaltungen | ZLB, TYPO3 | **aufnehmen (Stufe 2)** | saubere Teaser-Klassen: `article.eventTeaser`, `h3.eventTeaser__title`, Datum im Teaser — kein Feed (geprüft) |
| berlinmitkind.de (HIMBEER) | WordPress + Events Manager | **aufnehmen (Stufe 2)** | Event-Liste AJAX (`em-events-search`); Detailseiten JSON-LD `@type:Event`; `/termine/rss` = Blog-Feed, kein Event-Feed (geprüft) |
| familienportal.berlin.de/veranstaltungen | offiziell (Land) | **aufnehmen (Stufe 2)** | erreichbar (200, 103 KB); Datumsangaben + h3-Artikelstruktur; Feed: keiner gefunden |
| tip-berlin.de/veranstaltungen | Stadtmagazin (kommerziell-redaktionell), WordPress | **aufnehmen (Stufe 2, mit Kinder-Filter-Pflicht)** | serverseitige Event-Teaser `.card-teaser` (Kategorie/Titel/Venue/Datum/Link `/event/<slug>/`), robots offen; Familien-Rubrik `/stadt/familie/` ist redaktionell (28 Artikel, 3 Events) → nicht als Listing |
| Museumsportal Berlin (museumsportal-berlin.de) | öffentlich (Land Berlin), Ionic/Angular + SSR | **aufnehmen (Stufe 2)** | `/de/veranstaltungen/` serverseitig gerendert: `mp-card`-Karten (Titel/Datum `06.09.26 \| 20:00`/Link `/de/veranstaltungen/<slug>/`); robots `search=yes, use=reference` (explizit erlaubt), AI-Crawler geblockt; Fixture vorhanden |
| kinderkulturkalender-berlin.de | LKJ Berlin, Drupal | **nicht aufnehmen** | Einträge laufen über die jup!-Datenbasis → Duplikat; kein Doppel-Scrape |
| FEZ Berlin | TYPO3 | offen | Programm-URL noch zu klären |
| Grips/Parkaue-Spielpläne | SPA/API | später | |
| Kindaling, berlinfamily.de, rausgegangen | kommerziell/parked/bot-geschützt | **verwerfen** | rausgegangen: Bunny-Shield-Challenge (403, kein deterministischer Zugriff) |

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

### tip-berlin.de — Stufe 2, aufnehmen (mit Kinder-Filter)
- WordPress (Yoast-robots: **kein Disallow**, Crawling erlaubt), `/veranstaltungen/` → 200 (137 KB), **serverseitig gerenderte Event-Teaser** `.card-teaser` mit `.card-teaser__title`, Textzeile „Kategorie Titel — Venue, 06.09.2026“, Link `/event/<slug>/` — kein JS-Kalender (Fingerprint 2026-09-06).
- Feed: `/feed/` = Blog-Beiträge (Podcast/Club-Tipps), `/veranstaltungen/feed/` → 404 — kein Event-Feed → Stufe 2.
- **Kinder-Relevanz:** tip ist allgemeines Stadtmagazin (IFA, Food, Club …) → kinderrelevante Events sind Teilmenge. Aufnahme nur mit Kinder-Filter (Enrichment-Marker Kategorie/Titel/Text bzw. geklärte Event-Kategorie-URL beim Adapter-Bau). Familien-Rubrik `/stadt/familie/` ist redaktionell (28 Teaser, davon 3 `/event/`-Links) → nicht als Event-Listing geeignet.
- Einordnung: kommerziell-redaktionell wie berlinmitkind — Aggregation mit eigenem Abstract + Link (kein Volltext).

### FEZ Berlin — offen
- TYPO3; Programm-URL (früher `/programm` → 404) noch zu klären; robots offen.

### Museumsportal Berlin — Stufe 2, aufnehmen
- `/de/veranstaltungen/` → 200 (165 KB), **serverseitig gerenderte Event-Karten** (`mp-card`-System: `mp-card-type`, `mp-card-location`, `mp-card-content__info`); Titel im `<h3>`, Datum+Uhrzeit im Text (`06.09.26 | 20:00`, JJ.MM.TT), Detail-Link `/de/veranstaltungen/<slug>/`. Ionic/Angular-Bundles (Filter `?page&event_type=…`), aber Liste kommt als HTML — kein SPA-API-Reverse nötig (Fingerprint 2026-09-06, Fixture `tests/fixtures/museumsportal/`).
- **robots (2026-09-06):** `Allow: /` + `Content-Signal: search=yes, ai-train=no, use=reference` → Such-Index/Referenz-Aggregation ausdrücklich erlaubt; nur AI-Crawler (GPTBot, ClaudeBot …) disallowed — passt zur LLM-freien Laufzeit.
- Kinder-Relevanz: hoher Familienanteil („Familienworkshop“, 44 Kind-/Familien-Marker auf der Listenseite); Enrichment greift.
- Feed: keiner gefunden → Stufe 2.

### Theater (Grips, Parkaue) — später
- JS-SPA bzw. „spiritec“-API; deterministisch nur mit API-Reverse — spätere Phase.

### Grün Berlin — Park-Kalender (Tempelhofer Feld, Gärten der Welt, Britzer Garten, Natur-Park Südgelände) — Stufe 2, aufgenommen 2026-09-12

Anlass: Das **13. STADT UND LAND-Festival der RIESENDRACHEN** (12.09.2026,
11–20 Uhr) fehlte im Bestand. Der Betreiber Grün Berlin führt auf **vier**
Park-Websites einen Veranstaltungskalender; alle vier nutzen dasselbe
TYPO3-Plugin (`tx_events2`), aber **unterschiedliche Karten-Templates**.

- `gruen-berlin.de` selbst hat **keinen** Kalender (`tx_events2` fehlt) → nicht aufgenommen.
- `tempelhoferfeld.de/entdecken-erleben/veranstaltungskalender/` — Karte `div.eventWrapper`, Datum `div.date2` („Samstag, 12.09.2026"), Zeit `div.time` („Zeit: 11:00 – 20:00 Uhr"), `div.location` oft leer.
- `gaertenderwelt.de/events/veranstaltungen/` — Datum `div.date` (teils **Bereich** „01.09.2026 - 01.11.2026"), Zeit mit **Punkt** („12.30 Uhr"), kein Ortsblock.
- `britzergarten.de/events/eventkalender/` — Datum `div.date2`, Zeit nur **stundenweise** („Beginn: 19 – 21 Uhr"), kein Ortsblock.
- `natur-park-suedgelaende.de/entdecken-erleben/kalender/` — Datum **ohne Jahr** („Samstag, 12.09."), Ortsblock „Ort: Natur Park Südgelände".

**Lösung für alle vier:** `start` kommt aus dem **Detail-Pfad**
(`.../detail/JJJJ-MM-TT_HHMM/slug/`) — das ist das einzige Feld mit
vollständigem Datum *und* Uhrzeit und identisch über alle vier Seiten
(Format `%Y-%m-%d_%H%M`). Das umgeht das jahrlose suedgelaende-Datum und die
Datumsbereiche von gaertenderwelt. Umsetzung: `_GRUEN_BERLIN_VORLAGE` +
`_gruen_berlin_regeln()` in `app/quellen_defaults.py` mit per-Seite
abweichendem Ende-Regex/-Format (britzer-garten nutzt `%H`, gaertenderwelt
`%H.%M`).

**Befunde aus den Live-Abrufen (2026-09-12):**
- robots.txt bei allen vier: `User-agent: * / Allow: *`, keine Einschränkungen.
- **Kein Feed** (nur hreflang-Alternates) → Stufe 2.
- **Zeitraum-Parameter des Formulars werden serverseitig ignoriert**:
  `tx_events2_events[start]`/`[end]` (GET, `JavaScriptSearch`) ändern die
  Antwort nicht — geprüft mit `TT.MM.JJJJ` und ISO, identische 5 Karten /
  2 Tage. Die Liste zeigt nur die nächsten Tage; der tägliche Scheduler
  greift jeden Termin also kurz vorher ab.
- Detailseiten haben **Event-JSON-LD** (`startDate`/`endDate`/`description`),
  aber **keinen Veranstaltungsort** — der Ort steht im Seitentitel-Suffix
  („… | Tempelhofer Feld").
- **`kostenlos` wird bewusst NICHT gemappt**: `isAccessibleForFree` steht im
  JSON-LD auf `"False"`, obwohl das Festival der Riesendrachen Eintritt frei
  hat — das Feld ist unzuverlässig, keine Angabe ist besser als eine falsche.

### Verworfen
- **Kindaling** (kommerziell, Ticketing/Affiliate, ToS-Risiko), **berlinfamily.de** (parked).
- **rausgegangen.de** — **technisch blockiert (2026-09-06 neu geprüft):** gesamte Domain hinter **Bunny Shield** (JS-Proof-of-Work-Challenge, `/.bunny-shield/`); selbst `robots.txt` liefert 403/Challenge-HTML. Deterministischer LLM-freier Zugriff ohne Browser-Automation/Challenge-Umgehung nicht möglich → nicht aufnehmen (unabhängig vom Erwachsenen-Fokus, der die ursprüngliche Runde-1-Begründung war). Bei Wegfall des Schutzes neu bewerten: Kinder-/Familien-Kategorien ggf. mit Kinder-Filter wie tip-berlin.

## Offene Punkte
1. FEZ: aktuelle Programm-/Kalender-URL finden.
2. berlinmitkind: konkreten AJAX-Endpunkt (admin-ajax `action=…`) + Parameter aus der Listenseite extrahieren.
3. familienportal: exakte Teaser-Selektoren beim Adapter-Bau bestimmen (Fixture).
4. tip-berlin.de: Kinder-Filter-URL der Event-DB klären (Event-Kategorien-Archiv/Parameter); Kinder-Filter-Pflicht beim Adapter-Bau.
5. daten.berlin.de: offene Datensätze (Familienzentren-Standorte) als Venue-Stammdaten prüfen (später).

## Methodik & Wartungsregel
- Proben/Feeds: Live-Abrufe (UA `kids-events-berlin/0.2 (research)`) — Fixtures versioniert unter `tests/fixtures/<quelle>/`.
- Neue Quelle → Entscheidung Feed (Stufe 1) oder Regeln (Stufe 2) nach Live-Check; Eintrag in `configs/quellen.yaml` (+ ggf. `configs/regeln/<quelle>.yaml`); Fixture-Test Pflicht.
- Quelle fällt um oder baut um → Fixture-Test rot + Anomalie-Alarm; Regeln per Volume-Overlay korrigierbar (Anleitung in `docs/quellen-regeln.md`).
