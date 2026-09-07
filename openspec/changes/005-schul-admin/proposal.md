# Change 005: Schul-Termine-Admin (Termin-CRUD, Schulen, Kategorien, Mail)

**Status:** In Arbeit (2026-09-07)
**Basis:** Change 002/003/004 (App deployed unter kinderkram.cia-spandau.de)

## Why

Die Schul-Dates-Erweiterung (Spec: doc.n0ne.de/S_E4lC8hSLGFrhgAtJYVmA) braucht
eine Pflege-Ebene für Termine, die nicht automatisch scrapebar sind
(Stufe B/C, Turnstile-geschützt, harte 403er): Tage der offenen Tür und
Infoabende werden von den Einrichtungen per E-Mail angefragt und müssen im
Admin-Backend gepflegt werden. Bisher kann das Admin nur Quellen/Regeln
verwalten — Termine sind reine Scrape-Artefakte ohne manuelle
Bearbeitungsmöglichkeit.

## What Changes

- **Admin-Route bleibt `/admin`** (existiert seit Change 002, offen ohne
  Auth — Schutz folgt später; weiterhin NICHT von der Startseite verlinkt).
- **Neue Admin-Tabs** (Navigationsleiste statt Abschnitte untereinander):
  `Quellen` (bestehend), `Termine`, `Schulen`, `Kategorien`.
- **Schulen-Tab = Arbeitsansicht für Schul-Termine (User-Spec 2026-09-07):**
  1. **Liste ALLER Schulen** inkl. Adresse (bsn, schulform, bezirk, ortsteil,
     strasse+hausnr, plz, email, website) — aus dem Schul-WFS-Stamm
     (dl-de-zero-2.0), nur allgemeinbildende (Grundschule/ISS/Gymnasium/
     Gemeinschaftsschule = 722 von 930), filterbar nach Bezirk/Schulform/Suche.
  2. **Automatisch erkannte Termine je Schule** sichtbar: Crawl-Funde
     (Strato-Crawl 2026-09-07, `strato_termin_out.json`) werden als
     `termine_manuell` mit status=`ungeprueft` + Herkunfts-Vermerk
     (`quelle_hinweis` = z. B. „automatisch erkannt: <url>“) importiert —
     der Admin prüft sie, statt selbst zu suchen.
  3. **Termin-CRUD je Schule**: editieren, löschen, manuell eintragen.
  4. **Freigabe**: Status `ungeprueft` → `bestaetigt` (erscheint öffentlich
     auf der Karte, quelle=`manuell`) und zurück.
  5. **Link zur Homepage bzw. Kalender-Seite der Schule** — öffnet beim
     Klick die Seite im neuen Tab, damit der Admin den Termin gegenprüfen
     kann (website aus dem Stamm; erkannte Termine tragen ihre Fund-URL).
  6. **E-Mail-Fenster an die zentrale Kontaktadresse** der Schule mit
     Standardtext zur Nachfrage nach TdoT/Infoabenden (mail_vorlage.txt);
     Versand über SMTP-Einstellungen, `angefragt_am` wird gesetzt.
- **Termine-Tab:** Liste aller Termine, filterbar/gegruppert **pro
  Einrichtung** (Schule); CRUD: Termin anlegen, bearbeiten, löschen.
  Bestehende Scrape-Termine (Quellen) sind sichtbar, aber nur manuell
  gepflegte Schul-Termine editierbar (Scrape-Termine werden vom nächsten
  Lauf überschrieben — keine sinnlosen Edit-Felder).
- **Kategorien-Tab:** Terminkategorien verwalten (z. B. „Tag der offenen
  Tür“, „Infoabend“, „Schnuppertag“, „Ferienangebot“) — Name + Farbe.
- **Mail-Versand aus dem Backend:** pro Schule (Einrichtung) eine
  vorformulierte Termin-Anfrage-Mail versenden; Status der Anfrage wird an
  der Schule vermerkt (angefragt_am). SMTP-Zugang über Einstellungen
  (Admin-Einstellungen-Tab) oder Env.
- **Frontend-Volltextsuche:** Suchfeld in der Karten-UI; nutzt den
  vorhandenen `q`-Parameter von `/api/events` (titel/beschreibung/ort).
- **Datenmodell:** neue Tabelle `schulen` (Einrichtungs-Stamm),
  `termin_kategorien`, `termine_manuell` (manuell gepflegte Schul-Termine,
  Bezug auf schule + kategorie, Vertrauens-Status) — bestehende
  `events`-Tabelle bleibt unangetastet (Scrape-Bestand).

## Import (einmalig + wiederholbar)

- `schulen` aus dem WFS-Stamm befüllen (`/opt/data/schulen_all.json`,
  dl-de-zero-2.0): Import-Skript `app/import_schulen.py` (oder CLI-Kommando)
  — upsert, idempotent; nur allgemeinbildende Schularten.
- Crawl-Termine als `ungeprueft` importieren (Skript/CLI): dedupliziert,
  nur zukünftige Termine mit Datum + Fund-URL; Quelle-Hinweis dokumentiert
  die Herkunft, damit der Admin die Seite öffnen und gegenprüfen kann.
- Die Rohdaten (`strato_termin_out.json`) sind Text-Funde mit Rauschen
  (News-Zeitstempel, JS-Artefakte, veraltete Jahre) — der Import filtert
  konservativ: nur parsebares Datum, nur zukünftig, nur wenn ein
  Datums-Kontext im Text steht; Rest bleibt für die Mail-Anfrage (Stufe C).

## Redesign-Entscheidungen (User 2026-09-07) — ARCHITEKTUR-KORREKTUR

Schulen SIND Quellen — das bisherige UI-Modell (eigener Schulen-Tab neben
Quellen) ist verworfen. Ziel: EINE GUI für ALLE Terminarten.

1. **Quellen = Obertab mit Unter-Tabs:** je Quelle ein Unter-Tab
   (familienportal, jup-berlin, museumsportal, zlb, **schulen** = manuelle
   Quelle) + „Übersicht". Jede Quelle zeigt ihre Termine; Schulen zusätzlich
   Adresse/Kontakt/Mail-Anfrage.
2. **Termine-Tab: ALLE Termine editierbar** (auch gescrapte). Wer einen
   gescrapten Termin editiert, markiert ihn als **manuell gepflegt** — der
   Scrape-Lauf überschreibt ihn danach nicht mehr (Edit gewinnt,
   User-Entscheidung).
3. **Keine Kategorien — Tags** (für ALLE Terminarten): Template-Liste wird
   mitgeliefert (Schul-Tags: Tag der offenen Tür, Infoabend, Schnuppertag,
   Anmeldezeitraum; übliche Veranstaltungsarten: Lesung, Konzert, … — vom
   Agenten recherchiert), erweiterbar um eigene Tags **in den Einstellungen**.
   Events tragen Tags in der bestehenden `kategorien`-JSON-Spalte; die
   `termin_kategorien`-Tabelle wird zu `tags` (id/name/farbe/sort).
4. **Mail-Vorlage:** braucht Betreffszeile UND **Reply-To**; im
   Settings-Backend liegt ein Beispieltext (der GET liefert den Default,
   wenn nichts gespeichert ist — aktuell leer = kein Beispiel sichtbar).

## Specs-Delta

- `ADDED specs/schul-admin/spec.md` — Admin-Termin-/Schul-/Kategorien-
  Verwaltung + Mail-Versand.
- `MODIFIED specs/karte-ui/spec.md` — Req (Filter-Sidebar) um Volltextsuche
  ergänzt.

## Offene Punkte (vor Umsetzung klären)

1. Mail-Versand: SMTP-Zugang als **Admin-Einstellung** (Host/Port/User/Pass/
   From) — User trägt später einen echten Zugang ein; Versand-Endpunkt
   schlägt ohne konfigurierten SMTP sauber fehl (sichtbar, nicht still).
2. Vertrauens-Status der manuellen Termine: `ungeprueft` (Default, nach
   Mail-Anfrage) und `bestaetigt` (Antwort der Schule).
3. **Geklärt (2026-09-07):** Manuelle Termine erscheinen in der öffentlichen
   Karte NUR mit Status `bestaetigt`; `ungeprueft` bleibt Admin-intern.

## Downgrade

Downgrade = Stand Change 004: Admin zeigt wieder nur Quellen/Regeln/Läufe;
Schul-Tabellen und Mail-Funktion werden entfernt; Frontend-Suchfeld weg.
