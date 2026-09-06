# Quellen (MODIFIED)

## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Produktive Quellen-Matrix (Stand Change 002)

- Produktive Adapter: `jup-berlin` (MVP), `berlinmitkind`, `zlb`, `familienportal` (falls Live-Befund parsebar) — je mit Mengenbereich in der Registry.
- `kinderkulturkalender-berlin.de` wird **nicht** als Quelle aufgenommen: Einträge laufen über die jup!-Datenbasis (Duplikat); Entscheidung in `docs/quellen.md` belegt.
- Neue Quelle → Adapter + Fixture + Audit-Eintrag; Entfernen einer Quelle → Eintrag in `docs/quellen.md` mit Grund.

#### Scenario: kinderkulturkalender taucht als Fund auf
- **Akteure:** Entwickler, Adapter-Registry.
- **Eingaben:** kinderkulturkalender-berlin.de wird als Quelle vorgeschlagen.
- **Ergebnis:** Registry lehnt ab mit Verweis auf jup!-Verbund; kein Doppel-Scrape, Merge-Risiko entfällt.

### Requirement: JSON-LD-Detailpfad (berlinmitkind)

- Detailseiten von berlinmitkind.de liefern JSON-LD `@type: Event` (name, startDate/endDate, location, description, url) → Parser übernimmt Felder direkt, keine CSS-Detail-Extraktion nötig.
- Listing: dokumentierter Endpunkt (Server-HTML oder AJAX-Endpunkt) — deterministisch, kein Browser.

#### Scenario: berlinmitkind-Event ohne JSON-LD
- **Akteure:** Adapter „berlinmitkind“.
- **Eingaben:** Detailseite ohne JSON-LD-Block (z. B. älterer Beitrag).
- **Ergebnis:** Fallback CSS/Regex; fehlen Pflichtfelder → Validierungs-Queue mit Grund, kein stiller Drop.

### Requirement: TYPO3-Listenpfad (ZLB)

- zlb.de: TYPO3-Artikel-Listen mit Datumsangaben; Parser nutzt dokumentierte Selektoren (Live-Befund) + Regel-Lexikon für Kinder-/Familien-Relevanz beim Enrichment.

#### Scenario: ZLB-Listenumbau
- **Akteure:** CI, Monitoring.
- **Eingaben:** zlb.de ändert TYPO3-Templates; Fixture-Test schlägt fehl.
- **Ergebnis:** CI rot; Struktur-Anomalie-Alarm; kein stiller Leerlauf.
