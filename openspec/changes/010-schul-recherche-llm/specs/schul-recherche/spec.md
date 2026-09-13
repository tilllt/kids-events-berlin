## ADDED Requirements

### Requirement: LLM-Recherche außerhalb der Event-Pipeline

- **Invariante:** Die Event-Pipeline (Fetch/Parse/Normalize/Enrich/Dedupe/Publish) ruft kein LLM, kein Embedding und keinen externen ML-Dienst. Die Schul-Recherche ist ein separater, standardmäßig deaktivierter Job, der ausschließlich Vorschläge erzeugt.
- **Ablauf:** Der Job läuft sequenziell im vorhandenen Scheduler des App-Prozesses (ein SQLite-Schreiber, keine parallelen Fetch-Jobs gegen dieselbe Quell-IP), im Nachtfenster, mit Rate-Limit und Abbruchmöglichkeit.
- **Ergebnis:** Ein Lauf mit deaktiviertem Job verändert keinen einzigen Event-Datensatz.

#### Scenario: Job abgeschaltet
- **Akteure:** Scheduler, Store.
- **Eingaben:** Einstellung `recherche_aktiv = false`.
- **Ergebnis:** Kein LLM-Aufruf, keine neuen Vorschläge; die Event-Ausgabe der öffentlichen API ist byte-identisch zum Lauf ohne Job.

### Requirement: Kandidatenauswahl und Vorfilter

- **Ablauf:** Recherchiert werden nur Schulen, deren Website nicht schon regelbasiert auswertbar ist (Stufe A ausgeschlossen) und die eine Website im Stamm haben. Je Schule werden Homepage und höchstens zwei terminrelevante Folgeseiten geholt (Termin/Kalender/Aktuelles/TdoT-Schlüsselwörter, `tdot` vor `termin`).
- **Vorfilter:** Ein LLM-Aufruf erfolgt nur für Seiten, die mindestens ein Datums-Indiz (TT.MM.JJJJ oder Monatsname) **und** mindestens ein Ziel-Keyword (Tag der offenen Tür, Infoabend, Informationsveranstaltung, Schnuppern, Einschulung) enthalten.
- **Wiederholung:** Eine unveränderte Seite (gleicher Text-Hash) mit bereits bewertetem Ergebnis löst keinen neuen LLM-Aufruf aus.
- **Ergebnis:** Nicht erreichbare Schulen (Bot-Schutz, harte 403, Turnstile, iframe-JS-Kalender) werden als `abrufFehler` geführt, nicht als „kein Termin".

#### Scenario: Schule mit Bot-Schutz
- **Akteure:** Recherche-Job, Schule mit Strato-503-Schutz.
- **Eingaben:** Homepage liefert nach Wiederholung 503.
- **Ergebnis:** `recherche_status = abrufFehler` mit Notiz zum Statuscode; die Schule bleibt in der Mail-Liste, kein LLM-Aufruf.

### Requirement: Extraktion mit Belegpflicht

- **Ausgabeformat:** Je Termin `titel` (Vokabular TdoT/Infoabend/Infoveranstaltung/Schnuppertag/Schnupperunterricht), `datum` (TT.MM.JJJJ), `zeit` (HH:MM oder leer), `beleg` (wörtliches Zitat ≤ 200 Zeichen), `sicherheit` (hoch/mittel/niedrig).
- **Prüfung (deterministisch, vor jedem Anlegen):** Der `beleg` muss whitespace-normalisiert und case-insensitiv als Teilstring des Quelltextes vorkommen (mindestens 15 Zeichen); das Datum muss parsen und in `[heute, heute+400 Tage]` liegen; die Uhrzeit muss plausibel sein; der Titel muss in das vorhandene Vokabular abgebildet werden können; ein bereits vorhandener Eintrag (gleiche Schule, Datum, Titelnormalform) wird ergänzt, nicht dupliziert.
- **Verworfene Funde:** werden mit Grund (`zitat_nicht_belegt`, `datum_ausserhalb`, `titel_unbekannt`, `zeit_unplausibel`, `kein_json`) protokolliert und nicht in die Queue übernommen.

#### Scenario: Modell erfindet einen Termin
- **Akteure:** Recherche-Job, LLM.
- **Eingaben:** Antwort mit Datum und `beleg`, der im Seitentext nicht vorkommt.
- **Ergebnis:** Kein `termine_manuell`-Eintrag; der Lauf zeigt `n_roh = 1`, `n_belegt = 0`, `verworfen_grund = zitat_nicht_belegt`.

### Requirement: Vorschläge über die bestehende Freigabe-Queue

- **Ablauf:** Jeder belegte Fund wird als `termine_manuell` mit `status = ungeprueft` angelegt; `quelle_hinweis` nennt Herkunft, Fund-URL, Belegzitat und Modellnamen.
- **Ergebnis:** Öffentliche Sichtbarkeit entsteht ausschließlich durch die bestehende Freigabe (`bestaetigt`) — identisch zu handgepflegten Terminen (quelle = `manuell`).

#### Scenario: Admin bestätigt einen LLM-Fund
- **Akteure:** Admin.
- **Eingaben:** Vorschlag aus der Recherche mit Fund-URL und Zitat.
- **Ergebnis:** Nach Prüfung auf der Schul-Website wird der Termin bestätigt und erscheint auf der Karte; das Belegzitat bleibt am Datensatz nachvollziehbar.

### Requirement: Sichtbarkeit und Alarme

- **Sichtbarkeit:** Je Schule werden Recherche-Zeitpunkt, Status, Anzahl geprüfter Seiten, Fund/kein Fund und Fehlergrund angezeigt; je Lauf werden Zähler (geprüft, LLM-Calls, belegt, verworfen) und Dauer geführt. Kein Ergebnis bleibt unbegründet.
- **Alarme:** LLM-Fehlerquote > 30 % in einem Lauf, 0 belegte Funde bei mindestens 20 geprüften Schulen, dreimal fehlgeschlagener Postfach-Login oder Bounce-Quote > 10 % erzeugen einen Alarm über den bestehenden Kanal — mit Angabe, was zu tun ist.

#### Scenario: Endpunkt liefert nichts mehr
- **Akteure:** Recherche-Job, Alarmkanal.
- **Eingaben:** 20 Schulen geprüft, 20 Abruf-Fehler, 0 belegte Funde in einem Lauf.
- **Ergebnis:** Der Lauf endet sichtbar mit Zusammenfassung (geprüft/belegt/verworfen, Fehlerquote) und löst einen Alarm aus; die betroffenen Schulen tragen je einen Grund, kein Vorschlag wird angelegt.
