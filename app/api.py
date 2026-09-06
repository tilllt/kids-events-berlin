"""FastAPI: /api/events (JSON + GeoJSON), /api/meta, /api/health.

Filter: bezirk, altersband, uhrzeit, von/bis (lokal), kostenlos, quelle, q.
Zeiten in *_local = Ortszeit Europe/Berlin (Anzeige); start_iso = UTC.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request

from .model import ALTERSBAND_DEFAULT, BEZIRK_BERLINWEIT, BEZIRK_LABELS, TZ_BERLIN

router = APIRouter(prefix="/api")

# Token → (lo, hi, familie)
ALTERS_TOKENS = {name: (lo, hi, fam) for name, lo, hi, fam in ALTERSBAND_DEFAULT}
ALTERS_TOKENS["14+"] = (14, 17, False)
ALTERS_TOKENS["familie"] = (None, None, True)


def _store(request: Request):
    return request.app.state.store


def _parse_list(v: str | None) -> list[str]:
    if not v:
        return []
    return [x.strip().lower() for x in v.split(",") if x.strip()]


def _altersband_filter(tokens: list[str]) -> list[tuple]:
    out = []
    for tok in tokens:
        if tok in ALTERS_TOKENS:
            out.append(ALTERS_TOKENS[tok])
    return out


def _uhrzeit_filter(tokens: list[str]) -> list[str]:
    ok = {"vormittag", "nachmittag", "abend", "ganztags"}
    return [t for t in tokens if t in ok]


def _ev_public(e: dict) -> dict:
    bez = e.get("bezirk")
    return {
        "id": e["id"],
        "titel": e["titel"],
        "beschreibung_kurz": e.get("beschreibung_kurz"),
        "start_local": e["start_local"],
        "ende_local": e.get("ende_local"),
        "start_iso": e["start_iso"],
        "ganztags": bool(e.get("ganztags")),
        "ort": e.get("ort"),
        "adresse": e.get("adresse"),
        "bezirk": bez,
        "bezirk_label": BEZIRK_LABELS.get(bez or "", bez or "Ohne Angabe"),
        "altersband_min": e.get("altersband_min"),
        "altersband_max": e.get("altersband_max"),
        "alters_familie": bool(e.get("alters_familie")),
        "kategorien": e.get("kategorien") or [],
        "kostenlos": e.get("kostenlos"),
        "quelle": e["quelle"],
        "source_url": e["source_url"],
        "lat": e.get("lat"),
        "lon": e.get("lon"),
    }


def _filters(params) -> dict:
    return {
        "bezirk": _parse_list(params.get("bezirk")),
        "altersband": _altersband_filter(_parse_list(params.get("altersband"))),
        "uhrzeit": _uhrzeit_filter(_parse_list(params.get("uhrzeit"))),
        "von": params.get("von") or None,
        "bis": params.get("bis") or None,
        "kostenlos": {"true": True, "false": False}.get((params.get("kostenlos") or "").lower()),
        "quelle": _parse_list(params.get("quelle")),
        "q": params.get("q") or None,
        "limit": params.get("limit") or 500,
    }


@router.get("/health")
def health(request: Request):
    return {"status": "ok", "events": _store(request).count_events()}


@router.get("/meta")
def meta(request: Request):
    s = _store(request)
    quellen = []
    for q in s.list_sources(aktiv_nur=True):
        runs = s.recent_runs(q["quelle"], limit=1)
        quellen.append({
            "quelle": q["quelle"], "name": q.get("name") or q["quelle"],
            "typ": q.get("typ"), "letzter_lauf": (runs[0] if runs else None),
        })
    return {
        "quellen": quellen,
        "events_gesamt": s.count_events(),
        "bezirke": [{k: v} for k, v in BEZIRK_LABELS.items()
                    if k not in (BEZIRK_BERLINWEIT, "ausserhalb", "unbekannt")],
        "bezirk_berlinweit": BEZIRK_BERLINWEIT,
        "altersbaender": [{"id": name, "label": _band_label(name)}
                          for name, _, _, _ in ALTERSBAND_DEFAULT],
        "uhrzeiten": [
            {"id": "vormittag", "label": "Vormittag (bis 12 Uhr)"},
            {"id": "nachmittag", "label": "Nachmittag (12–17 Uhr)"},
            {"id": "abend", "label": "Abend (ab 17 Uhr)"},
            {"id": "ganztags", "label": "Ganztags"},
        ],
    }


def _band_label(tok: str) -> str:
    return {
        "0-3": "Baby & Kleinkind (0–3)",
        "4-6": "Kita-Alter (4–6)",
        "7-10": "Grundschule (7–10)",
        "11-13": "11–13 Jahre",
        "14-17": "Jugendliche (14–17)",
        "familie": "Familienangebote",
    }.get(tok, tok)


@router.get("/events")
def events(request: Request,
           bezirk: str | None = None, altersband: str | None = None,
           uhrzeit: str | None = None, von: str | None = None,
           bis: str | None = None, kostenlos: str | None = None,
           quelle: str | None = None, q: str | None = None,
           limit: int = Query(500, le=2000)):
    params = {"bezirk": bezirk, "altersband": altersband, "uhrzeit": uhrzeit,
              "von": von, "bis": bis, "kostenlos": kostenlos, "quelle": quelle,
              "q": q, "limit": limit}
    rows = _store(request).query_events(_filters(params))
    return [_ev_public(e) for e in rows]


@router.get("/events.geojson")
def events_geojson(request: Request,
                   bezirk: str | None = None, altersband: str | None = None,
                   uhrzeit: str | None = None, von: str | None = None,
                   bis: str | None = None, kostenlos: str | None = None,
                   quelle: str | None = None, q: str | None = None,
                   limit: int = Query(2000, le=5000)):
    params = {"bezirk": bezirk, "altersband": altersband, "uhrzeit": uhrzeit,
              "von": von, "bis": bis, "kostenlos": kostenlos, "quelle": quelle,
              "q": q, "limit": limit}
    rows = _store(request).query_events(_filters(params))
    features = []
    ohne = []
    for e in rows:
        pub = _ev_public(e)
        if e.get("lat") is not None and e.get("lon") is not None:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [e["lon"], e["lat"]]},
                "properties": pub,
            })
        else:
            ohne.append(pub)
    return {
        "type": "FeatureCollection",
        "features": features,
        "ohne_position": ohne,
        "anzahl": len(rows),
    }
