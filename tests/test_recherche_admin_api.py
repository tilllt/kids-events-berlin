"""Change 010: Admin-Endpunkte für LLM-Endpunkt und Recherche."""
import json

import pytest
from fastapi.testclient import TestClient

from app.recherche import llm
from app.store import Store


def _client(tmp_path):
    store = Store(tmp_path / "rec_api.db")
    store.seed_default_sources()
    from app.main import app
    app.state.store = store
    return TestClient(app), store


def _schule(store, bsn="02G32", name="Grundschule im Eliashof",
            website="https://www.grundschule-im-eliashof.de"):
    store.upsert_schule({"bsn": bsn, "name": name, "schulform": "Grundschule",
                         "bezirk": "friedrichshain-kreuzberg", "website": website})


# --- Einstellungen ---------------------------------------------------------
def test_llm_einstellungen_speichern_und_lesen(tmp_path):
    c, store = _client(tmp_path)
    # Standard kommt aus dem Client (KI-Box), nicht aus der DB
    d = c.get("/api/admin/llm").json()
    assert d["llm_base_url"] == llm.STANDARD["llm_base_url"]
    assert d["llm_api_key_gesetzt"] is False
    assert "llm_api_key" not in d  # Key wird nie ausgeliefert

    r = c.put("/api/admin/settings", json={
        "llm_base_url": "https://litellm.n0ne.de/v1", "llm_model": "kibox/gemma-4-12b",
        "llm_api_key": "geheim", "llm_timeout_s": "60",
        "llm_extra_json": "{}", "recherche_aktiv": "1", "recherche_max_schulen": "30"})
    assert r.status_code == 200, r.text
    d = c.get("/api/admin/llm").json()
    assert d["llm_base_url"] == "https://litellm.n0ne.de/v1"
    assert d["llm_model"] == "kibox/gemma-4-12b" and d["llm_api_key_gesetzt"] is True
    assert store.get_setting("recherche_aktiv") == "1"
    assert c.get("/api/admin/recherche").json()["max_schulen"] == 30
    store.close()


def test_ungueltige_llm_einstellungen_werden_abgelehnt(tmp_path):
    c, store = _client(tmp_path)
    for body, erwartet in (
        ({"llm_base_url": "127.0.0.1:8088/v1"}, "http://"),
        ({"llm_timeout_s": "1"}, "5 und 600"),
        ({"llm_extra_json": "{kaputt"}, "JSON-Objekt"),
        ({"llm_extra_json": '["liste"]'}, "JSON-Objekt"),
        ({"recherche_max_schulen": "0"}, "1 und 722"),
        ({"gibt_es_nicht": "1"}, "Unbekannte Einstellung"),
    ):
        r = c.put("/api/admin/settings", json=body)
        assert r.status_code == 422, body
        assert any(erwartet in f for f in r.json()["detail"]["fehler"]), (body, r.json())
    store.close()


def test_llm_test_endpunkt_mit_abgeschaltetem_netz(tmp_path, monkeypatch):
    c, store = _client(tmp_path)
    monkeypatch.setattr(llm, "test_verbindung",
                        lambda k, client=None: {"ok": False, "fehler": "kein Netz",
                                                "basis_url": k["llm_base_url"]})
    d = c.post("/api/admin/llm/test", json={}).json()
    assert d["ok"] is False and d["fehler"] == "kein Netz"
    # Feldwerte überschreiben die gespeicherten Einstellungen
    d2 = c.post("/api/admin/llm/test",
                json={"llm_base_url": "http://127.0.0.1:8088/v1"}).json()
    assert d2["basis_url"] == "http://127.0.0.1:8088/v1"
    store.close()


def test_llm_test_erfolg_liefert_antwort_und_modell(tmp_path, monkeypatch):
    c, store = _client(tmp_path)
    monkeypatch.setattr(llm, "test_verbindung", lambda k, client=None: {
        "ok": True, "dauer_s": 0.7, "modell": "llamacpp-gemma4-12B-unsloth",
        "basis_url": k["llm_base_url"], "antwort": '{"ok": true}', "json_erkannt": True})
    d = c.post("/api/admin/llm/test", json={}).json()
    assert d["ok"] and d["json_erkannt"] and d["dauer_s"] == 0.7
    store.close()


# --- Recherche -------------------------------------------------------------
def test_recherche_uebersicht_zeigt_schulen_und_stand(tmp_path):
    c, store = _client(tmp_path)
    _schule(store)
    store.upsert_schule({"bsn": "02G33", "name": "Schule ohne Website"})
    d = c.get("/api/admin/recherche").json()
    assert [s["bsn"] for s in d["schulen"]] == ["02G32"]  # ohne Website ausgeblendet
    assert d["schulen"][0]["recherche_status"] is None and d["lauf_aktiv"] is False
    store.set_schule_recherche("02G32", "gefunden", "1 belegt / 1 roh")
    d2 = c.get("/api/admin/recherche").json()
    assert d2["schulen"][0]["recherche_status"] == "gefunden"
    assert len(c.get("/api/admin/recherche?nur_ohne_fund=true").json()["schulen"]) == 0
    store.close()


def test_recherche_lauf_startet_und_schreibt_letzten_lauf(tmp_path, monkeypatch):
    c, store = _client(tmp_path)
    _schule(store)
    gesehen = {}

    def fake_lauf(store_, *, limit, nur_bsn, dry_run, bezirk=None, schulform=None,
                  bsn_liste=None):
        gesehen.update(limit=limit, nur_bsn=nur_bsn, dry_run=dry_run,
                       bezirk=bezirk, schulform=schulform)
        return {"geprueft": 1, "belegt": 1, "llm_calls": 1, "verworfen": {},
                "fehler": 0, "status": {"gefunden": 1}, "dauer_s": 3.2,
                "limit": limit, "dry_run": dry_run, "schulen": []}

    from app.recherche import kern
    monkeypatch.setattr(kern, "lauf", fake_lauf)
    r = c.post("/api/admin/recherche/lauf", json={"limit": 7, "dry_run": True})
    assert r.status_code == 202, r.text
    assert r.json()["limit"] == 7 and r.json()["dry_run"] is True
    # Der Thread schreibt den Lauf in die Einstellungen
    import time
    for _ in range(50):
        if store.get_setting("recherche_letzter_lauf"):
            break
        time.sleep(0.05)
    d = c.get("/api/admin/recherche/letzter-lauf").json()
    assert d["vorhanden"] and d["belegt"] == 1 and d["dry_run"] is True
    assert gesehen == {"limit": 7, "nur_bsn": None, "dry_run": True,
                       "bezirk": None, "schulform": None}
    store.close()


def test_recherche_lauf_reicht_bezirk_und_schulform_durch(tmp_path, monkeypatch):
    c, store = _client(tmp_path)
    _schule(store)
    gesehen = {}

    def fake_lauf(store_, **kw):
        gesehen.update(kw)
        return {"geprueft": 0, "belegt": 0, "llm_calls": 0, "verworfen": {}, "fehler": 0,
                "status": {}, "dauer_s": 0.1, "schulen": [], "limit": kw["limit"],
                "dry_run": kw["dry_run"]}

    from app.recherche import kern
    monkeypatch.setattr(kern, "lauf", fake_lauf)
    r = c.post("/api/admin/recherche/lauf", json={"limit": 40,
                                                  "bezirk": "Friedrichshain-Kreuzberg",
                                                  "schulform": "Grundschule"})
    assert r.status_code == 202 and r.json()["bezirk"] == "friedrichshain-kreuzberg"
    import time
    for _ in range(40):
        if gesehen:
            break
        time.sleep(0.05)
    assert gesehen["bezirk"] == "friedrichshain-kreuzberg" and gesehen["schulform"] == "Grundschule"
    store.close()


def test_recherche_uebersicht_filtert_nach_bezirk(tmp_path):
    c, store = _client(tmp_path)
    _schule(store)
    store.upsert_schule({"bsn": "05G01", "name": "Spandauer Schule", "schulform": "Grundschule",
                         "bezirk": "spandau", "website": "https://spandau.example.org"})
    d = c.get("/api/admin/recherche", params={"bezirk": "friedrichshain-kreuzberg"}).json()
    assert [s["bsn"] for s in d["schulen"]] == ["02G32"]
    d2 = c.get("/api/admin/recherche", params={"schulform": "Grundschule"}).json()
    assert len(d2["schulen"]) == 2
    store.close()


def test_recherche_lauf_limit_wird_geprueft(tmp_path):
    c, store = _client(tmp_path)
    for limit in (0, 999):
        r = c.post("/api/admin/recherche/lauf", json={"limit": limit})
        assert r.status_code == 422 and "1 und 722" in r.json()["detail"]["fehler"][0]
    store.close()


def test_fehlgeschlagener_lauf_landet_in_der_fehlerqueue(tmp_path, monkeypatch):
    c, store = _client(tmp_path)
    from app.recherche import kern

    def kaputt(*a, **k):
        raise RuntimeError("Endpunkt weg")

    monkeypatch.setattr(kern, "lauf", kaputt)
    c.post("/api/admin/recherche/lauf", json={"limit": 1})
    import time
    for _ in range(50):
        if store.recent_errors_all(limit=5):
            break
        time.sleep(0.05)
    fehler = store.recent_errors_all(limit=5)
    assert fehler and "Recherche-Lauf fehlgeschlagen" in fehler[0]["grund"]
    store.close()


def test_letzter_lauf_ohne_daten(tmp_path):
    c, store = _client(tmp_path)
    assert c.get("/api/admin/recherche/letzter-lauf").json() == {"vorhanden": False}
    store.set_setting("recherche_letzter_lauf", "kein json")
    d = c.get("/api/admin/recherche/letzter-lauf").json()
    assert d["vorhanden"] is False and "fehler" in d
    store.set_setting("recherche_letzter_lauf", json.dumps({"belegt": 2}))
    assert c.get("/api/admin/recherche/letzter-lauf").json()["belegt"] == 2
    store.close()


# --- Dubletten (Change 011) ------------------------------------------------
def test_dedupe_bericht_und_anwenden(tmp_path):
    """Admin sieht die Dubletten und kann sie zusammenführen."""
    from datetime import datetime
    from app.model import TZ_BERLIN, make_event_id

    c, store = _client(tmp_path)
    titel = "Tag der offenen Tür der Klax Kinderkrippe"

    def ev(quelle, nummer):
        seid = f"{titel}#{quelle}#{nummer}"
        return {"id": make_event_id(quelle, seid), "titel": titel, "beschreibung_kurz": None,
                "start_iso": "2026-09-26T10:00:00", "ende_iso": None,
                "start_local": "2026-09-26T10:00:00", "ende_local": None,
                "ganztags": False, "ort": "Klax Kinderkrippe", "adresse": None,
                "bezirk": None, "lat": 52.5019, "lon": 13.5701, "altersband_min": None,
                "altersband_max": None, "alters_familie": 0, "kategorien": "[]",
                "kostenlos": None, "quelle": quelle, "source_event_id": seid,
                "source_url": f"https://{quelle}.example.org/{nummer}",
                "geholt_am": datetime.now(TZ_BERLIN).isoformat(), "manuell": 0,
                "quellen_json": None}

    # Altbestand am Write-Path vorbei einfügen (vor Change 011 entstanden)
    for i, quelle in enumerate(("familienportal", "kinderkulturkalender", "zlb")):
        store._conn.execute(
            """INSERT INTO events (id, titel, beschreibung_kurz, start_iso, ende_iso,
               start_local, ende_local, ganztags, ort, adresse, bezirk, lat, lon,
               altersband_min, altersband_max, alters_familie, kategorien, kostenlos,
               quelle, source_event_id, source_url, geholt_am, status, manuell, quellen_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            store._ev_tuple(ev(quelle, i)))
    store._conn.commit()

    bericht = c.get("/api/admin/dedupe").json()
    assert bericht["gruppen"] == 1 and bericht["entfernbar"] == 2
    assert len(store.query_events({})) == 3            # Probelauf ändert nichts

    erg = c.post("/api/admin/dedupe/anwenden", json={}).json()
    assert erg["entfernt"] == 2
    events = store.query_events({})
    assert len(events) == 1 and events[0]["quelle"] == "familienportal"
    assert len(events[0]["quellen_json"] or "") > 0     # Provenienz bleibt erhalten
    # Verdachtsfälle sind sichtbar (hier: keine, alles gemergt)
    assert erg["verdacht"] == 0
    store.close()
