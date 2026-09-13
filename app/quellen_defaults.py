"""Standard-Regeln für verifizierte Quellen (Change 002).

Diese Regeln sind die Dev-/CI-Wahrheit (Fixture-Tests laden sie) und dienen
als Ausgangspunkt, wenn eine Quelle über die Admin-GUI angelegt wird. Im
Betrieb liegen die Regeln in der DB (regeln-Tabelle) — hier nichts ändern,
ohne Fixture-Test anzufassen (tests/test_selector_adapter.py).
"""
from __future__ import annotations

ZLB_REGELN = """quelle: zlb
# Fester Ort: die ZLB veranstaltet im Haus (Breite Str. 32-34, 10178 Berlin).
standard: {ort: "Zentral- und Landesbibliothek Berlin (ZLB)", bezirk: "mitte"}
robots: "erlaubt; Events-Pfade nicht disallowed (2026-09-06)"
listing:
  url: https://www.zlb.de/veranstaltungen
  item_css: article.eventTeaser
  felder:
    titel: {css: ".eventTeaser__title > span:not(.eventTeaser__superHeadline)"}
    url: {css: "a", attr: "href"}
    start: {css: ".visuallyhidden span", regex: "([0-9]{2}[.][0-9]{2}[.][0-9]{4})", format: "%d.%m.%Y"}
    zeit: {css: "span.meta:nth-of-type(1) .meta__text", regex: "([0-9]{1,2}:[0-9]{2}) Uhr", format: "%H:%M"}
    ende: {css: "span.meta:nth-of-type(1) .meta__text", regex: "[0-9]{1,2}:[0-9]{2} Uhr - ([0-9]{1,2}:[0-9]{2})", format: "%H:%M"}
    ort: {css: "span.meta:nth-of-type(2) .meta__text"}
"""

MUSEUMS_REGELN = """quelle: museumsportal
robots: "Content-Signal search=yes, use=reference; AI-Crawler geblockt (2026-09-06)"
listing:
  url: https://www.museumsportal-berlin.de/de/veranstaltungen
  item_css: "mp-card.mp-card-program"
  # 3-Wochen-Horizont: Serien-Termine aus Detailseiten (und Listing-Rows)
  # werden nur bis heute+21 Tage übernommen (User-Vorgabe).
  horizont_tage: 21
  felder:
    titel: {css: "h2"}
    url: {xpath: "ancestor::hylo-router-link[1]/@href"}
    start: {css: ".mp-card-content__info time", regex: "([0-9]{2}[.][0-9]{2}[.][0-9]{2})", format: "%d.%m.%y"}
    zeit: {css: ".mp-card-content__info time", regex: "([0-9]{1,2}:[0-9]{2})", format: "%H:%M"}
    ort: {css: ".mp-card-location"}
    beschreibung_kurz: {css: "h3"}
detail:
  jsonld: true
  felder:
    beschreibung_kurz: {jsonld: "$.description"}
    ort: {jsonld: "$.location.name"}
    adresse: {jsonld: "$.location.address"}
  # Serien: Detailseite listet weitere Termine („Datum und Uhrzeit“) als
  # li mit zwei Spans (deutsches Datum + Uhrzeit) → ein Event pro Termin
  # (3-Wochen-Horizont via listing.horizont_tage unten analog familienportal).
  termine_css: "hylo-list-more ul li"
"""

FAMILIENPORTAL_REGELN = """quelle: familienportal
robots: "erlaubt; nur /suche/ disallowed; www-Host blockt — ohne www (2026-09-06)"
listing:
  # Zeitraum über kesearch-Timestamps (filter_22_start/end, Unix-Sekunden);
  # nur Kategorie „Kinder & Jugendliche“ (filter_19). {seite} ab Seite 2.
  url: "https://familienportal.berlin.de/veranstaltungen/s?tx_kesearch_pi1%5Bfilter_19%5D%5B%5D=KinderJugendliche&tx_kesearch_pi1%5Bfilter_22_start%5D={start_ts}&tx_kesearch_pi1%5Bfilter_22_end%5D={ende_ts}"
  horizont_tage: 21
  pagination: {param: "currentPage", offset: 1}
  item_css: "article.modul-teaser"
  felder:
    titel: {css: "h3.title"}
    url: {css: "a.more", attr: "href", regex: '(/veranstaltungen-3/termin/[^?#]+)'}
    start: {css: ".teaser__meta .text--meta", regex: "([0-9]{2}[.][0-9]{2}[.][0-9]{4})", format: "%d.%m.%Y"}
    zeit: {css: '.teaser__meta .text--meta', regex: '([0-9]{1,2}:[0-9]{2})\\s*Uhr', format: '%H:%M'}
    bezirk: {css: '.teaser__meta .text--meta', regex: '\\|\\s*([^|]+)$'}
  detail_url_skip: calendarize
detail:
  # Venue + Adresse stehen erst auf der Termin-Detailseite (kein JSON-LD):
  # „#contact li.name“ = Einrichtung, „li.address.loc“ = Straße, PLZ Berlin.
  # Beschreibung ebenso aus dem Detail — die Listing-Vorschau ist vermüllt
  # (Titel-Dreifach, „Veranstaltungen dummyOption(wichtig!) …“-Template-Reste).
  felder:
    ort: {css: '#contact li.name'}
    adresse: {css: '#contact li.address.loc'}
    beschreibung_kurz: {css: '.modul-text_bild .text'}
"""

# ---------------------------------------------------------------------------
# Gruen Berlin: Veranstaltungskalender der Park-Websites
# ---------------------------------------------------------------------------
# Alle vier Seiten nutzen dasselbe TYPO3-Plugin (tx_events2), aber
# UNTERSCHIEDLICHE Karten-Templates. Gemeinsam ist nur:
#   * div.eventWrapper als Karte
#   * h3.media-heading a als Titel + Detail-Link
#   * der Detail-Pfad .../detail/JJJJ-MM-TT_HHMM/slug/ — das einzige Feld mit
#     vollstaendigem Datum UND Uhrzeit. suedgelaende listet "Samstag, 12.09."
#     (ohne Jahr!), gaertenderwelt teils Datumsbereiche ("01.09.2026 -
#     01.11.2026") und Zeiten mit Punkt ("12.30 Uhr") — deshalb kommt `start`
#     bei allen vieren aus der URL (Format %Y-%m-%d_%H%M).
# Zeitraum-Parameter des JavaScriptSearch-Formulars werden serverseitig
# ignoriert (geprueft 2026-09-12: TT.MM.JJJJ wie ISO, Antwort unveraendert),
# ein Feed existiert nicht -> Stufe 2, Liste zeigt nur die naechsten Tage.
# `kostenlos` wird NICHT gemappt: isAccessibleForFree steht im JSON-LD auf
# "False", obwohl z. B. das Festival der Riesendrachen Eintritt frei ist.
_GRUEN_BERLIN_VORLAGE = """quelle: __QUELLE__
# Fester Ort: der Kalender GEHÖRT zu einem Ort („Gärten der Welt IST der Ort").
# Gilt nur, wenn die Quelle nichts Eigenes liefert.
__STANDARD__
robots: "erlaubt (robots.txt: Allow: *, geprueft 2026-09-12)"
listing:
  url: __URL__
  item_css: "div.eventWrapper"
  horizont_tage: 21
  felder:
    titel: {css: "h3.media-heading a"}
    url: {css: "h3.media-heading a", attr: "href"}
    start: {css: "h3.media-heading a", attr: "href", regex: "detail/([0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4})", format: "%Y-%m-%d_%H%M"}
    ende: {css: "div.time", regex: "__ENDE_REGEX__", format: "__ENDE_FORMAT__"}
detail:
  # Event-JSON-LD vorhanden (name/description/startDate/endDate), aber kein
  # Veranstaltungsort — der steht im Seitentitel-Suffix ("... | <Park>").
  jsonld: true
  felder:
    beschreibung_kurz: {jsonld: "$.description"}
    # Element selbst, bei verschachtelten Kindern nur den Text davor ("Ort:").
"""


def _gruen_berlin_regeln(quelle: str, url: str, ende_regex: str, ende_format: str,
                         ort: str, bezirk: str) -> str:
    return (_GRUEN_BERLIN_VORLAGE
            .replace("__QUELLE__", quelle)
            .replace("__URL__", url)
            .replace("__ENDE_REGEX__", ende_regex)
            .replace("__ENDE_FORMAT__", ende_format)
            .replace("__STANDARD__", f'standard: {{ort: "{ort}", bezirk: "{bezirk}"}}')
            )


TEMPELHOFER_FELD_REGELN = _gruen_berlin_regeln(
    "tempelhoferfeld",
    "https://www.tempelhoferfeld.de/entdecken-erleben/veranstaltungskalender/",
    "[0-9]{1,2}:[0-9]{2}[^0-9]{1,4}([0-9]{1,2}:[0-9]{2})", "%H:%M",
    "Tempelhofer Feld", "tempelhof-schoeneberg")

GAERTEN_DER_WELT_REGELN = _gruen_berlin_regeln(
    "gaerten-der-welt",
    "https://www.gaertenderwelt.de/events/veranstaltungen/",
    "[-][ ]*([0-9]{1,2}[.][0-9]{2})[ ]*Uhr", "%H.%M",
    "Gärten der Welt", "marzahn-hellersdorf")

BRITZER_GARTEN_REGELN = _gruen_berlin_regeln(
    "britzer-garten",
    "https://www.britzergarten.de/events/eventkalender/",
    "[-][ ]*([0-9]{1,2})[ ]*Uhr", "%H",
    "Britzer Garten", "neukoelln")

SUEDGELAENDE_REGELN = _gruen_berlin_regeln(
    "suedgelaende",
    "https://www.natur-park-suedgelaende.de/entdecken-erleben/kalender/",
    "[0-9]{1,2}:[0-9]{2}[^0-9]{1,4}([0-9]{1,2}:[0-9]{2})", "%H:%M",
    "Natur Park Südgelände", "tempelhof-schoeneberg")

# Kinderkulturkalender (LKJ Berlin e.V., Drupal 10) — eigene Datenbank,
# KEIN jup!-Duplikat (Audit-Befund 2026-09-12 widerlegt; 87 der 91 im
# 21-Tage-Fenster überlappenden Angebote kommen über familienportal).
KINDERKULTURKALENDER_REGELN = """quelle: kinderkulturkalender
robots: "erlaubt: /startseite + /angebot/; disallowed nur /admin,/core,/profiles,/search,/user/* (2026-09-12)"
listing:
  url: https://www.kinderkulturkalender-berlin.de/startseite
  # Drupal-Views-Masonry: 186 Karten, keine Pagination; 3-Wochen-Horizont
  # über horizont_tage (Projekt-Vorgabe „nur 3 Wochen in die Zukunft").
  horizont_tage: 21
  item_css: "div.masonry-item.views-row article.node--type-offer"
  felder:
    titel: {css: "h3 .field--name-title"}
    url: {css: "a.offer__wrapper", attr: "href"}
    # Das Listing trägt nur Datum (teils als Spanne, ohne Uhrzeit) — die
    # echten Termine stehen im Detail (termine_css + termine_autoritativ).
    start: {css: "div.field--name-field-event-date", regex: "([0-9]{2}[.][0-9]{2}[.][0-9]{4})", format: "%d.%m.%Y"}
detail:
  felder:
    # Haupttext der Angebotsseite (das nackte .field--name-body matcht auch
    # Kopf-/Fußzeilen-Blöcke und liefert „Kontrast Instagram …“ davor).
    beschreibung_kurz: {css: "article.node--type-offer.node--view-mode-full .field--name-body"}
    ort: {css: ".field--name-field-location .field--name-title"}
    # Adresse in zwei Stufen: zuerst der verknüpfte Orts-Knoten (Straße+PLZ),
    # sonst der AddToCalendar-Link (Parameter location=, plus-kodiert) — 
    # ~40 % der Angebote haben keinen Orts-Knoten, aber IMMER den Link.
    # Länderzusatz „Deutschland" muss weg, sonst findet die amtliche
    # Adress-Geokodierung (WFS) nichts.
    adresse:
      - {css: ".field--name-field-location .field--name-field-address", regex: '^(.*?)(?:[,\\s]*Deutschland)?$'}
      - {css: '.addtocal-menu a[href*="calendar.google"]', attr: "href", urldecode: true, regex: '[?&]location=((?:[^,&\\d]*?\\d{1,4}[^,&\\d]*?)\\s+\\d{5}\\s+Berlin)'}
  # Termine als Textitems „20.09.26, 11:00 - 20.09.26, 12:30" (Form B im
  # Selector-Adapter) — Liste ist autoritativ, kein Phantom-Row-Event.
  # `> .field__item` ist Pflicht: ohne das Kind-Selektor matcht auch der
  # Spannen-Wrapper („13.09.2026 - 21.11.2026") ohne Uhrzeit.
  termine_css: "div.dates .field__items > .field__item"
  termine_autoritativ: true
"""

DEFAULT_REGELN: dict[str, str] = {
    "zlb": ZLB_REGELN,
    "museumsportal": MUSEUMS_REGELN,
    "familienportal": FAMILIENPORTAL_REGELN,
    "tempelhoferfeld": TEMPELHOFER_FELD_REGELN,
    "gaerten-der-welt": GAERTEN_DER_WELT_REGELN,
    "britzer-garten": BRITZER_GARTEN_REGELN,
    "suedgelaende": SUEDGELAENDE_REGELN,
    "kinderkulturkalender": KINDERKULTURKALENDER_REGELN,
}
