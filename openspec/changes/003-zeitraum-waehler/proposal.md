# Change 003: Zeitraum-Schnellwahl in der Filter-Sidebar

**Status:** In Arbeit (2026-09-06)
**Basis:** Change 001/002 (App deployed unter kinderkram.cia-spandau.de)

## Why

Veranstaltungen sind nur mit Zeitbezug nützlich — „was geht heute?“. Die bisherigen freien Von-/Bis-Date-Felder zwingen zum Tippen. Gewünscht ist eine Schnellwahl mit klaren Zeitfenstern, **„Heute“ als Default** beim Öffnen der Seite (statt ungefiltert alle Events).

## What Changes

- **UI:** Neues Filter-Segment „Wann“ mit vier Einzelwahl-Optionen: **Heute** (Default), **Morgen**, **Diese Woche** (heute bis heute+6, d. h. 7 Tage ab heute), **Nächste Woche** (heute+7 bis heute+13 — eine Woche ab in sieben Tagen).
- **Berechnung:** Tagesgrenzen in Europe/Berlin (clientseitig via `Intl`), API unverändert (`von`/`bis` inklusiv gegen `date(start_local)`, Bestand).
- **Interaktion:** Freie Von-/Bis-Felder bleiben; manuelle Änderung dort schaltet die Schnellwahl auf „Benutzerdefiniert“ (keine Option aktiv). Aktive Schnellwahl zeigt die berechneten Grenzen (Felder gefüllt, deaktiviert).
- **URL-State:** `zeitraum=heute|morgen|diese-woche|naechste-woche`; ohne Parameter gilt Default „Heute“; alte URLs mit `von`/`bis` bleiben gültig (→ benutzerdefiniert).
- **Reset:** setzt auf „Heute“ zurück.

## Specs-Delta

- `MODIFIED specs/karte-ui/spec.md` — Req 2 (Filter-Sidebar) um die Zeitraum-Schnellwahl ergänzt; Req 3-Leerzustand bleibt (Heute-Default kann leere Ergebnisliste zeigen → sichtbarer Leerzustand mit Reset-Vorschlag).

## Downgrade

Downgrade = Stand Change 002: Zeitraum-Segment entfernt, von/bis-Felder wie zuvor, Default ungefiltert.
