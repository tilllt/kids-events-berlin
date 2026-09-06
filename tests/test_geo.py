"""Tests: Forward-Geokodierung (Nominatim-Search) — Cache, Negativ-Cache,
Normalisierung. Netz wird mit httpx.MockTransport ersetzt (offline-deterministisch)."""
import urllib.parse

import httpx
import pytest

from app.geo import ort_key, ort_koordinaten


def _client_mit_antwort(treffer):
    def handler(request):
        return httpx.Response(200, json=treffer)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ort_key_normalisiert():
    assert ort_key("  Neue Nationalgalerie  ") == "neue nationalgalerie"
    assert ort_key("AGB | Wiese") == "agb | wiese"
    assert ort_key("Müggelsee") == "mueggelsee"
    assert ort_key("a  b") == "a b"


def test_ort_koordinaten_treffer_und_cache(tmp_path):
    from app.store import Store
    store = Store(tmp_path / "geo.db")
    treffer = [{
        "lat": "52.5073", "lon": "13.3675",
        "display_name": "Neue Nationalgalerie, Potsdamer Straße 50, 10785 Berlin, Deutschland",
        "address": {"borough": "Berlin", "suburb": "Tiergarten", "city": "Berlin"},
    }]
    calls = []
    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, json=treffer)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    r1 = ort_koordinaten(store, "Neue Nationalgalerie", client, sleep_s=0)
    assert r1 is not None
    assert r1["lat"] == 52.5073 and r1["lon"] == 13.3675
    assert r1["adresse"] == "Neue Nationalgalerie, Potsdamer Straße 50, 10785 Berlin"
    assert len(calls) == 1
    # Zweiter Aufruf: Cache, kein Netz
    r2 = ort_koordinaten(store, "Neue Nationalgalerie", client, sleep_s=0)
    assert r2 == r1 and len(calls) == 1
    client.close()


def test_ort_koordinaten_negativ_cache(tmp_path):
    from app.store import Store
    store = Store(tmp_path / "geo.db")
    calls = []
    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, json=[])
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert ort_koordinaten(store, "AGB | Wiese", client, sleep_s=0) is None
    n1 = len(calls)
    assert n1 == 2, "zweistufige Suche (Berlin + pur) pro Fehlversuch"
    assert ort_koordinaten(store, "AGB | Wiese", client, sleep_s=0) is None
    assert len(calls) == n1, "Negativ-Cache: kein zweiter Netz-Request"
    client.close()


def test_ort_koordinaten_kurz_none(tmp_path):
    from app.store import Store
    store = Store(tmp_path / "geo.db")
    assert ort_koordinaten(store, "Ohne Angabe", None) is None
    assert ort_koordinaten(store, "Abc", None) is None
    assert ort_koordinaten(store, "Neue Nationalgalerie", None) is None  # offline


def test_ort_key_ohne_treffer_wird_negativ_gespeichert(tmp_path):
    from app.store import Store
    store = Store(tmp_path / "geo.db")
    ort_koordinaten(store, "Unbekannter Ort XYZ", None)
    # kein Client → kein Cache-Eintrag (offline darf nichts speichern)
    assert store.get_ort_geo(ort_key("Unbekannter Ort XYZ")) is None


def test_ort_aufloesen():
    from app.geo import ort_aufloesen
    assert ort_aufloesen("AGB | Wiese") == (
        "Amerika-Gedenkbibliothek (Wiese)", "Blücherplatz 1, 10961 Berlin")
    assert ort_aufloesen("BStB | PopUp Saal") == (
        "Berliner Stadtbibliothek (PopUp Saal)", "Breite Straße 30-36, 10178 Berlin")
    assert ort_aufloesen("AGB") == ("Amerika-Gedenkbibliothek",
                                    "Blücherplatz 1, 10961 Berlin")
    assert ort_aufloesen("Treffpunkt") == (
        "Amerika-Gedenkbibliothek (Treffpunkt)", "Blücherplatz 1, 10961 Berlin")
    assert ort_aufloesen("Neue Nationalgalerie") == ("Neue Nationalgalerie", None)
    assert ort_aufloesen("Ohne Angabe") == ("Ohne Angabe", None)
    assert ort_aufloesen(None) == (None, None)


# --- Amtliche Geokodierung (WFS Adressen Berlin) ---------------------------
def test_utm33n_zu_wgs84():
    """Rostocker Straße 32 (RBS-Punkt) → Koordinaten nahe Nominatim-Wert."""
    from app.geo import _utm33n_zu_wgs84, _wgs84_zu_utm33n
    lat, lon = _utm33n_zu_wgs84(386477.656, 5821519.552)
    assert abs(lat - 52.5318) < 0.001
    assert abs(lon - 13.3262) < 0.001
    # Roundtrip: WGS84 → UTM33 → WGS84 (cm-Genauigkeit genügt)
    east, north = _wgs84_zu_utm33n(lat, lon)
    assert abs(east - 386477.656) < 1.0
    assert abs(north - 5821519.552) < 1.0
    lat2, lon2 = _utm33n_zu_wgs84(east, north)
    assert abs(lat2 - lat) < 1e-6 and abs(lon2 - lon) < 1e-6


def test_adresse_teile():
    from app.geo import _adresse_teile
    t = _adresse_teile("Königin-Luise-Straße 6-8, 14195 Berlin")
    assert t == {"str": "Königin-Luise-Straße", "hnr": "8",
                 "zus": None, "plz": "14195"}
    t2 = _adresse_teile("Rostocker Straße 32 B, 10553 Berlin")
    assert t2["str"] == "Rostocker Straße" and t2["hnr"] == "32"
    assert t2["zus"] == "B" and t2["plz"] == "10553"
    assert _adresse_teile("Neue Nationalgalerie") is None  # keine Hausnr


def test_adresse_amtlich_treffer_und_cache(tmp_path):
    from app.geo import adresse_amtlich
    from app.store import Store
    store = Store(tmp_path / "geo.db")
    feats = [{
        "type": "Feature", "id": "adressen_berlin.1",
        "geometry": {"type": "Point",
                     "coordinates": [386477.656, 5821519.552]},
        "properties": {"str_name": "Rostocker Straße", "hnr": "32",
                       "hnr_zusatz": None, "plz": "10553",
                       "bez_name": "Mitte", "ort_name": "Moabit"},
    }]
    calls = []
    def handler(request):
        calls.append(str(request.url))
        u = urllib.parse.unquote(str(request.url))
        assert "str_name='Rostocker Straße'" in u
        assert "plz='10553'" in u
        return httpx.Response(200, json={"type": "FeatureCollection",
                                         "features": feats})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    r1 = adresse_amtlich(store, "Rostocker Straße 32, 10553 Berlin", client, sleep_s=0)
    assert r1 is not None
    assert abs(r1["lat"] - 52.5318) < 0.001
    assert r1["bezirk"] == "mitte"
    assert len(calls) == 1
    r2 = adresse_amtlich(store, "Rostocker Straße 32, 10553 Berlin", client, sleep_s=0)
    assert r2 == r1 and len(calls) == 1  # Cache
    client.close()


def test_adresse_amtlich_negativ_cache(tmp_path):
    from app.geo import adresse_amtlich
    from app.store import Store
    store = Store(tmp_path / "geo.db")
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"type": "FeatureCollection",
                                         "features": []})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert adresse_amtlich(store, "Rostocker Straße 32, 10553 Berlin", client, sleep_s=0) is None
    assert adresse_amtlich(store, "Rostocker Straße 32, 10553 Berlin", client, sleep_s=0) is None
    assert len(calls) == 1
    client.close()
