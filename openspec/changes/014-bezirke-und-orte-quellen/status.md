# Change 014 — Bezirke und Orte aus den Kalenderquellen vollständig übernehmen

**Status:** gebaut, getestet, deployt (2026-09-13). Auslöser war der Nutzerhinweis
„Industriekultur gibt Orte an, du übernimmst sie aber nicht" — dahinter steckten
zwei getrennte Fehler.

## Why

Zwei Lücken in der Quellen-Auswertung, die still zu leeren Feldern führten:

1. **Bezirksnamen mit Umlaut/Transliteration fielen durch.** Quellen nennen den
   Bezirk mal als Anzeigename („Neukölln", „Treptow-Köpenick"), mal ASCII-slugig
   („neukoelln", „treptow-koepenick"). Die Zuordnung kannte nur die Anzeigenamen,
   also blieb `bezirk` bei genau diesen Bezirken `null` — ohne Warnung, sichtbar
   erst beim Blick in die Datenbank.
2. **Orte blieben ungenutzt.** `industriekultur-berlin` nennt den Ort pro Karte
   („Am Flugplatz Gatow 33", „Industriesalon Schöneweide"), die Regel las ihn
   nicht aus. `ort` fiel damit auf „Ohne Angabe", die Karte hatte keine Position.

## Umsetzung

- `_LABEL_ZU_SLUG` in `app/adapters/selector_adapter.py` löst **beide**
  Schreibweisen auf: kanonische Slugs *und* Anzeigenamen (jeweils
  kleingeschrieben). Damit ist die Invariante „ein erkannter Bezirksname landet
  immer als kanonischer Slug im Event" erzwungen, statt für jeden Einzelfall
  eine Ausnahme zu pflegen.
- Regel für `industriekultur-berlin`: `adresse` **und** `ort` aus dem Kartenfeld
  `…detail.is-place`, `zeit` aus `…detail.is-time`, `beschreibung_kurz` aus dem
  Formatfeld statt aus dem ganzen Textblock (der enthielt Uhrzeit und Ort doppelt).
- Tests: `test_bezirk_slug_und_label_landen_im_event` (Slug und Label → Slug) und
  `test_listing_bezirk_ascii_slug_endet_im_event` (Ende-zu-Ende über Listing →
  Event).

## Verifiziert (produktiv)

- Vorher/nachher in der Produktiv-DB (`/data/events.db`), Quelle
  `industriekultur-berlin`: 135 Events, **69 mit Bezirk**, 18 mit Adresse,
  0 mit echtem Ort.
- Nach dem Regel-Ausbau: siehe Messung unten (Ort/Adresse je Termin, Koordinaten
  auf der Karte).

## Offen

1. **Detailseiten als Adress-Quelle:** 117 der 135 Karten nennen in der Übersicht
   keinen Ort; er steht nur auf `/festival/veranstaltung/…`. Ein rein CSS-basierter
   Detail-Abruf ist eingebaut — bewusst **ohne** `jsonld`, weil der JSON-LD-Pfad
   (extruct) die früheren Läufe blockiert hat.
2. **Beschreibungs-Update:** die Produktiv-DB trug bei diesen Terminen noch den
   alten, zu breiten Beschreibungstext — ob der Store geänderte Beschreibungen
   in bestehenden Zeilen überschreibt, ist zu prüfen (sonst bleibt Alt-Text
   stehen, obwohl die Regeln sauber sind).
