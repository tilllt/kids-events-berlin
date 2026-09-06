# Admin (ADDED)

## ADDED Requirements

### Requirement: Konfiguration ausschließlich über die Admin-GUI

- Alle konfigurierbaren Optionen (Quellen, Scraping-Regeln, Einstellungen) werden über die Admin-Sektion bearbeitet; Persistenz in der Datenbank (Tabellen `sources`, `regeln`, `settings`) — kein Datei-Edit im Betrieb.
- Die Admin-Sektion ist zunächst **offen** (kein Login) und wird später geschützt; der Admin-Router und `/admin` sind klar getrennt und die Doku weist auf die Absicherung vor öffentlichem Betrieb hin.
- Beim ersten Start wird die MVP-Quelle (jup-berlin, typ `intern`) geseedet.

#### Scenario: Betreiber bindet eine neue Quelle an
- **Akteure:** Betreiber.
- **Eingaben:** Quelle (z. B. zlb.de) mit Feed- oder Regel-Typ.
- **Ergebnis:** Anlegen über die Admin-UI; bei Regel-Quellen öffnet sich der Regel-Editor mit Vorlage; Speichern ohne Code/Datei-Zugriff.

### Requirement: Quellen verwalten (CRUD + Status)

- `GET/POST /api/admin/sources`, `PUT/DELETE /api/admin/sources/{quelle}`: Name, Typ (`feed`|`regeln`|`intern`), URL, Aktiv, Rate-Limit, erwarteter Mengenbereich, Horizont, robots-Notiz.
- Die Quellen-Liste zeigt je Quelle den letzten Lauf (Status, Events, Fehler) — nichts Stilles.
- `POST /api/admin/sources/{quelle}/scrape` löst einen Lauf aus (sichtbares Ergebnis).

#### Scenario: Quelle liefert 0 Events
- **Akteure:** Betreiber, Admin-UI.
- **Eingaben:** Lauf endet mit 0 Events.
- **Ergebnis:** Status „anomalie-0-events“ mit Alarm-Hinweis in der Liste; Betreiber korrigiert die Regeln.

### Requirement: Regel-Editor mit Validierung

- `GET/PUT /api/admin/sources/{quelle}/regeln`; `POST …/validate` prüft YAML-Syntax, Schema und kompiliert alle Selektoren (CSS/XPath, JSON-LD-Pfade) mit verständlichen deutschen Meldungen.
- Für `regeln`-Quellen liefert die GUI eine Vorlage; gespeichert wird nur, was die Validierung besteht (Hinweis bei Abweichung, kein stiller Fehler).

#### Scenario: Tippfehler im CSS-Selektor
- **Akteure:** Betreiber.
- **Eingaben:** Selektor `.eventTeaser__titel` (falsch geschrieben) wird geprüft.
- **Ergebnis:** Validierung meldet den unbekannten Selektor-Kontext bzw. leere Treffer mit Zeilenhinweis; Speichern blockiert mit Begründung.

### Requirement: Läufe und Fehler sichtbar

- `GET /api/admin/runs` und `GET /api/admin/errors` (filterbar je Quelle) speisen die Admin-Statusansicht: letzter Lauf, Events gesamt/neu/geändert/Fehler, Dauer, Fehlermeldungen mit Kontext.

#### Scenario: Fehler-Queue prüfen
- **Akteure:** Betreiber.
- **Eingaben:** Mehrere Fehlermeldungen aus einem Lauf.
- **Ergebnis:** Ansicht zeigt Meldung + betroffenes Event (Titel/URL), Filter je Quelle; kein stiller Verlust.

### Requirement: Einstellungen

- `GET/PUT /api/admin/settings` (key-value, z. B. Scrape-Intervall/Cron, Admin-Hinweis); Änderungen gelten ab dem nächsten Scheduler-Zyklus.

#### Scenario: Scrape-Intervall ändern
- **Akteure:** Betreiber.
- **Eingaben:** Neues Intervall in den Einstellungen.
- **Ergebnis:** Gespeichert und vom Scheduler übernommen; Bestätigung sichtbar.
