"""Admin-API (offen; Auth-Middleware folgt in einem späteren Change).

Alle konfigurierbaren Optionen (Quellen, Regeln, Einstellungen) laufen über
diese Endpunkte — sie sind der einzige Schreibweg im Betrieb. Deutsche,
verständliche Fehlermeldungen; nichts Stilles.
"""
from __future__ import annotations

import re
import threading

from fastapi import APIRouter, HTTPException, Query, Request

from .model import TZ_BERLIN
from .regeln import validate_regeln_yaml

router = APIRouter(prefix="/api/admin")

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
    erlaubt = {"scrape_interval_h", "admin_hinweis", "scrape_at"}
    unbekannt = set(body) - erlaubt
    fehler = []
    for k in sorted(unbekannt):
        fehler.append(f"Unbekannte Einstellung '{k}' (erlaubt: {', '.join(sorted(erlaubt))}).")
    if "scrape_interval_h" in body:
        try:
            v = float(body["scrape_interval_h"])
            if not 0.5 <= v <= 168:
                raise ValueError
        except ValueError:
            fehler.append("scrape_interval_h muss eine Zahl zwischen 0.5 und 168 sein.")
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
