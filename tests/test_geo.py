"""Tests: Forward-Geokodierung (Nominatim-Search) — Cache, Negativ-Cache,
Normalisierung. Netz wird mit httpx.MockTransport ersetzt (offline-deterministisch)."""
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
    assert ort_koordinaten(store, "AGB | Wiese", client, sleep_s=0) is None
    assert len(calls) == 1, "Negativ-Cache: kein zweiter Netz-Request"
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
