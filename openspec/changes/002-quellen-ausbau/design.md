# Design — Change 002 Quellen-Ausbau

## Leitprinzipien (User-Vorgaben 2026-09-06)

1. **Benutzerfreundlichkeit ist Priorität** — für Betreiber UND Endnutzer. Quelle anbinden soll so einfach wie ein Abo sein; Regeln pflegen muss ohne Code/ohne Expertenwissen gehen; die Kinder-Events-UI bleibt einfach.
2. **Feed-first statt Selektor-Pflege:** RSS/Atom/iCal/JSON-Endpunkte konsumieren, bevor HTML geparst wird. Feeds (WordPress `/feed/`, Drupal `rss.xml`, TYPO3-RSS) brechen nicht bei Layout-Umbauten → deutlich weniger Wartung, kein Regeln-Basteln. changedetection.io war nur Referenz für das Konzept „Regeln als User-Daten“ — kein Dogma.
3. **Existierende, gepflegte Bibliotheken statt Eigenbau:** `feedparser` (RSS/Atom), `icalendar` (iCal), `parsel` (CSS/XPath), `extruct` (JSON-LD/Microformats). Kein Custom-Scraping-Code-Standard.
4. **Regeln sind Daten, user-korrigierbar:** Wenn doch Selektoren nötig sind (kein Feed), als einfache YAML-Regeldatei — versioniert + als Volume-Overlay editierbar, ohne Rebuild.

## Stufenmodell je Quelle

| Stufe | Mechanik | Aufwand Betreiber | Bibliothek |
|---|---|---|---|
| 1 (bevorzugt) | Feed-Abo: RSS/Atom/iCal/JSON-Endpunkt | URL + Typ angeben | feedparser, icalendar |
| 2 (Fallback) | Regeldatei: Item-/Feld-Selektoren oder JSON-LD-Pfade | YAML editieren (dokumentiert, Fixture-Selbsttest) | parsel, extruct |
| 3 (Ergänzung) | changedetection.io-Watch auf Listing-URL | Watch anlegen | changedetection-API |

Entscheidung je Quelle fällt bei der Live-Erkundung: **erst nach Feed suchen** (`/feed/`, `rss.xml`, `<link rel="alternate" type="application/rss+xml">`, iCal-Export). Quellen mit Feed landen auf Stufe 1, ohne Feed auf Stufe 2.

## Architektur

```
configs/quellen.yaml  (einfache Liste: quelle, name, typ: feed|regeln, url, menge, rate_limit)
   └─ Overlay: $DATA_DIR/configs/quellen.yaml gewinnt (Edit ohne Rebuild, Log mit Hash)

app/adapters/feed_adapter.py     generisch: feedparser/icalendar → Event-Modell
app/adapters/selector_adapter.py generisch: YAML-Regeln (parsel/extruct) → Event-Modell
   (jeweils: Fetch mit Rate-Limit/robots, Normalisierung, kein Quell-Parser-Code)
```

- Konfig-Datei bleibt **eine einfache, kommentierte YAML** (kein tiefes Regelwerk für Feed-Quellen).
- Validierung/Enrichment/Dedupe/Store unverändert (Change-001-Pipeline).
- `jup_berlin.py` bleibt bis zur Feed-Prüfung; falls jup.berlin einen RSS/JSON-Feed hat, wird der MVP-Adapter auf Stufe 1 umgestellt (ein Code-Pfad weniger).

## Ablauf je Quelle

1. Live-Erkundung: robots → **Feed suchen** → sonst Struktur/JSON-LD → Befund in `docs/quellen.md`.
2. Quelle in `configs/quellen.yaml` (Stufe 1) bzw. `configs/regeln/<quelle>.yaml` (Stufe 2) eintragen.
3. Fixtures (Feed-Antwort bzw. HTML) unter `tests/fixtures/<quelle>/`; Engine offline grün.
4. Online-Gegenprobe idempotent; changedetection-Watch nur als optionale Frühwarnung.

## Risiken

- Feed unvollständig (nur Titel/Link, kein Datum/Ort) → Stufe 2 Detail-Regeln oder Quelle zurückstellen; nie stiller Datenmangel (Validierungs-Queue).
- iCal-Zeitzonen (Europe/Berlin) → icalendar-Parsing normalisiert auf *_local wie bisher.
- Overlay divergiert → Lauf loggt Quelle + Hash; docs-Hinweis.
