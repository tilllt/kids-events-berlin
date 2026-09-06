# Design — Change 002 Quellen-Ausbau + Admin

## Leitprinzipien (User-Vorgaben 2026-09-06)

1. **Benutzerfreundlichkeit ist Priorität** — Betreiber binden Quellen über die GUI an; Regeln pflegen ohne Code; Kinder-Events-UI bleibt einfach.
2. **Alle konfigurierbaren Optionen über die GUI** — Admin-Sektion, zunächst offen, später geschützt. Kein Datei-Edit im Betrieb.
3. **Feed-first** (RSS/Atom/iCal) vor Selektoren; existierende Bibliotheken (feedparser, icalendar, parsel, extruct); keine pro-Quelle-Parser.
4. Regeln bleiben Daten — aber in der DB, nicht in YAML-Dateien; die GUI ist der einzige Schreibweg (außer API).

## Persistenz & Admin (Kern dieser Erweiterung)

```
SQLite (bestehender Store, WAL)
├─ sources      (quelle PK, name, typ: feed|regeln, url, aktiv, rate_limit_s,
│                menge_min/max, horizont_tage, robots, zuletzt_geaendert)
├─ regeln       (quelle PK/FK, regel_yaml TEXT — nur für typ=regeln)
├─ settings     (key PK, wert TEXT — z. B. scrape_cron, admin_hinweis)
├─ runs         (bestehend — Läufe je Quelle)
└─ errors       (bestehend — Fehler-Queue je Lauf)

Admin-API (Router /api/admin, offen; Auth-Middleware später davor)
├─ GET/POST /sources · PUT/DELETE /sources/{quelle}
├─ GET/PUT /sources/{quelle}/regeln
├─ POST /sources/{quelle}/validate   (YAML-Parse + Schema + Selektoren-Kompilierung)
├─ GET /sources/{quelle}/run-latest  (letzter Lauf + Fehler)
├─ GET /runs?quelle=…  · GET /errors?quelle=…
└─ GET/PUT /settings

Admin-UI (/admin, statisch wie Haupt-UI, Vanilla JS)
├─ Quellen-Liste: Name/Typ/URL/Aktiv/Events/letzter Lauf/Fehler + Aktionen
├─ Quelle bearbeiten (Formular) / neu (Vorlage)
├─ Regel-Editor (Textarea + „Prüfen“ → Ergebnis; Vorlage je Typ)
└─ Status: letzte Läufe + Fehler-Queue (nichts Stilles)
```

- Seed beim ersten Start: jup-berlin als `regeln`-Quelle mit dem heutigen Parser-Verhalten markiert? Nein: jup-berlin läuft über den **bestehenden Python-Adapter** (Sonderfall, dokumentiert); die `sources`-Tabelle führt ihn als `typ: intern` mit Status; neue Quellen sind `feed` oder `regeln`.
- Schutz später: Admin-Router + `/admin` statisch getrennt; Doku-Vermerk „vor öffentlichem Betrieb absichern (Basic-Auth/OIDC via Traefik oder App-Middleware)“.

## Stufenmodell je Quelle (wie bisher, jetzt über GUI)

| Stufe | Mechanik | Bibliothek |
|---|---|---|
| 1 (bevorzugt) | Feed-Abo: RSS/Atom/iCal/JSON | feedparser, icalendar |
| 2 (Fallback) | Regeldatei: Item-/Feld-Selektoren oder JSON-LD-Pfade | parsel, extruct |

Erkundungsbefunde (2026-09-06): zlb.de → Stufe 2 (Teaser `article.eventTeaser`, Titel `h3.eventTeaser__title > span:not(.eventTeaser__superHeadline)`, Datum `So, 06.09.2026`, Zeit in `.eventTeaser__meta`, Detailseite mit Ereignisort, JSON-LD @type:Event vorhanden); berlinmitkind.de → Stufe 2 (AJAX-Liste `em-events-search`, Detail-JSON-LD); familienportal → Stufe 2 (erreichbar, Datums-Struktur); jup rss.xml = News (kein Feed); kinderkulturkalender = jup-Duplikat.

## Adapter-Engine

- `app/adapters/feed_adapter.py` / `selector_adapter.py`: erfüllen das Pipeline-Interface (`fetch_listing_page`, `parse_listing` → [{slug,titel,start,ende,ganztags,ort}], `fetch_detail`, `parse_detail`, `zu_event`); Registry baut sie aus `sources`/`regeln` (Store-Read), `--quelle=alle` = alle aktiven.
- selector_regeln-Schema (DB-Feld regel_yaml, validiert): listing {url, pagination, item_css, felder{css/attr/format}} + optional detail {jsonld: bool, url_css, felder{jsonld-Pfade}} — kompakt dokumentiert, Vorlage in der GUI.

## Ablauf je Quelle (Betreiber, über GUI)

1. Quelle anlegen (Typ, URL, Mengenbereich, Rate-Limit) → speichern.
2. Bei `regeln`: Regel-Editor öffnen → „Prüfen“ (Schema/Selektoren) → speichern.
3. Lauf starten (Button „Jetzt scrapen“ ruft Pipeline) oder Scheduler abwarten → Status/Fehler sichtbar.
4. Struktur-Umbau: Fehler/0-Events sichtbar → Regeln in der GUI korrigieren → erneut scrapen. Fixture-Test bleibt Dev-Pflicht (CI), GUI-Validierung ergänzt.

## Risiken

- GUI-Regeln ohne Fixture können kaputte Selektoren speichern → `validate` kompiliert Selektoren + Schema; 0-Events-Lauf erzeugt sichtbaren Alarm (bestehend). Dev-Fixtures bleiben Quelle der Wahrheit für CI.
- Offene Admin-API → dokumentiert + später geschützt; kein Zugriff aus der Haupt-UI verlinkt (nur /admin).
- Feed unvollständig → Stufe-2-Details oder Quelle zurückstellen; Validierungs-Queue zeigt Grund.
