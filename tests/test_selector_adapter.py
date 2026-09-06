"""Offline-Tests: SelectorAdapter gegen echte Fixtures (ZLB, Museumsportal)."""
from datetime import datetime

import pytest

from app.adapters.selector_adapter import SelectorAdapter
from app.model import TZ_BERLIN
from app.regeln import validate_regeln_yaml

ZLB_REGELN = """quelle: zlb
robots: "erlaubt; Events-Pfade nicht disallowed (2026-09-06)"
listing:
  url: https://www.zlb.de/veranstaltungen
  pagination: {param: "tx_news_pi1%5B%40widget_0%5D%5BcurrentPage%5D"}
  item_css: article.eventTeaser
  felder:
    titel: {css: ".eventTeaser__title > span:not(.eventTeaser__superHeadline)"}
    url: {css: "a", attr: "href"}
    start: {css: ".eventTeaser__meta", regex: "(\\\\d{2}\\\\.\\\\d{2}\\\\.\\\\d{4})", format: "%d.%m.%Y"}
    zeit: {css: ".eventTeaser__meta", regex: "(\\\\d{1,2}:\\\\d{2}) Uhr", format: "%H:%M"}
    ort: {css: ".eventTeaser__location"}
detail:
  jsonld: true
  felder:
    beschreibung_kurz: {jsonld: "$.description"}
    ort: {jsonld: "$.location.name"}
    adresse: {jsonld: "$.location.address.streetAddress"}
"""


def test_zlb_regeln_validieren():
    assert validate_regeln_yaml(ZLB_REGELN, "zlb") == []


def test_zlb_listing_offline(fixture_dir_zlb):
    adapter = SelectorAdapter("zlb", regel_yaml=ZLB_REGELN)
    html = (fixture_dir_zlb / "listing.html").read_text(encoding="utf-8")
    rows = adapter.parse_listing(html)
    warn = adapter.drain_warnungen()
    assert len(rows) >= 5, f"nur {len(rows)} Events; warnungen: {warn}"
    r0 = rows[0]
    assert r0["titel"]
    assert r0["start"].year == 2026
    assert r0["start"].tzinfo is not None
    # ZLB-Teaser haben Uhrzeiten → nicht ganztags, sofern Zeit-Regel zog
    assert r0["url"] and r0["url"].startswith("http")
    # Datum/Zeit konsistent
    assert 8 <= r0["start"].hour <= 20 or r0["start"].hour == 0
    adapter.close()


def test_zlb_zu_event(fixture_dir_zlb):
    adapter = SelectorAdapter("zlb", regel_yaml=ZLB_REGELN)
    html = (fixture_dir_zlb / "listing.html").read_text(encoding="utf-8")
    rows = adapter.parse_listing(html)
    jetzt = datetime.now(TZ_BERLIN)
    ev = adapter.zu_event(rows[0], {}, jetzt)
    assert ev["quelle"] == "zlb"
    assert ev["id"] and ev["source_url"].startswith("https://www.zlb.de")
    assert ev["start_local"].startswith("2026-09")
    adapter.close()


def test_regeln_kaputt_wirft():
    with pytest.raises(ValueError):
        SelectorAdapter("zlb", regel_yaml="listing:\n  item_css: x\n")
