# Change 010: Schultermine per LLM-Recherche finden + automatische Mail-Anfrage und Antwort-Verarbeitung

**Status:** Konzept zur Review (2026-09-13)
**Basis:** Change 005 (Schul-Admin, `termine_manuell` + Mail-Anfrage) — dort endet der Weg heute beim manuellen Pflegen
**Autor:** Hermes (KI-unterstützt, vom User zu prüfen)

## Why

Der regelbasierte Weg reicht für die Schulen nicht: Von 722 allgemeinbildenden
Schulen (WFS-Stamm, 439 Grundschulen) haben nach der Website-Analyse
(`komplett_analyse_out.json`, 699 Seiten), dem RSS-/IServ-Audit und dem
Strato-Crawl (118 Schulen, 2026-09-07) nur **271** einen regelbasiert
auswertbaren Weg (Website-Stufe A: `<time>`/JSON-LD/ICS). **215** haben Termine
nur unstrukturiert im Text (Stufe B), **236** liefern nichts Abrufbares
(Schutz/keine Seite). Bei den **Grundschulen** ist das Verhältnis schlechter:
163 scraper / **124 manuell** / **152 mail** — also **276 von 439 (63 %) ohne
regelbasierten Weg**.

Zwei Befunde aus dem eigenen Crawl belegen, dass nicht der Zugang, sondern das
*Verstehen* fehlt:

- Der Strato-Crawl fand **667 datums-/terminartige Rohtreffer in 47 von 118
  Schulen** — die Rohinformation ist da, sie ist nur nicht maschinenlesbar
  ausgezeichnet (News-Zeitstempel, Jahre 2024, Monatsnamen-Schreibweise
  „Tag der offenen Tür 17. September 2026").
- Die automatische Regel-Ableitung über die 23 „Stufe A"-Schulen lieferte
  **0 Regeln** (`strato_regeln_schulen.yaml` leer). „A" heißt Datums-*Dichte*
  im Text, nicht wiederkehrende Item-Struktur. Die Zahl 271 ist eine
  optimistische Obergrenze.

Anlassfall: Die Grundschulen veröffentlichen ihre Tage der offenen Tür im
September/Oktober — verstreut in Fließtext, PDF-Jahresplänen, News-Einträgen.
Nur ein Bruchteil ist automatisch zu holen.

## What Changes

- **Neuer Recherche-Job (LLM, out-of-band):** Für Schulen **ohne**
  regelbasierte Quelle holt ein Job Homepage + bis zu zwei terminrelevante
  Folgeseiten, lässt daraus ausschließlich TdoT-/Infoabend-/Schnuppertage
  extrahieren und legt Treffer als `termine_manuell` mit Status `ungeprueft`
  in die **bestehende Freigabe-Queue** (Herkunft + wörtliches Belegzitat im
  `quelle_hinweis`). Der Admin prüft und bestätigt wie bisher — die
  öffentliche Karte ändert sich nur über diese Freigabe.
- **LLM-frei-Invariante bleibt:** Die Event-Pipeline (Fetch/Parse/Normalize/
  Enrich/Dedupe/Publish) ruft weiterhin kein LLM. Die Recherche ist ein
  separater, standardmäßig **abgeschalteter** Job im selben Prozess (ein
  SQLite-Schreiber, kein paralleler Job gegen dieselbe Quell-IP).
- **Alle LLM-Aufrufe über litellm** (`https://litellm.n0ne.de`), Modellname
  als Einstellung; **freie Endpunkte** werden dort als Modelle registriert
  (u. a. der bereits vorhandene OpenRouter-Free-Router
  `openrouter/openrouter/free`, Gemini-Flash-Free, Cerebras). Kein
  Provider-Key in der App, kein Abo.
- **Automatische Termin-Anfrage-Mail** an Schulen, bei denen die Recherche
  nichts gefunden hat: eine Mail je Schule und Schuljahr, Werktag 8–16 Uhr,
  gedrosselt, mit `Reply-To` = **das Tool-Postfach selbst**
  (`kinderkram@…`) und Vorgangs-Token im Betreff.
- **Eigener Postfach-Eingang:** Das Tool liest sein Postfach (IMAP), ordnet
  Antworten über `In-Reply-To`/`References` + Token der Schule zu, übersetzt
  sie per LLM in Terminvorschläge (wieder mit wörtlichem Beleg) und legt sie
  als `ungeprueft` in dieselbe Queue. Auto-Antworten, Bounces und „wir haben
  keinen TdoT" werden erkannt und als **sichtbarer Schul-Status** geführt —
  nichts wird still verworfen.
- **Anti-Halluzination als harte Bedingung:** Ein Terminvorschlag wird nur
  angelegt, wenn das vom Modell geforderte **wörtliche Zitat im Seitentext
  (bzw. im Mailtext) vorkommt**, das Datum im Sicht-Horizont liegt und der
  Titel zur Zielklasse gehört. Alles andere wird verworfen und protokolliert.
- **Sichtbarkeit statt Stille:** Recherche-Stand je Schule (wann geprüft,
  wie viele Seiten, Fund/kein Fund, Fehlergrund), Mail-Stand
  (angefragt/antwortet/kein Bedarf) und ein Zähler, wie viele Vorschläge je
  Lauf belegt/verworfen wurden. Bei LLM-Fehlerquote oder leerem Postfach-Login
  gibt es einen Alarm.
- **Manuell bleibt manuell:** Der bestehende Einzel-Mail-Versand und die
  Termin-Pflege im Admin bleiben unverändert; der Job nimmt dem Admin nur die
  Suche ab.

## Specs-Delta

- `ADDED specs/schul-recherche/spec.md` — neue Capability: LLM-Recherche,
  Belegpflicht, Vorschlags-Queue, Sichtbarkeit/Alarme (inkl. der Klarstellung,
  dass die LLM-frei-Invariante der Event-Pipeline unangetastet bleibt).
- Live-Specs `aggregation`, `quellen`, `api-events`, `karte-ui` bleiben
  unangetastet: Der Recherche-Weg ist **kein** Adapter und keine Quelle im
  Sinne der Extraktions-Priorität, und die öffentliche Ausgabe ändert sich nur
  über bestätigte `termine_manuell` (bestehender Weg aus Change 005).

## Nicht im Umfang (bewusst)

- Kein LLM in der Event-Pipeline, kein LLM für Dedupe/Geo/Kategorien.
- Keine Umgehung harter Zugangssperren: 3 Schulen blocken jeden Browser
  (403), 8 gehen nur per Camoufox+Residential, Turnstile / iframe-JS-Kalender
  bleiben Handarbeit bzw. Mail — das löst ein LLM nicht und soll es nicht
  (kein Captcha-Bruch, keine Proxy-Tricks als Dauerbetrieb).
- Kein Versand an Schulen, die keine Kontaktadresse im Stamm haben (23 ohne
  Website, davon einige ohne E-Mail) — die bleiben in der manuellen Liste.
- Kein Volltext-Archiv der Schul-Webseiten dauerhaft; gespeichert werden
  Fund-URL, Belegzitat, Zeitpunkt, Modell und Seiten-Hash.

## Risiken / offene Punkte (vor Umsetzung klären)

1. **Freie Endpunkte und Kontingente:** Free-Tiers haben RPM/RPD-Grenzen und
   können sich ändern; einige dürfen Prompts zum Training nutzen. Deshalb:
   öffentliche Webinhalte → Free-Tier ok; **eingehende Mails mit
   Personenbezug** → bevorzugt lokal (KI-Box) oder EU-Endpunkt mit
   Auftragsverarbeitung. Entscheidung des Users nötig (siehe design.md §4).
2. **Postfach:** `kinderkram@cia-spandau.org` muss als Postfach existieren
   (MX = IONOS bestätigt). IMAP-Zugang als Admin-Einstellung, nicht im Repo.
3. **Rechtliches:** einmalige, sachliche Terminanfrage mit Absender,
   Kontakt und Opt-out-Satz; Datenschutzhinweis (Art. 14) verlinken;
   Löschfrist für Antworten festlegen.
4. **Precision:** Ein falscher Termin auf der öffentlichen Karte ist teurer
   als ein fehlender. Deshalb Freigabe-Queue als Pflicht und eine
   Feldprobe (20 Schulen, manuell gegengeprüft), bevor die Auto-Mail scharf
   geschaltet wird.

## Downgrade

Recherche-Job und Postfach-Eingang abschalten (Standard ist aus), Mail-Versand
wie in Change 005 manuell je Schule. Die neuen Tabellen/Spalten bleiben liegen,
die öffentliche Ausgabe ist davon unabhängig.
