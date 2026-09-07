# Change 005: Schul-Termine-Admin (Termin-CRUD, Schulen, Kategorien, Mail)

**Status:** In Arbeit (2026-09-07)
**Basis:** Change 002/003/004 (App deployed unter kinderkram.cia-spandau.de)

## Why

Die Schul-Dates-Erweiterung (Spec: doc.n0ne.de/S_E4lC8hSLGFrhgAtJYVmA) braucht
eine Pflege-Ebene für Termine, die nicht automatisch scrapebar sind
(Stufe B/C, Turnstile-geschützt, harte 403er): Tage der offenen Tür und
Infoabende werden von den Einrichtungen per E-Mail angefragt und müssen im
Admin-Backend gepflegt werden. Bisher kann das Admin nur Quellen/Regeln
verwalten — Termine sind reine Scrape-Artefakte ohne manuelle
Bearbeitungsmöglichkeit.

## What Changes

- **Admin-Route bleibt `/admin`** (existiert seit Change 002, offen ohne
  Auth — Schutz folgt später; weiterhin NICHT von der Startseite verlinkt).
- **Neue Admin-Tabs** (Navigationsleiste statt Abschnitte untereinander):
  `Quellen` (bestehend), `Termine`, `Schulen`, `Kategorien`.
- **Termine-Tab:** Liste aller Termine, filterbar/gegruppert **pro
  Einrichtung** (Schule); CRUD: Termin anlegen, bearbeiten, löschen.
  Bestehende Scrape-Termine (Quellen) sind sichtbar, aber nur manuell
  gepflegte Schul-Termine editierbar (Scrape-Termine werden vom nächsten
  Lauf überschrieben — keine sinnlosen Edit-Felder).
- **Schulen-Tab:** Liste der Berliner Schulen (aus Schul-WFS-Stamm,
  bsn/schulname/schulform/bezirk/email/website) mit je Termin-Anzahl;
  Schule = Einrichtung.
- **Kategorien-Tab:** Terminkategorien verwalten (z. B. „Tag der offenen
  Tür“, „Infoabend“, „Schnuppertag“, „Ferienangebot“) — Name + Farbe.
- **Mail-Versand aus dem Backend:** pro Schule (Einrichtung) eine
  vorformulierte Termin-Anfrage-Mail versenden; Status der Anfrage wird an
  der Schule vermerkt (angefragt_am). SMTP-Zugang über Einstellungen
  (Admin-Einstellungen-Tab) oder Env.
- **Frontend-Volltextsuche:** Suchfeld in der Karten-UI; nutzt den
  vorhandenen `q`-Parameter von `/api/events` (titel/beschreibung/ort).
- **Datenmodell:** neue Tabelle `schulen` (Einrichtungs-Stamm),
  `termin_kategorien`, `termine_manuell` (manuell gepflegte Schul-Termine,
  Bezug auf schule + kategorie, Vertrauens-Status) — bestehende
  `events`-Tabelle bleibt unangetastet (Scrape-Bestand).

## Specs-Delta

- `ADDED specs/schul-admin/spec.md` — Admin-Termin-/Schul-/Kategorien-
  Verwaltung + Mail-Versand.
- `MODIFIED specs/karte-ui/spec.md` — Req (Filter-Sidebar) um Volltextsuche
  ergänzt.

## Offene Punkte (vor Umsetzung klären)

1. Mail-Versand: SMTP-Zugang als **Admin-Einstellung** (Host/Port/User/Pass/
   From) — User trägt später einen echten Zugang ein; Versand-Endpunkt
   schlägt ohne konfigurierten SMTP sauber fehl (sichtbar, nicht still).
2. Vertrauens-Status der manuellen Termine: `ungeprueft` (Default, nach
   Mail-Anfrage) und `bestaetigt` (Antwort der Schule).
3. **Geklärt (2026-09-07):** Manuelle Termine erscheinen in der öffentlichen
   Karte NUR mit Status `bestaetigt`; `ungeprueft` bleibt Admin-intern.

## Downgrade

Downgrade = Stand Change 004: Admin zeigt wieder nur Quellen/Regeln/Läufe;
Schul-Tabellen und Mail-Funktion werden entfernt; Frontend-Suchfeld weg.
