"""Admin-Persistenz: sources/regeln/settings (Phase 0, Change 002)."""
from app.store import Store


def _store(tmp_path):
    s = Store(tmp_path / "admin_test.sqlite3")
    s.seed_default_sources()
    return s


def test_seed_default_sources(tmp_path):
    s = _store(tmp_path)
    quellen = [q["quelle"] for q in s.list_sources()]
    assert quellen == ["jup-berlin"]
    assert s.get_source("jup-berlin")["typ"] == "intern"
    assert s.get_setting("scrape_interval_h") == "24"
    # idempotent
    s.seed_default_sources()
    assert len(s.list_sources()) == 1
    s.close()


def test_source_crud(tmp_path):
    s = _store(tmp_path)
    s.add_source("zlb", "ZLB Veranstaltungen", "regeln",
                 url="https://www.zlb.de/veranstaltungen",
                 rate_limit_s=2.0, menge_min=5, menge_max=80, aktiv=True)
    z = s.get_source("zlb")
    assert z["url"] == "https://www.zlb.de/veranstaltungen"
    assert z["rate_limit_s"] == 2.0 and z["menge_min"] == 5
    s.update_source("zlb", name="ZLB Berlin", menge_max=120)
    assert s.get_source("zlb")["menge_max"] == 120
    assert s.get_source("zlb")["name"] == "ZLB Berlin"
    # duplikat / unbekannt
    try:
        s.add_source("zlb", "nochmal", "regeln")
        assert False
    except ValueError:
        pass
    try:
        s.update_source("gibt-es-nicht", name="x")
        assert False
    except ValueError:
        pass
    s.delete_source("zlb")
    assert s.get_source("zlb") is None
    s.close()


def test_regeln_und_cascade(tmp_path):
    s = _store(tmp_path)
    s.add_source("zlb", "ZLB", "regeln", url="https://www.zlb.de/veranstaltungen")
    s.set_regeln("zlb", "listing:\n  url: https://www.zlb.de/veranstaltungen\n")
    r = s.get_regeln("zlb")
    assert r and "listing:" in r["regel_yaml"]
    # Löschen der Quelle cascadet die Regeln
    s.delete_source("zlb")
    assert s.get_regeln("zlb") is None
    s.close()


def test_settings(tmp_path):
    s = _store(tmp_path)
    assert s.get_setting("unbekannt") is None
    assert s.get_setting("unbekannt", "dflt") == "dflt"
    s.set_setting("scrape_interval_h", "6")
    assert s.get_setting("scrape_interval_h") == "6"
    s.set_setting("neu", "wert")
    assert s.all_settings()["neu"] == "wert"
    s.close()
