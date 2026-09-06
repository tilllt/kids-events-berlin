# Design — Change 002 Quellen-Ausbau (konfigurationsgetrieben)

## Leitprinzip (User-Vorgabe 2026-09-06)

Keine pro-Quelle handgeschriebenen Parser als Standard. Stattdessen:
- **Existierende Bibliotheken:** `parsel` (CSS/XPath, bereits Dependency) + `extruct` (JSON-LD/Microformats/Microdata/RDFa) — kein eigener Extraktions-Code-Standard.
- **Regeln sind Daten, nicht Code:** Eine generische Engine führt je Quelle eine YAML-Regeldatei aus. Selektoren (CSS/XPath), JSON-LD-Pfade, Datumsformate, Filter sind editierbar — angelehnt an changedetection.io (dort: XPath/CSS/JSONPath/jq als User-Regeln pro Watch, „Extract text“, „Remove by selector“).
- **User-korrigierbar im Betrieb:** Configs liegen versioniert unter `configs/` (Fixture-Tests laden sie) **und** werden zur Laufzeit aus `$DATA_DIR/configs/` überlesen (Volume-Overlay) → ein Admin korrigiert Selektoren per Datei-Edit, kein Rebuild/Code.
- **changedetection.io als Frühwarnung:** Je produktiver Quelle ein Watch auf die Listing-URL (Element-existiert/Text-Änderung) → Alarm bei Site-Umbau, bevor Fixture-Tests/Anomalie-Erkennung greifen (Betriebs-Task, Instanz + API vorhanden).

## Architektur

```
configs/<quelle>.yaml   (Regeln: listing, felder, jsonld-mapping, filter, menge)
        │  (Volume-Overlay: $DATA_DIR/configs/ gewinnt)
        ▼
app/adapters/config_adapter.py   (eine generische Engine, keine Quell-Parser)
   ├─ fetch: HTTP mit Rate-Limit/robots (bestehende Pipeline-Helfer)
   ├─ liste: item_css + Feld-Selektoren via parsel; Pagination (query-param oder next-css)
   ├─ detail/jsonld: extruct → @type:Event/@type:ItemList; Feld-Mapping per JSONPath (jsonpath-ng)
   └─ normalisieren → app.model.Event (Validierung/Enrichment unverändert)
```

- Die bestehende Req-2-Extraktionskette (JSON-LD → hEvent → CSS) wird durch `extruct` (json-ld, microformat, microdata) + `parsel`-Fallback abgebildet — Konfig wählt je Quelle den Pfad.
- `jup_berlin.py` bleibt vorerst (funktioniert, Sonderfälle Drupal-Pagination); Ziel: später ebenfalls auf Config umstellen → dann existiert genau EIN Adapter-Code.

## YAML-Schema (Entwurf)

```yaml
quelle: berlinmitkind          # Registry-Schlüssel
name: "berlinmitkind.de (HIMBEER)"
robots: "erlaubt; AI-Crawler geblockt (2026-09-06)"
rate_limit_s: 2
menge: {min: 5, max: 60}        # Anomalie-Schwellen
horizont_tage: 60
listing:
  url: "https://berlinmitkind.de/termine/"
  pagination: {param: "pg"}     # oder: next_css: "a.next"
  item_css: "article, .em-event-item"
felder:                          # parsel-CSS je Feld (attr optional)
  titel:  {css: ".event-title, h2 a"}
  url:    {css: "h2 a", attr: "href"}
  start:  {css: ".event-date", format: "%d.%m.%Y"}
  ort:    {css: ".event-location"}
  # statt css möglich: jsonld: "$.name"  (extruct-Pfad)
detail:
  jsonld: true                   # Detailseite: extruct @type:Event
  url_css: "h2 a"                # Listing-URLs → Details
  felder:
    beschreibung: {jsonld: "$.description"}
    adresse:      {jsonld: "$.location.address.streetAddress"}
filter_kinder: {regex: ["kind", "familie", "kinder", "eltern"]}   # Relevanz-Hinweis (Enrichment bleibt Hauptfilter)
```

## Ablauf je Quelle

1. Live-Erkundung (robots, Struktur, URL-Muster, JSON-LD) → Befunde in `docs/quellen.md`.
2. `configs/<quelle>.yaml` schreiben (Regeln als Daten).
3. Fixtures (Listing + 1–2 Details) unter `tests/fixtures/<quelle>/`.
4. Engine offline gegen Fixtures testen (kein Netz); Registry-Eintrag mit menge.
5. Online-Gegenprobe (`--quelle=alle`), idempotent; changedetection-Watch als Betriebs-Task.

## Risiken

- Zu fragile generische Engine → Regeln wachsen; Gegenmittel: Fixture-Tests je Quelle bleiben Pflicht (Spec Req 3).
- Config-Schema zu starr für Sonderfälle (AJAX, Auth) → Schema um `fetch:`-Hinweise (headers, json_endpoint) erweiterbar; wenn eine Quelle echte Sonderlogik braucht, wird sie als dokumentierte Ausnahme mit Begründung geführt — nicht der Standard.
- Volume-Overlay divergiert vom Repo → Overlay-Eintrag wird bei jedem Lauf geloggt (quelle + hash), `docs/quellen.md`-Hinweis.
