"""Feed-Adapter (Change 006): RSS-Parsing, Titel-Zeit-Extraktion, Event-Bau."""

from datetime import datetime

import pytest

from app.adapters import build_adapter
from app.adapters.feed_adapter import FeedAdapter, _titel_termin
from app.store import Store

FIXTURE = "tests/fixtures/berlin-senbjf/rss.xml"


def _fixture() -> str:
    return open(FIXTURE, encoding="utf-8").read()


def _store(tmp_path):
    s = Store(tmp_path / "feed.db")
    s.seed_default_sources()
    return s


# --- Titel-Datumsklammer ----------------------------------------------------
def test_titel_termin_mit_zeit():
    start, ende, ganztags, sauber = _titel_termin(
        "Tag der offenen Tür der Jane-Addams-Schule (17.02.2027)")
    assert ganztags is True
    assert sauber == "Tag der offenen Tür der Jane-Addams-Schule"
    assert start.isoformat().startswith("2027-02-17T00:00:00")


def test_titel_termin_mit_zeitspanne():
    start, ende, ganztags, sauber = _titel_termin(
        "Tag der Offenen Tür der ISS der Evangelischen Schule Neukölln "
        "(15.01.2027 15:30 - 18:00 Uhr)")
    assert ganztags is False
    assert start.hour == 15 and start.minute == 30
    assert ende.hour == 18 and ende.minute == 0
    assert "Evangelischen Schule Neukölln" in sauber
    assert "(15.01.2027" not in sauber


def test_titel_termin_ohne_klammer():
    start, ende, ganztags, sauber = _titel_termin("Tag der offenen Tür")
    assert start is None and sauber == "Tag der offenen Tür"


# --- Adapter: Fixture-Parsing ----------------------------------------------
def test_parse_fixture_rows():
    a = FeedAdapter("berlin-senbjf-kalender", url="https://example.org/rss")
    rows = a.parse_listing(_fixture())
    assert len(rows) == 4
    assert not a.drain_warnungen()
    titel = [r["titel"] for r in rows]
    assert any("Evangelischen Schule Neukölln" in t for t in titel)
    assert any("Jane-Addams-Schule" in t for t in titel)
    # Jede Zeile hat einen Termin + URL
    for r in rows:
        assert r["start"] is not None and r["url"].startswith("http")
    # ganztags nur bei reinen Datums-Titeln
    by_titel = {r["titel"]: r for r in rows}
    ja = [r for t, r in by_titel.items() if "Jane-Addams" in t]
    assert ja and all(r["ganztags"] for r in ja)
    a.close()


def test_zu_event_berlin_zeit():
    a = FeedAdapter("berlin-senbjf-kalender", url="https://example.org/rss")
    rows = a.parse_listing(_fixture())
    jetzt = datetime(2026, 9, 7, 12, 0)
    evs = [a.zu_event(r, None, jetzt) for r in rows]
    # Ev. Schule Neukölln: 15:30 Berlin (Winter, ISO trägt +01:00-Offset)
    ev = [e for e in evs if "Neukölln" in e["titel"]][0]
    assert ev["start_local"] == "2027-01-15T15:30:00"
    assert ev["start_iso"].startswith("2027-01-15T15:30:00+01:00")
    assert ev["ende_local"] == "2027-01-15T18:00:00"
    assert ev["quelle"] == "berlin-senbjf-kalender"
    assert ev["source_url"].startswith("https://www.berlin.de")
    assert ev["ort"] == "Ohne Angabe"
    # ganztags-Event: Jane-Addams
    g = [e for e in evs if "Jane-Addams" in e["titel"]][0]
    assert g["ganztags"] is True and g["start_local"] == "2027-02-17T00:00:00"
    # IDs deterministisch
    evs2 = [a.zu_event(r, None, jetzt) for r in rows]
    assert evs[0]["id"] == evs2[0]["id"]
    a.close()


# --- Registry + Pipeline-Einbindung -----------------------------------------
def test_build_adapter_feed(tmp_path):
    s = _store(tmp_path)
    s.add_source(quelle="berlin-senbjf-kalender", name="SenBJF-Kalender",
                 typ="feed", url="https://www.berlin.de/land/kalender/index.php?rss",
                 horizont_tage=365)
    a = build_adapter(s, "berlin-senbjf-kalender")
    assert isinstance(a, FeedAdapter)
    assert a.horizont_tage == 365
    a.close()


def test_scrape_offline_feed(tmp_path):
    """Pipeline-Lauf offline gegen das Fixture: 4 Events, idempotent."""
    from app.pipeline import scrape
    from app.model import TZ_BERLIN

    s = _store(tmp_path)
    s.add_source(quelle="berlin-senbjf-kalender", name="SenBJF-Kalender",
                 typ="feed", url="https://www.berlin.de/land/kalender/index.php?rss",
                 horizont_tage=400)
    jetzt = datetime(2026, 9, 7, 12, 0, 0, tzinfo=TZ_BERLIN)
    res = scrape(s, "berlin-senbjf-kalender", online=False, geo=False,
                 listing_htmls=[_fixture()], jetzt=jetzt)
    assert res["rows"] == 4, res
    # Die Quelle listet Jane-Addams doppelt (2 identische Kalendereinträge) —
    # die Zwilling-Dedup der Pipeline entfernt das Duplikat → 3 eindeutige
    # (2. Jane-Addams zählt als „geändert“, nicht „neu“).
    assert res["n_neu"] == 3
    evs = s.query_events({"quelle": ["berlin-senbjf-kalender"]})
    assert len(evs) == 3
    # Idempotenz: zweiter Lauf 0 neu
    res2 = scrape(s, "berlin-senbjf-kalender", online=False, geo=False,
                  listing_htmls=[_fixture()], jetzt=jetzt)
    assert res2["n_neu"] == 0
    assert s.list_events_admin(quelle="berlin-senbjf-kalender")[0]["titel"]
    s.close()


# --- CLI/Endpunkt-Preflight ------------------------------------------------
def test_quelle_feed_validierung_api(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app

    store = _store(tmp_path)
    app.state.store = store
    c = TestClient(app)
    r = c.post("/api/admin/sources", json={
        "quelle": "berlin-senbjf-kalender", "name": "SenBJF-Kalender",
        "typ": "feed", "url": "https://www.berlin.de/land/kalender/index.php?rss",
        "aktiv": 1, "horizont_tage": 365})
    assert r.status_code == 201, r.text
    assert r.json()["typ"] == "feed"
    # Scrape-Trigger für feed-Quellen ist jetzt erlaubt (2022 statt 409) —
    # der Lauf läuft im Hintergrund-Thread und scheitert online nur am Netz.
    r2 = c.post("/api/admin/sources/berlin-senbjf-kalender/scrape", json={})
    assert r2.status_code == 202, r2.text
    store.close()
