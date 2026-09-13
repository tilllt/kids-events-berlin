# Change 017 — Selbstheilung kaputter Scraper-Regeln (mit dem eingebauten LLM)

## Ziel

Wenn eine Quelle plötzlich keine Termine mehr liefert, weil sich ihre Seite
geändert hat, soll das System **selbst einen Reparaturvorschlag erzeugen** —
mit dem in den Einstellungen hinterlegten LLM (litellm/llama.cpp auf der KI-Box,
kein externer Dienst), und diesen Vorschlag **automatisch prüfen**. Übernommen
wird er nur mit Beleg und (Stufe 1) nach Bestätigung durch den Admin.

## Warum das hier geht und woanders nicht

Die Scraper sind **deklarative YAML-Regeln**, kein Programmcode. Eine
LLM-Reparatur ist deshalb eine **Datenänderung**, die man parsen, prüfen und
zurücknehmen kann. Das LLM schreibt nie Code, nie neue Module, nie Zugriffe auf
andere Domains — nur Feldselektoren, Zeitformate und optional eine neue
Listing-URL derselben Domain.

## Abgrenzung: geheilt wird nur Technisches

**Heilbar** (Struktur der Seite hat sich geändert):
- Selektoren treffen nicht mehr (0 Treffer statt N)
- Feldnamen/Pfade verschoben, Zeitformat geändert
- Listing-Seite umgezogen (404 auf die bekannte URL) → neue URL auf **derselben
  Domain** vorschlagen, geprüft am echten Abruf
- Detailseiten-Aufbau geändert (Beschreibung/Ort/Adresse nicht mehr gefunden)

**Nicht geheilt, sondern gemeldet** (das LLM darf hier nichts tun):
- Sperren, Captcha, Login, 403/429 — eine Umgehung wäre falsch und würde die
  Quelle beschädigen; hier wird die Quelle pausiert und der Admin informiert
- robots-Verbot, AGB-/Rechtsfragen, DSGVO
- Quelle abgeschaltet oder dauerhaft leer (dann: Vorschlag „Quelle deaktivieren")
- Fehler in eigener Pipeline/Code — dafür ist der Change nicht da

## Auslöser: ein Fehler, nicht eine Zahl

Grundsatz (Nutzer-Einwand vom 2026-09-13, übernommen): Geheilt wird nur, was
**nachweislich kaputt** ist. Eine kleinere Zahl ist kein Defekt — ein Kalender
kann saisonal oder nach dem Ende von Terminen legitim weniger anbieten. Die
erste Fassung dieses Changes nahm einen Einbruch der Trefferzahl als Auslöser;
das war falsch. Ein LLM-Lauf auf einer gesunden Quelle ist teuer und riskant:
Er würde Regeln ändern, die funktionieren, und das Gate könnte „die Seite hat
wirklich weniger Termine" nicht von „Selektor greift nur noch halb" unterscheiden.

**Heilung (LLM) läuft nur bei bewiesenen Fehlern:**

1. **Pflichtfeld bricht**: Zeilen werden gelesen, aber `start_iso` fehlt
   (Datumsformat geändert) → `n_fehler` steigt
2. **Fehlerquote** ≥ 30 % der gelesenen Zeilen oder ≥ 10 in Folge
3. **0 Treffer auf einer erreichbaren Seite, die früher Treffer lieferte**
   (Selektoren tot): HTTP 200, Inhalt vorhanden, unsere Selektoren finden nichts
4. **HTTP 404/410** auf der bekannten Listing-URL (umgezogen, gleiche Domain)

**Nur Meldung, keine Heilung:**

- Rückgang der Trefferzahl ohne Fehler → Meldung „Anomalie" an den Admin
  (verdächtig, aber kein Defekt; saisonal durchaus normal)
- Qualitäts-Rückgang einzelner Felder (z. B. Ort plötzlich bei 80 % leer)
- Sperren/Captcha/403/429, robots-Verbot, abgeschaltete Quelle

**Mittelweg für Verdachtsfälle:** Ein Rückgang löst die **Diagnose** aus (ohne
LLM, kostet nichts). Stellt die Diagnose fest, dass die Selektoren nicht mehr
passen — die Seite enthält weiterhin viele gleichartige Blöcke, unsere Selektoren
treffen 0 —, ist der Fehler bewiesen und die Reparatur startet. Sonst bleibt es
bei der Meldung. Damit entscheidet **der Befund**, nicht die Zahl.

**Manuell:** In der Admin-Oberfläche gibt es je Quelle „Regeln reparieren lassen"
— für alles, was die Automatik bewusst nicht selbst entscheidet.

Ein Heilungsversuch je Quelle und Tag.

## Diagnose (deterministisch, ohne LLM)

Ergebnis = strukturierter Befund, den das LLM als Fakten bekommt:
- HTTP-Status je Listing-Seite + Seitengröße
- Trefferzahl je Selektor (welcher greift, welcher nicht)
- Struktur-Signatur der Seite (Anzahl Knoten der bekannten Wiederhol-Blöcke)
  gegen den letzten gesunden Lauf
- Klassifikation: `selektoren_tot` | `url_umgezogen` | `gesperrt` | `leer`

## Der LLM-Auftrag (Prompt-Vertrag)

Eingabe (alles deterministisch vorbereitet):
- aktuelle Regel-YAML der Quelle
- die tatsächlich geholte HTML (auf die relevanten Bereiche gekürzt: Container
  der früheren Treffer + erkennbare Wiederhol-Blöcke)
- der Befund (Zahlen, nicht Vermutungen)
- erlaubte Feldnamen und Regel-Blöcke, Ausgabeformat (YAML), Randbedingungen:
  gleiche Domain, keine weiteren Quellen, keine Codeänderung

Ausgabe: `{neue_regeln: <yaml>, begruendung: <text>, konfidenz: 0..1}`

## Prüf-Gate (vollständig ohne LLM, hart)

Der Vorschlag wird verworfen, wenn **eine** dieser Prüfungen scheitert:

1. YAML parst und `validate_regeln_yaml` meldet keinen Fehler
2. Nur erlaubte Felder und Blöcke; Listing- und Detail-URLs bleiben auf der
   bisherigen Domain
3. **Probelauf live**: mit den neuen Regeln werden die Seiten wirklich geholt und
   geparst → mindestens N Termine mit gültigem Titel und Start
   (N = das Maximum aus „3" und 50 % der früheren Trefferzahl)
4. **Regressionsprobe gegen früheres HTML**: die neuen Regeln müssen auch auf
   den zwischengespeicherten Seiten früherer erfolgreicher Läufe mindestens
   80 % der damaligen Treffer finden — ein Selektor, der nur zufällig auf der
   heutigen Seite passt, fällt hier durch
5. Feld-Abdeckung: die vorher gefüllten Pflichtfelder (Titel, Start) sind auch
   mit den neuen Regeln gefüllt

**Voraussetzung dafür:** ein kleines **Seitenarchiv** — je Quelle wird die letzte
gesunde Listing-Seite aufgehoben (die Detailseiten liegen schon im
`detail_cache`). Ohne dieses Archiv wäre Prüfung 4 nicht möglich, und der
Vorschlag wäre nur an der heutigen Seite gemessen.

Ergebnis ist ein **Kandidat mit Belegzahlen** (gefundene Termine heute, Treffer
auf den alten Seiten, Abdeckung je Feld), nicht nur ein YAML-Block.

## Wirkung — Vorschlag, nicht Automatik (Stufe 1)

- Der Kandidat landet in der Tabelle `regel_vorschlaege` und erscheint in der
  Admin-Oberfläche bei der Quelle: **Regel-Differenz**, Begründung des Modells,
  Belegzahlen, Knöpfe „Übernehmen" / „Ablehnen"
- **Schattenlauf**: der Kandidat läuft bei jedem weiteren Lauf mit und zeigt,
  was er gefunden *hätte* — ohne den Bestand zu berühren. Damit steht vor der
  Übernahme fest, ob die Reparatur dauerhaft trägt
- Jede Regeländerung wird in `regel_historie` festgehalten (alt/neu, Grund,
  Zeit, Verursacher „LLM-Vorschlag" oder „Admin"); ein Klick stellt die letzte
  gesunde Fassung wieder her
- Nach der Übernahme wird der Lauf beobachtet: findet der nächste Lauf weniger
  als 50 % der Probelauf-Zahl, wird die Übernahme automatisch zurückgenommen
  und gemeldet

Stufe 1 ist damit „LLM schlägt vor, System prüft, Admin entscheidet". Nach
Abnahme kann Stufe 2 (Übernahme ohne Klick für Fälle, in denen alle Gates mit
großem Abstand grün sind) eingeschaltet werden.

## Sicherheitsnetze

- **Ein-Versuch-Regel**: höchstens ein Heilungsversuch je Quelle und Tag
- **Kontingent**: LLM-Aufrufe je Tag begrenzt (die KI-Box arbeitet seriell —
  Heilung läuft in derselben Warteschlange wie andere Jobs, nie parallel)
- **Kein Zugriff auf Code/Dateien**: das Modell bekommt Text, es schreibt Daten
- **Kennzeichnung**: jeder Vorschlag trägt „KI-Vorschlag, geprüft am <Datum>"
  und die Belegzahlen — nichts wird als Gewissheit dargestellt
- **Keine Nutzerdaten im Prompt**: nur öffentliche Quell-HTML und Regel-YAML

## Meldung an den Admin

Jeder Befund, ob geheilt oder nicht, geht sichtbar raus (kein stiller Fehler):
- geheilt + Vorschlag liegt vor → „Quelle X: Selektoren tot, Vorschlag geprüft
  (12 Termine heute, 9 von 11 auf Altdaten) — bitte bestätigen"
- nicht heilbar (Sperre/Captcha/abgeschaltet) → Quelle wird pausiert und gemeldet
- Gate durchgefallen → gemeldet mit Grund (z. B. „nur 1 Termin gefunden")

## Phasen

1. **Erkennung + Diagnose + Meldung** (ohne LLM): „Quelle X liefert seit 3 Läufen
   0 Termine; 4 von 6 Selektoren treffen nicht mehr" — sofort nützlich, voll
   testbar mit vorhandenen Fixtures
2. **LLM-Vorschlag + Gate** (Live-Probelauf + Regressionsprobe gegen alte Seiten)
3. **Admin-Oberfläche**: Vorschlag, Differenz, Beleg, Übernehmen/Ablehnen,
   Schattenlauf, Historie, Rücknahme
4. **Stufe 2**: automatische Übernahme nur bei klar belegten Fällen, mit
   automatischer Rücknahme bei Verschlechterung

## Offene Entscheidungen

- Wie viele Termine muss das Gate mindestens verlangen (Vorschlag: max(3, 50 %
  der früheren Trefferzahl))?
- Schattenlaufdauer vor der Übernahme (Vorschlag: ein regulärer Lauf)
- Ab wann Stufe 2 (automatische Übernahme) eingeschaltet wird
