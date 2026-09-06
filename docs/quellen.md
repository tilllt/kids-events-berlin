# Quellen-Audit: Veranstaltungen mit Kindern in Berlin

> Recherche-Stand: **2026-09-06** · Prüfmethode: echte HTTP-Abrufe, CMS-/Struktur-Fingerprints aus gespeicherten HTML-Proben (Funde eines Recherche-Agenten, der vor Abschluss in einen Timeout lief — Befunde unten sind die gesicherten Teile; nicht abgeschlossene Prüfungen sind explizit als **offen** markiert).

## Kurzfassung — Priorisierung

| Priorität | Quelle | Typ | Empfehlung |
|---|---|---|---|
| 1 | jup.berlin/events | offiziell (SenBJF/jfsb), Drupal 10 | **Adapter fertig (MVP-Quelle)** |
| 2 | familienportal.berlin.de/veranstaltungen | offiziell (Land) | aufnehmen — Struktur **offen** (robots offen) |
| 3 | kinderkulturkalender-berlin.de | LKJ Berlin (gemeinnützig), Drupal | aufnehmen (reich strukturiert) |
| 4 | ZLB-Veranstaltungen (zlb.de) | öffentlich, TYPO3 | aufnehmen (Liste mit Artikeln gefunden) |
| 5 | berlinmitkind.de (HIMBEER) | Magazin (kommerziell-redaktionell) | beobachten → aufnehmen (WordPress+Events Manager, AJAX, JSON-LD) |
| 6 | FEZ Berlin | gemeinnützig, TYPO3 | aufnehmen — Programm-URL **offen** (/programm → 404) |
| 7 | Museumsportal Berlin | öffentlich, Angular-SPA | beobachten (API-Reverse nötig) |
| 8 | Grips/Parkaue-Spielpläne | Theater | später (SPA/API) |
| – | Kindaling, berlinfamily.de, rausgegangen | kommerziell/parked | **verwerfen** |

## Detail-Befunde je Quelle (Belege 2026-09-06)

### 1. jup.berlin/events — ✅ Adapter fertig
- Server-HTML (Drupal 10), Listing `<article class="event teaser">`, Filter-Parameter `borough`/`categories`/`forfree`/`date_start/date_end`, Pagination `?page=N`.
- Detailseiten: Beschreibung, Adresse mit PLZ, Koordinaten als `"lat"/"lon"`, `field-forfree`.
- robots.txt: Crawling erlaubt (Drupal-Standard, nur Core-Assets eingeschränkt).
- Adapter: `app/adapters/jup_berlin.py`, Fixtures `tests/fixtures/jup-berlin/`.

### 2. familienportal.berlin.de/veranstaltungen — offen
- robots.txt: offen (nur `/suche//`, `/suche/s/` disallowed) — **geprüft**.
- Seitenstruktur/Technik: **nicht verifiziert** (Fetch schlug beim Audit fehl, `fp2=000`).

### 3. kinderkulturkalender-berlin.de — aufnehmen
- **Drupal** (442 KB-Probe, 162 `<article>`, 321 Datumsangaben) — sehr listenreich, guter Kandidat.
- robots.txt: Drupal-Standard, offen.
- Hinweis: Einträge laufen über die jup!-DB — **Duplikat-Risiko zu Quelle 1** beim Merge prüfen.

### 4. Berliner Bibliotheken / VÖBB
- **ZLB** (zlb.de): TYPO3; Veranstaltungsliste gefunden (238 KB-Probe, 16 `<article>`, 43 Datumsangaben); TYPO3-Extension `tx_wwt3list_recordlist` (Transkript-Fund). robots: `Disallow /aDISWeb/`, `*.ics`; Events erlaubt. Selektoren: **offen** (Detail-Analyse nötig).
- **VÖBB zentral** (voebb.de): keine zentrale `/veranstaltungen`-URL gefunden (`voebbev`-Probe 196 B = Fehler/Redirect). Einzelne Angebote liegen im aDISWeb (`/aDISWeb/app/prod00?sp=…`), teils mit `*.ics`-Disallow. Zentraler Bibliotheks-Kalender: **offen** — ggf. je Bezirksbibliothek (berlin.de-Seiten) oder ZLB-Liste als Einstieg.
- robots voebb.de: Events-Pfade nicht disallowed (ausgenommen `/daia`, `/divibib`, `/download`, `/dvbapp`, `/ncip*`).

### 5. berlinmitkind.de (= HIMBEER-Magazin online) — beobachten → aufnehmen
- **WordPress mit Events-Manager-Plugin**: Kalender nutzt `em-wrapper`/`em-list`, AJAX-Nachladen (23 AJAX-Referenzen in Probe), Detailseiten mit **JSON-LD `@type: Event`** (Beleg: Detail-Probe 179 KB).
- robots.txt: `User-agent: *` **ohne Disallow** (Crawling erlaubt); explizit nur AI-Crawler geblockt (Amazonbot, CCBot, Bytespider, Applebot-Extended …).
- Himbeer-Magazin (Print) hat **keinen eigenen Online-Kalender** jenseits von berlinmitkind.de (nicht verifiziert: himbeer-magazin.de ohne robots-Datei).
- Wochenendtipps (`/termine/wochenendtipps/`) als redaktionelle Quelle — für Aggregation weniger geeignet.

### 6. FEZ Berlin — aufnehmen, URL offen
- **TYPO3**; `fez-berlin.de/programm` → **404** (Struktur geändert); Programm-URL: **offen**.
- robots.txt: offen (nur interne TYPO3-Pfade, `print=1` disallowed).

### 7. Museumsportal Berlin — beobachten
- **Angular/Ionic-SPA** (Proben 82–164 KB ohne server-seitige Event-Marker) → Events kommen per API; deterministisches Scraping = Reverse-Engineering des JSON-Endpunkts. Machbar, aber Folgeaufwand.
- robots: generell offen (AI-Crawler geblockt).

### 8. Theater-Spielpläne (Grips, Parkaue)
- **Grips**: JS-SPA (Probe 517 KB, 0 server-seitige Termine); robots.txt leer.
- **Parkaue**: „spiritec“-System, Spielplan-API im JS (379 KB-Probe, 34 Datumsangaben, 0 Artikel).
- Einordnung: schwer für deterministisches Scraping → spätere Phase.

### Verworfen
- **Kindaling** (Rails, JS-lastig): kommerziell, Ticketing/Affiliate — ToS-Risiko; robots erlaubt `/` außer `/admin`,`/tickets`,`/account`.
- **berlinfamily.de**: laut Audit parked/verkauft (kein redaktioneller Kalender).
- **rausgegangen.de**: robots offen, aber Fokus Erwachsenen-Events/Clubs — geringer Kindertreffer-Anteil.

## Offene Punkte (nächste Recherche-Runde)
1. familienportal.berlin.de: Technik + Listings-Struktur verifizieren (Fetch schlug fehl).
2. FEZ: aktuelle Programm-/Kalender-URL finden.
3. ZLB: Event-Listen-Selektoren + Detail-URL-Muster bestimmen.
4. VÖBB: zentralen Bibliotheks-Veranstaltungskalender klären (ggf. je Bezirk).
5. berlinmitkind.de: AJAX-Kalender-Endpunkt + JSON-LD-Felder dokumentieren (für Adapter).
6. jup!- vs. kinderkulturkalender-Duplikate: Merge-Regel.
7. daten.berlin.de: offene Datensätze (z. B. Familienzentren-Standorte) als Venue-Stammdaten prüfen.

## Methodik
- Proben als HTML in `/tmp/kidaudit/` (Recherche-Agent 2026-09-06) — nicht versioniert.
- CMS-/Struktur-Fingerprints per Regex über gespeicherte Proben; robots.txt je Domain direkt abgerufen.
- Neue Quelle → Adapter mit Fixture-Test + Eintrag oben (Repo-Wartungsregel).
