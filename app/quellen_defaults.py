"""Standard-Regeln für verifizierte Quellen (Change 002).

Diese Regeln sind die Dev-/CI-Wahrheit (Fixture-Tests laden sie) und dienen
als Ausgangspunkt, wenn eine Quelle über die Admin-GUI angelegt wird. Im
Betrieb liegen die Regeln in der DB (regeln-Tabelle) — hier nichts ändern,
ohne Fixture-Test anzufassen (tests/test_selector_adapter.py).
"""
from __future__ import annotations

ZLB_REGELN = """quelle: zlb
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
    url: {css: "a.more", attr: "href"}
    start: {css: ".teaser__meta .text--meta", regex: "([0-9]{2}[.][0-9]{2}[.][0-9]{4})", format: "%d.%m.%Y"}
    zeit: {css: '.teaser__meta .text--meta', regex: '([0-9]{1,2}:[0-9]{2})\\s*Uhr', format: '%H:%M'}
    bezirk: {css: '.teaser__meta .text--meta', regex: '\\|\\s*([^|]+)$'}
    beschreibung_kurz: {css: '.inner .text', regex: '(.*?)\\s*Mehr\\s*$'}
"""

DEFAULT_REGELN: dict[str, str] = {
    "zlb": ZLB_REGELN,
    "museumsportal": MUSEUMS_REGELN,
    "familienportal": FAMILIENPORTAL_REGELN,
}
