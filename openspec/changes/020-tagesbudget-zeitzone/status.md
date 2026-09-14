# Change 020 — Tagesbudget der Web-Suche rechnete in zwei Zeitzonen

**Status:** behoben, Test festgehalten (2026-09-14).

## Befund

Der Test `tests/test_recherche_websuche.py::test_tagesbudget_stoppt_und_nennt_die_zahlen`
war rot („DID NOT RAISE“) — und er hatte recht: **das Tagesbudget der
Brave-Websuche griff nicht.**

Ursache, gemessen nachgestellt (`websearch.status` gegen `store.brave_verbrauch`):

- `Store.brave_verbrauch` stempelt und zählt Aufrufe im **Berliner** Datum.
- `websearch.status(..., heute=...)` bekam `date.today()` — die **Systemzeit**
  des Containers. Läuft der Container in UTC, weichen beide Daten zwischen
  00:00 und 02:00 Berliner Zeit (bzw. 22:00–24:00 UTC) auseinander: die
  Tageszählung fand **0** Aufrufe, das Budget von z. B. 30/Tag konnte nicht
  erreichen und die Suche lief weiter — gegen echtes Guthaben.

Zweite Stelle derselben Ursache: `zuletzt_gesucht` verglich den in **UTC**
gespeicherten Zeitstempel direkt gegen „heute“ und meldete „vor 1 Tagen“
statt „vor 0 Tagen“, wenn die Uhr gerade über Mitternacht Berliner Zeit stand.

## Änderung

- Neue Funktion `websearch.heute_berlin()` — **eine** Quelle für „heute“.
  `monat()`, `zuletzt_gesucht` und der Vorgabewert `BraveSuche(heute_fn=…)`
  benutzen sie; `date.today()` ist aus dem Modul verschwunden.
- Der gespeicherte UTC-Zeitstempel wird für das Alter über
  `.astimezone(TZ_BERLIN).date()` in Berliner Zeit ausgewertet.
- Gleiche Ursache nebenan: `app/schul_import.py` nahm für „heute“ die
  Systemzeitzone (`.astimezone()`) — jetzt `TZ_BERLIN`.

## Verifiziert

- Neuer Test `test_tageszaehler_und_verbrauch_rechnen_in_berliner_zeit`:
  Tageszähler und Verbrauch müssen **dasselbe** Datum benutzen, und der
  Vorgabewert der Suche muss die Berliner Uhr sein. Er gilt zu jeder Uhrzeit
  (vorher war der Fehler nur nachts sichtbar — genau deshalb blieb er lange
  unbemerkt).
- `test_tagesbudget_stoppt_und_nennt_die_zahlen` ist grün: der zweite Aufruf
  wird mit „Tagesbudget erreicht (1/1 Anfragen)“ abgewiesen.
- `test_wiederholung_schuetzt_das_kontingent` grün (wieder „vor 0 Tagen“).

## Wirkung in Produktion — gemessen, nicht behauptet

Die laufende Instanz läuft in Berliner Zeit: eine Testsuche über
`POST /api/admin/brave/test` um 01:55 Berliner Zeit wurde korrekt als
„heute“ gezählt (`verbraucht_heute: 1`, Tag 2026-09-14). Der Fehler traf also
Umgebungen mit UTC-Systemzeit (hier: Entwicklungscontainer und die
Testumgebung) — dort war der Schutz nachts wirkungslos. Die Änderung entfernt
die Abhängigkeit von der Systemzeitzone vollständig.
