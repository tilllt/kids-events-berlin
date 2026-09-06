# Tasks — Change 003 Zeitraum-Schnellwahl

- [ ] `index.html`: Segment „Wann“ mit 4 Optionen über den Von-/Bis-Feldern
- [ ] `app.js`: Berlin-Tagesgrenzen (`Intl`, Europe/Berlin), Optionen Heute/Morgen/Diese Woche/Nächste Woche, Default „Heute“, URL-State `zeitraum=…`, Umschalten auf „Benutzerdefiniert“ bei manueller Von/Bis-Änderung, Reset → Heute
- [ ] `style.css`: Styling konsistent zu bestehenden Chips
- [ ] Smoke-Test lokal (pytest unverändert grün; Browser: Default zeigt Heute-Events, Umschalten filtert korrekt, URL teilbar)
- [ ] Commit + Push + Deploy (Coolify, kinderkram.cia-spandau.de) + Online-Smoke

## Abnahme-Kriterien

- Seite ohne URL-Params → nur heutige Events (Default Heute), Von-/Bis-Felder zeigen heute
- Morgen / Diese Woche / Nächste Woche liefern korrekte, aufsteigende Zeitfenster (7-Tage-Fenster ab heute bzw. ab heute+7)
- Manuelle Datumswahl deaktiviert Schnellwahl; URL enthält `zeitraum` bzw. `von`/`bis`
