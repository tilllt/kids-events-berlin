"""Admin-API-Tests (Phase 1, Change 002) — offen, ohne Auth."""
import time

from fastapi.testclient import TestClient

from app.store import Store

GUT_REGELN = """listing:
  url: https://www.zlb.de/veranstaltungen
  item_css: article.eventTeaser
  felder:
    titel: {css: ".eventTeaser__title"}
    start: {css: ".eventTeaser__date", format: "%d.%m.%Y"}
"""

SCHLECHTE_REGELN = """listing:
  url: https://www.zlb.de/veranstaltungen
  item_css: "article[[kaputt"
  felder:
    titel: {css: ".eventTeaser__title"}
    start: {css: ".eventTeaser__date", format: "%d.%m.%Y"}
"""


def _client(tmp_path):
    store = Store(tmp_path / "admin_api.db")
    store.seed_default_sources()
    from app.main import app
    app.state.store = store
    return TestClient(app), store


def test_sources_liste_mit_seed(tmp_path):
    c, _ = _client(tmp_path)
    r = c.get("/api/admin/sources")
    assert r.status_code == 200
    quellen = r.json()
    assert len(quellen) == 1
    assert quellen[0]["quelle"] == "jup-berlin"
    assert quellen[0]["typ"] == "intern"
    assert quellen[0]["aktiv"] is True
    assert "letzter_lauf" in quellen[0]


def test_source_crud(tmp_path):
    c, _ = _client(tmp_path)
    r = c.post("/api/admin/sources", json={
        "quelle": "zlb", "name": "ZLB Veranstaltungen", "typ": "regeln",
        "url": "https://www.zlb.de/veranstaltungen", "rate_limit_s": 2.0,
        "menge_min": 5, "menge_max": 80})
    assert r.status_code == 201, r.text
    assert c.get("/api/admin/sources/zlb").json()["menge_max"] == 80
    r = c.put("/api/admin/sources/zlb", json={"menge_max": 120, "aktiv": False})
    assert r.status_code == 200
    z = r.json()
    assert z["menge_max"] == 120 and z["aktiv"] is False
    assert c.delete("/api/admin/sources/zlb").status_code == 204
    assert c.get("/api/admin/sources/zlb").status_code == 404
    assert c.delete("/api/admin/sources/zlb").status_code == 404


def test_source_ungueltig(tmp_path):
    c, _ = _client(tmp_path)
    r = c.post("/api/admin/sources", json={"quelle": "ZLB!x", "name": "", "typ": "was"})
    assert r.status_code == 422
    fehler = r.json()["detail"]["fehler"]
    assert any("quelle" in f for f in fehler)
    assert any("typ" in f for f in fehler)
    # Duplikat
    c.post("/api/admin/sources", json={"quelle": "zlb", "name": "ZLB", "typ": "regeln"})
    r = c.post("/api/admin/sources", json={"quelle": "zlb", "name": "nochmal", "typ": "regeln"})
    assert r.status_code == 409


def test_regeln_put_validate(tmp_path):
    c, _ = _client(tmp_path)
    c.post("/api/admin/sources", json={"quelle": "zlb", "name": "ZLB", "typ": "regeln",
                                       "url": "https://www.zlb.de/veranstaltungen"})
    # intern hat keine Regeln
    assert c.put("/api/admin/sources/jup-berlin/regeln",
                 json={"regel_yaml": GUT_REGELN}).status_code == 409
    # gültig
    r = c.put("/api/admin/sources/zlb/regeln", json={"regel_yaml": GUT_REGELN})
    assert r.status_code == 200, r.text
    assert c.get("/api/admin/sources/zlb/regeln").json()["regel_yaml"].startswith("listing:")
    # ungültig → 422 mit Meldungen
    r = c.put("/api/admin/sources/zlb/regeln", json={"regel_yaml": SCHLECHTE_REGELN})
    assert r.status_code == 422
    assert r.json()["detail"]["fehler"]
    # validate ohne Speichern
    r = c.post("/api/admin/sources/zlb/regeln/validate", json={"regel_yaml": SCHLECHTE_REGELN})
    assert r.status_code == 200 and r.json()["ok"] is False
    r = c.post("/api/admin/sources/zlb/regeln/validate", json={"regel_yaml": GUT_REGELN})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_regeln_schema_checks(tmp_path):
    c, _ = _client(tmp_path)
    # fehlende Pflichtfelder / unbekannte Keys
    kaputt = "listing:\n  url: https://x.de\n  item_css: .a\n  felder:\n    titel: {css: '.t'}\n"
    r = c.post("/api/admin/sources/jup-berlin/regeln/validate", json={"regel_yaml": kaputt})
    assert r.json()["ok"] is False
    assert any("'start'" in f for f in r.json()["fehler"])
    kaputt2 = "listing:\n  url: https://x.de\n  item_css: .a\n  felder:\n    titel: {css: '.t'}\n    start: {css: '.d'}\n    quatsch: {css: '.q'}\n"
    r = c.post("/api/admin/sources/jup-berlin/regeln/validate", json={"regel_yaml": kaputt2})
    assert any("quatsch" in f for f in r.json()["fehler"])


def test_settings(tmp_path):
    c, _ = _client(tmp_path)
    assert c.get("/api/admin/settings").json()["scrape_interval_h"] == "24"
    assert c.put("/api/admin/settings", json={"scrape_interval_h": "6"}).status_code == 200
    assert c.get("/api/admin/settings").json()["scrape_interval_h"] == "6"
    r = c.put("/api/admin/settings", json={"scrape_interval_h": "abc", "böse": "1"})
    assert r.status_code == 422 and r.json()["detail"]["fehler"]


def test_runs_errors_sichtbar(tmp_path):
    c, s = _client(tmp_path)
    rid = s.start_run("jup-berlin")
    s.finish_run(rid, n_events=12, n_neu=3, n_geaendert=0, n_fehler=1, n_quellseiten=2)
    s.log_error("jup-berlin", "Detail kaputt", {"titel": "X"})
    r = c.get("/api/admin/runs")
    assert r.status_code == 200 and r.json()[0]["n_neu"] == 3
    r = c.get("/api/admin/errors?quelle=jup-berlin")
    assert r.status_code == 200 and r.json()[0]["grund"] == "Detail kaputt"
    r = c.get("/api/admin/sources/jup-berlin/run-latest")
    assert r.json()["runs"][0]["status"] == "ok"


def test_scrape_intern_startet(tmp_path, monkeypatch):
    c, _ = _client(tmp_path)
    gerufen = []

    def fake_scrape(store, quelle, **kw):
        gerufen.append(quelle)
        return {"run_id": 1, "quelle": quelle}

    monkeypatch.setattr("app.pipeline.scrape", fake_scrape)
    # typ regeln → 409 (Engine folgt in Phase 3)
    c.post("/api/admin/sources", json={"quelle": "zlb", "name": "ZLB", "typ": "regeln"})
    assert c.post("/api/admin/sources/zlb/scrape").status_code == 409
    # typ intern → 202, Thread ruft scrape
    assert c.post("/api/admin/sources/jup-berlin/scrape").status_code == 202
    for _ in range(40):
        if gerufen:
            break
        time.sleep(0.05)
    assert gerufen == ["jup-berlin"]
