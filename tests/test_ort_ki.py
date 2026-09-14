"""Ortsvorschläge der LLM-Prüfung (Change 022).

Der Kern dieser Tests ist eine Invariante: **eine übernommene Ortskorrektur
überlebt den nächsten Scrape** (`manuell=1`). Ohne sie wäre das ganze Werkzeug
wertlos, weil der nächste Lauf die Korrektur wieder überschreibt.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app import ort_ki
from app.model import TZ_BERLIN, iso_utc, make_event_id
from app.store import Store

TEXT_BOTANISCH = (
    "Mit einer Fläche von 43 Hektar und nahezu 20.000 Pflanzenarten ist der "
    "Botanischer Garten Berlin nicht nur der größte in Deutschland, sondern "
    "einer der bedeutendsten Gärten der Welt. Bei dieser Sonntagsführung "
    "erleben Sie die einzigartigen Anlagen auf einem Spaziergang. "
    "Ort/Treffpunkt: Steglitz-Zehlendorf, Königin-Luise-Str. 6-8, 14195 Berlin, "
    "Besuchszentrum, Eingang Königin-Luise-Platz "
    "Anbieter: Botanischer Garten und Botanisches Museum Berlin")


def _event(store, *, titel="Sonntagsführung", ort="Besuchszentrum",
           adresse="Königin-Luise-Str. 6-8, 14195 Berlin", lat=None, lon=None,
           beschreibung=TEXT_BOTANISCH, quelle="test-feed", url="https://example.org/t/1"):
    start = datetime.now(TZ_BERLIN) + timedelta(days=3)
    local = start.strftime("%Y-%m-%dT%H:%M:%S")
    sid = f"{titel}#{local}"
    ev = {"id": make_event_id(quelle, sid), "titel": titel,
          "beschreibung_kurz": beschreibung, "start_iso": iso_utc(start),
          "ende_iso": iso_utc(start + timedelta(hours=2)), "start_local": local,
          "ende_local": (start + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S"),
          "ganztags": False, "ort": ort, "adresse": adresse, "bezirk": "steglitz-zehlendorf",
          "lat": lat, "lon": lon, "altersband_min": 6, "altersband_max": 12,
          "alters_familie": 0, "kategorien": [], "kostenlos": True,
          "quelle": quelle, "source_event_id": sid, "source_url": url,
          "geholt_am": datetime.now(TZ_BERLIN).isoformat()}
    store.upsert_event(ev)
    return store.get_event(ev["id"])


# --- Kandidaten und Prüfregeln --------------------------------------------

def test_kandidat_erkennt_fehlende_ortsnamen(tmp_path):
    store = Store(tmp_path / "k.db")
    store.add_source("test-feed", "Test", "feed", "https://example.org/feed")
    assert ort_ki.ist_kandidat(_event(store, ort="Am Tierpark 125")) is True       # Straße
    assert ort_ki.ist_kandidat(_event(store, ort="vielerorts")) is True            # generisch
    assert ort_ki.ist_kandidat(_event(store, ort="Ohne Angabe")) is True
    assert ort_ki.ist_kandidat(_event(store, ort="Museumsdorf Düppel", lat=52.4, lon=13.2)) is False
    # guter Name, aber keine Position → trotzdem prüfen
    assert ort_ki.ist_kandidat(_event(store, ort="Museumsdorf Düppel")) is True


def test_plausibilitaet_weist_die_bekannten_fehlertypen_ab():
    faelle = [
        ("Neukölln", True, "", False, "Bezirksname statt Ort"),
        ("Friedrichshain-Kreuzberg, Lichtenberg, Pankow", True, "", False, "Bezirksname statt Ort"),
        ("online", True, "", False, "generische Angabe"),
        ("Berlinweit", True, "", False, "generische Angabe"),
        ("Hochstr. 18", True, "Hochstr. 18", False, "kein Gewinn (wie bisher)"),
        ("unserem Büro", True, "", False, "beginnt klein"),
        ("Besuchszentrum", True, "", True, "Teilbereich bleibt erlaubt (Warnung im Band)"),
        ("Museumsdorf Düppel", True, "Clauertstr. 11", True, "ok"),
    ]
    for ort, belegt, jetzt, erwartet, hinweis in faelle:
        ok, grund = ort_ki.plausibel(ort, belegt, jetzt)
        assert ok is erwartet, f"{ort}: {grund} ({hinweis})"
    # ohne Beleg geht nichts — egal wie plausibel der Name klingt
    assert ort_ki.plausibel("Museumsdorf Düppel", False, "")[0] is False


def test_name_im_text_ist_die_sicherung():
    """Geprüft wird der NAME, nicht die Formulierung des Zitats (Nutzerfund
    „Botanischer Garten" vs. „Besuchszentrum", 14.09.2026)."""
    assert ort_ki.name_belegt("Botanischer Garten", TEXT_BOTANISCH) is True
    assert ort_ki.name_belegt("Besuchszentrum", TEXT_BOTANISCH) is True
    assert ort_ki.name_belegt("Botanischer Garten Berliner Stadtgüter", TEXT_BOTANISCH) is False
    # leicht abweichendes Zitat bleibt erkennbar
    assert ort_ki.zitat_aehnlich("Anbieter: Botanischer Garten und Botanisches Museum Berlin",
                                 TEXT_BOTANISCH) > 0.8


def test_abstandsbaender_statt_binaerer_schwelle():
    """„Botanischer Garten" liegt 431 m vom Museumsgebäude — das ist dieselbe
    Anlage, keine falsche Warnung (gemessen 14.09.2026)."""
    assert ort_ki.abstand_band(120) == "an derselben Adresse"
    assert ort_ki.abstand_band(431) == "gleiche Anlage"
    assert ort_ki.abstand_band(4000) == "nicht ortsgleich"
    assert ort_ki.abstand_band(None) == "n/v"


def test_vorschlag_kuerzt_lagebeschreibung_und_trennt_treffpunkt(tmp_path):
    store = Store(tmp_path / "k2.db")
    ev = _event(store)
    roh = {"ort": "Gendarmenmarkt direkt vor der Freitreppe des Konzerthauses Berlin",
           "adresse": "Gendarmenmarkt 1", "treffpunkt": "Freitreppe",
           "beleg": "auf dem Gendarmenmarkt direkt vor der Freitreppe des Konzerthauses Berlin"}
    v = ort_ki.vorschlag_bauen(store, ev, {}, TEXT_BOTANISCH + " Gendarmenmarkt direkt vor der "
                               "Freitreppe des Konzerthauses Berlin", roh, "testmodell",
                               "Lauf im Admin", None)
    assert v is not None
    assert v["ort_vorschlag"] == "Gendarmenmarkt"
    assert "Freitreppe" in v["treffpunkt"]
    assert v["belegherkunft"] == "Fließtext"


# --- Store ----------------------------------------------------------------

def _vorschlag(ev, ort="Botanischer Garten"):
    return {"event_id": ev["id"], "quelle": ev["quelle"], "ort_vorschlag": ort,
            "adresse_vorschlag": "Königin-Luise-Str. 6-8", "treffpunkt": "Besuchszentrum",
            "beleg": "Anbieter: Botanischer Garten und Botanisches Museum Berlin",
            "belegherkunft": "Anbieter-Feld", "abstand_m": 431, "ortsband": "gleiche Anlage",
            "name_im_text": True, "modell": "testmodell", "herkunft": "Test"}


def test_vorschlaege_speichern_ist_idempotent_und_geprueft_bleibt_geprueft(tmp_path):
    store = Store(tmp_path / "s.db")
    ev = _event(store)
    assert store.ort_vorschlaege_speichern([_vorschlag(ev)]) == 1
    assert store.ort_vorschlaege_speichern([_vorschlag(ev)]) == 0      # kein Doppel
    vid = store.list_ort_vorschlaege()[0]["id"]
    store.ort_vorschlaege_pruefen([vid], "verworfen", grund="Test")
    # erneutes Speichern darf eine geprüfte Entscheidung nicht zurückdrehen
    assert store.ort_vorschlaege_speichern([_vorschlag(ev)]) == 0
    assert store.ort_vorschlag_holen(vid)["status"] == "verworfen"
    z = store.ort_vorschlaege_zaehlen()
    assert z["verworfen"] == 1 and z["vorschlag"] == 0


# --- API + die entscheidende Invariante -----------------------------------

def _client(tmp_path):
    store = Store(tmp_path / "api.db")
    store.add_source("test-feed", "Test", "feed", "https://example.org/feed")
    ev = _event(store)
    store.ort_vorschlaege_speichern([_vorschlag(ev)])
    from app.main import app
    app.state.store = store
    return TestClient(app), store, ev


def test_uebernahme_setzt_ort_und_ueberlebt_den_naechsten_scrape(tmp_path):
    client, store, ev = _client(tmp_path)
    vid = store.list_ort_vorschlaege()[0]["id"]
    r = client.post("/api/admin/ort/uebernehmen", json={"ids": [vid]})
    assert r.status_code == 200 and r.json()["uebernommen"] == 1
    danach = store.get_event(ev["id"])
    assert danach["ort"] == "Botanischer Garten"
    assert danach["treffpunkt"] == "Besuchszentrum"
    assert danach["manuell"] == 1
    # Der nächste Scrape liefert wieder den Regelwert — er darf NICHT gewinnen.
    alt = dict(ev)
    alt["ort"] = "Besuchszentrum"
    neu, geaendert = store.upsert_event(alt)
    assert (neu, geaendert) == (False, False)
    assert store.get_event(ev["id"])["ort"] == "Botanischer Garten"
    # und der Vorschlag bleibt als übernommen stehen
    assert store.ort_vorschlag_holen(vid)["status"] == "uebernommen"
    # zweite Übernahme desselben Vorschlags ist kein stiller Erfolg
    r2 = client.post("/api/admin/ort/uebernehmen", json={"ids": [vid]})
    assert r2.json()["uebernommen"] == 0
    assert r2.json()["ergebnis"][0]["grund"] == "schon uebernommen"


def test_verwerfen_aendert_das_event_nicht(tmp_path):
    client, store, ev = _client(tmp_path)
    vid = store.list_ort_vorschlaege()[0]["id"]
    r = client.post("/api/admin/ort/verwerfen", json={"ids": [vid], "grund": "Ort falsch"})
    assert r.json()["verworfen"] == 1
    assert store.get_event(ev["id"])["ort"] == "Besuchszentrum"
    assert store.ort_vorschlag_holen(vid)["status"] == "verworfen"


def test_uebernehmen_ohne_ids_ist_ein_fehler(tmp_path):
    client, _store_, _ev = _client(tmp_path)
    assert client.post("/api/admin/ort/uebernehmen", json={}).status_code == 400
    assert client.post("/api/admin/ort/verwerfen", json={"ids": []}).status_code == 400


def test_import_nimmt_nur_plausible_vorschlaege(tmp_path):
    client, store, ev = _client(tmp_path)
    zeilen = "\n".join([
        '{"url": "%s", "ort_llm": "Botanischer Garten", "adresse_llm": "Königin-Luise-Str. 6-8",'
        ' "beleg": "Anbieter: Botanischer Garten", "beleg_woertlich": true, "treffpunkt_llm": "Besuchszentrum"}'
        % ev["source_url"],
        '{"url": "%s", "ort_llm": "Steglitz-Zehlendorf", "beleg": "Ort/Treffpunkt: Steglitz-Zehlendorf",'
        ' "beleg_woertlich": true}' % ev["source_url"],
        '{"url": "https://example.org/unbekannt", "ort_llm": "Irgendwo", "beleg_woertlich": true}',
    ])
    r = client.post("/api/admin/ort/import", json={"jsonl": zeilen, "modell": "schattenlauf"})
    assert r.status_code == 200
    d = r.json()
    assert d["importiert"] == 1 and d["verworfen"] == 2
    v = store.list_ort_vorschlaege()[0]
    assert v["ort_vorschlag"] == "Botanischer Garten"
    assert v["herkunft"] == "Import Schattenlauf"


def test_lauf_mit_gefaktem_modell_legt_vorschlaege_an(tmp_path):
    """Die Stufe selbst: Kandidat → Modell (gefakt) → geprüfter Vorschlag."""
    store = Store(tmp_path / "lauf.db")
    store.add_source("test-feed", "Test", "feed", "https://example.org/feed")
    ev = _event(store, ort="Besuchszentrum")

    def fake_chat(prompt: str) -> dict:
        assert "Botanischer Garten" in prompt          # Text geht ans Modell
        return {"text": '{"ort": "Botanischer Garten", "adresse": "Königin-Luise-Str. 6-8",'
                        ' "treffpunkt": "Besuchszentrum, Eingang Königin-Luise-Platz",'
                        ' "beleg": "Anbieter: Botanischer Garten und Botanisches Museum Berlin"}'}

    z = ort_ki.lauf(store, quelle="test-feed", llm_chat=fake_chat)
    assert z["kandidaten"] == 1 and z["vorschlaege"] == 1
    assert z["llm_fehler"] == 0 and z["abruf_fehler"] == 0
    v = store.list_ort_vorschlaege()[0]
    assert v["ort_vorschlag"] == "Botanischer Garten"
    assert v["treffpunkt"].startswith("Besuchszentrum")
    assert v["belegherkunft"] == "Anbieter-Feld"
    # Der Termin selbst bleibt unangetastet — Vorschlag heißt Vorschlag.
    assert store.get_event(ev["id"])["ort"] == "Besuchszentrum"
    assert ort_ki.letzter_lauf(store)["vorschlaege"] == 1


def test_lauf_verwirft_bezirksnamen_und_zaehlt_sie(tmp_path):
    store = Store(tmp_path / "lauf2.db")
    store.add_source("test-feed", "Test", "feed", "https://example.org/feed")
    _event(store, ort="Steglitz-Zehlendorf")

    def fake_chat(prompt: str) -> dict:
        return {"text": '{"ort": "Steglitz-Zehlendorf", "beleg": "Ort/Treffpunkt: Steglitz-Zehlendorf"}'}

    z = ort_ki.lauf(store, quelle="test-feed", llm_chat=fake_chat)
    assert z["vorschlaege"] == 0 and z["verworfen"] == 1
    assert store.list_ort_vorschlaege() == []
