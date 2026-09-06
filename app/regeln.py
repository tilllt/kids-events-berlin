"""Stufe-2-Regeln: YAML-Schema, Validierung, Selektor-Prüfung (parsel).

Regeln sind Daten (DB-Tabelle regeln) und werden über die Admin-GUI/API
bearbeitet. Diese Datei ist die einzige Quelle der Wahrheit für das Schema;
die Selector-Engine (Phase 3) nutzt dieselben Regeln zur Laufzeit.

Schema (Beispiel):
    listing:
      url: "https://www.zlb.de/veranstaltungen"
      pagination: {param: "page"}            # oder next_css
      item_css: "article.eventTeaser"
      felder:
        titel: {css: ".eventTeaser__title span:not(.eventTeaser__superHeadline)"}
        url:   {css: "a", attr: "href"}
        start: {css: ".eventTeaser__date", format: "%d.%m.%Y"}
        ort:   {css: ".eventTeaser__location"}
    detail:                                  # optional
      jsonld: true
      felder:
        adresse: {jsonld: "$.location.address"}
    filter_kinder: {regex: ["kind", "familie"]}   # optional
"""
from __future__ import annotations

import re

import parsel
import yaml

# Feld-Mapping: welche Event-Felder die Regeln liefern dürfen (listing).
_LISTING_FELDER = {
    "titel": "Pflicht",
    "url": "optional",        # Detail-URL; fehlt → kein Detail-Fetch
    "start": "Pflicht",       # Datum (format) oder JSON-LD
    "ende": "optional",
    "zeit": "optional",       # Uhrzeit separat (format "%H:%M")
    "ort": "optional",
    "bezirk": "optional",     # Quelle nennt den Bezirk direkt (Label)
    "beschreibung_kurz": "optional",
    "adresse": "optional",
}
_DETAIL_FELDER = {
    "beschreibung_kurz", "adresse", "ort", "lat", "lon",
}

_TOP_KEYS = {"listing", "detail", "filter_kinder", "name", "robots", "quelle"}
_LISTING_KEYS = {"url", "pagination", "item_css", "felder", "horizont_tage", "detail_url_skip"}
_PAGINATION_KEYS = {"param", "next_css", "offset"}
_FILTER_KEYS = {"regex"}


def _typfehler(msg: str) -> list[str]:
    return [msg]


def _css_ok(selektor: str) -> str | None:
    """None = ok, sonst Fehlermeldung (deutsch)."""
    if not isinstance(selektor, str) or not selektor.strip():
        return "Selektor ist leer."
    try:
        parsel.Selector(text="<html><body></body></html>").css(selektor)
    except Exception as e:  # SelectorSyntaxError u. a.
        return f"CSS-Selektor ungültig: {e}"
    return None


# Feld-Optionen: css (parsel) und/oder jsonld (extruct-Pfad).
# Zusätzlich: xpath (relativ zum Item statt css), attr (href aus css-Element),
# regex (erster Treffer im Text), format (strptime auf extrahiertem Text),
# join (Textliste verbinden).
_FELD_OPTIONEN = {"css", "jsonld", "xpath", "attr", "regex", "format", "join"}


def _pruefe_feld(feldname: str, regeln: dict, pfad: str) -> list[str]:
    fehler: list[str] = []
    if not isinstance(regeln, dict):
        return [f"{pfad}: Feld-Regel für '{feldname}' ist kein Mapping."]
    keys = set(regeln)
    quelle = [k for k in ("css", "jsonld", "xpath") if k in keys]
    if len(quelle) > 1:
        fehler.append(f"{pfad}/{feldname}: 'css', 'jsonld' und 'xpath' schließen sich aus.")
    if not quelle:
        fehler.append(f"{pfad}/{feldname}: braucht 'css', 'jsonld' oder 'xpath'.")
    if "xpath" in regeln:
        try:
            parsel.Selector(text="<a><b/></a>").xpath(str(regeln["xpath"]))
        except Exception as e:
            fehler.append(f"{pfad}/{feldname}.xpath: XPath ungültig: {e}")
    if "css" in regeln:
        msg = _css_ok(str(regeln["css"]))
        if msg:
            fehler.append(f"{pfad}/{feldname}.css: {msg}")
    if "jsonld" in regeln:
        p = regeln["jsonld"]
        if not isinstance(p, str) or not p.startswith("$"):
            fehler.append(f"{pfad}/{feldname}.jsonld: Pfad muss mit '$' beginnen (z. B. $.name).")
    if "regex" in regeln:
        rx = regeln["regex"]
        try:
            re.compile(rx)
        except re.error as e:
            fehler.append(f"{pfad}/{feldname}.regex: ungültig ({e}).")
    if "format" in regeln and not any(k in regeln for k in ("css", "jsonld", "regex")):
        fehler.append(f"{pfad}/{feldname}: 'format' ist nur mit 'css'/'regex'/'jsonld' sinnvoll.")
    if "attr" in regeln and "css" not in regeln:
        fehler.append(f"{pfad}/{feldname}: 'attr' ist nur mit 'css' sinnvoll.")
    unbekannt = keys - _FELD_OPTIONEN
    for u in sorted(unbekannt):
        fehler.append(f"{pfad}/{feldname}: unbekannte Option '{u}' (erlaubt: {', '.join(sorted(_FELD_OPTIONEN))}).")
    return fehler


def validate_regeln_yaml(yaml_text: str, quelle: str | None = None) -> list[str]:
    """→ Fehlerliste (leer = gültig). Meldungen deutsch mit Pfad-Angabe."""
    if not yaml_text or not yaml_text.strip():
        return ["Regeln sind leer."]
    try:
        doc = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        return [f"YAML-Syntaxfehler: {e}"]
    if not isinstance(doc, dict):
        return ["Regeln müssen ein Mapping (dict) sein."]
    fehler: list[str] = []

    unbekannt = set(doc) - _TOP_KEYS
    for u in sorted(unbekannt):
        fehler.append(f"Unbekannter Abschnitt '{u}' (erlaubt: {', '.join(sorted(_TOP_KEYS))}).")

    if quelle and doc.get("quelle") and doc["quelle"] != quelle:
        fehler.append(f"'quelle' in den Regeln ({doc['quelle']}) passt nicht zur Quelle {quelle}.")

    listing = doc.get("listing")
    if not isinstance(listing, dict):
        fehler.append("Abschnitt 'listing' fehlt (url, item_css, felder).")
        return fehler
    lkeys = set(listing)
    unbek_l = lkeys - _LISTING_KEYS
    for u in sorted(unbek_l):
        fehler.append(f"listing: unbekannte Option '{u}' (erlaubt: {', '.join(sorted(_LISTING_KEYS))}).")
    if not listing.get("url"):
        fehler.append("listing.url fehlt (Start-URL der Liste).")
    if not listing.get("item_css"):
        fehler.append("listing.item_css fehlt (CSS-Selektor für ein Event-Element).")
    else:
        msg = _css_ok(str(listing["item_css"]))
        if msg:
            fehler.append(f"listing.item_css: {msg}")
    pag = listing.get("pagination") or {}
    if pag:
        if not isinstance(pag, dict):
            fehler.append("listing.pagination muss ein Mapping sein (param oder next_css).")
        else:
            for u in sorted(set(pag) - _PAGINATION_KEYS):
                fehler.append(f"listing.pagination: unbekannte Option '{u}'.")
    felder = listing.get("felder")
    if not isinstance(felder, dict) or not felder:
        fehler.append("listing.felder fehlt (mindestens 'titel' und 'start').")
        return fehler
    fkeys = set(felder)
    unbek_f = fkeys - set(_LISTING_FELDER)
    for u in sorted(unbek_f):
        fehler.append(f"listing.felder: unbekanntes Feld '{u}' "
                      f"(erlaubt: {', '.join(sorted(_LISTING_FELDER))}).")
    for pflicht in ("titel", "start"):
        if pflicht not in fkeys:
            fehler.append(f"listing.felder: Pflichtfeld '{pflicht}' fehlt.")
    for fname, regel in felder.items():
        fehler.extend(_pruefe_feld(fname, regel, "listing.felder"))

    detail = doc.get("detail")
    if detail is not None:
        if not isinstance(detail, dict):
            fehler.append("detail muss ein Mapping sein.")
        else:
            if "jsonld" in detail and not isinstance(detail["jsonld"], bool):
                fehler.append("detail.jsonld muss true/false sein.")
            dfelder = detail.get("felder")
            if dfelder is not None:
                if not isinstance(dfelder, dict):
                    fehler.append("detail.felder muss ein Mapping sein.")
                else:
                    for u in sorted(set(dfelder) - _DETAIL_FELDER):
                        fehler.append(f"detail.felder: unbekanntes Feld '{u}' "
                                      f"(erlaubt: {', '.join(sorted(_DETAIL_FELDER))}).")
                    for fname, regel in dfelder.items():
                        fehler.extend(_pruefe_feld(fname, regel, "detail.felder"))

    fk = doc.get("filter_kinder")
    if fk is not None:
        if not isinstance(fk, dict) or not isinstance(fk.get("regex"), list):
            fehler.append("filter_kinder.regex muss eine Liste sein (z. B. [\"kind\", \"familie\"]).")
    return fehler
