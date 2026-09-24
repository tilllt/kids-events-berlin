# Change 026 — BWB-Veranstaltungen: Uhrzeit wurde abgeschnitten

Status: Vorschlag (2026-09-24)
Anlass: Abschluss-Check über alle Quellen (offener `anomalie-0-events`-Fall)

## Anlass

Abschluss-Check über alle 17 Quellen: **`bwb-veranstaltungen`** (Berliner
Wasserbetriebe) war die einzige Quelle mit `status != ok` —
`anomalie-0-events`, seit Wochen jeden Morgen.

Zwei getrennte Befunde, die auseinandergehalten werden müssen:

1. **Die Quelle ist derzeit wirklich leer.** Die Seite
   `https://www.bwb.de/de/veranstaltungen.php` listet 23 Termine, **alle in der
   Vergangenheit** (neuester 13.09.2026); die Berliner Wasser-Mobil-Tour läuft
   Mai bis September. `anomalie-0-events` ist hier also **richtig** — anders als
   bei `industriekultur-berlin`, wo dieselbe Meldung ein 301-Umzug auf eine
   Seite ohne Termine war (Change 024).
2. **Die Regel hatte einen latenten Fehler**, der erst beim Saisonstart 2027
   sichtbar geworden wäre.

## Der Fehler

`info-begin` trägt Datum **und** Uhrzeit:

```html
<div class="info-begin" style="display:none">2026-05-09 12:00:00</div>
```

Die Regel las daraus nur den Datumsteil und formatierte ihn:

```yaml
start: {css: '.info-begin', regex: '([0-9]{4}-[0-9]{2}-[0-9]{2})', format: '%Y-%m-%d'}
```

`datetime.strptime` baut daraus 00:00 — **jeder** Termin der Quelle wäre als
ganztägig in die App gekommen, obwohl die Quelle die Uhrzeit nennt. Genau die
Fehlerklasse aus Change 023/024, nur eine Quelle weiter.

## Umsetzung

`app/quellen_defaults.py` — neue Konstante `BWB_REGELN` (die Quelle existierte
bisher **nur in der Produktions-DB**, ohne Repo-Vorlage) und Eintrag in
`DEFAULT_REGELN`:

```yaml
start: {css: '.info-begin', regex: '([0-9]{4}-[0-9]{2}-[0-9]{2})', format: '%Y-%m-%d'}
zeit:  {css: '.info-begin', regex: '([0-9]{2}:[0-9]{2})', format: '%H:%M'}
ende:  {css: '.info-end',   regex: '([0-9]{2}:[0-9]{2})', format: '%H:%M'}
```

**Bewusst getrennte Felder statt eines Formats `'%Y-%m-%d %H:%M:%S'`:** einzelne
Einträge der Seite haben GAR KEINE Uhrzeit (`2024-04-28`). Ein Format, das die
Uhrzeit verlangt, würde solche Zeilen vollständig verwerfen. So bleiben sie
ganztags, statt zu verschwinden — „keine Angabe statt raten“ und keine
stille Lücke.

## Tests

`tests/test_bwb_veranstaltungen.py`, 4 Tests, Fixture
`tests/fixtures/bwb/listing.html` (zwei **echte** Einträge: einer mit, einer
ohne Uhrzeit):

- Regel ist prüfbar (`validate_regeln_yaml` == [])
- 12:00–19:00 statt 00:00 — also nicht ganztägig
- der Eintrag OHNE Uhrzeit bleibt erhalten, ist ganztägig und bekommt das
  Tagesende 23:59 (nicht None, nicht 00:00)
- **Gegenprobe:** mit dem alten Feldaufbau (ohne `zeit`) kommt 00:00 heraus —
  der Test beweist also, dass die Änderung wirkt

## Abnahme

- Volle Testsuite: **390 grün, 11 rot** (dieselben datumsgebundenen Altlasten in
  `tests/test_recherche_*`, identisch rot auf einem frischen `worktree HEAD`).
- Live: Regel ausrollen, Lauf starten. Die Terminzahl bleibt **0**, und das ist
  das erwartete Ergebnis (Saison vorbei) — die Prüfung ist, dass der Lauf `ok`
  bleibt und die Regel gegen die Repo-Vorlage stimmt. Zahlen in `status.md`.
