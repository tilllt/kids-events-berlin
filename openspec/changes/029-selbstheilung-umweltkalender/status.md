# Status — Change 029 (27.10.2026)

## Ergebnis

Der Umweltkalender lässt sich jetzt reparieren — und ist repariert.

| | vorher | nachher |
|---|---|---|
| Auslesefehler je Lauf | 998 (499 Blöcke × 2 Seiten) | **0** |
| Heilungsfälle | 7 × `fehlerquote`, alle `verworfen` | 1 × `angenommen` (`nur_mit`) |
| Gate-Grund | „1.175 Treffer heute (Grenze 200)" | entfällt (Klassen-Selektor) |
| Termine im Bestand | 2.533 | 2.532 (unverändert im Tagesgang) |
| Laufzeit | 118 s | 563 s (einmalig: Detail-Cache neu gefüllt) |

## Belege

- `heilungen` id 27: `art=fehlerquote`, `status=angenommen`,
  `verursacher=manuell`, `erwartete_treffer=1175`, Beleg
  `nur_mit=a[href*="dat="]`, `fehler_vorher=499`, `fehler_nachher=0`.
- Gespeicherte Regel enthält `nur_mit: a[href*="dat="]` neben
  `item_css: div.grid-item.teaser`.
- Lauf 935 (06:18 UTC, nach der Übernahme): `status=ok`, `n_fehler=0`,
  **keine** Zeile in `errors` nach dem Startzeitpunkt; Lauf 932 (04:35) hatte
  die `Item N: start: kein Wert extrahiert`-Zeilen (je zweimal, zwei Seiten).
- Container-Log: `[heilung] umweltkalender-berlin: Blöcke ohne Termin-Merkmal
  aussortiert (499 → 0 Fehler, 1175 Treffer)`.

## Tests

- 8 neue Tests (`tests/test_selbstheilung_itemfilter.py`), alle grün.
- Betroffene Suiten: 115 passed (`test_selbstheilung*`, `test_selector_adapter`,
  `test_admin_api`).
- Gesamtlauf: 427 passed, 12 failed — die bekannten roten
  `test_recherche_*`/`test_schul_import` (u. a. festes Datum 15.10.2026, heute
  Vergangenheit); keine davon berührt diese Änderung.

## Offen

- Laufzeit der Quelle beobachten: der erste Lauf nach der Änderung füllte den
  Detail-Cache neu (563 s). Bleibt sie dauerhaft hoch, ist der `nur_mit`-Filter
  nicht die Ursache, sondern die Zahl der Detailseiten — dann Rate-Limit prüfen.
- `nur_mit` ist bisher nur beim Umweltkalender im Einsatz; andere Quellen mit
  gemischten Kacheln (bwb-veranstaltungen?) wurden nicht angefasst.
