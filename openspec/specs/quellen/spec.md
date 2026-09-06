# Quellen (Adapter-Framework)

## Purpose

Pro Veranstaltungsquelle existiert ein Adapter, der deklarativ beschreibt, wie die Quelle gefetcht und extrahiert wird. Ein gemeinsames Framework kümmert sich um HTTP-Politik (robots.txt, Rate-Limit, Cache), Extraktions-Priorität und Regressionssicherheit durch Fixture-Snapshots. Ziel: Quelle fällt um oder baut um → das System meldet es, statt still falsche Daten zu liefern.

## Requirements

### Requirement: Deklarative Adapter-Konfiguration

- **Ablauf:** Ein Adapter definiert: Listing-URL(s), Pagination, Extraktionsregeln, Rate-Limit, robots-Policy (erlaubt/nicht erlaubt, dokumentiert), erwarteter Event-Mengenbereich, Sicht-Horizont.
- **Datei:** `app/adapters/<quelle>.py` bzw. `configs/<quelle>.yaml` + ggf. Mini-Parser; Registry in `app/adapters/__init__.py`.
- **Robots/ToS:** Jede Quelle führt im Adapter-Kommentar und in `docs/quellen.md` den robots.txt-/ToS-Befund.

#### Scenario: Neuen Adapter registrieren
- **Akteure:** Entwickler.
- **Eingaben:** Neue Quelle (z. B. voebb.de-Veranstaltungen) mit Konfiguration und Fixture.
- **Ergebnis:** Adapter erscheint in der Registry; `--quelle=alle` führt ihn mit aus; `docs/quellen.md` enthält den Audit-Eintrag.

### Requirement: Extraktions-Priorität JSON-LD → hEvent → CSS

- **Ablauf:** Beim Parsen einer Detail-/Listing-Seite wird in fester Reihenfolge versucht: (1) eingebettetes JSON-LD mit `@type: Event`, (2) hEvent-Microformate, (3) konfigurierte CSS-Selektoren, (4) Regex nur für Einzelfelder.
- **Zweck:** Robuste Extraktion ohne LLM; strukturierte Daten (JSON-LD) schlagen fragile Selektoren.

#### Scenario: Museum liefert JSON-LD, Bibliothek nicht
- **Akteure:** Adapter „museum-x“, Adapter „bibliothek-y“, Parser.
- **Eingaben:** Museum-Seite mit JSON-LD; Bibliotheks-Seite nur HTML-Liste.
- **Ergebnis:** Museum-Event vollständig aus JSON-LD extrahiert; Bibliotheks-Event über Selektoren; beide im gleichen Modell.

### Requirement: Fixture-Tests und Anomalie-Alarme

- **Ablauf:** Zu jedem Adapter gehört ein Fixture-Snapshot (gespeichertes HTML + erwartete Events) als Regressionstest; CI führt sie aus.
- **Anomalie:** Liefert eine Quelle `0 Events` oder weicht die Zahl um mehr als 50 % vom 7-Tage-Mittel ab, wird ein Alarm ausgelöst (ntfy/Matrix) — nie stiller Lauf.
- **Struktur-Hash:** Anzahl der Listing-Elemente je Lauf wird gespeichert; Abweichung > 20 % → Alarm „Adapter-Review nötig“.

#### Scenario: Site-Umbau bei jup.berlin
- **Akteure:** CI, Monitoring.
- **Eingaben:** jup.berlin ändert das Listing-HTML; Fixture-Test schlägt fehl.
- **Ergebnis:** CI rot mit Diff-Hinweis; Produktions-Lauf meldet Struktur-Anomalie; Alarm geht raus, bevor Nutzer leere Ergebnisse sehen.
