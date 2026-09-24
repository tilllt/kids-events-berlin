# 023 — Veranstaltungsuhrzeiten der Quelle Umweltkalender Berlin

**Status:** umgesetzt (2026-09-24); Live-Übernahme und Messung siehe `status.md`.
**Anlass:** Nutzerfund (2026-09-24): „Bei Kinderkram / Umweltkalender stehen
durchaus die Veranstaltungsuhrzeiten drin, aber der Scraper kennt sie nicht.“

## Befund

Die Quelle Umweltkalender Berlin liefert im **Listing** nur das **Datum**:

```html
<div class="grid-item teaser js-grid-item">
  <a href="/angebote/details/17652?dat=2026-09-25">
    …
    <div class="date">Do., 24.09.2026 + weitere Termine</div>
```

Die **Uhrzeit** steht ausschließlich im **Terminblock der Detailseite**, als
Geschwister von Datum und Separator:

```html
<div class="date_detail">
  Freitag, 25. September 2026<div class="separator">|</div>12:00&nbsp;-&nbsp;18:30&nbsp;Uhr<br>
  <div class="zusatzinfo gray fs-14"><strong>immer freitags</strong></div>
</div>
```

Die Regel kannte bisher nur Listing-Felder: `start` kam aus `dat=` in der URL
(Format `%Y-%m-%d`), ein Zeit-Feld gab es nicht. Folge: **jeder** Termin der
Quelle stand ganztägig in der App („00:00 – 23:59“).

**Messung der Formen (2026-09-24, 180 echte Detailseiten):**

| Form | Anzahl |
| --- | --- |
| `HH:MM - HH:MM Uhr` (Spanne) | 155 |
| `HH:MM Uhr` (Beginn ohne Ende) | 8 |
| andere Schreibweise | 0 |
| keine Uhrzeit auf der Seite | 17 |

Die 17 Seiten ohne Uhrzeit gehören zu **vier** Angeboten (Aktionswochen eines
Trägers, Dauerprogramme, „unterschiedliche Anfangszeiten“) — dort ist
„ganztägig“ die richtige Antwort, nicht ein Fehler. In allen 180 Fällen stimmte
das Datum aus `dat=` mit dem Datum im Terminblock überein (kein Auseinander-
laufen von Datum und Uhrzeit).

## Umsetzung

1. **Der Regel-Adapter kann Uhrzeiten auch aus dem Detail lesen.**
   Neue Detail-Felder `zeit` und `ende` (gleiche Konvention wie im Listing:
   `zeit` = Beginn, `ende` = Ende, Format `%H:%M`), Schema in `app/regeln.py`
   (`_DETAIL_FELDER`).
2. **Sie greifen nur, wenn der Listing-Termin wirklich ganztägig ist**, und
   nur für diesen Termin: Termine aus einer Serienliste (`termine_css`)
   bringen ihre Zeit selbst mit und werden nicht überschrieben; einen
   Zeitanteil aus dem Listing ersetzt das Detail nie.
3. **Kein negatives Ende:** liegt das Detail-Ende nicht nach dem Beginn
   (Nachttermin-Schreibweise), bleibt das Ende unbekannt.
4. **Regel in `app/quellen_defaults.py`** (`UMWELTKALENDER_REGELN`) mit
   Anker-Prinzip: Die Zeit muss direkt nach dem Separator `|` stehen und mit
   „Uhr“ enden. Eine hypothetische Form „10:00 bis 13:00 Uhr“ ergibt dann
   **keine** Zeit (Termin bleibt ganztägig) statt einer falsch gelesenen Zahl
   — stille Fehlwerte sind das Schlimmere.
5. **Tests:** `tests/test_umweltkalender_zeit.py` (Regel-Prüfer, echte
   Fixture-Detailseite, alle gemessenen Formen, Überschreib-Schutz,
   Serien-Termin, Nachttermin, unbrauchbarer Wert) und eine neue Fixture
   `tests/fixtures/umweltkalender/detail_17652.html` (echter Auszug).

## Nicht betroffen

- Termine ohne Uhrzeit in der Quelle bleiben ganztägig (Quelleneigenschaft).
- Die Serien-/Dublettenlogik ändert sich nicht; die Kennung eines Termins
  enthält die Uhrzeit, alte ganztägige Zeilen werden vom Lauf als „nicht mehr
  angeboten“ ersetzt (Change 016), also entstehen keine Doppel-Einträge.
- Die Regeln im Betrieb sind eine **Kopie** der `quellen_defaults`: nach dem
  Deploy müssen die Regeln der Quelle per Admin-API aktualisiert und der
  Detail-Cache der Quelle geleert werden (kein neuer Abruf nötig — der Fix
  wirkt auf die bereits gecachten Seiten).
