# Tasks — Change 002 Quellen-Ausbau (konfigurationsgetrieben)

Reihenfolge mit TDD; nach jeder Aufgabe committen. **Leitprinzip: keine pro-Quelle-Parser; Regeln als YAML-Daten, ausgeführt von einer generischen Engine (parsel + extruct); user-korrigierbar via Volume-Overlay.**

## Phase 0 — Engine (generisch, einmal)

- [ ] Deps: `extruct`, `jsonpath-ng` zu pyproject (parsel vorhanden); Dev-Umgebung aktualisieren
- [ ] `configs/`-Loader: YAML aus Paket-`configs/` + Overlay `$DATA_DIR/configs/` (Overlay gewinnt, Log mit Quelle+Hash); Schema-Validierung
- [ ] `app/adapters/config_adapter.py`: listing (item_css, Feld-CSS inkl. attr, Datums-`format`, Pagination query-param/next_css), JSON-LD-Detailpfad via extruct (Feld-Mapping JSONPath), Normalisierung → Event-Modell
- [ ] Registry: config-Adapter liest `configs/*.yaml`; `--quelle=alle` führt alle produktiven Quellen; Mengenbereich je Quelle
- [ ] Tests: Loader (Overlay gewinnt), Engine gegen synthetisches HTML + JSON-LD-Fixture

## Phase 1 — Quelle berlinmitkind.de (JSON-LD-Pfad)

- [ ] Live-Erkundung: Listing-URL/Struktur, Detail-JSON-LD-Felder → docs/quellen.md
- [ ] `configs/berlinmitkind.yaml` (Regeln) + Fixtures (Listing + 2 Details)
- [ ] Engine offline grün; Online-Gegenprobe idempotent

## Phase 2 — Quelle zlb.de (CSS/TYPO3-Pfad)

- [ ] Live-Erkundung: Listen-/Detail-Selektoren → docs/quellen.md
- [ ] `configs/zlb.yaml` + Fixtures
- [ ] Engine offline grün; Online-Gegenprobe idempotent

## Phase 3 — Quelle familienportal.berlin.de

- [ ] Live-Erkundung (Erreichbarkeit/Struktur); falls parsebar → `configs/familienportal.yaml` + Fixtures + Gegenprobe; sonst Status „pending“ + Grund dokumentiert

## Phase 4 — Betrieb + Doku

- [ ] Duplikat-Befund kinderkulturkalender→jup dokumentieren (keine eigene Quelle)
- [ ] `docs/quellen.md`: Quellen-Matrix + „Regeln anpassen“-Anleitung (Overlay, Selektoren, Fixture-Pflicht)
- [ ] changedetection.io-Watch je produktiver Listing-URL (Element-existiert) als Frühwarnung; Anomalie-Alarm-Pipeline unverändert
- [ ] pytest gesamt grün; Commit; Deploy (kinderkram.cia-spandau.de); Events neuer Quellen sichtbar
- [ ] (optional, separat) jup_berlin.py auf config_adapter migrieren → ein Adapter-Code

## Abnahme-Kriterien

- Kein neuer Quell-Parser-Code außerhalb der generischen Engine; neue Quellen = nur `configs/*.yaml` + Fixtures
- Regel-Änderung (Selektor) ohne Code-Deploy möglich: Datei ins Volume-Overlay → nächster Lauf nutzt sie (Log-Beleg)
- pytest grün; Online-Läufe je Quelle > 0 Events und idempotent; kinderkulturkalender nicht in Registry
