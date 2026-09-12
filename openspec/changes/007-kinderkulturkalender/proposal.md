# Change 007: Quelle Kinderkulturkalender Berlin (LKJ)

**Status:** In Arbeit (2026-09-12)
**Basis:** Change 002 (Selector-Engine), Change 004 (Serien-Termine)

## Why

Der User fragt nach `https://www.kinderkulturkalender-berlin.de/` und will sie
aufnehmen. Die bisherige Audit-Notiz („nicht aufnehmen, läuft über die
jup!-Datenbasis“) ist **falsch**: Es ist eine eigene Drupal-10-Seite der LKJ
Berlin e.V. mit eigener Datenbank (`/angebot/<slug>`-Knoten, eigene Felder
`field-event-date`, `field-location`, `field-event-link`, `term-categories`).

Nachgemessen am 2026-09-12 (Startseiten-Listing, 186 Angebote, Abgleich über
Titel-Token gegen den eigenen Bestand):

- **21-Tage-Fenster:** 94 Angebote, davon 91 (97 %) schon im Bestand — aber
  87 über `familienportal` und nur 4 über `jup-berlin`. Der Überschneidungs-
  partner ist der Familienportal-Aggregator, nicht jup.
- **ab +22 Tagen:** 78 Angebote, davon 4 im Bestand — der Oktober-/Ferien-
  Vorlauf (KinderKulturMonat, CABUWAZI-Shows, Zirkusferien) ist unser
  blinder Fleck; nur durch unser 21-Tage-Fenster begrenzt, nicht exklusiv.

Zusatznutzen der Quelle: kuratierte LKJ-/KinderkulturMonat-Termine,
Preisangabe (inkl. ermäßigt) und vollständige Veranstaltungsadresse.

## What Changes

### Regel-Adapter (Stufe 2, kein pro-Quelle-Code)

- `listing.url: https://www.kinderkulturkalender-berlin.de/startseite`
  (Drupal-Views-Masonry, 186 Karten; keine Pagination),
  `item_css: div.masonry-item.views-row article.node--type-offer`,
  `horizont_tage: 21` (Projekt-Vorgabe „nur 3 Wochen in die Zukunft“).
- Listing-Felder: `titel` (`h3 .field--name-title`), `url`
  (`a.offer__wrapper[href]`, relativ → Engine joint gegen die Listing-URL),
  `start` (erste `TT.MM.JJJJ` im `div.field--name-field-event-date`).
  Zeiten stehen NICHT im Listing, sondern erst im Detail („Termine“) —
  deshalb `detail`.
- Detail-Felder: `beschreibung_kurz` (`.field--name-body`, voller Text statt
  Listing-Teaser), `ort` (`div.field--name-field-location .field--name-title`),
  `adresse` (`.field--name-field-location .field--name-field-address`),
  `termine_css: "div.dates .field--name-field-event-date .field__item"`.
- Der `field-organizer` des Listings wird bewusst NICHT als `ort` gemappt
  (Veranstalter ≠ Veranstaltungsort); der Ort kommt aus dem Detail.

### Engine-Erweiterungen (generisch, nicht KKK-spezifisch)

1. **`termine_css`-Textform „TT.MM.JJ, HH:MM - TT.MM.JJ, HH:MM“**: Die
   bestehende Serien-Erkennung erwartet `li` mit zwei Spans (deutsches Datum
   + Uhrzeit, Museumsportal). KKK liefert die Termine als Textknoten in
   `div.field__item` („20.09.26, 11:00 - 20.09.26, 12:30“). Der Parser
   verarbeitet jetzt beide Formen: erst Span-/Monatsname-Weg, sonst
   Datums-/Zeitpaare aus dem Elementtext (2-stellige Jahre → 20YY,
   fehlende Uhrzeit → ganztägig). Zeiten sind Berliner Lokalzeit.
2. **`detail.termine_autoritativ: true`** (optional, Default false): Sind
   Serien-Termine vorhanden, wird das Listing-Row-Event NICHT zusätzlich
   gebaut. Nötig, weil das KKK-Listing nur ein Datum (teils als Spanne) ohne
   Uhrzeit trägt — das Row-Event wäre sonst ein zusätzlicher ganztägiger
   Phantom-Termin neben den echten Terminen.

### Quelle in Produktion

- quelle `kinderkulturkalender`, typ `regeln`, aktiv, `rate_limit_s: 1.0`,
  `horizont_tage: 21`, robots-Vermerk (nur `/admin`, `/core`,
  `/profiles`, `/search`, `/user/*` disallowed — `/startseite` und
  `/angebot/` erlaubt). Anlage über die Admin-API, KEIN Deploy nötig.
- `/rss.xml` existiert, hat aber 0 Items → keine Stufe-1-Quelle.

## Nicht-Ziele

- Kein Aufbohren des Horizonts für diese Quelle (bleibt 21 Tage wie alle
  anderen). Wenn der Ferien-Vorlauf gewünscht ist, ist das eine eigene
  Entscheidung → `horizont_tage` in der Quelle ändern.
- Keine Übernahme der Karten-Taxonomie (`field-term-categories` liefert nur
  Icon-Klassen ohne Text); Tags entstehen wie bisher über `enrich.py`.
- Kein Scrapen der Merkliste/„Alle Daten anzeigen“-JS-Funktion (die Termine
  stehen vollständig im HTML).

## Tests

- Fixture `tests/fixtures/kinderkulturkalender/listing.html` (echte
  Startseite, 2026-09-12) + `detail.html` (echte Angebotsseite mit Terminen,
  Preisen und Veranstaltungsort).
- Regel-Validierung, Listing-Parse (Pflichtfelder, Ort/Zeit-Verhalten),
  Detail-Parse (Ort/Adresse/Beschreibung, `_termine` aus der Textform) und
  `zu_events` mit `termine_autoritativ` (kein Phantom-Row-Event).
- Textformen-Parser separat (`TT.MM.JJ, HH:MM - TT.MM.JJ, HH:MM`,
  Einzeltermin, datumslos → verwerfen).
