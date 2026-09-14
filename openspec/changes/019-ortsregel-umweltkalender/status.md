# Change 019 — Ortsname der Quelle Umweltkalender (Anschrift war kein Ort)

**Status:** Regel umgesetzt und gemessen (2026-09-14); Live-Übernahme über die
Admin-API mit Quellenlauf, Beleg unten.

## Warum

Nutzerfund: „Schiff ahoi!“ stand im Ortsfilter mit **„Niederneuendorfer
Allee 81“** — der Anschrift statt des Veranstaltungsorts. Die Detailseite nennt
den Ort sehr wohl:

```html
<strong>Ort/Treffpunkt:</strong><br>
<div>Spandau, Niederneuendorfer Allee 81, 13587 Berlin, Waldschule Spandau</div>
```

Die Regel las das Feld „Ort/Treffpunkt:“ aus der **ganzen Section** und nahm
darin den Straßenteil (`Ort/Treffpunkt: *[^,]+,? *([^,]+)`).

## Größe des Problems (gemessen, nicht geschätzt)

- **818 von 1401** Terminen der Quelle trugen eine Ziffer im Ortsnamen
  (58 %) — Abzug der Live-API `/api/events?quelle=umweltkalender-berlin`,
  2026-09-13.
- Stichprobe von 375 Detailseiten: Anschrift als Ort in **254** Fällen.

## Umsetzung

1. **Der Wert wird dort gelesen, wo er steht:** das `div` direkt nach dem
   Label — `section.veranstaltungsdetail strong:contains("Ort/Treffpunkt:")
   + br + div`. Das verhindert außerdem, dass der Ortsname in die folgende
   „Anfahrt:“-Zeile läuft (beim ersten Umbauversuch genau so passiert und im
   Test festgehalten).
2. **Ortsname statt Anschrift** in vier Alternativen, erste mit Treffer
   gewinnt: `online` → `<Ort>, <Straße>, PLZ` (Name in der Mitte) →
   `<Ort>, PLZ` (Name vor der PLZ, ziffernfrei) → `<Straße>, PLZ, <Ort>`
   (Name nach der PLZ) → wie bisher die Straße als Rettungsnetz.
3. **Die Regel liegt jetzt auch im Repo** (`app/quellen_defaults.py`,
   `UMWELTKALENDER_REGELN`), wie die übrigen Quellen — vorher gab es sie nur in
   der Datenbank, also ohne Test und ohne Nachvollziehbarkeit. Fixture
   (`tests/fixtures/umweltkalender/detail_97972.html`) und Regressionstest
   (`tests/test_umweltkalender_ort.py`, 16 Fälle) gehören dazu.
4. **Treffpunkt-Hinweise sind keine Orte:** „Wir kommen zum Ausgangspunkt
   zurück.“, „Weitere Informationen …“, „Raum 118“, „Vorplatz“, „Kasse“ fallen
   durch eine Liste in den Alternativen heraus. Klein geschriebene Hinweise
   („am Jahn-Denkmal“, „vor dem großen Parkplan“) fallen schon dadurch heraus,
   dass ein Ortsname groß beginnt.

## Verifiziert

- Vielfalt der Quelle über 654 Detailseiten geprüft; die Reihenfolge der
  Alternativen wurde an **375** echten Werten zweimal verglichen
  („Name vor der PLZ“ zuerst vs. „Name nach der PLZ“ zuerst): 125 statt 254
  Anschriften, **kein** vorher sauberer Name wurde zur Anschrift, **kein**
  Termin verlor seinen Ortsnamen.
- 16 neue Tests grün (Regel-Prüfer, echter Seitenauszug, 12 echte Messwerte).

## Grenzen (ehrlich)

- Straßennamen **ohne** Hausnummer sind von einem Ortsnamen nicht zu
  unterscheiden („Altonaer Straße/Klopstockstraße“, „Hobrechtsfelder
  Dorfstraße“) und bleiben stehen.
- Nennt die Quelle nur eine Anschrift, bleibt die Straße der Ortsname — die
  Adresszeile trägt weiterhin die Geokodierung.
- Unter-Orte innerhalb eines benannten Orts („Britzer Garten“ → „Parkeingang
  Mohriner Allee“) werden bewusst **nicht** bevorzugt: der Name vor der PLZ
  gewinnt, weil er der bekanntere Ort ist.

## Nach dem Lauf gemessen (live, 2026-09-14)

- Anschrift im Ortsnamen: **818 → 449** von 1350 Terminen.
- Ortsname fehlt („Ohne Angabe"/„Berlin"): 15 → 14.
- Echte Ortsnamen stehen jetzt im Ortsfeld, z. B. „OTTO Textilwerkstatt",
  „Tempelhofer Feld", „Gartenarbeitsschule Lichtenberg", „Leopoldplatz".
- Der gemeldete Fall selbst ist live nicht mehr prüfbar — „Schiff ahoi!" lief
  nur am 13.09. und ist mit Change 016 als vergangener Termin entfernt worden.
  Der Regressionstest führt den Fall an der echten Fixture-Detailseite:
  `tests/test_umweltkalender_ort.py::test_ort_und_adresse_aus_echter_detailseite`.

## Nachtrag — Bezirksnamen aus der Detailseite (2026-09-14)

Die Messung nach dem Lauf zeigte einen **zweiten** Weg ins Ortsfeld: **185 von
1350** Terminen standen mit „Friedrichshain-Kreuzberg", „Mitte" & Co. als Ort.

Ursache: Bei manchen Angeboten nennt die Quelle nur „<Bezirk>, <PLZ> Berlin" —
keine Straße, keinen Namen. Die Prüfung „Bezirksname ist kein Ort" sah nur das
Feld der Übersichtsseite an; das erst danach gelesene Detail-Feld wurde
ungeprüft übernommen und überschrieb das Ergebnis.

- Die Prüfung gilt jetzt für **jede** Quelle der Ortsangabe (Übersicht,
  Detail, feste Vorgabe); der Bezirksname wandert weiterhin in den Bezirk —
  aus jedem Ortsfeld, damit keine Information verloren geht.
- Debugging-Befund am Rande: Ein erster Versuch, den Wert einfach zu verwerfen,
  ließ den Bezirk auf `None` fallen — deshalb wandert er weiterhin in `bezirk`.
- „vielerorts" (89 Termine) ist in `app/orte.py` als generische Angabe
  aufgenommen — wie „verschiedene Orte": kein Ort, keine Geokodierung.

**Offen, dem Nutzer zur Entscheidung:** „vielerorts" (89) und „online" (34)
stehen weiterhin als Werte in der Orts-Auswahlliste, weil `Store.list_orte`
generische Angaben nicht ausschließt. Das ist eine Produktentscheidung (will
man „online" filtern können?), nicht offensichtlich ein Fehler.
