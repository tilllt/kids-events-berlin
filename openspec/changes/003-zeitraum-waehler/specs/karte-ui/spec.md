# Karten-UI (MODIFIED)

## MODIFIED Requirements

### Requirement: Filter-Sidebar (Bezirk, Alter, Uhrzeit, Datum, Kostenlos)

- **Ablauf:** Sidebar mit: Bezirk (12 + „Berlinweit“), Altersband, Uhrzeit (Vormittag/Nachmittag/Abend/Ganztags), Zeitraum-Schnellwahl, Datum-von/bis, Kostenlos-Schalter.
- **Zeitraum-Schnellwahl:** Einzelwahl „Heute“ (Default beim Öffnen ohne URL-Parameter), „Morgen“, „Diese Woche“ (heute bis heute+6, 7 Tage ab heute), „Nächste Woche“ (heute+7 bis heute+13). Tagesgrenzen in Europe/Berlin; aktive Auswahl füllt und deaktiviert die Von-/Bis-Felder mit den berechneten Daten.
- **Benutzerdefiniert:** Manuelle Änderung an Von/Bis deaktiviert die Schnellwahl; URL-State `zeitraum=heute|morgen|diese-woche|naechste-woche`, bestehende `von`/`bis`-URLs bleiben gültig.
- **Verhalten:** Jede Filteränderung lädt Karte + Liste neu; aktive Filter sind sichtbar und einzeln entfernbar; Seitenzustand in der URL (teilbar).
- **UI-Regeln:** kompakt, dunkles Farbschema konsistent, keine funktionslosen Bedienelemente; „Filter zurücksetzen“ stellt die Schnellwahl auf „Heute“.

#### Scenario: Filterkombination anwenden und teilen
- **Akteure:** Nutzer.
- **Eingaben:** Bezirk=Pankow, Alter=Grundschule, Uhrzeit=Nachmittag.
- **Ergebnis:** Karte und Liste zeigen nur passende Events; URL enthält die Filter; beim Teilen/Neuladen bleiben sie erhalten.

#### Scenario: Seite öffnen, „was geht heute?“
- **Akteure:** Nutzer.
- **Eingaben:** Keine URL-Parameter.
- **Ergebnis:** Schnellwahl „Heute“ aktiv; Liste/Karte zeigen nur Events mit Startdatum heute (Berlin); ohne heutige Events erscheint der sichtbare Leerzustand mit Reset-Vorschlag — keine stille leere Karte.
