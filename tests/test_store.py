"""Store: Idempotenz, Filter (Bezirk/Alter/Uhrzeit), Prune."""
from datetime import datetime, timedelta

from app.model import TZ_BERLIN, iso_utc, make_event_id
from app.store import Store


def _ev(store, *, titel="Test-Event", start=None, ort="Ort X", bezirk=None,
        band=None, ganztags=False, quelle="jup-berlin"):
    start = start or datetime.now(TZ_BERLIN).replace(hour=10, minute=0, second=0, microsecond=0)
    ende = start + timedelta(hours=2)
    local = start.strftime("%Y-%m-%dT%H:%M:%S")
    sid = f"{titel}#{local}"
    ev = {
        "id": make_event_id(quelle, sid), "titel": titel, "beschreibung_kurz": "kurz",
        "start_iso": iso_utc(start), "ende_iso": iso_utc(ende), "start_local": local,
        "ende_local": ende.strftime("%Y-%m-%dT%H:%M:%S"), "ganztags": ganztags,
        "ort": ort, "adresse": None, "bezirk": bezirk, "lat": 52.5, "lon": 13.4,
        "altersband_min": band[0] if band else None,
        "altersband_max": band[1] if band else None, "alters_familie": 0,
        "kategorien": ["workshop"], "kostenlos": True, "quelle": quelle,
        "source_event_id": sid, "source_url": f"https://jup.berlin/events/x",
        "geholt_am": datetime.now(TZ_BERLIN).isoformat(),
    }
    store.upsert_event(ev)
    return ev


def test_upsert_idempotent(tmp_path):
    s = Store(tmp_path / "t.db")
    ev = _ev(s)  # _ev fügt bereits ein
    assert s.count_events() == 1
    neu2, geaendert2 = s.upsert_event(ev)
    assert neu2 is False and geaendert2 is False
    assert s.count_events() == 1


def test_upsert_zwilling_uebernimmt(tmp_path):
    """ID-Schema-Wechsel: gleicher Inhalt unter neuer ID ersetzt den alten
    Eintrag statt ein Duplikat anzulegen."""
    from app.model import make_event_id
    s = Store(tmp_path / "t.db")
    ev = _ev(s, titel="Staudenmarkt 2026")
    # „Neue“ Version desselben Events: andere ID (z. B. URL-Slug statt Hash)
    alt = s.query_events({})[0]
    neu = dict(ev)
    neu["id"] = make_event_id("jup-berlin", "staudenmarkt-2026#20260906T0900")
    neu["source_event_id"] = "staudenmarkt-2026#20260906T0900"
    neu["source_url"] = "https://example.org/de/veranstaltungen/staudenmarkt-2026/"
    neu2, geaendert2 = s.upsert_event(neu)
    assert neu2 is False and geaendert2 is True
    rows = s.query_events({})
    assert len(rows) == 1, f"Duplikat trotz Zwilling-Übernahme: {len(rows)}"
    assert rows[0]["id"] == neu["id"]
    assert rows[0]["source_url"].endswith("staudenmarkt-2026/")
    assert s.count_events() == 1


def test_upsert_zwilling_nur_bei_gleichem_ort(tmp_path):
    """Gleicher Titel + Start an verschiedenen Orten bleibt zwei Events."""
    from app.model import make_event_id
    s = Store(tmp_path / "t.db")
    ev1 = _ev(s, titel="Familiensportfest", ort="Ort A")
    ev2 = _ev(s, titel="Familiensportfest", ort="Ort B")
    # _ev leitet die ID aus Titel ab → zweite ID explizit unterscheiden
    ev2["id"] = make_event_id("jup-berlin", ev2["source_event_id"] + "-b")
    ev2["source_event_id"] = ev2["source_event_id"] + "-b"
    s.upsert_event(ev2)
    assert s.count_events() == 2


def test_filter_bezirk_und_altersband(tmp_path):
    s = Store(tmp_path / "t.db")
    _ev(s, titel="A", bezirk="neukoelln", band=(4, 6))
    _ev(s, titel="B", bezirk="pankow", band=(10, 14))
    _ev(s, titel="C", bezirk=None, band=None)
    r = s.query_events({"bezirk": ["neukoelln"]})
    assert [e["titel"] for e in r] == ["A"]
    r = s.query_events({"altersband": [(7, 10, False)]})
    # Event B (10–14) überlappt Band 7–10 bei Alter 10; A (4–6) nicht; C ohne Angabe nicht.
    assert {e["titel"] for e in r} == {"B"}
    r = s.query_events({"altersband": [(4, 6, False), (10, 10, False)]})
    assert {e["titel"] for e in r} == {"A", "B"}


def test_filter_uhrzeit_bands_lokal(tmp_path):
    """Nachmittags-Event (15:00 lokal = 13:00 UTC) muss unter 'nachmittag' liegen."""
    s = Store(tmp_path / "t.db")
    start = datetime(2026, 9, 12, 15, 0, tzinfo=TZ_BERLIN)
    _ev(s, titel="Nachmittag", start=start)
    _ev(s, titel="Ganztags", start=start.replace(hour=0), ganztags=True)
    r = s.query_events({"uhrzeit": ["nachmittag"]})
    assert {e["titel"] for e in r} == {"Nachmittag", "Ganztags"}
    r = s.query_events({"uhrzeit": ["abend"]})
    assert {e["titel"] for e in r} == {"Ganztags"}


def test_filter_datum_von_bis(tmp_path):
    s = Store(tmp_path / "t.db")
    _ev(s, titel="Heute", start=datetime.now(TZ_BERLIN))
    alt = datetime.now(TZ_BERLIN) + timedelta(days=60)
    _ev(s, titel="Spaeter", start=alt)
    r = s.query_events({"von": alt.strftime("%Y-%m-%d"), "bis": alt.strftime("%Y-%m-%d")})
    assert [e["titel"] for e in r] == ["Spaeter"]


def test_prune_stale(tmp_path):
    s = Store(tmp_path / "t.db")
    alt = datetime.now(TZ_BERLIN) - timedelta(days=30)
    _ev(s, titel="Alt", start=alt)
    _ev(s, titel="Neu")
    n = s.prune_stale("jup-berlin", iso_utc(datetime.now(TZ_BERLIN) - timedelta(days=3)))
    assert n == 1
    assert s.count_events() == 1
