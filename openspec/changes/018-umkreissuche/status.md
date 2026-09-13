# Change 018 — „In meiner Nähe": Umkreissuche und Kalender-Abo

## Ziel

Termine in einem wählbaren Umkreis um einen selbst gewählten Punkt anzeigen —
mit allen Filtern, die auf der Startseite schon gelten — und dieselbe Auswahl
als **Kalender-Abo** (iCal) anbieten.

## Ausgangslage (gemessen, 2026-09-13)

- **2281 von 3178** Terminen haben eine Kartenposition; **897 nicht**.
  Ohne Position kann kein Termin im Umkreis erscheinen — das muss die
  Oberfläche **sagen**, nicht verschweigen.
- Größte Blöcke ohne Position: Polizei-Kalender 85 von 85, Industriekultur 117
  von 271, Familienportal 58 von 931, Umweltkalender 322 von 1401.
- Die Startseite filtert bereits über URL-Parameter (Bezirk, Ort, Alter,
  Uhrzeit, Wann) und die Karte (Leaflet) ist vorhanden.

## Eingabe des Mittelpunkts — drei Wege

1. **Standort des Geräts** (`navigator.geolocation`), nur auf ausdrücklichen
   Klick, nie automatisch. Die Position bleibt im Browser.
2. **Postleitzahl oder Ortsteil** — Auflösung in dieser Reihenfolge:
   - **aus dem eigenen Bestand**: Mittelpunkt aller bekannten Adressen mit
     dieser PLZ (sofort, kostenlos, deterministisch, keine Fremdabhängigkeit)
   - sonst über den amtlichen Geokodierer/Nominatim (gecacht, 1 Anfrage/s)
3. **Punkt auf der Karte** — Klick setzt den Mittelpunkt.

Der Mittelpunkt ist jederzeit sichtbar und verschiebbar; ein zweiter Klick
setzt ihn neu.

## Umkreis und Anzeige

- Auswahl **1 / 2 / 5 / 10 km**, Standard 2 km; Kreis auf der Karte sichtbar.
- Sortierung nach Entfernung (Luftlinie, Haversine), Entfernung je Termin
  ausgewiesen („1,2 km").
- Kopfzeile mit ehrlicher Zahl: „**87 Termine im Umkreis von 2 km** — 312
  Termine haben keine Position und können hier nicht erscheinen."
- **Alle bestehenden Filter bleiben aktiv** und kombinieren sich: Bezirk, Ort,
  Alter, Uhrzeit, Wann. Der Umkreis ist ein weiterer Parameter, keine eigene
  Ansicht — die Filterleiste bleibt dieselbe, inklusive Markierung und ✕.

## Technik (klein, weil alles Nötige da ist)

- `/api/events` bekommt `lat`, `lon`, `umkreis_km`.
- Serverseitig: erst **Bounding-Box** (Index auf `lat`/`lon` nutzbar), dann
  exakte Distanz in Python — bei ~3200 Terminen unmessbar schnell, keine
  Geo-Erweiterung in SQLite nötig.
- Es gilt `lat`/`lon` des Termins; Termine ohne Position werden gezählt und
  getrennt ausgewiesen.
- Frontend: Radius-Auswahl, „Mein Standort"-Knopf, Karte-Klick, Kreis und
  Entfernungsangabe.

## Datenschutz beim Standort

Der Standort ist die sensibelste Angabe in dieser App:

- **Keine Speicherung** in der Datenbank, keine Verknüpfung mit Sitzungen,
  keine Weitergabe.
- Kein automatisches Auslesen — nur auf Klick.
- **Offener Punkt:** Der Webserver protokolliert Anfrage-URLs. Ein Radius über
  GET-Parameter würde Koordinaten in Logs schreiben (Standortverlauf!). Drei
  Möglichkeiten, bitte entscheiden:
  a) Umkreissuche per **POST** (Body wird nicht protokolliert) — Nachteil: der
     Link ist nicht teilbar
  b) GET lassen, aber Mittelpunkt vor dem Senden auf **~1 km runden** —
     teilbar, ungenau, Logs enthalten nur grobe Punkte
  c) GET unverändert — einfachste Lösung, Logs enthalten genaue Koordinaten

Empfehlung: **(b)** für die Weitergabe-Fähigkeit plus **(a)** beim Gerätestandort
(der ist persönlich; der per PLZ/Karte gewählte Punkt ist es nicht).

## Kalender-Abo — Aufwand: klein

**Nein, das ist kein großer Aufwand.** Der Grund: Die Filter existieren bereits
als URL-Parameter, und iCal ist reiner Text. Der Abo-Endpunkt ist praktisch die
vorhandene Filter-URL mit anderer Ausgabe:

`/api/kalender.ics?bezirk=mitte&alter=6-10&lat=52.52&lon=13.40&umkreis_km=2`

Was dafür nötig ist:

- iCal-Erzeugung (RFC 5545) als Text — keine Bibliothek zwingend nötig
- **stabile UID je Termin** (die Kennung aus Quelle + Quell-ID existiert schon),
  sonst legt der Kalender bei jeder Aktualisierung Duplikate an
- **Zeitzonen**: lokale Zeit mit `TZID=Europe/Berlin` plus VTIMEZONE-Block
  (nicht als UTC — sonst verschieben sich Termine in Clients ohne
  Zeitzonentabelle)
- **ganztägige Termine** als `VALUE=DATE` ohne Uhrzeit
- Zeitraum begrenzen (Standard: heute + 8 Wochen) — sonst zieht ein Abo
  tausende Termine
- `SEQUENCE` hochzählen, wenn sich ein Termin ändert, und „letzte
  Aktualisierung" im Feed mitführen

**Der eigentliche Vorteil:** Kalender-Clients **holen selbst** (pull) — kein
Versand, keine Zustellung, keine Speicherung, kein Login. Es gibt keinen
Newsletter-Betrieb, der laufen muss. Wer das Abo nicht mehr will, löscht es im
Kalender.

Grenzen, ehrlich benannt:

- Aktualisierung bestimmt der **Client** (meist 1–24 h) — kein Sofort-Push
- Erinnerungen/Wecker sind Sache des Kalenders, nicht der App
- Termine ohne Position erscheinen auch im Abo nicht, wenn ein Umkreis gesetzt
  ist (ohne Umkreis: alle, wie in der Liste)

## Stufen

1. **Umkreissuche** (API-Filter + Radius-Auswahl + PLZ/Karte + Kreis + ehrliche
   Zahl der Termine ohne Position)
2. **Kalender-Abo** (`/api/kalender.ics` mit denselben Parametern, plus
   „Als Kalender abonnieren"-Knopf neben den Filtern, der die aktuelle Auswahl
   in den Abo-Link übersetzt)
3. Später optional: gespeicherte Auswahlen mit Namen (braucht Speicherung —
   dann bewusst **ohne** Gerätestandort), Erinnerungs-Vorlauf, Bilder im Feed

## Offene Entscheidungen

- Datenschutz-Variante a/b/c für die Koordinaten in den Logs (Empfehlung: b + a
  beim Gerätestandort)
- Standard-Umkreis (Vorschlag 2 km) und Standard-Zeitraum im Abo (Vorschlag
  8 Wochen)
- Soll das Abo-Termine ohne Position **weglassen** (Vorschlag: ja, wenn ein
  Umkreis gewählt ist — sonst wäre der Kalender voller Termine außerhalb)
