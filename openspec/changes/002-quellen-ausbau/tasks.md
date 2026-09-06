# Tasks — Change 002 Quellen-Ausbau + Admin

Reihenfolge mit TDD; nach jeder Aufgabe committen. **Prinzip: alle Konfiguration über GUI (Admin, offen, später geschützt); Feed-first; generische Engine; keine pro-Quelle-Parser.**

## Phase 0 — Persistenz

- [ ] `store.py`: Tabellen `sources` (quelle PK, name, typ feed|regeln|intern, url, aktiv, rate_limit_s, menge_min/max, horizont_tage, robots, zuletzt_geaendert), `regeln` (quelle PK, regel_yaml), `settings` (key PK, wert); Seed: jup-berlin (typ intern) + Default-Settings; Migration bestehender DB (CREATE IF NOT EXISTS)
- [ ] Store-API: source_crud (list/get/add/update/delete), regeln_get/set, settings_get/set; Tests

## Phase 1 — Admin-API (offen)

- [ ] `app/admin_api.py` (Router `/api/admin`): GET/POST `/sources`, PUT/DELETE `/sources/{quelle}`, GET/PUT `/sources/{quelle}/regeln`, POST `/sources/{quelle}/validate` (YAML-Parse + Schema + Selektor-Kompilierung, deutsche Meldungen), GET `/sources/{quelle}/run-latest`, GET `/runs`, GET `/errors`, GET/PUT `/settings`, POST `/sources/{quelle}/scrape` (Lauf auslösen)
- [ ] Registrierung in main.py; Parametertests je Endpunkt

## Phase 2 — Admin-UI (`/admin`)

- [ ] `app/static/admin.html` + `admin.js` (+ CSS-Erweiterung): Quellen-Liste (Name/Typ/URL/Aktiv/Events/letzter Lauf/Fehler), Neu/Bearbeiten/Löschen, Regel-Editor mit „Prüfen“, Einstellungen, Läufe/Fehler-Ansicht; dunkles Design wie Haupt-UI; Fehler-/Leerzustände sichtbar
- [ ] Smoke: CRUD-Durchlauf im Browser

## Phase 3 — Adapter-Engine

- [ ] Deps feedparser/icalendar (extruct/jsonpath-ng/PyYAML bereits ergänzt)
- [ ] `feed_adapter.py`: RSS/Atom + iCal → Pipeline-Interface
- [ ] `selector_adapter.py`: Regeln aus DB (listing: url/pagination/item_css/felder; detail: jsonld/url_css/felder) mit parsel/extruct → Pipeline-Interface; slug = Detail-URL-Hash
- [ ] Registry: baut aktive Adapter aus `sources` (intern → JupBerlinAdapter); `--quelle=alle`; Tests (offline gegen Fixtures)

## Phase 4 — Quellen

- [ ] zlb.de: Fixture (vorhanden: `tests/fixtures/zlb/listing.html`, Detail-Probe sichern) + Regeln in DB/GUI validiert; offline grün; Online-Gegenprobe
- [ ] berlinmitkind.de: AJAX-Endpunkt dokumentieren (aus `em-events-search`-Seite), Fixtures, Regeln; offline grün; Online-Gegenprobe
- [ ] familienportal.berlin.de: Struktur-Feinschliff, Fixture, Regeln; offline grün; Online-Gegenprobe; falls nicht parsebar → Status „pending“ + Grund

## Phase 5 — Betrieb + Doku

- [ ] kinderkulturkalender-Duplikat-Befund in docs/quellen.md (bereits dokumentiert)
- [ ] docs/admin.md: Admin-Sektion in Alltagssprache (Quelle anlegen, Regeln prüfen, Läufe lesen) + Hinweis „vor öffentlichem Betrieb schützen (Auth folgt)“
- [ ] pytest grün; Commit; Deploy (kinderkram.cia-spandau.de); Admin-UI + neue Quellen online sichtbar

## Abnahme-Kriterien

- Quelle anlegen/bearbeiten/löschen + Regeln editieren ausschließlich über `/admin` (API); kein Datei-Edit im Betrieb
- „Prüfen“ meldet kaputte YAML/Selektoren verständlich; 0-Events-Läufe sichtbar (Alarm)
- pytest grün; Online-Läufe je Quelle > 0 Events idempotent; kinderkulturkalender nicht in Registry
