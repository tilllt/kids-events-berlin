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
