"""Offline-Tests: SelectorAdapter gegen echte Fixtures (ZLB, Museumsportal)."""
from datetime import datetime, timedelta

import pytest

from app.adapters.selector_adapter import SelectorAdapter, _parse_termin_text
from app.model import TZ_BERLIN
from app.quellen_defaults import (
    BRITZER_GARTEN_REGELN,
    GAERTEN_DER_WELT_REGELN,
    KINDERKULTURKALENDER_REGELN,
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


def test_bezirk_slug_und_label_landen_im_event():
    """Quellen nennen den Bezirk mal ASCII-slugig („neukoelln", „treptow-koepenick"),
    mal als Label („Neukölln"). Beides muss auf den kanonischen Slug führen —
    sonst fällt genau die Umlaut-Gruppe stumm durch (bezirk=null)."""
    from app.adapters.selector_adapter import _LABEL_ZU_SLUG

    for roh, erwartet in [("neukoelln", "neukoelln"), ("treptow-koepenick", "treptow-koepenick"),
                          ("tempelhof-schoeneberg", "tempelhof-schoeneberg"),
                          ("Neukölln", "neukoelln"), ("Treptow-Köpenick", "treptow-koepenick"),
                          ("SPANDAU", "spandau"), ("Berlinweit", "berlinweit")]:
        assert _LABEL_ZU_SLUG.get(roh.strip().lower()) == erwartet, roh


def test_listing_bezirk_ascii_slug_endet_im_event():
    """Ende-zu-Ende: Bezirks-Slug aus dem Listing muss im Event ankommen."""
    regeln = """
quelle: test-bezirk-slug
name: Testquelle Bezirk
robots: 'erlaubt: / (Test)'
listing:
  url: https://example.org/kalender
  item_css: 'div.ev'
  felder:
    titel: {css: 'h3'}
    start: {css: '.d', format: '%d.%m.%Y'}
    bezirk: {css: '.b'}
"""
    html = ('<div class="ev"><h3>Testfest</h3><div class="d">01.10.2026</div>'
            '<div class="b">treptow-koepenick</div></div>')
    adapter = SelectorAdapter("test-bezirk-slug", regel_yaml=regeln)
    rows = adapter.parse_listing(html)
    ev = adapter.zu_event(rows[0], {}, datetime.now(TZ_BERLIN))
    assert ev["bezirk"] == "treptow-koepenick"
    adapter.close()


def test_url_regex_verwirft_tote_links():
    """Familienportal liefert pro Karte mal einen sprechenden /termin/-Link, mal
    einen toten calendarize/cHash-Link, der auf die Liste umleitet. Über ein
    Muster auf dem url-Feld darf nur der brauchbare Link übrig bleiben
    (Nutzerhinweis: „Quelle linked auf eine leere Seite")."""
    regeln = """
quelle: test-url-regex
name: Testquelle URL
robots: 'erlaubt: / (Test)'
listing:
  url: https://example.org/veranstaltungen
  item_css: 'article.t'
  felder:
    titel: {css: 'h3'}
    start: {css: '.d', format: '%d.%m.%Y'}
    url: {css: 'a.more', attr: 'href', regex: '(/veranstaltungen-3/termin/[^?#]+)'}
"""
    html = ('<article class="t"><h3>Gut</h3><div class="d">01.10.2026</div>'
            '<a class="more" href="/veranstaltungen-3/termin/robotik-20261001-7">mehr</a></article>'
            '<article class="t"><h3>Tod</h3><div class="d">02.10.2026</div>'
            '<a class="more" href="/veranstaltungen-3?tx_calendarize_calendar%5Baction%5D=detail&cHash=abc">mehr</a></article>')
    adapter = SelectorAdapter("test-url-regex", regel_yaml=regeln)
    rows = {r["titel"]: r for r in adapter.parse_listing(html)}
    assert rows["Gut"]["url"] == "https://example.org/veranstaltungen-3/termin/robotik-20261001-7"
    assert not rows["Tod"].get("url"), "toter calendarize-Link muss verworfen werden"
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


# --- Kinderkulturkalender (LKJ Berlin, Drupal 10; Change 007) --------------

def test_kinderkulturkalender_regeln_validieren():
    assert validate_regeln_yaml(KINDERKULTURKALENDER_REGELN,
                                "kinderkulturkalender") == []


def test_kkk_listing_offline(fixture_dir_kinderkulturkalender):
    adapter = SelectorAdapter("kinderkulturkalender",
                              regel_yaml=KINDERKULTURKALENDER_REGELN)
    assert adapter.braucht_detail is True
    assert adapter.horizont_tage == 21
    rows = adapter.parse_listing(
        (fixture_dir_kinderkulturkalender / "listing.html").read_text(encoding="utf-8"))
    assert adapter.drain_warnungen() == []
    assert len(rows) > 100, f"nur {len(rows)} Karten"
    for r in rows:
        assert r["titel"]
        assert r["url"] and r["url"].startswith(
            "https://www.kinderkulturkalender-berlin.de/angebot/")
        assert r["start"].tzinfo is not None
        assert r["start"].year >= 2025
    # Genau ein Alt-Eintrag der Quelle trägt ein veraltetes Datum
    # („Skulptur mit Ton“: 15.09.2025 - 23.08.2027, Quelldaten, kein
    # Parser-Fehler); alles andere ist 2026+ und wird vom Fenster-Filter
    # der Pipeline auf die nächsten 3 Wochen begrenzt.
    assert sum(1 for r in rows if r["start"].year >= 2026) >= 180
    # Das Listing trägt nur ein Datum ohne Uhrzeit → ganztags; Ort/Zeit
    # kommen erst aus der Detailseite.
    assert all(r["ganztags"] for r in rows)
    needle = [r for r in rows if "Herbstshow bei CABUWAZI" in r["titel"]]
    assert needle, "Anlass-Event fehlt im Listing"
    # Die Quelle führt die Show als mehrere Knoten (…-show-1, …-show-1-0, …-show-2)
    # mit 19.09. bzw. 20.09.2026; der 20.09. ist der in der Detailseite
    # hinterlegte Termin (11:00–12:30).
    starts = {(r["start"].month, r["start"].day) for r in needle}
    assert (9, 20) in starts, starts
    adapter.close()


def test_kkk_detail_ort_adresse_beschreibung(fixture_dir_kinderkulturkalender):
    adapter = SelectorAdapter("kinderkulturkalender",
                              regel_yaml=KINDERKULTURKALENDER_REGELN)
    det = adapter.parse_detail(
        (fixture_dir_kinderkulturkalender / "detail.html").read_text(encoding="utf-8"))
    assert adapter.drain_warnungen() == []  # kein JSON-LD-Rauschen ohne jsonld-Regel
    assert det["ort"] == "Amerika-Gedenkbibliothek"
    # Länderzusatz entfernt + PLZ erhalten (für die amtliche Geokodierung)
    assert det["adresse"] == "Blücherplatz 1 10961 Berlin"
    assert "<" not in (det["beschreibung_kurz"] or "")
    assert not det["beschreibung_kurz"].startswith("Kontrast")
    adapter.close()


def test_kkk_detail_termine_textform(fixture_dir_kinderkulturkalender):
    adapter = SelectorAdapter("kinderkulturkalender",
                              regel_yaml=KINDERKULTURKALENDER_REGELN)
    det = adapter.parse_detail(
        (fixture_dir_kinderkulturkalender / "detail_serie.html").read_text(encoding="utf-8"))
    termine = det.get("_termine") or []
    assert len(termine) == 4, termine
    start, ende, ganztags = termine[0]
    assert (start.month, start.day, start.hour, start.minute) == (9, 13, 16, 0)
    assert (ende.hour, ende.minute) == (16, 45)
    assert ganztags is False
    # Der Spannen-Wrapper („13.09.2026 - 21.11.2026“) darf NICHT als
    # zusätzlicher ganztägiger Termin durchrutschen.
    assert not any(t[2] for t in termine)
    adapter.close()


def test_kkk_zu_events_autoritativ(fixture_dir_kinderkulturkalender):
    """termine_autoritativ: kein Phantom-Row-Event neben den echten Terminen."""
    adapter = SelectorAdapter("kinderkulturkalender",
                              regel_yaml=KINDERKULTURKALENDER_REGELN)
    rows = adapter.parse_listing(
        (fixture_dir_kinderkulturkalender / "listing.html").read_text(encoding="utf-8"))
    row = [r for r in rows if r["slug"] == "chaos-der-gefuehle-relaxed-performance"][0]
    det = adapter.parse_detail(
        (fixture_dir_kinderkulturkalender / "detail_serie.html").read_text(encoding="utf-8"))
    jetzt = datetime(2026, 9, 12, 12, 0, tzinfo=TZ_BERLIN)
    evs = adapter.zu_events(row, det, jetzt)
    assert len(evs) == 4
    assert all(e["ganztags"] is False for e in evs)
    assert all(e["ort"] == "THEATER AN DER PARKAUE" for e in evs)
    assert all(e["adresse"] == "Parkaue 29 10367 Berlin" for e in evs)
    ids = {e["id"] for e in evs}
    assert len(ids) == 4  # eindeutige Event-IDs je Termin
    adapter.close()


@pytest.mark.parametrize("text,erwartet", [
    ("20.09.26, 11:00 - 20.09.26, 12:30", (2026, 9, 20, 11, 0, 12, 30, False)),
    ("11.10.2026, 10:00 - 11.10.2026, 16:00", (2026, 10, 11, 10, 0, 16, 0, False)),
    ("13.09.26, 16:00", (2026, 9, 13, 16, 0, None, None, False)),
    ("20.09.26", (2026, 9, 20, 0, 0, 23, 59, True)),
])
def test_parse_termin_text(text, erwartet):
    start, ende, ganztags = _parse_termin_text(text)
    jahr, monat, tag, sh, sm, eh, em, ganz = erwartet
    assert (start.year, start.month, start.day, start.hour, start.minute) == (jahr, monat, tag, sh, sm)
    assert start.tzinfo is not None
    assert ganztags is ganz
    if eh is None:
        assert ende is None
    else:
        assert (ende.hour, ende.minute) == (eh, em)


def test_parse_termin_text_ohne_datum():
    """Elemente ohne Datum (Buttons, Kalender-Links) werden verworfen."""
    assert _parse_termin_text("Zum Kalender hinzufügen Google Yahoo!") is None
    assert _parse_termin_text("") is None


def test_kkk_detail_adresse_fallback_kalenderlink(fixture_dir_kinderkulturkalender):
    """Ohne Orts-Knoten kommt die Adresse aus dem AddToCalendar-Link der Seite."""
    html = (fixture_dir_kinderkulturkalender / "detail_ohne_ort.html").read_text(encoding="utf-8")
    assert "field--name-field-location" not in html  # Beweis: Orts-Knoten fehlt
    adapter = SelectorAdapter("kinderkulturkalender",
                              regel_yaml=KINDERKULTURKALENDER_REGELN)
    det = adapter.parse_detail(html)
    assert det.get("adresse") == "Columbiadamm 84 10965 Berlin", det
    # Die Quelle nennt hier keinen Veranstaltungsnamen → Feld bleibt leer
    # (Fallback „Ohne Angabe" in der Pipeline), aber die Position kommt.
    assert not det.get("ort")
    adapter.close()


def test_kkk_detail_adresse_bevorzugt_ortsknoten(fixture_dir_kinderkulturkalender):
    adapter = SelectorAdapter("kinderkulturkalender",
                              regel_yaml=KINDERKULTURKALENDER_REGELN)
    det = adapter.parse_detail(
        (fixture_dir_kinderkulturkalender / "detail.html").read_text(encoding="utf-8"))
    # Erste Alternative (Orts-Knoten) gewinnt, nicht der Kalender-Link.
    assert det["adresse"] == "Blücherplatz 1 10961 Berlin"
    adapter.close()


def test_parse_termin_text_ganztags_schreibweise():
    """Explizit „00:00 - 23:59" der Quelle = ganztägig (jup-Konvention)."""
    start, ende, ganztags = _parse_termin_text("12.09.26, 00:00 - 12.09.26, 23:59")
    assert ganztags is True
    assert (start.hour, start.minute) == (0, 0)
    assert (ende.hour, ende.minute) == (23, 59)
