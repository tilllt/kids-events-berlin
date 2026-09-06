"""Geokodierungs-Auflösung, gecacht — kein LLM.

- Reverse (Koordinaten → Bezirk): Venue-Koordinaten der Quellen.
- Forward (Ortsname → Koordinaten): Quellen, die nur Ortsnamen liefern
  (z. B. „Neue Nationalgalerie“). Nominatim-Search, deterministisch, 1 req/s,
  Cache in SQLite (auch negativ: nicht gefundene Orte werden nicht wiederholt).
Offline (kein Netz) → kein Lookup.
"""

from __future__ import annotations

import math
import re
import time
import unicodedata
import urllib.parse

import httpx

from .model import BEZIRK_LABELS, BEZIRK_UNBEKANNT

# Label → Slug (Umkehrung von BEZIRK_LABELS; Sonderwerte ausgenommen)
_LABEL_SLUG = {v: k for k, v in BEZIRK_LABELS.items()
               if k not in ("berlinweit", "ausserhalb", "unbekannt")}

NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
# Amtlicher WFS „Adressen Berlin“ (gdi.berlin.de, Datenlizenz Zero 2.0):
# RBS-Adresspunkte mit Straße, Hausnummer, PLZ und Bezirk (bez_name).
WFS_ADRESSEN = "https://gdi.berlin.de/services/wfs/adressen_berlin"


# --- Orts-Alias-Lexikon ----------------------------------------------------
# Quellen liefern Orte teils als Abkürzungen („AGB | Wiese“ = Raum in der
# Amerika-Gedenkbibliothek). Alias → (kanonischer Name, Adresse für die
# Geokodierung). Deterministisch, LLM-frei; erweiterbar je Quelle.
ORT_ALIAS: dict[str, tuple[str, str]] = {
    "AGB": ("Amerika-Gedenkbibliothek", "Blücherplatz 1, 10961 Berlin"),
    "BSTB": ("Berliner Stadtbibliothek", "Breite Straße 30-36, 10178 Berlin"),
    "TREFFPUNKT": ("Amerika-Gedenkbibliothek (Treffpunkt)", "Blücherplatz 1, 10961 Berlin"),
}


def ort_aufloesen(ort: str | None) -> tuple[str | None, str | None]:
    """„AGB | Wiese“ → („Amerika-Gedenkbibliothek (Wiese)“, Lexikon-Adresse).

    Unbekannte Orte bleiben unverändert (adresse None).
    """
    if not ort or ort == "Ohne Angabe":
        return ort, None
    o = ort.strip()
    if "|" in o:
        kuerzel, raum = (p.strip() for p in o.split("|", 1))
        eintrag = ORT_ALIAS.get(kuerzel.upper())
        if eintrag:
            name, adresse = eintrag
            if raum:
                return f"{name} ({raum})", adresse
            return name, adresse
    eintrag = ORT_ALIAS.get(o.upper())
    if eintrag:
        return eintrag
    return ort, None


# --- UTM Zone 33N (ETRS89 ≈ WGS84) → WGS84 --------------------------------
# Standard-UTM-Inverse (Ellipsoid WGS84); für Events genügt Meter-Genauigkeit.
def _utm33n_zu_wgs84(east: float, north: float) -> tuple[float, float]:
    a = 6378137.0
    f = 1 / 298.257223563
    k0 = 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    e1 = (1 - (1 - e2) ** 0.5) / (1 + (1 - e2) ** 0.5)
    x = east - 500000.0
    y = north
    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 ** 3 / 256))
    phi1 = (mu
            + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 * e1 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu))
    n = a / (1 - e2 * math.sin(phi1) ** 2) ** 0.5
    t = math.tan(phi1) ** 2
    c = ep2 * math.cos(phi1) ** 2
    r = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = x / (n * k0)
    lat = (phi1
           - (n * math.tan(phi1) / r)
           * (d * d / 2
              - (5 + 3 * t + 10 * c - 4 * c * c - 9 * ep2) * d ** 4 / 24
              + (61 + 90 * t + 298 * c + 45 * t * t - 252 * ep2
                 - 3 * c * c) * d ** 6 / 720))
    lon = (d
           - (1 + 2 * t + c) * d ** 3 / 6
           + (5 - 2 * c + 28 * t - 3 * c * c + 8 * ep2 + 24 * t * t)
           * d ** 5 / 120) / math.cos(phi1)
    return (math.degrees(lat),  # noqa: E501
            33 * 6 - 183 + math.degrees(lon))


_ADRESSE_RX = re.compile(
    r"^\s*(?P<str>[^,]+?)\s+(?P<hnr>\d{1,4})\s*"
    r"(?:[-/–]\s*(?P<hnr2>\d{1,4}))?\s*(?P<zus>[a-zA-Z])?"
    r"(?:[,\s]+(?P<plz>\d{5}))?\s*"
    r"(?:Berlin|berlin)?\s*,?\s*(?:Berlin)?\s*$")


def _adresse_teile(adresse: str) -> dict | None:
    """„Königin-Luise-Straße 6-8, 14195 Berlin“ → {str, hnr, zus, plz}."""
    a = (adresse or "").strip()
    m = _ADRESSE_RX.match(a)
    if not m:
        return None
    hnr = m.group("hnr")
    if m.group("hnr2"):
        hnr = m.group("hnr2")  # Bereich 6-8 → obere Nr genügt für den Punkt
    return {"str": m.group("str").strip().rstrip(",").strip(),
            "hnr": hnr,
            "zus": (m.group("zus") or "").upper() or None,
            "plz": m.group("plz")}


def adresse_amtlich(store, adresse: str, client: httpx.Client | None = None,
                    sleep_s: float = 0.6) -> dict | None:
    """Amtliche Adress-Geokodierung (WFS Adressen Berlin).

    Nur wenn Straße+Hausnummer (+ möglichst PLZ) parsebar sind; ohne PLZ nur
    bei eindeutigem Treffer. Ergebnis {lat, lon, bezirk, adresse} | None —
    gecacht (auch negativ).
    """
    teile = _adresse_teile(adresse)
    if not teile:
        return None
    key = "amtlich:" + ort_key(adresse)
    cached = store.get_ort_geo(key)
    if cached:
        if not cached["gefunden"]:
            return None
        return {"lat": cached["lat"], "lon": cached["lon"],
                "bezirk": cached["bezirk"], "adresse": cached["adresse"]}
    if client is None:
        return None
    conds = [f"str_name='{teile['str']}'", f"hnr='{teile['hnr']}'"]
    if teile.get("plz"):
        conds.append(f"plz='{teile['plz']}'")
    if teile.get("zus"):
        conds.append(f"hnr_zusatz='{teile['zus']}'")
    cql = " AND ".join(conds)
    try:
        u = (f"{WFS_ADRESSEN}?service=WFS&version=2.0.0&request=GetFeature"
             f"&typeNames=adressen_berlin:adressen_berlin"
             f"&outputFormat=application/json&count=5&cql_filter="
             + urllib.parse.quote(cql))
        r = client.get(u)
        r.raise_for_status()
        feats = (r.json() or {}).get("features", [])
    except Exception:
        return None  # transient — nicht negativ cachen
    if not feats:
        store.set_ort_geo(key, adresse, None, None, None, None, gefunden=False)
        if sleep_s:
            time.sleep(sleep_s)
        return None
    # Bevorzugt exakte Hausnummer ohne Zusatz, sonst erster Treffer
    f0 = feats[0]
    for f in feats:
        p = f.get("properties", {})
        if not (p.get("hnr_zusatz") or "").strip():
            f0 = f
            break
    p = f0.get("properties", {})
    geom = (f0.get("geometry") or {}).get("coordinates")
    if not geom:
        return None
    try:
        lat, lon = _utm33n_zu_wgs84(float(geom[0]), float(geom[1]))
    except (TypeError, ValueError, IndexError):
        return None
    bezirk = _LABEL_SLUG.get(p.get("bez_name")) if p.get("bez_name") else None
    store.set_ort_geo(key, adresse, lat, lon, bezirk, adresse, gefunden=True)
    if sleep_s:
        time.sleep(sleep_s)
    return {"lat": lat, "lon": lon, "bezirk": bezirk, "adresse": adresse}


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
            "countrycodes": "de", "addressdetails": 1,
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
