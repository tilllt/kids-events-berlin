# Change 025 — Neue Quelle: Wochenmärkte & Flohmärkte Berlin

Status: Vorschlag (Nutzerauftrag 2026-09-24: „füge diese termine zu den quellen
hinzu: https://www.wochenmarkt-flohmarkt.de/")

## Warum

Der Nutzer will die Termine dieser Seite im Aggregator. Es ist die erste
**Markt-Quelle** im Bestand: Wochen- und Trödelmärkte in Berlin, kostenlos,
draußen, ohne Anmeldung — familientauglich, aber ohne Kinderprogramm und ohne
Altersangabe. Sie läuft deshalb ohne Altersband; der Altersfilter blendet sie
nicht aus.

## Was die Quelle ist

Joomla mit **JEvents** (`com_jevents`). `robots.txt` sperrt nur
Administrations- und Cache-Pfade (`/administrator/`, `/cache/`, `/cli/`,
`/components/`, `/includes/`, `/installation/`, `/language/`, `/libraries/`,
`/logs/`, `/media/`, `/plugins/`, `/templates/`, `/tmp/`) — die Terminansichten
und `/eventdetail/…` sind frei.

Gemessen am 2026-09-24:

- `/eventsnachkategorie/-?limit=100` listet **alle kommenden** Termine,
  aufsteigend ab heute: Seite 1 = 24.09.2026 … 26.11.2026. `limit=100` ist das
  Maximum der Seite (`limit=200` und `limit=0` liefern ebenfalls 100).
- Jede Zeile ist `div.jev_listrow` und trägt in **100 von 100 Fällen** einen
  Google-Kalender-Link mit `dates=20260901T100000/20260901T160000`.
- Die Detailseite trägt den Ortsblock `div.jev-detail__address` mit
  `<br/>`-getrennten Zeilen (Ort / Straße / Stadt / Region / PLZ / Land).
- Das `itemtype="https://schema.org/Event"` der Detailseite ist **unbrauchbar**:
  `startDate` stand bei einem Termin am 24.09.2026 auf `2026-01-03T10:00:00`
  (Verdrehung von Tag und Monat) — die Zeit kommt aus dem Listing.

## Umsetzung

`app/quellen_defaults.py` — neue Konstante `WOCHENMARKT_FLOHMARKT_REGELN`,
registriert in `DEFAULT_REGELN`:

- `listing.url` = `https://www.wochenmarkt-flohmarkt.de/eventsnachkategorie/-?limit=100`
- `horizont_tage: 60` (die erste Seite deckt 63 Tage ab)
- `item_css` = `div.jev_listrow`
- `titel`/`url` aus `a.ev_link_row`
- `start`/`ende` aus `dates=…` im Google-Kalender-Link, `format: '%Y%m%dT%H%M%S'`
- Detail: `ort` = Textknoten 1, `adresse` = Textknoten 2 des Ortsblocks
- **kein `pagination`-Abschnitt** (Begründung unten)

`app/adapters/selector_adapter.py` — Detail-Felder dürfen jetzt auch `xpath`
sein. Der Detail-Pfad filterte bisher auf `css`; ein Block, der seine Werte nur
mit `<br/>` trennt, liefert über CSS den zusammengeklebten Blocktext („Ort
Straße Berlin Berlin 10961 Deutschland http://…“). Der Listing-Pfad kann
`xpath` längst, der Detail-Pfad jetzt auch (`_detail_feld_wert` und der
Vorfilter in `parse_detail`).

## Zwei Fallen, die die Regel umgeht

1. **Deutsche Monatsnamen.** Die Zeile nennt die Zeit nur als Fließtext
   („Dienstag, 01. September 2026 10:00 - 16:00“). `datetime.strptime` liest
   Monatsnamen in der C-Locale; im Projekt ist kein `setlocale` gesetzt. `%B`
   funktioniert für „September“, scheitert aber für „März“, „Mai“, „Oktober“
   und „Dezember“ — also ab dem nächsten Monatswechsel. Die Regel liest
   deshalb den maschinenlesbaren Kalender-Link.
2. **Seitenweise.** `pagination: {param: start}` zählt je Seite um **1** hoch
   (`start=0,1,2…`), die Seite blättert aber in **100er**-Schritten (Seite 3
   endet am 22.04.2028). Der Lauf hätte rund 20 Seiten à 1,7 MB geholt und
   Termine bis 2028 eingelesen (die der Zeitfenster-Filter danach verwirft).
   Ohne `pagination` ruft die Engine dieselbe URL ein zweites Mal ab, sieht
   dieselben Slugs und bricht ab — zwei Abrufe, 100 Zeilen, 63 Tage.

## Tests

`tests/test_wochenmarkt_flohmarkt.py`, 9 Tests, Fixtures
`tests/fixtures/wochenmarkt/listing_kategorie.html` (drei **echte** Zeilen) und
`detail_marheinekeplatz.html`:

- Regel ist prüfbar (`validate_regeln_yaml` == [])
- kein `pagination`-Abschnitt (sonst Blättern bis 2028)
- drei Zeilen werden gelesen, Titel und absolute Detail-URLs vorhanden
- **10:00–16:00 statt 00:00** (sonst gälte der Termin als ganztägig)
- **Monatsnamen-Falle:** derselbe Fixture mit „Oktober“ im Fließtext bei
  unverändertem Kalender-Link muss denselben Start liefern — wer die Regel auf
  `%B` umstellt, fällt hier auf
- ein Termin, der in der Quelle um 00:00 beginnt, bleibt ganztägig (die Regel
  erfindet keine Uhrzeit)
- ohne Kalender-Link gibt es keine erfundene Zeit, sondern eine Warnung
- `ort`/`adresse` aus den Textknoten der Detailseite
- die tragenden Selektoren stehen in der Regel

## Abnahme

- Volle Testsuite: **386 grün, 11 rot** — alle 11 in `tests/test_recherche_*`,
  identisch rot auf einem frischen `git worktree HEAD` (Altlast).
- Live: Quelle anlegen, Regel ausrollen, Lauf starten, Bestand gegen die
  Übersicht zählen. Zahlen stehen in `status.md`.
