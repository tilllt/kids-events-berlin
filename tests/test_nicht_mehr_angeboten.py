"""Change 016: nicht mehr angebotene Termine entfernen („zuletzt gesehen").

Realer Anlass: 242 Termine mit Startdatum in der Vergangenheit, die die Quellen
nicht mehr anbieten — sie behielten ihren alten Zustand (Ort „Ohne Angabe",
keine Kartenposition) und erschienen als „Events von gestern" in der Liste.
"""
from datetime import datetime, timedelta

from app.model import TZ_BERLIN, iso_utc, make_event_id
from app.store import Store

QUELLE = "umweltkalender-berlin"


def _ev(store, *, titel, start, ende=None, quelle=QUELLE):
    local = start.strftime("%Y-%m-%dT%H:%M:%S")
    sid = f"{titel}#{local}"
    ev = {
        "id": make_event_id(quelle, sid), "titel": titel, "beschreibung_kurz": "kurz",
        "start_iso": iso_utc(start), "ende_iso": iso_utc(ende) if ende else None,
        "start_local": local,
        "ende_local": ende.strftime("%Y-%m-%dT%H:%M:%S") if ende else None,
        "ganztags": False, "ort": "Ohne Angabe", "adresse": None, "bezirk": None,
        "lat": None, "lon": None, "altersband_min": None, "altersband_max": None,
        "alters_familie": 0, "kategorien": ["workshop"], "kostenlos": None,
        "quelle": quelle, "source_event_id": sid,
        "source_url": "https://example.invalid/x", "geholt_am": start.isoformat(),
    }
    store.upsert_event(ev)
    return ev


def test_nicht_mehr_angeboten_wird_entfernt(tmp_path):
    s = Store(tmp_path / "t.db")
    jetzt = datetime.now(TZ_BERLIN)
    gestern = _ev(s, titel="Gestern weg", start=jetzt - timedelta(days=1))
    laufend = _ev(s, titel="Gestern noch angeboten",
                  start=jetzt - timedelta(days=1), ende=jetzt + timedelta(days=1))
    morgen = _ev(s, titel="Morgen", start=jetzt + timedelta(days=1))
    assert s.count_events() == 3

    # Die Quelle bietet nur noch „laufend" und „morgen" an.
    s.markiere_gesehen(QUELLE, [(laufend["id"], laufend["source_event_id"]),
                                (morgen["id"], morgen["source_event_id"])],
                       jetzt.isoformat())
    weg = s.entferne_nicht_mehr_angeboten(QUELLE, jetzt.isoformat())
    assert weg == 1

    titel = {e["titel"] for e in s.list_events_admin()}
    assert gestern["titel"] not in titel           # nicht gesehen + vergangen → weg
    assert laufend["titel"] in titel               # gestempelt → bleibt
    assert morgen["titel"] in titel                # Zukunft bleibt


def test_fehlerlauf_loescht_nichts(tmp_path):
    """Ein halb gelesenes Listing darf keinen Termin kosten."""
    s = Store(tmp_path / "t.db")
    jetzt = datetime.now(TZ_BERLIN)
    _ev(s, titel="Gestern", start=jetzt - timedelta(days=1))
    weg = s.entferne_nicht_mehr_angeboten(QUELLE, jetzt.isoformat(), ok=False)
    assert weg == 0 and s.count_events() == 1
    # mit ok=True verschwindet er
    assert s.entferne_nicht_mehr_angeboten(QUELLE, jetzt.isoformat()) == 1


def test_stempel_greift_auch_ueber_source_event_id(tmp_path):
    """Nach einer Zusammenführung kann der Satz unter einer anderen id stehen."""
    s = Store(tmp_path / "t.db")
    jetzt = datetime.now(TZ_BERLIN)
    ev = _ev(s, titel="Gestern", start=jetzt - timedelta(days=1))
    s.markiere_gesehen(QUELLE, [("fremd-vergebene-id", ev["source_event_id"])],
                       jetzt.isoformat())
    assert s.entferne_nicht_mehr_angeboten(QUELLE, jetzt.isoformat()) == 0
    assert s.count_events() == 1


def test_migration_ist_wiederholbar(tmp_path):
    """Alte DB: Spalte ergänzen, Bestand als gesehen stempeln — zweimal öffnen."""
    p = tmp_path / "alt.db"
    s1 = Store(p)
    jetzt = datetime.now(TZ_BERLIN)
    _ev(s1, titel="Alt", start=jetzt - timedelta(days=2))
    s1._conn.commit()
    s1.close()
    s2 = Store(p)   # Migration läuft erneut, darf nichts löschen
    assert s2.count_events() == 1
    zeile = s2._conn.execute(
        "SELECT zuletzt_gesehen FROM events").fetchone()
    assert zeile["zuletzt_gesehen"], "Altbestand muss als gesehen gestempelt sein"
    s2.close()
