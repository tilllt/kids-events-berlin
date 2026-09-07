"""Admin: Events-Verwaltung (alle Termine editierbar) — Store- + API-Ebene."""

import pytest
from app.store import Store


def _ev(ev_id="zlb-1", quelle="zlb", titel="Kinderführung"):
    return {"id": ev_id, "titel": titel, "beschreibung_kurz": "Führung",
            "start_iso": "2026-10-01T10:00:00+02:00", "ende_iso": None,
            "start_local": "2026-10-01T10:00:00", "ende_local": None,
            "ganztags": 0, "ort": "ZLB Berlin", "adresse": None,
            "bezirk": "mitte", "lat": None, "lon": None,
            "altersband_min": None, "altersband_max": None, "alters_familie": 0,
            "kategorien": ["lesung"], "kostenlos": 1, "quelle": quelle,
            "source_event_id": ev_id.split("-")[1], "source_url": "https://zlb.de/1",
            "geholt_am": "2026-09-07T00:00:00+00:00", "status": "auto"}


def _store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.seed_default_sources()
    return s


# --- Store ---
def test_list_events_admin_alle_quellen(tmp_path):
    s = _store(tmp_path)
    s.upsert_event(_ev("zlb-1", "zlb"))
    s.upsert_event(_ev("jup-1", "jup-berlin", titel="Workshop"))
    alle = s.list_events_admin()
    assert len(alle) == 2
    nur_zlb = s.list_events_admin(quelle="zlb")
    assert len(nur_zlb) == 1 and nur_zlb[0]["titel"] == "Kinderführung"
    suche = s.list_events_admin(q="Workshop")
    assert len(suche) == 1 and suche[0]["quelle"] == "jup-berlin"
    assert suche[0]["kategorien"] == ["lesung"]  # JSON wieder Liste
    s.close()


def test_update_event_admin_setzt_manuell(tmp_path):
    s = _store(tmp_path)
    s.upsert_event(_ev())
    # Admin-Edit → manuell=1, nur gesendete Felder
    assert s.update_event_admin("zlb-1", {"titel": "Gruselführung",
                                          "kategorien": ["theater"]})
    e = s.list_events_admin(quelle="zlb")[0]
    assert e["titel"] == "Gruselführung"
    assert e["kategorien"] == ["theater"]
    assert e["manuell"] == 1
    assert e["ort"] == "ZLB Berlin"  # ungesendete Felder bleiben
    # Scrape-Update überschreibt jetzt NICHT mehr
    neu, geaendert = s.upsert_event(_ev())  # Original ohne manuell
    assert not geaendert
    assert s.list_events_admin(quelle="zlb")[0]["titel"] == "Gruselführung"
    # start_local-Änderung zieht start_iso nach
    assert s.update_event_admin("zlb-1", {"start_local": "2026-11-01T15:00:00"})
    e2 = s.list_events_admin(quelle="zlb")[0]
    assert e2["start_local"] == "2026-11-01T15:00:00"
    assert e2["start_iso"].startswith("2026-11-01T14:00:00")  # UTC = CEST−2
    # unbekanntes Event
    assert not s.update_event_admin("gibtsnicht", {"titel": "x"})
    s.close()


# --- API ---
def test_events_api_crud(tmp_path):
    from fastapi.testclient import TestClient

    store = Store(tmp_path / "events_api.db")
    store.seed_default_sources()
    from app.main import app
    app.state.store = store
    c = TestClient(app)

    store.upsert_event(_ev())
    alle = c.get("/api/admin/events").json()
    assert any(e["id"] == "zlb-1" for e in alle)
    r = c.put("/api/admin/events/zlb-1", json={"titel": "API-Edit",
                                               "kategorien": ["fest"]})
    assert r.status_code == 200, r.text
    assert r.json()["titel"] == "API-Edit"
    assert r.json()["manuell"] == 1
    assert r.json()["kategorien"] == ["fest"]
    assert c.put("/api/admin/events/gibtsnicht", json={"titel": "x"}).status_code == 404
    store.close()
