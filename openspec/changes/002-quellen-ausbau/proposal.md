# Change 002: Quellen-Ausbau + Admin-Konfiguration

**Status:** In Arbeit (2026-09-06)
**Basis:** Change 001 (MVP, deployed unter kinderkram.cia-spandau.de)

## Why

Der MVP aggregiert nur jup.berlin. Für einen brauchbaren Berliner Kinder-Veranstaltungskalender fehlen weitere Quellen (ZLB, berlinmitkind, familienportal). Zugleich gilt die Vorgabe: **alle konfigurierbaren Optionen sind über eine GUI bearbeitbar** (Admin-Sektion; Schutz/Auth folgt später, zunächst offen konzipiert) — Quelle anbinden und Regeln pflegen ohne Code, ohne Datei-Edits, ohne Expertenwissen. Feed-first (Stufe 1) vor HTML-Selektoren (Stufe 2); existierende Bibliotheken statt Eigenbau.

## What Changes

- **Konfigurations-Persistenz in der Datenbank** (SQLite-Tabellen `sources`, `regeln`, `settings`), gelesen vom Adapter-Loader und Scheduler — kein YAML-Overlay im Volume. Beim ersten Start werden Default-Quellen (jup-berlin) geseedet; YAML-Dateien entfallen als Betriebsweg.
- **Admin-API (offen, später geschützt):** `/api/admin/sources` (CRUD: Name, Typ feed|regeln, URL, Rate-Limit, Mengenbereich, Aktiv, robots-Notiz), `/api/admin/sources/{quelle}/regeln` (Selektoren/JSON-LD/Formate lesen+schreiben), `/api/admin/sources/{quelle}/validate` (Schema-, YAML- und Selektor-Prüfung mit verständlichen Meldungen), `/api/admin/runs` + `/api/admin/errors` (Status letzter Läufe, Fehler-Queue sichtbar), `/api/admin/settings` (z. B. Scrape-Intervall). Klar als Admin-Router getrennt, später per Auth-Middleware geschützt.
- **Admin-UI (`/admin`):** deutsche, kompakte Oberfläche: Quellen-Liste (Status, Events, letzter Lauf, Fehler) mit Anlegen/Bearbeiten/Löschen, Regel-Editor je Quelle (validiert, mit Vorlage), Einstellungen. Zunächst ohne Login (Hinweis in der UI + Doku „vor Produktivgang schützen“).
- **Generische Adapter-Engine (Stufe 1 + 2):** `feed_adapter` (RSS/Atom via feedparser, iCal via icalendar) und `selector_adapter` (YAML-artige Regeln aus der DB: parsel CSS/XPath, extruct JSON-LD/Microformats) — keine pro-Quelle-Parser. Beide erfüllen das bestehende Pipeline-Interface (slug-Modell).
- **Quellen:** zlb.de (Teaser-CSS, verifiziert), berlinmitkind.de (AJAX + JSON-LD-Details), familienportal.berlin.de (Stufe 2) über die Engine; jup.berlin bleibt bestehen (kein Feed, rss.xml = News).
- **Duplikat-Politik:** kinderkulturkalender läuft über die jup!-Datenbasis → nicht als Quelle; Befund in `docs/quellen.md`.

## Specs-Delta

- `ADDED specs/admin/spec.md` — Admin-Konfiguration: DB-Persistenz, offene API/UI (Schutz später), Quellen-CRUD, Regel-Editor mit Validierung, sichtbare Läufe/Fehler
- `MODIFIED specs/quellen/spec.md` — Quellen-Matrix, Feed-first, generische Engine statt Quell-Parser

## Downgrade

Downgrade = Stand Change 001: Admin-Tabellen/Endpunkte/UI entfernt, Registry nur jup-berlin, `data/`-DB unversioniert (kann gelöscht werden), Container ohne Datenverlust neu baubar.
