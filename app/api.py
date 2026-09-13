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


def _ort_filter(tok: str | None) -> list[str]:
    """Ortsnamen für den Ortsfilter. Trenner ist '|', NICHT ',' — Ortsnamen
    enthalten selbst Kommas („Wildunger Weg, 13587 Berlin“), ein Komma-Split
    würde sie zerschneiden."""
    return [x.strip() for x in (tok or "").split("|") if x.strip()]


def _filters(params) -> dict:
    return {
        "bezirk": _parse_list(params.get("bezirk")),
        "orte": _ort_filter(params.get("ort")),
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


@router.get("/orte")
def orte(request: Request,
         bezirk: str | None = None, altersband: str | None = None,
         uhrzeit: str | None = None, von: str | None = None,
         bis: str | None = None, kostenlos: str | None = None,
         quelle: str | None = None, q: str | None = None):
    """Auswahlliste für den Ortsfilter — passt sich den übrigen Filtern an.

    Ist ein Bezirk gewählt, enthält die Liste nur Veranstaltungsorte in diesen
    Bezirken; dasselbe gilt für Alter, Uhrzeit, Zeitraum, „nur kostenlos“ und
    die Volltextsuche. Der aktuell gesetzte Ortsfilter zählt bewusst nicht mit,
    damit eine getroffene Auswahl sichtbar und abwählbar bleibt.
    """
    params = {"bezirk": bezirk, "altersband": altersband, "uhrzeit": uhrzeit,
              "von": von, "bis": bis, "kostenlos": kostenlos, "quelle": quelle, "q": q}
    liste = _store(request).list_orte(_filters(params))
    return {"orte": liste, "anzahl": len(liste)}


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Luftlinie in Kilometern (Haversine)."""
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _naehe(rows: list[dict], lat: float | None, lon: float | None,
           umkreis_km: float | None) -> tuple[list[dict], dict]:
    """Termine im Umkreis, nach Entfernung sortiert. Change 018.

    Termine OHNE Position fallen heraus — das ist unvermeidlich und wird in der
    Oberfläche als Zahl ausgewiesen, nicht verschwiegen.
    """
    if lat is None or lon is None or not umkreis_km:
        return rows, {}
    im, entf = [], {}
    for e in rows:
        if e.get("lat") is None or e.get("lon") is None:
            continue
        d = _km(lat, lon, e["lat"], e["lon"])
        if d <= float(umkreis_km):
            entf[e["id"]] = round(d, 1)
            im.append(e)
    im.sort(key=lambda e: entf.get(e["id"], 9e9))
    return im, entf


@router.get("/events")
def events(request: Request,
           bezirk: str | None = None, altersband: str | None = None,
           uhrzeit: str | None = None, von: str | None = None,
           bis: str | None = None, kostenlos: str | None = None,
           quelle: str | None = None, q: str | None = None,
           ort: str | None = None,
           lat: float | None = None, lon: float | None = None,
           umkreis_km: float | None = None,
           limit: int = Query(500, le=2000)):
    params = {"bezirk": bezirk, "altersband": altersband, "uhrzeit": uhrzeit,
              "von": von, "bis": bis, "kostenlos": kostenlos, "quelle": quelle,
              "q": q, "ort": ort, "limit": limit}
    rows = _store(request).query_events(_filters(params))
    im, entf = _naehe(rows, lat, lon, umkreis_km)
    return [{**_ev_public(e), **({"entfernung_km": entf[e["id"]]} if e["id"] in entf else {})}
            for e in im]


@router.get("/plz/{suchtext}")
def plz_zentrum(suchtext: str, request: Request):
    """Mittelpunkt zu Postleitzahl oder Ortsname — aus dem eigenen Bestand.

    Bewusst aus eigenen Daten statt Fremd-Geokodierung: kostenlos,
    deterministisch, keine zusätzliche Abhängigkeit. Der Mittelpunkt wird auf
    zwei Nachkommastellen gerundet (rund 1 km) — so steht in den Server-Logs
    kein genauer Ort. Der Gerätestandort wird zusätzlich auf drei Stellen
    gerundet (rund 110 m), damit ein Umkreis von 1 km brauchbar bleibt.
    """
    import re as _re
    st = (suchtext or "").strip()
    if len(st) < 3:
        raise HTTPException(400, {"fehler": ["Bitte Postleitzahl oder Ortsname "
                                             "(mindestens 3 Zeichen) angeben."]})
    rows = _store(request).query_events({"limit": 5000})
    ist_plz = bool(_re.fullmatch(r"\d{5}", st))
    treffer = []
    for e in rows:
        if e.get("lat") is None or e.get("lon") is None:
            continue
        if ist_plz:
            if st in (e.get("adresse") or ""):
                treffer.append(e)
        elif st.lower() in (e.get("ort") or "").lower():
            treffer.append(e)
    if not treffer:
        raise HTTPException(404, {"fehler": [f"Zu „{st}“ gibt es keine Termine mit "
                                            f"Kartenposition."]})
    lat = sum(e["lat"] for e in treffer) / len(treffer)
    lon = sum(e["lon"] for e in treffer) / len(treffer)
    return {"suche": st, "lat": round(lat, 2), "lon": round(lon, 2),
            "termine": len(treffer),
            "hinweis": f"Mittelpunkt aus {len(treffer)} Terminen mit Position"}


@router.get("/kalender.ics")
def kalender_ics(request: Request,
                 bezirk: str | None = None, altersband: str | None = None,
                 uhrzeit: str | None = None, von: str | None = None,
                 bis: str | None = None, kostenlos: str | None = None,
                 quelle: str | None = None, q: str | None = None,
                 ort: str | None = None,
                 lat: float | None = None, lon: float | None = None,
                 umkreis_km: float | None = None,
                 wochen: int = Query(8, ge=1, le=52)):
    """Kalender-Abo (iCal) für die aktuelle Filterauswahl — Change 018.

    Pull statt Push: Kalender-Clients holen selbst, kein Versand, kein Login,
    keine Speicherung. Der Link IST die Filterauswahl.
    """
    from datetime import datetime as _dt, timedelta as _td

    from fastapi import Response

    from . import ical
    params = {"bezirk": bezirk, "altersband": altersband, "uhrzeit": uhrzeit,
              "von": von, "bis": bis, "kostenlos": kostenlos, "quelle": quelle,
              "q": q, "ort": ort, "limit": 2000}
    rows = _store(request).query_events(_filters(params))
    im, entf = _naehe(rows, lat, lon, umkreis_km)
    heute = _dt.now(TZ_BERLIN)
    grenze = (heute + _td(weeks=wochen)).strftime("%Y-%m-%d")
    tag = heute.strftime("%Y-%m-%d")
    gewaehlt = []
    for e in im:
        start = (e.get("start_local") or "")[:10]
        letzter = (e.get("ende_local") or e.get("start_local") or "")[:10]
        if start and start <= grenze and letzter >= tag:
            gewaehlt.append(e)
    name = "kinderkram – Veranstaltungen"
    if umkreis_km:
        name += f" (Umkreis {umkreis_km} km)"
    if bezirk:
        name += f" ({bezirk})"
    text = ical.kalender([_ev_public(e) for e in gewaehlt], name=name,
                         stand=tag, entfernungen=entf)
    return Response(content=text, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'inline; filename="kinderkram.ics"'})


@router.get("/events.geojson")
def events_geojson(request: Request,
                   bezirk: str | None = None, altersband: str | None = None,
                   uhrzeit: str | None = None, von: str | None = None,
                   bis: str | None = None, kostenlos: str | None = None,
                   quelle: str | None = None, q: str | None = None,
                   ort: str | None = None,
                   lat: float | None = None, lon: float | None = None,
                   umkreis_km: float | None = None,
                   limit: int = Query(2000, le=5000)):
    params = {"bezirk": bezirk, "altersband": altersband, "uhrzeit": uhrzeit,
              "von": von, "bis": bis, "kostenlos": kostenlos, "quelle": quelle,
              "q": q, "ort": ort, "limit": limit}
    rows = _store(request).query_events(_filters(params))
    im, entf = _naehe(rows, lat, lon, umkreis_km)
    features = []
    ohne = []
    # Ohne Position: über ALLE gefilterten Termine — diese Zahl sagt der
    # Oberfläche, was im Umkreis grundsätzlich nicht erscheinen kann.
    for e in rows:
        if e.get("lat") is None or e.get("lon") is None:
            ohne.append(_ev_public(e))
    for e in im:
        if e.get("lat") is None or e.get("lon") is None:
            # Ohne Position keine Kartenmarke: Leaflet bricht sonst mit
            # „Cannot read properties of null" ab und die Liste bleibt leer
            # (real passiert am 2026-09-13, vom Browser-Test gefunden).
            continue
        pub = _ev_public(e)
        if e["id"] in entf:
            pub["entfernung_km"] = entf[e["id"]]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [e["lon"], e["lat"]]},
            "properties": pub,
        })
    # Termine mit Position, die außerhalb des Umkreises liegen — ehrliche Zahl
    # für die Oberfläche („N Termine konnten nicht erscheinen").
    if umkreis_km:
        bekannt = {e["id"] for e in im}
        ausserhalb = sum(1 for e in rows
                         if e.get("lat") is not None and e["id"] not in bekannt)
    else:
        ausserhalb = 0
    return {
        "type": "FeatureCollection",
        "features": features,
        "ohne_position": ohne,
        "ausserhalb_umkreis": ausserhalb,
        "anzahl": len(im),
    }
