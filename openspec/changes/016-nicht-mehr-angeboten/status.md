# Change 016 — Nicht mehr angebotene Termine entfernen (zuletzt gesehen)

## Warum

Befund des Nutzers vom 2026-09-13: **242 Termine** im Bestand hatten ein
Startdatum in der Vergangenheit und wurden von den Quellen **nicht mehr
angeboten** — sie wurden beim Neu-Einlesen nie wieder angefasst und behielten
deshalb ihren alten Zustand (Ort „Ohne Angabe", keine Kartenposition). Genau
diese Zeilen waren auch die Ursache der früheren Meldung „Die App zeigt Events
von gestern".

Bisherige Bereinigung: `prune_stale` löscht Termine einer Quelle, die **vor
drei Tagen enden** — also erst nachlaufend, mit drei Tagen Verzug, und
unabhängig davon, ob die Quelle den Termin noch anbietet.

## Was

1. Neue Spalte `events.zuletzt_gesehen` (Migration idempotent, Alt-DBs werden
   ergänzt).
2. `Store.markiere_gesehen(quelle, source_event_ids, zeit)`: Bei jedem Lauf
   wird für alle Termine, die die Quelle **noch anbietet**, der Zeitstempel
   gesetzt — auch wenn sich inhaltlich nichts geändert hat (der normale
   Schreibpfad schreibt nur echte Änderungen und würde hier nichts tun).
3. `Store.entferne_nicht_mehr_angeboten(quelle, lauf_start, ok)`: löscht
   Termine einer Quelle, die
   - von der Quelle **nicht mehr angeboten** wurden (zuletzt_gesehen fehlt oder
     liegt vor dem Laufbeginn), **und**
   - deren Starttag in der Vergangenheit liegt (Mehrtagestermine bleiben
     erhalten, solange sie laufen).

   Bei `ok = False` (Lauf mit Fehlern) wird **nichts** gelöscht — ein halb
   gelesenes Listing darf keinen Termin kosten.

Deterministisches Signal statt Fristenschätzung: **die Quelle selbst** sagt,
was sie noch anbietet.

## Verifikation

- Tests: nicht gesehen + Vergangenheit → entfernt; nicht gesehen + Zukunft →
  bleibt; gesehen + Vergangenheit → bleibt (laufender Mehrtagestermin);
  Fehlerlauf → nichts passiert.
- Produktion: Anzahl Termine mit Vergangenheits-Start vor und nach dem Lauf,
  aufgeschlüsselt je Quelle (Erwartung: die nicht mehr angebotenen verschwinden
  sofort, statt nach drei Tagen).

## Offen

- Anzeige: Termine mit Vergangenheits-Start bleiben zusätzlich aus der Liste
  ausgeblendet (Filter „heute/demnächst"), damit ein Quellenfehler nie sichtbar
  wird.
