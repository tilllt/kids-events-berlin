"""Die Schul-Mail in getrennten Feldern: An, Reply-To, Betreff, Nachricht.

Anlass (User-Befund 2026-09-13): im Dialog „Schule → E-Mail" stand der GESAMTE
Mailtext inklusive Betreffzeile in einem einzigen Feld. Jetzt liefert der Server
eine fertige Vorschau in getrennten Feldern (Platzhalter schon ersetzt) und der
Versand nimmt genau diese Felder entgegen.
"""
import pytest
from fastapi.testclient import TestClient

from app import admin_api as A
from app.main import app
from app.store import Store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = Store(tmp_path / "anfrage.db")
    store.upsert_schule({"bsn": "02G99", "name": "Test-Grundschule", "schulform": "Grundschule",
                         "bezirk": "friedrichshain-kreuzberg", "email": "sekretariat@test-schule.de",
                         "website": "https://test-schule.de"})
    store.set_setting("smtp_reply_to", "kinderkram@mekotools.de")
    store.set_setting("smtp_from", "kinderkram@mekotools.de")
    store.set_setting("smtp_host", "w00d77ee.kasserver.com")
    store.set_setting("smtp_port", "465")
    store.set_setting("mail_betreff", "Termin {jahr}: {schule}")
    store.set_setting("mail_text", "Guten Tag,\n\nwann ist der Tag der offenen Tür der {schulform} {schule} ({bezirk})?\n")
    monkeypatch.setattr(A, "_store", lambda request: store)
    with TestClient(app) as c:
        c.store = store
        yield c
    store.close()


def test_vorschau_liefert_getrennte_felder_mit_gefuellten_platzhaltern(client):
    d = client.get("/api/admin/schulen/02G99/anfrage/vorschau").json()
    assert d["an"] == "sekretariat@test-schule.de"
    assert d["reply_to"] == "kinderkram@mekotools.de"
    assert d["betreff"].startswith("Termin ") and "Test-Grundschule" in d["betreff"]
    assert "{" not in d["betreff"] and "}" not in d["betreff"]
    assert d["text"].startswith("Guten Tag,")
    assert "Betreff" not in d["text"], "Betreffzeile darf nicht mehr im Nachrichtentext stecken"
    assert "Grundschule Test-Grundschule (friedrichshain-kreuzberg)" in d["text"]
    assert d["hat_email"] is True


def test_vorschau_meldet_fehlende_schule(client):
    assert client.get("/api/admin/schulen/99X99/anfrage/vorschau").status_code == 404


def test_versand_nimmt_getrennte_felder(client, monkeypatch):
    gerufen = {}

    def fake(store, empfaenger, betreff, nachricht, reply_to=None):
        gerufen.update(an=empfaenger, betreff=betreff, nachricht=nachricht, reply_to=reply_to)

    monkeypatch.setattr(A, "_sende_mail", fake)
    r = client.post("/api/admin/schulen/02G99/anfrage", json={
        "betreff": "Frage zum Tag der offenen Tür",
        "text": "Guten Tag,\n\nkurze Frage.",
        "reply_to": "antwort@mekotools.de",
    })
    assert r.status_code == 200, r.text
    assert gerufen["betreff"] == "Frage zum Tag der offenen Tür"
    assert gerufen["nachricht"].startswith("Guten Tag,")
    assert gerufen["reply_to"] == "antwort@mekotools.de"
    assert r.json()["betreff"] == "Frage zum Tag der offenen Tür"
    assert r.json()["reply_to"] == "antwort@mekotools.de"


def test_versand_ohne_getrennte_felder_bleibt_rueckwaertskompatibel(client, monkeypatch):
    """Alter Aufruf: alles in `text`, erste Zeile 'Betreff: …' ist der Betreff."""
    gerufen = {}
    monkeypatch.setattr(A, "_sende_mail",
                        lambda store, an, betreff, nachricht, reply_to=None:
                        gerufen.update(betreff=betreff, nachricht=nachricht, reply_to=reply_to))
    r = client.post("/api/admin/schulen/02G99/anfrage",
                    json={"text": "Betreff: Alter Weg\n\nNachrichtentext"})
    assert r.status_code == 200
    assert gerufen["betreff"] == "Alter Weg"
    assert gerufen["nachricht"] == "Nachrichtentext"
    assert gerufen["reply_to"] is None      # Einstellungen entscheiden


def test_platzhalter_werden_auch_im_betreff_ersetzt(client, monkeypatch):
    gerufen = {}
    monkeypatch.setattr(A, "_sende_mail",
                        lambda store, an, betreff, nachricht, reply_to=None:
                        gerufen.update(betreff=betreff))
    client.post("/api/admin/schulen/02G99/anfrage",
                json={"betreff": "TdOT {schule} {jahr}", "text": "Hallo"})
    assert "{" not in gerufen["betreff"] and "Test-Grundschule" in gerufen["betreff"]
