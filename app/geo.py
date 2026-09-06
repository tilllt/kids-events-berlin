"""Geokodierungs-Auflösung, gecacht — kein LLM.

- Reverse (Koordinaten → Bezirk): Venue-Koordinaten der Quellen.
- Forward (Ortsname → Koordinaten): Quellen, die nur Ortsnamen liefern
  (z. B. „Neue Nationalgalerie“). Nominatim-Search, deterministisch, 1 req/s,
  Cache in SQLite (auch negativ: nicht gefundene Orte werden nicht wiederholt).
Offline (kein Netz) → kein Lookup.
"""

from __future__ import annotations

import re
import time
import unicodedata

import httpx

from .model import BEZIRK_LABELS, BEZIRK_UNBEKANNT

# Label → Slug (Umkehrung von BEZIRK_LABELS; Sonderwerte ausgenommen)
_LABEL_SLUG = {v: k for k, v in BEZIRK_LABELS.items()
               if k not in ("berlinweit", "ausserhalb", "unbekannt")}

NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"


def ort_key(ort: str) -> str:
    """Normalisierter Cache-Schlüssel für einen Ortsnamen."""
    s = unicodedata.normalize("NFC", ort or "").strip().lower()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = re.sub(r"\s+", " ", s)
    return s


def bezirk_from_latlon(store, lat: float, lon: float, client: httpx.Client | None = None,
                       sleep_s: float = 1.1) -> str | None:
    """Bezirk zu Koordinaten: Cache → Nominatim-Reverse → None."""
    key = f"{lat:.5f},{lon:.5f}"
    cached = store.get_venue_cache(key)
    if cached:
        return cached["bezirk"] or None
    if client is None:
        return None  # offline: kein Netz, kein Raten
    try:
        r = client.get(NOMINATIM, params={
            "format": "jsonv2", "lat": lat, "lon": lon, "zoom": 10,
        })
        r.raise_for_status()
        addr = r.json().get("address", {})
        bezirk = None
        for k in ("borough", "city_district", "suburb", "county"):
            cand = addr.get(k)
            if cand and cand in _LABEL_SLUG:
                bezirk = _LABEL_SLUG[cand]
                break
        store.set_venue_cache(key, lat, lon, bezirk, addr.get("city", "Berlin"))
        if sleep_s:
            time.sleep(sleep_s)
        return bezirk
    except Exception:
        store.set_venue_cache(key, lat, lon, BEZIRK_UNBEKANNT, None)
        return None


def ort_koordinaten(store, ort: str, client: httpx.Client | None = None,
                    sleep_s: float = 1.1) -> dict | None:
    """Ortsname → {lat, lon, bezirk, adresse} | None (nicht auflösbar).

    Nominatim-Search 'q=<Ort>, Berlin'. Treffer werden gecacht, Fehlversuche
    negativ gecacht (gefunden=0) — Wiederholung erst nach Cache-Löschung.
    """
    ort = (ort or "").strip()
    if len(ort) < 4 or ort == "Ohne Angabe":
        return None
    key = ort_key(ort)
    cached = store.get_ort_geo(key)
    if cached:
        if not cached["gefunden"]:
            return None
        return {"lat": cached["lat"], "lon": cached["lon"],
                "bezirk": cached["bezirk"], "adresse": cached["adresse"]}
    if client is None:
        return None  # offline
    try:
        r = client.get(NOMINATIM_SEARCH, params={
            "q": f"{ort}, Berlin", "format": "jsonv2", "limit": 1,
            "countrycodes": "de",
        })
        r.raise_for_status()
        treffer = r.json()
    except Exception:
        return None  # Netz/API-Fehler: nicht negativ cachen (transient)
    if not treffer:
        store.set_ort_geo(key, ort, None, None, None, None, gefunden=False)
        if sleep_s:
            time.sleep(sleep_s)
        return None
    t = treffer[0]
    try:
        lat = float(t["lat"])
        lon = float(t["lon"])
    except (KeyError, TypeError, ValueError):
        store.set_ort_geo(key, ort, None, None, None, None, gefunden=False)
        return None
    addr = t.get("address", {})
    bezirk = None
    for k in ("borough", "city_district", "suburb", "county"):
        cand = addr.get(k)
        if cand and cand in _LABEL_SLUG:
            bezirk = _LABEL_SLUG[cand]
            break
    if not bezirk:
        # Nominatim-address ist uneinheitlich → Bezirks-Label im Anzeigenamen
        anzeige_low = (t.get("display_name") or "").lower()
        for label, slug in _LABEL_SLUG.items():
            if label.lower() in anzeige_low:
                bezirk = slug
                break
    # Adresse = Anzeigename, gekürzt um das Länder-Suffix („…, Deutschland“)
    anzeige = t.get("display_name") or ""
    adresse = re.sub(r",\s*Deutschland\s*$", "", anzeige) if anzeige else None
    store.set_ort_geo(key, ort, lat, lon, bezirk, adresse, gefunden=True)
    if sleep_s:
        time.sleep(sleep_s)
    return {"lat": lat, "lon": lon, "bezirk": bezirk, "adresse": adresse}
