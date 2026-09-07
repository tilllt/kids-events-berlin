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
