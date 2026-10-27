# Change 029 — Selbstheilung repariert den Umweltkalender (Blöcke ohne Termin)

Status: in Arbeit (Nutzerauftrag 2026-10-27: „checke, warum das kinderkram
autohealing den Umweltkalender nicht reparieren kann. Erweitere das autohealing
so, dass es Umweltkalender reparieren kann.")

## Befund (live, 27.10.2026)

Die Quelle `umweltkalender-berlin` läuft technisch (`status=ok`, 961 Termine im
Bestand, täglich 20–35 neu), aber die Selbstheilung dreht sich im Kreis:

- `heilungen` enthält seit dem 22.10. sieben Einträge für diese Quelle, **alle
  `art=fehlerquote`, alle `status=verworfen`**.
- Jeder Befund lautet „998 von 1935 gelesenen Zeilen sind fehlerhaft (998 davon
  beim Auslesen der Listing-Blöcke)"; je Lauf ~499 Blöcke, zwei Seiten.
- Die Modell-Vorschläge sind **inhaltlich korrekt, aber wirkungslos**: sie
  schlagen genau die Regel vor, die schon gespeichert ist
  (`item_css: div.grid-item.teaser`) — die Selektoren sind ja nicht kaputt.
- Abgelehnt wurden sie an genau einer Prüfung: „Kein absurd grober Selektor:
  1.175 Treffer heute (Grenze 200)". Das Gate verwechselt einen großen Kalender
  mit einem Wildcard-Selektor.

**Ursache der 998 Fehler** (am HTML gemessen, 2,1 MB, 1.674 Kacheln):
1.175 Kacheln tragen einen Datums-Link (`/angebote/details/…?dat=2026-10-27`),
499 nicht — das sind Dauer-Angebote („Ausstellung", „Ausflugsziel",
„Beratung") im **gleichen** Karten-Layout. Ohne Datum scheitert `start`
(`Item N: start: kein Wert extrahiert`). Die Regel ist also nicht falsch, sie
greift nur zu breit.

## Was gebaut wird

1. **`listing.nur_mit`** (Schema, Engine, Admin-Validierung): ein CSS-Selektor,
   den jeder Termin-Block enthalten muss. `SelectorAdapter.parse_listing`
   filtert danach; bleibt nichts übrig, steht das als Warnung in der Queue
   (kein stiller Nulltreffer).
2. **Deterministische Reparatur** `itemfilter_reparieren()`: leitet den Filter
   aus dem Start-Feld ab (Text vor der ersten Regex-Gruppe —
   `dat=(…)` → `a[href*="dat="]`), prüft ihn durch dasselbe Gate wie ein
   Modell-Vorschlag und übernimmt nur, wenn die Zahl der Auslesefehler
   nachweislich sinkt (`fehler_vorher` → `fehler_nachher` im Beleg).
   Läuft vor dem Modellaufruf, wie die Filtergruppen-Reparatur aus Change 028.
3. **Gate-Fix beim „absurd groben Selektor"**: die Grenze 200 bleibt, gilt aber
   nur noch für Selektoren **ohne** Klassen-, ID- oder Attribut-Merkmal
   (`div`, `*`, `div div`). Ein Selektor, der ein wiederkehrendes Element
   beschreibt, darf 1.500 Treffer haben — das steht als Warnung im Beleg.
   Der Wildcard-Schutz selbst bleibt (Test: `item_css: div` bei 300 Blöcken
   wird weiter abgelehnt).
4. **Prompt**: `nur_mit` ist als Listing-Option genannt, damit das Modell es
   ebenfalls vorschlagen kann.

## Nicht geändert

- Erkennung und Schwellen (30 %, 10 Fehler) bleiben.
- Ein Rückgang der Trefferzahl bleibt kein Defekt.
- Keine neue Domain, kein Code aus dem Modell.

## Tests

- Ableitung: `dat=([0-9]{4}-…)` → `a[href*="dat="]`; ohne literales Merkmal
  oder ohne Regex kein Kandidat.
- Engine: ohne `nur_mit` 30 Termine + 30 Fehler, mit `nur_mit` 30 Termine und
  0 Fehler.
- Gate: 1.500 Treffer mit Klassen-Selektor grün (mit Warnung), 300 Treffer mit
  `div` rot.
- Reparatur: übernimmt `nur_mit`, schreibt Historie, Beleg mit
  `fehler_vorher=30`/`fehler_nachher=0`; ohne Gewinn keine Änderung.

## Verifikation (nach Deploy)

- Lauf der Quelle: `n_fehler`/Warnungen sinken von ~998 auf 0, Terminzahl
  bleibt (961 ± Tagesgang).
- `heilungen`: neuer Fall `angenommen` mit `nur_mit` im Beleg statt siebenmal
  `verworfen`.
