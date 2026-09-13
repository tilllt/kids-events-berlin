"""Filter und Mehrfachauswahl für Schul-Recherche und Schul-Mails.

Vorgabe: in beiden Ansichten dieselben Filter wie im Frontend (Bezirk, Schulform),
Schulen mit vorhandenem Termin ausblendbar, mehrere Schulen auswählbar — für eine
Sammel-Mail und für einen Recherche-Lauf über genau die Auswahl.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app import admin_api as A
from app.main import app
from app.store import Store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = Store(tmp_path / "filter.db")
    for bsn, name, bez, form, mail in (
        ("02G01", "Alpha-Grundschule", "friedrichshain-kreuzberg", "Grundschule", "a@example.org"),
        ("02G02", "Beta-Grundschule", "friedrichshain-kreuzberg", "Grundschule", "b@example.org"),
        ("02G03", "Gamma-Gymnasium", "pankow", "Gymnasium", ""),
        ("02G04", "Delta-Grundschule", "pankow", "Grundschule", "d@example.org"),
    ):
        store.upsert_schule({"bsn": bsn, "name": name, "bezirk": bez, "schulform": form,
                             "email": mail, "website": f"https://{bsn.lower()}.example.org"})
    # Alpha hat schon einen künftigen Termin
    store.upsert_termin_manuell({"schule_bsn": "02G01", "titel": "Tag der offenen Tür",
                                 "start_datum": "2099-09-18", "status": "ungeprueft"})
    store.set_setting("smtp_host", "mail.example.org")
    store.set_setting("smtp_from", "kinderkram@mekotools.de")
    store.set_setting("smtp_reply_to", "kinderkram@mekotools.de")
    store.set_setting("mail_betreff", "Frage {schule}")
    store.set_setting("mail_text", "Hallo, wann ist Ihr Tag der offenen Tür? ({bezirk})")
    monkeypatch.setattr(A, "_store", lambda request: store)
    with TestClient(app) as c:
        c.store = store
        yield c
    store.close()


def namen(client, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return [s["name"] for s in client.get("/api/admin/schulen?" + qs).json()]


def test_filter_nach_bezirk_und_schulform(client):
    assert namen(client, bezirk="friedrichshain-kreuzberg") == ["Alpha-Grundschule", "Beta-Grundschule"]
    assert namen(client, schulform="Grundschule") == ["Alpha-Grundschule", "Beta-Grundschule", "Delta-Grundschule"]
    assert namen(client, bezirk="pankow", schulform="Grundschule") == ["Delta-Grundschule"]


def test_ohne_termin_blendet_schulen_mit_termin_aus(client):
    alle = client.get("/api/admin/schulen").json()
    assert {s["bsn"] for s in alle if s["hat_termin"]} == {"02G01"}
    assert alle[0]["naechster_termin"] == "2099-09-18"
    ohne = namen(client, ohne_termin="true")
    assert "Alpha-Grundschule" not in ohne
    assert len(ohne) == 3


def test_nur_mit_email_und_vorhandener_status(client):
    assert namen(client, nur_mit_email="true") == ["Alpha-Grundschule", "Beta-Grundschule", "Delta-Grundschule"]


def test_schul_filter_liefert_frontend_bezeichnungen(client):
    f = client.get("/api/admin/schul-filter").json()
    labels = {b["key"]: b["label"] for b in f["bezirke"]}
    assert labels.get("friedrichshain-kreuzberg") == "Friedrichshain-Kreuzberg"
    assert "pankow" in labels
    assert f["schulformen"] == ["Grundschule", "Gymnasium"]


def test_sammel_mail_prueft_erst_und_sendet_dann(client, monkeypatch):
    gesendet = []
    monkeypatch.setattr(A, "_sende_mail",
                        lambda store, an, betreff, nachricht, reply_to=None:
                        gesendet.append((an, betreff, nachricht, reply_to)))
    d = client.post("/api/admin/schulen/mail-batch", json={
        "bsn": ["02G02", "02G03"], "trocken": True, "betreff": "Frage {schule}",
        "text": "Hallo {bezirk}"}).json()
    assert d["trocken"] is True and d["gesendet"] == 0 and not gesendet
    assert d["ergebnisse"][0]["betreff"] == "Frage Beta-Grundschule"
    assert d["ergebnisse"][1]["grund"] == "keine E-Mail-Adresse hinterlegt"

    d2 = client.post("/api/admin/schulen/mail-batch", json={
        "bsn": ["02G02"], "betreff": "Frage {schule}", "text": "Hallo {bezirk}",
        "reply_to": "antwort@mekotools.de"}).json()
    assert d2["gesendet"] == 1
    an, betreff, nachricht, reply = gesendet[0]
    assert an == "b@example.org" and betreff == "Frage Beta-Grundschule"
    assert "friedrichshain-kreuzberg" in nachricht and reply == "antwort@mekotools.de"


def test_sammel_mail_meldet_fehlende_adresse_und_grenze(client, monkeypatch):
    def fake_send(store, an, betreff, nachricht, reply_to=None):
        """Wie ein echter Versand: schreibt ins Protokoll (Grundlage der Bremse)."""
        i = store.starte_mail_versand(an, betreff)
        store.beende_mail_versand(i, ok=True, fehler=None)

    monkeypatch.setattr(A, "_sende_mail", fake_send)
    client.store.set_setting("mail_max_pro_tag", "0")
    leer = client.post("/api/admin/schulen/mail-batch", json={"bsn": []})
    assert leer.status_code == 422
    zu_viel = client.post("/api/admin/schulen/mail-batch",
                          json={"bsn": [f"02G{i:02d}" for i in range(101)]})
    assert zu_viel.status_code == 422
    client.store.set_setting("mail_max_pro_tag", "1")
    d = client.post("/api/admin/schulen/mail-batch",
                    json={"bsn": ["02G02", "02G04"], "betreff": "x", "text": "y"}).json()
    assert d["gesendet"] == 1
    assert "Tagesgrenze" in d["abbruch"]
    assert "nicht gesendet" in d["ergebnisse"][1]["grund"]


def test_sammel_recherche_laeuft_nur_fuer_die_auswahl(client, monkeypatch):
    from app.recherche import kern
    gesehen = {}

    def fake_lauf(store, *, limit=20, nur_bsn=None, dry_run=False, bezirk=None,
                  schulform=None, konfig=None, client=None, suche=None, bsn_liste=None):
        gesehen.update(limit=limit, bsn_liste=bsn_liste, dry_run=dry_run)
        return {"geprueft": len(bsn_liste or []), "belegt": 0, "status": {}, "schulen": []}

    monkeypatch.setattr(kern, "lauf", fake_lauf)
    r = client.post("/api/admin/recherche/lauf", json={"bsn": ["02G02", "02G04"], "dry_run": True})
    assert r.status_code == 202
    assert r.json()["anzahl_auswahl"] == 2
    for _ in range(50):
        if gesehen:
            break
        import time
        time.sleep(0.05)
    assert gesehen["bsn_liste"] == ["02G02", "02G04"]
    assert gesehen["dry_run"] is True


def test_store_liefert_nur_die_ausgewaehlten_schulen_mit_website(client):
    from app.recherche import kern
    k = kern.schul_kandidaten(client.store, bsn_liste=["02G04"])
    assert [s["bsn"] for s in k] == ["02G04"]
