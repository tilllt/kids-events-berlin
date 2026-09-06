"""Offline-Tests: SelectorAdapter gegen echte Fixtures (ZLB, Museumsportal)."""
from datetime import datetime

import pytest

from app.adapters.selector_adapter import SelectorAdapter
from app.model import TZ_BERLIN
from app.quellen_defaults import MUSEUMS_REGELN, ZLB_REGELN
from app.regeln import validate_regeln_yaml


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
    assert r0["url"] and r0["url"].startswith("http")
    assert 8 <= r0["start"].hour <= 20
    assert r0["ende"] is None or r0["ende"] > r0["start"]
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


def test_museumsportal_regeln_validieren():
    assert validate_regeln_yaml(MUSEUMS_REGELN, "museumsportal") == []


def test_museumsportal_listing_offline(fixture_dir_museumsportal):
    adapter = SelectorAdapter("museumsportal", regel_yaml=MUSEUMS_REGELN)
    html = (fixture_dir_museumsportal / "listing.html").read_text(encoding="utf-8")
    rows = adapter.parse_listing(html)
    warn = adapter.drain_warnungen()
    assert len(rows) >= 5, f"nur {len(rows)} Events; warnungen: {warn}"
    r0 = rows[0]
    assert r0["titel"]
    assert r0["start"].year == 2026
    assert r0["ort"]
    assert r0["start"].hour >= 0
    # Keine Detail-URL in der Liste → slug = Hash, url leer
    assert not r0["url"]
    adapter.close()


def test_ganztags_fixture():
    """Reines Datum (ohne Uhrzeit-Feld) → ganztags 00:00–23:59."""
    regeln = """quelle: test
listing:
  url: https://example.org/
  item_css: .ev
  felder:
    titel: {css: ".t"}
    start: {css: ".d", format: "%d.%m.%Y"}
"""
    adapter = SelectorAdapter("test", regel_yaml=regeln)
    html = '<div class="ev"><span class="t">Tag der offenen Tür</span><span class="d">12.09.2026</span></div>'
    rows = adapter.parse_listing(html)
    assert len(rows) == 1
    r = rows[0]
    assert r["ganztags"] is True
    assert r["start"].hour == 0
    assert r["ende"].hour == 23 and r["ende"].minute == 59
    adapter.close()
