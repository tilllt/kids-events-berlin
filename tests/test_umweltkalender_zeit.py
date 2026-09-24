"""Regressionstest: Veranstaltungsuhrzeiten der Quelle Umweltkalender Berlin.

Anlass (2026-09-24, Nutzerfund): Die Uhrzeiten stehen auf der Seite, der Scraper
kannte sie nicht — alle Termine der Quelle standen ganztägig in der App. Grund:
Im Listing steht nur das Datum (das kommt aus `dat=` in der URL), die Uhrzeit
steht ausschließlich im Terminblock der Detailseite:

    ... Freitag, 25. September 2026<div class="separator">|</div>12:00 - 18:30 Uhr

Der Regel-Adapter kann Uhrzeiten jetzt auch aus dem Detail lesen
(`detail.felder.zeit` / `.ende`, Format `%H:%M`) und setzt sie nur auf den
Listing-Termin, der sonst ganztägig wäre.

Messwerte 2026-09-24 an 180 echten Detailseiten: 155× „HH:MM - HH:MM Uhr“,
8× „HH:MM Uhr“, 0× andere Schreibweise; 17 Seiten nennen gar keine Uhrzeit —
sie gehören zu vier Angeboten (Aktionswoche, Dauerprogramm, „unterschiedliche
Anfangszeiten“) und bleiben ganztägig.
"""
from datetime import datetime

import pytest

from app.adapters.selector_adapter import SelectorAdapter
from app.model import TZ_BERLIN
from app.quellen_defaults import UMWELTKALENDER_REGELN
from app.regeln import validate_regeln_yaml


def _adapter() -> SelectorAdapter:
    return SelectorAdapter("umweltkalender-berlin", regel_yaml=UMWELTKALENDER_REGELN)


def _seite(terminblock: str) -> str:
    """Detailseite in der echten Struktur — Terminblock + Ortsblock."""
    return ("<!doctype html><html lang='de'><body>"
            "<section class='veranstaltungsdetail'>"
            f"<div class='date_detail'>{terminblock}</div>"
            "<h1>Ökomarkt im Hansaviertel</h1>"
            "<div class='read-more-content'><p>Beschreibung</p></div>"
            "<strong>Ort/Treffpunkt:</strong><br>"
            "<div>Mitte, Altonaer Straße/Klopstockstraße, 10557 Berlin, direkt am U-Bahnhof</div><br>"
            "</section></body></html>")


def _row(start: datetime, ganztags: bool, slug: str = "oekomarkt-im-hansaviertel") -> dict:
    """Listing-Zeile, wie sie `parse_listing` für den Umweltkalender liefert.

    Der Umweltkalender liefert im Listing nur das Datum (`dat=` aus der URL),
    die Zeile ist deshalb ganztägig und hat keinen Zeitanteil.
    """
    return {
        "slug": slug, "url": "https://www.umweltkalender-berlin.de/angebote/details/17652",
        "titel": "Ökomarkt im Hansaviertel", "start": start, "ende": None,
        "ganztags": ganztags, "ort": "Mitte", "beschreibung_kurz": None,
        "adresse": None, "bezirk": "mitte",
    }


def test_regeln_sind_pruefbar():
    assert validate_regeln_yaml(UMWELTKALENDER_REGELN, "umweltkalender-berlin") == []


def test_detail_zeit_aus_leerem_detail_ist_erlaubt():
    """`zeit`/`ende` sind Detail-Felder — vorher lehnte der Prüfer sie ab."""
    assert "zeit" in UMWELTKALENDER_REGELN and "ende" in UMWELTKALENDER_REGELN


def test_zeit_und_ende_aus_echter_detailseite(fixture_dir_umweltkalender):
    html = (fixture_dir_umweltkalender / "detail_17652.html").read_text(encoding="utf-8")
    d = _adapter().parse_detail(html)
    assert d["zeit"] == "12:00"
    assert d["ende"] == "18:30"
    # Der Termin des Tages (nicht die „Weitere Termine“-Liste) ist die Quelle:
    # die Liste hat dieselben Zeiten, ein anderer Tag dürfte hier nicht stehen.
    assert "02.10" not in d["zeit"]


@pytest.mark.parametrize("block,zeit,ende", [
    # Spanne — die häufigste Form (140 von 163)
    ("Freitag, 25. September 2026<div class='separator'>|</div>12:00&nbsp;-&nbsp;18:30&nbsp;Uhr<br>",
     "12:00", "18:30"),
    # Einzelzeit (5 von 163): Beginn ohne Ende
    ("Donnerstag, 24. September 2026<div class='separator'>|</div>17:00&nbsp;Uhr<br>", "17:00", None),
    # ZLB-Schreibweise mit „Uhr“ an beiden Zeiten
    ("Samstag, 26. September 2026<div class='separator'>|</div>10:00 Uhr - 13:00 Uhr<br>",
     "10:00", "13:00"),
    # Aktionswoche/Dauerprogramm: nur Datum, keine Uhrzeit
    ("Donnerstag, 24. September 2026<br><div class='zusatzinfo gray fs-14'><strong>18.09.-08.10.26</strong></div>",
     None, None),
    # „unterschiedliche Anfangszeiten“ — keine einzelne Zeit nennbar
    ("Freitag, 25. September 2026<br><div class='zusatzinfo gray fs-14'>"
     "<strong>unterschiedliche Anfangszeiten</strong></div>", None, None),
    # Hypothetische „bis“-Schreibweise: lieber keine Zeit als die falsche Zahl
    # (ohne den „|“-Anker läse die Regel hier fälschlich 13:00 als Beginn).
    ("Freitag, 25. September 2026<div class='separator'>|</div>10:00 bis 13:00 Uhr<br>",
     None, None),
])
def test_terminblock_formen(block, zeit, ende):
    d = _adapter().parse_detail(_seite(block))
    # Kein Treffer → Feld fehlt ganz (kein leerer String in der Datenbank).
    assert d.get("zeit") == zeit
    assert d.get("ende") == ende


def test_zu_event_setzt_uhrzeit_und_ende():
    """Der gemeldete Fehler: der Termin stand ganztägig, obwohl die Zeit bekannt ist."""
    adapter = _adapter()
    detail = {"zeit": "12:00", "ende": "18:30"}
    start = datetime(2026, 9, 25, tzinfo=TZ_BERLIN)
    ev = adapter.zu_event(_row(start, ganztags=True), detail, datetime.now(TZ_BERLIN))
    assert ev["start_local"] == "2026-09-25T12:00:00"
    assert ev["ende_local"] == "2026-09-25T18:30:00"
    assert ev["ganztags"] is False
    assert ev["start_local"].startswith("2026-09-25"), "Datum aus dem Listing bleibt"
    adapter.close()


def test_ohne_detailzeit_bleibt_ganztags():
    adapter = _adapter()
    start = datetime(2026, 9, 25, tzinfo=TZ_BERLIN)
    ev = adapter.zu_event(_row(start, ganztags=True), {}, datetime.now(TZ_BERLIN))
    assert ev["ganztags"] is True
    assert ev["start_local"] == "2026-09-25T00:00:00"
    adapter.close()


def test_listing_zeit_wird_nicht_ueberschrieben():
    """Hat das Listing eine Zeit, ist es die Wahrheit — nicht das Detail."""
    adapter = _adapter()
    start = datetime(2026, 9, 25, 9, 0, tzinfo=TZ_BERLIN)
    row = _row(start, ganztags=False)
    row["ende"] = datetime(2026, 9, 25, 10, 0, tzinfo=TZ_BERLIN)
    ev = adapter.zu_event(row, {"zeit": "12:00", "ende": "18:30"}, datetime.now(TZ_BERLIN))
    assert ev["start_local"] == "2026-09-25T09:00:00"
    assert ev["ende_local"] == "2026-09-25T10:00:00"
    adapter.close()


def test_serientermin_behaelt_eigene_zeit():
    """Termin aus `termine_css` (Serie) bringt seine Zeit mit — Detail greift nicht."""
    adapter = _adapter()
    row = _row(datetime(2026, 9, 25, tzinfo=TZ_BERLIN), ganztags=True)
    termine = [(datetime(2026, 9, 25, 8, 30, tzinfo=TZ_BERLIN),
                datetime(2026, 9, 25, 9, 30, tzinfo=TZ_BERLIN), False)]
    detail = {"zeit": "12:00", "ende": "18:30"}
    ev = adapter._bau_event(row, detail, datetime.now(TZ_BERLIN),
                            termine[0][0], termine[0][1], termine[0][2])
    assert ev["start_local"] == "2026-09-25T08:30:00"
    assert ev["ende_local"] == "2026-09-25T09:30:00"
    adapter.close()


def test_ende_vor_start_bleibt_ohne_ende():
    """Nachttermin-Schreibweise: kein negatives Ende in die Datenbank."""
    adapter = _adapter()
    start = datetime(2026, 9, 25, tzinfo=TZ_BERLIN)
    ev = adapter.zu_event(_row(start, ganztags=True),
                          {"zeit": "22:00", "ende": "02:00"}, datetime.now(TZ_BERLIN))
    assert ev["start_local"] == "2026-09-25T22:00:00"
    assert ev["ende_local"] is None
    assert ev["ganztags"] is False
    adapter.close()


def test_kaputte_detailzeit_wird_ignoriert():
    """Ein Wert, der nicht zum Format passt, darf den Lauf nicht sprengen."""
    adapter = _adapter()
    start = datetime(2026, 9, 25, tzinfo=TZ_BERLIN)
    ev = adapter.zu_event(_row(start, ganztags=True),
                          {"zeit": "abends", "ende": "?"}, datetime.now(TZ_BERLIN))
    assert ev["ganztags"] is True
    adapter.close()


# ------------------------------------------------------------ Nutzerfund 2
# 2026-09-24: Die Uhrzeit steht BEI VIELEN Angeboten schon in der Übersicht —
# die Regel las die Datumskarte gar nicht. Gemessen an der Filterliste:
# 1265 von 3095 `div.date`-Feldern nennen eine Zeit; mit dem neuen Listing-Feld
# bekommen 1199 von 1338 Zeilen (90 %) ihre Uhrzeit direkt aus dem Listing,
# die übrigen (z. B. Bauernmarkt: nur Datum) aus der Detailseite.

def _karte(dat_text: str, zeit_text: str = "") -> str:
    """Listing-Karte in der echten Struktur (zwei `div.date`: Datum, Zeit)."""
    zeit = f'<div class="separator">|</div><div class="date">{zeit_text}</div>' if zeit_text else ""
    return ("<div class='grid-item teaser js-grid-item'>"
            "<a href='/angebote/details/62508?dat=2026-09-24' target='_self'>"
            "<h3>Bauernmarkt Wittenbergplatz</h3>"
            "<div class='location'>Charlottenburg-Wilmersdorf | Wittenbergplatz</div>"
            f"<div class='date'>Do., 24.09.2026</div>{zeit}"
            "</a></div>")


def test_listing_zeit_wird_gelesen():
    """Der gemeldete Fall: Zeit steht in der Übersicht, der Scraper kannte sie nicht."""
    ad = _adapter()
    rows = ad.parse_listing(f"<html><body>{_karte('Do., 24.09.2026', '10:00 - 16:00 Uhr')}</body></html>")
    assert len(rows) == 1
    r = rows[0]
    assert r["ganztags"] is False
    assert r["start"].strftime("%Y-%m-%d %H:%M") == "2026-09-24 10:00"
    assert r["ende"].strftime("%H:%M") == "16:00"
    ad.close()


def test_listing_ohne_zeit_bleibt_ganztags():
    """Karte ohne Uhrzeit (nur Datum) → ganztägig, Detail entscheidet später."""
    ad = _adapter()
    rows = ad.parse_listing(f"<html><body>{_karte('Do., 24.09.2026')}</body></html>")
    assert rows and rows[0]["ganztags"] is True
    assert rows[0]["start"].strftime("%H:%M") == "00:00"
    ad.close()


def test_listing_zeit_schlaegt_nicht_bei_anderem_tag_zu():
    """„+ weitere Termine“ in der Karte darf keine Uhrzeit erfinden.

    Die Karte nennt nur den ersten Tag; eine Uhrzeit ohne „Uhr“ (z. B. eine
    Jahreszahl oder ein anderes Datum) ergibt KEINE Zeit — lieber ganztägig
    als eine falsche Zahl.
    """
    ad = _adapter()
    rows = ad.parse_listing(
        "<html><body><div class='grid-item teaser'><a href='/angebote/details/1?dat=2026-09-25'>"
        "<h3>Angebot</h3><div class='date'>Do., 24.09.2026 + weitere Termine</div>"
        "<div class='date'>24.09.2026</div></a></div></body></html>")
    assert rows and rows[0]["ganztags"] is True
    ad.close()
