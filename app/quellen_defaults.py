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
    adresse: {jsonld: "$.location.address.streetAddress"}
"""

DEFAULT_REGELN: dict[str, str] = {
    "zlb": ZLB_REGELN,
    "museumsportal": MUSEUMS_REGELN,
}
