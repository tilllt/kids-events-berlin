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

Nachtrag 2026-09-24 (zweiter Nutzerfund): Der Fix konnte nie greifen — die
ÜBERSICHT ist umgezogen. `https://industriekultur.berlin/festival/` leitet per
301 auf `/industriekultur-festival/` (Marketing-Seite ohne Termine) um; die
Terminübersicht liegt jetzt unter `/erleben/festival/`. Folge: 0 Treffer je Lauf
(`anomalie-0-events`, Läufe 262–358), der Bestand fror ein — die 105 ganztägigen
Einträge waren stehengebliebene Alt-Dubletten. In der neuen Übersicht trägt JEDE
Karte `.is-time` (gemessen: 165 von 165).
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


# --------------------------------------------------------------- Listing-Umzug
# Zweiter Nutzerfund 2026-09-24: /festival/ → 301 → /industriekultur-festival/
# (Marketing-Seite OHNE Termine). Die Übersicht liegt unter /erleben/festival/.
# Fixture `listing_erleben.html` = echte Karten (Auszug; live 165 Karten).

NEUE_LISTING_URL = "https://industriekultur.berlin/erleben/festival/"


def _listing_rows(fixture_dir_industriekultur) -> list[dict]:
    html = (fixture_dir_industriekultur / "listing_erleben.html").read_text(
        encoding="utf-8")
    adapter = _adapter()
    rows = adapter.parse_listing(html)
    assert adapter.drain_warnungen() == []
    adapter.close()
    return rows


def test_uebersicht_liegt_nicht_mehr_unter_festival():
    assert f"url: {NEUE_LISTING_URL}" in INDUSTRIEKULTUR_REGELN
    # Die alte Adresse darf nirgends mehr als Listing stehen (sie leitet um).
    assert "url: https://industriekultur.berlin/festival/" not in INDUSTRIEKULTUR_REGELN


def test_neue_uebersicht_traegt_die_zeit_in_jeder_karte(fixture_dir_industriekultur):
    rows = _listing_rows(fixture_dir_industriekultur)
    assert len(rows) == 3
    # Der Unterschied zur alten Übersicht: jede Karte hat `.is-time` — keine
    # ganztägigen Platzhalter mehr (gemessen live: 165 von 165 Karten).
    assert all(r["ganztags"] is False for r in rows)
    assert all(r["start"].strftime("%H:%M") != "00:00" for r in rows)

    r = next(x for x in rows if x["titel"].startswith("After Work Radtour: Warmes Licht"))
    assert r["start"].strftime("%Y-%m-%dT%H:%M") == "2026-09-24T16:00"
    assert r["ort"] == "Start: Hauptbahnhof"
    assert r["beschreibung_kurz"] == "exklusive Einblicke Fahrrad- und Kanutouren"
    assert r["url"].startswith(
        "https://industriekultur.berlin/festival/veranstaltung/")


def test_mehrwertiger_bezirk_ergibt_den_startbezirk(fixture_dir_industriekultur):
    """`data-festival-bezirk` ist mehrwertig („mitte,pankow") — 4 von 165 Karten.

    Der Bezirksfilter kennt nur einen Bezirk; ohne Regex auf den ersten Wert
    scheiterte der Label-Lookup stumm (bezirk = None).
    """
    rows = _listing_rows(fixture_dir_industriekultur)
    r = next(x for x in rows if x["titel"].startswith("After Work Radtour: Warmes Licht"))
    assert r["bezirk"] == "mitte"
    assert all("," not in (x["bezirk"] or "") for x in rows)


def test_detail_ort_kommt_aus_der_adress_factbox(fixture_dir_industriekultur):
    """Der Detail-Ort ist die Fact-Box „Adresse" — nicht die Folgetermin-Karten.

    Der alte Anker `.bzi-festival-event-card-detail.is-place` trifft auch die
    Karten der „Weitere Termine"-Liste und hängte deren Orte aneinander
    (gemessen live: 7 Orte in einem Wert).
    """
    html = (fixture_dir_industriekultur
            / "detail_alte_verkehrswege.html").read_text(encoding="utf-8")
    d = _adapter().parse_detail(html)
    assert "Start: Hauptbahnhof" in (d.get("ort") or "")
    assert "Bahnhof Spandau" not in (d.get("ort") or ""), d.get("ort")
