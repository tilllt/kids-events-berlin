"""Change 013: E-Mail-Versand und -Empfang (Postfach kinderkram@mekotools.de)."""
import email

import pytest

from app import mail as M
from app.store import Store


def _store(tmp_path, **settings):
    s = Store(tmp_path / "mail.db")
    basis = {"smtp_host": "w00d77ee.kasserver.com", "smtp_port": "465",
             "smtp_from": "kinderkram@mekotools.de", "smtp_user": "kinderkram@mekotools.de",
             "smtp_pass": "geheim", "smtp_reply_to": "kinderkram@mekotools.de",
             "imap_host": "w00d77ee.kasserver.com", "imap_port": "993",
             "mail_betreff": "Frage zum Tag der offenen Tür",
             "mail_text": "Hallo {schule}, wann ist Ihr Tag der offenen Tür?"}
    basis.update(settings)
    for k, v in basis.items():
        s.set_setting(k, str(v))
    return s


class FakeSMTP:
    """Minimaler SMTP-Ersatz: merkt sich die gesendete Nachricht."""

    def __init__(self, *a, **k):
        self.gesendet = []
        self.gemeldet = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, user, pw):
        self.gemeldet = (user, pw)

    def noop(self):
        pass

    def quit(self):
        pass

    def send_message(self, msg):
        self.gesendet.append(msg)


def test_konfiguration_bildet_die_oberflaechen_schluessel_ab(tmp_path):
    s = _store(tmp_path)
    k = M.konfiguration(s)
    assert k["mail_smtp_host"] == "w00d77ee.kasserver.com"
    assert k["mail_smtp_port"] == "465"
    assert k["mail_smtp_verschluesselung"] == "ssl"
    assert k["mail_imap_host"] == "w00d77ee.kasserver.com" and k["mail_imap_port"] == "993"
    assert k["mail_adresse"] == "kinderkram@mekotools.de"
    assert k["mail_reply_to"] == "kinderkram@mekotools.de"
    assert k["mail_betreff"] == "Frage zum Tag der offenen Tür"
    assert M.fehlende_angaben(k) == []
    assert M.redigiere(k)["mail_passwort_gesetzt"] is True
    # Geheimnisse verlassen den Server nicht — die Antwort sagt nur, DASS eines da ist
    r = M.redigiere(k)
    assert "mail_passwort" not in r and "smtp_pass" not in r
    assert r["mail_passwort_gesetzt"] is True
    s.close()


def test_fehlende_angaben_werden_genannt(tmp_path):
    s = Store(tmp_path / "leer.db")
    k = M.konfiguration(s)
    fehlt = M.fehlende_angaben(k)
    assert "mail_passwort" in fehlt
    assert M.teste_smtp(k)["ok"] is False
    s.close()


def test_verschluesselung_aus_dem_port(tmp_path):
    s = _store(tmp_path, smtp_port="587", smtp_verschluesselung="")
    assert M.konfiguration(s)["mail_smtp_verschluesselung"] == "starttls"
    s.set_setting("smtp_port", "25")
    s.set_setting("smtp_verschluesselung", "keine")
    assert M.konfiguration(s)["mail_smtp_verschluesselung"] == "keine"
    s.close()


def test_versand_setzt_reply_to_betreff_und_fuellt_platzhalter(tmp_path, monkeypatch):
    s = _store(tmp_path)
    fake = FakeSMTP()
    # echten _smtp-Weg laufen lassen (Port/SSL-Wahl + Login), nur den Server ersetzen
    monkeypatch.setattr(M.smtplib, "SMTP_SSL",
                        lambda host, port, timeout=None, context=None: fake)
    erg = M.sende(s, "grundschule@example.org", schule="Aziz-Nesin-Grundschule")
    assert erg["ok"] and erg["reply_to"] == "kinderkram@mekotools.de"
    msg = fake.gesendet[0]
    assert msg["To"] == "grundschule@example.org"
    assert msg["Reply-To"] == "kinderkram@mekotools.de"
    assert msg["From"] == "Kinderkram Berlin <kinderkram@mekotools.de>"
    assert msg["Subject"] == "Frage zum Tag der offenen Tür"
    assert "Aziz-Nesin-Grundschule" in msg.get_content()
    assert fake.gemeldet == ("kinderkram@mekotools.de", "geheim")
    protokoll = s.mail_letzte(1)[0]
    assert protokoll["an"] == "grundschule@example.org" and protokoll["ok"] == 1
    s.close()


def test_fehlversand_wird_protokolliert_und_gemeldet(tmp_path, monkeypatch):
    s = _store(tmp_path)

    def kaputt(k, timeout=25.0):
        raise OSError("Connection refused")

    monkeypatch.setattr(M, "_smtp", kaputt)
    with pytest.raises(M.MailFehler) as e:
        M.sende(s, "x@example.org")
    assert "Connection refused" in str(e.value)
    assert s.mail_letzte(1)[0]["ok"] == 0
    assert "Connection refused" in s.mail_letzte(1)[0]["fehler"]
    s.close()


def test_tagesbremse_verhindert_massenversand(tmp_path, monkeypatch):
    s = _store(tmp_path, mail_max_pro_tag="2", mail_absender_pro_stunde="0")
    monkeypatch.setattr(M, "_smtp", lambda k, timeout=25.0: FakeSMTP())
    M.sende(s, "a@example.org"); M.sende(s, "b@example.org")
    assert s.mail_versand_erlaubt() is False
    with pytest.raises(M.MailFehler) as e:
        M.sende(s, "c@example.org")
    assert "Tagesgrenze" in str(e.value)
    assert s.mail_versand_zaehler()["heute"] == 2
    s.close()


def test_stundengrenze(tmp_path, monkeypatch):
    s = _store(tmp_path, mail_absender_pro_stunde="1")
    monkeypatch.setattr(M, "_smtp", lambda k, timeout=25.0: FakeSMTP())
    M.sende(s, "a@example.org")
    with pytest.raises(M.MailFehler) as e:
        M.sende(s, "b@example.org")
    assert "Stundengrenze" in str(e.value)
    s.close()


class FakeIMAP:
    def __init__(self, roh: bytes):
        self.roh = roh
        self.gelesen = False

    def login(self, user, pw):
        assert user == "kinderkram@mekotools.de" and pw == "geheim"

    def select(self, box, readonly=False):
        assert box == "INBOX"
        return "OK", [b"1"]

    def search(self, *a, **k):
        return "OK", [b"7"]

    def fetch(self, uid, was):
        return "OK", [(b"1 (RFC822 {n}", self.roh)]

    def logout(self):
        self.gelesen = True

    def list(self):
        return "OK", [b'(\\HasNoChildren) "." "INBOX"', b'(\\HasNoChildren) "." "Gesendet"']


ROH = """From: Sekretariat <sekretariat@aziz-nesin-schule.de>
To: kinderkram@mekotools.de
Subject: =?UTF-8?Q?Tag_der_offenen_T=C3=BCr?=
Date: Mon, 14 Sep 2026 09:12:00 +0200
Content-Type: text/plain; charset=utf-8

Guten Tag, unser Tag der offenen Tür ist am 18.09.2026 von 16 bis 18 Uhr.
""".encode("utf-8")


def test_postfach_abrufen_liest_ungelesene(tmp_path, monkeypatch):
    s = _store(tmp_path)
    fake = FakeIMAP(ROH)
    monkeypatch.setattr(M, "_imap", lambda k, timeout=25.0: fake)
    msgs = M.hole_nachrichten(M.konfiguration(s), limit=5)
    assert len(msgs) == 1
    assert "aziz-nesin-schule.de" in msgs[0]["von"]
    assert "Tag der offenen Tür" in msgs[0]["betreff"]      # MIME-Kopfzeile dekodiert
    assert "18.09.2026" in msgs[0]["text"]
    assert fake.gelesen
    assert M.teste_imap(M.konfiguration(s))["ok"] is True
    s.close()


def test_postfachfehler_meldet_klartext(tmp_path, monkeypatch):
    s = _store(tmp_path)

    def kaputt(k, timeout=25.0):
        raise OSError("kein Netz")

    monkeypatch.setattr(M, "_imap", kaputt)
    with pytest.raises(M.MailFehler) as e:
        M.hole_nachrichten(M.konfiguration(s))
    assert "nicht erreichbar" in str(e.value)
    assert M.teste_imap(M.konfiguration(s))["ok"] is False
    s.close()


def test_vorlage_kommt_aus_betreff_und_nachricht(tmp_path):
    from app import admin_api as A
    s = _store(tmp_path, mail_betreff="Termin?", mail_text="Hallo {schule}")
    text = A._mail_vorlage(s)
    assert text.startswith("Betreff: Termin?")
    assert "Hallo {schule}" in text
    s.set_setting("mail_text", "")
    s.set_setting("mail_vorlage", "Betreff: Alt\n\nAlter Text")
    assert A._mail_vorlage(s).startswith("Betreff: Alt")
    s.close()
