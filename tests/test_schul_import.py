"""Schul-Import: WFS-Stamm + Crawl-Termine (Change 005)."""
import json

from app.schul_import import (SCHULARTEN_ALLGEMEINBILDEND,
                              import_crawl_termine, import_schulen)
from app.store import Store


def _store(tmp_path):
    return Store(tmp_path / "schul_import.db")


WFS = {
    "type": "FeatureCollection",
    "features": [
        {"properties": {"bsn": "01B01", "schulname": "OSZ Banken",
                        "schulart": "Oberstufenzentrum", "bezirk": "Mitte",
                        "ortsteil": "Moabit", "plz": "10557",
                        "strasse": "Alt-Moabit", "hausnr": "10",
                        "email": "i@osz.de", "internet": "https://osz.de",
                        "schuljahr": "2025/26"}},
        {"properties": {"bsn": "01G01", "schulname": "Test-Grundschule",
                        "schulart": "Grundschule", "bezirk": "Spandau",
                        "ortsteil": "Haselhorst", "plz": "13599",
                        "strasse": "Musterweg", "hausnr": "1",
                        "email": "k@schule.de", "internet": "https://schule.de",
                        "schuljahr": "2025/26"}},
        {"properties": {"bsn": "03Y01", "schulname": "Test-Gymnasium",
                        "schulart": "Gymnasium", "bezirk": "Mitte",
                        "strasse": "Weg", "hausnr": "2"}},
    ],
}


def _crawl(bsn="01G01", termine=None):
    return [{"bsn": bsn, "name": "X", "stufe": "A",
             "termine": termine or []}]


def test_import_schulen_nur_allgemeinbildend(tmp_path):
    s = _store(tmp_path)
    p = tmp_path / "wfs.json"
    p.write_text(json.dumps(WFS), encoding="utf-8")
    erg = import_schulen(s, str(p))
    # OSZ übersprungen, Grundschule + Gymnasium importiert
    assert erg["importiert"] == 2
    assert erg["uebersprungen"] == 1
    assert s.get_schule("01G01")["schulform"] == "Grundschule"
    g = s.get_schule("01G01")
    assert g["bezirk"] == "spandau"  # normalisiert
    assert g["strasse"] == "Musterweg 1"  # strasse + hausnr
    assert g["email"] == "k@schule.de"
    assert g["website"] == "https://schule.de"
    assert s.get_schule("01B01") is None
    # idempotent
    erg2 = import_schulen(s, str(p))
    assert erg2["importiert"] == 2
    assert len(s.list_schulen()) == 2
    s.close()


def test_schularten_menge():
    assert "Grundschule" in SCHULARTEN_ALLGEMEINBILDEND
    assert "Integrierte Sekundarschule" in SCHULARTEN_ALLGEMEINBILDEND
    assert "Oberstufenzentrum" not in SCHULARTEN_ALLGEMEINBILDEND


def test_import_crawl_zukunft_mit_keyword(tmp_path):
    s = _store(tmp_path)
    s.upsert_schule({"bsn": "01G01", "name": "Test-Grundschule"})
    p = tmp_path / "crawl.json"
    p.write_text(json.dumps(_crawl(termine=[
        {"quelle": "text", "url": "https://schule.de/termine",
         "zeile": "Tag der offenen Tür am 15.10.2026 von 09:00 bis 12:00 Uhr"},
        # vergangen → verworfen
        {"quelle": "text", "url": "https://schule.de/x",
         "zeile": "Tag der offenen Tür am 05.01.2026"},
        # News-Zeitstempel ohne Keyword → verworfen
        {"quelle": "time", "url": "https://schule.de/news",
         "datetime": "2026-10-01T10:00:00+02:00", "text": "1. Oktober 2026"},
        # kein Termin-Keyword → verworfen
        {"quelle": "text", "url": "https://schule.de/y",
         "zeile": "Einschulung am 01.08.2027"},
        # Duplikat (gleiche Seite) → zählt als Duplikat
        {"quelle": "text", "url": "https://schule.de/termine",
         "zeile": "Wir laden ein zum Tag der offenen Tür am 15.10.2026"},
    ])), encoding="utf-8")
    erg = import_crawl_termine(s, str(p))
    assert erg["importiert"] == 1
    assert erg["verworfen_alt_oder_rauschen"] == 3
    termine = s.list_termine_manuell(schule_bsn="01G01")
    assert len(termine) == 1
    t = termine[0]
    assert t["titel"] == "Tag der offenen Tür"
    assert t["start_datum"] == "15.10.2026"
    assert t["start_zeit"] == "09:00"
    assert t["status"] == "ungeprueft"
    assert t["quelle_hinweis"].startswith("automatisch erkannt:")
    assert "Crawl-Fund" in (t["beschreibung"] or "")
    s.close()


def test_import_crawl_idempotent(tmp_path):
    s = _store(tmp_path)
    s.upsert_schule({"bsn": "01G01", "name": "Test-Grundschule"})
    p = tmp_path / "crawl.json"
    p.write_text(json.dumps(_crawl(termine=[
        {"quelle": "text", "url": "https://schule.de/termine",
         "zeile": "Infoabend am 20.11.2026 um 18 Uhr"},
    ])), encoding="utf-8")
    erg1 = import_crawl_termine(s, str(p))
    assert erg1["importiert"] == 1
    erg2 = import_crawl_termine(s, str(p))
    assert erg2["importiert"] == 0
    assert erg2["duplikate"] >= 1
    assert len(s.list_termine_manuell()) == 1
    s.close()


def test_import_crawl_ohne_stamm_ignoriert(tmp_path):
    s = _store(tmp_path)  # keine Schulen importiert
    p = tmp_path / "crawl.json"
    p.write_text(json.dumps(_crawl(bsn="9999", termine=[
        {"quelle": "text", "url": "https://x.de",
         "zeile": "Tag der offenen Tür am 15.10.2026"},
    ])), encoding="utf-8")
    erg = import_crawl_termine(s, str(p))
    assert erg["importiert"] == 0
    assert erg["schulen_ohne_stamm"] == 1
    s.close()


def test_import_crawl_zeit_fallback_nicht_datum(tmp_path):
    """'TT.MM.JJJJ' im Text darf NICHT als Uhrzeit TT:MM geparst werden.

    Datum relativ zu heute, damit der Test nicht mit der Zeit veraltet
    (der Import verwirft Vergangenes — real passiert am 13.09.2026).
    """
    from datetime import date, timedelta

    s = _store(tmp_path)
    s.upsert_schule({"bsn": "01G01", "name": "Test-Grundschule"})
    ziel = date.today() + timedelta(days=30)
    p = tmp_path / "crawl.json"
    p.write_text(json.dumps(_crawl(termine=[
        {"quelle": "text", "url": "https://schule.de/t",
         "zeile": f"Tag der offenen Tür am {ziel:%d.%m.%Y} (ohne Uhrzeit-Angabe)"},
    ])), encoding="utf-8")
    erg = import_crawl_termine(s, str(p))
    assert erg["importiert"] == 1
    t = s.list_termine_manuell()[0]
    assert t["start_datum"] == f"{ziel:%d.%m.%Y}"
    assert t["start_zeit"] is None
    s.close()


def test_import_schulzweig_ids(tmp_path):
    """Mapping {bsn: IDSchulzweig} → schulen.schulzweig_id (Schulportrait-Link)."""
    from app.schul_import import import_schulzweig_ids

    s = _store(tmp_path)
    s.upsert_schule({"bsn": "01G01", "name": "Test-Grundschule"})
    s.upsert_schule({"bsn": "03Y01", "name": "Test-Gymnasium"})
    p = tmp_path / "mapping.json"
    p.write_text(json.dumps({"01G01": "31345", "03Y01": "30638",
                             "99Z99": "12345"}), encoding="utf-8")
    erg = import_schulzweig_ids(s, str(p))
    assert erg["aktualisiert"] == 2
    assert erg["bsn_unbekannt"] == 1  # 99Z99 nicht in DB
    assert s.get_schule("01G01")["schulzweig_id"] == "31345"
    assert s.get_schule("03Y01")["schulzweig_id"] == "30638"
    # idempotent: zweiter Lauf aktualisiert nichts mehr
    erg2 = import_schulzweig_ids(s, str(p))
    assert erg2["aktualisiert"] == 0
    s.close()
