"""Regressionstest: Ortsname der Quelle Umweltkalender Berlin.

Anlass (2026-09-13, Nutzerfund): „Schiff ahoi!“ stand mit „Niederneuendorfer
Allee 81“ im Ortsfilter, obwohl die Detailseite den Veranstaltungsort nennt
(„Waldschule Spandau“). Ursache: Die Ortsregel las den Straßenteil aus dem
Feld „Ort/Treffpunkt:“. Die Regel liest jetzt genau das div, das den Wert
trägt — ein Umbau der Seite soll diesen Test rot machen, nicht still falsche
Orte liefern.

Die Fälle sind echte Messwerte von 654 Detailseiten (2026-09-13).
"""
import re

import pytest

from app.adapters.selector_adapter import SelectorAdapter
from app.quellen_defaults import UMWELTKALENDER_REGELN
from app.regeln import validate_regeln_yaml


def _seite(roh: str) -> str:
    """Detailseite in der ECHTEN Struktur: Wert im eigenen div nach dem Label.

    Wichtig: Das div ist der Grund, warum der Ortsname nicht in die folgende
    „Anfahrt:“-Zeile läuft — genau das war beim Umbau zuerst falsch.
    """
    return ("<!doctype html><html lang='de'><body>"
            "<section class='veranstaltungsdetail'>"
            "<strong>Anbieter:</strong><br><div>Waldschule Spandau</div><br>"
            f"<strong>Ort/Treffpunkt:</strong><br><div>{roh}</div><br>"
            "<strong>Anfahrt:</strong><br><div>Bürgerablage (Bus X36)</div><br>"
            "</section></body></html>")


def _adapter() -> SelectorAdapter:
    return SelectorAdapter("umweltkalender-berlin", regel_yaml=UMWELTKALENDER_REGELN)


def test_regeln_sind_pruefbar():
    assert validate_regeln_yaml(UMWELTKALENDER_REGELN, "umweltkalender-berlin") == []


@pytest.mark.parametrize("wert,erwartet", [
    # (d) Anschrift + Ortsname -> der Ortsname (der gemeldete Fehlerfall)
    ("Spandau, Niederneuendorfer Allee 81, 13587 Berlin, Waldschule Spandau",
     "Waldschule Spandau"),
    ("Spandau, Am Juliusturm 64, 13599 Berlin, Zitadelle Spandau",
     "Zitadelle Spandau"),
    ("Mitte, Otto-Braun-Straße 70-72, 10178 Berlin, OTTO Textilwerkstatt",
     "OTTO Textilwerkstatt"),
    ("Marzahn-Hellersdorf, Alte Hellersdorfer Straße 77, 12629 Berlin, SOS Kinderdorf, Lehrküche",
     "SOS Kinderdorf"),
    # (b) Ort + PLZ ohne Straße -> der Ort vor der PLZ
    ("Neukölln, Britzer Garten, 12349 Berlin, Lehmbau-Werkstatt, ca. 300m vom Eingang Tauernallee",
     "Britzer Garten"),
    ("Marzahn-Hellersdorf, Kienbergpark, 12683 Berlin, vor dem Umweltbildungszentrum",
     "Kienbergpark"),
    ("Reinickendorf, Tegeler Forst, 13505 Berlin, Weitere Informationen sollten nach der Anmeldung zur Verfügung gestellt werden.",
     "Tegeler Forst"),
    # (c) Bezirk, Ort, Straße, PLZ -> der Ort in der Mitte
    ("Marzahn-Hellersdorf, Umweltbildungszentrum Kienbergpark, Am Wuhleteich, 12619 Berlin",
     "Umweltbildungszentrum Kienbergpark"),
    # (a) nur Anschrift: der Straßenname bleibt stehen (kein Name in der Quelle)
    ("Spandau, Hahnebergweg 50, 13591 Berlin", "Hahnebergweg 50"),
    ("Pankow, Parkplatz Möllersfelder Weg, 13159 Berlin, Wir kommen zum Ausgangspunkt zurück.",
     "Parkplatz Möllersfelder Weg"),
    # online-Termine
    ("online", "online"),
    ("online, Umland von Berlin, der Treffpunkt für die Exkursionen wird bei der "
     "Vorbesprechung und digital bekannt gegeben (Vorbesprechungen freitags).",
     "online"),
])
def test_ort_aus_treffpunkt(wert, erwartet):
    assert _adapter().parse_detail(_seite(wert))["ort"] == erwartet


def test_ort_laeuft_nicht_in_die_anfahrt_zeile():
    """Der Punktestand-Fehler beim Umbau: Selektor ohne div-Grenze liest weiter."""
    ort = _adapter().parse_detail(
        _seite("Spandau, Niederneuendorfer Allee 81, 13587 Berlin, Waldschule Spandau"))["ort"]
    assert "Anfahrt" not in ort
    assert "Bürgerablage" not in ort


def test_anschrift_wird_nicht_zum_ortsnamen():
    """Wo die Quelle einen Namen nennt, darf keine Hausnummer im Ortsfeld landen."""
    faelle = [
        "Spandau, Niederneuendorfer Allee 81, 13587 Berlin, Waldschule Spandau",
        "Spandau, Am Juliusturm 64, 13599 Berlin, Zitadelle Spandau",
        "Mitte, Invalidenstr. 43, 10115 Berlin, Museum für Naturkunde",
    ]
    for wert in faelle:
        ort = _adapter().parse_detail(_seite(wert))["ort"]
        assert not re.search(r"\d", ort), f"Anschrift als Ort: {ort!r} aus {wert!r}"


def test_ort_und_adresse_aus_echter_detailseite(fixture_dir_umweltkalender):
    html = (fixture_dir_umweltkalender / "detail_97972.html").read_text(encoding="utf-8")
    d = _adapter().parse_detail(html)
    assert d["ort"] == "Waldschule Spandau"
    assert d["adresse"] == "Niederneuendorfer Allee 81, 13587 Berlin"
