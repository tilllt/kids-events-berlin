# Tasks — Change 002 Quellen-Ausbau

Reihenfolge mit TDD; nach jeder Aufgabe committen. **Prinzip: Benutzerfreundlichkeit zuerst → Feed-first (Stufe 1) vor Selektoren (Stufe 2); existierende Bibliotheken; Regeln als editierbare Daten.**

## Phase 0 — Feed-Adapter (generisch, bevorzugter Weg)

- [ ] Deps: `feedparser`, `icalendar` (+ `extruct`, `jsonpath-ng` für Stufe 2) zu pyproject
- [ ] `configs/quellen.yaml`: einfache Quellen-Liste (quelle, name, typ: feed|regeln, url, menge, rate_limit, horizont); Overlay-Loader `$DATA_DIR/configs/` (gewinnt, Log mit Hash)
- [ ] `app/adapters/feed_adapter.py`: RSS/Atom via feedparser, iCal via icalendar → Event-Modell (Titel, start/ende, ganztags, Ort, URL, Beschreibung); Zeitnormalisierung Europe/Berlin
- [ ] Registry: `--quelle=alle` führt feed- und regel-Quellen; Mengenbereich je Quelle
- [ ] Tests: Loader (Overlay), feedparser/icalendar-Fixtures (synthetisch)

## Phase 1 — Quelle berlinmitkind.de

- [ ] Live-Erkundung: robots → Feed suchen (WP `/feed/`, `/events/feed/`) → sonst AJAX/JSON-LD → docs/quellen.md
- [ ] Bei Feed: Eintrag in `configs/quellen.yaml` + Fixture; sonst `configs/regeln/berlinmitkind.yaml`
- [ ] Engine offline grün; Online-Gegenprobe idempotent

## Phase 2 — Quelle zlb.de

- [ ] Live-Erkundung: Feed suchen (TYPO3-RSS) → sonst Listen-/Detail-Selektoren → docs/quellen.md
- [ ] Konfig + Fixtures; offline grün; Online-Gegenprobe idempotent

## Phase 3 — Quelle familienportal.berlin.de (+ jup-Feed-Prüfung)

- [ ] Live-Erkundung familienportal (Erreichbarkeit, Feed/Struktur); falls parsebar → Konfig; sonst Status „pending“ + Grund
- [ ] jup.berlin auf RSS/JSON-Feed prüfen → falls vorhanden: MVP-Adapter auf feed_adapter umstellen (Entfall `jup_berlin.py`-Parser)

## Phase 4 — Betrieb + Doku

- [ ] Duplikat-Befund kinderkulturkalender→jup dokumentieren (keine eigene Quelle)
- [ ] `docs/quellen.md`: Quellen-Matrix + „Quelle hinzufügen“-Anleitung (Stufe 1/2, Overlay, Fixture-Pflicht) — in Alltagssprache
- [ ] changedetection.io-Watch optional je Stufe-2-Quelle (Frühwarnung)
- [ ] pytest grün; Commit; Deploy (kinderkram.cia-spandau.de); Events neuer Quellen sichtbar

## Abnahme-Kriterien

- Neue Quelle OHNE Feed → nur YAML (kein Python); MIT Feed → nur Listeneintrag
- Regel-/Config-Änderung per Overlay-Edit wirkt beim nächsten Lauf (Log-Beleg), kein Rebuild
- pytest grün; Online-Läufe je Quelle > 0 Events, idempotent; kinderkulturkalender nicht in Registry
