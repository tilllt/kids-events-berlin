# Quellen (ADDED)

## ADDED Requirements

### Requirement: Deklarative Adapter-Konfiguration
- Adapter definiert Listing-URL(s), Pagination, Extraktionsregeln, Rate-Limit, robots-Policy (erlaubt/nicht, dokumentiert), erwarteten Event-Mengenbereich, Sicht-Horizont.
- Ablage `app/adapters/<quelle>.py` bzw. `configs/<quelle>.yaml`; Registry in `app/adapters/__init__.py`.
- robots/ToS-Befund je Quelle in Adapter-Kommentar und `docs/quellen.md`.

#### Scenario: Neuen Adapter registrieren
- **Akteure:** Entwickler.
- **Eingaben:** Neue Quelle mit Konfiguration und Fixture.
- **Ergebnis:** Adapter in Registry; `--quelle=alle` führt ihn mit; Audit-Eintrag in `docs/quellen.md`.

### Requirement: Extraktions-Priorität JSON-LD → hEvent → CSS
- Feste Reihenfolge beim Parsen: (1) JSON-LD `@type: Event`, (2) hEvent-Microformate, (3) CSS-Selektoren, (4) Regex nur für Einzelfelder.
- Strukturierte Daten schlagen fragile Selektoren; keine LLM-Extraktion.

#### Scenario: Museum liefert JSON-LD, Bibliothek nicht
- **Akteure:** Adapter „museum-x“, Adapter „bibliothek-y“, Parser.
- **Eingaben:** Museum-Seite mit JSON-LD; Bibliotheks-Seite nur HTML-Liste.
- **Ergebnis:** Museum-Event vollständig aus JSON-LD; Bibliotheks-Event über Selektoren; gleiches Modell.

### Requirement: Fixture-Tests und Anomalie-Alarme
- Fixture-Snapshot (HTML + erwartete Events) je Adapter als Regressionstest in CI.
- 0 Events oder Abweichung > 50 % vom 7-Tage-Mittel → Alarm; Struktur-Hash je Lauf, Abweichung > 20 % → Alarm „Adapter-Review nötig“.

#### Scenario: Site-Umbau bei jup.berlin
- **Akteure:** CI, Monitoring.
- **Eingaben:** jup.berlin ändert Listing-HTML; Fixture-Test schlägt fehl.
- **Ergebnis:** CI rot mit Diff; Produktion meldet Struktur-Anomalie; Alarm vor leeren Nutzerergebnissen.
