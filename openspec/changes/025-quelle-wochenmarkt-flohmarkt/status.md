# Change 025 — Wochenmärkte & Flohmärkte Berlin: live

Stand 2026-09-24 (angelegt, Regel ausgerollt, gelaufen, gemessen)

## Rollout

| Schritt | Ergebnis |
|---|---|
| Quelle anlegen (`POST /api/admin/sources`) | `wochenmarkt-flohmarkt`, Typ `regeln`, horizont 60 |
| Regel prüfen | `{"ok": true, "fehler": []}` |
| Regel speichern (`PUT …/regeln`) | gespeichert |
| Gegenprobe | `gespeicherte Regel == Repo-Vorlage: True` |
| Lauf 370 | **ok**, 18,2 s, 2 Quellseiten, **98 neu**, 0 geändert, 0 Fehler, 0 Warnungen |
| Deploy | `dsudk0x2gurfqrcm7aytvnzo`, `END=finished`, `running:healthy` |

Die Detail-`xpath`-Erweiterung im Adapter brauchte einen Deploy — er lief
**vor** dem Anlegen der Quelle, damit der Lauf sie schon nutzt.

## Gemessen am Bestand (98 Termine, `/api/events?quelle=wochenmarkt-flohmarkt`)

| Merkmal | Anzahl | Anteil |
|---|---|---|
| Termine | 98 | — |
| mit echter Uhrzeit (> 00:00) | **80** | 82 % |
| ohne Uhrzeit (Quelle liefert 00:00) | 18 | 18 % |
| mit Bezirk | **80** | 82 % |
| mit Koordinaten | 80 | 82 % |
| mit Ort **und** Adresse | **98** | 100 % |
| gleiche (Titel, Start) mehrfach | 0 | — |
| Zeitraum | 24.09.2026 … 24.11.2026 | 62 Tage |

**Die zwei Auffälligkeiten sind Quellendaten, keine Parserfehler** — beide sind
an echten Zeilen belegt:

- **18× ohne Uhrzeit** sind ausnahmslos „Berliner Kunstmarkt an der
  Museumsinsel" (Adresse `Am Zeughaus 1-2`, Bezirk `mitte` ✓). Die Quelle setzt
  dort im Kalender-Link `dates=20260905T000000/…` — also selbst 00:00. Die
  Regel erfindet keine Uhrzeit; die App zählt 00:00-Termine als ganztägig
  (`GANZTAGS_SQL`).
- **18× ohne Bezirk und ohne Koordinaten**: „Großer Trödelmarkt am Arkonaplatz"
  (9 Termine) und „Trödelmarkt Boxhagener Platz" (9). Die Adresse ist nur der
  Platzname (`Arkonaplatz`, `Boxhagener Platz`) — dafür findet die Geokodierung
  keine Straße. Diese 18 haben **eine** Uhrzeit, aber keinen Bezirk; sie sind
  damit im Bezirksfilter nicht sichtbar und auf der Karte ohne Punkt.

## Offen (ehrlich benannt)

- Die 18 platzgenauen Adressen warten auf Auflösung. Genau dafür gibt es seit
  Change 022 den Admin-Tab **„Ortsvorschläge"**: die Liste füllt sich aus dem
  Ortstext der Termine. Wenn dort „Arkonaplatz, 10435 Berlin" bzw. „Boxhagener
  Platz, 10245 Berlin" bestätigt wird, greifen Bezirk und Karte beim nächsten
  Lauf. Vorher von mir **nicht** von Hand eingetragen — Ortsangaben gehören in
  die Prüfliste, nicht stillschweigend in die Daten.
- **Reichweite der Quelle:** die erste Übersichtsseite reicht 63 Tage
  (24.09.–26.11.2026), `horizont_tage: 60` schöpft sie aus. Ältere/fernere
  Termine fehlen bewusst, weil die Seite in 100er-Schritten blättert und die
  Engine je Seite nur um 1 hochzählt (im Modulkopf der Regel und in
  `proposal.md` erklärt). Reicht der Horizont später nicht, ist die Lösung eine
  zweite Regel-URL mit `?start=100`, nicht `pagination`.
- Diese Quelle ist die erste **ohne Kinderprogramm und ohne Altersangabe**. Sie
  läuft ohne Altersband; der Altersfilter blendet sie nicht aus. Falls sie in
  der Oberfläche anders behandelt werden soll (eigene Kennzeichnung „Markt"),
  ist das ein eigener Change — hier bewusst nicht mitentschieden.
