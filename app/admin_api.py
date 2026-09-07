"""Admin-API (offen; Auth-Middleware folgt in einem späteren Change).

Alle konfigurierbaren Optionen (Quellen, Regeln, Einstellungen) laufen über
diese Endpunkte — sie sind der einzige Schreibweg im Betrieb. Deutsche,
verständliche Fehlermeldungen; nichts Stilles.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from .model import TZ_BERLIN, iso_utc
from .regeln import validate_regeln_yaml

router = APIRouter(prefix="/api/admin")


class AnfrageBody(BaseModel):
    text: str = ""

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
    return _store(request).all_settings()


@router.put("/settings")
def settings_put(body: dict, request: Request):
    store = _store(request)
    erlaubt = {"scrape_interval_h", "admin_hinweis", "scrape_at",
               "smtp_host", "smtp_port", "smtp_user", "smtp_pass", "smtp_from"}
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
    if fehler:
        raise HTTPException(422, {"message": "Einstellungen ungültig.", "fehler": fehler})
    for k, v in body.items():
        if k in erlaubt:
            store.set_setting(k, str(v))
    return store.all_settings()


# --- Lauf auslösen ---------------------------------------------------------
@router.post("/sources/{quelle}/scrape", status_code=202)
def source_scrape(quelle: str, request: Request):
    """Startet einen Lauf im Hintergrund. Typ 'feed' folgt (keine Feed-Quelle
    aufgenommen); 'intern' und 'regeln' laufen sofort über ihre Adapter."""
    store = _store(request)
    s = store.get_source(quelle)
    if not s:
        raise HTTPException(404, f"Unbekannte Quelle: {quelle}")
    if not s["aktiv"]:
        raise HTTPException(409, {"fehler": [f"Quelle '{quelle}' ist pausiert — erst aktivieren."]})
    if s["typ"] == "feed":
        raise HTTPException(409, {"fehler": [
            f"Quelle '{quelle}' ist vom Typ 'feed': der Feed-Adapter folgt, "
            "sobald die erste Feed-Quelle aufgenommen wird."]})
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
    t = threading.Thread(target=_lauf, name=f"scrape-{quelle}", daemon=True)
    t.start()
    return {"status": "gestartet", "quelle": quelle}


# --- Schulen / Kategorien / manuelle Termine / Mail -------------------------
@router.get("/schulen")
def schulen_list(request: Request, bezirk: str | None = None, q: str | None = None):
    return _store(request).list_schulen(bezirk=bezirk, q=q)


@router.get("/schulen/{bsn}")
def schule_get(bsn: str, request: Request):
    s = _store(request).get_schule(bsn)
    if not s:
        raise HTTPException(404, f"Unbekannte Schule: {bsn}")
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
    if not store.get_schule(bsn):
        raise HTTPException(404, f"Unbekannte Schule: {bsn}")
    body = {**body, "bsn": bsn}
    try:
        store.upsert_schule(body)
    except ValueError as e:
        raise HTTPException(422, {"fehler": [str(e)]}) from None
    return store.get_schule(bsn)


@router.delete("/schulen/{bsn}", status_code=204)
def schule_delete(bsn: str, request: Request):
    try:
        _store(request).delete_schule(bsn)
    except ValueError as e:
        raise HTTPException(404, str(e)) from None


@router.post("/schulen/{bsn}/anfrage", status_code=200)
def schule_mail_anfrage(bsn: str, body: AnfrageBody, request: Request):
    """Sendet eine Termin-Anfrage-Mail an die Schule (SMTP aus Einstellungen).
    Ohne konfigurierten SMTP oder ohne Schul-E-Mail → sichtbarer Fehler."""
    store = _store(request)
    sch = store.get_schule(bsn)
    if not sch:
        raise HTTPException(404, f"Unbekannte Schule: {bsn}")
    empfaenger = (sch.get("email") or "").strip()
    if not empfaenger:
        raise HTTPException(422, {"fehler": ["Schule hat keine E-Mail-Adresse hinterlegt."]})
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(422, {"fehler": ["text fehlt (Nachricht an die Schule)."]})
    _sende_mail(store, empfaenger, sch.get("name") or bsn, text)
    store.set_schule_angefragt(bsn, iso_utc(datetime.now(TZ_BERLIN)))
    return {"status": "gesendet", "schule": bsn, "an_": empfaenger,
            "angefragt_am": store.get_schule(bsn)["angefragt_am"]}


def _sende_mail(store, empfaenger: str, schulname: str, text: str) -> None:
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
    msg["Subject"] = f"Termin-Anfrage: {schulname}"
    msg["From"] = von
    msg["To"] = empfaenger
    msg.set_content(text)
    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            if port == 587:
                smtp.starttls()
            if user:
                smtp.login(user, pw)
            smtp.send_message(msg)
    except Exception as e:  # sichtbar statt still
        raise HTTPException(502, {"fehler": [f"Mail-Versand fehlgeschlagen: {e}"]}) from e


@router.get("/kategorien")
def kategorien_list(request: Request):
    return _store(request).list_kategorien()


@router.post("/kategorien", status_code=201)
def kategorie_create(body: dict, request: Request):
    store = _store(request)
    kid = str(body.get("id") or "").strip()
    if store.get_kategorie(kid):
        raise HTTPException(409, {"fehler": [f"Kategorie existiert bereits: {kid}"]})
    try:
        store.upsert_kategorie(body)
    except ValueError as e:
        raise HTTPException(422, {"fehler": [str(e)]}) from None
    return store.get_kategorie(kid)


@router.put("/kategorien/{kid}")
def kategorie_update(kid: str, body: dict, request: Request):
    store = _store(request)
    if not store.get_kategorie(kid):
        raise HTTPException(404, f"Unbekannte Kategorie: {kid}")
    try:
        store.upsert_kategorie({**body, "id": kid})
    except ValueError as e:
        raise HTTPException(422, {"fehler": [str(e)]}) from None
    return store.get_kategorie(kid)


@router.delete("/kategorien/{kid}", status_code=204)
def kategorie_delete(kid: str, request: Request):
    try:
        _store(request).delete_kategorie(kid)
    except ValueError as e:
        raise HTTPException(404, str(e)) from None


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
    if not store.get_termin_manuell(tid):
        raise HTTPException(404, f"Unbekannter Termin: {tid}")
    if body.get("schule_bsn") and not store.get_schule(str(body["schule_bsn"])):
        raise HTTPException(422, {"fehler": [f"Unbekannte Schule: {body['schule_bsn']}"]})
    try:
        store.upsert_termin_manuell({**body, "id": tid})
    except ValueError as e:
        raise HTTPException(422, {"fehler": [str(e)]}) from None
    return store.get_termin_manuell(tid)


@router.delete("/termine/{tid}", status_code=204)
def termin_delete(tid: int, request: Request):
    try:
        _store(request).delete_termin_manuell(tid)
    except ValueError as e:
        raise HTTPException(404, str(e)) from None
