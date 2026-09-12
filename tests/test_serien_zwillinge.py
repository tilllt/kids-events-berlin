"""Change 008: überlappende Serien-Zwillinge einer Quelle zusammenfassen.

Realer Anlass: jup.berlin führt einen mehrtägigen Ferienworkshop als mehrere,
je um einen Tag verschobene Einträge derselben Spanne → 13 Karteileichen in
Liste und Karte. Echte Serientermine (berührende Slots) dürfen NICHT kollabieren.
"""
from datetime import datetime, timedelta

from app.model import TZ_BERLIN, make_event_id
from app.pipeline import scrape
from app.store import Store

QUELLE = "jup-berlin"


def _ev(quelle: str, titel: str, start: datetime, ende: datetime | None,
        ort: str = "MAXIM, Kinder- und Jugendkulturzentrum", *, manuell: int = 0,
        nummer: int = 0) -> dict:
    """Minimal-Event für den Store (Pflichtfelder + Zeitspalten beide Formen)."""
    occ = start.astimezone(TZ_BERLIN).strftime("%Y%m%dT%H%M")
    seid = f"{titel}#{occ}#{nummer}"
    return {
        "id": make_event_id(quelle, seid),
        "titel": titel,
        "beschreibung_kurz": None,
        "start_iso": start.astimezone(TZ_BERLIN).isoformat(),
        "ende_iso": ende.astimezone(TZ_BERLIN).isoformat() if ende else None,
        "start_local": start.astimezone(TZ_BERLIN).strftime("%Y-%m-%dT%H:%M:%S"),
        "ende_local": (ende.astimezone(TZ_BERLIN).strftime("%Y-%m-%dT%H:%M:%S")
                       if ende else None),
        "ganztags": False,
        "ort": ort,
        "adresse": None,
        "bezirk": None,
        "lat": None,
        "lon": None,
        "kostenlos": None,
        "quelle": quelle,
        "source_event_id": seid,
        "source_url": f"https://jup.berlin/events/{nummer}",
        "geholt_am": datetime(2026, 9, 12, 12, 0, tzinfo=TZ_BERLIN).isoformat(),
        "manuell": manuell,
    }


def _d(tag: int, stunde: int, monat: int = 10) -> datetime:
    return datetime(2026, monat, tag, stunde, 0, tzinfo=TZ_BERLIN)


def test_ueberlappende_ketten_werden_auf_fruehesten_start_reduziert(tmp_path):
    store = Store(tmp_path / "events.db")
    titel = "Wie kommt das Milchhäuschen am Weißen See zu seinem Namen?"
    # 3 verschobene Kopien derselben Spanne (je 5 Tage, Start +1 Tag)
    for i in range(3):
        store.upsert_event(_ev(QUELLE, titel, _d(5 + i, 10), _d(9 + i, 16), nummer=i))

    entfernt = store.entferne_ueberlappende_zwillinge(QUELLE)
    assert len(entfernt) == 2, entfernt
    rest = [e for e in store.query_events({}) if e["titel"] == titel]
    assert len(rest) == 1
    # Der früheste Start (5.10. 10:00) bleibt — das ist der echte Termin.
    assert rest[0]["start_local"] == "2026-10-05T10:00:00"
    # Idempotent: zweiter Aufruf findet nichts mehr.
    assert store.entferne_ueberlappende_zwillinge(QUELLE) == []
    store.close()


def test_beruehrende_slots_sind_keine_dubletten(tmp_path):
    """ZLB-Stundenblöcke (09–10, 10–11 Uhr) dürfen NICHT zusammenfallen."""
    store = Store(tmp_path / "events.db")
    titel = "U-16 Wahllokal für Schulklassen"
    for i, (h1, h2) in enumerate([(9, 10), (10, 11), (11, 12)]):
        store.upsert_event(_ev(QUELLE, titel, _d(8, h1), _d(8, h2), nummer=i))
    assert store.entferne_ueberlappende_zwillinge(QUELLE) == []
    assert len([e for e in store.query_events({}) if e["titel"] == titel]) == 3
    store.close()


def test_verschiedene_orte_bleiben_getrennt(tmp_path):
    store = Store(tmp_path / "events.db")
    titel = "Keramikwerkstatt"
    store.upsert_event(_ev(QUELLE, titel, _d(5, 10), _d(9, 16), ort="Haus A", nummer=1))
    store.upsert_event(_ev(QUELLE, titel, _d(6, 10), _d(10, 16), ort="Haus B", nummer=2))
    assert store.entferne_ueberlappende_zwillinge(QUELLE) == []
    assert len([e for e in store.query_events({}) if e["titel"] == titel]) == 2
    store.close()


def test_manuell_gepflegte_events_bleiben(tmp_path):
    """Admin-Pflege gewinnt: manuell=1 wird nie als Dublette gelöscht."""
    store = Store(tmp_path / "events.db")
    titel = "Ferienworkshop (vom Admin korrigiert)"
    store.upsert_event(_ev(QUELLE, titel, _d(5, 10), _d(9, 16), nummer=1))
    store.upsert_event(_ev(QUELLE, titel, _d(6, 10), _d(10, 16), nummer=2, manuell=1))
    assert store.entferne_ueberlappende_zwillinge(QUELLE) == []
    assert len([e for e in store.query_events({}) if e["titel"] == titel]) == 2
    store.close()


def test_nur_die_gescrapte_quelle_wird_bereinigt(tmp_path):
    store = Store(tmp_path / "events.db")
    titel = "Doppelter Titel"
    store.upsert_event(_ev(QUELLE, titel, _d(5, 10), _d(9, 16), nummer=1))
    store.upsert_event(_ev(QUELLE, titel, _d(6, 10), _d(10, 16), nummer=2))
    store.upsert_event(_ev("zlb", titel, _d(5, 10), _d(9, 16), nummer=3))
    store.upsert_event(_ev("zlb", titel, _d(6, 10), _d(10, 16), nummer=4))
    entfernt = store.entferne_ueberlappende_zwillinge(QUELLE)
    assert len(entfernt) == 1
    assert len([e for e in store.query_events({}) if e["quelle"] == "zlb"]) == 2
    store.close()


def test_pipeline_raeumt_altlasten_und_meldet_sie(tmp_path, listing_p0, listing_p1,
                                                  detail_fam, detail_raetsel):
    """Offline-Lauf räumt vorhandene Kopien weg und meldet die Zahl."""
    store = Store(tmp_path / "events.db")
    store.seed_default_sources()
    titel = "Ferienworkshop mit überlappenden Quell-Einträgen"
    for i in range(3):
        store.upsert_event(_ev(QUELLE, titel, _d(5 + i, 10), _d(9 + i, 16), nummer=i))
    assert len([e for e in store.query_events({}) if e["titel"] == titel]) == 3

    jetzt = datetime(2026, 9, 4, 12, 0, tzinfo=TZ_BERLIN)
    summary = scrape(store, online=False,
                     listing_htmls=[listing_p0, listing_p1],
                     detail_html={"familiensportfest": detail_fam,
                                  "raetselabenteuer-berlin-prenzlauer-berg": detail_raetsel},
                     jetzt=jetzt)
    assert summary["n_fehler"] == 0
    assert summary["n_zwillinge_entfernt"] == 2, summary
    assert len([e for e in store.query_events({}) if e["titel"] == titel]) == 1
    # Regressionsschutz: echte Fixture-Events bleiben vollständig vorhanden.
    assert len([e for e in store.query_events({})
                if e["titel"] != titel]) >= 5
    store.close()
