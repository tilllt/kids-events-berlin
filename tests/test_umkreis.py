"""Change 018: Umkreissuche und Kalender-Abo (iCal)."""
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app import ical
from app.api import _naehe
from app.model import TZ_BERLIN, iso_utc, make_event_id
from app.store import Store

MITTE = (52.5200, 13.4050)


def _seed(store):
    def add(titel, *, lat=None, lon=None, adresse=None, start=None):
        start = start or (datetime.now(TZ_BERLIN) + timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0)
        ende = start + timedelta(hours=2)
        local = start.strftime("%Y-%m-%dT%H:%M:%S")
        sid = f"{titel}#{local}"
        store.upsert_event({
            "id": make_event_id("jup-berlin", sid), "titel": titel,
            "beschreibung_kurz": "Beschreibung", "start_iso": iso_utc(start),
            "ende_iso": iso_utc(ende), "start_local": local,
            "ende_local": ende.strftime("%Y-%m-%dT%H:%M:%S"),
            "ganztags": False, "ort": "Ort", "adresse": adresse, "bezirk": "mitte",
            "lat": lat, "lon": lon, "altersband_min": None, "altersband_max": None,
            "alters_familie": 0, "kategorien": ["workshop"], "kostenlos": True,
            "quelle": "jup-berlin", "source_event_id": sid,
            "source_url": "https://example.invalid/x",
            "geholt_am": datetime.now(TZ_BERLIN).isoformat(),
        })
    # Abstände zum Mittelpunkt MITTE: 0,3 km / 1,0 km / 13,9 km
    add("Nah", lat=52.5225, lon=13.4050, adresse="Nahstr. 1, 10115 Berlin")
    add("Mittel", lat=52.5290, lon=13.4050, adresse="Mittelstr. 2, 10115 Berlin")
    add("Weit", lat=52.5350, lon=13.2000, adresse="Weitstr. 3, 13587 Berlin")
    add("OhnePosition", adresse=None)


def _client(tmp_path):
    store = Store(tmp_path / "n.db")
    _seed(store)
    from app.main import app
    app.state.store = store
    return TestClient(app), store


def test_naehe_filtert_und_sortiert():
    rows = [{"id": "a", "lat": 52.5225, "lon": 13.405},      # 0,3 km
            {"id": "b", "lat": 52.5290, "lon": 13.405},      # 1,0 km
            {"id": "c", "lat": 52.5350, "lon": 13.200},      # 13,9 km
            {"id": "d", "lat": None, "lon": None}]
    im, entf = _naehe(rows, MITTE[0], MITTE[1], 2)
    assert [e["id"] for e in im] == ["a", "b"]                # nach Entfernung
    assert entf["a"] < entf["b"] <= 1.1
    assert "d" not in entf                                    # ohne Position fällt raus
    # Ohne Umkreis bleibt alles unverändert
    assert _naehe(rows, None, None, None)[0] == rows


def test_events_endpoint_mit_umkreis(tmp_path):
    c, _ = _client(tmp_path)
    nah = c.get("/api/events", params={"lat": MITTE[0], "lon": MITTE[1],
                                       "umkreis_km": 2}).json()
    titel = [e["titel"] for e in nah]
    assert titel == ["Nah", "Mittel"], titel
    assert nah[0]["entfernung_km"] <= 0.5
    # größerer Umkreis nimmt den weiten Termin mit
    weit = c.get("/api/events", params={"lat": MITTE[0], "lon": MITTE[1],
                                        "umkreis_km": 20}).json()
    assert "Weit" in [e["titel"] for e in weit]


def test_geojson_meldet_ehrlich_was_fehlt(tmp_path):
    """Die Oberfläche muss sagen können, was NICHT erscheinen kann."""
    c, _ = _client(tmp_path)
    gj = c.get("/api/events.geojson", params={"lat": MITTE[0], "lon": MITTE[1],
                                              "umkreis_km": 2}).json()
    assert len(gj["features"]) == 2
    assert len(gj["ohne_position"]) == 1          # „OhnePosition"
    assert gj["ausserhalb_umkreis"] == 1          # „Weit" liegt außerhalb
    assert gj["anzahl"] == 2


def test_plz_zentrum_aus_eigenem_bestand(tmp_path):
    c, _ = _client(tmp_path)
    r = c.get("/api/plz/13587").json()
    assert r["lat"] == round(52.5350, 2) and r["lon"] == round(13.2000, 2)
    assert r["termine"] == 1
    # Ortsname als Eingabe
    assert c.get("/api/plz/Ort").json()["termine"] >= 1
    # Unbekannt → 404 mit verständlichem Text, zu kurz → 400
    assert c.get("/api/plz/99999").status_code == 404
    assert c.get("/api/plz/ab").status_code == 400


def test_kalender_abo_liefert_ical(tmp_path):
    c, _ = _client(tmp_path)
    r = c.get("/api/kalender.ics", params={"lat": MITTE[0], "lon": MITTE[1],
                                           "umkreis_km": 2})
    assert r.status_code == 200
    assert "text/calendar" in r.headers["content-type"]
    t = r.text
    for pflicht in ("BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VTIMEZONE",
                    "TZID:Europe/Berlin", "END:VCALENDAR"):
        assert pflicht in t, pflicht
    assert t.count("BEGIN:VEVENT") == 2
    assert "DTSTART;TZID=Europe/Berlin:" in t
    assert "Entfernung: " in t
    # UID stabil: zweiter Abruf erzeugt dieselben Kennungen (sonst Duplikate
    # im Kalender des Nutzers)
    uids1 = [z for z in t.splitlines() if z.startswith("UID:")]
    uids2 = [z for z in c.get("/api/kalender.ics", params={
        "lat": MITTE[0], "lon": MITTE[1], "umkreis_km": 2}).text.splitlines()
        if z.startswith("UID:")]
    assert uids1 and uids1 == uids2


def test_ical_ganztags_escaping_und_faltung():
    ev = {"id": "x1", "titel": "Fest, mit Strich; und Komma",
          "beschreibung_kurz": "Zeile1\nZeile2 " + "lang " * 40,
          "start_local": "2026-09-14T00:00:00", "ende_local": "2026-09-14T23:59:00",
          "ganztags": True, "ort": "Gärten der Welt", "adresse": "Eisenacher Str. 99",
          "source_url": "https://example.invalid/x", "kategorien": ["fest"],
          "geholt_am": "2026-09-13T10:00:00+02:00"}
    zeilen = ical.vevent(ev)
    text = "\r\n".join(zeilen)
    assert "DTSTART;VALUE=DATE:20260914" in text          # ganztags ohne Uhrzeit
    assert "DTEND;VALUE=DATE:20260915" in text            # Enddatum ist exklusiv
    assert "SUMMARY:Fest\\, mit Strich\\; und Komma" in text
    assert "\\n" in text                                   # Zeilenumbruch escaped
    # Gefaltet wird mit "\r\n " (RFC 5545) — jede so entstehende Zeile muss
    # höchstens 75 Oktette lang sein.
    for z in "\r\n".join(zeilen).split("\r\n"):
        assert len(z.encode("utf-8")) <= 75, z


def test_kalender_zeitraum_wird_begrenzt(tmp_path):
    """Ohne Begrenzung würde ein Abo tausende Termine ziehen."""
    c, store = _client(tmp_path)
    weit = datetime.now(TZ_BERLIN) + timedelta(days=200)
    local = weit.strftime("%Y-%m-%dT%H:%M:%S")
    sid = f"Zukunft#{local}"
    store.upsert_event({
        "id": make_event_id("jup-berlin", sid), "titel": "Zukunft",
        "beschreibung_kurz": "x", "start_iso": iso_utc(weit),
        "ende_iso": iso_utc(weit + timedelta(hours=2)), "start_local": local,
        "ende_local": (weit + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S"),
        "ganztags": False, "ort": "Ort", "adresse": None, "bezirk": "mitte",
        "lat": None, "lon": None, "altersband_min": None, "altersband_max": None,
        "alters_familie": 0, "kategorien": [], "kostenlos": None,
        "quelle": "jup-berlin", "source_event_id": sid,
        "source_url": "https://example.invalid/z",
        "geholt_am": datetime.now(TZ_BERLIN).isoformat()})
    t = c.get("/api/kalender.ics").text
    assert "Zukunft" not in t                              # außerhalb der 8 Wochen
    t20 = c.get("/api/kalender.ics", params={"wochen": 40}).text
    assert "Zukunft" in t20
