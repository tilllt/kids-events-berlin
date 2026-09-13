# Change 011 — Dieselbe Veranstaltung darf nicht mehrfach im Bestand stehen

**Status:** Umgesetzt und in Produktion verifiziert (2026-09-13)
**Basis:** Change 008 (Serien-Zwillinge innerhalb einer Quelle)

## Why (gemessen 2026-09-13, kinder.cia-spandau.de-Bestand)

Die bisherige Bereinigung wirkt nur INNERHALB einer Quelle: `upsert_event`
suchte Zwillinge mit `quelle=? AND titel=? AND start_iso=? AND ort=?`, und
`entferne_ueberlappende_zwillinge` arbeitet ausschließlich für eine übergebene
Quelle. Quellenübergreifende Dubletten waren damit strukturell unsichtbar.

Befund im öffentlichen Bestand (1.733 Events):
- **195 überzählige Zeilen** in 167 Gruppen waren dieselbe Veranstaltung aus
  zwei Quellen (11,3 %). Quellen-Paare: familienportal+museumsportal 78,
  familienportal+kinderkulturkalender 72, familienportal+jup-berlin 15.
- Anlassfall: ein Tag der offenen Tür der Klax Kinderkrippen stand **57×** im
  Bestand (29× familienportal, 28× Kinderkulturkalender) — je Einrichtung
  doppelt, mit abweichendem Ortsfeld („Klax Kinderkrippe Mäusekiste" vs.
  „Berlin") und abweichender Endzeit (nur eine Quelle hatte sie).
- Zusätzlich 33 Gruppen mit exakter Doppelung INNERHALB einer Quelle
  (z. B. ZLB „Wahllokal für Schulklassen" 3×).

## What Changes

- **Identitätsregel statt Zeichengleichheit.** Zwei Datensätze sind dieselbe
  Veranstaltung, wenn ALLE Bedingungen zutreffen: gleicher Tag; Titel gleich
  nach Normalisierung (Kleinschreibung, Umlaut-Faltung, Satzzeichen); Uhrzeit
  gleich, wenn beide eine haben (fehlende Zeit = ganztags/unbekannt); Ortsname
  verträglich UND Koordinaten ≤ 200 m.
- **Schutz gegen falsche Merges (User-Vorgabe):** verschiedene Titel am selben
  Ort zur selben Zeit bleiben verschiedene Veranstaltungen — das ZLB bietet
  genau das an. Gleicher Titel in Stundenblöcken (09/10/11 Uhr) wird NICHT
  zusammengeführt; gleicher Titel an zwei echten Orten (zwei Sternwarten)
  ebenso wenig. Beides erscheint als **Verdachtsfall** im Bericht, nie als
  automatischer Merge: 168 Verdachtsfälle im Produktivbestand, davon
  „andere_uhrzeit" und „anderer_ort_name" (nachprüfbar in der Admin-GUI).
- **Zwei Ebenen der Durchsetzung:**
  1. beim Schreiben (`upsert_event`): ein identischer Termin wird sofort
     zusammengeführt — die Invariante, die 79-fache Einträge verhindert;
  2. `merge_doppelte_events()` räumt Altbestand auf und läuft nach jedem
     Quellen-Lauf automatisch mit (Zähler im Lauf-Ergebnis).
- **Kanon und Provenienz:** kanonisch ist der manuell gepflegte Satz, sonst die
  amtliche Quelle vor Einrichtung vor Aggregator; leere Felder des Kanons werden
  aus der Dublette gefüllt (real: Endzeit), die weiteren Quellen wandern als
  Provenienz nach `events.quellen_json` (ein Eintrag je weiterer Quelle).
- **Sichtbar statt still:** Admin-GUI (Einstellungen → Dubletten) mit
  „Prüfen" (Probelauf, ändert nichts) und „Gefundene zusammenführen"; Bericht
  mit Beispielen und Verdachtsfällen. CLI `dedupe-audit [--apply]`.
  API: `GET /api/admin/dedupe`, `POST /api/admin/dedupe/anwenden`.

## Nebenbefunde, die mitbehoben wurden

Zwei echte Fehler, die der erste Feldlauf der Schul-Recherche aufdeckte:
- Website-Werte aus dem Schul-WFS enthalten Steuerzeichen (`"\\rhttps://…"`) →
  httpx brach mit `InvalidURL` ab und **riss den kompletten Recherche-Lauf mit**.
  Jetzt: URL-Säuberung beim Abruf und beim Import, und eine unerwartete Ausnahme
  je Schule beendet den Lauf nicht mehr (sie wird als `fehler` mit Klartext an
  der Schule vermerkt).
- Ein LLM-Endpunkt, der HTML statt JSON liefert (Proxy-Fehlerseite), meldet
  jetzt einen klaren Fehler statt eines unerwarteten Ausnahmefalls.

## Specs-Delta

- `ADDED specs/schul-recherche/spec.md` bleibt unverändert gültig.
- Die Dedupe-Regeln gehören in die Aggregations-Capability; bis zur
  Archivierung sind sie hier dokumentiert (Live-Spec-Anpassung folgt mit der
  nächsten Spec-Runde, damit die Anwendung der Deltas in einem Zug passiert).

## Risiken

- Konservative Zeitregel: dieselbe Veranstaltung mit abweichender Startzeit
  (10:00 vs. 10:30) bei zwei Quellen wird NICHT automatisch gemergt, sondern
  gemeldet. Gewählt, weil eine Toleranz echte Stundenblöcke (ZLB) verschmelzen
  würde — falsch gelöschte Termine sind teurer als ein sichtbarer Verdacht.
- Titelvarianten mit Füllwörtern („Sonne, Mond und Sterne" vs. „Sonne Mond
  Sterne") bleiben getrennt; im Produktivbestand blieben dadurch Klax-Zeilen
  stehen (32 statt der angestrebten 29). Nächster Schritt, falls gewünscht:
  Füllwort-Normalisierung (und/der/die/im/in/am/an) in `dedupe.titel_norm`.
