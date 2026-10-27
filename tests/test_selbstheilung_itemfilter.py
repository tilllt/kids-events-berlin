"""Selbstheilung: Blöcke ohne Termin-Merkmal deterministisch aussortieren.

Fall Umweltkalender Berlin: die Filterliste mischt datierte Termine und
Dauer-Angebote im gleichen Karten-Layout. Der `item_css` trifft beide, die
Angebote scheitern an `start` und erzeugen eine Fehlerquote — die das Modell
nicht reparieren kann, weil die Selektoren bereits stimmen. Der Filter wird
deshalb aus dem Start-Feld abgeleitet (`dat=` im Link) und wie ein
Modell-Vorschlag durch das Gate geschickt.
"""
import yaml

from app import selbstheilung as sh
from app.adapters.selector_adapter import SelectorAdapter
from app.store import Store

Q = "uk-test"
URL = "https://example.invalid/termine"

REGELN = """quelle: uk-test
listing:
  url: https://example.invalid/termine
  item_css: "div.grid-item"
  felder:
    titel: {css: "h3"}
    url: {css: "a", attr: "href"}
    start: {css: "a", attr: "href", regex: "dat=([0-9]{4}-[0-9]{2}-[0-9]{2})", format: "%Y-%m-%d"}
"""


def _html(n_termin: int = 30, n_angebot: int = 30) -> str:
    teile = []
    for i in range(n_termin):
        teile.append(
            f'<div class="grid-item"><h3>Termin {i}</h3>'
            f'<a href="/d/{i}?dat=2026-10-{i % 28 + 1:02d}">Details</a></div>')
    for i in range(n_angebot):
        teile.append(
            f'<div class="grid-item"><h3>Angebot {i}</h3>'
            f'<a href="/d/9{i}">Details</a></div>')
    return "<html><body>" + "".join(teile) + "</body></html>"


def _mit_nur_mit(regeln: str, nur_mit: str) -> str:
    doc = yaml.safe_load(regeln)
    doc["listing"]["nur_mit"] = nur_mit
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


# --- Ableitung des Filters ------------------------------------------------

def test_kandidat_kommt_aus_dem_start_link():
    assert sh.nur_mit_kandidat(REGELN) == 'a[href*="dat="]'


def test_ohne_literales_merkmal_kein_kandidat():
    ohne = REGELN.replace(
        'start: {css: "a", attr: "href", regex: "dat=([0-9]{4}-[0-9]{2}-[0-9]{2})", format: "%Y-%m-%d"}',
        'start: {css: "span.datum", format: "%d.%m.%Y"}')
    assert sh.nur_mit_kandidat(ohne) is None


def test_regex_ohne_praefix_kein_kandidat():
    ohne = REGELN.replace('regex: "dat=([0-9]{4}', 'regex: "([0-9]{4}')
    assert sh.nur_mit_kandidat(ohne) is None


# --- Engine ---------------------------------------------------------------

def test_adapter_ueberspringt_bloecke_ohne_das_merkmal():
    roh = SelectorAdapter(Q, regel_yaml=REGELN)
    zeilen = roh.parse_listing(_html())
    fehler = [w for w in roh.drain_warnungen() if w.startswith("Item ")]
    roh.close()
    assert len(zeilen) == 30 and len(fehler) == 30   # ohne Filter: 30 Angebote scheitern

    gefiltert = SelectorAdapter(Q, regel_yaml=_mit_nur_mit(REGELN, 'a[href*="dat="]'))
    zeilen2 = gefiltert.parse_listing(_html())
    fehler2 = [w for w in gefiltert.drain_warnungen() if w.startswith("Item ")]
    gefiltert.close()
    assert len(zeilen2) == 30 and fehler2 == []


# --- Gate: große Kalender sind kein Wildcard-Selektor ---------------------

def _viele(n: int) -> str:
    return "<html><body>" + "".join(
        f'<div class="grid-item"><h3>Termin {i}</h3>'
        f'<a href="/d/{i}?dat=2026-10-{i % 28 + 1:02d}">Details</a></div>'
        for i in range(n)) + "</body></html>"


def test_gate_akzeptiert_grossen_kalender_mit_klasse():
    neu = _mit_nur_mit(REGELN, 'a[href*="dat="]')
    p = sh.gate(neu_yaml=neu, alt_yaml=REGELN, quelle=Q,
                html_heute=_viele(1500), html_alt=None, treffer_alt=None)
    assert p["ok"], p["fehler"]
    assert p["beleg"]["treffer_heute"] == 1500
    assert any("großer Kalender" in w for w in p["beleg"]["warnungen"])


def test_gate_lehnt_wildcard_weiterhin_ab():
    grob = REGELN.replace('item_css: "div.grid-item"', 'item_css: "div"')
    p = sh.gate(neu_yaml=grob, alt_yaml=REGELN, quelle=Q,
                html_heute=_viele(300), html_alt=None, treffer_alt=None)
    assert not p["ok"] and any("grob" in f for f in p["fehler"]), p["fehler"]


# --- Reparatur ------------------------------------------------------------

def _store(tmp_path) -> Store:
    s = Store(tmp_path / "uk.db")
    s.add_source(Q, "Umweltkalender-Test", "regeln", URL)
    s.set_regeln(Q, REGELN)
    return s


def test_itemfilter_reparieren_uebernimmt_nach_gewinn(tmp_path):
    s = _store(tmp_path)
    mails = []
    mailer = lambda an, betreff, text: mails.append(text)  # noqa: E731
    konf = {"auto": True, "mail_aktiv": False, "max_pro_tag": 3}

    ergebnis = sh.itemfilter_reparieren(
        s, quelle=Q, regeln=REGELN, html=_html(), jetzt="2026-10-27T05:00:00+00:00",
        konf=konf, mailer=mailer, auto=True)

    assert ergebnis and ergebnis["aktion"] == "uebernommen", ergebnis
    neu = s.get_regeln(Q)["regel_yaml"]
    assert 'nur_mit: a[href*="dat="]' in neu
    assert ergebnis["beleg"]["fehler_vorher"] == 30
    assert ergebnis["beleg"]["fehler_nachher"] == 0
    # Historie vorhanden (Rücknahme möglich)
    assert s.regel_historie_liste(Q)[0]["neu_yaml"] == neu


def test_ohne_gewinn_wird_nichts_uebernommen(tmp_path):
    s = _store(tmp_path)
    konf = {"auto": True, "mail_aktiv": False, "max_pro_tag": 3}
    # Alle Blöcke tragen ein Datum → der Filter würde nichts wegnehmen.
    ergebnis = sh.itemfilter_reparieren(
        s, quelle=Q, regeln=REGELN, html=_html(n_angebot=0),
        jetzt="2026-10-27T05:00:00+00:00", konf=konf, auto=True)
    assert ergebnis is None
    assert s.get_regeln(Q)["regel_yaml"] == REGELN
