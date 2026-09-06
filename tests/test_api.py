"""API-Tests: Filter-Endpunkte gegen einen Offline-befüllten Store."""
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.model import TZ_BERLIN, iso_utc, make_event_id
from app.store import Store


def _seed(store):
    def add(titel, *, start, bezirk, band=None, kostenlos=True, ganztags=False, lat=None, lon=None):
        ende = start + timedelta(hours=2)
        local = start.strftime("%Y-%m-%dT%H:%M:%S")
        sid = f"{titel}#{local}"
        ev = {
            "id": make_event_id("jup-berlin", sid), "titel": titel,
            "beschreibung_kurz": "Beschreibung", "start_iso": iso_utc(start),
            "ende_iso": iso_utc(ende), "start_local": local,
            "ende_local": ende.strftime("%Y-%m-%dT%H:%M:%S"),
            "ganztags": ganztags, "ort": "Ort", "adresse": None, "bezirk": bezirk,
            "lat": lat, "lon": lon, "altersband_min": band[0] if band else None,
            "altersband_max": band[1] if band else None, "alters_familie": 0,
            "kategorien": ["workshop"], "kostenlos": kostenlos,
            "quelle": "jup-berlin", "source_event_id": sid,
            "source_url": f"https://jup.berlin/events/{titel.lower()}",
            "geholt_am": datetime.now(TZ_BERLIN).isoformat(),
        }
        store.upsert_event(ev)

    now = datetime.now(TZ_BERLIN)
    add("Vormittag Neukölln", start=now.replace(hour=9, minute=30), bezirk="neukoelln", band=(4, 6))
    add("Nachmittag Pankow", start=now.replace(hour=14, minute=0), bezirk="pankow", band=(7, 10), kostenlos=False)
    add("Ganztägig Mitte", start=now.replace(hour=0, minute=0), bezirk="mitte", ganztags=True,
        lat=52.52, lon=13.405)


def _client(tmp_path):
    store = Store(tmp_path / "api.db")
    _seed(store)
    from app.main import app
    app.state.store = store  # lifespan läuft im TestClient nicht automatisch an
    return TestClient(app), store


def test_events_filters_kombiniert(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/api/events", params={
        "bezirk": "neukoelln", "altersband": "4-6", "uhrzeit": "vormittag"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1 and data[0]["titel"] == "Vormittag Neukölln"
    assert data[0]["bezirk_label"] == "Neukölln"


def test_events_kostenlos_und_ganztags_bei_uhrzeit(tmp_path):
    client, _ = _client(tmp_path)
    # abend-Band: nur ganztägige Events (Regel: ganztags passt zu jedem Band);
    # das 9:30-Event ist Vormittag und fliegt raus.
    r = client.get("/api/events", params={"kostenlos": "true", "uhrzeit": "abend"})
    assert {e["titel"] for e in r.json()} == {"Ganztägig Mitte"}
    r2 = client.get("/api/events", params={"kostenlos": "false"})
    assert [e["titel"] for e in r2.json()] == ["Nachmittag Pankow"]
    r3 = client.get("/api/events", params={"uhrzeit": "vormittag"})
    assert {e["titel"] for e in r3.json()} >= {"Vormittag Neukölln", "Ganztägig Mitte"}


def test_geojson_und_ohne_position(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/api/events.geojson", params={"bezirk": "mitte"})
    gj = r.json()
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == 1
    f = gj["features"][0]
    assert f["geometry"]["coordinates"] == [13.405, 52.52]
    assert f["properties"]["source_url"].startswith("https://")
    r2 = client.get("/api/events.geojson")
    assert len(r2.json()["ohne_position"]) == 2  # zwei Events ohne Koordinaten


def test_meta_und_health(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/api/health").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert len(meta["bezirke"]) == 12
    assert any(b.get("neukoelln") for b in meta["bezirke"])
    assert {b["id"] for b in meta["altersbaender"]} >= {"0-3", "familie"}
