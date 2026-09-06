# Quellen (MODIFIED)

## MODIFIED Requirements

### Requirement: Deklarative Adapter-Konfiguration

- Quellen werden in der Datenbank geführt (`sources`-Tabelle: quelle, name, typ: `feed`|`regeln`|`intern`, url, aktiv, rate_limit_s, menge_min/max, horizont_tage, robots) und über die Admin-Sektion bearbeitet (siehe Capability admin). Für Stufe 2 liegen die Regeln je Quelle in der `regeln`-Tabelle. **Regeln sind Daten, kein Quell-Parser-Code.**
- Stufe 1 (`feed`): generischer Feed-Adapter (`feedparser` RSS/Atom, `icalendar` iCal) — Anbinden = Quellen-Eintrag über die GUI.
- Stufe 2 (`regeln`): generische Engine (`parsel` CSS/XPath, `extruct` JSON-LD/Microformats) mit Item-/Feld-Selektoren oder JSON-LD-Pfaden, Datums-`format`, Pagination; nur wenn kein Feed existiert.
- robots/ToS-Befund je Quelle in der Quellen-Konfiguration und in `docs/quellen.md`.
- Abweichungen (Quelle braucht echte Sonderlogik, z. B. jup-berlin `intern`) sind dokumentierte Ausnahmen mit Begründung — nicht der Standard.

#### Scenario: Neuen Adapter registrieren
- **Akteure:** Entwickler, Betreiber.
- **Eingaben:** Neue Quelle mit Feed → Eintrag über die Admin-UI; ohne Feed → zusätzlich Regeln im Regel-Editor. Fixture je Quelle (Dev).
- **Ergebnis:** Adapter in Registry; `--quelle=alle` führt ihn mit; Audit-Eintrag in `docs/quellen.md`. Kein Python-Code nötig.

### Requirement: Feed-first (Stufe 1 vor Stufe 2)

- Bei jeder Quelle wird zuerst nach einem maschinenlesbaren Feed gesucht (RSS/Atom via `<link rel="alternate">`, `/feed/`, `rss.xml`, iCal-Export); existiert einer, MUSS die Quelle über den Feed-Adapter laufen.
- Layout-Umbauten brechen Feeds nicht; Selektor-Pflege entfällt. Die Entscheidung je Quelle wird in `docs/quellen.md` belegt.

#### Scenario: TYPO3-Website bietet RSS an
- **Akteure:** Entwickler.
- **Eingaben:** Quelle ohne dokumentierten Feed, `<link rel="alternate" type="application/rss+xml">` im HTML.
- **Ergebnis:** Quelle läuft über feed_adapter; keine CSS-Selektoren; Fixture = Feed-Antwort.

### Requirement: Extraktions-Priorität JSON-LD → hEvent → CSS

- Feste Reihenfolge beim Parsen: (1) eingebettetes JSON-LD (`@type: Event`), (2) hEvent-Microformate, (3) CSS-Selektoren, (4) Regex nur für Einzelfelder — abgebildet durch `extruct` (json-ld/microformat/microdata) mit `parsel`-Fallback.
- Strukturierte Daten schlagen fragile Selektoren; keine LLM-Extraktion. Die Regeln (DB) wählen je Quelle den Pfad und das Feld-Mapping.

#### Scenario: Museum liefert JSON-LD, Bibliothek nicht
- **Akteure:** Adapter „museum-x“, Adapter „bibliothek-y“, Parser.
- **Eingaben:** Museum-Seite mit JSON-LD; Bibliotheks-Seite nur HTML-Liste.
- **Ergebnis:** Museum-Event vollständig aus JSON-LD (extruct); Bibliotheks-Event über CSS-Regeln (parsel); gleiches Modell.

## ADDED Requirements

### Requirement: User-korrigierbare Regeln über die Admin-GUI

- Regeldateien liegen in der Datenbank (`regeln`-Tabelle, je Quelle) und werden ausschließlich über die Admin-Sektion bearbeitet (API/UI, siehe Capability admin); kein Datei-Edit im Betrieb.
- Jede Regeländerung durchläuft die Validierung (YAML-Syntax, Schema, Selektor-Kompilierung); Regressionstests an Fixtures bleiben Dev-/CI-Pflicht.

#### Scenario: Site-Umbau bei einer Quelle
- **Akteure:** Betreiber, Monitoring.
- **Eingaben:** Quelle ändert Selektoren; Lauf meldet 0 Events/Fehler; Fixture-Test rot.
- **Ergebnis:** Betreiber korrigiert die Regeln im Admin-Regel-Editor, Validierung besteht, Lauf wieder grün — kein Code-Deploy, kein Datei-Zugriff.

### Requirement: Produktive Quellen-Matrix (Stand Change 002)

- Produktive Quellen: `jup-berlin` (MVP, migriert später auf die Engine), `berlinmitkind`, `zlb`, `familienportal` (falls Live-Befund parsebar) — je Mengenbereich in der Registry.
- `kinderkulturkalender-berlin.de` wird **nicht** als Quelle aufgenommen: Einträge laufen über die jup!-Datenbasis (Duplikat); Entscheidung in `docs/quellen.md` belegt.
- changedetection.io-Watch je produktiver Listing-URL als Frühwarnung vor Site-Umbauten (Betrieb).

#### Scenario: kinderkulturkalender taucht als Fund auf
- **Akteure:** Entwickler, Adapter-Registry.
- **Eingaben:** kinderkulturkalender-berlin.de wird als Quelle vorgeschlagen.
- **Ergebnis:** Registry lehnt ab mit Verweis auf jup!-Verbund; kein Doppel-Scrape, Merge-Risiko entfällt.

### Requirement: JSON-LD-Detailpfad (berlinmitkind)

- Detailseiten von berlinmitkind.de liefern JSON-LD `@type: Event` → Extraktion über `extruct`, Feld-Mapping per JSONPath (name, startDate/endDate, location, description, url). Listing: dokumentierter Endpunkt in den Regeln (Server-HTML oder AJAX-Endpunkt) — deterministisch, kein Browser.

#### Scenario: berlinmitkind-Event ohne JSON-LD
- **Akteure:** Adapter „berlinmitkind“ (Engine + Regeln aus DB).
- **Eingaben:** Detailseite ohne JSON-LD-Block (z. B. älterer Beitrag).
- **Ergebnis:** Fallback CSS/Regex aus den Regeln; fehlen Pflichtfelder → Validierungs-Queue mit Grund, kein stiller Drop.

### Requirement: TYPO3-Listenpfad (ZLB)

- zlb.de: TYPO3-Artikel-Listen mit Datumsangaben; Extraktion über CSS-Regeln (DB, `regeln` je Quelle, parsel) + Regel-Lexikon für Kinder-/Familien-Relevanz beim Enrichment.

#### Scenario: ZLB-Listenumbau
- **Akteure:** CI, Monitoring.
- **Eingaben:** zlb.de ändert TYPO3-Templates; Fixture-Test schlägt fehl.
- **Ergebnis:** CI rot; Struktur-Anomalie-Alarm; kein stiller Leerlauf.
