"""Offline-Tests: SelectorAdapter gegen echte Fixtures (ZLB, Museumsportal)."""
from datetime import datetime, timedelta

import pytest

from app.adapters.selector_adapter import SelectorAdapter
from app.model import TZ_BERLIN
from app.quellen_defaults import (
    BRITZER_GARTEN_REGELN,
    GAERTEN_DER_WELT_REGELN,
    MUSEUMS_REGELN,
    SUEDGELAENDE_REGELN,
    TEMPELHOFER_FELD_REGELN,
    ZLB_REGELN,
)

# Gruen-Berlin-Parks: gleiches TYPO3-Plugin, unterschiedliche Karten-Templates.
GRUEN_BERLIN = [
    ("tempelhoferfeld", TEMPELHOFER_FELD_REGELN, "fixture_dir_tempelhoferfeld", "RIESENDRACHEN"),
    ("gaerten-der-welt", GAERTEN_DER_WELT_REGELN, "fixture_dir_gaerten_der_welt", None),
    ("britzer-garten", BRITZER_GARTEN_REGELN, "fixture_dir_britzer_garten", None),
    ("suedgelaende", SUEDGELAENDE_REGELN, "fixture_dir_suedgelaende", None),
]
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
    # Fixture-Snapshot hat feste Termine; Zeitpunkt an die Daten pinnen,
    # sonst kippt der Test, sobald "heute" ueber den Snapshot hinauswandert
    # (validate_event prueft HORIZONT_PAST gegen now()).
    jetzt = rows[0]["start"] - timedelta(hours=1)
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


def test_familienportal_regeln_validieren():
    from app.quellen_defaults import FAMILIENPORTAL_REGELN
    assert validate_regeln_yaml(FAMILIENPORTAL_REGELN, "familienportal") == []


def test_familienportal_listing_offline(fixture_dir_familienportal):
    from app.quellen_defaults import FAMILIENPORTAL_REGELN
    adapter = SelectorAdapter("familienportal", regel_yaml=FAMILIENPORTAL_REGELN)
    assert adapter.braucht_detail is True, "Detail-Regeln aktiv (Venue/Adresse)"
    html = (fixture_dir_familienportal / "listing.html").read_text(encoding="utf-8")
    rows = adapter.parse_listing(html)
    warn = adapter.drain_warnungen()
    assert len(rows) >= 8, f"nur {len(rows)} Events; warnungen: {warn}"
    r0 = rows[0]
    assert r0["titel"]
    assert r0["start"].year == 2026 and r0["start"].tzinfo is not None
    assert r0["start"].hour == 9  # 09:00 Uhr im Teaser
    assert r0["bezirk"] in ("Mitte", "Pankow", "Tempelhof-Schöneberg")
    # Events ohne Uhrzeit → ganztags
    ganztags = [r for r in rows if r.get("ganztags")]
    for r in ganztags:
        assert r["ende"].hour == 23
    adapter.close()


def test_familienportal_zu_event_bezirk(fixture_dir_familienportal):
    from app.quellen_defaults import FAMILIENPORTAL_REGELN
    adapter = SelectorAdapter("familienportal", regel_yaml=FAMILIENPORTAL_REGELN)
    html = (fixture_dir_familienportal / "listing.html").read_text(encoding="utf-8")
    rows = adapter.parse_listing(html)
    jetzt = datetime.now(TZ_BERLIN)
    ev = adapter.zu_event(rows[0], {}, jetzt)
    assert ev["quelle"] == "familienportal"
    assert ev["bezirk"] == "mitte"  # Label „Mitte“ → kanonischer Slug
    assert ev["start_local"].startswith("2026-09-07T09:00")
    # Quelle nennt nur den Bezirk → kein Ort, keine Geokodierung nötig
    assert ev["ort"] == "Ohne Angabe" and ev["lat"] is None
    adapter.close()


def test_listing_url_zeitraum_platzhalter():
    from app.quellen_defaults import FAMILIENPORTAL_REGELN
    adapter = SelectorAdapter("familienportal", regel_yaml=FAMILIENPORTAL_REGELN)
    # Seite 0: {seite} nicht in URL → pagination-Params None
    url0, params0 = adapter._listing_url_mit_zeitraum(0)
    assert "{start_ts}" not in url0 and "{ende_ts}" not in url0
    assert params0 is None
    # Seite 1 (zweite Seite): currentPage=2 (offset 1)
    url1, params1 = adapter._listing_url_mit_zeitraum(1)
    assert url1 == url0
    assert params1 == {"currentPage": "2"}
    # Timestamps: Ende > Start, Ende = heute+21 Tage
    import re
    m = re.search(r"filter_22_start%5D=(\d+)", url0)
    n = re.search(r"filter_22_end%5D=(\d+)", url0)
    assert m and n and int(n.group(1)) - int(m.group(1)) >= 20 * 86400
    adapter.close()


def test_museumsportal_serien_termine(fixture_dir_museumsportal):
    """Detailseite mit Serien-Terminliste („Datum und Uhrzeit“) → _termine."""
    from app.quellen_defaults import MUSEUMS_REGELN
    adapter = SelectorAdapter("museumsportal", regel_yaml=MUSEUMS_REGELN)
    html = (fixture_dir_museumsportal / "detail_serie.html").read_text(encoding="utf-8")
    d = adapter.parse_detail(html)
    termine = d.get("_termine") or []
    assert len(termine) >= 6, f"nur {len(termine)} Termine in der Serie"
    # Erster Termin: 6. September 2026, 11:00 (Berlin)
    t0 = termine[0]
    assert t0[0].year == 2026 and t0[0].month == 9 and t0[0].day == 6
    assert (t0[0].hour, t0[0].minute) == (11, 0)
    assert t0[0].tzinfo is not None
    # Chronologisch sortiert? (Quelle listet aufsteigend)
    starts = [t[0] for t in termine]
    assert starts == sorted(starts)
    # JSON-LD-Felder kommen weiterhin an
    assert d.get("ort"), "Ort aus JSON-LD fehlt"
    adapter.close()


def test_museumsportal_zu_events_serie_expandiert(fixture_dir_museumsportal):
    """Serien-Detail → ein Event pro Termin (nicht nur das JSON-LD-Event)."""
    from app.quellen_defaults import MUSEUMS_REGELN
    from app.validate import validate_event
    adapter = SelectorAdapter("museumsportal", regel_yaml=MUSEUMS_REGELN)
    # Listing-Row künstlich aus der Detailseite extrahieren ist nicht möglich —
    # nimm den ersten Row des Listing-Fixtures + Serien-Detail.
    lhtml = (fixture_dir_museumsportal / "listing.html").read_text(encoding="utf-8")
    rows = adapter.parse_listing(lhtml)
    dhtml = (fixture_dir_museumsportal / "detail_serie.html").read_text(encoding="utf-8")
    det = adapter.parse_detail(dhtml)
    # Fixture-Snapshot hat feste Termine; Zeitpunkt an die Daten pinnen,
    # sonst kippt der Test, sobald "heute" ueber den Snapshot hinauswandert
    # (validate_event prueft HORIZONT_PAST gegen now()).
    jetzt = rows[0]["start"] - timedelta(hours=1)
    evs = adapter.zu_events(rows[0], det, jetzt)
    termine = det["_termine"]
    # Row-Start in der Terminliste? Dann exakt len(termine) Events, sonst +1.
    row_start = rows[0]["start"].astimezone(TZ_BERLIN).replace(second=0, microsecond=0)
    erwartet = len(termine) if any(t[0] == row_start for t in termine) else len(termine) + 1
    assert len(evs) == erwartet, f"{len(evs)} != {erwartet}"
    ids = {e["id"] for e in evs}
    assert len(ids) == len(evs), "Serien-Events kollidieren in der ID"
    for e in evs:
        assert e["quelle"] == "museumsportal"
        assert e["start_local"]
        assert validate_event(e, jetzt) == [], validate_event(e, jetzt)
    adapter.close()


def test_familienportal_detail_css_felder(fixture_dir_familienportal):
    """Termin-Detailseite (kein JSON-LD): Venue + Adresse per CSS (#contact)."""
    from app.quellen_defaults import FAMILIENPORTAL_REGELN
    adapter = SelectorAdapter("familienportal", regel_yaml=FAMILIENPORTAL_REGELN)
    html = (fixture_dir_familienportal / "detail.html").read_text(encoding="utf-8")
    d = adapter.parse_detail(html)
    assert d.get("ort") == "Eisbahn im Sportforum Hohenschönhausen", d
    # Textknoten-Komma normalisiert: „…39, 13055 Berlin“ ohne Leerzeichen vor Komma
    assert d.get("adresse") == "Konrad-Wolf-Str. 39, 13055 Berlin", d
    adapter.close()


def test_familienportal_zu_events_mit_detail(fixture_dir_familienportal):
    """zu_events übernimmt Detail-Venue+Adresse in jedes Serien-Event."""
    from app.quellen_defaults import FAMILIENPORTAL_REGELN
    from app.validate import validate_event
    adapter = SelectorAdapter("familienportal", regel_yaml=FAMILIENPORTAL_REGELN)
    lhtml = (fixture_dir_familienportal / "listing.html").read_text(encoding="utf-8")
    rows = adapter.parse_listing(lhtml)
    assert rows, "Listing-Fixture ohne Rows"
    dhtml = (fixture_dir_familienportal / "detail.html").read_text(encoding="utf-8")
    det = adapter.parse_detail(dhtml)
    # Fixture-Snapshot hat feste Termine; Zeitpunkt an die Daten pinnen,
    # sonst kippt der Test, sobald "heute" ueber den Snapshot hinauswandert
    # (validate_event prueft HORIZONT_PAST gegen now()).
    jetzt = rows[0]["start"] - timedelta(hours=1)
    evs = adapter.zu_events(rows[0], det, jetzt)
    ev = evs[0]
    assert ev["ort"] == "Eisbahn im Sportforum Hohenschönhausen"
    assert "13055 Berlin" in (ev.get("adresse") or "")
    assert validate_event(ev, jetzt) == [], validate_event(ev, jetzt)
    adapter.close()


def test_familienportal_detail_beschreibung_sauber(fixture_dir_familienportal):
    """Beschreibung kommt aus dem Detail (.modul-text_bild .text) — die
    Listing-Vorschau ist vermüllt (dummyOption-Artefakte)."""
    from app.quellen_defaults import FAMILIENPORTAL_REGELN
    adapter = SelectorAdapter("familienportal", regel_yaml=FAMILIENPORTAL_REGELN)
    dhtml = (fixture_dir_familienportal / "detail.html").read_text(encoding="utf-8")
    d = adapter.parse_detail(dhtml)
    b = d.get("beschreibung_kurz") or ""
    assert "Landessportbund" in b, b[:120]
    assert "dummyOption" not in b and "Mehr" not in b, b[:120]
    # Listing liefert keine beschreibung_kurz mehr (kommt nur aus dem Detail)
    lhtml = (fixture_dir_familienportal / "listing.html").read_text(encoding="utf-8")
    rows = adapter.parse_listing(lhtml)
    for r in rows:
        assert not r.get("beschreibung_kurz"), "Listing-Beschreibung entfernt (vermüllt)"
    adapter.close()




# --------------------------------------------------------------------------
# Gruen Berlin: Park-Kalender (Tempelhofer Feld, Gärten der Welt,
# Britzer Garten, Natur-Park Südgelände) — gleiches Plugin, andere Templates
# --------------------------------------------------------------------------


@pytest.mark.parametrize("quelle,regeln,fixture_name,needle", GRUEN_BERLIN)
def test_gruen_berlin_regeln_validieren(quelle, regeln, fixture_name, needle):
    assert validate_regeln_yaml(regeln, quelle) == []


@pytest.mark.parametrize("quelle,regeln,fixture_name,needle", GRUEN_BERLIN)
def test_gruen_berlin_listing_offline(quelle, regeln, fixture_name, needle, request):
    fixture_dir = request.getfixturevalue(fixture_name)
    adapter = SelectorAdapter(quelle, regel_yaml=regeln)
    rows = adapter.parse_listing((fixture_dir / "listing.html").read_text(encoding="utf-8"))
    warn = adapter.drain_warnungen()
    assert len(rows) >= 3, f"nur {len(rows)} Events; warnungen: {warn}"
    for r in rows:
        assert r["titel"]
        # Das Datum kommt aus dem Detail-Pfad (JJJJ-MM-TT_HHMM) — immer mit Jahr.
        assert r["start"].year >= 2026, f"{r['titel']}: {r['start']}"
        assert r["start"].tzinfo is not None
        assert r["url"] and r["url"].startswith("http")
    if needle:
        treffer = [r for r in rows if needle in r["titel"].upper()]
        assert treffer, f"{needle} fehlt im Listing"
        d0 = treffer[0]
        assert d0["start"].hour == 11 and d0["ende"].hour == 20, (d0["start"], d0["ende"])
    adapter.close()


@pytest.mark.parametrize("quelle,regeln,fixture_name,needle", GRUEN_BERLIN)
def test_gruen_berlin_detail_ort(quelle, regeln, fixture_name, needle, request):
    fixture_dir = request.getfixturevalue(fixture_name)
    adapter = SelectorAdapter(quelle, regel_yaml=regeln)
    assert adapter.braucht_detail is True
    det = adapter.parse_detail((fixture_dir / "detail.html").read_text(encoding="utf-8"))
    # Ort kommt aus dem Seitentitel-Suffix ("... | <Park>") bzw. dem
    # Listing-Block (suedgelaende: "Ort: Natur Park Südgelände").
    assert det.get("ort") or det.get("beschreibung_kurz"), f"kein Ort/keine Beschreibung: {det}"
    if det.get("beschreibung_kurz"):
        assert len(det["beschreibung_kurz"]) > 20
    adapter.close()
