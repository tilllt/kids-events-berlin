# Change 008 — Umsetzung (2026-09-12, live)

## Was gebaut wurde
- `Store.entferne_ueberlappende_zwillinge(quelle)`: fasst je (Titel, Ort) Ketten
  mit **echter** Überlappung (start < Ende des Vorgängers) zusammen, behält den
  frühesten Start, `manuell=1` bleibt unangetastet. Aufruf in der Pipeline nach
  dem Upsert, vor der Stale-Bereinigung.
- `Store.prune_stale`: löscht nach `COALESCE(ende_iso, start_iso)` statt nach dem
  Start — mehrtägige, noch laufende Events überleben (der Dedup behält den
  frühesten Eintrag, mit Start-Bedingung fiel genau der laufende Workshop weg).

## Verifikation (Produktion)
- Überlappungs-Klumpen im Gesamtbestand: 9 → **0** (vorher 22 überzählige
  Einträge, 8 jup + 1 zlb).
- Milchhäuschen am Weißen See (MAXIM): 13 Einträge → **1** (12.–16.09., 10–16 Uhr).
- Gegenprobe echte Serientermine: ZLB „U-16-Wahllokal“ behält 09–10 / 10–11 /
  11–12 Uhr (berührende Slots), unverändert nach allen Läufen.
- Tests: 148 grün (u. a. `tests/test_serien_zwillinge.py` mit Prune-Fall).
