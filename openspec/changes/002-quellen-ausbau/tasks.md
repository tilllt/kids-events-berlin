# Tasks — Change 002 Quellen-Ausbau

Reihenfolge mit TDD; nach jeder Aufgabe committen (`feat:`/`test:`/`docs:`).

## Phase 0 — Live-Erkundung (Befunde → docs/quellen.md)

- [ ] berlinmitkind.de: robots (bereits offen, AI-Crawler geblockt), Listing-URL, AJAX-Endpunkt oder Server-HTML, Detail-JSON-LD-Felder dokumentieren
- [ ] zlb.de: Veranstaltungs-Listen-URL(s), Artikel-Selektoren, Datums-Muster, Detail-URL-Form, Kinder-Events-Anteil dokumentieren
- [ ] familienportal.berlin.de: Erreichbarkeit (UA/Retry), Technik, Listen-/Detailstruktur dokumentieren; falls blockiert: Status „pending“ + Grund
- [ ] kinderkulturkalender-berlin.de: Duplikat-Befund zu jup.berlin verifizieren (gleiche Events?) → Entscheidung in docs/quellen.md

## Phase 1 — Adapter berlinmitkind.de

- [ ] Fixtures: Listing + 2 Detailseiten (davon ≥ 1 Kinder-Event mit JSON-LD)
- [ ] `app/adapters/berlinmitkind.py`: Listing-Parser + JSON-LD-Detailparser → Event-Modell (Titel, Zeit, Ort, URL, Beschreibung)
- [ ] Registry + Mengenbereich; Tests gegen Fixtures; Enrichment-Regeln (kostenlos/Alter) greifen

## Phase 2 — Adapter ZLB (zlb.de)

- [ ] Fixtures: Listen-Seite(n) + 1 Detailseite
- [ ] `app/adapters/zlb.py`: TYPO3-Artikel-Parser (Titel/Datum/Zeit/Ort/URL), Regel-Filter Kinder/Familie am Enrichment
- [ ] Registry + Mengenbereich; Tests gegen Fixtures

## Phase 3 — Adapter familienportal.berlin.de

- [ ] Fixtures (nach Live-Befund; falls Seite nicht parsebar → Task entfällt mit Begründung)
- [ ] `app/adapters/familienportal.py` nach Befund
- [ ] Registry + Mengenbereich; Tests gegen Fixtures

## Phase 4 — Integration + Verifikation

- [ ] `--quelle=alle` läuft alle produktiven Adapter (offline: Fixtures); Online-Gegenprobe je Quelle: > 0 Events, 2. Lauf `n_neu=0`
- [ ] `docs/quellen.md` + README aktualisiert (Quellen-Matrix, Duplikat-Entscheidung)
- [ ] pytest gesamt grün; Commit; Deploy über Coolify (kinderkram.cia-spandau.de), Events der neuen Quellen sichtbar

## Abnahme-Kriterien

- pytest grün (alle Fixture-Adapter offline)
- Online-Läufe je neuer Quelle: > 0 Events, idempotent
- API `/api/events?quelle=…` liefert Events der neuen Quellen mit Provenienz
- kinderkulturkalender nicht in Registry; Entscheidung dokumentiert
