# Tasks — Change 010

Reihenfolge bewusst: erst Belege/Prüfungen (deterministisch, testbar), dann
LLM-Anbindung, dann Mail, dann UI. Jeder Schritt hat einen Test; kein Schritt
ist „fertig", weil er ohne Fehler durchlief.

## 0. Vorbereitung (ohne Code, User-Entscheidungen)

- [ ] Offene Fragen aus design.md §13 beantworten (Postfach, Mail-LLM-Pfad,
      Auto-Versand ja/nein, Löschfrist, Impressum-/Datenschutztext).
- [ ] Freie-Endpunkt-Matrix (design.md §4) gegen die Anbieter-Doku
      nachprüfen; gewähltes Modell + Ausweichmodell in litellm sicherstellen
      (`GET /v1/models`).
- [ ] Postfach `kinderkram@mekotools.de` anlegen, IMAP/SMTP testen
      (Testmail an sich selbst, Antwort landet im selben Postfach).

## 1. Store/Migration (TDD)

- [ ] `tests/test_schul_recherche_store.py`: Spalten
      (`recherche_am/status/notiz`, `anfrage_status`, `anfrage_token`,
      `antwort_am`), Tabellen `schul_recherche_lauf`, `schul_mail_eingang`;
      Idempotenz der Migration auf einer Alt-DB-Kopie.
- [ ] `app/store.py`: Migration + Zugriffsfunktionen
      (`set_recherche_status`, `log_recherche_lauf`, `offene_schulen_fuer_recherche`,
      `speichere_mail_eingang`, `set_anfrage_status`).
- [ ] `app/schul_import.py`: Kandidatenliste (Stufe A ausgeschlossen, Website
      vorhanden) als wiederverwendbare Funktion + Test gegen die echten
      Zahlen (722/271/429 als Erwartung).

## 2. Fetch + Vorfilter (ohne LLM, offline testbar)

- [ ] `app/recherche/fetch.py`: Seiten holen (Browser-UA, 1 req/s, Timeout,
      3 Seiten max.), Text normalisieren, Hash bilden, Kandidatenlinks finden
      (Priorität tdot > termin/kalender > aktuelles > anmeldung).
- [ ] `tests/test_recherche_fetch.py` mit Fixtures: WordPress-Terminseite,
      Jimdo-Textseite (Monatsnamen „17. September 2026"), PDF-Jahresplan-Link,
      Seite ohne Datum, Seite mit 503.
- [ ] Vorfilter: Seite ohne Datums-Indiz oder ohne Ziel-Keyword → kein
      LLM-Aufruf (Test zählt Aufrufe).

## 3. LLM-Anbindung (mit Fake-Client)

- [ ] `app/recherche/llm.py`: litellm-Client (Basis-URL + Key aus
      Einstellungen), JSON-Zwang, Temperatur 0, Timeout, max. 2 Retries mit
      Backoff, Ausweichmodell, Circuit Breaker (Fehlerquote im Lauf),
      Rückgabe Rohantwort + Modellname.
- [ ] `tests/test_recherche_llm.py`: Fake-Client für (a) gültige Antwort,
      (b) leere `content` (Reasoning-Modell), (c) 429 → Ausweichmodell,
      (d) Reihenfolge der Wiederholungen. **Keine echten Netzaufrufe in CI.**

## 4. Extraktionskern mit Belegprüfung

- [ ] `app/recherche/kern.py`: Prompt (design.md §6), Ergebnisprüfung
      (Zitat-Substring, Datumsfenster, Zeitplausibilität, Titelvokabular,
      Dublette), Mapping auf `termine_manuell`.
- [ ] `tests/test_recherche_kern.py`: Fixtures inkl. **Halluzinationsfall**
      (Zitat nicht im Text → verworfen), Vorjahresdatum, Titel ohne
      Zielklasse, doppeltes Datum.
- [ ] Prompt-Version im Datensatz (`modell`, Prompt-Hash) mitschreiben, damit
      ein späterer Prompt-Wechsel nachvollziehbar bleibt.

## 5. Job + CLI + Scheduler

- [ ] `app/cli.py`: `recherche-schulen [--limit N] [--dry-run] [--nur-bsn X]`
      mit Fortschritt (x/y) und Zusammenfassung.
- [ ] Scheduler: Lauf im Nachtfenster, nur wenn `recherche_aktiv = true`;
      Abbruch bei Fehlerquote; Logzeile je Lauf.
- [ ] `tests/test_scheduler.py` erweitern: Job läuft nicht, wenn deaktiviert;
      läuft genau einmal je Nachtfenster.

## 6. Mail-Ausgang (Anfrage)

- [ ] `DEFAULT_MAIL_VORLAGE`: Platzhalter `[Name / Einrichtung]`/`[Kontakt]`
      aus Einstellungen füllen; Opt-out-Satz, Datenschutz-Link,
      Token `[KK-<BSN>-<Jahr>]` im Betreff, `Reply-To` = Postfach.
- [ ] Drosselung (Mo–Fr 08–16 Uhr, 20/Stunde, 1 je Schule/Schuljahr,
      12-Monats-Sperre) + `anfrage_status`-Übergänge.
- [ ] `tests/test_schul_admin_api.py`: Versand setzt Status, zweiter Versand
      im selben Schuljahr wird mit klarer Fehlermeldung abgelehnt; ohne
      Absender keine Mail.

## 7. Postfach-Eingang (IMAP) + Antwort-Verarbeitung

- [ ] `app/mail_eingang.py`: IMAP-Poll (Ordner INBOX, ungelesen bleibt
      ungelesen, Rohmail auf Platte), Zuordnung `In-Reply-To`/`References`
      → Token → Absenderadresse, Sonderfälle (`Auto-Submitted`,
      `X-Autoreply`, Bounce) als Status.
- [ ] `tests/test_mail_eingang.py` mit `.eml`-Fixtures: Antwort mit Termin,
      Absage, Auto-Antwort, Bounce, fremde Mail ohne Zuordnung.
- [ ] Antwort-Extraktion mit demselben Kern wie §4 (Mailtext als Quelle,
      Zitat = Satz aus der Mail); Ergebnis → `termine_manuell` +
      `quelle_hinweis` „Antwort-Mail vom …".
- [ ] Anhänge: PDF-Text via pymupdf; Bilder/Excel → Vermerk „Anhang bitte
      prüfen" (kein stiller Ignorier-Fall).

## 8. Admin-API + UI

- [ ] API: `GET /api/admin/recherche` (Status je Schule, Filter ohneFund),
      `POST /api/admin/recherche/lauf`, `POST /api/admin/termine/uebernehmen`,
      `GET/PUT /api/admin/settings` (litellm-Modell, IMAP, Löschfrist),
      `POST /api/admin/mail/pruefen`, `GET /api/admin/mail/eingang`.
- [ ] UI „Recherche": Liste mit Stand/Belegzitat/Fund-URL, Vorschau des
      Zitats, „übernehmen", Sammel-Lauf mit echtem Fortschritt, Filter
      „ohne Fund" → Aktion „Anfrage-Mail senden".
- [ ] UI „Mail-Eingang": Antworten, Zuordnung, extrahierte Vorschläge,
      Sonderfälle, Rohmail-Download.
- [ ] Tests: `tests/test_recherche_admin_api.py`, UI-Smoke mobil (≤ 400 px,
      keine funktionslosen Knöpfe, Fehler sichtbar).

## 9. Feldprobe und Abnahme (vor Auto-Versand)

- [ ] `--dry-run` über 20 zufällige Grundschulen; Ergebnis manuell gegen die
      Schul-Website prüfen (Precision, erfundene Termine = 0).
- [ ] Zahlen in `status.md`: geprüft/belegt/verworfen, Precision, Dauer,
      Tokens, Fehlerbilder je Bot-Schutz-Klasse.
- [ ] Erst nach bestandener Feldprobe: `recherche_aktiv = true` und
      Mail-Versand (zunächst als Liste mit Klick, siehe design.md §13.3).
- [ ] Regression: Scrape-Lauf und öffentliche API vor/nach dem Job
      vergleichen (identische Event-Zahl, keine neuen Quellen).

## 10. Doku und Abschluss

- [ ] `docs/quellen.md`: Abschnitt „Schul-Recherche (LLM, out-of-band)" mit
      Endpunkt-Wahl, Datenschutzgrenze (öffentliche Seite vs. Mail),
      Drosselung, Löschfrist.
- [ ] `openspec/project.md`: Capability-Index um `schul-recherche` ergänzen.
- [ ] `status.md` mit Verifikationszahlen und offener Restschuld.
- [ ] Skill `kids-events-berlin` um die LLM-Recherche-Referenz erweitern
      (Prompt, Belegprüfung, Endpunkt-Fallen, Rate-Limit-Messwerte).
