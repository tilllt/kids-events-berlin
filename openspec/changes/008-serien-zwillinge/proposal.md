# Change 008: Überlappende Serien-Zwillinge einer Quelle zusammenfassen

**Status:** In Arbeit (2026-09-12)
**Basis:** Change 002/004 (Serien-Termine), Change 005 (manuell-Schutz)

## Why

Realer User-Befund (2026-09-12): Der Ferienworkshop „Wie kommt das Milchhäuschen
am Weißen See zu seinem Namen?“ (MAXIM) steht **13× im Bestand** mit
täglich verschobenen, überlappenden Spannen:

```
09.09.2026 10:00 – 13.09.2026 16:00
10.09.2026 10:00 – 14.09.2026 16:00
…
21.09.2026 10:00 – 25.09.2026 16:00
```

Ursache ist die QUELLE, nicht unser Parser: jup.berlin führt für ein mehrtägiges
Event mehrere „Veranstaltungstermin/e“-Einträge, die je um einen Tag verschoben
dieselbe Spanne wiederholen (Detailseite: 08.–12.09., 09.–13.09., 10.–14.09.,
11.–15.09., 12.–16.09.). Unser Adapter erzeugt pro Eintrag ein Event
(`slug#start`) — bei jedem Tageslauf kommt eine weitere Variante dazu, und die
alten bleiben bis Start+3 Tage liegen. Jeder Eintrag ist einzeln korrekt, in
Summe entsteht ein Stapel überlappender Kopien (Liste wie Karte).

Gemessener Umfang im Produktionsbestand (1.493 Events): 9 Überlappungs-Klumpen,
22 überzählige Einträge — 8 Klumpen bei `jup-berlin`, 1 bei `zlb`.

Abgrenzung: **echte Serientermine sind KEINE Dubletten**. Aufeinanderfolgende
Slots derselben Veranstaltung (ZLB „U-16-Wahllokal“ 09–10, 10–11, 11–12 Uhr;
Weinmeisterhaus „Textilwerkstatt“ 15:30–17:00 und 17:00–19:00) berühren sich
nur und bleiben getrennt. Ebenso mehrere parallel laufende Angebote mit
gleichem Titel an verschiedenen Orten (Ort ist Teil des Schlüssels).

## What Changes

### Store: `entferne_ueberlappende_zwillinge(quelle)`

- Gruppiert die Events EINER Quelle nach `(lower(titel), lower(ort))` und
  fasst Ketten mit **echter Überlappung** zusammen
  (`start_kette < ende_letztes`, wobei ein fehlendes `ende` als Starttag
  gilt — sonst würden eintägige Events fälschlich kollabieren).
- Behält je Kette den Eintrag mit dem **frühesten Start** (bei jup ist das der
  ursprüngliche Termin; die verschobenen Kopien sind die späteren), löscht die
  übrigen und gibt die gelöschten Datensätze zurück.
- `manuell = 1`-Events sind ausgenommen (Admin-Pflege gewinnt, wie beim
  Zwilling-Dedup und beim Scrape-Schutz).

### Pipeline

- Nach dem Event-Upsert und vor der Stale-Bereinigung wird die Bereinigung für
  die gescrapte Quelle aufgerufen. Damit räumt der erste Lauf nach dem Deploy
  die vorhandenen Altlasten mit weg — und jeder weitere Lauf verhindert das
  Wiederauftreten.
- Ergebnis: `n_zwillinge_entfernt` im Lauf-Summary plus Logzeile
  `[dedup] <quelle>: N überlappende Serien-Zwillinge entfernt`.

## Nicht-Ziele

- **Keine** quellenübergreifende Zusammenführung (z. B. dasselbe Event aus
  jup und familienportal bleibt zwei Einträge — das ist die bestehende
  Zwilling-Logik für identische Titel+Start+Ort und ein eigenes Thema).
- Keine Gleichverteilung „ein Event pro Tag“ für tägliche Kurse
  (familienportal listet 18 Einzeltage ohne Spanne; die sind nicht
  überlappend und bleiben wie sie sind).
- Keine Änderung an Adaptern — die Bereinigung läuft generisch auf dem
  Bestand der jeweiligen Quelle.

## Tests

- Store-Test: überlappende Ketten werden auf den frühesten Eintrag reduziert;
  berührende Slots (ende == start) bleiben; unterschiedliche Orte bleiben;
  `manuell=1` bleibt.
- Pipeline-Test (offline): ein Fixture-Lauf mit zwei überlappenden Kopien
  hinterlässt genau einen Eintrag und meldet `n_zwillinge_entfernt`.
- Regression: Museumsportal-Serien (nicht überlappende Einzeltermine) bleiben
  unverändert.
