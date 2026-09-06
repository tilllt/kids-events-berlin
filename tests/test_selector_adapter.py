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
    assert adapter.braucht_detail is False
    html = (fixture_dir_zlb / "listing.html").read_text(encoding="utf-8")
    rows = adapter.parse_listing(html)
    warn = adapter.drain_warnungen()
    assert len(rows) >= 5, f"nur {len(rows)} Events; warnungen: {warn}"
    r0 = rows[0]
    assert r0["titel"]
    assert r0["start"].year == 2026
    assert r0["start"].tzinfo is not None
    assert r0["url"] and r0["url"].startswith("http")
    assert r0["ort"] and r0["ort"] != "Ohne Angabe"
    # Erstes Event (Sonntagsprogramm AGB): 11:00–12:00 Uhr
    assert r0["start"].hour == 11 and r0["ende"].hour == 12
    assert r0["ende"] > r0["start"]
    # Kein Event ohne Ort (ZLB listet den Ort im Teaser)
    ohne = [r["titel"] for r in rows if not r.get("ort")]
    assert not ohne, f"Events ohne Ort: {ohne}"
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
    assert adapter.braucht_detail is True  # Detail-JSON-LD wird angereichert
    html = (fixture_dir_museumsportal / "listing.html").read_text(encoding="utf-8")
    rows = adapter.parse_listing(html)
    warn = adapter.drain_warnungen()
    assert len(rows) >= 5, f"nur {len(rows)} Events; warnungen: {warn}"
    r0 = rows[0]
    assert r0["titel"]
    assert r0["start"].year == 2026
    assert r0["ort"]
    assert r0["start"].hour >= 0
    # Event-Link aus dem umschließenden hylo-router-link (statt nur Listing-URL)
    assert r0["url"] and r0["url"].startswith("https://www.museumsportal-berlin.de/de/veranstaltungen/")
    assert r0["slug"] == r0["url"].rstrip("/").rsplit("/", 1)[-1]
    adapter.close()


def test_museumsportal_detail_jsonld_offline(fixture_dir_museumsportal):
    """Detailseite: Event-JSON-LD liefert Beschreibung, Ort und Adresse."""
    adapter = SelectorAdapter("museumsportal", regel_yaml=MUSEUMS_REGELN)
    html = (fixture_dir_museumsportal / "detail.html").read_text(encoding="utf-8")
    d = adapter.parse_detail(html)
    assert d.get("beschreibung_kurz"), "description fehlt im JSON-LD-Detail"
    assert d.get("ort") == "Botanischer Garten und Botanisches Museum Berlin"
    adapter.close()


def test_museumsportal_zu_event(fixture_dir_museumsportal):
    """source_url zeigt auf die Event-Seite (nicht die Listing-Übersicht)."""
    from app.validate import validate_event
    adapter = SelectorAdapter("museumsportal", regel_yaml=MUSEUMS_REGELN)
    html = (fixture_dir_museumsportal / "listing.html").read_text(encoding="utf-8")
    rows = adapter.parse_listing(html)
    jetzt = datetime.now(TZ_BERLIN)
    slugs = {r["slug"] for r in rows}
    assert len(slugs) == len(rows), "Slug-Kollision: Events würden sich überschreiben"
    ev0 = adapter.zu_event(rows[0], {}, jetzt)
    assert ev0["source_url"].startswith("https://www.museumsportal-berlin.de/de/veranstaltungen/")
    assert ev0["id"] and ev0["titel"]
    assert validate_event(ev0, jetzt) == [], validate_event(ev0, jetzt)
    # mit Detail-JSON-LD: Adresse fließt ins Event
    dhtml = (fixture_dir_museumsportal / "detail.html").read_text(encoding="utf-8")
    ev1 = adapter.zu_event(rows[0], adapter.parse_detail(dhtml), jetzt)
    assert ev1.get("adresse"), "Adresse aus Detail-JSON-LD fehlt"
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
