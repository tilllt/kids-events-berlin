# Change 010 — Design: LLM-Recherche für Schultermine, Mail-Anfrage und Antwort-Eingang

## 1. Zielbild (drei Stufen, eine Queue)

```
Stufe 1  regelbasiert (heute)      Website A: <time> / JSON-LD / ICS / PDF-Jahresplan
         ─────────────────────►
Stufe 2  LLM-Recherche (neu)       Homepage + ≤2 Terminseiten → Termin-Objekte mit
         nur wo Stufe 1 nicht greift   wörtlichem Belegzitat → Vorschlag (ungeprüft)
         ─────────────────────►
Stufe 3  Mail-Anfrage + Eingang    Reply-To = eigenes Postfach; Antwort → LLM →
         (neu) nur wo Stufe 2 leer     Vorschlag (ungeprüft) / Status „kein Bedarf“

                    ▼
        EINE Freigabe-Queue  ───────►  termine_manuell.status
        (bestehend, Change 005)        ungeprueft → bestaetigt → öffentliche Karte
```

Der LLM ersetzt keine Quelle und keine Freigabe: Er füllt die Queue, die der
Admin schon hat. Jeder Vorschlag trägt Fund-URL, wörtliches Zitat, Zeitpunkt
und Modellnamen — Nachprüfbarkeit ist Teil des Datensatzes, nicht Beiwerk.

## 2. Warum LLM — und warum nicht „mehr Regeln"

Gemessen am eigenen Bestand (`/opt/data/schul_dates/`):

- 722 allgemeinbildende Schulen, 439 Grundschulen; Stufen: A 225 / B 261 /
  C 213 / keine Website 23 (722 = A+B+C+23).
- Arbeitszuordnung: scraper 271 / manuell 215 / mail 236.
- Der Regel-Generator über die 23 „A"-Schulen des Strato-Crawls erzeugte
  **0 Regeln**: „A" entsteht aus Datums-**Dichte** im Text (News-Listen,
  PDF-Jahrespläne, einzelne JSON-LD-Events), nicht aus einem wiederkehrenden
  Item-Container. Eine belastbare Regel braucht genau das.
- Der Crawler fand 667 Rohtreffer mit Datums-/Terminbezug in 47 von 118
  Schulen — darunter echter TdoT-Text („Unser Tag der offenen Tür findet am
  Samstag, 24.01.2026, in der Zeit von 10 – 13 Uhr statt"), aber auch News-
  Zeitstempel und Vorjahre.

Fazit: Der Engpass ist nicht Erreichbarkeit und nicht Datenmenge, sondern
**formunabhängiges Verstehen** (Fließtext, Monatsnamen, verschiedene
Jahresangaben, PDF-Text). Genau das ist die Stärke eines Sprachmodells und
gleichzeitig sein Risiko (Erfinden) — deshalb die Belegpflicht in §6.

## 3. Architektur-Entscheidungen

1. **Zugang und Verstehen strikt trennen.** Das LLM hilft gegen schlechte
   Struktur, nicht gegen Zugangssperren. Der Fetch bleibt deterministisch
   (httpx/urllib, Browser-UA, robots notiert, 1 Abruf/Sekunde, max. 3 Seiten
   je Schule). 503 Strato-Bot-Schutz, harte 403, Turnstile und iframe-JS-
   Kalender bleiben in der manuellen bzw. Mail-Liste — kein Captcha-Bruch.
2. **Job statt Pipeline.** Die Recherche läuft als eigener, sequenzieller Job
   im vorhandenen Scheduler-Thread (`app/main.py`, Muster wie der Scrape-
   Scheduler) — nicht als zweiter Prozess. Gründe: SQLite hat einen
   Schreiber (WAL hilft nur Lesern), und pro Quell-IP darf nur ein Fetch-Job
   laufen (Lehre aus dem Strato-Crawl: Volumina addieren sich zur Sperr-
   Schwelle).
3. **Standardmäßig aus.** `recherche_aktiv` = false. Erst nach der Feldprobe
   (§12) scharf schalten. Damit ist der Downgrade-Pfad kein Codeeingriff.
4. **Vorfilter vor dem LLM.** Nur Seiten, die (a) ein Datums-Indiz
   (`TT.MM.JJJJ` oder Monatsname) **und** (b) ein Ziel-Keyword
   (`offene Tür|Infoabend|Schnupper|Einschulung|Schulanfang`) enthalten,
   werden überhaupt gesendet. Rechnung: 722 Seiten-Universum → 276 Kandidaten-
   Schulen → davon nach Indiz-Filter grob die Hälfte → je Seite 1 Call.
5. **Wiederholung nur bei Änderung.** Je URL wird ein Seiten-Hash (SHA-256
   des normalisierten Textes) gespeichert. Unveränderte Seite + bereits
   beurteiltes Ergebnis = kein neuer Call. Wochentakt je Schule, Nachtfenster
   22:00–06:00. Das ist der eigentliche Kontingent-Schutz, nicht das Rate-Limit.
6. **Ergebnis-Cache getrennt von der Queue.** Rohantwort des Modells und
   Belegprüfung landen in `schul_recherche_lauf`; erst der geprüfte Fund wird
   zu `termine_manuell`. Verworfenes wird mit Grund protokolliert (nichts
   Stilles), aber nicht veröffentlicht.
7. **Kein LLM für Dedupe/Geo/Tags.** Wenn die LLM-Angabe „Tag der offenen
   Tür" heißt, wird der Titel auf das vorhandene Vokabular abgebildet
   (`app/schul_import.py: KEYWORD_TITEL`); Tags bleiben die des Katalogs.

## 4. Freie LLM-Endpunkte — Auswahlmatrix (Stand 2026-09-13)

Vorhandene Verdrahtung im Haus: `litellm.n0ne.de` führt u. a.
`openrouter/openrouter/free` (Free-Models-Router), `mistral/*`,
`google/gemma-4-31b-it` — ein Aufruf mit `LITELLM_API_KEY` genügt. Damit
braucht die App keinen Provider-Key (User-Vorgabe) und wir können Modelle
tauschen, ohne die App anzufassen.

| Anbieter | Frei-Kontingent (Free-Tier) | Für uns relevant, weil | Vorbehalt |
|---|---|---|---|
| Google AI Studio (Gemini Flash/Flash-Lite) | 15–30 RPM, 1.500 RPD, 1M Kontext | langer Kontext (ganze Seite in 1 Call), solide JSON-Ausgabe | Free-Tier-Prompts dürfen zur Produktverbesserung genutzt werden; kein EU-Hosting |
| OpenRouter (Free-Router) | 20 RPM, 50 RPD (1.000 RPD nach 10 $ Guthaben) | **schon in litellm verdrahtet**, ein Key für viele Modelle, Ausweichmodell bei 429 | Free-Router rotiert das Modell → Antwortqualität streut (Belegprüfung fängt das ab) |
| Cerebras | ~1 Mio. Tokens/Tag, 30 RPM | Volumen-Reserve für Nachläufe | Modellpalette wechselt |
| Groq | 30 RPM, 1.000 RPD | sehr schnell, gut für Retries | Modell-Deprecations (2026 diverse) |
| Mistral (Experiment) | ~1 Mrd. Tokens/Monat, ~1 RPS | EU-Anbieter (FR), viel Volumen | **Training-Opt-in** im Free-Modus → für Mails ungeeignet, für öffentliche Seiten vertretbar |
| Cloudflare Workers AI | 10.000 Neurons/Tag | schlanke Extraktion/Klassifikation | kleinere Kontexte, Modellkatalog wechselt |
| OVH AI Endpoints / Scaleway Generative APIs (EU) | Free-Tiers mit harten Limits | **EU-Hosting ohne Training** — Kandidat für die Mail-Verarbeitung | kleine Modelle, Limits niedrig |

Quellen: Anbieter-Doku plus die Sammel-Auswertungen
`openrouter.ai/blog/tutorials/free-llm-apis-compared`,
`github.com/mnfst/awesome-free-llm-apis`, `edenai.co/post/top-free-llm-tools…`
(jeweils Stand 2026). **Vor der Umsetzung wird die Matrix gegen die
Anbieter-Doku nachgeprüft** — Free-Tiers ändern sich; Zahlen sind hier
Rechercheergebnis, keine Zusage.

**Zwei Datenklassen, zwei Regeln:**

- **Öffentliche Webinhalte** (Schul-Homepage): Free-Tier erlaubt. Empfehlung:
  primär Gemini Flash-Lite (Kontext), Ausweich OpenRouter-Free-Router,
  Reserve Cerebras. Alles über litellm, Modellnamen als Einstellung.
- **Eingehende Mails** (Name, Funktion, Signatur, ggf. Telefonnummer =
  personenbezogene Daten): **nicht** an einen US-Free-Tier. Optionen:
  (a) lokal auf der KI-Box (RTX 3090) — datenschutzfreundlich, kein
  Kontingent, konkurriert aber mit ComfyUI-Jobs um die GPU;
  (b) EU-Endpunkt mit Auftragsverarbeitungsvertrag (Mistral zahlend, OVH,
  Scaleway); (c) kein Auto-Parsing, sondern Antwort im Admin anzeigen und
  Vorschlag per Knopfdruck erzeugen. **Entscheidung des Users** — die
  Umsetzung kapselt das als `mail_llm_pfad`-Einstellung, damit alle drei
  Wege ohne Umbau möglich sind.

### 4a. Gemessener lokaler Endpunkt (KI-Box, 13.09.2026)

`llama-server` auf der KI-Box (Container `llama-server`, Restart
`unless-stopped`, Startdatei `/opt/container/llama.cpp/compose.yml`) lädt
`gemma-4-12B-it-qat-UD-Q4_K_XL.gguf` mit MTP-Draft-Modell, 131k Kontext,
Alias **`llamacpp-gemma4-12B-unsloth`**.

- **Erreichbar vom App-Host .50** über NetBird `http://100.117.139.29:8080/v1`
  und im LAN über `http://<LLM_PORT>/v1` (beide verifiziert, echter
  Completion-Call). GPU-Belegung 13,6 von 24,5 GB → läuft parallel zu ComfyUI.
- **Pflicht-Einstellung:** `chat_template_kwargs: {"enable_thinking": false}`.
  Mit Thinking liefert das Modell `content: ""` und `finish_reason: length`
  (die Denk-Tokens fressen das Budget) — für die Extraktion unbrauchbar.
- **Messwerte** (echte Seite Grundschule im Eliashof, Thinking aus): 0,7 s für
  einen vollständigen Extraktions-Call, 263 tok/s Generierung, Ergebnis exakt
  der gesuchte Termin (`17.09.2026`, `09:30 bis 11:30 Uhr`) samt wörtlichem
  Belegzitat — also genau der Fall, an dem der Free-Router in zwei Läufen
  gescheitert ist (einmal „kein JSON", einmal kein Fund).
- **Konsequenz für die Modellwahl:** der lokale Endpunkt ist der bevorzugte
  Extraktor (deterministisch verfügbar, kein Kontingent, kein Datenschutz-
  problem, ~20–60× schneller als der Free-Router); freie Cloud-Endpunkte
  bleiben Ausweichpfad. Registrierung in litellm ist vorgesehen (einheitlicher
  Zugang), scheitert derzeit aber an fehlendem Konfigurationszugang zum
  litellm-Host; der Direktweg vom App-Container ist gemessen und funktioniert.


## 5. Kontingent- und Kostenrechnung

Annahmen aus dem Bestand: 276 Grundschulen ohne Regelweg; ~50 % davon haben
überhaupt ein Termin-Indiz; 1 Call je geänderter Seite; Seitenwechsel selten
(TdOT-Seite ändert sich 1–3× je Schuljahr).

- **Erstlauf:** ~140 Calls à ~3.000 Eingabe-Tokens → ~0,4 Mio. Tokens. Passt
  in jeden der Free-Tiers oben (Gemini 1.500 RPD, Cerebras 1 Mio. Tokens/Tag,
  Cerebras/Mistral reichlich). Nachtfenster mit 6 s Abstand → ~15 min.
- **Regelbetrieb:** wöchentlicher Re-Check, nur geänderte Seiten: erfahrungs-
  gemäß < 10 Calls/Lauf.
- **Ganzjährig:** weit unter 10.000 Calls. Kosten: **0 €** im Free-Pfad.
  Als Notnagel dokumentiert: derselbe Job über ein bezahltes Modell in litellm
  (bei dieser Menge deutlich unter 1 €/Monat) — Umschalten ist eine
  Einstellung, kein Code.
- **Endpunkt-Tod ist der Normalfall,** nicht die Ausnahme: 429/5xx →
  exponentieller Backoff, dann Ausweichmodell, dann Lauf abbrechen **mit
  sichtbarem Zustand** und Alarm. Kein stiller Teil-Lauf.

## 6. Prompt, Schema, Belegpflicht (Anti-Halluzination)

Ablauf je Kandidatenseite:

1. Text normalisieren (Scripts/Styles raus, Entitäten auflösen, Whitespace
   kollabieren), auf ~9.000 Zeichen um die Termin-Stellen schneiden.
2. Ein Call mit JSON-Zwang, Zielschema je Termin:
   `titel` (aus dem engen Vokabular), `datum` TT.MM.JJJJ, `zeit` HH:MM|null,
   `beleg` (wörtliches Zitat ≤ 200 Zeichen), `sicherheit`
   (hoch/mittel/niedrig). Kein Datum im Text → kein Termin.
3. **Deterministische Prüfung (die eigentliche Absicherung)** — jeder
   Vorschlag fällt raus, wenn eine der Bedingungen verletzt ist:
   - `beleg` (whitespace-normalisiert, case-insensitiv, ≥ 15 Zeichen) ist
     **Substring des Seitentextes** → erfindet das Modell, fliegt es auf;
   - Datum parst und liegt in `[heute, heute+400 Tage]`;
   - Titel gehört zur Zielklasse (TdoT/Infoabend/Schnuppern/Anmeldung);
   - Zeit, wenn angegeben, ist plausibel (05:00–22:00, Ende > Start);
   - keine Dublette (Schule + Datum + Titelnormalform bereits vorhanden
     → bestehender Eintrag wird nur ergänzt, nicht doppelt angelegt).
4. Nur geprüfte Vorschläge werden `termine_manuell` (`status='ungeprueft'`,
   `quelle_hinweis` = „LLM-Recherche: <url> | Zitat: … | Modell: …").

Optionaler Zusatz bei strittigen Fällen (Sicherheit „niedrig" oder mehrere
Daten in einem Satz): zweiter Call mit einem anderen Modell; nur bei
übereinstimmendem Datum wird der Vorschlag angelegt, sonst als „unklar"
markiert. Nicht als Standard — das verdoppelt die Calls ohne proportionalen
Nutzen.

## 7. Datenmodell (Erweiterung, abwärtskompatibel)

Neu (per `ALTER TABLE`/`CREATE TABLE IF NOT EXISTS` im bestehenden
Migrationsmuster von `app/store.py`):

- `schulen` + Spalten: `recherche_am`, `recherche_status`
  (gefunden|keinFund|keinIndiz|abrufFehler|uebersprungen),
  `recherche_notiz`, `anfrage_status`
  (offen|gesendet|antwort|keinBedarf|unzustellbar),
  `anfrage_token`, `antwort_am`.
- `schul_recherche_lauf`: `id`, `bsn`, `url`, `seiten_hash`, `modell`,
  `text_zeichen`, `n_roh`, `n_belegt`, `verworfen_grund`, `dauer_s`,
  `erstellt_am` — jede LLM-Antwort ist nachvollziehbar, auch die verworfene.
- `schul_mail_eingang`: `message_id`, `in_reply_to`, `references`, `bsn`,
  `von`, `betreff`, `empfangen_am`, `body_text`, `anhaenge` (JSON),
  `verarbeitet_am`, `ergebnis` (termine|keinBedarf|autoantwort|unzustellbar|
  unklar), `fehler`.

`termine_manuell` bleibt unverändert die Queue; keine öffentliche
Verhaltensänderung ohne `bestaetigt`.

## 8. Mail-Anfrage (Ausgang)

- **Absender:** Einrichtungsadresse mit Klarnamen (CIA Spandau / kinderkram).
  Die bestehende Vorlage (`DEFAULT_MAIL_VORLAGE` in `app/admin_api.py`) hat
  noch Platzhalter `[Name / Einrichtung]` / `[Kontakt]` — die werden bei der
  Umsetzung aus den Einstellungen gefüllt, sonst geht keine Mail raus.
- **Reply-To = das Tool-Postfach selbst** (`kinderkram@…`), wie vom User
  gewünscht; damit landen Antworten im verarbeiteten Postfach, nicht in einem
  Personeneingang.
- **Betreff enthält den Vorgangs-Token** `[KK-<BSN>-<Schuljahr>]` — robust
  auch dann, wenn ein Mailprogramm die Thread-Header zerlegt. Primärweg der
  Zuordnung bleibt `In-Reply-To`/`References` gegen die gespeicherte
  `Message-ID`.
- **Text:** bestehende Vorlage, ergänzt um (a) konkrete Frage in einem Satz,
  (b) Hinweis „eine Mail pro Schuljahr, keine Erinnerungen", (c) Opt-out-
  Satz, (d) Link auf den Datenschutzhinweis. Kein Tracking, keine Bilder,
  kein Link-Pixel.
- **Drosselung:** Mo–Fr 08:00–16:00, max. 20 Mails/Stunde, max. 1 Mail je
  Schule und Schuljahr, keine Wiederholung an dieselbe Adresse innerhalb von
  12 Monaten; Treffer nur Schulen, bei denen Stufe 1 und 2 leer blieben und
  eine Kontaktadresse existiert.
- **Sichtbarkeit:** jede Mail erzeugt eine Zeile im Schul-Status; der Admin
  kann denselben Versand weiter einzeln oder als Liste auslösen.

## 9. Postfach-Eingang (Antwort-Verarbeitung)

- **Abruf:** IMAP (Host/Port/User/Pass als Einstellungen, Muster wie
  `smtp_*`), Poll alle 10 Minuten im Scheduler, ausschließlich INBOX der
  Tool-Adresse, `\Seen` bleibt unangetastet, Rohmail wird als Datei abgelegt
  (Nachweisbarkeit), Löschfrist konfigurierbar.
- **Zuordnung:** `In-Reply-To`/`References` → Token im Betreff →
  Absenderadresse gegen Schul-Stamm (in dieser Reihenfolge; kein Treffer =
  Status „unklar" mit roher Anzeige im Admin, nichts wird still verworfen).
- **Inhalt:** Text aus Plaintext/HTML; Anhänge: PDF → Text via pymupdf;
  Bilder/Tabellen → nicht interpretieren, sondern als „Anhang bitte prüfen"
  am Vorschlag vermerken.
- **Extraktion:** dasselbe Schema und dieselbe Belegprüfung wie in §6, nur
  mit dem Mailtext als Quelle (Zitat = Satz aus der Mail). Termine →
  `termine_manuell` mit `quelle_hinweis` „Antwort-Mail vom <Datum>,
  <Absenderadresse>".
- **Sonderfälle werden zu Status, nicht zu Fehlern:** Auto-Antwort/Abwesenheit
  (`Auto-Submitted`/`X-Autoreply`) → „später erneut", Bounce
  (`Mailer-Daemon`, `Undelivered`) → „unzustellbar" (Adresse im Admin
  markieren), Absage/„kein TdoT" → „keinBedarf" mit Belegzitat,
  Rückfrage („was genau brauchen Sie?") → „Rückfrage" mit Vorschlagstext im
  Admin (Versand bleibt beim Menschen).

## 10. Betrieb, Sichtbarkeit, Alarme

- **Admin-Bereich „Recherche":** Tabelle je Schule (Bezirk/Schulform/Filter)
  mit Recherche-Stand, Fund, Belegzitat, Fund-URL, „jetzt prüfen"-Knopf,
  Sammel-Lauf mit Fortschritt (x/y) und Abbruch; ohne Fund → Sammel-Aktion
  „Anfrage-Mail senden".
- **Admin-Bereich „Mail-Eingang":** Liste der Antworten mit Zuordnung,
  extrahierten Terminvorschlägen, Sonderfall-Status und Rohmail-Download.
- **Alarme (bestehender Kanal):** LLM-Fehlerquote > 30 % in einem Lauf;
  0 belegte Funde bei ≥ 20 geprüften Schulen (Indiz für kaputten Endpunkt);
  IMAP-Login schlägt 3× hintereinander fehl; Bounce-Quote der Anfragemails
  > 10 %. Immer mit dem, was der Admin tun muss.
- **Datenschutz im Betrieb:** Antwortmails werden zweckgebunden gespeichert
  (Schul-Termine), Löschfrist (Vorschlag 24 Monate) läuft im Scheduler;
  Kontaktdaten der Schulen sind öffentliche Dienststellendaten, private
  Ansprechpartner werden nicht in `events` übernommen.

## 11. Geprüfte Alternativen

| Alternative | Bewertung |
|---|---|
| Nur Mail-Anfragen, kein Scraping | skaliert nicht (Rücklaufquote, Zeitpunkt: TdoT-Termine kommen nach dem Termin), bleibt als **Stufe 3** erhalten |
| Nur bessere Regex/mehr Regeln | am eigenen Bestand gemessen: 0 Regeln aus 23 A-Schulen; Monatsnamen/PDF/Fließtext sprengen Regex-Pflege |
| Bezahl-LLM dauerhaft | unnötig bei < 10.000 Calls/Jahr; bleibt als Notnagel in litellm |
| LLM in der Event-Pipeline | verletzt die Laufzeit-Invariante (Latenz, Ausfall, Kosten, Reproduzierbarkeit) |
| Zwei-Modell-Konsens für alles | doppelte Calls, kein proportionaler Gewinn; nur für strittige Einzelfälle |
| Captcha/Turnstile umgehen | rechtlich/ethisch nicht als Dauerbetrieb; Einzelfälle bleiben manuell |
| Volltext der Seiten archivieren | Urheberrecht + Speicherminimierung; es reicht Hash + Belegzitat + URL |

## 12. Messbare Erfolgskriterien

1. **Belegtreue:** 100 % der angelegten Vorschläge haben ein im Quelltext
   gefundenes Zitat (Test + Feldprobe). Verworfen wird gezählt, nicht
   verschwiegen.
2. **Precision der Feldprobe:** 20 zufällige Grundschulen werden manuell
   gegengeprüft; Ziel ≥ 80 % korrekte Datumsangaben unter den belegten
   Vorschlägen, 0 erfundene Termine.
3. **Abdeckung:** von den 276 Grundschulen ohne Regelweg liefert Stufe 2 für
   ≥ 25 % einen belegten TdoT/Infoabend-Vorschlag; die übrigen bekommen eine
   Anfrage-Mail.
4. **Keinstille Fehler:** jede Schule ohne Fund trägt einen Grund
   (keinIndiz/keinFund/abrufFehler/uebersprungen).
5. **Kontingent:** Erstlauf < 200 LLM-Calls und < 45 min; Regelbetrieb
   < 20 Calls/Lauf; kein Lauf bricht ohne Alarm ab.
6. **Invariante:** Event-Pipeline unberührt — Test, dass ein Lauf ohne
   LLM-Aufruf (Job aus) identische Events liefert wie vorher.

## 13. Offene Fragen an den User

1. Postfach anlegen: `kinderkram@mekotools.de` bei IONOS (IMAP+SMTP) —
   Zugangsdaten trägt der User in den Admin-Einstellungen ein.
2. Antwort-Mails: lokal auf der KI-Box, EU-Endpunkt mit AVV oder Finger weg
   vom Auto-Parsing? (§4)
3. Anfragen automatisch rausschicken oder erst als Liste mit einem
   „Senden"-Klick (Empfehlung: Liste mit Klick für den ersten Jahrgang,
   später automatisch)?
4. Löschfrist für Antwortmails (Vorschlag 24 Monate) und Impressum/
   Datenschutzhinweis-Text der Einrichtung.
