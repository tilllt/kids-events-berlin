# Change 028 — Selbstheilung: Knopf in der Verwaltung UND Automatik, die meldet

Status: in Arbeit (Nutzerauftrag 2026-10-16: „Baue den Knopf ein, aber etabliere
auch einen automatischen Modus, der versucht zu reparieren, oder wenn das nicht
klappt, Bescheid sagt.")

## Ausgangslage (am 16.10.2026 live gemessen)

- Erkennung läuft: `heilungen` enthält genau EINE Zeile vom 22.09.2026
  (`museumsportal`, `art=verdacht`, `status=beobachtet`, Diagnose
  „selektoren_funktionieren" → korrekt kein Eingriff). Seither nichts.
- **Reparatur ist toter Code.** `heilen()` (LLM-Vorschlag + Prüf-Gate, Change 017
  Phase 2) hat keinen Aufrufer; im Container matcht `heilen(` nur die Definition,
  `selbstheilung` wird allein von `pipeline.py` importiert. Es gibt keinen
  Admin-Endpunkt und in `app/static/` kein einziges „heil". Von einem Befund zu
  einer Reparatur führt kein Weg — auch nicht über die Oberfläche.
- **Blinder Fleck der Erkennung:** Listing-Parse-Fehler
  (`Item N: feld: kein Wert extrahiert`, `selector_adapter.parse_listing`) landen
  nur in `_warnungen` → `errors`, sie zählen NICHT in `n_fehler` (das zählt nur
  `validate_event`-Fehler). Beleg: `umweltkalender-berlin` hat 45.568 solcher
  Fehlerzeilen, aber in 34 Läufen `n_fehler` = 0. Der Auslöser „Pflichtfeld
  bricht / Fehlerquote" konnte so nie feuern.

## Was gebaut wird

1. **Verdrahtung:** `selbstheilung.lauf_auswerten()` ersetzt den bisherigen
   `pruefen()`-Aufruf in der Pipeline. Er macht drei Dinge in fester Reihenfolge:
   Befund feststellen (wie bisher, unverändert streng: ein Rückgang ist kein
   Defekt), die zuvor übernommene Reparatur beobachten (Rücknahme, s. 4) und —
   nur bei bewiesenem Defekt — einen Reparaturversuch starten.
2. **Knopf je Quelle:** „Regeln reparieren lassen" in der Quellenliste (nur bei
   `typ=regeln`). `POST /api/admin/sources/{quelle}/reparieren` holt die
   Listing-Seite wirklich, stellt den Befund fest, ruft das LLM und prüft mit dem
   Gate. Grünes Gate → die Regeln werden übernommen (`verursacher=manuell`),
   sonst bleibt alles unverändert und der Grund steht in der Oberfläche.
3. **Automatik** (Einstellung `heilung_auto`, Standard **an**): Bei bewiesenem
   Defekt übernimmt die Automatik die Reparatur selbst, sobald das Gate grün ist.
   Verdacht/Folgen sind weiterhin nur Meldungen. Sperren (401/402/403/429)
   werden NICHT repariert; die Quelle wird auch NICHT automatisch pausiert
   (eine stille Abschaltung wäre schlimmer als der Fehler) — es geht sofort eine
   Meldung raus. Ein Versuch je Quelle und Tag, höchstens
   `heilung_max_pro_tag` (Standard 3) LLM-Versuche pro Tag insgesamt.
4. **Vorsichtsnetz (Rücknahme):** Nach einer Übernahme wird der nächste Lauf
   beobachtet. Findet er weniger als 50 % der Probelauf-Zahl, wird die vorherige
   Regel-Fassung automatisch wiederhergestellt, die Heilung auf
   `zurueckgenommen` gesetzt und gemeldet. Jede Regeländerung steht in
   `regel_historie` (alt/neu/Grund/Verursacher) — in der Oberfläche sichtbar und
   per Klick rückholbar.
5. **Meldung („Bescheid sagen"):** Jedes Ergebnis geht sichtbar raus — in der
   Oberfläche (Liste „Selbstheilung" mit Status, Belegzahlen, Vorschlag) UND per
   E-Mail an `heilung_mail_an` (Standard: eigene Absenderadresse), sofern
   `heilung_mail_aktiv` an ist. Schlägt der Versand fehl, steht der Fehler in der
   Oberfläche (`errors`) — nichts fällt still aus.
6. **Zähler-Fix:** Listing-Warnungen zählen mit in den Befund. Die Quote wird
   ehrlich gerechnet (Fehler / (gelesene Zeilen + Warnungen)); ab 10 Fehlern oder
   30 % gilt der Befund als `fehlerquote` (wie bisher für Feld-Fehler).
   Folge, die bewusst in Kauf genommen wird: `umweltkalender-berlin` und
   `bwb-veranstaltungen` sind damit die ersten Kandidaten der Automatik.

## Grenzen (bleibt wie in Change 017)

- Geheilt wird nur Technisches: Selektoren, Feldpfade, Zeitformate, Listing-URL
  derselben Domain. Kein Code, keine fremde Domain, kein Rechte-Thema.
- Übernommen wird nur mit grünem Gate (Regeln formal gültig, Quelle + Domain
  unverändert, Probelauf heute ≥ max(3, 50 % der früheren Treffer) mit
  gefülltem Titel UND Start, kein absurd grober Selektor).
- Ein Rückgang der Trefferzahl ohne Fehler löst weiterhin nur die kostenlose
  Diagnose aus.

## Oberfläche

- Quellen-Tab: Knopf „Regeln reparieren lassen" in der Zeile jeder Regel-Quelle;
  darunter der Bereich **Selbstheilung** (offen): Automatik-Status, Liste der
  Fälle mit Zeit/Quelle/Art/Status/Beleg, Vorschlag + Begründung als Klappblock,
  Knöpfe Übernehmen / Ablehnen / Regeln zurücknehmen, dazu der Regel-Verlauf.
- Einstellungen-Tab: Klappblock **Selbstheilung** mit `heilung_auto`,
  `heilung_mail_aktiv`, `heilung_mail_an`, `heilung_max_pro_tag`.

## Tests

- Automatik an + grünes Gate → Regeln geändert, `regel_historie` geschrieben,
  Status `angenommen`, Meldung gesetzt, Mail versucht.
- Gate rot → Regeln UNVERÄNDERT, Status `verworfen`, Meldung mit Grund.
- Automatik aus → Status `vorschlagen`/`vorgeschlagen`, keine Regeländerung.
- Sperre (403) → kein LLM-Aufruf, Meldung, keine Regeländerung.
- Rücknahme: nach Übernahme findet der nächste Lauf < 50 % → alte Fassung
  wiederhergestellt, Status `zurueckgenommen`, Meldung.
- Ein Versuch je Quelle/Tag; Tageskontingent greift.
- API: Liste, Einzel-Abruf, Übernehmen, Ablehnen, Zurücknehmen, Reparatur-Knopf.
- Oberflächen-Invarianten (keine doppelten IDs, formgrid nur Labels) bleiben grün.

## Offene Entscheidung

- Soll eine gesperrte Quelle automatisch pausiert werden? Vorschlag: nein
  (eine stille Abschaltung ist riskanter als der Fehler) — gemeldet wird sofort.
