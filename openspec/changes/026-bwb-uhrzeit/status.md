# Change 026 — BWB-Veranstaltungen: Rollout und Messung

Stand 2026-09-24 (Regel ausgerollt, Lauf gefahren, geprüft)

## Rollout

| Schritt | Ergebnis |
|---|---|
| Regel prüfen (`POST …/regeln/validate`) | `{"ok": true, "fehler": []}` |
| Regel speichern (`PUT …/regeln`) | 200 |
| Gegenprobe | `gespeicherte Regel == Repo-Vorlage: True` |
| Lauf 372 | `anomalie-0-events`, 0,24 s, 1 Quellseite, 0 neu, 0 Fehler |
| Deploy | `wxbrytrlgfd8ndjk66l1scwr`, `END=finished`, `running:healthy` |

## Ergebnis: 0 Termine — und das ist das richtige Ergebnis

Die Quelle bleibt leer. Belegt am Seiteninhalt vom 2026-09-24: **23 Termine,
alle in der Vergangenheit**, neuester `2026-09-13`. Die Berliner
Wasser-Mobil-Tour läuft Mai bis September; danach pflegt die BWB die Seite
nicht weiter. Der Zeitfenster-Filter der Pipeline wirft vergangene Termine
korrekt weg, deshalb 0 Zeilen — `anomalie-0-events` ist hier die **richtige
Meldung**, kein Defekt.

Der Unterschied zu Change 024 ist wichtig: bei `industriekultur-berlin` war
dieselbe Meldung ein 301-Umzug auf eine Seite ohne Termine (echter Defekt).
**`anomalie-0-events` allein sagt nichts — die Listen-URL und den Seiteninhalt
ansehen.**

## Was tatsächlich behoben wurde

Die Regel hätte beim Saisonstart 2027 jeden Termin ganztägig eingetragen:
`info-begin` = `2026-05-09 12:00:00`, die Regel las aber nur
`([0-9]{4}-[0-9]{2}-[0-9]{2})` mit `format: '%Y-%m-%d'` — die Uhrzeit fiel weg.
Jetzt getrennte Felder `start` / `zeit` / `ende`; Einträge **ohne** Uhrzeit
(`2024-04-28`, kommt auf der Seite vor) bleiben ganztags, statt ganz zu fehlen.
Tests: 4 grün, davon eine Gegenprobe, die mit dem alten Feldaufbau 00:00
nachweist. Volle Suite 390 grün / 11 rot (Altlast `test_recherche_*`).

## Offene Reste (ehrlich benannt)

- **`anomalie-0-events` wird bis Mai 2027 jeden Morgen auftauchen** — die
  Quelle ist saisonal leer. Drei Wege: so lassen (die Meldung ist korrekt),
  die Quelle bis zur Saison auf `aktiv=false` setzen (kommt dann aber **nicht**
  von selbst zurück), oder eine Erwartung `menge_min` erst ab Mai setzen.
  Entscheidung liegt beim Betreiber — hier nichts davon eigenmächtig gemacht.
- **Ein Eintrag der Seite hat einen leeren Titel** (`info-subject` leer). Die
  Engine verwirft ihn mit der Warnung `Item 12: titel fehlt` — wiederkehrend,
  aber korrekt: der Termin ist damit vollständig aus dem Bestand, nicht halb
  drin. Das Fixture dokumentiert den Fall.
- Die Regel der Quelle lag bisher **nur in der Produktions-DB**; sie steht jetzt
  als `BWB_REGELN` im Repo (`DEFAULT_REGELN`). Damit ist der Repo-Stand wieder
  die Wahrheit — bis hierher war er es für diese Quelle nicht.
