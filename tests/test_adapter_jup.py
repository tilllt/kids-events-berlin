"""Adapter jup.berlin: Parser gegen echte Fixture-HTML (2026-09-06)."""
from app.adapters.jup_berlin import JupBerlinAdapter, _parse_daterange
from app.model import make_event_id, parse_local_dt


def test_listing_parse_erkennt_articles(listing_p0):
    rows = JupBerlinAdapter.parse_listing(listing_p0)
    assert len(rows) >= 10
    row = rows[0]
    assert row["slug"]
    assert row["titel"]
    assert row["start"].tzinfo is not None  # tz-aware
    assert row["ort"]


def test_listing_title_und_ort_sauber(listing_p0):
    rows = JupBerlinAdapter.parse_listing(listing_p0)
    by_slug = {r["slug"]: r for r in rows}
    kochbuch = by_slug.get("raetselabenteuer-berlin-prenzlauer-berg")
    assert kochbuch and kochbuch["titel"] == "Das magische Kochbuch"
    assert kochbuch["ort"] == "Kurt-Tucholsky-Bibliothek"


def test_daterange_formen():
    # ganztägig (00:00–23:59)
    s, e, g = _parse_daterange("05.09.2026 | 00:00 - 05.09.2026 | 23:59")
    assert s is not None and e is not None
    assert g is True and s.date().day == 5
    # mit Uhrzeiten
    s, e, g = _parse_daterange("05.09.2026 | 10:00 - 14:00")
    assert g is False and s.hour == 10 and e.hour == 14 and e.date() == s.date()
    # mehrtägig
    s, e, g = _parse_daterange("04.09.2026 | 10:00 - 08.09.2026 | 16:00")
    assert g is False and (e - s).days == 4


def test_detail_familiensportfest(detail_fam):
    d = JupBerlinAdapter.parse_detail(detail_fam)
    assert d["kostenlos_flag"] is True
    assert d["adresse"] and "13055" in d["adresse"]
    assert d["beschreibung_kurz"]


def test_detail_raetsel_koordinaten_und_adresse(detail_raetsel):
    d = JupBerlinAdapter.parse_detail(detail_raetsel)
    assert d["lat"] is not None and d["lon"] is not None
    assert abs(d["lat"] - 52.530955) < 0.01
    assert abs(d["lon"] - 13.32667) < 0.01
    assert d["adresse"] and "10553" in d["adresse"]
    assert d["kostenlos_flag"] is False


def test_zu_event_deterministisch_und_anreicherbar(detail_raetsel):
    a = JupBerlinAdapter()
    det = a.parse_detail(detail_raetsel)
    start = parse_local_dt("05.09.2026", "10:00")
    from datetime import datetime, timedelta
    row = {"slug": "raetselabenteuer-berlin-prenzlauer-berg", "titel": "Rätselabenteuer",
           "start": start, "ende": start + timedelta(hours=4), "ganztags": False,
           "ort": "Kurt-Tucholsky-Bibliothek"}
    jetzt = datetime.now(start.tzinfo)
    ev1 = a.zu_event(row, det, jetzt)
    ev2 = a.zu_event(row, det, jetzt)
    assert ev1["id"] == ev2["id"] == make_event_id("jup-berlin", ev1["source_event_id"])
    assert ev1["lat"] and ev1["source_url"].endswith("/events/raetselabenteuer-berlin-prenzlauer-berg")
    assert ev1["start_local"].startswith("2026-09-05T10:00")
