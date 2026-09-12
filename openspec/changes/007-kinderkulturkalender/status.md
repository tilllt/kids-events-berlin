# Change 007 — Umsetzung (2026-09-12, live)

## Was gebaut wurde
- Quelle `kinderkulturkalender` (LKJ Berlin, Drupal 10) als Stufe-2-Regel-Quelle,
  `horizont_tage 21` (Vorgabe: 3 Wochen Vorlauf), `termine_autoritativ: true`.
- Engine: Termin-Textform („20.09.26, 11:00 - 20.09.26, 12:30“), `termine_css`,
  CSS-Felder mit `regex`, Feld-Regeln als **Alternativen-Liste**, neue Option
  `urldecode` (Adresse aus dem AddToCalendar-Link), `attr` für Link-Attribute.
- Ganztags-Konvention: explizites „00:00 - 23:59“ setzt das ganztags-Flag.
- Geo: amtliche Adress-Geokodierung läuft **vor** und **unabhängig vom Ortsnamen**
  (vorher hing sie hinter dem Orts-Guard → Ortsangaben wie „Ohne Angabe“/„Berlin“
  verhinderten jeden Lookup).

## Verifikation (Produktion)
- Lauf 1: 211 Events, 0 Fehler, 115 s, idempotenter Folgelauf.
- Adresse vorhanden: 184 von 211 (vorher 122); Ortsangabe fehlt bei 89 (Quelle
  nennt keinen Ort) — Adresse kommt dann aus dem Kalender-Link (12/12 Stichprobe).
- Koordinaten: 125 → 77 ohne Position; Rest = 27 ohne Adresse + 50, deren Adresse
  der WFS nicht auflöst (Abkürzungen „Ruheplatzstr.“/„Konrad-Wolf-Str.“, Quell-
  Tippfehler „BErlin“, eingebettete Ortsnamen wie „… ZLB … 10961 Berlin“).
- Keine Dubletten, keine überlappenden Spannen innerhalb der Quelle.

## Offen
- Adress-Normalisierung vor der WFS-Abfrage („Str.“ → „straße“) würde den Rest
  der 50 auflösen — eigener Change, betrifft alle Quellen.
