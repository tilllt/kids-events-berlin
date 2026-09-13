# Change 012 — Websuche (Brave) mit Kontingent-Verwaltung

**Status:** gebaut, Tests grün, deployt (2026-09-13). **Wartet auf den API-Key**
der neue Brave-Account wird vom Nutzer angelegt; der Schlüssel wird in der
Admin-GUI eingetragen, nicht im Code und nicht per Umgebungsvariable.

## Why

Die Recherche besucht bisher nur die Schul-Seite selbst (Homepage + bis zu zwei
Link-Kandidaten). Suchprobe am 13.09.2026 über 8 Friedrichshain-Kreuzberger
Grundschulen **ohne** Fund: **5 von 8** hatten über eine Websuche ein Datum zum
Tag der offenen Tür — u. a. eine tiefe Unterseite der Schul-Website
(`www.aziz-nesin-schule.de/tag-der-offenen-tuer-am-18-9-2026`), die die
Heuristik nie erreicht hätte. Die Suche ist damit in erster Linie ein
**Link-Finder**; die Auswertung bleibt beim LLM mit der bestehenden
Belegprüfung (Zitat wörtlich im Seitentext, Datum im Zitat) und dem
Dublettenschutz aus Change 011.

## Kontingent (Grundlage der Verwaltung)

Laut offizieller Preisseite von Brave (abgerufen 13.09.2026):
- Web Search kostet **5,00 $ je 1.000 Anfragen**.
- Brave schreibt **monatlich 5,00 $ Guthaben** gut → **1.000 Anfragen gratis/Monat**.
- Kapazität 50 Anfragen/Sekunde; Überschreitung läuft gegen das Guthaben/die
  Zahlungsart → hier wird deshalb **hart gestoppt**, nicht „probiert".

## Umsetzung

- `app/recherche/websearch.py`: Brave-Client (`/res/v1/web/search`), Kontingent-
  Prüfung, Reservierung, Rate Limit, Fehlerbehandlung.
- **Kontingent ohne driftenden Zähler:** Tabelle `brave_aufrufe` — jeder Aufruf
  wird **vor** dem Absenden verbucht (Reservierung), nach der Antwort um
  HTTP-Code, Trefferzahl und Fehler ergänzt. Monats- und Tagesverbrauch sind
  `COUNT(*)` auf dieser Tabelle; ein Monatswechsel setzt damit automatisch
  zurück. Absturz mitten im Request „verliert" kein Guthaben.
- **Budgets in der Admin-GUI:** Anfragen je Monat (Standard **900** = 1.000
  Gratis abzüglich 100 Reserve), Anfragen je Tag (Standard **30**, 0 = aus),
  Anfragen pro Sekunde (Standard 1; Brave erlaubt 50), Schalter „Websuche
  nutzen". Erreichtes Budget ⇒ sichtbarer Klartext-Fehler an der Schule, kein
  stilles Überspringen.
- **Rate Limit:** Mindestabstand 1/anfragen_pro_s, bei HTTP 429 genau ein
  Wiederholungsversuch (kostet kein zweites Budget), danach klarer Abbruch.
  HTTP 401/403 „Key abgelehnt", 402 „Guthaben fehlt — gestoppt, damit keine
  Kosten entstehen".
- **Fallback statt Vorstufe:** Die Suche läuft nur, wenn die eigenen Seiten
  nichts hergeben — Schulen, die schon liefern, kosten kein Kontingent
  (Test `test_keine_websuche_wenn_die_eigene_seite_schon_liefert`).
- **Fremdquellen** (Blogs, Bezirksseiten) sind zugelassen, stehen aber hinter
  den Treffern auf der Schul-Domain; die Fund-URL steht im Vorschlag.
- Admin: `GET /api/admin/brave` (Verbrauch/Budget/letzte Aufrufe),
  `POST /api/admin/brave/test` (eine echte Testsuche, wird als Anfrage
  ausgewiesen), `brave/letzte`.
- Lauf-Ergebnis zählt `websuche_anfragen` und `websuche_fehler` mit.

## Tests (14 neu, gesamt 221 grün)

Monatsbudget-Stopp mit Zahlen, Tagesbudget-Stopp, Monatswechsel-Reset,
fehlender Key, Reservierung bei Netzfehler, Rate-Limit-Abstand,
429-Wiederholung ohne doppelte Verbuchung, dauerhafte 429, 401/403/402,
Treffer-Sortierung (eigene Domain zuerst, Dubletten entfernt),
Websuche-Fallback findet tiefe Unterseite, keine Suche bei eigenem Fund,
Budgetfehler sichtbar an der Schule, Schalter aus = null Aufrufe.

## Offen

1. **API-Key** vom Nutzer (neuer Brave-Account) — danach in der GUI eintragen,
   „Verbindung testen" klicken und „Websuche nutzen" einschalten.
2. Nach dem ersten FK-Lauf mit Suche: Messung, wie viele der 25 Schulen ohne
   Fund zusätzlich abgedeckt werden (Erwartung nach der Probe: +5 von 8).
3. Die verbleibenden Schulen sind die Menge für die Mail-Anfrage (Stufe 3).
