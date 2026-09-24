r"""Quelle Wochenmärkte & Flohmärkte Berlin (wochenmarkt-flohmarkt.de).

Anlass (Nutzerauftrag 2026-09-24): „füge diese termine zu den quellen hinzu:
https://www.wochenmarkt-flohmarkt.de/". Joomla + JEvents (com_jevents).

Die zwei Fallen, die dieser Test festnagelt:

1. **Uhrzeit.** Die Listenzeile (`div.jev_listrow`) nennt die Zeit nur als
   Fließtext — „Dienstag, 01. September 2026 10:00 - 16:00". Ein
   `format: '%d. %B %Y %H:%M'` wäre eine Falle: `datetime.strptime` liest
   Monatsnamen in der C-Locale, deutsche Namen scheitern ab „März/Mai/Oktober/
   Dezember" (im Projekt ist kein `setlocale` gesetzt). Verlässlich ist der
   maschinenlesbare Google-Kalender-Link JEDER Zeile
   (`dates=20260901T100000/20260901T160000`) — gemessen 2026-09-24: 100 von
   100 Zeilen der Übersicht tragen ihn.

2. **Blättern.** Die Engine zählt `pagination.param` je Seite um 1 hoch
   (`start=0,1,2…`), die Seite blättert in 100er-Schritten. Ein
   `pagination: {param: start}` liefe deshalb bis 2028 durch (gemessen: Seite 3
   endet am 22.04.2028) — rund 20 Seiten à 1,7 MB je Lauf.
"""
from datetime import datetime
from pathlib import Path

from app.adapters.selector_adapter import SelectorAdapter
from app.model import TZ_BERLIN
from app.quellen_defaults import WOCHENMARKT_FLOHMARKT_REGELN
from app.regeln import validate_regeln_yaml

QUELLE = "wochenmarkt-flohmarkt"
FIXTURES = Path(__file__).parent / "fixtures" / "wochenmarkt"


def _adapter() -> SelectorAdapter:
    return SelectorAdapter(QUELLE, regel_yaml=WOCHENMARKT_FLOHMARKT_REGELN)


def _listing() -> str:
    return (FIXTURES / "listing_kategorie.html").read_text(encoding="utf-8")


def _detail() -> str:
    return (FIXTURES / "detail_marheinekeplatz.html").read_text(encoding="utf-8")


def test_regeln_sind_pruefbar():
    assert validate_regeln_yaml(WOCHENMARKT_FLOHMARKT_REGELN, QUELLE) == []


def test_kein_start_blaettern():
    """`pagination: {param: start}` würde bis 2028 durchlaufen (s. Modulkopf)."""
    import yaml
    doc = yaml.safe_load(WOCHENMARKT_FLOHMARKT_REGELN)
    assert "pagination" not in (doc["listing"] or {}), doc["listing"]
    assert "limit=100" in WOCHENMARKT_FLOHMARKT_REGELN


def test_listing_zeilen_werden_gelesen():
    rows = _adapter().parse_listing(_listing())
    assert len(rows) == 3, rows
    assert all(r["titel"] for r in rows), rows
    assert all(r["url"].endswith(r["slug"]) for r in rows), rows
    assert all(r["url"].startswith("https://www.wochenmarkt-flohmarkt.de/eventdetail/")
               for r in rows), rows


def test_uhrzeit_kommt_aus_dem_kalender_link():
    """10:00 und 16:00 — NICHT 00:00 (das wäre „ganztägig" in der App)."""
    rows = {r["titel"]: r for r in _adapter().parse_listing(_listing())}
    r = rows["Samstag Trödelmarkt Bergmannstraße Marheinekeplatz"]
    assert r["start"] == datetime(2026, 9, 1, 10, 0, tzinfo=TZ_BERLIN)
    assert r["ende"] == datetime(2026, 9, 1, 16, 0, tzinfo=TZ_BERLIN)
    assert not r["ganztags"], r


def test_deutscher_monatsname_ist_keine_falle():
    """Der Beweis, dass die Zeit NICHT aus dem Fließtext kommt.

    Der Fließtext wird auf „Oktober" umgeschrieben (der Google-Link bleibt, wie
    er ist). Kommt die Zeit weiterhin richtig heraus, liest die Regel den
    Kalender-Link. Wer sie später auf `%B` umstellt, fällt hier auf: `%B` kennt
    kein „Oktober" in der C-Locale — und für „März", „Mai" und „Dezember"
    (Jahreswechsel) ebenso wenig.
    """
    html = _listing().replace("01. September 2026", "01. Oktober 2026")
    assert "01. Oktober 2026" in html
    rows = {r["titel"]: r for r in _adapter().parse_listing(html)}
    r = rows["Samstag Trödelmarkt Bergmannstraße Marheinekeplatz"]
    assert r["start"] == datetime(2026, 9, 1, 10, 0, tzinfo=TZ_BERLIN)


def test_ganztags_termin_bleibt_ganztags():
    """„Berliner Kunstmarkt an der Museumsinsel" startet in der Quelle um 00:00 —
    das darf die Regel nicht zu 10:00 o. Ä. erfinden."""
    rows = {r["titel"]: r for r in _adapter().parse_listing(_listing())}
    r = rows["Berliner Kunstmarkt an der Museumsinsel"]
    assert r["start"].hour == 0 and r["start"].minute == 0, r


def test_ohne_kalender_link_kein_start():
    """Fehlt der Google-Link, gibt es KEINE erfundene Uhrzeit — die Zeile fällt
    raus und der Lauf meldet eine Warnung (kein stiller Fehler)."""
    a = _adapter()
    html = _listing().replace("google.com/calendar", "example.invalid/kalender")
    rows = a.parse_listing(html)
    assert rows == [] or all(r.get("start") is None for r in rows), rows
    assert a.drain_warnungen(), "fehlender Kalender-Link muss gewarnt werden"


def test_ort_und_adresse_aus_der_detailseite():
    """Der Ortsblock ist mit <br/> getrennt: Zeile 1 = Ort, Zeile 2 = Straße."""
    d = _adapter().parse_detail(_detail())
    assert d["ort"] == "Trödelmarkt Bergmannstraße Marheinekeplatz", d
    assert d["adresse"] == "Marheinekeplatz", d


def test_live_regel_traegt_dieselben_felder():
    """Der Repo-Stand ist die Vorlage für die Live-Regel — die tragenden
    Selektoren müssen drinstehen (sie wurden live gegengeprüft)."""
    for stelle in ("jev_listrow", "a.ev_link_row", "google.com/calendar",
                   "jev-detail__address", "eventsnachkategorie"):
        assert stelle in WOCHENMARKT_FLOHMARKT_REGELN, stelle
