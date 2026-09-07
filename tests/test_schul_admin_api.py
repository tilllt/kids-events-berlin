"""Admin-API: Schulen/Kategorien/manuelle Termine/Mail (Change 005) — offen, ohne Auth."""
import smtplib

from fastapi.testclient import TestClient

from app.store import Store


def _client(tmp_path):
    store = Store(tmp_path / "schul_api.db")
    store.seed_default_sources()
    from app.main import app
    app.state.store = store
    return TestClient(app), store


def _schule(bsn="1001", name="Grundschule Muster"):
    return {"bsn": bsn, "name": name, "schulform": "Grundschule",
            "bezirk": "spandau", "ortsteil": "Haselhorst", "plz": "13599",
            "strasse": "Musterweg 1", "email": "kontakt@beispiel-schule.de",
            "website": "https://beispiel-schule.de"}


def _kategorie(kid="tdot", name="Tag der offenen Tür"):
    return {"id": kid, "name": name, "farbe": "#2ea043", "sort": 1}


def _termin(schule_bsn="1001", status="ungeprueft", kategorie_id=None):
    return {"schule_bsn": schule_bsn, "kategorie_id": kategorie_id,
            "titel": "Tag der offenen Tür 2026", "start_datum": "15.10.2026",
            "start_zeit": "16:00", "ort": "Aula", "status": status}


# --- Schulen ----------------------------------------------------------------
def test_schulen_crud_api(tmp_path):
    c, _ = _client(tmp_path)
    assert c.get("/api/admin/schulen").json() == []
    r = c.post("/api/admin/schulen", json=_schule())
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Grundschule Muster"
    assert c.get("/api/admin/schulen/1001").json()["bezirk"] == "spandau"
    r = c.put("/api/admin/schulen/1001", json={"name": "Grundschule Neu"})
    assert r.status_code == 200 and r.json()["name"] == "Grundschule Neu"
    # Suche/Filter
    c.post("/api/admin/schulen", json=_schule("2002", "Gymnasium Beispiel"))
    assert len(c.get("/api/admin/schulen", params={"q": "Gymnasium"}).json()) == 1
    assert len(c.get("/api/admin/schulen", params={"bezirk": "spandau"}).json()) == 2
    # Fehlerfälle
    assert c.get("/api/admin/schulen/9999").status_code == 404
    assert c.put("/api/admin/schulen/9999", json={"name": "x"}).status_code == 404
    assert c.post("/api/admin/schulen", json={"name": "ohne bsn"}).status_code == 422
    assert c.post("/api/admin/schulen", json=_schule()).status_code == 409
    assert c.delete("/api/admin/schulen/1001").status_code == 204
    assert c.get("/api/admin/schulen/1001").status_code == 404
    assert c.delete("/api/admin/schulen/1001").status_code == 404


# --- Kategorien -------------------------------------------------------------
def test_kategorien_crud_api(tmp_path):
    c, _ = _client(tmp_path)
    assert c.get("/api/admin/kategorien").json() == []
    assert c.post("/api/admin/kategorien", json=_kategorie()).status_code == 201
    assert c.get("/api/admin/kategorien").json()[0]["name"] == "Tag der offenen Tür"
    r = c.put("/api/admin/kategorien/tdot", json={"name": "Infoabend"})
    assert r.status_code == 200 and r.json()["name"] == "Infoabend"
    assert c.post("/api/admin/kategorien", json=_kategorie()).status_code == 409
    assert c.post("/api/admin/kategorien", json={"id": "x"}).status_code == 422
    assert c.put("/api/admin/kategorien/unbekannt", json={"name": "x"}).status_code == 404
    assert c.delete("/api/admin/kategorien/tdot").status_code == 204
    assert c.delete("/api/admin/kategorien/tdot").status_code == 404


# --- Termine ----------------------------------------------------------------
def test_termine_crud_und_spiegel_api(tmp_path):
    c, _ = _client(tmp_path)
    c.post("/api/admin/schulen", json=_schule())
    c.post("/api/admin/kategorien", json=_kategorie())
    # ungeprueft anlegen → kein öffentliches Event
    r = c.post("/api/admin/termine", json=_termin())
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert r.json()["status"] == "ungeprueft"
    assert c.get("/api/admin/termine").json()[0]["schulname"] == "Grundschule Muster"
    # öffentlich: manuelle Quelle leer (nur ungeprüft)
    assert c.get("/api/events", params={"quelle": "manuell"}).json() == []
    # bestätigen → Event erscheint öffentlich
    r = c.put(f"/api/admin/termine/{tid}", json={"status": "bestaetigt"})
    assert r.status_code == 200
    offen = c.get("/api/events", params={"quelle": "manuell"}).json()
    assert len(offen) == 1 and offen[0]["titel"] == "Tag der offenen Tür 2026"
    assert offen[0]["bezirk"] == "spandau"
    # zurück auf ungeprueft → Spiegel weg
    c.put(f"/api/admin/termine/{tid}", json={"status": "ungeprueft"})
    assert c.get("/api/events", params={"quelle": "manuell"}).json() == []
    # Filter + Fehler
    assert len(c.get("/api/admin/termine", params={"schule": "1001"}).json()) == 1
    assert c.post("/api/admin/termine", json=_termin("9999")).status_code == 422
    assert c.get("/api/admin/termine/99999").status_code == 404
    assert c.put("/api/admin/termine/99999", json={"titel": "x"}).status_code == 404
    assert c.delete("/api/admin/termine/99999").status_code == 404
    assert c.delete(f"/api/admin/termine/{tid}").status_code == 204
    assert c.get("/api/admin/termine").json() == []


def test_schule_loeschen_raeumt_termine_auf_api(tmp_path):
    c, _ = _client(tmp_path)
    c.post("/api/admin/schulen", json=_schule())
    tid = c.post("/api/admin/termine", json=_termin(status="bestaetigt")).json()["id"]
    assert len(c.get("/api/events", params={"quelle": "manuell"}).json()) == 1
    assert c.delete("/api/admin/schulen/1001").status_code == 204
    assert c.get("/api/admin/termine").json() == []
    assert c.get("/api/events", params={"quelle": "manuell"}).json() == []


# --- Mail-Anfrage -----------------------------------------------------------
def test_anfrage_ohne_smtp_409(tmp_path):
    c, _ = _client(tmp_path)
    c.post("/api/admin/schulen", json=_schule())
    r = c.post("/api/admin/schulen/1001/anfrage",
               json={"text": "Hallo, wir hätten gern Eure Termine."})
    assert r.status_code == 409
    assert "SMTP" in r.json()["detail"]["fehler"][0]
    assert c.get("/api/admin/schulen/1001").json()["angefragt_am"] is None


def test_anfrage_ohne_schul_email_422(tmp_path):
    c, s = _client(tmp_path)
    s.set_setting("smtp_host", "smtp.example.org")
    s.set_setting("smtp_from", "app@example.org")
    sch = _schule()
    sch["email"] = ""
    c.post("/api/admin/schulen", json=sch)
    r = c.post("/api/admin/schulen/1001/anfrage", json={"text": "Hallo"})
    assert r.status_code == 422
    assert "E-Mail" in r.json()["detail"]["fehler"][0]


def test_anfrage_sendet_mail(tmp_path, monkeypatch):
    c, s = _client(tmp_path)
    s.set_setting("smtp_host", "smtp.example.org")
    s.set_setting("smtp_from", "kinderkram@example.org")
    c.post("/api/admin/schulen", json=_schule())
    gesendet = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            gesendet["host"] = host
            gesendet["port"] = port
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def ehlo(self):
            pass
        def starttls(self):
            pass
        def send_message(self, msg):
            gesendet["msg"] = msg

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    r = c.post("/api/admin/schulen/1001/anfrage",
               json={"text": "Bitte Termine schicken!"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "gesendet"
    assert gesendet["host"] == "smtp.example.org"
    assert gesendet["port"] == 587
    assert gesendet["msg"]["To"] == "kontakt@beispiel-schule.de"
    assert "Termin-Anfrage" in gesendet["msg"]["Subject"]
    # angefragt_am ist gesetzt
    assert c.get("/api/admin/schulen/1001").json()["angefragt_am"] is not None
    # leerer Text → Vorlage wird gefüllt (Standard-Text), kein 422
    gesendet.pop("msg", None)
    r = c.post("/api/admin/schulen/1001/anfrage", json={"text": "   "})
    assert r.status_code == 200, r.text
    assert gesendet["msg"]["Subject"].startswith("Tage der offenen Tür")
    assert "Grundschule Muster" in gesendet["msg"].get_content()
    assert "spandau" in gesendet["msg"].get_content()
    # explizite Betreff-Zeile wird als Subject übernommen
    gesendet.pop("msg", None)
    r = c.post("/api/admin/schulen/1001/anfrage",
               json={"text": "Betreff: Terminliste gesucht\n\nHallo!"})
    assert r.status_code == 200
    assert gesendet["msg"]["Subject"] == "Terminliste gesucht"


def test_anfrage_unbekannte_schule_404(tmp_path):
    c, _ = _client(tmp_path)
    assert c.post("/api/admin/schulen/9999/anfrage",
                  json={"text": "Hallo"}).status_code == 404
