# Change 011 — Status (Verifikation 2026-09-13)

## Produktivmessung (kinderkram.cia-spandau.de, öffentliche API)

| Kennzahl | vorher | nachher |
|---|---|---|
| Events im Bestand | 1.733 | **1.443** (−290) |
| Davon Dubletten-Gruppen (Admin-Bericht) | 254 | 0 (nach dem Lauf) |
| Klax-TdOT-Zeilen | 57 (29 fam + 28 KKK) | **32** |
| Klax Kinderkrippen-Zeilen | 22 (11 + 11) | **12** (11 + 1) |
| Verdachtsfälle (nicht gemergt) | — | 168 (sichtbar im Bericht) |

Angewendet über `POST /api/admin/dedupe/anwenden`:
`{gruppen: 254, entfernt: 290, felder_ergaenzt: 321, verdacht: 168}`.

**Feldauffüllung belegt:** 321 leere Felder des Kanons wurden aus den Dubletten
gefüllt — u. a. die Endzeiten, die nur eine der beiden Quellen lieferte.

**Provenienz belegt:** 254 Events tragen `quellen_json` mit den weiteren
Quellen (Stichprobe: „Kreativer Kindertanz" bleibt bei familienportal,
kinderkulturkalender als weitere Quelle mit Fund-URL).

**Quellen-Bilanz (keine Quelle verlor eigene Termine, nur Doppelzeilen):**

| Quelle | vorher | nachher |
|---|---|---|
| familienportal | 964 | 954 |
| museumsportal | 356 | 268 |
| kinderkulturkalender | 218 | 87 |
| jup-berlin | 142 | 84 |
| zlb | 21 | 18 |
| gaerten-der-welt / tempelhoferfeld / suedgelaende / britzer-garten | 8/8/6/3 | unverändert |
| berlin-senbjf-kalender | 3 | unverändert |
| manuell | 4 | unverändert (nie gelöscht) |

## Tests

`202 → 207` grün (26 s). Neu in diesem Change:
- Identitätsregeln: Klax-Fall (generischer Ort, abweichende Endzeit) wird gemergt.
- **ZLB-Schutz:** verschiedene Titel am selben Ort zur selben Zeit → kein Merge.
- **Stundenblöcke:** gleicher Titel 09/10/11 Uhr → kein Merge, Verdachtsfall.
- **Zwei Orte:** gleicher Titel in zwei Sternwarten → kein Merge.
- Provenienz, Feldauffüllung, Kanon-Priorität, Idempotenz, Probelauf,
  manuell gepflegte Sätze bleiben.
- Regressionen aus dem Feldlauf: dreckige Website-URLs aus dem Schul-Stamm
  (Steuerzeichen) und eine kaputte Schule stoppen den Recherche-Lauf nicht mehr.

## Offene Restschuld (ehrlich)

1. **Titelvarianten mit Füllwörtern** bleiben getrennt (Klax: 32 statt 29
   Zeilen). Fix wäre eine Füllwort-Normalisierung in `dedupe.titel_norm`
   (und/der/die/im/in/am/an) — bewusst nicht in diesem Change, weil das die
   Mergeschwelle senkt.
2. **Provenienz ist noch nicht in der öffentlichen API:** `quellen_json` steht
   in der Admin-Ansicht (254 Events), `/api/events` liefert das Feld noch nicht
   — die UI kann „auch gelistet bei …" daher noch nicht zeigen.
3. **Zeit-Toleranz fehlt bewusst:** abweichende Startzeiten bei gleichem
   Titel/Tag/Ort landen als Verdacht (168 Fälle), nicht im Merge.
4. Der nächste reguläre Scrape-Lauf ruft `merge_doppelte_events()` erneut auf;
   erwartet wird `entfernt = 0` (Idempotenz-Beleg im Lauf-Log).
