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

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from .model import TZ_BERLIN, iso_utc
from .regeln import validate_regeln_yaml

router = APIRouter(prefix="/api/admin")

# Standardtext für die Termin-Anfrage-Mail an Schulen (Vorlage aus der
# Schul-Erkundung, User-Vorgabe). Platzhalter werden beim Senden ersetzt:
# {schule}, {schulform}, {bezirk}, {jahr}.
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
    v = (store.get_setting("mail_vorlage") or "").strip()
    return v or DEFAULT_MAIL_VORLAGE


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
    """Liefert die gespeicherten Einstellungen. Fehlt mail_vorlage, wird der
    Standardtext (DEFAULT_MAIL_VORLAGE) als Beispieltext mitgeliefert, damit
    die GUI immer einen sichtbaren Ausgangstext zeigt (User-Vorgabe 2026-09)."""
    store = _store(request)
    s = store.all_settings()
    if not (s.get("mail_vorlage") or "").strip():
        s["mail_vorlage"] = DEFAULT_MAIL_VORLAGE
        s["mail_vorlage_ist_default"] = True
    return s


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
               "brave_anfragen_pro_s", "brave_websuche_aktiv"}
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
    return store.all_settings()


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

    def _lauf():
        try:
            zusammen = kern.lauf(store, limit=limit, nur_bsn=nur_bsn, dry_run=dry_run,
                                 bezirk=bezirk, schulform=schulform)
            store.set_setting("recherche_letzter_lauf", json.dumps(zusammen, ensure_ascii=False))
            print(f"[recherche] Lauf fertig: {zusammen['geprueft']} Schulen, "
                  f"{zusammen['belegt']} belegt, {zusammen['status']}", flush=True)
        except Exception as e:  # sichtbar statt still
            store.log_error("recherche", f"Recherche-Lauf fehlgeschlagen: {e}")
            print(f"[recherche] Lauf fehlgeschlagen: {e}", flush=True)

    threading.Thread(target=_lauf, name="schul-recherche", daemon=True).start()
    return {"status": "gestartet", "limit": limit, "nur_bsn": nur_bsn,
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
    t = threading.Thread(target=_lauf, name=f"scrape-{quelle}", daemon=True)
    t.start()
    return {"status": "gestartet", "quelle": quelle}


# --- Schulen / Kategorien / manuelle Termine / Mail -------------------------
@router.get("/schulen")
def schulen_list(request: Request, bezirk: str | None = None,
                 schulform: str | None = None, q: str | None = None):
    return _store(request).list_schulen(bezirk=bezirk, schulform=schulform, q=q)


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
    text = _mail_mit_platzhaltern(store, sch, (body.text or "").strip())
    betreff, nachricht = _mail_betreff(text, sch.get("name") or bsn)
    _sende_mail(store, empfaenger, betreff, nachricht)
    store.set_schule_angefragt(bsn, iso_utc(datetime.now(TZ_BERLIN)))
    return {"status": "gesendet", "schule": bsn, "an_": empfaenger,
            "betreff": betreff,
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


def _sende_mail(store, empfaenger: str, betreff: str, nachricht: str) -> None:
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
    reply_to = (store.get_setting("smtp_reply_to") or "").strip()
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(nachricht)
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
