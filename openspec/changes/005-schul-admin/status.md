# Change 005 — Schul-Termine-Admin: Status

## Phase 1: Store + Admin-API (FERTIG, 16 neue Tests)

- Store: Tabellen `schulen`/`termin_kategorien`/`termine_manuell` (FK CASCADE/SET
  NULL, `PRAGMA foreign_keys=ON`), CRUD je Entität, Termin-Spiegelung nach
  `events` (quelle=`manuell`) nur bei `bestaetigt`, `_sync/_unsync_manuelles_event`.
- Admin-API: `/api/admin/schulen|kategorien|termine` CRUD + POST
  `/schulen/{bsn}/anfrage` (SMTP aus Einstellungen, sichtbarer 409 ohne SMTP).
- Tests: `tests/test_schul_admin_store.py` (8) + `tests/test_schul_admin_api.py` (8).
  Gesamtsuite: 93 passed.

### Bugfix (durch Tests gefunden): Teil-Update löschte still Felder
`PUT /schulen/{bsn}` (und analog kategorien/termine) machte Voll-Replacement:
ein PUT mit nur `{"name": …}` schrieb bezirk/plz/email/… auf NULL — stille
Datenzerstörung. Fix: Update-Endpunkte laden den Bestand und überschreiben nur
gesendete Felder (Muster wie `source_update`). Kategorie-Entfernung am Termin
explizit über `kategorie_id: ""`.

## Offen

- Admin-UI (`/admin`): Schul-Suche, Termin-Listen je Schule, Kategorien-Pflege,
  Status-Badge, Mail-Button je Schule
- Mail-Text-Vorlage + Betreff finalisieren
- Vorschau der öffentlichen Ansicht (was erscheint nach Bestätigen)

## Redesign 2026-09 (User-Korrektur): Quellen-Obertab + Tags + alle Termine editierbar — FERTIG + DEPLOYED

- Commit `ccb426d` (Backend) + `59c1ce6` (UI), Deployment via Coolify
  `ndehtgmfntlu1r94csuymgrb`, live verifiziert auf kinderkram.cia-spandau.de.
- **Architektur-Korrektur:** Schulen SIND Quellen. Obertabs jetzt
  Quellen | Termine | Einstellungen; Quellen-Tab hat Unter-Tabs (Übersicht,
  je aktive Quelle mit Event-Liste, Schulen als manuelle Quelle).
  Die frühere flache Struktur (eigener Schulen-Tab + Kategorien-Tab) ist
  verworfen.
- **Tags statt Kategorien (für ALLE Terminarten):** `termin_kategorien` →
  `tags` (id/name/farbe/sort/template), Migration idempotent VOR
  executescript (Reihenfolge-Bug dokumentiert); 19 Template-Tags
  (Schul-Tags + übliche Veranstaltungsarten aus Live-Quellen-Kategorien),
  eigene Tags in Einstellungen, Template-Tags nicht löschbar und nie vom
  Seed überschrieben. Admin-API `/api/admin/tags`.
- **Alle Termine editierbar:** `/api/admin/events` (Liste aller Events mit
  quelle/status/q) + `PUT /events/{id}` (Partial-Update → manuell=1).
  Scrape überschreibt admin-gepflegte Events nicht mehr (Upsert-Guard +
  Zwilling-Bereinigung mit `manuell=0`).
- **Mail:** `smtp_reply_to` + Reply-To-Header; `GET /settings` liefert den
  Beispieltext (Default-Vorlage), wenn keine gespeicherte Vorlage existiert.
- Tests: +3 (`tests/test_schul_admin_events.py`), Gesamtsuite 102 passed.
- Produktion: Migration erfolgreich (tags 19, events.manuell, 1106 Events
  erhalten). Erster Schul-Termin freigegeben: Grundschule am Wasserturm,
  Tag der offenen Tür 12.09.2026 — öffentlich unter `?quelle=manuell`.
