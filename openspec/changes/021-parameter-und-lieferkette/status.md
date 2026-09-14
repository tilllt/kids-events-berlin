# Change 021 — Prüfungen für Parameternamen, Auslieferung und Gate

**Status:** umgesetzt, Tests grün (2026-09-14). Reine Absicherung — kein
Nutzungsverhalten ändert sich.

## Warum

Drei Fehler derselben Art waren in kurzer Folge aufgetreten und jeweils nur
durch Zufall aufgefallen:

1. `km` im Frontend gegen `umkreis_km` in der API → der Umkreis kam nie an.
2. `zeitstufe` in der App-Adresse gegen `uhrzeit` in `/api/kalender.ics` → der
   Zeitfilter fehlte im Kalender-Abo (579 statt 222 Termine).
3. Bei jedem Deploy musste die Versionsnummer der statischen Dateien von Hand
   erhöht werden; einmal vergessen heißt „Änderung kommt nicht an“, obwohl die
   Datei live ist.

Dazu kam eine Schwäche des Deploy-Gates: `git add -A` nahm auch Dateien mit,
die erst **während** des Testlaufs entstanden waren.

## Änderung

1. **`tests/test_parameternamen.py`** (5 Tests) liest die Namen aus den
   statischen Dateien und den echten FastAPI-Signaturen und prüft:
   jeder durchgereichte Filter existiert im Ziel-Endpunkt; die
   Ausschlussliste des Abos enthält keine erfundenen Schlüssel; jeder im
   Frontend gesetzte Parameter existiert überhaupt irgendwo.
   Der Test fand sofort einen echten Rest: `seite` in `NICHT_IM_ABO` gehörte zu
   einer Paginierung, die es nicht mehr gibt — entfernt.
2. **`test_static_dateien_mit_versionsnummer`** (in `test_frontend_layout.py`):
   jede Datei unter `/static/` braucht `?v=N`, und alle dieselbe Nummer —
   ein Knopf statt drei. `cia-logo.svg` hatte keine.
3. **Gate gehärtet** (`/opt/data/deploy_gate.sh`):
   - Der Arbeitsbaum wird vor dem Testlauf festgehalten (Namen **und**
     Inhalte) und danach verglichen. Ändert er sich während des Laufs, bricht
     das Gate ab und **nennt** die Dateien, statt sie mitzucommitten.
   - Committet wird nur der festgehaltene Stand (`git add -A -- <pfade>`),
     optional auf beim Aufruf genannte Pfade eingeschränkt.
   - Ein Lauf ohne Änderungen bricht sauber ab (Exit 8) statt in einen
     fehlgeschlagenen Commit zu laufen.

## Verifiziert

- Voller Lauf: **330 Tests grün** (16 Ortsregel, 5 Parameternamen, 2 Zeitzone,
  1 Versionsnummer, 1 neuer Schultest-Aufruf …). Ausgangslage war ein roter
  Test (Tagesbudget) — der ist in Change 020 erklärt und behoben.
- Der Gate-Lauf selbst ist der Beweis für Punkt 3: er hat diese Änderung
  committet, gepusht, deployt und die Bereitschaft abgewartet.
