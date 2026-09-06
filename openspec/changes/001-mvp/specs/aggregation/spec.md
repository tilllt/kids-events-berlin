# Aggregation (ADDED)

## ADDED Requirements

### Requirement: Normalisiertes Event-Modell
- Adapter-Roh-Events werden auf ein kanonisches Modell abgebildet: Pflichtfelder `titel`, `start` (lokal, Europe/Berlin), `ort`, `quelle`, `source_url`; optionale Felder u. a. `ende`, `ganztags`, `beschreibung_kurz`, `bezirk`, `altersband_min/max`, `kategorien[]`, `kostenlos`, `preis_cent`, `venue_adresse`, `lat/lon`.
- Deterministische ID `sha1(quelle + "/" + source_event_id)`; Wiederholungsläufe idempotent.
- Architektur: `app/model.py`, `app/store.py`.

#### Scenario: Einheitliche Event-Struktur aus zwei Adaptern
- **Akteure:** Pipeline, Adapter „jup-berlin“, Adapter „familienportal“.
- **Eingaben:** Je ein Roh-Event mit unterschiedlichen Feldnamen („Bezirk“ vs. „Stadtteil“).
- **Ergebnis:** Beide Events im Store mit identischem Feld-Schema; Quell-Quirks aufgelöst.

### Requirement: Idempotenter Lauf je Quelle
- Lauf lädt alle aktuellen Events einer Quelle, Upsert gegen Store, nur Änderungen schreiben.
- Metriken je Lauf in Tabelle `runs`: `n_events`, `n_neu`, `n_geaendert`, `n_fehler`, `dauer_s`, `quelle`, `zeitpunkt`.

#### Scenario: Unveränderte Quelle erneut laufen lassen
- **Akteure:** Scheduler.
- **Eingaben:** Zweiter Lauf derselben Quelle innerhalb 24 h ohne Quell-Änderung.
- **Ergebnis:** `n_neu = 0`, `n_geaendert = 0`, Event-Anzahl unverändert, Lauf protokolliert.

### Requirement: Validierung mit sichtbarer Fehler-Queue
- Validierung vor Speichern: Pflichtfelder, `ende >= start`, Datum im Sicht-Horizont, `source_url` wohlgeformt.
- Nicht valide Events landen sichtbar in der Fehler-Queue (Grund + Rohdaten), nie still verworfen; `n_fehler > 0` oder `n_events = 0` → Alarm (ntfy/Matrix im Betriebskontext).

#### Scenario: Kaputtes Zeitfeld
- **Akteure:** Adapter, Validator.
- **Eingaben:** Event mit `ende` vor `start` und unparsebarem Datumsstring.
- **Ergebnis:** Event in Fehler-Queue mit Grund; Lauf meldet `n_fehler ≥ 1`; Alarm ausgelöst.

### Requirement: LLM-frei zur Laufzeit
- Aggregation, Anreicherung, Dedupe und Validierung ohne LLM-/Embedding-/externe ML-Aufrufe; offline mit Fixtures lauffähig.
- KI-Werkzeuge nur im Entwicklungs-Loop; CI prüft die Invarianz (keine ML-Dependencies in Runtime-Deps).

#### Scenario: Offline-Lauf mit Fixtures
- **Akteure:** Entwickler, CI.
- **Eingaben:** Pipeline-Lauf ausschließlich mit gespeicherten HTML-Fixtures, ohne Internetzugang.
- **Ergebnis:** Lauf erfolgreich; Ergebnisse identisch zum Online-Lauf mit denselben Quell-Daten.
