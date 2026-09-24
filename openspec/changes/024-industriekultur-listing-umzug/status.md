# Change 024 — Festival Industriekultur: Umzug der Übersicht + Alt-Dubletten

Stand 2026-09-24 (gebaut, getestet, deployt, live gemessen)

Anlass: Nutzerfund „die meisten events auf industriekultur haben auch eine
uhrzeit" (Beispiel `after-work-radtour-warmes-licht-und-kuehles-bier`,
„Do., 24.09.2026 | 16:00 Uhr") — der Termin stand ganztägig in der App.
Befund und Umsetzung: `proposal.md`.

## Warum der Fix aus Change 023 nie ankam

`https://industriekultur.berlin/festival/` leitet seit dem 17./18.09.2026 per
301 auf `/industriekultur-festival/` um — eine Marketing-Seite **ohne**
Termine. Der Adapter folgt der Umleitung, findet dort 0 Elemente und meldet
`anomalie-0-events`. Beleg aus der Läufe-Tabelle:

| Lauf | Datum | status | n_quellseiten |
|---|---|---|---|
| 246 | 2026-09-17 | ok | 2 |
| 262 | 2026-09-18 | anomalie-0-events | 1 |
| 278–342 | 2026-09-19 … 09-23 | anomalie-0-events | 1 |
| 358 | 2026-09-24 03:34 | anomalie-0-events | 1 |

Der Bestand fror ein (`MAX(zuletzt_gesehen) = 2026-09-17`). Die 023-Messung
(„industriekultur 40/40 mit Zeit") war eine Prüfung an **Detailseiten**, keine
Aussage über den laufenden Betrieb — deshalb sah sie richtig aus, während die
Quelle gar nichts mehr lieferte. Neue Übersicht: `/erleben/festival/`.

## Umsetzung

1. `app/quellen_defaults.py` — `INDUSTRIEKULTUR_REGELN`:
   - `listing.url` → `https://industriekultur.berlin/erleben/festival/`
   - `bezirk` mit `regex: '^([a-zäöüß-]+)'` (Feld ist mehrwertig)
   - Detail-`ort`/`-adresse` aus der Fact-Box „Adresse" (vorher: 7 verkettete
     Orte aus den Karten der „Weitere Termine"-Liste)
2. `app/store.py` — `entferne_ueberlappende_zwillinge`:
   - Tages-Dublette gruppiert über **(Titel-Kern, Tag)** statt (Titel, Ort)
   - `titel_kern()` streift Status-Vorsätze („AUSGEBUCHT: ", „Abgesagt – ")
3. Tests: `tests/test_industriekultur_zeit.py` (+5, Fixture
   `tests/fixtures/industriekultur/listing_erleben.html`),
   `tests/test_serien_zwillinge.py` (+4).

## Verifiziert

**Tests:** 33 grün in den beiden geänderten Dateien.
Gesamtsuite: **375 grün, 11 rot** — alle 11 in `tests/test_recherche_*`
(datumsgebundene Altlast, auf einem frischen `git worktree HEAD` **identisch
rot**, also kein Rückschritt dieser Änderung).

**Trockenlauf an der Produktiv-DB (read-only), vor jedem Schreiben:**

| Regel | Löschungen | davon industriekultur | Fremdtreffer |
|---|---|---|---|
| alte Gruppierung (Titel, Ort) | 0 | 0 | 0 |
| neue Gruppierung (Titel-Kern, Tag) | 3 | 3 | 0 |

(Die erste Fassung ohne `titel_kern` löschte 102 Alt-Dubletten — die 3 Reste
wurden mit den Status-Vorsätzen gemessen und dann nachgezogen.)

**Live-Messung** (`/api/events?quelle=industriekultur-berlin&limit=2000`):

| | vorher | nachher |
|---|---|---|
| Termine der Quelle | 236 | **78** |
| ganztägig | 105 | **0** |
| URLs mit mehr als einem Eintrag | 105 | **0** |
| mit Uhrzeit | 131 (55 %) | **78 (100 %)** |

Der Nutzerfall:
`After Work Radtour: Warmes Licht und kühles Bier` → `2026-09-24T16:00:00`,
`ganztags = False`, Ort `Start: Hauptbahnhof`, Bezirk `mitte`. ✔

Läufe: **368** `ok` (23 s, 0 Fehler, 102 Dubletten entfernt) und **369** `ok`
(0 Fehler, die 3 Reste entfernt). Deploy-UUIDs `urnrsdoopvzs35czbyi9cccd`
(Commit `7975f08`) und `iocsnqvrvjrc6pxdbv1zufta` (Commit `73733d5`),
Container `running:healthy`.

Regel-Rollout per `PUT /api/admin/sources/industriekultur-berlin/regeln`:
`GET …/regeln` gegen die Repo-Fassung verglichen → `DB == Repo: True`.

## Offen (ehrlich benannt)

- **Die Terminzahl sinkt von 236 auf 78, und das ist richtig:** die 165 Karten
  der Übersicht reichen von 12.09. bis 04.10.; ab heute sind es 78. Die übrigen
  waren vergangene Termine (17.–23.09.) und die 105 Dubletten. Das Festival-
  programm der Quelle endet am 04.10.2026 — danach ist die Quelle leer, bis
  ein neues Programm erscheint (`anomalie-0-events` wäre dann erwartbar und
  kein Defekt).
- **3 Reste wurden in zwei Schritten abgeräumt** (erster Lauf 102, zweiter
  Lauf 3 nach der `titel_kern`-Erweiterung) — bewusst so, weil der Trockenlauf
  vor jedem Schreiben stand.
- Der Skill-Referenztext `references/uhrzeit-quellen.md` bzw.
  `references/quellen-regeln-wartung.md` führt die Aussage „die Übersichtskarte
  trägt `.is-time` nicht bei jedem Termin" — das galt für die **alte**
  Übersicht und ist mit dem Umzug überholt (neue Übersicht: 165 von 165).
