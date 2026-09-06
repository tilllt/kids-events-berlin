"""Kanonisches Event-Modell + Zeit-/Normalisierungs-Helfer.

Laufzeit-Invariante: Dieses Paket ruft keine LLM-/Embedding-/ML-Dienste auf.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ_BERLIN = ZoneInfo("Europe/Berlin")

# Kanonische Bezirks-Slugs (12 + Sonderwerte), Reihenfolge wie UI-Dropdown.
BEZIRKE = [
    "charlottenburg-wilmersdorf",
    "friedrichshain-kreuzberg",
    "lichtenberg",
    "marzahn-hellersdorf",
    "mitte",
    "neukoelln",
    "pankow",
    "reinickendorf",
    "spandau",
    "steglitz-zehlendorf",
    "tempelhof-schoeneberg",
    "treptow-koepenick",
]
BEZIRK_BERLINWEIT = "berlinweit"
BEZIRK_AUSSERHALB = "ausserhalb"
BEZIRK_UNBEKANNT = "unbekannt"

BEZIRK_LABELS = {
    "charlottenburg-wilmersdorf": "Charlottenburg-Wilmersdorf",
    "friedrichshain-kreuzberg": "Friedrichshain-Kreuzberg",
    "lichtenberg": "Lichtenberg",
    "marzahn-hellersdorf": "Marzahn-Hellersdorf",
    "mitte": "Mitte",
    "neukoelln": "Neukölln",
    "pankow": "Pankow",
    "reinickendorf": "Reinickendorf",
    "spandau": "Spandau",
    "steglitz-zehlendorf": "Steglitz-Zehlendorf",
    "tempelhof-schoeneberg": "Tempelhof-Schöneberg",
    "treptow-koepenick": "Treptow-Köpenick",
    BEZIRK_BERLINWEIT: "Berlinweit",
    BEZIRK_AUSSERHALB: "Außerhalb Berlins",
    BEZIRK_UNBEKANNT: "Ohne Angabe",
}

# Altersbänder für den UI-Filter: (id, min, max, familie_flag).
ALTERSBAND_DEFAULT = [
    ("0-3", 0, 3, False),
    ("4-6", 4, 6, False),
    ("7-10", 7, 10, False),
    ("11-13", 11, 13, False),
    ("14-17", 14, 17, False),
    ("familie", None, None, True),  # explizit als Familienangebot gekennzeichnet
]

UHRZEIT_BANDS = {
    "vormittag": (time(0, 0), time(12, 0)),
    "nachmittag": (time(12, 0), time(17, 0)),
    "abend": (time(17, 0), time(23, 59, 59)),
    "ganztags": None,  # nur für ganztägige Events ohne Uhrzeit
}


def normalize_key(s: str) -> str:
    """Normalisiert Titel/Venue für Vergleich & Blocking: NFC, lowercase, Umlaute, Satzzeichen raus."""
    s = unicodedata.normalize("NFC", s or "").lower().strip()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = re.sub(r"[^a-z0-9äöüß ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def make_event_id(quelle: str, source_event_id: str) -> str:
    """Deterministische Event-ID: sha1(quelle + '/' + source_event_id)."""
    return hashlib.sha1(f"{quelle}/{source_event_id}".encode("utf-8")).hexdigest()


def parse_local_dt(day: str, hm: str) -> datetime:
    """'05.09.2026' + '10:00' → tz-aware datetime (Europe/Berlin)."""
    dt = datetime.strptime(f"{day.strip()} {hm.strip()}", "%d.%m.%Y %H:%M")
    return dt.replace(tzinfo=TZ_BERLIN)


def iso_utc(dt: datetime) -> str:
    """Beliebige datetime → UTC-ISO-String für den Store."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_BERLIN)
    return dt.astimezone(ZoneInfo("UTC")).isoformat()


def parse_iso(s: str) -> datetime:
    """ISO-String aus dem Store → tz-aware datetime (UTC→lokal konvertieren Aufrufer)."""
    return datetime.fromisoformat(s)


def berlin_now() -> datetime:
    return datetime.now(TZ_BERLIN)
