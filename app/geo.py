"""Geokodierungs-Auflösung (Venue-Koordinaten → Bezirk), gecacht.

Externer Dienst: Nominatim Reverse (OpenStreetMap), deterministisch, 1 req/s,
Cache in SQLite — kein LLM. Offline (kein Netz) → bezirk None.
"""
from __future__ import annotations

import time

import httpx

from .model import BEZIRK_LABELS, BEZIRK_UNBEKANNT

# Label → Slug (Umkehrung von BEZIRK_LABELS; Sonderwerte ausgenommen)
_LABEL_SLUG = {v: k for k, v in BEZIRK_LABELS.items()
               if k not in ("berlinweit", "ausserhalb", "unbekannt")}

NOMINATIM = "https://nominatim.openstreetmap.org/reverse"


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
