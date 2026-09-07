"""Admin: Schulen/Kategorien/manuelle Termine — Store-Ebene (Change 005)."""
from app.model import make_event_id
from app.store import Store


def _store(tmp_path):
    s = Store(tmp_path / "schul_admin.db")
    s.seed_default_sources()
    return s


def _schule(bsn="1001", name="Grundschule Muster"):
    return {"bsn": bsn, "name": name, "schulform": "Grundschule",
            "bezirk": "spandau", "ortsteil": "Haselhorst", "plz": "13599",
            "strasse": "Musterweg 1", "email": "kontakt@beispiel-schule.de",
            "website": "https://beispiel-schule.de"}


def _tag(kid="tdot", name="Tag der offenen Tür"):
    return {"id": kid, "name": name, "farbe": "#2ea043", "sort": 1}


def _termin(schule_bsn="1001", status="ungeprueft", kategorie_id=None):
    t = {"schule_bsn": schule_bsn, "kategorie_id": kategorie_id,
         "titel": "Tag der offenen Tür 2026", "start_datum": "15.10.2026",
         "start_zeit": "16:00", "ort": "Aula", "beschreibung": "Besichtigung",
         "status": status}
    return t


def _event(store, ev_id):
    """Öffentliches Event per ID holen (quelle+source_event_id-Filter)."""
    treffer = store.query_events({"quelle": ["manuell"]})
    for e in treffer:
        if e["id"] == ev_id:
            return e
    return None


# --- Schulen ----------------------------------------------------------------
def test_schule_crud(tmp_path):
    s = _store(tmp_path)
    s.upsert_schule(_schule())
    sch = s.get_schule("1001")
    assert sch["name"] == "Grundschule Muster"
    assert sch["bezirk"] == "spandau"
    # n_termine ist ein list_schulen-Aggregat (nicht Teil von get_schule)
    assert s.list_schulen()[0]["n_termine"] == 0
    # Update
    s.upsert_schule({**_schule(), "name": "Grundschule Neu"})
    assert s.get_schule("1001")["name"] == "Grundschule Neu"
    # Liste + Filter
    s.upsert_schule(_schule("2002", "Gymnasium Beispiel"))
    assert len(s.list_schulen()) == 2
    assert len(s.list_schulen(bezirk="spandau")) == 2
    assert len(s.list_schulen(q="Gymnasium")) == 1
    assert len(s.list_schulen(q="2002")) == 1
    # Pflichtfelder
    try:
        s.upsert_schule({"bsn": "x"})
        assert False
    except ValueError:
        pass
    s.delete_schule("1001")
    assert s.get_schule("1001") is None
    try:
        s.delete_schule("1001")
        assert False
    except ValueError:
        pass
    s.close()


def test_schule_angefragt(tmp_path):
    s = _store(tmp_path)
    s.upsert_schule(_schule())
    assert s.get_schule("1001")["angefragt_am"] is None
    s.set_schule_angefragt("1001", "2026-09-07T12:00:00+02:00")
    assert s.get_schule("1001")["angefragt_am"] == "2026-09-07T12:00:00+02:00"
    s.close()


# --- Tags -------------------------------------------------------------
def test_tag_crud(tmp_path):
    s = _store(tmp_path)
    s.upsert_tag(_tag())
    kat = s.get_tag("tdot")
    assert kat["name"] == "Tag der offenen Tür" and kat["farbe"] == "#2ea043"
    s.upsert_tag({**_tag(), "name": "Infoabend"})
    assert s.get_tag("tdot")["name"] == "Infoabend"
    try:
        s.upsert_tag({"id": "x"})
        assert False
    except ValueError:
        pass
    s.delete_tag("tdot")
    assert s.get_tag("tdot") is None
    try:
        s.delete_tag("tdot")
        assert False
    except ValueError:
        pass
    s.close()


# --- Manuelle Termine: CRUD + Spiegelung ------------------------------------
def test_termin_crud_ungeprueft_kein_spiegel(tmp_path):
    s = _store(tmp_path)
    s.upsert_schule(_schule())
    s.upsert_tag(_tag())
    tid = s.upsert_termin_manuell(_termin(kategorie_id="tdot"))
    t = s.get_termin_manuell(tid)
    assert t["titel"] == "Tag der offenen Tür 2026"
    assert t["schulname"] == "Grundschule Muster"
    assert t["kategorie_name"] == "Tag der offenen Tür"
    assert t["status"] == "ungeprueft"
    # ungeprueft → KEIN öffentliches Event
    assert _event(s, make_event_id("manuell", str(tid))) is None
    # Liste mit Filter
    assert len(s.list_termine_manuell(schule_bsn="1001")) == 1
    assert len(s.list_termine_manuell(status="ungeprueft")) == 1
    assert len(s.list_termine_manuell(status="bestaetigt")) == 0
    # Pflichtfelder
    try:
        s.upsert_termin_manuell({"schule_bsn": "1001", "titel": "ohne Datum"})
        assert False
    except ValueError:
        pass
    try:
        s.upsert_termin_manuell({**_termin(), "status": "quatsch"})
        assert False
    except ValueError:
        pass
    s.delete_termin_manuell(tid)
    assert s.get_termin_manuell(tid) is None
    s.close()


def test_termin_bestaetigt_spiegelt_event(tmp_path):
    s = _store(tmp_path)
    s.upsert_schule(_schule())
    tid = s.upsert_termin_manuell(_termin(status="bestaetigt"))
    ev_id = make_event_id("manuell", str(tid))
    ev = _event(s, ev_id)
    assert ev is not None
    assert ev["quelle"] == "manuell"
    assert ev["titel"] == "Tag der offenen Tür 2026"
    assert ev["ort"] == "Aula"
    assert ev["bezirk"] == "spandau"  # aus der Schule
    assert ev["kostenlos"] == 1
    assert ev["start_local"].startswith("2026-10-15T16:00")
    # Statuswechsel zurück → Spiegel weg
    s.upsert_termin_manuell({**_termin(status="bestaetigt"), "id": tid,
                             "status": "ungeprueft"})
    assert _event(s, ev_id) is None
    s.close()


def test_termin_update_bestaetigt_aktualisiert_spiegel(tmp_path):
    s = _store(tmp_path)
    s.upsert_schule(_schule())
    tid = s.upsert_termin_manuell(_termin(status="bestaetigt"))
    ev_id = make_event_id("manuell", str(tid))
    assert _event(s, ev_id)["titel"] == "Tag der offenen Tür 2026"
    s.upsert_termin_manuell({**_termin(status="bestaetigt"), "id": tid,
                             "titel": "Schnuppertag 2026"})
    ev = _event(s, ev_id)
    assert ev is not None and ev["titel"] == "Schnuppertag 2026"
    # Löschen entfernt den Spiegel
    s.delete_termin_manuell(tid)
    assert _event(s, ev_id) is None
    s.close()


def test_schule_loeschen_cascadet_termine_und_spiegel(tmp_path):
    s = _store(tmp_path)
    s.upsert_schule(_schule())
    tid = s.upsert_termin_manuell(_termin(status="bestaetigt"))
    ev_id = make_event_id("manuell", str(tid))
    assert _event(s, ev_id) is not None
    s.delete_schule("1001")
    assert s.get_schule("1001") is None
    assert s.get_termin_manuell(tid) is None  # FK CASCADE
    assert _event(s, ev_id) is None          # Spiegel aufgeräumt
    s.close()


def test_termin_ganztags_und_ende(tmp_path):
    s = _store(tmp_path)
    s.upsert_schule(_schule())
    t = _termin(status="bestaetigt")
    t.update({"start_zeit": None, "ganztags": 1, "ende_datum": "16.10.2026"})
    tid = s.upsert_termin_manuell(t)
    ev = _event(s, make_event_id("manuell", str(tid)))
    assert ev["ganztags"] == 1
    assert ev["start_local"].endswith("T00:00:00")
    assert ev["ende_local"].startswith("2026-10-16T23:59")
    s.close()
