# Change 015 — Ortsfilter auf der Startseite

**Status:** gebaut, getestet, deployt (2026-09-13). Nutzer-Vorgabe: „wir brauchen
auf der Startseite einen weiteren Termin Filter mit Ort (also Veranstaltungsort),
muss sich den anderen Filtern anpassen. Wenn Bezirk gesetzt ist dürfen nur die
Orte in den gewählten Bezirken sichtbar sein."

## Why

Bisher ließ sich nur nach Bezirk, Alter, Uhrzeit, Zeitraum und kostenlos filtern.
Wer gezielt eine Einrichtung sucht (Bibliothek, Museum, Jugendzentrum), musste
durch die ganze Liste. Der Bezirk ist dafür zu grob — und ein reiner Freitext-
Treffer unterscheidet nicht zwischen Ort und Beschreibung.

## Umsetzung

- **Auswahlliste passt sich den übrigen Filtern an:** neuer Endpunkt
  `GET /api/orte` liefert Veranstaltungsorte mit Anzahl, gefiltert nach Bezirk,
  Alter, Uhrzeit, Zeitraum, „nur kostenlos“ und Volltextsuche. Ist ein Bezirk
  gewählt, enthält die Liste **nur Orte in diesen Bezirken**.
- **Der Ortsfilter selbst zählt in der Liste nicht mit.** Sonst würde eine
  getroffene Auswahl ihre eigene Optionsliste auf einen Eintrag zusammen-
  streichen und man käme nicht mehr heraus. Die Auswahl bleibt sichtbar und
  abwählbar; fällt ein gewählter Ort durch eine Änderung heraus, wird er
  entfernt **und der Hinweis nennt ihn** (kein stiller Zustand).
- **Datenbank:** `Store.list_orte(filters)` zählt die Orte im Filterkontext
  (nach Häufigkeit, dann alphabetisch); `query_events` kennt einen
  `orte`-Filter.
- **Trenner der Ortsnamen ist `|`, nicht `,`:** Ortsnamen enthalten selbst
  Kommas („Wildunger Weg, 13587 Berlin“), ein Komma-Split würde sie zerschneiden.
- **Frontend:** neuer Filter-Tab „Ort“ (zwischen Bezirk und Alter) mit Suchfeld
  und scrollbarer Liste (`max-height: 300px`), da es hunderte Orte gibt.
  Die Liste wird bei jeder Filteränderung nachgeladen; neu aufgebaut wird sie nur,
  wenn sich die Optionen wirklich geändert haben (sonst springt die Scrollposition
  bei jedem Klick). Der Ortsfilter steht auch in der URL (`?ort=A|B`).

## Verifiziert

- Tests: **264 grün** (3 neu): Ortsliste folgt dem Bezirksfilter, Ortsfilter
  selbst zählt nicht mit, Frontend-Regression (Tab, Panel, Request-Parameter).
- Live: siehe Messung unten.

## Offen

1. Ortsnamen sind Quelltexte, keine normalisierten Einrichtungen — dieselbe
   Bibliothek kann als „Humboldt-Bibliothek“ und „Humboldt Bibliothek“ auftauchen.
   Ein Zusammenfassen wäre ein eigener Schritt (Venue-Normalisierung).
2. Orte ohne Angabe („Ohne Angabe“) sind bewusst kein Filterwert.
