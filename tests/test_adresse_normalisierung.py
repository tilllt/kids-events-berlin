"""Change 009: Adress-Normalisierung vor der WFS-Abfrage (Abkürzungen/Schreibweise).

Gemessen am Berliner WFS (2026-09-12): „Distelfalterstr. 41 12683 Berlin“ →
0 Treffer, „Distelfalterstraße 41“ → 1 Treffer. Gleiches Muster bei
„Konrad-Wolf-Str.“ und „Rheinstr.“; die Anzeige-Adresse bleibt die Quellangabe.
"""
import urllib.parse

import httpx

from app.geo import _adresse_normalisieren, adresse_amtlich
from app.store import Store

ANTWORT = {"features": [{
    "properties": {"hnr_zusatz": "", "bez_name": "Mitte", "str_name": "Teststraße"},
    "geometry": {"coordinates": [391500.0, 5824000.0]},
}]}


def _client(anfragen: list):
    def handler(request):
        anfragen.append(urllib.parse.unquote(str(request.url)))
        return httpx.Response(200, json=ANTWORT)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_abkuerzungen_werden_ausgeschrieben():
    assert _adresse_normalisieren("Distelfalterstr. 41 12683 Berlin") == \
        "Distelfalterstraße 41 12683 Berlin"
    assert _adresse_normalisieren("Ruheplatzstr. 12 13347 Berlin") == \
        "Ruheplatzstraße 12 13347 Berlin"
    assert _adresse_normalisieren("Klosterstr. 3 13581 Berlin") == \
        "Klosterstraße 3 13581 Berlin"
    assert _adresse_normalisieren("Scherenbergstr. 1 10439 Berlin") == \
        "Scherenbergstraße 1 10439 Berlin"


def test_wortteil_str_und_platz():
    assert _adresse_normalisieren("Konrad-Wolf-Str. 39 13055 Berlin") == \
        "Konrad-Wolf-Straße 39 13055 Berlin"
    assert _adresse_normalisieren("Robert-W.-Kempner-Str. 1 14167 Berlin") == \
        "Robert-W.-Kempner-Straße 1 14167 Berlin"
    assert _adresse_normalisieren("Heinrich-von-Kleist-Pl. 1 12249 Berlin") == \
        "Heinrich-von-Kleist-Platz 1 12249 Berlin"


def test_stadt_schreibweise_und_laenderzusatz():
    assert _adresse_normalisieren("Charlottenburger Straße 117 13086 BErlin") == \
        "Charlottenburger Straße 117 13086 Berlin"
    assert _adresse_normalisieren("Blücherplatz 1 10961 Berlin Deutschland") == \
        "Blücherplatz 1 10961 Berlin"
    assert _adresse_normalisieren("  Riesestr.  10   12053  Berlin ") == \
        "Riesestraße 10 12053 Berlin"


def test_vollstaendige_schreibweise_bleibt_unveraendert():
    for a in ("Königin-Luise-Straße 6-8, 14195 Berlin",
              "Columbiadamm 84 10965 Berlin",
              "Straße zum FEZ 2 12459 Berlin",
              "Am Straßenrand 3 10115 Berlin"):
        assert _adresse_normalisieren(a) == a


def test_wfs_abfrage_nutzt_die_langform_und_einen_schluessel(tmp_path):
    store = Store(tmp_path / "geo.db")
    anfragen: list = []
    client = _client(anfragen)
    r = adresse_amtlich(store, "Distelfalterstr. 41 12683 Berlin", client, sleep_s=0)
    assert r is not None, "Mock-Treffer muss durchgehen"
    assert len(anfragen) == 1
    assert "Distelfalterstraße" in anfragen[0]
    assert "Distelfalterstr." not in anfragen[0]
    # Schreibvariante trifft denselben Cache-Eintrag → kein zweiter Netzzugriff
    adresse_amtlich(store, "Distelfalterstraße 41 12683 Berlin", client, sleep_s=0)
    assert len(anfragen) == 1
    store.close()


def test_unparsebare_adresse_bleibt_ohne_abfrage(tmp_path):
    store = Store(tmp_path / "geo.db")
    anfragen: list = []
    client = _client(anfragen)
    # „… Kapelle …“ zwischen Hausnummer und PLZ bleibt (noch) unparsebar
    assert adresse_amtlich(store, "Immanuelkirchstraße 1 Kapelle 10405 Berlin",
                           client, sleep_s=0) is None
    assert anfragen == []
    store.close()
