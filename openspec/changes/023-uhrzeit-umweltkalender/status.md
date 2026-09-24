# Change 023 — Uhrzeit aus der Übersicht/Detailseite statt „ganztags“

Stand 2026-09-24 (abgeschlossen, live gemessen)

## Ausgangslage

Nutzerfund: „Bei Kinderkram / Umweltkalender stehen durchaus die
Veranstaltungsuhrzeiten drin aber der scraper kennt sie nicht."

Bestand vorher: **1144 von 1232** Terminen der Quelle `umweltkalender-berlin`
ganztägig, nur 88 mit Zeit (7 %).

## Zwei Ursachen

1. **Regel-Lücke (Übersicht).** Die Uhrzeit steht bei vielen Angeboten schon in
   der Listing-Karte (`div.date`: „09:30 - 16:30 Uhr"; gemessen 1265 von 3095
   Datumsfeldern der Filterliste). `UMWELTKALENDER_REGELN` hatte **kein**
   Listing-Feld `zeit`/`ende` — der Wert wurde verworfen. Karten ohne Zeit
   (z. B. Bauernmarkt: nur „Do., 24.09.2026") tragen sie nur im Detail
   (`div.date_detail`, 180 geprüfte Detailseiten: 155× Spanne, 8× Einzelzeit,
   17 Seiten ohne Zeit aus nur 4 Dauerprogrammen).
2. **Dedup-Falle.** `Store.entferne_ueberlappende_zwillinge` gruppiert nach
   Titel+Ort und behält je Überlappungskette den **frühesten** Start. Der alte
   ganztägige Satz desselben Tages (00:00–23:59) stand vor dem neu gelernten
   Termin mit Uhrzeit (10:00–16:00) und blieb stehen; der Termin MIT Zeit wurde
   als „überlappender Zwilling" gelöscht. Messung live: Lauf schrieb 976 Termine
   neu, **777 davon sofort wieder entfernt**, Bestand unverändert ganztägig.

## Änderungen

- `app/quellen_defaults.py`
  - `UMWELTKALENDER_REGELN`: Listing-Felder `zeit`/`ende` (`div.date`,
    Anker „Uhr"), Detail-Felder `zeit`/`ende` (`div.date_detail`) bleiben als
    Rückfall; Detail greift nur, wenn der Listing-Termin ganztägig ist.
  - `INDUSTRIEKULTUR_REGELN` neu im Repo (vorher nur in der DB) + Detail-Felder
    `zeit`/`ende` (`h2.bzi-color-1`, Form „Do., 24.09.2026 | 10:00 Uhr";
    gemessen 40 von 40 ganztägigen Terminen haben dort eine Zeit).
- `app/store.py` — `entferne_ueberlappende_zwillinge`: neue Tages-Regel.
  Gleicher Tag, ein ganztägiger Platzhalter gegen einen Eintrag MIT Uhrzeit →
  Platzhalter geht. Berührende Zeitfenster (ZLB 09–10/10–11) und überlappende
  Serienkopien bleiben unangetastet.
- Tests: `tests/test_umweltkalender_zeit.py` (+3 Listing-Fälle, 18 gesamt),
  `tests/test_industriekultur_zeit.py` (neu, 13), `tests/test_serien_zwillinge.py`
  (+4 Tages-Dubletten-Fälle), Fixture `tests/fixtures/industriekultur/`.

## Messung live (nach Deploy + Regel-Ausrollung)

| | vorher | nachher |
|---|---|---|
| Termine der Quelle | 1232 | 1233 |
| ganztägig | 1144 | **266** |
| mit Uhrzeit | 88 (7 %) | **967 (78,5 %)** |

Lauf 367: `status ok`, 2914 Termine, 880 neu, 3 geändert, **0 Fehler**.
Beispiele: Bauernmarkt Wittenbergplatz 10:00–16:00, Ökomarkt am Kollwitzplatz
12:00–19:00, BSR-Kieztag 13:00–18:00. Deploy
`37yanufszfcche0d0ut848p9`, Commit `4c7e7e9`.

## Offen (ehrlich benannt)

Von 30 geprüften Restseiten zeigen 14 irgendwo eine Uhrzeit — überwiegend aus
„Weitere Termine"-Listen **anderer** Tage (z. B. „morgen Fr., 13.11.2026 |
15:00 - 20:00 Uhr"), also kein Fehler des Termins. Ein echter Rest bleibt:
Termine, deren Zeit nur in der Terminliste des Details zu einem bestimmten Datum
steht (Beispiel „10 Jahre Verkehrswende" 24.09. 18:00–20:00, in der DB
ganztägig). Vor einer weiteren Änderung erst messen, wie viele der 266 wirklich
eine Zeit für IHR Datum haben — die Krude Textsuche zählt Fremdtermine mit.

## Quellen-Audit (gleicher Anlass)

40 ganztägige Termine je Quelle ab heute, Quellseite abgerufen:
`industriekultur-berlin` 40/40 mit Zeit (gefixt) · `jup-berlin` 0/40 (korrekt
ganztägig) · `familienportal` 34/40 ohne Zeit, 2 Treffer nur Fließtext,
4 veraltete Links · `museumsportal` Treffer = Öffnungszeiten · `kinderkultur-
kalender` Quelle schreibt selbst 00:00–23:59 · `dvn-berlin` Treffer fremder
Termin · `bwb-veranstaltungen` Datenfehler (01.01.2000), kein Zeitproblem.
