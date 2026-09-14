"""Admin-API (offen; Auth-Middleware folgt in einem späteren Change).

Alle konfigurierbaren Optionen (Quellen, Regeln, Einstellungen) laufen über
diese Endpunkte — sie sind der einzige Schreibweg im Betrieb. Deutsche,
verständliche Fehlermeldungen; nichts Stilles.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from . import ort_ki
from .geo import adresse_amtlich, ort_koordinaten
from .model import TZ_BERLIN, iso_utc
from .regeln import validate_regeln_yaml

router = APIRouter(prefix="/api/admin")

# Standardtext für die Termin-Anfrage-Mail an Schulen (Vorlage aus der
# Schul-Erkundung, User-Vorgabe). Platzhalter werden beim Senden ersetzt:
# {schule}, {schulform}, {bezirk}, {jahr}.
DEFAULT_MAIL_BETREFF = "Tage der offenen Tür {jahr} – Bitte um Terminmitteilung"
DEFAULT_MAIL_REPLY_TO = "kinderkram@mekotools.de"
DEFAULT_MAIL_HOST = "w00d77ee.kasserver.com"
DEFAULT_MAIL_TEXT = """Guten Tag,

wir betreiben den Veranstaltungskalender „kinderkram" (kinderkram.cia-spandau.de),
auf dem Familien mit Kindern Veranstaltungen in Berlin finden – unter anderem
die Tage der offenen Tür und Informationsveranstaltungen der Schulen.

Für die {schulform} {schule} ({bezirk}) konnten wir im Internet keinen
öffentlichen Termin finden. Darf ich Sie bitten, uns kurz mitzuteilen:

1. Tag der offenen Tür / Informationsnachmittag: Datum + Uhrzeit
2. Ggf. Anmeldezeitraum / Schnuppertage
3. Falls vorhanden: Link zu einer öffentlichen Terminübersicht

Die Angaben veröffentlichen wir kostenfrei als knappe Terminfakten mit Link auf
Ihre Website. Auf Wunsch nehmen wir die Schule selbstverständlich wieder aus dem
Kalender.

Vielen Dank und freundliche Grüße
Kinderkram Berlin
kinderkram.cia-spandau.de"""


DEFAULT_MAIL_VORLAGE = """Betreff: Tage der offenen Tür {jahr} – Bitte um Terminmitteilung

Sehr geehrte Damen und Herren,

wir betreiben den Veranstaltungskalender „kinderkram“ (kinderkram.cia-spandau.de),
auf dem Familien mit Kindern Veranstaltungen in Berlin finden – unter anderem
die Tage der offenen Tür und Informationsveranstaltungen der Schulen.

Für die {schulform} {schule} ({bezirk}) konnten wir im Internet keinen
öffentlichen Terminkalender finden. Darf ich Sie bitten, uns die Termine
für das laufende Schuljahr mitzuteilen:

1. Tag der offenen Tür / Informationsnachmittag: Datum + Uhrzeit
2. Ggf. Anmeldezeitraum / Schnuppertage
3. Falls vorhanden: Link zu einer öffentlichen Terminübersicht

Die Angaben werden kostenfrei und ohne weitere Verwendung Ihrer Inhalte
(keine Texte, keine Bilder) als knappe Terminfakten mit Link auf Ihre
Website veröffentlicht. Auf Wunsch nehmen wir die Schule selbstverständlich
wieder aus dem Kalender.

Vielen Dank und freundliche Grüße
[Name / Einrichtung]
[Kontakt]
"""


def _mail_vorlage(store) -> str:
    """Mail-Vorlage als Text — aus den getrennten Feldern Betreff + Nachricht.

    Die Oberfläche pflegt Betreff und Nachricht getrennt (plus Reply-To). Intern
    setzt der bestehende Versandweg die erste Zeile „Betreff: …" voran, deshalb
    wird hier zusammengesetzt statt den Versandweg zu duplizieren. Ist nichts
    gepflegt, greift die alte Sammelvorlage.
    """
    betreff = (store.get_setting("mail_betreff") or "").strip()
    text = (store.get_setting("mail_text") or "").strip()
    if text:
        return f"Betreff: {betreff or DEFAULT_MAIL_BETREFF}\n\n{text}"
    v = (store.get_setting("mail_vorlage") or "").strip()
    return v or DEFAULT_MAIL_VORLAGE


class AnfrageBody(BaseModel):
    # Getrennte Felder (User-Vorgabe): Betreff und Nachricht einzeln, dazu ein
    # optionales Reply-To. `text` bleibt für Aufrufer, die alles in einem Feld
    # schicken (erste Zeile "Betreff: …" wird dann als Subject gelesen).
    text: str = ""
    betreff: str = ""
    reply_to: str = ""

TYPEN = {"feed", "regeln", "intern"}
QUELLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_SLUG_FELDER = {"quelle", "name", "typ", "url", "aktiv", "rate_limit_s", "menge_min",
                "menge_max", "horizont_tage", "robots", "notiz"}


def _store(request: Request):
    return request.app.state.store


def _public_source(s: dict, store) -> dict:
    runs = store.recent_runs(s["quelle"], limit=1)
    letzter = runs[0] if runs else None
    out = dict(s)
    out["aktiv"] = bool(out["aktiv"])
    out["letzter_lauf"] = letzter
    return out


def _body_felder(body: dict, erlaubt: set[str]) -> dict:
    return {k: v for k, v in body.items() if k in erlaubt}


# --- Quellen ----------------------------------------------------------------
@router.get("/sources")
def sources_list(request: Request):
    store = _store(request)
    return [_public_source(s, store) for s in store.list_sources()]


@router.get("/sources/{quelle}")
def source_get(quelle: str, request: Request):
    store = _store(request)
    s = store.get_source(quelle)
    if not s:
        raise HTTPException(404, f"Unbekannte Quelle: {quelle}")
    return _public_source(s, store)


@router.post("/sources", status_code=201)
def source_create(body: dict, request: Request):
    store = _store(request)
    quelle = (body.get("quelle") or "").strip()
    name = (body.get("name") or "").strip()
    typ = (body.get("typ") or "").strip()
    fehler = []
    if not QUELLE_RE.match(quelle):
        fehler.append("quelle: kleinbuchstaben, Zahlen und Bindestriche (2–64 Zeichen).")
    if not name:
        fehler.append("name fehlt (Anzeigename).")
    if typ not in TYPEN:
        fehler.append(f"typ muss eine sein von: {', '.join(sorted(TYPEN))}.")
    if body.get("url") and not str(body["url"]).startswith(("http://", "https://")):
        fehler.append("url muss mit http(s):// beginnen.")
    if fehler:
        raise HTTPException(422, {"message": "Validierung fehlgeschlagen.", "fehler": fehler})
    try:
        store.add_source(quelle, name, typ, body.get("url"),
                         aktiv=bool(body.get("aktiv", True)),
                         rate_limit_s=float(body.get("rate_limit_s", 1.0)),
                         menge_min=body.get("menge_min"), menge_max=body.get("menge_max"),
                         horizont_tage=int(body.get("horizont_tage", 60)),
                         robots=body.get("robots"), notiz=body.get("notiz"))
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    return _public_source(store.get_source(quelle), store)  # type: ignore[arg-type]


@router.put("/sources/{quelle}")
def source_update(quelle: str, body: dict, request: Request):
    store = _store(request)
    if not store.get_source(quelle):
        raise HTTPException(404, f"Unbekannte Quelle: {quelle}")
    felder = _body_felder(body, _SLUG_FELDER - {"quelle"})
    if "typ" in felder and felder["typ"] not in TYPEN:
        raise HTTPException(422, {"fehler": [f"typ muss eine sein von: {', '.join(sorted(TYPEN))}."]})
    try:
        store.update_source(quelle, **felder)
    except ValueError as e:
        raise HTTPException(404, str(e)) from None
    return _public_source(store.get_source(quelle), store)  # type: ignore[arg-type]


@router.delete("/sources/{quelle}", status_code=204)
def source_delete(quelle: str, request: Request):
    store = _store(request)
    try:
        store.delete_source(quelle)
    except ValueError as e:
        raise HTTPException(404, str(e)) from None


# --- Regeln ----------------------------------------------------------------
@router.get("/sources/{quelle}/regeln")
def regeln_get(quelle: str, request: Request):
    store = _store(request)
    if not store.get_source(quelle):
        raise HTTPException(404, f"Unbekannte Quelle: {quelle}")
    r = store.get_regeln(quelle)
    if not r:
        return {"quelle": quelle, "regel_yaml": "", "geaendert": None}
    return {"quelle": quelle, **r}


@router.put("/sources/{quelle}/regeln")
def regeln_put(quelle: str, body: dict, request: Request):
    store = _store(request)
    s = store.get_source(quelle)
    if not s:
        raise HTTPException(404, f"Unbekannte Quelle: {quelle}")
    if s["typ"] == "intern":
        raise HTTPException(409, {"fehler": ["Quelle vom Typ 'intern' hat keine Regeln (eigener Adapter)."]})
    regel_yaml = body.get("regel_yaml") or ""
    fehler = validate_regeln_yaml(regel_yaml, quelle)
    if fehler:
        raise HTTPException(422, {"message": "Regeln ungültig.", "fehler": fehler})
    store.set_regeln(quelle, regel_yaml)
    return {"quelle": quelle, "regel_yaml": regel_yaml, "geaendert": store.get_regeln(quelle)["geaendert"]}  # type: ignore[index]


@router.post("/sources/{quelle}/regeln/validate")
def regeln_validate(quelle: str, body: dict, request: Request):
    """Prüft Regel-YAML ohne zu speichern → {ok, fehler[]}."""
    regel_yaml = body.get("regel_yaml") or ""
    fehler = validate_regeln_yaml(regel_yaml, quelle)
    return {"ok": not fehler, "fehler": fehler}


# --- Läufe / Fehler --------------------------------------------------------
@router.get("/sources/{quelle}/run-latest")
def source_run_latest(quelle: str, request: Request, limit: int = Query(5, le=50)):
    store = _store(request)
    if not store.get_source(quelle):
        raise HTTPException(404, f"Unbekannte Quelle: {quelle}")
    runs = store.recent_runs(quelle, limit=limit)
    fehler = store.recent_errors(quelle, limit=10)
    return {"quelle": quelle, "runs": runs, "fehler": fehler}


@router.get("/runs")
def runs_list(request: Request, quelle: str | None = None, limit: int = Query(50, le=200)):
    store = _store(request)
    return store.recent_runs_all(quelle=quelle, limit=limit)


@router.get("/errors")
def errors_list(request: Request, quelle: str | None = None, limit: int = Query(50, le=200)):
    store = _store(request)
    return store.recent_errors(quelle, limit=limit) if quelle else store.recent_errors_all(limit=limit)


# --- Einstellungen ---------------------------------------------------------
@router.get("/settings")
def settings_get(request: Request):
    """Liefert die gespeicherten Einstellungen. Fehlt mail_vorlage, wird der
    Standardtext (DEFAULT_MAIL_VORLAGE) als Beispieltext mitgeliefert, damit
    die GUI immer einen sichtbaren Ausgangstext zeigt (User-Vorgabe 2026-09)."""
    store = _store(request)
    s = _redigiere_settings(store.all_settings())
    if not (s.get("mail_vorlage") or "").strip():
        s["mail_vorlage"] = DEFAULT_MAIL_VORLAGE
        s["mail_vorlage_ist_default"] = True
    # Change 013: leere Mail-Felder mit unseren Standardwerten anzeigen
    for key, wert in (("smtp_reply_to", DEFAULT_MAIL_REPLY_TO),
                      ("mail_betreff", DEFAULT_MAIL_BETREFF),
                      ("mail_text", DEFAULT_MAIL_TEXT),
                      ("smtp_host", DEFAULT_MAIL_HOST),
                      ("imap_host", DEFAULT_MAIL_HOST),
                      ("smtp_port", "465"), ("imap_port", "993"),
                      ("smtp_verschluesselung", "ssl")):
        if not (s.get(key) or "").strip():
            s[key] = wert
            s[key + "_ist_default"] = True
    if not (s.get("smtp_from") or "").strip():
        s["smtp_from"] = DEFAULT_MAIL_REPLY_TO
    if not (s.get("smtp_user") or "").strip():
        s["smtp_user"] = DEFAULT_MAIL_REPLY_TO
    return s


def _redigiere_settings(s: dict) -> dict:
    """Passwörter und Schlüssel verlassen den Server nie im Klartext."""
    raus = dict(s)
    for key in ("smtp_pass", "llm_api_key", "brave_api_key", "mail_passwort"):
        gesetzt = bool(str(raus.get(key) or "").strip())
        raus[key] = ""
        raus[key + "_gesetzt"] = gesetzt
    return raus


@router.put("/settings")
def settings_put(body: dict, request: Request):
    store = _store(request)
    erlaubt = {"scrape_interval_h", "admin_hinweis", "scrape_at",
               "smtp_host", "smtp_port", "smtp_user", "smtp_pass", "smtp_from",
               "smtp_reply_to", "mail_vorlage",
               # Change 010: LLM-Endpunkt der Schul-Recherche (frei konfigurierbar)
               "llm_base_url", "llm_model", "llm_api_key", "llm_timeout_s",
               "llm_extra_json", "recherche_aktiv", "recherche_max_schulen",
               "brave_api_key", "brave_monat_limit", "brave_tages_limit",
               "brave_anfragen_pro_s", "brave_websuche_aktiv",
               "brave_wiederholung_tage",
               # Change 013: Mail (getrennte Zeilen Reply-To/Betreff/Nachricht)
               "mail_betreff", "mail_text", "mail_aktiv", "mail_max_pro_tag",
               "mail_absender_pro_stunde", "smtp_verschluesselung",
               "imap_host", "imap_port", "imap_verschluesselung"}
    unbekannt = set(body) - erlaubt
    fehler = []
    for k in sorted(unbekannt):
        fehler.append(f"Unbekannte Einstellung '{k}' (erlaubt: {', '.join(sorted(erlaubt))}).")
    if "scrape_interval_h" in body:
        v_raw = (body["scrape_interval_h"] or "").strip()
        if v_raw:  # leer = Einstellung löschen (Uhrzeit-Modus)
            try:
                v = float(v_raw)
                if not 0.5 <= v <= 168:
                    raise ValueError
            except ValueError:
                fehler.append("scrape_interval_h muss eine Zahl zwischen 0.5 und 168 sein (oder leer).")
    if "scrape_at" in body:
        at = (body["scrape_at"] or "").strip()
        if at:
            try:
                h, m = (int(x) for x in at.split(":"))
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError
            except ValueError:
                fehler.append("scrape_at muss 'HH:MM' sein (z. B. 05:30) oder leer für Intervall-Modus.")
    if "llm_base_url" in body:
        url = (body["llm_base_url"] or "").strip()
        if url and not url.startswith(("http://", "https://")):
            fehler.append("llm_base_url muss mit http:// oder https:// beginnen "
                          "(z. B. http://192.168.178.140:8088/v1).")
    if "llm_timeout_s" in body:
        t = (body["llm_timeout_s"] or "").strip()
        if t:
            try:
                tv = float(t)
                if not 5 <= tv <= 600:
                    raise ValueError
            except ValueError:
                fehler.append("llm_timeout_s muss eine Zahl zwischen 5 und 600 sein.")
    if "llm_extra_json" in body:
        roh = (body["llm_extra_json"] or "").strip()
        if roh:
            try:
                if not isinstance(json.loads(roh), dict):
                    raise ValueError
            except ValueError:
                fehler.append("llm_extra_json muss ein JSON-Objekt sein, "
                              'z. B. {"chat_template_kwargs": {"enable_thinking": false}}.')
    if "smtp_port" in body or "imap_port" in body:
        for key in ("smtp_port", "imap_port"):
            if key in body:
                pv = (body[key] or "").strip()
                try:
                    pn = int(pv)
                    if not 1 <= pn <= 65535:
                        raise ValueError
                except ValueError:
                    fehler.append(f"{key} muss ein Port zwischen 1 und 65535 sein.")
    if "smtp_verschluesselung" in body and (body["smtp_verschluesselung"] or "").strip() \
            not in ("ssl", "starttls", "keine"):
        fehler.append("smtp_verschluesselung muss ssl, starttls oder keine sein.")
    if "imap_verschluesselung" in body and (body["imap_verschluesselung"] or "").strip() \
            not in ("ssl", "keine"):
        fehler.append("imap_verschluesselung muss ssl oder keine sein.")
    if "mail_max_pro_tag" in body:
        mv = (body["mail_max_pro_tag"] or "").strip()
        try:
            mn = int(mv)
            if not 0 <= mn <= 1000:
                raise ValueError
        except ValueError:
            fehler.append("mail_max_pro_tag muss zwischen 0 (aus) und 1000 liegen.")
    if "mail_aktiv" in body and str(body["mail_aktiv"]).strip() not in ("0", "1", "true", "false"):
        fehler.append("mail_aktiv muss 0 oder 1 sein.")
    if "recherche_max_schulen" in body:
        n = (body["recherche_max_schulen"] or "").strip()
        if n:
            try:
                nv = int(n)
                if not 1 <= nv <= 722:
                    raise ValueError
            except ValueError:
                fehler.append("recherche_max_schulen muss eine ganze Zahl zwischen 1 und 722 sein.")
    if fehler:
        raise HTTPException(422, {"message": "Einstellungen ungültig.", "fehler": fehler})
    for k, v in body.items():
        if k in erlaubt:
            store.set_setting(k, str(v))
    return _redigiere_settings(store.all_settings())


# --- Laufende Hintergrund-Laeufe -------------------------------------------
# Scrapes und Recherchen laufen in Threads. Sie werden hier gefuehrt, damit
# Tests (und ein Herunterfahren) auf sie warten koennen: Ohne das lief ein
# Scrape-Thread nach Testende weiter und stiess in einem spaeteren Test mit
# SQLite/lxml zusammen — die Suite brach mit einem Segfault ab (Exit 139).
# Entstanden 2026-09-13 aus einem Faulthandler-Protokoll.
LAUF_THREADS: list[threading.Thread] = []


def _thread_starten(ziel, name: str) -> threading.Thread:
    t = threading.Thread(target=ziel, name=name, daemon=True)
    LAUF_THREADS.append(t)
    t.start()
    LAUF_THREADS[:] = [x for x in LAUF_THREADS if x.is_alive()]
    return t


# --- LLM-Endpunkt der Recherche (Change 010) --------------------------------
@router.get("/llm")
def llm_get(request: Request):
    """Geltende LLM-Konfiguration (ohne Key-Inhalt, nur ob einer gesetzt ist)."""
    from .recherche.llm import konfiguration
    k = konfiguration(_store(request))
    k["llm_api_key_gesetzt"] = bool((k.get("llm_api_key") or "").strip())
    k.pop("llm_api_key", None)
    return k


@router.post("/llm/test")
def llm_test(request: Request, body: dict | None = None):
    """Testaufruf gegen den konfigurierten Endpunkt — Ergebnis immer sichtbar.

    Liefert 200 mit {"ok": true, …} oder {"ok": false, "fehler": …}; so kann die
    Oberfläche den echten Fehlertext anzeigen, statt nur „Fehler".
    """
    from .recherche.llm import konfiguration, test_verbindung
    store = _store(request)
    body = body or {}
    k = konfiguration(store)
    for key in ("llm_base_url", "llm_model", "llm_api_key", "llm_timeout_s",
                "llm_extra_json"):
        if key in body and str(body[key]).strip() != "":
            k[key] = str(body[key]).strip()
    return test_verbindung(k)


@router.get("/recherche")
def recherche_status(request: Request, nur_ohne_fund: bool = Query(False),
                     bezirk: str | None = Query(None), schulform: str | None = Query(None),
                     limit: int = Query(500, le=2000)):
    """Recherche-Stand je Schule + Zähler des letzten geprüften Laufs."""
    store = _store(request)
    daten = store.recherche_uebersicht(nur_ohne_fund=nur_ohne_fund, limit=limit,
                                      bezirk=bezirk, schulform=schulform)
    aktiv = (store.get_setting("recherche_aktiv") or "0").strip() in ("1", "true", "ja", "on")
    daten["lauf_aktiv"] = aktiv
    daten["max_schulen"] = int(store.get_setting("recherche_max_schulen") or 20)
    return daten


@router.post("/recherche/lauf", status_code=202)
def recherche_lauf_starten(request: Request, body: dict | None = None):
    """Startet einen Recherche-Lauf im Hintergrund (sequenziell, ein Schreiber)."""
    from .recherche import kern
    store = _store(request)
    body = body or {}
    if "limit" in body and str(body["limit"]).strip() != "":
        try:
            limit = int(body["limit"])
        except (TypeError, ValueError):
            raise HTTPException(422, {"fehler": ["limit muss eine Zahl sein."]}) from None
    else:
        try:
            limit = int(store.get_setting("recherche_max_schulen") or 20)
        except (TypeError, ValueError):
            limit = 20
    if not 1 <= limit <= 722:
        raise HTTPException(422, {"fehler": ["limit muss zwischen 1 und 722 liegen."]})
    nur_bsn = (body.get("nur_bsn") or "").strip() or None
    bezirk = (body.get("bezirk") or "").strip().lower() or None
    schulform = (body.get("schulform") or "").strip() or None
    dry_run = bool(body.get("dry_run"))
    bsn_liste = [str(b).strip() for b in (body.get("bsn") or []) if str(b).strip()]
    if bsn_liste:
        # Mehrfachauswahl aus der Oberfläche: genau diese Schulen prüfen
        limit = max(1, len(bsn_liste))
    ohne_termin = bool(body.get("ohne_termin"))

    def _lauf():
        try:
            zusammen = kern.lauf(store, limit=limit, nur_bsn=nur_bsn, dry_run=dry_run,
                                 bezirk=bezirk, schulform=schulform,
                                 bsn_liste=bsn_liste or None)
            store.set_setting("recherche_letzter_lauf", json.dumps(zusammen, ensure_ascii=False))
            print(f"[recherche] Lauf fertig: {zusammen['geprueft']} Schulen, "
                  f"{zusammen['belegt']} belegt, {zusammen['status']}", flush=True)
        except Exception as e:  # sichtbar statt still
            store.log_error("recherche", f"Recherche-Lauf fehlgeschlagen: {e}")
            print(f"[recherche] Lauf fehlgeschlagen: {e}", flush=True)

    _thread_starten(_lauf, "schul-recherche")
    return {"status": "gestartet", "limit": limit, "nur_bsn": nur_bsn,
            "anzahl_auswahl": len(bsn_liste), "ohne_termin": ohne_termin,
            "bezirk": bezirk, "schulform": schulform, "dry_run": dry_run}


@router.get("/recherche/letzter-lauf")
def recherche_letzter_lauf(request: Request):
    store = _store(request)
    roh = store.get_setting("recherche_letzter_lauf")
    if not roh:
        return {"vorhanden": False}
    try:
        d = json.loads(roh)
    except json.JSONDecodeError:
        return {"vorhanden": False, "fehler": "gespeicherter Lauf ist kein JSON"}
    d["vorhanden"] = True
    return d


# --- E-Mail: Versand und Empfang (Change 013) --------------------------------
@router.get("/mail")
def mail_status(request: Request):
    """Zustand des Postfachs: Konfiguration (ohne Passwort), Zähler, Protokoll."""
    from .mail import konfiguration as mail_konfig, fehlende_angaben, redigiere
    store = _store(request)
    k = mail_konfig(store)
    return {"konfig": redigiere(k), "fehlende_angaben": fehlende_angaben(k),
            "versand": store.mail_versand_zaehler(),
            "bremse": store.mail_versand_bremse_grund(),
            "letzte": store.mail_letzte(limit=20),
            "adresse": k["mail_adresse"], "reply_to": k["mail_reply_to"],
            "betreff": k["mail_betreff"]}


@router.post("/mail/test")
def mail_test(request: Request, body: dict | None = None):
    """SMTP- und IMAP-Login prüfen — ohne eine Mail zu senden."""
    from .mail import konfiguration as mail_konfig, teste_imap, teste_smtp
    store = _store(request)
    k = mail_konfig(store)
    for key, wert in (body or {}).items():
        if key in k and str(wert).strip() and key != "smtp_pass":
            k[key] = str(wert).strip()
    if (body or {}).get("smtp_pass"):
        k["mail_passwort"] = str(body["smtp_pass"])
    return {"smtp": teste_smtp(k), "imap": teste_imap(k)}


@router.post("/mail/testmail")
def mail_testmail(request: Request, body: dict | None = None):
    """Echte Testmail über das konfigurierte Postfach (wird protokolliert)."""
    from .mail import MailFehler, teste_versand
    store = _store(request)
    an = ((body or {}).get("an") or store.get_setting("smtp_reply_to")
          or DEFAULT_MAIL_REPLY_TO).strip()
    try:
        return teste_versand(store, an)
    except MailFehler as e:
        raise HTTPException(502, {"fehler": [str(e)]}) from e


@router.post("/mail/abrufen")
def mail_abrufen(request: Request, body: dict | None = None):
    """Ungelesene Nachrichten aus dem Postfach holen (Antworten der Schulen)."""
    from .mail import MailFehler, hole_nachrichten, konfiguration as mail_konfig
    store = _store(request)
    limit = int((body or {}).get("limit") or 20)
    nur_ungelesene = bool((body or {}).get("nur_ungelesene", True))
    try:
        nachrichten = hole_nachrichten(mail_konfig(store), limit=limit,
                                       nur_ungelesene=nur_ungelesene)
    except MailFehler as e:
        raise HTTPException(502, {"fehler": [str(e)]}) from e
    return {"anzahl": len(nachrichten), "nachrichten": nachrichten}


# --- Websuche (Brave) mit Kontingent-Verwaltung (Change 012) -----------------
def _int_oder_none(wert):
    try:
        return int(str(wert).strip())
    except (TypeError, ValueError):
        return None


@router.get("/brave")
def brave_status(request: Request):
    """Verbrauch gegen Budget + letzte Aufrufe (Grundlage der Drosselung)."""
    from .recherche import websearch
    store = _store(request)
    st = websearch.status(store)
    st["budget_fehler"] = websearch.budget_fehler(st)
    st["letzte"] = store.brave_letzte(limit=15)
    return st


@router.post("/brave/test")
def brave_test(request: Request, body: dict | None = None):
    """Eine echte Testsuche — zählt als eine Anfrage und wird so ausgewiesen."""
    from .recherche import websearch
    store = _store(request)
    body = body or {}
    konfig = websearch.konfiguration(store)
    if (body.get("brave_api_key") or "").strip():
        konfig["brave_api_key"] = body["brave_api_key"].strip()
    if not str(konfig.get("brave_api_key") or "").strip():
        return {"ok": False, "fehler": "Kein API-Key hinterlegt."}
    frage = (body.get("query") or "").strip() or '"Tag der offenen Tür" Berlin Grundschule 2026'
    try:
        suche = websearch.BraveSuche(store, konfig)
        daten = suche.suche(frage, count=3)
    except websearch.BraveFehler as e:
        st = websearch.status(store)
        return {"ok": False, "fehler": str(e), "query": frage,
                "verbraucht_monat": st["verbraucht_monat"], "monats_limit": st["monats_limit"]}
    urls = websearch.ergebnis_urls(daten)
    return {"ok": True, "query": frage, "treffer": len(urls), "urls": urls,
            "verbraucht_monat": websearch.status(store)["verbraucht_monat"],
            "monats_limit": websearch.status(store)["monats_limit"]}


@router.get("/brave/letzte")
def brave_letzte(request: Request, limit: int = Query(50, le=500)):
    return _store(request).brave_letzte(limit=limit)


# --- Dubletten über Quellen hinweg (Change 011) -----------------------------
@router.get("/dedupe")
def dedupe_pruefen(request: Request, quelle: str | None = Query(None)):
    """Bericht: dieselbe Veranstaltung bei mehreren Quellen (nichts wird geändert)."""
    return _store(request).merge_doppelte_events(dry_run=True, nur_quelle=quelle)


@router.post("/dedupe/anwenden")
def dedupe_anwenden(request: Request, body: dict | None = None):
    """Führt die gefundenen Dubletten zusammen (Provenienz bleibt erhalten)."""
    quelle = ((body or {}).get("quelle") or "").strip() or None
    return _store(request).merge_doppelte_events(dry_run=False, nur_quelle=quelle)


# --- Lauf auslösen ---------------------------------------------------------
@router.post("/sources/{quelle}/scrape", status_code=202)
def source_scrape(quelle: str, request: Request):
    """Startet einen Lauf im Hintergrund (intern/regeln/feed)."""
    store = _store(request)
    s = store.get_source(quelle)
    if not s:
        raise HTTPException(404, f"Unbekannte Quelle: {quelle}")
    if not s["aktiv"]:
        raise HTTPException(409, {"fehler": [f"Quelle '{quelle}' ist pausiert — erst aktivieren."]})
    # Regeln/Adapter vorab prüfen (Fehler sofort sichtbar statt im Thread)
    try:
        from .adapters import build_adapter
        adapter = build_adapter(store, quelle)
        adapter.close()
    except ValueError as e:
        raise HTTPException(422, {"message": "Quelle kann nicht laufen.", "fehler": [str(e)]}) from e

    ergebnis: dict = {}
    def _lauf():
        from .pipeline import scrape
        try:
            ergebnis.update(scrape(store, quelle, online=True, geo=True))
        except Exception as e:  # pragma: no cover
            ergebnis["fehler"] = str(e)
    _thread_starten(_lauf, f"scrape-{quelle}")
    return {"status": "gestartet", "quelle": quelle}


# --- Schulen / Kategorien / manuelle Termine / Mail -------------------------
@router.get("/schulen")
def schulen_list(request: Request, bezirk: str | None = None,
                 schulform: str | None = None, q: str | None = None,
                 ohne_termin: bool = Query(False), nur_mit_email: bool = Query(False),
                 nur_ohne_fund: bool = Query(False)):
    """Schulliste mit denselben Filtern wie im Frontend (Bezirk, Schulform).

    ohne_termin blendet Schulen aus, die schon einen Termin haben (Vorschlag oder
    freigegeben); jede Zeile trägt `naechster_termin` und `hat_termin` mit.
    """
    return _store(request).list_schulen(
        bezirk=(bezirk or "").strip().lower() or None,
        schulform=(schulform or "").strip() or None, q=q,
        ohne_termin=ohne_termin, nur_mit_email=nur_mit_email,
        nur_ohne_fund=nur_ohne_fund)


@router.get("/schul-filter")
def schul_filter(request: Request):
    """Auswahllisten der Schul-Filter — Bezirke mit denselben Bezeichnungen wie
    im Frontend (BEZIRK_LABELS), Schulformen aus dem Bestand."""
    from .api import BEZIRK_LABELS
    store = _store(request)
    vorhanden = set(store.bezirke_liste())
    bezirke = [{"key": k, "label": v} for k, v in BEZIRK_LABELS.items()
               if not vorhanden or k in vorhanden]
    return {"bezirke": bezirke, "schulformen": store.schulformen_liste()}


class MailBatchBody(BaseModel):
    bsn: list[str] = []
    betreff: str = ""
    text: str = ""
    reply_to: str = ""
    trocken: bool = False
    max_anzahl: int = 100


@router.post("/schulen/mail-batch")
def schulen_mail_batch(body: MailBatchBody, request: Request):
    """Dieselbe Mail an mehrere ausgewählte Schulen — mit Einzelergebnis.

    Ablauf je Schule: Empfänger prüfen (ohne Adresse = übersprungen, sichtbarer
    Grund), Text mit den Schuldaten füllen, senden. Ist die Tages-/Stundengrenze
    erreicht, wird abgebrochen und für die restlichen Schulen „nicht gesendet"
    gemeldet — nichts läuft still ins Leere. `trocken=true` prüft nur.
    """
    store = _store(request)
    auswahl = [b.strip() for b in (body.bsn or []) if str(b).strip()]
    if not auswahl:
        raise HTTPException(422, {"fehler": ["Keine Schulen ausgewählt."]})
    if len(auswahl) > 100:
        raise HTTPException(422, {"fehler": ["Höchstens 100 Schulen je Durchgang — "
                                            "bitte in zwei Schritten senden."]})
    ergebnisse: list[dict] = []
    gesendet = 0
    abbruch: str | None = None
    for bsn in auswahl:
        if abbruch:
            ergebnisse.append({"bsn": bsn, "ok": False, "grund": "nicht gesendet: " + abbruch})
            continue
        sch = store.get_schule(bsn)
        if not sch:
            ergebnisse.append({"bsn": bsn, "ok": False, "grund": "unbekannte Schule"})
            continue
        name = sch.get("name") or bsn
        empfaenger = (sch.get("email") or "").strip()
        if not empfaenger:
            ergebnisse.append({"bsn": bsn, "schule": name, "ok": False,
                               "grund": "keine E-Mail-Adresse hinterlegt"})
            continue
        grund = store.mail_versand_bremse_grund()
        if grund:
            abbruch = grund
            ergebnisse.append({"bsn": bsn, "schule": name, "ok": False,
                               "grund": "nicht gesendet: " + grund})
            continue
        if (body.betreff or "").strip():
            betreff = " ".join(_mail_mit_platzhaltern(store, sch, body.betreff).split())[:200]
            nachricht = _mail_mit_platzhaltern(store, sch, body.text or "")
        else:
            betreff, nachricht = _mail_betreff(
                _mail_mit_platzhaltern(store, sch, (body.text or "").strip()), name)
        if body.trocken:
            ergebnisse.append({"bsn": bsn, "schule": name, "an": empfaenger, "ok": True,
                               "trocken": True, "betreff": betreff})
            continue
        try:
            _sende_mail(store, empfaenger, betreff, nachricht,
                        reply_to=(body.reply_to or "").strip() or None)
        except HTTPException as e:
            detail = e.detail
            text = (detail.get("fehler", [detail])[0] if isinstance(detail, dict) else str(detail))
            ergebnisse.append({"bsn": bsn, "schule": name, "an": empfaenger, "ok": False,
                               "grund": text})
            continue
        store.set_schule_angefragt(bsn, iso_utc(datetime.now(TZ_BERLIN)))
        gesendet += 1
        ergebnisse.append({"bsn": bsn, "schule": name, "an": empfaenger, "ok": True,
                           "betreff": betreff})
    return {"ausgewaehlt": len(auswahl), "gesendet": gesendet,
            "uebersprungen": sum(1 for e in ergebnisse if not e["ok"]),
            "trocken": body.trocken, "abbruch": abbruch, "ergebnisse": ergebnisse,
            "versand": store.mail_versand_zaehler(),
            "reply_to": (body.reply_to or store.get_setting("smtp_reply_to") or "").strip()}


@router.get("/schulen/{bsn}")
def schule_get(bsn: str, request: Request,
               mit_termine: bool = Query(False)):
    store = _store(request)
    s = store.get_schule(bsn)
    if not s:
        raise HTTPException(404, f"Unbekannte Schule: {bsn}")
    if mit_termine:
        s = dict(s)
        s["termine"] = store.list_termine_manuell(schule_bsn=bsn)
    return s


@router.post("/schulen", status_code=201)
def schule_create(body: dict, request: Request):
    store = _store(request)
    if not str(body.get("bsn") or "").strip():
        raise HTTPException(422, {"fehler": ["bsn fehlt (Schulnummer)."]})
    if store.get_schule(str(body["bsn"]).strip()):
        raise HTTPException(409, {"fehler": [f"Schule existiert bereits: {body['bsn']}"]})
    try:
        store.upsert_schule(body)
    except ValueError as e:
        raise HTTPException(422, {"fehler": [str(e)]}) from None
    return store.get_schule(str(body["bsn"]).strip())


@router.put("/schulen/{bsn}")
def schule_update(bsn: str, body: dict, request: Request):
    store = _store(request)
    alt = store.get_schule(bsn)
    if not alt:
        raise HTTPException(404, f"Unbekannte Schule: {bsn}")
    # Teil-Update: nur gesendete Felder ändern — nie stille NULLs auf andere
    # Felder schreiben (Voll-Replacement würde bezirk/plz/email etc. löschen).
    neu = {k: alt.get(k) for k in ("bsn", "name", "schulform", "bezirk", "ortsteil",
                                   "plz", "strasse", "email", "website", "notiz")}
    for k, v in body.items():
        if k in neu:
            neu[k] = v
    neu["bsn"] = bsn
    try:
        store.upsert_schule(neu)
    except ValueError as e:
        raise HTTPException(422, {"fehler": [str(e)]}) from None
    return store.get_schule(bsn)


@router.delete("/schulen/{bsn}", status_code=204)
def schule_delete(bsn: str, request: Request):
    try:
        _store(request).delete_schule(bsn)
    except ValueError as e:
        raise HTTPException(404, str(e)) from None


@router.get("/schulen/{bsn}/anfrage/vorschau", status_code=200)
def schule_mail_vorschau(bsn: str, request: Request):
    """Fertige Mail in getrennten Feldern: An, Reply-To, Betreff, Nachricht.

    Platzhalter ({schule}, {schulform}, {bezirk}, {jahr}) sind hier schon
    ersetzt — die Oberfläche zeigt also den Text, der wirklich rausgeht, und
    muss ihn nicht selbst zusammensetzen.
    """
    store = _store(request)
    sch = store.get_schule(bsn)
    if not sch:
        raise HTTPException(404, f"Unbekannte Schule: {bsn}")
    betreff, nachricht = _mail_betreff(_mail_mit_platzhaltern(store, sch, ""),
                                       sch.get("name") or bsn)
    return {"an": (sch.get("email") or "").strip(), "schule": sch.get("name") or bsn,
            "reply_to": (store.get_setting("smtp_reply_to") or "").strip(),
            "betreff": betreff, "text": nachricht,
            "hat_email": bool((sch.get("email") or "").strip())}


@router.post("/schulen/{bsn}/anfrage", status_code=200)
def schule_mail_anfrage(bsn: str, body: AnfrageBody, request: Request):
    """Sendet eine Termin-Anfrage-Mail an die Schule (SMTP aus Einstellungen).

    text: voller Mail-Text. Optional mit erster Zeile 'Betreff: …' (wird als
    Subject verwendet). Ohne text wird die Vorlage (Einstellung mail_vorlage,
    Fallback DEFAULT_MAIL_VORLAGE) mit Platzhaltern gefüllt. Platzhalter
    {schule}/{schulform}/{bezirk}/{jahr} werden ersetzt.
    Ohne konfigurierten SMTP oder ohne Schul-E-Mail → sichtbarer Fehler.
    """
    store = _store(request)
    sch = store.get_schule(bsn)
    if not sch:
        raise HTTPException(404, f"Unbekannte Schule: {bsn}")
    empfaenger = (sch.get("email") or "").strip()
    if not empfaenger:
        raise HTTPException(422, {"fehler": ["Schule hat keine E-Mail-Adresse hinterlegt."]})
    if (body.betreff or "").strip():
        # Getrennte Felder: Betreff wie eingegeben, Text ist bereits der Nachrichtentext
        betreff = _mail_mit_platzhaltern(store, sch, body.betreff.strip())
        betreff = " ".join(betreff.split())[:200]
        nachricht = _mail_mit_platzhaltern(store, sch, body.text or "")
    else:
        text = _mail_mit_platzhaltern(store, sch, (body.text or "").strip())
        betreff, nachricht = _mail_betreff(text, sch.get("name") or bsn)
    _sende_mail(store, empfaenger, betreff, nachricht,
                reply_to=(body.reply_to or "").strip() or None)
    store.set_schule_angefragt(bsn, iso_utc(datetime.now(TZ_BERLIN)))
    return {"status": "gesendet", "schule": bsn, "an_": empfaenger,
            "betreff": betreff,
            "reply_to": (body.reply_to or store.get_setting("smtp_reply_to") or "").strip(),
            "angefragt_am": store.get_schule(bsn)["angefragt_am"]}


def _mail_mit_platzhaltern(store, sch: dict, text: str) -> str:
    """Leeren Text mit der Vorlage füllen; {schule}-Platzhalter ersetzen."""
    if not text:
        text = _mail_vorlage(store)
    jahr = datetime.now(TZ_BERLIN).year
    ersetzungen = {
        "schule": sch.get("name") or "",
        "schulform": sch.get("schulform") or "Schule",
        "bezirk": sch.get("bezirk") or "",
        "jahr": str(jahr),
    }
    for k, v in ersetzungen.items():
        text = text.replace("{" + k + "}", v)
    return text.strip()


def _mail_betreff(text: str, schulname: str) -> tuple[str, str]:
    """Erste 'Betreff: …'-Zeile als Subject, Rest als Nachricht."""
    if text.startswith("Betreff:"):
        erste, _, rest = text.partition("\n")
        betreff = erste.split(":", 1)[1].strip()
        return betreff, rest.strip()
    return f"Termin-Anfrage: {schulname}", text


def _sende_mail(store, empfaenger: str, betreff: str, nachricht: str,
                reply_to: str | None = None) -> None:
    import smtplib
    from email.message import EmailMessage
    host = (store.get_setting("smtp_host") or "").strip()
    user = (store.get_setting("smtp_user") or "").strip()
    pw = store.get_setting("smtp_pass") or ""
    von = (store.get_setting("smtp_from") or "").strip()
    if not host or not von:
        raise HTTPException(409, {"fehler": [
            "SMTP ist nicht konfiguriert — Host und Absender (smtp_from) unter "
            "Einstellungen eintragen."]})
    try:
        port = int((store.get_setting("smtp_port") or "587").strip())
    except ValueError:
        port = 587
    msg = EmailMessage()
    msg["Subject"] = betreff
    msg["From"] = von
    msg["To"] = empfaenger
    antwort_an = (reply_to or store.get_setting("smtp_reply_to") or "").strip()
    if antwort_an:
        reply_to = antwort_an
        msg["Reply-To"] = reply_to
    msg.set_content(nachricht)
    grund = store.mail_versand_bremse_grund()
    if grund:
        raise HTTPException(429, {"fehler": [grund]})
    art = (store.get_setting("smtp_verschluesselung") or "").strip().lower()
    if not art:
        art = "ssl" if port == 465 else ("starttls" if port == 587 else "keine")
    versand_id = store.starte_mail_versand(empfaenger, betreff)
    try:
        if art == "ssl":
            verbindung = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            verbindung = smtplib.SMTP(host, port, timeout=30)
        with verbindung as smtp:
            if art != "ssl":
                smtp.ehlo()
            if art == "starttls":
                smtp.starttls()
            if user:
                smtp.login(user, pw)
            smtp.send_message(msg)
    except Exception as e:  # sichtbar statt still
        store.beende_mail_versand(versand_id, ok=False, fehler=str(e))
        raise HTTPException(502, {"fehler": [f"Mail-Versand fehlgeschlagen: {e}"]}) from e
    store.beende_mail_versand(versand_id, ok=True, fehler=None)


@router.get("/tags")
def tags_list(request: Request, template: bool | None = Query(None)):
    return _store(request).list_tags(nur_template=bool(template))


@router.post("/tags", status_code=201)
def tag_create(body: dict, request: Request):
    store = _store(request)
    kid = str(body.get("id") or "").strip()
    if store.get_tag(kid):
        raise HTTPException(409, {"fehler": [f"Tag existiert bereits: {kid}"]})
    try:
        store.upsert_tag(body)
    except ValueError as e:
        raise HTTPException(422, {"fehler": [str(e)]}) from None
    return store.get_tag(kid)


@router.put("/tags/{kid}")
def tag_update(kid: str, body: dict, request: Request):
    store = _store(request)
    alt = store.get_tag(kid)
    if not alt:
        raise HTTPException(404, f"Unbekannter Tag: {kid}")
    neu = {k: alt.get(k) for k in ("id", "name", "farbe", "sort", "template")}
    for k, v in body.items():
        if k in neu:
            neu[k] = v
    neu["id"] = kid
    try:
        store.upsert_tag(neu)
    except ValueError as e:
        raise HTTPException(422, {"fehler": [str(e)]}) from None
    return store.get_tag(kid)


@router.delete("/tags/{kid}", status_code=204)
def tag_delete(kid: str, request: Request):
    try:
        _store(request).delete_tag(kid)
    except ValueError as e:
        raise HTTPException(404, str(e)) from None


@router.get("/events")
def events_admin_list(request: Request, quelle: str | None = None,
                      status: str | None = None, q: str | None = None,
                      limit: int = 1000):
    """ALLE Events (auch gescrapte) für die Termin-Verwaltung."""
    return _store(request).list_events_admin(quelle=quelle, status=status,
                                             q=q, limit=limit)


# --- Ortsvorschläge (Change 022) -------------------------------------------
# Nutzerentscheid 14.09.2026: Die LLM-Ortsprüfung schlägt nur VOR. In die
# Ortsfelder kommt etwas erst hier — übernehmen heißt: Ort/Adresse/Treffpunkt
# am Event setzen und `manuell=1`, damit kein Scrape das Ergebnis zurücksetzt.

@router.get("/ort/vorschlaege")
def ort_vorschlaege_list(request: Request, status: str | None = "vorschlag",
                         quelle: str | None = None, q: str | None = None,
                         band: str | None = None, limit: int = Query(500, le=3000)):
    """Prüfliste: Vorschläge + Zähler + letzter Lauf."""
    store = _store(request)
    return {"vorschlaege": store.list_ort_vorschlaege(
                status=status, quelle=quelle, q=q, band=band, limit=limit),
            "zaehler": store.ort_vorschlaege_zaehlen(),
            "letzter_lauf": ort_ki.letzter_lauf(store)}


@router.post("/ort/uebernehmen")
def ort_uebernehmen(body: dict, request: Request):
    """Vorschläge übernehmen (einzeln oder Liste).

    Setzt ort/adresse/treffpunkt am Event und `manuell=1` — ab dann gewinnt die
    Bearbeitung gegen jeden weiteren Scrape (`upsert_event`, manuell_schutz).
    Danach wird die Position aus der Adresse (sonst aus dem Ortsnamen) neu
    bestimmt; findet sich keine, bleibt die alte Position und das steht in der
    Antwort (kein stiller Teil-Erfolg).
    """
    store = _store(request)
    ids = [int(i) for i in (body.get("ids") or [])]
    if not ids:
        raise HTTPException(400, "ids fehlt (Liste von Vorschlags-IDs)")
    ergebnis, uebernommen = [], 0
    for vid in ids:
        v = store.ort_vorschlag_holen(vid)
        if not v:
            ergebnis.append({"id": vid, "ok": False, "grund": "Vorschlag unbekannt"})
            continue
        if v["status"] != "vorschlag":
            ergebnis.append({"id": vid, "ok": False,
                             "grund": f"schon {v['status']}"})
            continue
        felder = {k: v[k] for k in ("ort_vorschlag", "adresse_vorschlag", "treffpunkt")
                  if v.get(k)}
        if "ort_vorschlag" in felder:
            felder["ort"] = felder.pop("ort_vorschlag")
        if "adresse_vorschlag" in felder:
            felder["adresse"] = felder.pop("adresse_vorschlag")
        if not store.update_event_admin(v["event_id"], felder):
            ergebnis.append({"id": vid, "ok": False, "grund": "Event nicht gefunden"})
            continue
        position = _position_setzen(store, v["event_id"], felder)
        store.ort_vorschlaege_pruefen([vid], "uebernommen")
        uebernommen += 1
        ergebnis.append({"id": vid, "ok": True, "event_id": v["event_id"],
                         "ort": felder.get("ort"), "treffpunkt": felder.get("treffpunkt"),
                         "position": position})
    return {"uebernommen": uebernommen, "ergebnis": ergebnis}


def _position_setzen(store, ev_id: str, felder: dict) -> str:
    """Position nach der Übernahme neu bestimmen. Rückgabe: was passiert ist."""
    adresse = (felder.get("adresse") or "").strip()
    ort = (felder.get("ort") or "").strip()
    with httpx.Client(timeout=20, follow_redirects=True) as c:
        koord = None
        if adresse:
            try:
                koord = adresse_amtlich(store, adresse, client=c)
            except Exception:
                koord = None
        if not koord and ort:
            try:
                koord = ort_koordinaten(store, ort, client=c)
            except Exception:
                koord = None
    if not koord or not koord.get("lat"):
        return "keine Position gefunden"
    store.set_event_position(ev_id, koord["lat"], koord["lon"])
    return f"Position gesetzt ({koord['lat']:.5f}, {koord['lon']:.5f})"


@router.post("/ort/verwerfen")
def ort_verwerfen(body: dict, request: Request):
    """Vorschläge verwerfen (einzeln oder Liste). Ändert das Event nicht."""
    store = _store(request)
    ids = [int(i) for i in (body.get("ids") or [])]
    if not ids:
        raise HTTPException(400, "ids fehlt (Liste von Vorschlags-IDs)")
    return {"verworfen": store.ort_vorschlaege_pruefen(ids, "verworfen",
                                                       grund=body.get("grund"))}


@router.post("/ort/import")
def ort_import(body: dict, request: Request):
    """Bootstrap-Import eines Schattenlauf-Ergebnisses (JSONL-Zeilen oder Liste).

    Für Ergebnisse, die außerhalb der App mit demselben Prompt entstanden sind.
    Importiert wird nur, was die Prüfregeln der Stufe passiert (Bezirksname,
    generisch, kein Gewinn fliegen raus) — die Herkunft wird mitgespeichert,
    damit eine Liste erkennbar aus einem Import stammt.
    """
    store = _store(request)
    roh = body.get("jsonl") or ""
    zeilen: list[dict] = []
    for zeile in roh.splitlines():
        zeile = zeile.strip()
        if not zeile:
            continue
        try:
            zeilen.append(json.loads(zeile))
        except json.JSONDecodeError:
            continue
    if isinstance(body.get("vorschlaege"), list):
        zeilen += body["vorschlaege"]
    importiert, verworfen = 0, 0
    for z in zeilen:
        text = (z.get("text") or z.get("beleg") or "")
        ort = (z.get("ort_llm") or z.get("ort") or "").strip()
        belegt = bool(z.get("name_im_text")) or bool(z.get("beleg_woertlich"))
        ok, _grund = ort_ki.plausibel(ort, belegt, (z.get("ort_live") or ""))
        if not ok:
            verworfen += 1
            continue
        ev = store.get_event_by_url(z.get("url") or z.get("source_url") or "")
        if not ev:
            verworfen += 1
            continue
        meter = z.get("abstand_m")
        store.ort_vorschlaege_speichern([{
            "event_id": ev["id"], "quelle": ev["quelle"], "ort_vorschlag": ort,
            "adresse_vorschlag": z.get("adresse_llm") or z.get("adresse"),
            "treffpunkt": z.get("treffpunkt_llm") or z.get("treffpunkt"),
            "beleg": z.get("beleg"), "belegherkunft": z.get("belegherkunft") or
            ort_ki.belegherkunft(z.get("beleg") or ""),
            "abstand_m": meter, "ortsband": z.get("ortsband") or ort_ki.abstand_band(meter),
            "name_im_text": belegt, "modell": z.get("modell") or body.get("modell"),
            "herkunft": z.get("herkunft") or "Import Schattenlauf"}])
        importiert += 1
    return {"importiert": importiert, "verworfen": verworfen, "zeilen": len(zeilen)}


@router.get("/ort/status")
def ort_status(request: Request):
    from .recherche.llm import konfiguration as llm_konfiguration
    store = _store(request)
    return {"zaehler": store.ort_vorschlaege_zaehlen(),
            "letzter_lauf": ort_ki.letzter_lauf(store),
            "llm": {k: v for k, v in llm_konfiguration(store).items()
                    if k in ("llm_model", "llm_base_url")}}


@router.post("/ort/lauf")
def ort_lauf(request: Request, body: dict | None = None):
    """Ortsprüfung starten (Hintergrund) — pro Quelle oder für alle aktiven."""
    store = _store(request)
    koerper = body or {}
    quelle = koerper.get("quelle") or None
    limit = koerper.get("limit")
    if quelle and not store.get_source(quelle):
        raise HTTPException(404, f"Unbekannte Quelle: {quelle}")

    def _lauf():
        try:
            ort_ki.lauf(store, quelle=quelle, limit=limit)
        except Exception as e:                      # sichtbar, nie still
            store.set_setting("ort_ki_letzter_lauf", json.dumps(
                {"fehler": f"{type(e).__name__}: {e}"}, ensure_ascii=False))

    _thread_starten(_lauf, "ort-ki")
    return {"status": "gestartet", "quelle": quelle or "alle aktiven"}


@router.put("/events/{ev_id}")
def event_admin_update(ev_id: str, body: dict, request: Request):
    """Admin-Edit eines beliebigen Events → manuell=1 (Scrape überschreibt
    danach nicht mehr — „Meine Bearbeitung gewinnt“, User-Entscheidung)."""
    store = _store(request)
    if not store.update_event_admin(ev_id, body):
        raise HTTPException(404, f"Unbekanntes Event: {ev_id}")
    # frisch zurücklesen
    ev = store.get_event(ev_id)
    if not ev:
        raise HTTPException(404, f"Unbekanntes Event: {ev_id}")
    return ev


@router.get("/termine/vorschlaege")
def termin_titel_vorschlaege(request: Request, limit: int = 25):
    """Häufigste bisherige Termin-Titel für das Auto-Complete im Formular."""
    return _store(request).titel_vorschlaege(limit=min(int(limit), 100))


@router.get("/termine")
def termine_list(request: Request, schule: str | None = None,
                 status: str | None = None):
    return _store(request).list_termine_manuell(schule_bsn=schule, status=status)


@router.get("/termine/{tid}")
def termin_get(tid: int, request: Request):
    t = _store(request).get_termin_manuell(tid)
    if not t:
        raise HTTPException(404, f"Unbekannter Termin: {tid}")
    return t


@router.post("/termine", status_code=201)
def termin_create(body: dict, request: Request):
    store = _store(request)
    if body.get("schule_bsn") and not store.get_schule(str(body["schule_bsn"])):
        raise HTTPException(422, {"fehler": [f"Unbekannte Schule: {body['schule_bsn']}"]})
    try:
        tid = store.upsert_termin_manuell(body)
    except ValueError as e:
        raise HTTPException(422, {"fehler": [str(e)]}) from None
    return store.get_termin_manuell(tid)


@router.put("/termine/{tid}")
def termin_update(tid: int, body: dict, request: Request):
    store = _store(request)
    alt = store.get_termin_manuell(tid)
    if not alt:
        raise HTTPException(404, f"Unbekannter Termin: {tid}")
    # Teil-Update wie bei schulen: nur gesendete Felder ändern, der Rest bleibt.
    import copy
    neu = copy.deepcopy(alt)
    for k, v in body.items():
        if k in ("id", "schulname", "schulbezirk", "kategorie_name", "kategorie_farbe"):
            continue  # JOIN-Spalten / Schlüssel nie überschreiben
        if k == "kategorie_id" and not v:
            v = None  # Kategorie explizit entfernen ("" → NULL)
        neu[k] = v
    if body.get("schule_bsn") and not store.get_schule(str(body["schule_bsn"])):
        raise HTTPException(422, {"fehler": [f"Unbekannte Schule: {body['schule_bsn']}"]})
    try:
        store.upsert_termin_manuell(neu)
    except ValueError as e:
        raise HTTPException(422, {"fehler": [str(e)]}) from None
    return store.get_termin_manuell(tid)


@router.delete("/termine/{tid}", status_code=204)
def termin_delete(tid: int, request: Request):
    try:
        _store(request).delete_termin_manuell(tid)
    except ValueError as e:
        raise HTTPException(404, str(e)) from None
