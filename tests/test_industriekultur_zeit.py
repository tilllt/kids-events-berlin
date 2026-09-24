r"""Regressionstest: Uhrzeiten der Quelle Festival Industriekultur Berlin.

Anlass (2026-09-24, Nutzerfund nach dem Umweltkalender-Fix): 105 von 236 Terminen
standen ganztägig in der App, obwohl die Detailseite die Uhrzeit nennt. Grund:
Die Übersichtskarte (div.bzi-festival-event-item) trägt bei diesen Terminen kein
`.bzi-festival-event-card-detail.is-time` — die Uhrzeit steht nur im Kopf der
Detailseite:

    <h2 class="bzi-color-1">Do., 24.09.2026 | 10:00 Uhr</h2>

Messung 2026-09-24 an 40 ganztägigen Terminen ab heute: 40 von 40 Detailseiten
nennen eine Uhrzeit (Audit-Skript, Muster `\d{1,2}:\d{2}`); an 20 Seiten geprüft:
je genau ein `h2.bzi-color-1`, immer die Form „<Wochentag>, <Datum> | HH:MM Uhr",
keine Seite ohne Zeit.
"""
from datetime import datetime

import pytest

from app.adapters.selector_adapter import SelectorAdapter
from app.model import TZ_BERLIN
from app.quellen_defaults import INDUSTRIEKULTUR_REGELN
from app.regeln import validate_regeln_yaml

QUELLE = "industriekultur-berlin"
URL = "https://industriekultur.berlin/festival/veranstaltung/alte-verkehrswege-im-suedwesten/"


def _adapter() -> SelectorAdapter:
    return SelectorAdapter(QUELLE, regel_yaml=INDUSTRIEKULTUR_REGELN)


def _head(text: str) -> str:
    """Detailseite in der echten Struktur — Kopfzeile mit der Uhrzeit."""
    return ("<!doctype html><html lang='de'><body>"
            "<section class='bzi-inner-section-wrapper ort-detail-wrapper'>"
            "<div class='ort-column ort-description bzi-festival-event-description'>"
            f"<h2 class='bzi-color-1'>{text}</h2>"
            "<span class='bzi-festival-event-status is-past'>Vergangen</span>"
            "<h2 class='bzi-festival-event-title'>Alte Verkehrswege im Südwesten</h2>"
            "<h4 class='bzi-color-1 subheadline'>Bahndamm-Wanderung (14 km)</h4>"
            "</div></section>"
            # „Weitere Termine"-Karten haben eigene Zeiten — sie dürfen nicht greifen.
            "<div class='bzi-festival-event-item'>"
            "<p class='bzi-festival-event-card-detail is-time'><span>16:00 Uhr</span></p>"
            "</div></body></html>")


def _row(start: datetime, ganztags: bool) -> dict:
    """Listing-Zeile, wie sie `parse_listing` für das Festival liefert."""
    return {
        "slug": "alte-verkehrswege-im-suedwesten", "url": URL,
        "titel": "Alte Verkehrswege im Südwesten", "start": start, "ende": None,
        "ganztags": ganztags, "ort": "Steglitz-Zehlendorf", "beschreibung_kurz": None,
        "adresse": None, "bezirk": "steglitz-zehlendorf",
    }


def test_regeln_sind_pruefbar():
    assert validate_regeln_yaml(INDUSTRIEKULTUR_REGELN, QUELLE) == []


def test_regel_ist_die_live_regel_plus_detailzeit():
    """Der Repo-Stand darf nicht hinter der Live-Regel zurückfallen."""
    assert "bzi-festival-event-item" in INDUSTRIEKULTUR_REGELN
    assert "detail:" in INDUSTRIEKULTUR_REGELN
    assert "h2.bzi-color-1" in INDUSTRIEKULTUR_REGELN


def test_zeit_aus_echter_detailseite(fixture_dir_industriekultur):
    """Echte, am 24.09.2026 gesicherte Detailseite (Auszug)."""
    html = (fixture_dir_industriekultur
            / "detail_alte_verkehrswege.html").read_text(encoding="utf-8")
    d = _adapter().parse_detail(html)
    assert d.get("zeit") == "10:00"
    # Nur die Kopfzeile zählt — nicht die „Weitere Termine“-Karte (16:00).
    assert d.get("zeit") != "16:00"


@pytest.mark.parametrize("text,zeit,ende", [
    ("Do., 24.09.2026 | 10:00 Uhr", "10:00", None),          # gemessene Form
    ("Fr., 25.09.2026 | 17:30 Uhr", "17:30", None),
    ("Sa., 26.09.2026 | 14:00 Uhr", "14:00", None),
    # Range-Form (auf dieser Quelle nicht gemessen, aber plausibel für
    # Ausstellungen): Beginn und Ende dürfen nicht verwechselt werden.
    ("Sa., 26.09.2026 | 10:00 - 18:00 Uhr", "10:00", "18:00"),
    # „bis“-Schreibweise ohne „|“-Anker: lieber keine Zeit als die falsche Zahl.
    ("Sa., 26.09.2026 10:00 bis 18:00 Uhr", None, None),
    # reine Datumszeile (Status „Vergangen“): keine Uhrzeit erfinden
    ("Do., 24.09.2026", None, None),
])
def test_kopfzeilen_formen(text, zeit, ende):
    d = _adapter().parse_detail(_head(text))
    assert d.get("zeit") == zeit
    assert d.get("ende") == ende


def test_zu_event_setzt_uhrzeit():
    """Der gemeldete Fehler: Termin stand ganztägig, obwohl die Zeit bekannt ist."""
    adapter = _adapter()
    start = datetime(2026, 9, 24, tzinfo=TZ_BERLIN)
    ev = adapter.zu_event(_row(start, ganztags=True), {"zeit": "10:00"},
                          datetime.now(TZ_BERLIN))
    assert ev["start_local"] == "2026-09-24T10:00:00"
    assert ev["ganztags"] is False
    adapter.close()


def test_listing_zeit_wird_nicht_ueberschrieben():
    """Hat die Übersichtskarte eine Zeit, bleibt sie die Wahrheit."""
    adapter = _adapter()
    start = datetime(2026, 9, 24, 16, 0, tzinfo=TZ_BERLIN)
    ev = adapter.zu_event(_row(start, ganztags=False), {"zeit": "10:00"},
                          datetime.now(TZ_BERLIN))
    assert ev["start_local"] == "2026-09-24T16:00:00"
    assert ev["ganztags"] is False
    adapter.close()


def test_ohne_detailzeit_bleibt_ganztags():
    adapter = _adapter()
    start = datetime(2026, 9, 24, tzinfo=TZ_BERLIN)
    ev = adapter.zu_event(_row(start, ganztags=True), {}, datetime.now(TZ_BERLIN))
    assert ev["ganztags"] is True
    adapter.close()


def test_kaputte_detailzeit_wird_ignoriert():
    adapter = _adapter()
    start = datetime(2026, 9, 24, tzinfo=TZ_BERLIN)
    ev = adapter.zu_event(_row(start, ganztags=True), {"zeit": "vormittags"},
                          datetime.now(TZ_BERLIN))
    assert ev["ganztags"] is True
    adapter.close()
