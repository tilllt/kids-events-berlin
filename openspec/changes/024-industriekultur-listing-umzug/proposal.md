# 024 — Quelle Festival Industriekultur: Umzug der Übersicht + stehengebliebene Alt-Dubletten

**Status:** in Arbeit (2026-09-24) — Verifikation folgt in `status.md`.
**Anlass:** Nutzerfund (2026-09-24): „die meisten events auf industriekultur haben
auch eine uhrzeit“, Beispiel `after-work-radtour-warmes-licht-und-kuehles-bier`
(„Do., 24.09.2026 | 16:00 Uhr“). Der Termin stand in der App ganztägig.

## Befund

### 1. Die Übersicht ist umgezogen — die Quelle liefert 0 Termine

`https://industriekultur.berlin/festival/` (die Listing-URL der Regel) antwortet
mit **301 → `/industriekultur-festival/`** — einer Marketing-Seite **ohne**
Termine. Der Veranstaltungskalender liegt jetzt unter
**`https://industriekultur.berlin/erleben/festival/`**.

Der HTTP-Client folgt der Umleitung (kein Fehler), `item_css` findet auf der
Zielseite aber 0 Elemente. Folge: jeder Lauf ab dem 18.09.2026 endet
`anomalie-0-events` — belegt über die Läufe-Tabelle:

```
Lauf 246  2026-09-17  status ok                  n_quellseiten=2
Lauf 262  2026-09-18  status anomalie-0-events   n_quellseiten=1
Lauf 278  2026-09-19  anomalie-0-events ... 358  2026-09-24  anomalie-0-events
```

Der Bestand (236 Termine) fror ein: `MAX(zuletzt_gesehen) = 2026-09-17`. Damit
konnte der Detail-Zeit-Fix aus **Change 023 nie greifen** — er war an der
Detailseite gemessen (`40/40`), ist aber im Betrieb nie angekommen.

**Gegenmessung der neuen Übersicht (2026-09-24, echte Seite, echter Adapter):**
165 Karten, `item_css` greift, **0 Warnungen**, **165 von 165 mit `.is-time`**,
165 eindeutige URLs (keine Duplikate in der Liste). Die einzige Änderung an der
Regel ist die URL — alle Feldselektoren (`data-festival-date`,
`data-festival-bezirk`, `.bzi-festival-event-card-main`, `…-card-link`,
`…-card-detail.is-time`, `…-card-detail.is-place`, `…-card-format`) treffen
unverändert.

### 2. 105 ganztägige Alt-Dubletten im Bestand

Von den 236 eingefrorenen Terminen standen 105 ganztägig, jeder mit einem
Zeit-Zwilling desselben Tages und derselben `source_url`:

```
cfbd2736…  source_event_id …kuehles-bier#20260924T0000  ganztags=1  ort="Ohne Angabe"        geholt 2026-09-13T15:22
a05f1b28…  source_event_id …kuehles-bier#20260924T1600  ganztags=0  ort="Start: Hauptbahnhof" geholt 2026-09-13T15:46
```

Mechanismus: Die Termin-ID ist `sha1(quelle + "/" + slug + "#" + <Startzeit>)`.
Wird ein Termin nachträglich **präzisiert** (Uhrzeit gelernt), ändert sich die
Startzeit und damit die **ID** → der neue Satz wird eingefügt, der alte bleibt
unter seiner alten ID stehen. `Store.entferne_ueberlappende_zwillinge` hätte ihn
entfernen müssen — die Tages-Regel aus Change 023 gruppiert aber über
**(Titel, Ort)**, und der alte Satz trägt den schlechteren Ort `"Ohne Angabe"`.
Er lag damit in einem anderen Topf und wurde nie mit dem neuen Satz verglichen.

### 3. Kleiner Nebenfund: `data-festival-bezirk` ist mehrwertig

4 von 165 Karten nennen zwei Bezirke (`"mitte,pankow"`). Der Label-Lookup kennt
nur einen Bezirk und fiel dort stumm auf `None` (kein Bezirk in der App).

## Umsetzung

1. **`app/quellen_defaults.py` — `INDUSTRIEKULTUR_REGELN`**
   - `listing.url` → `https://industriekultur.berlin/erleben/festival/`
     (mit Kommentar + Läufe-Beleg, damit die alte Adresse nicht zurückkommt).
   - `bezirk` mit `regex: '^([a-zäöüß-]+)'` — die erste Nennung ist der
     Startbezirk; der Bezirksfilter kennt nur einen Wert.
   - Detail-`ort`/`-adresse` aus der Fact-Box „Adresse“
     (`div.bzi-fact-box:contains('Adresse') p`) statt aus
     `.bzi-festival-event-card-detail.is-place`. Der alte Anker trifft auch die
     Karten der **„Weitere Termine“-Liste** und hängte deren Orte aneinander —
     gemessen an der echten Detailseite: **7 Orte in einem Wert**
     („Start: Bahnhof Spandau Start: Bahnhof Schöneweide …“). Nur Rückfall:
     die Übersicht trägt den Ort in jeder Karte.
2. **`app/store.py` — `entferne_ueberlappende_zwillinge`**
   Die Tages-Regel („ganztägiger Platzhalter gegen Eintrag **mit** Uhrzeit am
   selben Tag → Platzhalter geht“, Change 023) gruppiert jetzt über die
   **Event-Identität** (normalisierter Titel + Tag) statt über (Titel, Ort).
   Der Ort darf kein Teil des Schlüssels sein, weil genau er sich beim
   Präzisieren mitändert. Die Ketten-Regel für überlappende Serien bleibt
   unverändert auf (Titel, Ort) — sie schützt andere Fälle.
3. **Tests** — `tests/test_industriekultur_zeit.py` (+5, Fixture
   `listing_erleben.html` mit 3 echten Karten), `tests/test_serien_zwillinge.py`
   (+3: Fremd-Ort-Fall, Kontrolle „zwei echte Zeiten bleiben“, Admin-Schutz).

## Messung vor dem Schreiben (Trockenlauf an der Produktiv-DB, read-only)

Nachbildung der **neuen** Gruppierung über alle Quellen:

```
QUELLE                      Zeilen  alt  neu  zusaetzlich
industriekultur-berlin         236    0  102          102
SUMME                                 0  102          102
Verdachtsfälle: 0
```

- Die **alte** Regel löschte projektweit **nichts**; die neue löscht **102**
  Zeilen, **alle** aus `industriekultur-berlin`, **alle** ganztägige
  Platzhalter mit Zeit-Zwilling am selben Tag. **0 Fremdtreffer** in den
  übrigen 16 Quellen.
- 3 der 105 haben nach einer Titeländerung der Quelle („AUSGEBUCHT: …“) keinen
  **exakten** Zwilling und bleiben stehen; sie sind vergangen oder laufen aus
  und werden von `entferne_nicht_mehr_angeboten` / `prune_stale` abgeräumt
  (ehrlich benannte Restschuld, kein neuer Mechanismus).

## Abgrenzung

- **Kein** neues ID-Schema. Die ID enthält weiterhin die Startzeit; ein
  Schemawechsel würde erneut einen Bestand verdoppeln (genau der Fall aus
  Change 011/022). Die Aufräumlast trägt die Tages-Regel.
- **Keine** Änderung an der Detail-Zeitregel (`h2.bzi-color-1`) — sie bleibt
  Sicherheitsnetz für Karten ohne Zeitangabe und greift nur bei ganztägigen
  Listing-Terminen.
- **Kein** Eingriff in andere Quellen (Trockenlauf: 0 zusätzliche Löschungen).
- Die Regel lebt im Betrieb in der DB — Repo und Live-Regel müssen beide
  gepflegt werden (`PUT /api/admin/sources/industriekultur-berlin/regeln`).
