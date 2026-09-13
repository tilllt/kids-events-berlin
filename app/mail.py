"""E-Mail-Versand und -Empfang (Change 013).

Zweck: Schulen, deren Tag der offenen Tür weder auf der eigenen Website noch
über die Websuche zu finden war, per Mail danach fragen — und die Antworten
wieder ins Tool holen. Bewusst mit der Standardbibliothek (smtplib/imaplib),
damit dafür kein Fremddienst und keine Zusatzabhängigkeit nötig ist.

Einstellungen kommen aus der Datenbank (Admin-GUI), nicht aus Umgebungsvariablen:
Adresse, Passwort, SMTP-/IMAP-Host und -Port, Verschlüsselung sowie getrennt
Reply-To, Betreff und Nachrichtentext. Die Zugangsdaten erscheinen nie in einer
API-Antwort (siehe `redigiere`).

Versand-Bremse: `mail_max_pro_tag` begrenzt die ausgehenden Mails je Tag, damit
ein Fehllauf nicht 700 Schulen anschreibt. Jeder Versand steht in `mail_versand`.
"""
from __future__ import annotations

import imaplib
import smtplib
import ssl
from datetime import datetime
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr

from .model import TZ_BERLIN

# Interne Namen <- App-Einstellungen (EINE Vokabel: die vorhandenen
# smtp_*/imap_*/mail_*-Schlüssel der Oberfläche, siehe `konfiguration`).
KONFIG_STANDARD = {
    "mail_aktiv": "0",
    "mail_adresse": "kinderkram@mekotools.de",
    "mail_absendername": "Kinderkram Berlin",
    "mail_passwort": "",
    "mail_smtp_host": "w00d77ee.kasserver.com",
    "mail_smtp_port": "465",
    "mail_smtp_verschluesselung": "ssl",     # ssl | starttls | keine
    "mail_imap_host": "w00d77ee.kasserver.com",
    "mail_imap_port": "993",
    "mail_imap_verschluesselung": "ssl",     # ssl | keine
    "mail_reply_to": "kinderkram@mekotools.de",
    "mail_betreff": "Kurze Frage: Wann ist Ihr Tag der offenen Tür?",
    "mail_nachricht": (
        "Guten Tag,\n"
        "\n"
        "wir sammeln für den Kinderkram Berlin die Tage der offenen Tür der\n"
        "Berliner Grundschulen und haben den Termin Ihrer Schule "
        "({schule}) weder auf Ihrer Website noch in Ihrem Kalender gefunden.\n"
        "\n"
        "Könnten Sie uns kurz mitteilen, wann Ihr Tag der offenen Tür "
        "stattfindet (Datum und Uhrzeit)? Eine kurze Antwort auf diese Mail "
        "genügt.\n"
        "\n"
        "Vielen Dank und freundliche Grüße\n"
        "Kinderkram Berlin\n"
    ),
    "mail_max_pro_tag": "40",
    "mail_absender_pro_stunde": "20",
}

GEHEIM = ("mail_passwort", "smtp_pass")


class MailFehler(RuntimeError):
    """Klartext-Fehler für die Oberfläche (kein stiller Ausfall)."""


def _s(store, key: str, standard: str = "") -> str:
    wert = store.get_setting(key)
    wert = "" if wert is None else str(wert).strip()
    return wert or standard


def konfiguration(store) -> dict:
    """Einstellungen der Oberfläche auf die internen Namen abbilden.

    Quelle sind die vorhandenen Schlüssel (`smtp_*`, `imap_*`, `mail_*`), damit
    es nur EINE Vokabel gibt und die Werte im Admin sichtbar bleiben.
    """
    k = dict(KONFIG_STANDARD)
    k["smtp_pass"] = _s(store, "smtp_pass")
    k["smtp_verschluesselung"] = _s(store, "smtp_verschluesselung")
    k["mail_adresse"] = _s(store, "smtp_from") or _s(store, "smtp_user") or k["mail_adresse"]
    k["mail_passwort"] = k["smtp_pass"] or _s(store, "mail_passwort")
    k["mail_smtp_host"] = _s(store, "smtp_host", k["mail_smtp_host"])
    k["mail_smtp_port"] = _s(store, "smtp_port", k["mail_smtp_port"])
    k["mail_smtp_verschluesselung"] = (k["smtp_verschluesselung"].lower()
                                       or ("ssl" if k["mail_smtp_port"] == "465" else "starttls"))
    k["mail_imap_host"] = _s(store, "imap_host", k["mail_smtp_host"])
    k["mail_imap_port"] = _s(store, "imap_port", k["mail_imap_port"])
    k["mail_imap_verschluesselung"] = _s(store, "imap_verschluesselung", "ssl")
    k["mail_reply_to"] = _s(store, "smtp_reply_to", k["mail_adresse"])
    k["mail_betreff"] = _s(store, "mail_betreff", k["mail_betreff"])
    k["mail_nachricht"] = _s(store, "mail_text", k["mail_nachricht"])
    for key in ("mail_max_pro_tag", "mail_absender_pro_stunde"):
        k[key] = _s(store, key, k[key])
    k["mail_aktiv"] = _s(store, "mail_aktiv", k["mail_aktiv"])
    # Rückwärts: das Postfach ist der Absender — ein Wert, zwei Sichten
    k["imap_host"] = k["mail_imap_host"]
    k["imap_port"] = k["mail_imap_port"]
    k["smtp_host"] = k["mail_smtp_host"]
    k["smtp_port"] = k["mail_smtp_port"]
    k["smtp_user"] = _s(store, "smtp_user", k["mail_adresse"])
    k["smtp_from"] = _s(store, "smtp_from", k["mail_adresse"])
    k["smtp_reply_to"] = k["mail_reply_to"]
    k["mail_text"] = k["mail_nachricht"]
    return k


def redigiere(k: dict) -> dict:
    """Konfiguration für die API-Antwort: Geheimnisse nie im Klartext."""
    raus = {key: wert for key, wert in k.items() if key not in GEHEIM}
    raus["mail_passwort_gesetzt"] = bool(str(k.get("mail_passwort") or "").strip())
    return raus


def fehlende_angaben(k: dict) -> list[str]:
    fehlt = [key for key in ("mail_adresse", "mail_passwort", "mail_smtp_host",
                             "mail_imap_host") if not str(k.get(key) or "").strip()]
    return fehlt


def nachricht_fuellen(vorlage: str, schule: str = "", zusatz: dict | None = None) -> str:
    """Platzhalter füllen. Unbekannte Platzhalter bleiben stehen (kein Absturz)."""
    werte = {"schule": schule, "heute": datetime.now(TZ_BERLIN).strftime("%d.%m.%Y")}
    werte.update(zusatz or {})
    raus = vorlage
    for key, wert in werte.items():
        raus = raus.replace("{" + key + "}", str(wert))
    return raus


def _smtp(k: dict, timeout: float = 25.0) -> smtplib.SMTP:
    host, port = k["mail_smtp_host"], int(k["mail_smtp_port"] or 465)
    art = str(k.get("mail_smtp_verschluesselung") or "ssl").lower()
    if art == "ssl":
        s = smtplib.SMTP_SSL(host, port, timeout=timeout,
                             context=ssl.create_default_context())
    else:
        s = smtplib.SMTP(host, port, timeout=timeout)
        if art == "starttls":
            s.starttls(context=ssl.create_default_context())
    s.login(str(k["mail_adresse"]), str(k["mail_passwort"]))
    return s


def teste_smtp(k: dict) -> dict:
    """Login prüfen, ohne eine Mail zu senden."""
    fehlt = fehlende_angaben(k)
    if fehlt:
        return {"ok": False, "fehler": "Fehlende Angaben: " + ", ".join(fehlt)}
    try:
        s = _smtp(k)
        try:
            s.noop()
        finally:
            s.quit()
    except Exception as e:  # noqa: BLE001 — jede Ursache wird im Klartext gemeldet
        return {"ok": False, "fehler": f"{type(e).__name__}: {e}"}
    return {"ok": True, "fehler": None, "server": f"{k['mail_smtp_host']}:{k['mail_smtp_port']}"}


def sende(store, an: str, *, betreff: str | None = None, text: str | None = None,
          schule: str = "", k: dict | None = None, antwort_an: str | None = None,
          kopfzeilen: dict | None = None) -> dict:
    """Eine Mail senden und den Versand protokollieren (auch Fehlversuche)."""
    k = k or konfiguration(store)
    fehlt = fehlende_angaben(k)
    if fehlt:
        raise MailFehler("E-Mail ist noch nicht vollständig eingerichtet: "
                         + ", ".join(fehlt))
    if not store.mail_versand_erlaubt():
        raise MailFehler(store.mail_versand_bremse_grund())
    adresse = parseaddr(an)[1] or an
    betreff = nachricht_fuellen(betreff if betreff is not None else k["mail_betreff"],
                               schule)
    text = nachricht_fuellen(text if text is not None else k["mail_nachricht"], schule)
    msg = EmailMessage()
    msg["From"] = f"{k.get('mail_absendername') or 'Kinderkram'} <{k['mail_adresse']}>"
    msg["To"] = adresse
    antwort = (antwort_an or k.get("mail_reply_to") or k["mail_adresse"]).strip()
    if antwort:
        msg["Reply-To"] = antwort
    msg["Subject"] = betreff
    for name, wert in (kopfzeilen or {}).items():
        del msg[name]
        msg[name] = str(wert)
    msg.set_content(text)
    eintrag = store.starte_mail_versand(adresse, betreff, schule or None)
    try:
        s = _smtp(k)
        try:
            s.send_message(msg)
        finally:
            s.quit()
    except Exception as e:  # noqa: BLE001
        store.beende_mail_versand(eintrag, ok=False, fehler=f"{type(e).__name__}: {e}")
        raise MailFehler(f"Versand an {adresse} fehlgeschlagen: {type(e).__name__}: {e}")
    store.beende_mail_versand(eintrag, ok=True, fehler=None)
    return {"ok": True, "an": adresse, "betreff": betreff, "reply_to": antwort,
            "id": eintrag}


def teste_versand(store, an: str, k: dict | None = None) -> dict:
    """Echte Testmail (zählt gegen die Tagesbremse und wird protokolliert)."""
    k = k or konfiguration(store)
    return sende(store, an, betreff="Testmail aus der Kinderkram-Verwaltung",
                 text=("Diese Nachricht ist ein Test aus der Verwaltungsoberfläche.\n"
                       "Versand, Reply-To und Protokollierung funktionieren.\n"),
                 k=k)


def _dekodiere(wert: str | None) -> str:
    if not wert:
        return ""
    try:
        return str(make_header(decode_header(wert)))
    except Exception:  # noqa: BLE001 — kaputte Kopfzeile darf den Abruf nicht stoppen
        return wert


def _imap(k: dict, timeout: float = 25.0):
    host, port = k["mail_imap_host"], int(k["mail_imap_port"] or 993)
    art = str(k.get("mail_imap_verschluesselung") or "ssl").lower()
    if art == "ssl":
        m = imaplib.IMAP4_SSL(host, port, timeout=timeout,
                              ssl_context=ssl.create_default_context())
    else:
        m = imaplib.IMAP4(host, port, timeout=timeout)
    m.login(str(k["mail_adresse"]), str(k["mail_passwort"]))
    return m


def teste_imap(k: dict) -> dict:
    """Login und Ordnerliste prüfen."""
    fehlt = fehlende_angaben(k)
    if fehlt:
        return {"ok": False, "fehler": "Fehlende Angaben: " + ", ".join(fehlt)}
    try:
        m = _imap(k)
        try:
            typ, daten = m.select("INBOX")
            typ2, ordner = m.list()
        finally:
            try:
                m.logout()
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "fehler": f"{type(e).__name__}: {e}"}
    return {"ok": True, "fehler": None, "ordner": len(ordner or []), "inbox": typ == "OK"}


def hole_nachrichten(k: dict, limit: int = 20, nur_ungelesene: bool = True) -> list[dict]:
    """Ungelesene Nachrichten aus INBOX holen (Kopfzeilen + Text)."""
    fehlt = fehlende_angaben(k)
    if fehlt:
        raise MailFehler("E-Mail ist noch nicht vollständig eingerichtet: "
                         + ", ".join(fehlt))
    raus: list[dict] = []
    try:
        m = _imap(k)
    except Exception as e:  # noqa: BLE001
        raise MailFehler(f"Postfach nicht erreichbar: {type(e).__name__}: {e}")
    try:
        m.select("INBOX", readonly=False)
        kriterium = "(UNSEEN)" if nur_ungelesene else "ALL"
        typ, daten = m.search(None, kriterium)
        if typ != "OK":
            raise MailFehler(f"Suche im Postfach fehlgeschlagen: {typ}")
        ids = (daten[0] or b"").split()[-limit:]
        for uid in reversed(ids):
            typ, roh = m.fetch(uid, "(RFC822)")
            if typ != "OK" or not roh or not isinstance(roh[0], tuple):
                continue
            nachricht = email_message_from_bytes(roh[0][1])
            raus.append({
                "uid": uid.decode(),
                "von": _dekodiere(nachricht.get("From")),
                "an": _dekodiere(nachricht.get("To")),
                "betreff": _dekodiere(nachricht.get("Subject")),
                "datum": _dekodiere(nachricht.get("Date")),
                "text": nachricht_text(nachricht),
            })
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass
    return raus


def email_message_from_bytes(roh: bytes):
    import email
    return email.message_from_bytes(roh)


def nachricht_text(nachricht, max_zeichen: int = 6000) -> str:
    """Klartext einer Mail; HTML wird grob entkleidet (kein Renderer)."""
    if nachricht.is_multipart():
        for teil in nachricht.walk():
            if teil.get_content_type() == "text/plain" and "attachment" not in str(
                    teil.get("Content-Disposition") or ""):
                try:
                    return teil.get_payload(decode=True).decode(
                        teil.get_content_charset() or "utf-8", "replace")[:max_zeichen]
                except Exception:  # noqa: BLE001
                    continue
        for teil in nachricht.walk():
            if teil.get_content_type() == "text/html":
                try:
                    roh = teil.get_payload(decode=True).decode(
                        teil.get_content_charset() or "utf-8", "replace")
                except Exception:  # noqa: BLE001
                    continue
                import re
                return re.sub(r"<[^>]+>", " ", roh)[:max_zeichen]
        return ""
    try:
        return (nachricht.get_payload(decode=True) or b"").decode(
            nachricht.get_content_charset() or "utf-8", "replace")[:max_zeichen]
    except Exception:  # noqa: BLE001
        return ""
