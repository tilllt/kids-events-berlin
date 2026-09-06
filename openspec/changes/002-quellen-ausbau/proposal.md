# Change 002: Quellen-Ausbau — berlinmitkind, ZLB, familienportal

**Status:** In Arbeit (2026-09-06)
**Basis:** Change 001 (MVP, deployed auf Coolify unter kinderkram.cia-spandau.de)

## Why

Der MVP aggregiert nur jup.berlin (12 Events, ein Scrape). Für einen brauchbaren Berliner Kinder-Veranstaltungskalender fehlen die redaktionellen (berlinmitkind/HIMBEER), öffentlich-bibliothekarischen (ZLB) und landesoffiziellen (Familienportal) Quellen. Das Quellen-Audit (`docs/quellen.md`) hat alle drei als „aufnehmen“ priorisiert; die offenen Strukturfragen daraus werden in diesem Change live beantwortet und in Adaptern umgesetzt — weiterhin 100 % deterministisch ohne LLM.

## What Changes

- **Adapter berlinmitkind.de:** WordPress + Events-Manager; Detailseiten mit JSON-LD `@type: Event`. Listing via AJAX-Endpunkt oder Server-HTML (je nach Live-Befund). Nutzt den JSON-LD-Extraktionspfad des Frameworks (Spec-Req 2).
- **Adapter ZLB (zlb.de):** TYPO3-Veranstaltungsliste; Selektoren/URL-Muster werden live bestimmt (Audit offen). Kinder-/Familienfilterung regelbasiert beim Enrichment (kein Volltext-Kopieren).
- **Adapter familienportal.berlin.de:** offizielle Landes-Quelle; Struktur/Technik wird live verifiziert (Audit: Fetch schlug fehl, robots offen).
- **Duplikat-Politik kinderkulturkalender:** Einträge laufen über die jup!-Datenbasis → wird **nicht** als eigene Quelle aufgenommen; Befund und Entscheidung werden in `docs/quellen.md` festgehalten. Dedupe-Regel (jup vs. andere Quellen) nutzt vorhandenen Merge (Titel + Datum ± 1 + Venue).
- **Registry/CLI:** `--quelle=alle` führt alle produktiven Adapter aus; jeder Adapter mit Fixture-Snapshot und Mengenbereich.

## Specs-Delta

- `MODIFIED specs/quellen/spec.md` — Anforderungen für die drei neuen Adapter konkretisiert (Quellen-Matrix, JSON-LD-Pfad berlinmitkind, TYPO3/CSS-Pfad ZLB, familienportal nach Live-Befund); Duplikat-Entscheidung kinderkulturkalender dokumentiert.

## Downgrade

Downgrade = Stand von Change 001: Adapter-Registry ohne die drei neuen Quellen; entfernte Adapter-Dateien, Fixtures und `docs/quellen.md`-Einträge. Datenbank unter `data/` ist unversioniert; Events der neuen Quellen verschwinden nach `prune_stale`, kein Datenverlust am kanonischen Bestand.
