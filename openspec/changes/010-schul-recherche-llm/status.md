# Change 010 — Status (Feldprobe 2026-09-13)

## Feldprobe: alle Grundschulen in Friedrichshain-Kreuzberg

Lauf über die produktive Instanz (`POST /api/admin/recherche/lauf` mit
`bezirk=friedrichshain-kreuzberg, schulform=Grundschule, limit=40`), Modell
**lokal auf der KI-Box** (`llamacpp-gemma4-12B-unsloth`), Thinking aus.

- **34 von 34 Schulen geprüft** (35 FK-Grundschulen, eine ohne Website im Stamm)
  in **224 s** (~6,6 s je Schule) → Hochrechnung 722 Schulen: ca. 80 min/Nachtlauf.
- **23 LLM-Aufrufe** (der Vorfilter hat 11 Schulen ohne Terminstelle mit Datum
  gespart — dort wurde gar nicht erst gefragt).
- **9 Schulen mit belegten Funden → 11 Terminvorschläge**, alle als `ungeprüft`
  in der Termin-Queue (nichts davon öffentlich):

| Datum | Zeit | Titel | Schule |
|---|---|---|---|
| 15.09.2026 | — | Tag der offenen Tür | 02G26 Lemgo-Grundschule |
| 21.09.2026 | 18:00 | Infoabend | 02G21 Reinhardswald-Grundschule |
| 22.09.2026 | — | Tag der offenen Tür | 02G26 Lemgo-Grundschule |
| 22.09.2026 | — | Tag der offenen Tür | 02G24 Otto-Wels-Grundschule |
| 24.09.2026 | — | Tag der offenen Tür | 02G19 Fanny-Hensel-Grundschule |
| 24.09.2026 | 15:00 | Tag der offenen Tür | 02G36 Blumen-Grundschule |
| 30.09.2026 | 08:00 | Tag der offenen Tür | 02G04 Pettenkofer-Grundschule |
| 30.09.2026 | 09:00 | Tag der offenen Tür | 02G13 Charlotte-Salomon-Grundschule |
| 01.10.2026 | 08:00 | Tag der offenen Tür | 02G04 Pettenkofer-Grundschule |
| 01.10.2026 | 16:30 | Tag der offenen Tür | 02G34 Jane-Goodall-Grundschule |
| 08.10.2026 | 17:00 | Infoabend | 02P09 Freie Schule Kreuzberg |

- **Status-Verteilung:** 9 × `gefunden`, 14 × `keinFund` (Terminstelle vorhanden,
  aber kein TdOT/Infoabend darauf), 11 × `keinIndiz` (keine Terminstelle mit
  Datum). Jede Schule trägt einen nachprüfbaren Grund — keine stille Lücke.
- **Verworfene Modellantworten (25):** 12 × `zeit_unplausibel`,
  6 × `zitat_nicht_belegt`, 4 × `dublette`, 2 × `datum_nicht_im_zitat`,
  1 × `datum_vergangen`. Genau dafür ist die Prüfung da: das lokale Modell
  liefert gelegentlich plausibel aussehende, aber nicht belegte Zeiten.
- **Abdeckung:** 9 von 34 (26 %) automatisch mit Termin — die übrigen gehen in
  die Mail-Anfrage (Stufe 3, noch nicht gebaut).

## Zu prüfen durch den Admin (Beobachtung, nicht Urteil)

- `02G04 Pettenkofer` liefert zweimal `08:00` (30.09. und 01.10.) — möglich,
  aber auffällig; die Fundstelle ist im Vorschlag verlinkt.
- `02G26 Lemgo` liefert zwei Daten von derselben Seite (`/event/tag-der-offenen-tuer-2`)
  — plausibel (zwei Termine auf einer Seite), aber prüfen.

## Technik-Stand

- Endpunkt im Admin konfigurierbar (Basis-URL, Modell, Key, Timeout,
  Zusatz-Parameter als JSON), voreingestellt auf `http://<LLM_PORT>/v1`
  (`llamacpp-gemma4-12B-unsloth`), Pflichtparameter `enable_thinking: false`
  vorbelegt. Gemessen: 0,7 s pro Extraktion, 263 tok/s.
- Admin-UI: „LLM-Endpunkt" (mit Verbindungstest samt echter Antwort) und
  „Schul-Recherche" (Lauf mit Umfang/Probelauf, Stand je Schule, Fundstelle,
  Verwerfungsgründe). CLI: `recherche-schulen --bezirk --schulform --limit --dry-run`.
- LLM-frei-Invariante unangetastet: der Job ist getrennt, sequenziell,
  standardmäßig nur manuell auslösbar, und schreibt ausschließlich `ungeprüft`.

## Offene Restschuld

1. **Stufe 3 (Mail-Anfrage + Postfach-Eingang)** ist konzipiert, aber nicht
   gebaut (Postfach, Reply-To, Token, IMAP-Verarbeitung).
2. **Scheduler-Anbindung:** der nächtliche Automatiklauf ist als Schalter
   vorbereitet (`recherche_aktiv`), aber noch nicht im Scheduler verdrahtet.
3. **Feldprobe „Precision":** die 11 Vorschläge müssen vom Admin gegen die
   Schul-Website geprüft werden; erst danach ist die Trefferquote belegbar.
