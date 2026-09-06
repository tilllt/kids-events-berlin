# Aggregation (Kern-Pipeline)

## Purpose

Die Kern-Pipeline nimmt die Roh-Events eines Adapters entgegen, normalisiert sie in ein einheitliches Event-Modell, validiert sie, speichert sie idempotent im SQLite-Store und protokolliert jede Ablehnung sichtbar. Zur Laufzeit ist die Pipeline vollständig deterministisch und frei von LLM-/Embedding-Aufrufen.

## Requirements

### Req 1: Normalisiertes Event-Modell

- **Ablauf:** Jeder Adapter liefert Roh-Events; die Pipeline bildet sie auf das kanonische Modell ab.
- **Pflichtfelder:** `titel`, `start` (lokal, tz Europe/Berlin), `ort` (Venue-Name), `quelle`, `source_url`.
- **Optionale Felder:** `ende`, `ganztags`, `beschreibung_kurz` (eigener Abstract), `bezirk`, `altersband_min/max`, `kategorien[]`, `kostenlos`, `preis_cent`, `venue_adresse`, `lat/lon`.
- **Deterministische ID:** `event_id = sha1(quelle + "/" + source_event_id)`; Wiederholte Läufe erzeugen dieselbe ID (Idempotenz).
- **Architektur:** `app/model.py` (Dataclasses/Pydantic), `app/store.py`.

#### Scenario: Einheitliche Event-Struktur aus zwei Adaptern
- **Akteure:** Pipeline, Adapter „jup-berlin“, Adapter „familienportal“.
- **Eingaben:** Je ein Roh-Event mit unterschiedlichen Feldnamen (z. B. „Bezirk“ vs. „Stadtteil“).
- **Ergebnis:** Beide Events liegen im Store mit identischem Feld-Schema; Feldnamen-Quirks der Quellen sind aufgelöst.

### Req 2: Idempotenter Lauf je Quelle

- **Ablauf:** Ein Lauf lädt alle aktuellen Events einer Quelle, vergleicht gegen den Store und schreibt nur Änderungen (Upsert).
- **Wiederholung:** Ein zweiter Lauf ohne Quell-Änderungen erzeugt keine neuen Zeilen und keine Duplikate.
- **Metriken:** Je Lauf werden gespeichert: `n_events`, `n_neu`, `n_geaendert`, `n_fehler`, `dauer_s`, `quelle`, `zeitpunkt` (Tabelle `runs`).
- **Architektur:** `app/pipeline.py`, `app/store.py`.

#### Scenario: Unveränderte Quelle erneut laufen lassen
- **Akteure:** Scheduler.
- **Eingaben:** Zweiter Lauf derselben Quelle innerhalb 24 h ohne Quell-Änderung.
- **Ergebnis:** `n_neu = 0`, `n_geaendert = 0`, Event-Anzahl im Store unverändert, Lauf protokolliert.

### Req 3: Validierung mit sichtbarer Fehler-Queue

- **Ablauf:** Vor dem Speichern wird jedes Event validiert: Pflichtfelder vorhanden, `ende >= start`, Datum im konfigurierten Sicht-Horizont, `source_url` wohlgeformt.
- **Ablehnung:** Nicht valide Events werden NICHT still verworfen, sondern in die Fehler-Queue geschrieben (`n_fehler` im Lauf, Eintrag mit Rohdaten + Grund).
- **Alarm:** Ein Lauf mit `n_fehler > 0` oder `n_events = 0` setzt einen Alarmsignal-Zustand (ntfy/Matrix im Betriebskontext).
- **Architektur:** `app/validate.py`.

#### Scenario: Kaputtes Zeitfeld
- **Akteure:** Adapter, Validator.
- **Eingaben:** Event mit `ende` vor `start` und nicht parsebarem Datumsstring.
- **Ergebnis:** Event landet in der Fehler-Queue mit Grund „Zeitlogik: ende < start“ bzw. „Datum nicht parsebar“; der Lauf meldet `n_fehler ≥ 1`; Alarm ausgelöst.

### Req 4: LLM-frei zur Laufzeit

- **Ablauf:** Aggregation, Anreicherung, Dedupe und Validierung laufen ohne LLM-, Embedding- oder externe ML-Aufrufe.
- **Ausnahme:** Nur der Entwicklungs-Loop (Adapter schreiben, Fehler-Analyse, Code-Review) darf KI-Werkzeuge nutzen — nie der Produktiv-Pfad.
- **Test:** CI-Test prüft, dass die Pipeline-Module keine Netzwerk-Aufrufe an externe Inference-Dienste enthalten (Import-/Mock-Check) und offline mit Fixture-Daten laufen.
- **Architektur:** Invarianz dokumentiert in `openspec/project.md`, eingehalten in `app/` (keine ML-Abhängigkeiten in den Runtime-Dependencies).

#### Scenario: Offline-Lauf mit Fixtures
- **Akteure:** Entwickler, CI.
- **Eingaben:** Pipeline-Lauf ausschließlich mit gespeicherten HTML-Fixtures, ohne Internetzugang.
- **Ergebnis:** Lauf erfolgreich; Ergebnisse identisch zu einem Online-Lauf mit denselben Quell-Daten.
