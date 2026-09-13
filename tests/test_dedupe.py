"""Change 011: Dubletten über Quellen hinweg — inklusive der Schutzfälle.

Realer Anlass: ein Tag der offenen Tür stand 57× im Bestand (29× familienportal,
28× Kinderkulturkalender). Ebenso real: das ZLB bietet am selben Ort zur selben
Zeit VERSCHIEDENE Veranstaltungen an — die dürfen nicht zusammenfallen.
"""
import json
from datetime import datetime

from app import dedupe
from app.model import TZ_BERLIN, make_event_id
from app.store import Store


def _ev(quelle, titel, start_local, *, ende=None, ort=None, lat=None, lon=None,
        manuell=0, beschreibung=None, nummer=0, sid=None):
    seid = sid or f"{titel}#{start_local}#{quelle}#{nummer}"
    return {
        "id": make_event_id(quelle, seid), "titel": titel,
        "beschreibung_kurz": beschreibung,
        "start_iso": start_local, "ende_iso": ende,
        "start_local": start_local, "ende_local": ende,
        "ganztags": False, "ort": ort, "adresse": None, "bezirk": None,
        "lat": lat, "lon": lon, "altersband_min": None, "altersband_max": None,
        "alters_familie": 0, "kategorien": [], "kostenlos": None,
        "quelle": quelle, "source_event_id": seid,
        "source_url": f"https://{quelle}.example.org/{nummer}",
        "geholt_am": datetime.now(TZ_BERLIN).isoformat(), "manuell": manuell,
    }


# --- Normalisierung --------------------------------------------------------
def test_titel_und_ort_normalisierung():
    assert dedupe.titel_norm("Tag der offenen Tür – Klax!") == "tag der offenen tuer klax"
    assert dedupe.titel_norm("TAG  der   OFFENEN") == "tag der offenen"
    assert dedupe.ort_norm("Klax Kinderkrippe Mäusekiste, Berlin") == "klax kinderkrippe maeusekiste"
    assert dedupe.ist_generisch("Berlin") and dedupe.ist_generisch("") and dedupe.ist_generisch(None)
    assert not dedupe.ist_generisch("Zeiss-Großplanetarium")


def test_meter_abstand():
    a = {"lat": 52.5019, "lon": 13.5701}
    b = {"lat": 52.5020, "lon": 13.5702}
    assert 0 < dedupe.meter_abstand(a, b) < 50
    weit = {"lat": 52.4572, "lon": 13.5260}  # Archenhold vs. Zeiss-Großplanetarium
    assert dedupe.meter_abstand(a, weit) > 5000
    assert dedupe.meter_abstand({"lat": None, "lon": None}, a) is None


# --- Identitätsregeln ------------------------------------------------------
def test_klax_fall_wird_als_gleiche_veranstaltung_erkannt():
    """familienportal vs. Kinderkulturkalender: Titel/Datum/Zeit gleich, Ort einmal generisch."""
    fam = _ev("familienportal", "Tag der offenen Tür in der Klax Kinderkrippe Mäusekiste",
              "2026-09-26T10:00:00", ort="Klax Kinderkrippe Mäusekiste",
              lat=52.50194558105659, lon=13.57007423113423)
    kkk = _ev("kinderkulturkalender", "Tag der offenen Tür in der Klax Kinderkrippe Mäusekiste",
              "2026-09-26T10:00:00", ende="2026-09-26T15:00:00", ort="Berlin",
              lat=52.50194558105659, lon=13.57007423113423)
    gleich, grund = dedupe.gleiche_veranstaltung(fam, kkk)
    assert gleich, grund
    # Kanon: amtliche Quelle schlägt Aggregator
    assert dedupe.waehle_kanon([kkk, fam])["quelle"] == "familienportal"
    # Die abweichende Endzeit ist die einzige echte Zusatzinformation
    assert dedupe.fehlende_felder(fam, kkk) == {"ende_local": "2026-09-26T15:00:00",
                                                "ende_iso": "2026-09-26T15:00:00"}


def test_zlb_verschiedene_veranstaltungen_gleicher_ort_gleiche_zeit():
    """Das ZLB bietet am selben Ort zur selben Zeit anderes Programm — kein Merge."""
    a = _ev("zlb", "Vorlesestunde für Kinder", "2026-10-02T16:00:00", ort="ZLB Berlin",
            lat=52.4675, lon=13.3900)
    b = _ev("zlb", "Wahllokal für Schulklassen", "2026-10-02T16:00:00", ort="ZLB Berlin",
            lat=52.4675, lon=13.3900)
    gleich, grund = dedupe.gleiche_veranstaltung(a, b)
    assert not gleich and grund == "anderer_titel"
    assert dedupe.finde_dubletten([a, b])["entfernbar"] == 0


def test_zlb_stundenbloecke_gleicher_titel_bleiben_getrennt():
    """Gleicher Titel, gleicher Ort, aber Stundenblöcke 09/10/11 Uhr sind echte Slots."""
    slots = [_ev("zlb", "Führung durch die Bibliothek", f"2026-10-02T0{h}:00:00",
                 ort="ZLB Berlin", lat=52.4675, lon=13.39, nummer=h)
             for h in (9, 10, 11)]
    bericht = dedupe.finde_dubletten(slots)
    assert bericht["entfernbar"] == 0
    assert {v["grund"] for v in bericht["verdacht"]} == {"andere_uhrzeit"}


def test_gleicher_titel_an_zwei_orten_bleibt_getrennt():
    """„Sternstunde“ läuft in zwei Sternwarten am selben Tag — zwei Veranstaltungen."""
    a = _ev("museumsportal", "Sternstunde", "2026-09-10T18:00:00",
            ort="Archenhold-Sternwarte", lat=52.4572, lon=13.5260, nummer=1)
    b = _ev("museumsportal", "Sternstunde", "2026-09-10T18:00:00",
            ort="Zeiss-Großplanetarium", lat=52.5420, lon=13.5880, nummer=2)
    # Der Ortsname entscheidet VOR den Koordinaten (gleiches Gebäude, zwei Einrichtungen)
    assert dedupe.gleiche_veranstaltung(a, b) == (False, "anderer_ort_name")
    # Gleicher Name, aber weit auseinander: zwei Standorte derselben Einrichtung
    weit = dict(b, ort="Archenhold-Sternwarte")
    assert dedupe.gleiche_veranstaltung(a, weit) == (False, "anderer_ort_koordinaten")
    # Namensteil-Verhältnis gilt als derselbe Ort (Kurzform vs. Langform)
    kurz = dict(b, ort="Sternwarte Archenhold")
    assert dedupe.gleiche_veranstaltung(a, kurz)[0] is False  # anderer Ortsname bleibt anders
    
    # Kurz-/Langform derselben Einrichtung = derselbe Ort
    lang = _ev("museumsportal", "Sternstunde", "2026-09-10T18:00:00",
               ort="Zeiss-Großplanetarium Berlin", lat=52.5420, lon=13.5880, nummer=3)
    kurz2 = _ev("zlb", "Sternstunde", "2026-09-10T18:00:00",
                ort="Zeiss-Großplanetarium", lat=52.5420, lon=13.5880, nummer=4)
    assert dedupe.gleiche_veranstaltung(lang, kurz2)[0] is True


def test_fehlende_zeit_ist_kein_hindernis():
    a = _ev("familienportal", "Sommerfest", "2026-09-20T15:00:00", ort="Schule X",
            lat=52.5, lon=13.4)
    b = _ev("jup-berlin", "Sommerfest", "2026-09-20T00:00:00", ort="Berlin",
            lat=52.5, lon=13.4)
    b["ganztags"] = True
    b["start_local"] = "2026-09-20T00:00:00"
    gleich, grund = dedupe.gleiche_veranstaltung(a, b)
    assert gleich, grund


def test_anderer_tag_wird_nie_gemergt():
    a = _ev("a-quelle", "Ferienworkshop", "2026-09-20T10:00:00", ort="Ort X",
            lat=52.5, lon=13.4)
    b = _ev("b-quelle", "Ferienworkshop", "2026-09-21T10:00:00", ort="Ort X",
            lat=52.5, lon=13.4)
    assert dedupe.gleiche_veranstaltung(a, b) == (False, "anderer_tag")


# --- Zusammenführen im Store ----------------------------------------------
def _direkt_einfuegen(store, ev):
    """Altbestand simulieren: Zeile am Write-Path vorbei einfügen.

    `upsert_event` kanonisiert kategorien/manuell vor dem Schreiben — wer direkt
    insertet, muss das selbst tun (sonst bindet SQLite eine Liste nicht).
    """
    ev = dict(ev)
    ev["kategorien"] = json.dumps(ev.get("kategorien") or [], ensure_ascii=False)
    ev["manuell"] = int(bool(ev.get("manuell")))
    store._conn.execute(
        """INSERT INTO events (id, titel, beschreibung_kurz, start_iso, ende_iso,
           start_local, ende_local, ganztags, ort, adresse, bezirk, lat, lon,
           altersband_min, altersband_max, alters_familie, kategorien, kostenlos,
           quelle, source_event_id, source_url, geholt_am, status, manuell, quellen_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        store._ev_tuple({**ev, "quellen_json": None}))
    store._conn.commit()


def _klax_paar(store):
    fam = _ev("familienportal", "Tag der offenen Tür in der Klax Kinderkrippe Mäusekiste",
              "2026-09-26T10:00:00", ort="Klax Kinderkrippe Mäusekiste",
              lat=52.50194558105659, lon=13.57007423113423, beschreibung="Programm")
    kkk = _ev("kinderkulturkalender", "Tag der offenen Tür in der Klax Kinderkrippe Mäusekiste",
              "2026-09-26T10:00:00", ende="2026-09-26T15:00:00", ort="Berlin",
              lat=52.50194558105659, lon=13.57007423113423, nummer=2)
    store.upsert_event(fam)
    store.upsert_event(kkk)


def test_klax_dublette_kommt_gar_nicht_erst_in_die_datenbank(tmp_path):
    """Die strukturelle Invariante: gleiche Veranstaltung, zwei Quellen → eine Zeile."""
    store = Store(tmp_path / "klax.db")
    _klax_paar(store)
    events = store.query_events({})
    assert len(events) == 1, [e["titel"] for e in events]
    e = events[0]
    assert e["quelle"] == "familienportal"          # amtliche Quelle bleibt
    assert e["ende_local"] == "2026-09-26T15:00:00"  # Feld aus der Dublette ergänzt
    quellen = json.loads(e["quellen_json"])
    assert [q["quelle"] for q in quellen] == ["kinderkulturkalender"]
    assert quellen[0]["source_url"].startswith("https://kinderkulturkalender")
    # Zweiter Lauf findet nichts mehr (idempotent)
    assert store.merge_doppelte_events()["entfernbar"] == 0
    store.close()


def test_wiederholte_laeufe_erzeugen_keine_79_zeilen(tmp_path):
    """79-fach-Schutz: dieselbe Veranstaltung 12× aus 3 Quellen → 1 Zeile."""
    store = Store(tmp_path / "viele.db")
    titel = "Tag der offenen Tür der Klax Kinderkrippe"
    for quelle in ("familienportal", "kinderkulturkalender", "jup-berlin"):
        for i in range(4):
            store.upsert_event(_ev(quelle, titel, "2026-09-26T10:00:00",
                                   ort="Klax Kinderkrippe" if i % 2 else "Berlin",
                                   lat=52.5019, lon=13.5701, nummer=i,
                                   sid=f"{titel}#{quelle}#{i}"))
    events = store.query_events({})
    assert len(events) == 1
    # Provenienz: ein Eintrag je weiterer Quelle (nicht je Wiederholung)
    assert [q["quelle"] for q in json.loads(events[0]["quellen_json"])] == \
        ["kinderkulturkalender", "jup-berlin"]
    store.close()


def test_merge_doppelte_events_raeumt_bestand_auf(tmp_path):
    """Bestandsdaten (vor dem Fix entstanden) werden bereinigt — mit Bericht."""
    store = Store(tmp_path / "bestand.db")
    titel = "Ferienprogramm"
    for nummer, quelle in enumerate(("museumsportal", "familienportal", "kinderkulturkalender")):
        ev = _ev(quelle, titel, "2026-10-05T10:00:00", ort="Museum X",
                 lat=52.5, lon=13.4, nummer=nummer)
        _direkt_einfuegen(store, ev)  # am Write-Path vorbei = Altbestand
    assert len(store.query_events({})) == 3

    probelauf = store.merge_doppelte_events(dry_run=True)
    assert probelauf["entfernbar"] == 2 and len(store.query_events({})) == 3

    erg = store.merge_doppelte_events()
    assert erg["entfernt"] == 2 and erg["gruppen"] == 1
    events = store.query_events({})
    assert len(events) == 1 and events[0]["quelle"] == "familienportal"  # Prio 1
    assert len(json.loads(events[0]["quellen_json"])) == 2
    store.close()


def test_manuell_gepflegte_datensaetze_bleiben(tmp_path):
    store = Store(tmp_path / "manuell.db")
    titel = "Jahresfest"
    store.upsert_event(_ev("zlb", titel, "2026-10-05T10:00:00", ort="ZLB Berlin",
                           lat=52.4675, lon=13.39))
    ev = _ev("familienportal", titel, "2026-10-05T10:00:00", ort="ZLB Berlin",
             lat=52.4675, lon=13.39, manuell=1, nummer=3)
    _direkt_einfuegen(store, ev)
    erg = store.merge_doppelte_events()
    ids = {e["id"] for e in store.query_events({})}
    assert ev["id"] in ids, "manuell gepflegter Datensatz wurde entfernt"
    assert erg["entfernt"] == 1  # nur der Scrape-Zwilling
    store.close()


def test_felder_des_kanons_werden_nicht_ueberschrieben(tmp_path):
    store = Store(tmp_path / "felder.db")
    titel = "Konzert"
    store.upsert_event(_ev("familienportal", titel, "2026-10-05T19:00:00", ort="Haus X",
                           lat=52.5, lon=13.4, ende="2026-10-05T21:00:00",
                           beschreibung="amtliche Beschreibung"))
    store.upsert_event(_ev("kinderkulturkalender", titel, "2026-10-05T19:00:00", ort="Haus X",
                           lat=52.5, lon=13.4, ende="2026-10-05T23:00:00",
                           beschreibung="andere Beschreibung", nummer=2))
    e = store.query_events({})[0]
    assert e["ende_local"] == "2026-10-05T21:00:00" and e["beschreibung_kurz"] == "amtliche Beschreibung"
    store.close()


def test_schluessel_nach_unten_schlaegt_aggregator(tmp_path):
    """Kommt die bessere Quelle später, wird sie kanonisch — Provenienz wandert mit."""
    store = Store(tmp_path / "prio.db")
    titel = "Theaterwerkstatt"
    store.upsert_event(_ev("kinderkulturkalender", titel, "2026-10-05T15:00:00",
                           ort="Haus Y", lat=52.5, lon=13.4))
    store.upsert_event(_ev("familienportal", titel, "2026-10-05T15:00:00",
                           ort="Haus Y", lat=52.5, lon=13.4, nummer=2))
    events = store.query_events({})
    assert len(events) == 1 and events[0]["quelle"] == "familienportal"
    assert json.loads(events[0]["quellen_json"])[0]["quelle"] == "kinderkulturkalender"
    store.close()
