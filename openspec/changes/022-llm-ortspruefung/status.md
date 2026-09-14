# 022 — Ort aus dem Beschreibungstext gewinnen (LLM-Stufe mit Prüfliste)

**Status:** Entwurf, Messung läuft (2026-09-14)
**Anlass:** Nach Change 019 bleiben Termine ohne Ortsnamen. Gemessen: 818 von
2828 Terminen ohne Position, davon rund 700 mit auswertbarem Seitentext.

## Befund (Messung, 2026-09-14)

Stichprobe 45 echte Detailseiten (umweltkalender-berlin, industriekultur-berlin),
Modell wie in Produktion:

- **34 von 45 (75 %)** Seiten nannten den Ort im Fließtext, wo die Regel keinen
  findet — **alle 34 mit wörtlichem Belegzitat**, das im Text nachweisbar war
  (Anti-Halluzinations-Prüfung), 0 Modellfehler.
- Beispiele: „ZKSI Flughafen Tegel 1", „Parkeingang Kienbergpark",
  „Kulturlabor Trial&Error", „Café TorEins", „Bhf. Potsdamer Platz",
  „Tor zum Grünflächenamt".
- 11 Seiten nannten wirklich keinen Ort („WONK 2026", „BSR-Kieztag") — dort ist
  keine Angabe die richtige Antwort.
- Gegenprobe zur Textmenge: **9 von 10** Seiten OHNE gepflegte Kurzbeschreibung
  haben trotzdem 700–3200 Zeichen Fließtext (PLZ und Treffpunkt-Hinweise
  enthalten). Die Kandidatenmenge ist also nicht auf die 587 Termine mit
  Kurztext begrenzt.

## Entwurf

**Kein Ort ohne Textbeleg.** Der Vorschlag wird nur angenommen, wenn das
Belegzitat wörtlich im Seitentext steht.

**Eigene Stufe, nicht im Adapter.** Der Adapter-Code nennt die Invariante
„rein deterministisch, kein LLM" (`app/adapters/__init__.py`). Die Prüfung läuft
deshalb als eigene Stufe nach der Pipeline (Muster: `app/enrich.py`), mit
eigenem Schalter, eigener Laufzeitmessung und sichtbaren Fehlern.

**Nie überschreiben.** Ergebnis landet in getrennten Feldern
(`ort_ki`, `adresse_ki`, `beleg_ki`, `modell_ki`, `ki_geprueft_am`, Status
`vorschlag` / `uebernommen` / `verworfen`). Der deterministisch gewonnene Wert
bleibt unangetastet, bis ein Mensch übernimmt.

**Mensch entscheidet.** Prüfliste im Admin: Vorschlag, wörtlicher Beleg,
Modell, Zeitpunkt und **Link zur Fundstelle** (Quell-URL, möglichst Sprung zur
Textstelle). Übernehmen / Verwerfen je Eintrag; erst die Übernahme macht den
Wert zur offiziellen Ortsangabe, mit sichtbarer Herkunft „aus
Beschreibungstext".

**Automatische Plausibilitätsprüfung vor der Prüfliste** (aus dem Schattenlauf):

- Belegzitat muss wörtlich im Text vorkommen.
- Wert muss mit Großbuchstaben beginnen und darf kein Satzfragment sein
  (Fund: `„unserem Büro"` — Pronomen, kleingeschrieben).
- Generische Angaben sind keine Orte: „online", „vielerorts", „Berlinweit",
  „Berlin", „Ohne Angabe" → kein Vorschlag.
- Erfundene Adressen fallen automatisch durch die bestehende amtliche
  Geokodierung (WFS); ohne Treffer keine Position.
- Vorschläge ohne Ort *und* Adresse werden nicht gespeichert.

**Textquelle je Quellentyp:** Seitenquellen (`typ: regeln`) → Detailseite,
Text der Felder + Abschnitt; Feed-Quellen (`typ: feed`) → gespeicherte
Beschreibung (kein Abruf); `typ: intern` (jup-berlin) → Beschreibung aus dem
Adapter.

## Erwartung

Etwa 500 der rund 700 Kandidaten bekommen einen Vorschlag. Nutzen: richtige
Ortsnamen im Ortsfilter statt Straßen (Change 019-Rest) und überhaupt eine
Position für Termine der Quellen familienportal, Polizei-Kalender,
Kinderkulturkalender.

## Schattenlauf (1282 Termine, 2026-09-14, 66 min)

Modell wie in Produktion (`llamacpp-gemma4-12B-unsloth`, KI-Box), Text je Quelle
(Seitenquellen: Detailseite; Feed-Quellen: gespeicherte Beschreibung), nichts
gespeichert, nichts übernommen.

| Größe | Zahl |
| --- | --- |
| geprüfte Termine | 1282 |
| Funde mit wörtlichem Beleg | 1058 |
| **saubere Vorschläge nach Filter** | **670 Termine / 270 verschiedene Orte** |
| davon mit Adresse (Chance auf neue Position) | 243 |
| Grenzfälle (Ort beschrieben statt benannt) | 79 |
| ohne Fund im Text | 170 |
| Text zu kurz (Feed-Beschreibung) | 39 |
| Modell-/Abruffehler | 0 |

Beleg-Herkunft der 270 Orte: Fließtext 152, Ort-Feld 82, Anbieter-Feld 36.
Letzteres ist die Gruppe, die ein Mensch genauer ansehen muss: der Veranstalter
ist oft, aber nicht immer der Ort (Verein führt durch einen Park).

**Was der Filter rausgeholt hat** (Regeln aus dem Lauf, nicht ausgedacht):

- **155 × Bezirksname statt Ort** — dieselbe Fehlerklasse wie Change 019, nur
  diesmal vom Modell: „Pankow (26 Termine)", „Neukölln (22)", „Friedrichs-
  hain-Kreuzberg, Lichtenberg, Pankow". Der Ortswert muss dieselbe
  Bezirksprüfung durchlaufen wie der Regelwert.
- **185 × kein wörtlicher Beleg** — Behauptungen ohne Fundstelle im Text. Ohne
  diese Prüfung wären sie in die Prüfliste gekommen; mit ihr fallen sie auf.
- 87 × Vorschlag gleich bisheriger Wert (kein Gewinn), 43 × generisch
  („online", „vielerorts", „Berlinweit"), 21 × beginnt klein („unserem Büro"),
  2 × Pronomen-Fragment, 1 × Länge, 39 × Text zu kurz.
- Zusätzlich gekürzt: Lagebeschreibungen („Gendarmenmarkt direkt vor der
  Freitreppe des Konzerthauses Berlin" → Name + Treffpunkt-Zusatz).

**Gegenprobe (7 Vorschläge quer über vier Quellen):** Ortsname *und* Belegzitat
auf der Quellseite nachweisbar — Tierpark Berlin, Zeiss-Großplanetarium,
Museumsdorf Düppel, Umweltbildungszentrum NIRGENDWO, Industriesalon
Schönewoode, Wasserturm Prenzlauer Berg, Gendarmenmarkt.

Prüfliste: `/opt/data/probe/llm_ort_pruefliste.md` und `.csv`.

## Prompt v2 (14.09.2026, nach Nutzerfund „Besuchszentrum")

**Fund:** Vorschlag „Besuchszentrum" für details/98890, richtig wäre „Botanischer
Garten". Die Seite nennt das Feld `Ort/Treffpunkt: Steglitz-Zehlendorf,
Königin-Luise-Str. 6-8, 14195 Berlin, Besuchszentrum, Eingang Königin-Luise-Platz`
— der Teil **nach** der PLZ ist ein Teilbereich/Treffpunkt, nicht der Ort. Die
Einrichtung steht an zwei anderen Stellen: `Anbieter: Botanischer Garten und
Botanisches Museum Berlin` und im Beschreibungstext („… ist der Botanische Garten
Berlin …"). Beide Stufen hatten also „recht" und das Ergebnis war trotzdem falsch.

**Änderung:** Der Prompt verlangt die **Einrichtung/das Gelände**. Teilbereiche
(Besuchszentrum, Eingang, Kasse, Werkstatt, Pavillon) und Haltestellen/Parkplätze
(„S Rummelsburg", „Parkplatz Paulsborn") sind ausdrücklich *nicht* der Ort; sie
wandern in ein **eigenes Feld `treffpunkt`**. Fehlt die Einrichtung im Ort-Feld,
muss sie aus Anbieter-Feld oder Beschreibungstext kommen (Zitatpflicht bleibt).

**Zwei Prüfungen wurden dabei nachgeschärft:**

1. **Namentest statt Zitat-Test.** Bisher musste das Belegzitat wörtlich
   vorkommen; das verwarf korrekte Vorschläge, wenn das Modell die Formulierung
   leicht änderte. Jetzt wird geprüft, dass der **vorgeschlagene Name selbst**
   wörtlich auf der Quellseite steht (das Zitat ist nur der Zeiger). Messung:
   **7 von 7** so verworfenen Vorschlägen standen wörtlich im Text.
2. **Abstandsbänder statt binärem „ortsgleich".** Der Vorschlag wird geokodiert
   und mit der Adresse verglichen. Die 300-m-Schwelle war zu streng: „Botanischer
   Garten" liegt **431 m** vom Museumsgebäude (Königin-Luise-Str. 6-8) — Parks,
   Gärten und Campusflächen sind mehrere hundert Meter groß. Bänder: bis 300 m
   „an derselben Adresse", bis 1 km „gleiche Anlage", darüber „nicht ortsgleich".

**Messung v1 gegen v2** (839 gemeinsame umweltkalender-Termine, Vollauf 56 min,
0 Modellfehler):

| Ergebnis | Termine |
| --- | --- |
| unverändert gültig | 532 |
| **Gewinn** (v1 Bezirksname/Grafik → v2 echter Ortsname) | **120** |
| Teilbereich/Treffpunkt → Einrichtungsname | 3 |
| Name → Teilbereich (Abwertung) | **0** |
| v2 findet nichts, v1 hatte einen gültigen Namen | 28 |
| beide ungültig/leer | 156 |

Die 28 „Verluste" sind nach Prüfung **keine**: 20 haben einen Treffpunkt im neuen
Feld (z. B. „Mettmannplatz"), 7 waren die fälschlich verworfenen (siehe oben),
1 war in v2 selbst ein Bezirksname. Beispiel eines Gewinns: „Neukölln" →
„Kulturlabor Trial&Error", „Steglitz-Zehlendorf" → „Königliche Gartenakademie".

**Ergebnis der Prüfliste (v2-Stand):** 828 Ortsvorschläge auf **313 verschiedene
Orte**, dazu **36 Fälle „nur Treffpunkt bekannt"** als eigene, gekennzeichnete
Gruppe (der Ort ist unbekannt, ein Treffpunkt ist genannt — Fallback nur, wenn
gewünscht). 245 Vorschläge bringen eine Adresse mit, die bisher fehlte.
Beleg-Herkunft: Fließtext 200, Anbieter-Feld 73, Ort-Feld 40.
Dateien: `/opt/data/probe/llm_ort_pruefliste.md` und `.csv`.

**Konsequenz für die Umsetzung:** Die Stufe braucht **zwei** Felder —
`ort_ki` (Einrichtung) und `treffpunkt_ki` (Teilbereich/Haltestelle) — und darf
den Treffpunkt nie als Ortsnamen ausgeben. Fertige Liste: der gemeldete Fall
steht als „Botanischer Garten" mit dem Beleg „Anbieter: Botanischer Garten und
Botanisches Museum Berlin" und dem Treffpunkt „Besuchszentrum, Eingang
Königin-Luise-Platz" in der Prüfliste.

## Offen

- Prüfliste durchsehen und übernehmen (dein Schritt); erst danach eine
  Übernahme-Möglichkeit in der App — die Admin-Prüfliste ist noch nicht gebaut.
- Nebenfund: „Berlinweit" (79 Termine, familienportal) ist noch nicht in
  `_GENERISCH` (`app/orte.py`) — mit dieser Stufe mitnehmen.
- Rate-Limit/Scheduler: nur neue oder geänderte Termine prüfen, damit der
  tägliche Lauf nicht ~1300 LLM-Aufrufe macht (66 min für den Vollbestand).
- Anzeige: Kennzeichnung in der Terminkarte („Ort aus Beschreibungstext"),
  damit die Herkunft sichtbar bleibt (Provenienz-Regel des Projekts).
- „Gendarmenmarkt"-Fall: Vorschläge, die den Treffpunkt *beschreiben*, als
  eigenen Feldtyp führen (`treffpunkt_ki`) statt als Ortsnamen.

## Kein Bestandteil

- Keine Event-Detailseiten von Quellen scrapen, die nur Kalenderübersichten
  anbieten (Nutzerentscheidung 13.09.).
- Keine automatische Übernahme ohne Prüfung.
- Keine Änderung an Titel, Zeit oder Kategorien durch das Modell.
