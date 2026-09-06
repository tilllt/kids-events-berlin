# 004: Museumsportal-Serien-Termine (Detailseiten mit mehreren Terminen)

## Problem
Detailseiten im Museumsportal listen Serien-Veranstaltungen mit mehreren
Terminen (z. B. Schloss Babelsberg: Zeit(ge)schichten — 8 Termine bis
25.10.). Der Adapter parst nur das JSON-LD-Ereignis (erster Termin) →
weitere Termine gehen verloren; die mp-Liste zeigt ohnehin nur den
nächsten Termin. Das kostet Zeitraum-Tiefe bei einer der Hauptquellen.

## Lösung
1. Detail-Regel-Option `termine_css`: extrahiert Terminzeilen
   (`hylo-list-more ul li` mit zwei Spans: Datum deutsch + Uhrzeit) aus
   der Detailseite → `detail["_termine"]` (tz-aware, Europe/Berlin).
2. Adapter `zu_events(row, detail, jetzt)` → Liste: ohne Terminliste ein
   Event (bisheriges Verhalten); mit Terminliste ein Event pro Termin.
   Row-Start nicht in der Liste → Row-Event zusätzlich (Sicherheitsnetz).
3. Pipeline wendet das 3-Wochen-Fenster (heute .. heute+21, Europe/Berlin)
   auch auf die expandierten Events an — Serien-Termine jenseits des
   Horizonts werden nicht übernommen (konsistent zu familienportal).
4. museumsportal bekommt `horizont_tage: 21` + `termine_css`.

## Tasks
- [x] OpenSpec-Change angelegt
- [ ] parse_detail: termine_css + deutsches Datums-Parsing (_DE_MONATE)
- [ ] zu_events (zu_event bleibt Kompat-Wrapper)
- [ ] Pipeline: Fenster-Filter auf Events (nach zu_events)
- [ ] MUSEUMS_REGELN + Fixture (detail_serie.html) + Tests
- [ ] Prod: horizont_tage=21 für museumsportal setzen; Scrape; Verifikation
