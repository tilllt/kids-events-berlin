"""Offline-End-to-End: Pipeline gegen Fixture-HTML, ohne Netz.

Beweist die LLM-frei/offline-Invariante und die Idempotenz über zwei Läufe.
"""
from datetime import datetime

from app.model import TZ_BERLIN
from app.pipeline import scrape
from app.store import Store


def test_offline_scrape_idempotent(tmp_path, listing_p0, listing_p1,
                                   detail_fam, detail_raetsel):
    db = tmp_path / "events.db"
    store = Store(db)
    listings = [listing_p0, listing_p1]
    details = {
        "familiensportfest": detail_fam,
        "raetselabenteuer-berlin-prenzlauer-berg": detail_raetsel,
    }
    s1 = scrape(store, online=False, listing_htmls=listings, detail_html=details)
    assert s1["n_fehler"] == 0
    assert s1["n_neu"] > 0
    assert s1["rows"] > 0
    n1 = store.count_events()

    s2 = scrape(store, online=False, listing_htmls=listings, detail_html=details)
    assert s2["n_neu"] == 0
    assert s2["n_geaendert"] == 0
    assert store.count_events() == n1

    runs = store.recent_runs("jup-berlin")
    assert runs[0]["status"] == "ok"
    assert runs[0]["n_events"] == n1

    # Detail-Anreicherung muss angekommen sein (Raetsel mit Koordinaten + Adresse)
    events = store.query_events({})
    raetsel = [e for e in events if "magische kochbuch" in e["titel"].lower()]
    assert raetsel and raetsel[0]["adresse"] and "10553" in raetsel[0]["adresse"]
    store.close()
