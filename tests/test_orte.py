"""Ortsnamen: Normalform, automatische Zusammenführung, Prüfliste.

Alle Beispiele stammen aus echten Befunden des Nutzers (2026-09-13).
"""
from __future__ import annotations

from app.orte import (AEHNLICH_AB, aehnlich, automatische_zuordnung, generische,
                      gruppiere, ist_generisch, kanonisch_waehlen, normalform,
                      verdachtsfaelle)


def test_normalform_vereinheitlicht_schreibweisen():
    faelle = {
        "B.L.O. Ateliers": "b l o ateliers",
        "B.L.O.-Ateliers": "b l o ateliers",
        "Neue Kammern am Schloss Sanssouci": "neue kammern sanssouci",
        "Neue Kammern von Sanssouci": "neue kammern sanssouci",
        "Immanuelkirchstr. 1": "immanuelkirchstrasse 1",
        "Immanuelkirchstraße 1": "immanuelkirchstrasse 1",
        "Kapelle Ev. Immanuelkirche": "kapelle immanuelkirche",
    }
    for roh, erwartet in faelle.items():
        assert normalform(roh) == erwartet, roh


def test_generische_angaben_sind_keine_orte():
    """„Aula", „online", „Kein Ort" sagen keinen Ort — sie dürfen nicht als
    Veranstaltungsort geführt werden (Nutzerhinweis: „Kein spezifischer Ort")."""
    for roh in ("Aula", "aula", "online", "Kein Ort", "Ohne Angabe", "Berlinweit",
                "verschiedene Orte", "vielerorts", "vielerorts "):
        assert ist_generisch(roh), roh
    for echt in ("B.L.O. Ateliers", "Gärten der Welt", "Zühlsdorfer Str. 16-18",
                 "Humboldt-Bibliothek"):
        assert not ist_generisch(echt), echt


def test_bezirksname_wird_auch_aus_dem_detail_kein_ort():
    """Bezirksnamen gehören nicht ins Ortsfeld — auch nicht aus dem Detail.

    Messung 2026-09-14 (Umweltkalender): 185 von 1350 Terminen standen mit
    „Friedrichshain-Kreuzberg" & Co. im Ortsfeld, weil die Prüfung nur das
    Feld der Übersichtsseite ansah und das Detail-Feld ungeprüft übernahm
    (dort steht bei manchen Angeboten nur „<Bezirk>, <PLZ> Berlin").
    """
    from datetime import datetime

    from app.adapters.selector_adapter import SelectorAdapter
    from app.model import TZ_BERLIN

    regel = """
quelle: testbezirk
listing:
  url: https://example.org/liste
  item_css: 'div.item'
  felder:
    titel: {css: 'h3'}
    start: {css: 'a', attr: 'href', regex: 'dat=([0-9]{4}-[0-9]{2}-[0-9]{2})', format: '%Y-%m-%d'}
detail:
  felder:
    ort: {css: 'div.ort'}
"""
    ad = SelectorAdapter("testbezirk", regel_yaml=regel)
    jetzt = datetime(2026, 9, 14, 12, 0, tzinfo=TZ_BERLIN)
    row = {"slug": "x", "titel": "Testangebot", "start": jetzt,
           "url": "https://example.org/details/1", "ort": "Friedrichshain-Kreuzberg"}
    # Detail liefert ebenfalls nur den Bezirk
    ev = ad.zu_event(row, {"ort": "Friedrichshain-Kreuzberg", "adresse": "10965 Berlin"},
                     jetzt)
    assert ev["ort"] != "Friedrichshain-Kreuzberg", "Bezirksname im Ortsfeld"
    assert ev["bezirk"] == "friedrichshain-kreuzberg"
    # Detail liefert einen echten Ort → der zählt
    ev2 = ad.zu_event(row, {"ort": "Gleisdreieckpark", "adresse": "10965 Berlin"}, jetzt)
    assert ev2["ort"] == "Gleisdreieckpark"


def test_automatische_zuordnung_nur_bei_gleicher_normalform():
    orte = [("B.L.O. Ateliers", 2), ("B.L.O.-Ateliers", 1),
            ("Neue Kammern am Schloss Sanssouci", 1), ("Neue Kammern von Sanssouci", 1),
            ("Humboldt-Bibliothek", 4), ("Aula", 3)]
    zu = automatische_zuordnung(orte)
    assert zu["B.L.O.-Ateliers"] == "B.L.O. Ateliers"          # häufigere gewinnt
    # Bei Häufigkeits-Gleichstand gewinnt die ausführlichere Schreibweise;
    # welche der beiden kanonisch wird, ist bewusst eine Anzeige-Entscheidung
    # und im Admin änderbar.
    kammern = {"Neue Kammern am Schloss Sanssouci", "Neue Kammern von Sanssouci"}
    assert (kammern & set(zu)) and set(zu.values()) & kammern
    assert "Humboldt-Bibliothek" not in zu                     # keine Variante
    assert "Aula" not in zu                                    # generisch


def test_kanonisch_waehlen_nimmt_die_ausfuehrlichste_bei_gleichstand():
    assert kanonisch_waehlen([("B.L.O. Ateliers", 3), ("B.L.O.-Ateliers", 1)]) == "B.L.O. Ateliers"
    assert kanonisch_waehlen([("Sanssouci", 2), ("Neue Kammern Sanssouci", 2)]) == \
        "Neue Kammern Sanssouci"


def test_gruppiere_laesst_generisches_weg():
    gruppen = gruppiere([("Aula", 5), ("online", 2), ("B.L.O. Ateliers", 2),
                         ("B.L.O.-Ateliers", 1)])
    assert set(gruppen) == {"b l o ateliers"}


def test_verdachtsfaelle_statt_automatischer_zusammenfuehrung():
    """Ähnliche Namen kommen auf die Prüfliste — nicht in die Automatik.
    „Grundschule am Park" kann es in zwei Bezirken geben."""
    orte = [("Kapelle Ev. Immanuelkirche", 2), ("Immanuelkirche", 1),
            ("Humboldt-Bibliothek", 3), ("Aula", 4)]
    paare = verdachtsfaelle(orte)
    gefunden = {(p["a"], p["b"]) for p in paare} | {(p["b"], p["a"]) for p in paare}
    assert ("Kapelle Ev. Immanuelkirche", "Immanuelkirche") in gefunden
    assert all(p["aehnlichkeit"] >= AEHNLICH_AB or p["grund"] == "teilmenge" for p in paare)
    assert any(p["grund"] == "teilmenge" for p in paare)   # „Immanuelkirche" ⊂ „Kapelle …"
    assert not any("Aula" in (p["a"], p["b"]) for p in paare)      # generisch raus
    assert aehnlich("Humboldt-Bibliothek", "Humboldt Bibliothek") == 1.0


def test_generische_liste_mit_anzahl():
    liste = generische([("Aula", 3), ("online", 2), ("B.L.O. Ateliers", 1)])
    assert liste[0] == ("Aula", 3)
    assert ("online", 2) in liste
    assert all(n not in ("B.L.O. Ateliers",) for n, _ in liste)
