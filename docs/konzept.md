# Konzept: Meta-Aggregator für Kinder-Veranstaltungen in Berlin (LLM-frei)

> Stand: 2026-09-06 · Status: Konzept zur Review · Autor: Hermes (KI-unterstützt, vom User zu prüfen)

**Goal:** Ein System, das Veranstaltungen mit Kindern in Berlin aus vielen Quellen einsammelt, normalisiert, dedupliziert und als filterbare Übersicht/Feeds bereitstellt — zur Laufzeit **100 % LLM-frei** (deterministisch, offline-fähig, keine API-Kosten).

**Architektur:** Dünne, deklarative Adapter pro Quelle → generische Pipeline (Fetch/Cache → Parse → Normalize → Enrich → Dedupe → Validate → Publish). Regelwerke + strukturierte Daten (JSON-LD/schema.org) ersetzen jede LLM-Nutzung zur Laufzeit.

**Tech-Stack (Vorschlag):** Python 3.12+, httpx + parsel (Scraping), SQLite (WAL) als Store, ssg (statische Site, z.B. 11ty/Python-SSG) + ICS/RSS-Export, systemd-Timer oder Hermes-Cron, Docker-Compose schlank. Keine GPU, keine externen ML-Services.

---

## 1. Zielsetzung & Prinzipien

- **Meta-Ebene:** Nicht nur Einzelquellen scrapen, sondern Quellen *über* Quellen (jup! ist selbst schon ein Kuratier-Portal) mit **kanonischer Event-Merge** (ein Event, viele Quell-Links).
- **LLM-frei = harte Laufzeit-Invariante:** Reproduzierbar, auditierbar, kostenlos im Betrieb, kein Provider-Ausfallrisiko. LLM-Einsatz nur im *Entwicklungs-Loop* (Adapter bauen, Code-Review), nie im kritischen Pfad.
- **Fehler sichtbar:** Stille Fehler (Quelle umgebaut, 0 Events, kaputte Datensätze) sind inakzeptabel → Alarme statt Schweigen.
- **Fakten statt Meinung:** Titel/Zeit/Ort/Link + kurzer eigener Abstract; keine Volltext-Kopie der Beschreibungen (Urheberrecht), Quellen stets verlinkt.

## 2. LLM-frei-Strategie (wo LLM typischerweise „reinkriecht“ → Pendant)

| Typische LLM-Stelle | Deterministisches Pendant |
|---|---|
| Freies HTML parsen | Extraktions-Priorität: ① JSON-LD/schema.org Event ② hEvent-Microformate ③ CSS-Selektoren ④ Regex nur für Einzelfelder |
| Duplikate erkennen (Embedding-Similarity) | Normalisierung + Wort-2-Gram-Shingles + Jaccard, Blocking auf (Tag ±1, Ort, Titel), Union-Find, Schwellen + Review-Queue |
| Kategorien/Alter „verstehen“ | Regel-Lexika (Altersausdrücke, Kategorie-Whitelists) + Quell-Kategorie-Mapping-Tabellen |
| Adressen → Bezirk | Geocoding-Cache (Nominatim) einmalig, danach offline Punkt-in-Polygon gegen Berliner Bezirks-GeoJSON |
| Unsichere Fälle „schätzen“ | Review-Queue mit Ampelsystem (grün=auto, gelb=Review, rot=Fehler) — menschlich, nicht per LLM |
| Adapter nach Site-Redesign reparieren | Entwicklungsaufgabe (darf KI-gestützt sein), erkannt durch Fixture-Snapshots + Struktur-Hash-Alarme |

**Folgekosten-Prinzip:** Wenn eine Regel später nicht mehr reicht (z.B. Altersklassifikation), ist die Eskalation *ein kleines, lokales, trainierbares Modell mit klarer Fehlerquote* — niemals ein Blackbox-LLM-API-Call pro Event.

## 3. Quellen-Matrix

### Verifiziert (06.09.2026, Stichprobe)
- **jup.berlin/events** — offizielles Jugendportal (Betrieb jfsb i.A. SenBJF). Server-gerendertes HTML, Filter nach Bezirk/Kategorie/*Kostenlos*, Pagination `?page=N`, Detail-Slugs `/events/<slug>`, Venue-Name + Datumsangaben im Listing. Sehr guter Adapter-Kandidat (stabile Slug-Struktur). **Hinweis:** kinderkulturkalender-berlin.de speist über die jup!-DB → keine zweite Quelle nötig.
- **familienportal.berlin.de/veranstaltungen** — offizieller Familien-Kalender des Landes Berlin. Existiert; Struktur/API **noch zu auditieren**.
- **berlin.de/land/kalender/?c=158** — Familienwegweiser-Kalender auf berlin.de (Kategorie-Parameter). **Zu auditieren** (ggf. gleiche Datenbasis wie Familienportal).

### Zu auditieren (Phase 1)
- **VÖBB-Veranstaltungen** (voebb.de, Bibliotheks-Events: Vorlesen, Gaming, Ferienprogramm) — aDISWeb-Umfeld (bestehende Skills vorhanden), eigenes Event-Modul prüfen.
- **FEZ Berlin** (fez-berlin.de/programm) — Leit-Einrichtung für Familienprogramm; auf JSON-LD prüfen.
- **Berlin Open Data** (daten.berlin.de) — vermutlich keine zentrale Event-API für Kinder; Einzeldatensätze (z.B. Familienzentren-Standorte) als *Venue/Stammdaten-Ergänzung* nutzen.
- **berlin.de-Veranstaltungskalender** allgemein (Kategorie-Schnittmengen prüfen).

### Kommerzielle Portale (kritisch prüfen)
- **Kindaling** (Buchungsplattform, Tickets ab 39 €), **berlinmitkind.de** u.ä.: ToS/robots.txt entscheiden. Vermutlich **ausschließen oder nur als Hinweisquelle** — rechtlich heikel, oft Affiliate-getrieben, inhaltlich von den offiziellen Quellen abgedeckt.

### Langfristig („Long Tail“): Einrichtungs-Adapter
Museen (Stadtmuseum, Naturkunde, Technikmuseum), Kinder-/Jugendtheater (Parkaue, Grips, ATZE, Morgenstern …), Jugendkunstschulen, Familientreffs — meist mit eigenem Kalender und häufig JSON-LD. Viele kleine Adapter = gleicher Standard-Mechanismus, je Einrichtung nur Konfig + Fixture.

**Prioritätsregel:** offiziell (Land/Bezirk) > gemeinnützige Einrichtung > Portal. Kanonisierung beim Merge richtet sich danach.

## 4. System-Architektur

```
Quellen ──► [Adapter je Quelle] ──► Fetch/Cache ──► Parse ──► Normalize ──► Enrich ──► Dedupe/Merge ──► Validate ──► Publish
              (Konfig + Mini-Parser)   (ETag, Rate-Limit,  (JSON-LD first)   (einheitliches   (Regeln,    (kanonische    (Pflichtfelder, (Statische Site,
                                        robots-Policy,      → hEvent → CSS    Event-Modell)    Geocoding)  Events,         Zeitlogik,      ICS, RSS,
                                        Disk-Cache)                                               Provenienz)   Fehler-Queue)   Digest)
                                                                                                                    │
                                                                                                                    ▼
                                                                                              Monitoring: Metriken, Anomalie-Alarme (ntfy/Matrix), Status-Seite
```

### Komponenten
1. **Adapter** (`adapters/<quelle>.py` + `config`): deklariert Listing-URL(s), Pagination, Selektoren/JSON-LD-Pfade, Rate-Limit, robots-Policy, erwarteten Event-Bereich. Listing- und Detail-Seite getrennt handhabbar.
2. **Fetch-Schicht:** gemeinsamer HTTP-Client (httpx) mit If-Modified-Since/ETag, Retry/Backoff, UA-String, robots.txt-Check (Policy im Adapter dokumentiert), roher Cache auf Disk (für Fixtures & Forensik).
3. **Normalize:** einheitliches Event-Modell → Felder siehe §6 Datenmodell. `event_id = sha1(source_id + "/" + source_event_id)` — deterministisch, idempotent.
4. **Enrich:** regelbasiert (siehe §7).
5. **Dedupe/Merge:** siehe §5 — Kernstück des „Meta“-Anspruchs.
6. **Validate:** Pflichtfelder, `end ≥ start`, Datum im Sicht-Horizont, URL-Format; Ablehnung → Fehler-Queue **mit Alarm**, nie stilles Verwerfen.
7. **Publish:** statische Site + Feeds + Digest-Erzeugung. Kein Server-State zur Laufzeit nötig → billig zu betreiben, gut cachebar.

### Datenmodell (Kern)
- `events`: id (sha1), kanonischer Titel, description_short (eigener Abstract), start/end (lokale Zeit + tz Europe/Berlin), all_day, venue_id, bezirk, altersband (min/max), kategorien[], preis_info, preis_cent|null, kostenlos bool, url_kanonisch, image, status, qualitaet (auto/review), geändert/erstellt.
- `event_sources`: event_id, quelle, source_event_id, source_url, roh_titel, roh_zeit, geholt_am (Provenienz, Mehrfach-Quellen erlaubt).
- `venues`: name_normalisiert, adresse, lat/lon, bezirk.
- `runs`: je Quelle je Lauf: n_events, n_neu, n_geaendert, n_fehler, dauer_s.
- `alerts`/Status: letzter Lauf, Event-Zählung, Struktur-Hash je Quelle.

## 5. Dedupe & Merge (deterministisch)

1. **Normalisierung:** Unicode-NFC, lowercase, Satzzeichen/Emojis raus, Whitespace kollabieren, Stoppwörter-Filter („der/die/das/Berlin/Veranstaltung“), Umlaut-tolerant.
2. **Shingling:** Wort-2-Gramme → Jaccard-Similarity.
3. **Blocking** (nur Kandidaten vergleichen, sonst O(n²)): gleiches Datumsfenster (±1 Tag) UND (Venue-normalisiert ODER ≥1 signifikantes Titel-Wort gemeinsam).
4. **Clustering:** Union-Find über Kanten ≥ Schwelle. Zwei Schwellen: **merge ≥ 0.85** (automatisch), **0.60–0.85 → Review-Queue** (gelb), darunter getrennt.
5. **Kanonisierung:** Priorität offiziell > Einrichtung > Portal; alle Quell-Links bleiben erhalten (`event_sources`); Titel/Zeit vom höchstprioren Beleg, Abweichungen protokolliert.
6. **Serien-Erkennung (später):** gleicher normalisierter Titel + Ort über mehrere Tage (z.B. „Das magische Kochbuch“ läuft täglich) → Serien-Gruppe mit Terminliste statt 15 Einzel-Events in der UI.
7. **Konflikt-Regel:** Ändert eine Quelle einen gemergten Datensatz (Zeit/Ort verschoben), wird das als *Änderung* mit Quelle im Log geführt und bei Relevanz (gelber Bereich) in die Review-Queue gehoben — nie still überschrieben.

## 6. Regelbasierte Anreicherung

- **Altersband:** Regel-Lexikon über Titel+Text: „ab 4/6/8/10“, „6–10 Jahre“, „U12/16“, „für Familien“, „Kinder ab“, „Kita-/Grundschulalter“ … → min/max-Alter oder Kennzeichen `familie`. Nicht klassifizierbar → leer lassen (Filter „ohne Altersangabe“), nicht raten.
- **Kategorien:** eigenes Vokabular (Theater, Musik, Museum, Workshop, Sport, Bibliothek, Fest/Markt, Ferien, Draußen …) via Whitelist-Synonyme + Quell-Kategorie-Mapping-Tabelle (jup!-Kategorien 1:1 mappen).
- **Bezirk:** Venue-Adresse → Geocoding (einmalig, Cache) → Punkt-in-Polygon gegen Bezirks-GeoJSON (offline). Ohne Adresse: Quell-Angabe (jup! liefert Bezirk direkt).
- **Preis:** Quell-Feld (jup!-Filter „Kostenlos“) + Regeln („Eintritt frei“, „kostenfrei“, €-Angaben) → `kostenlos`-Flag und Betrag.

## 7. Qualität, Monitoring, Betrieb

- **Pro Adapter Fixture-Tests:** gespeicherte HTML-Schnappschüsse + erwartete Events; CI oder manuell ausführbar. Site-Umbau → Test rot → Alarm, bevor Nutzer es merken.
- **Struktur-Hash:** Anzahl der Listing-Elemente je Quelle pro Lauf; weicht er ab (>20 %) oder liefert die Quelle 0 Events → **Alert (ntfy/Matrix)** mit Quell-Link.
- **Metriken je Lauf** in `runs`; 7-Tage-Mittel als Referenz; Abfall >50 % = Alarm.
- **Status-Seite/Health-Endpoint:** je Quelle: grün/gelb/rot, letzter erfolgreicher Lauf, Event-Zahl. Gelb = Review-Queue gefüllt, rot = Adapter defekt.
- **Cron:** je Quelle eigener Rhythmus (jup!/Familienportal 1–2×/Tag; Museen/bezirklich wöchentlich reicht meist — Ferienprogramme brauchen Vorlauf, daher im Oktober/Februar/Juli dichter pollen).
- **Deploy:** schlanker Container (Python slim), kein GPU; Kandidaten: Containerhost .50 oder KI-Box; Daten + Cache als Volume. EU-only (ohnehin kein Cloud-Bedarf).

## 8. Rechtliches

- robots.txt + ToS **je Quelle** prüfen, Policy im Adapter dokumentieren; offizielle Verwaltungsquellen (jup!, familienportal, berlin.de) unkritisch, trotzdem Nutzungsbedingungen lesen.
- Nur Faktendaten + Link + eigener Abstract; keine Beschreibungstexte 1:1 übernehmen. Quellen/Impressum angeben, Verlinkung zurück.
- Keine personenbezogenen Daten (Veranstalter-Kontaktdaten nicht speichern) → DSGVO weitgehend entlastet.
- Aggregatoren wie Kindaling: Terms prüfen — bei Affiliate-/Buchungsmodellen i.d.R. Ausschluss.

## 9. Phasenplan

- **Phase 0 — Quellen-Audit (2–3 Tage):** familienportal.berlin.de, berlin.de-Kalender, VÖBB-Events, FEZ auf Struktur/JSON-LD/robots prüfen; Source-Matrix finalisieren. Ergebnis: Tabelle je Quelle (Typ, Frequenz, Lizenz, erwarteter Ertrag).
- **Phase 1 — Kern-Pipeline + 2 Pilotquellen:** Datenmodell, Fetch/Cache, Normalize, Validate, Store; Adapter **jup! Berlin** + **familienportal.berlin.de**. Abnahme-Kriterium: täglicher Lauf ohne LLM, Fixture-Tests grün, 0-Events-Alarm nachweisbar.
- **Phase 2 — Enrich + Dedupe:** Regeln, Bezirk-Offline-Matching, Merge mit Review-Queue; manuelles Prüfen an 2 Wochen Real-Daten (Recall/Precision der Dedupe-Schwellen kalibrieren).
- **Phase 3 — Publish:** filterbare statische Site (Datum/Bezirk/Alter/kostenlos), ICS je Filter, RSS; Digest (E-Mail/ntfy) via Cron.
- **Phase 4 — Skalierung:** VÖBB/FEZ/Einrichtungs-Long-Tail, Serien-Erkennung, Status-Seite öffentlich.

## 10. Offene Fragen / Annahmen

1. **Zweck & Publikum:** öffentlicher Familien-Kalender (ganz Berlin oder Kiez/Bezirk-Fokus?) oder internes Werkzeug (eigene Programmplanung, Kooperations-/Konkurrenz-Scouting für das Medienkompetenzzentrum)? → bestimmt Quellen-Priorität und UI.
2. **Konsum:** Website + Feeds, wöchentlicher Digest, ICS-Abo — was ist Pflicht im MVP?
3. **Bezahlte Events:** nur kostenlos/günstig oder auch kommerzielle (Tickets)? (beeinflusst Kindaling-Frage)
4. **Pflege-Budget:** 10 vs. 50 Quellen — Adapter-Wartung ist der Dauerposten; wer pflegt?
5. **Deploy-Ziel:** Containerhost .50 oder KI-Box?

**Annahmen (zu bestätigen):** Berlin-weiter Scope; Python; Selbsthost auf vorhandener Infrastruktur; Englisch/Deutsch-UI (vermutlich deutsch); Datenhaltung SQLite reicht für MVP (kein Multi-Writer).
