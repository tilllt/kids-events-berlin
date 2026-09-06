# Change 002: Quellen-Ausbau — berlinmitkind, ZLB, familienportal

**Status:** In Arbeit (2026-09-06)
**Basis:** Change 001 (MVP, deployed auf Coolify unter kinderkram.cia-spandau.de)

## Why

Der MVP aggregiert nur jup.berlin (12 Events, ein Scrape). Für einen brauchbaren Berliner Kinder-Veranstaltungskalender fehlen die redaktionellen (berlinmitkind/HIMBEER), öffentlich-bibliothekarischen (ZLB) und landesoffiziellen (Familienportal) Quellen. Das Quellen-Audit (`docs/quellen.md`) hat alle drei als „aufnehmen“ priorisiert; die offenen Strukturfragen daraus werden in diesem Change live beantwortet und in Adaptern umgesetzt — weiterhin 100 % deterministisch ohne LLM.

## What Changes

- **Feed-first-Adapter (Stufe 1):** Generischer Feed-Adapter (RSS/Atom via `feedparser`, iCal via `icalendar`) — eine Quelle anbinden heißt: URL + Typ in `configs/quellen.yaml` eintragen. Kein Selektor-Wissen nötig.
- **Regel-Adapter (Stufe 2, nur Fallback ohne Feed):** Generische Engine mit YAML-Regeln (`parsel` CSS/XPath, `extruct` JSON-LD/Microformats); Regeln als editierbare Daten (Repo + Volume-Overlay), keine pro-Quelle-Parser.
- **Benutzerfreundlichkeit:** Quellen-Konfiguration als eine kommentierte YAML-Liste; Anleitung in Alltagssprache; Fixture-Selbsttest bei Regel-Änderung. changedetection.io nur optionale Frühwarnung, kein Dogma.
- **Adapter berlinmitkind.de, zlb.de, familienportal.berlin.de** über das Stufenmodell (Entscheidung je Quelle nach Live-Feed-Suche); jup.berlin wird auf Feed geprüft (falls vorhanden: MVP-Parser entfällt).
- **Duplikat-Politik kinderkulturkalender:** läuft über die jup!-Datenbasis → nicht als eigene Quelle; Befund in `docs/quellen.md`.

## Specs-Delta

- `MODIFIED specs/quellen/spec.md` — Anforderungen für die drei neuen Adapter konkretisiert (Quellen-Matrix, JSON-LD-Pfad berlinmitkind, TYPO3/CSS-Pfad ZLB, familienportal nach Live-Befund); Duplikat-Entscheidung kinderkulturkalender dokumentiert.

## Downgrade

Downgrade = Stand von Change 001: Adapter-Registry ohne die drei neuen Quellen; entfernte Adapter-Dateien, Fixtures und `docs/quellen.md`-Einträge. Datenbank unter `data/` ist unversioniert; Events der neuen Quellen verschwinden nach `prune_stale`, kein Datenverlust am kanonischen Bestand.
