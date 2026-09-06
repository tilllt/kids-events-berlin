# Quellen (MODIFIED)

## MODIFIED Requirements

### Requirement: Deklarative Adapter-Konfiguration

- Jede Quelle wird durch eine YAML-Regeldatei `configs/<quelle>.yaml` beschrieben — **Regeln sind Daten, kein Quell-Parser-Code**. Eine generische Engine (`app/adapters/config_adapter.py`) führt die Regeln aus; sie nutzt die existierenden Bibliotheken `parsel` (CSS/XPath) und `extruct` (JSON-LD/Microformats/Microdata/RDFa).
- Die Regeldatei definiert: Listing-URL(s), Pagination (query-param oder next-Selektor), Item-/Feld-Selektoren (CSS inkl. `attr`, Datums-`format`) oder JSON-LD-Pfade (JSONPath), Detail-Extraktion, Rate-Limit, robots-Policy (dokumentiert), erwarteten Event-Mengenbereich, Sicht-Horizont.
- robots/ToS-Befund je Quelle steht im Regeldatei-Kommentar und in `docs/quellen.md`.
- Abweichungen (Quelle braucht echte Sonderlogik) sind dokumentierte Ausnahmen mit Begründung — nicht der Standard.

#### Scenario: Neuen Adapter registrieren
- **Akteure:** Entwickler, Admin.
- **Eingaben:** Neue Quelle → Regeldatei `configs/<quelle>.yaml` + Fixture.
- **Ergebnis:** Adapter in Registry; `--quelle=alle` führt ihn mit; Audit-Eintrag in `docs/quellen.md`. Kein Python-Code nötig.

### Requirement: Extraktions-Priorität JSON-LD → hEvent → CSS

- Feste Reihenfolge beim Parsen: (1) eingebettetes JSON-LD (`@type: Event`), (2) hEvent-Microformate, (3) CSS-Selektoren, (4) Regex nur für Einzelfelder — abgebildet durch `extruct` (json-ld/microformat/microdata) mit `parsel`-Fallback.
- Strukturierte Daten schlagen fragile Selektoren; keine LLM-Extraktion. Die Regeldatei wählt je Quelle den Pfad und das Feld-Mapping.

#### Scenario: Museum liefert JSON-LD, Bibliothek nicht
- **Akteure:** Adapter „museum-x“, Adapter „bibliothek-y“, Parser.
- **Eingaben:** Museum-Seite mit JSON-LD; Bibliotheks-Seite nur HTML-Liste.
- **Ergebnis:** Museum-Event vollständig aus JSON-LD (extruct); Bibliotheks-Event über CSS-Regeln (parsel); gleiches Modell.

## ADDED Requirements

### Requirement: User-korrigierbare Regeln im Betrieb

- Regeldateien liegen versioniert unter `configs/` (Fixture-Tests laden sie) und werden zur Laufzeit aus `$DATA_DIR/configs/` überlesen: das Volume-Overlay gewinnt. Ein Admin korrigiert Selektoren per Datei-Edit ohne Rebuild/Code-Deploy; der nächste Lauf loggt Quelle + Regel-Hash.
- Jede Regeländerung muss an den Fixtures geprüft werden können (Regressionspflicht bleibt).

#### Scenario: Site-Umbau bei einer Quelle
- **Akteure:** Admin, Monitoring.
- **Eingaben:** Quelle ändert Selektoren; Fixture-Test rot; changedetection.io-Watch meldet Struktur-Änderung.
- **Ergebnis:** Admin korrigiert `configs/<quelle>.yaml` (Overlay), Fixture-Test wird aktualisiert, Lauf wieder grün — kein Code-Deploy.

### Requirement: Produktive Quellen-Matrix (Stand Change 002)

- Produktive Quellen: `jup-berlin` (MVP, migriert später auf die Engine), `berlinmitkind`, `zlb`, `familienportal` (falls Live-Befund parsebar) — je Mengenbereich in der Registry.
- `kinderkulturkalender-berlin.de` wird **nicht** als Quelle aufgenommen: Einträge laufen über die jup!-Datenbasis (Duplikat); Entscheidung in `docs/quellen.md` belegt.
- changedetection.io-Watch je produktiver Listing-URL als Frühwarnung vor Site-Umbauten (Betrieb).

#### Scenario: kinderkulturkalender taucht als Fund auf
- **Akteure:** Entwickler, Adapter-Registry.
- **Eingaben:** kinderkulturkalender-berlin.de wird als Quelle vorgeschlagen.
- **Ergebnis:** Registry lehnt ab mit Verweis auf jup!-Verbund; kein Doppel-Scrape, Merge-Risiko entfällt.

### Requirement: JSON-LD-Detailpfad (berlinmitkind)

- Detailseiten von berlinmitkind.de liefern JSON-LD `@type: Event` → Extraktion über `extruct`, Feld-Mapping per JSONPath (name, startDate/endDate, location, description, url). Listing: dokumentierter Endpunkt in der Regeldatei (Server-HTML oder AJAX-Endpunkt) — deterministisch, kein Browser.

#### Scenario: berlinmitkind-Event ohne JSON-LD
- **Akteure:** Adapter „berlinmitkind“ (Engine + Regeldatei).
- **Eingaben:** Detailseite ohne JSON-LD-Block (z. B. älterer Beitrag).
- **Ergebnis:** Fallback CSS/Regex aus der Regeldatei; fehlen Pflichtfelder → Validierungs-Queue mit Grund, kein stiller Drop.

### Requirement: TYPO3-Listenpfad (ZLB)

- zlb.de: TYPO3-Artikel-Listen mit Datumsangaben; Extraktion über CSS-Regeln in `configs/zlb.yaml` (parsel) + Regel-Lexikon für Kinder-/Familien-Relevanz beim Enrichment.

#### Scenario: ZLB-Listenumbau
- **Akteure:** CI, Monitoring.
- **Eingaben:** zlb.de ändert TYPO3-Templates; Fixture-Test schlägt fehl.
- **Ergebnis:** CI rot; Struktur-Anomalie-Alarm; kein stiller Leerlauf.
