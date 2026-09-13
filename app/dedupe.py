"""Dubletten-Erkennung über Quellen hinweg (Change 011).

Warum ein eigenes Modul: Die bisherige Bereinigung greift nur INNERHALB einer
Quelle (gleiche `quelle` + Titel + Start + Ort). Dass dieselbe Veranstaltung von
zwei Quellen gelistet wird — real: ein Tag der offenen Tür stand 57× im Bestand,
je 29×/28× aus familienportal und Kinderkulturkalender — blieb damit unsichtbar.

Was als DIESELBE Veranstaltung gilt (alle Bedingungen müssen zutreffen):

1. **Gleicher Tag** (start_local[:10]).
2. **Titel gleich** nach Normalisierung (Kleinschreibung, Umlaut-Faltung,
   Satzzeichen weg). Das ist die Schutzregel gegen falsche Merges: das ZLB
   bietet am selben Ort zur selben Zeit VERSCHIEDENE Veranstaltungen an, und
   verschiedene Titel bedeuten hier immer verschiedene Veranstaltungen.
3. **Uhrzeit gleich**, wenn beide eine haben (fehlende Zeit = Ganztags/unbekannt
   → zählt als „passt"). Bewusst KEINE Toleranz: das ZLB führt dieselbe
   Veranstaltung als Stundenblöcke (09:00, 10:00, 11:00) — eine Toleranz würde
   diese echten Slots zusammenwerfen. Gleiche Titel an gleichem Tag mit
   abweichender Zeit landen deshalb im Verdachts-Report, nicht im Merge.
4. **Ort verträglich:** beide Koordinaten vorhanden → höchstens `MAX_METER`
   auseinander; sonst Ortsnamen gleich; sonst darf eine Seite generisch
   („Berlin", leer) sein. Zwei verschiedene echte Ortsnamen = zwei Orte
   („Sternstunde" läuft in zwei Sternwarten am selben Tag).

Nichts wird still gelöscht: der kanonische Datensatz behält seine Quelle, die
anderen Quellen wandern als Provenienz in `quellen_json`, und leere Felder des
Kanons werden aus den Dubletten aufgefüllt (real: die Endzeit stand nur in einer
der beiden Quellen).
"""
from __future__ import annotations

import math
import re
from datetime import datetime

# Quellen-Priorität für den kanonischen Datensatz: je offizieller, desto
# besser. 1 = amtlich/Land, 2 = Einrichtung, 3 = Aggregator/Portal.
QUELLEN_PRIO = {
    "familienportal": 1,
    "jup-berlin": 1,
    "berlin-senbjf-kalender": 1,
    "zlb": 2,
    "museumsportal": 2,
    "gruen-berlin": 2,
    "kinderkulturkalender": 3,
}
PRIO_STANDARD = 2

# Ortsangaben ohne Unterscheidungskraft (Stadt statt Ortsteil).
GENERISCHE_ORTE = {"", "berlin", "online", "verschiedene orte", "diverse"}

MAX_METER = 200.0  # Toleranz zwischen zwei Koordinaten desselben Ortes

# Felder, die beim Zusammenführen aus der Dublette aufgefüllt werden können
# (der Kanon gewinnt bei Konflikten).
FUELLBARE_FELDER = ("ende_local", "ende_iso", "adresse", "bezirk", "lat", "lon",
                    "beschreibung_kurz", "altersband_min", "altersband_max",
                    "kostenlos")

_UMLAUTE = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def titel_norm(titel: str | None) -> str:
    """Vergleichsform des Titels: klein, Umlaute gefaltet, Satzzeichen weg."""
    t = (titel or "").strip().lower()
    for k, v in _UMLAUTE.items():
        t = t.replace(k, v)
    t = re.sub(r"[^\w\s]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def ort_norm(ort: str | None) -> str:
    """Vergleichsform des Orts (Stadt-Token ohne Aussage bleibt generisch)."""
    o = titel_norm(ort)
    o = re.sub(r"\b(berlin|deutschland|gmbh|e v|ev|ggmbh)\b", " ", o)
    return re.sub(r"\s+", " ", o).strip()


def ist_generisch(ort: str | None) -> bool:
    return ort_norm(ort) in GENERISCHE_ORTE or not ort_norm(ort)


def meter_abstand(a: dict, b: dict) -> float | None:
    """Haversine-Distanz in Metern; None, wenn eine Seite keine Koordinaten hat."""
    try:
        lat1, lon1, lat2, lon2 = (float(a["lat"]), float(a["lon"]),
                                  float(b["lat"]), float(b["lon"]))
    except (KeyError, TypeError, ValueError):
        return None
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _tag(ev: dict) -> str:
    return (ev.get("start_local") or "")[:10]


def _zeit(ev: dict) -> str | None:
    if ev.get("ganztags"):
        return None
    s = ev.get("start_local") or ""
    return s[11:16] if len(s) >= 16 else None


def _ort_vertraeglich(a: dict, b: dict) -> tuple[bool, str]:
    """Orts-Verträglichkeit: Name zuerst, dann Koordinaten.

    Der Name entscheidet bewusst VOR den Koordinaten: zwei echte, verschiedene
    Ortsnamen bei gleichen Koordinaten (gleiches Gebäude, zwei Einrichtungen)
    sind zwei Orte — dieselbe Regel schützt „Sternstunde“ in zwei Sternwarten.
    Ein Namensteil-Verhältnis („Klax Kinderkrippe“ ⊂ „Klax Kinderkrippe
    Mäusekiste“) gilt als derselbe Ort, generische Angaben („Berlin“, leer)
    sind immer verträglich.
    """
    oa, ob = ort_norm(a.get("ort")), ort_norm(b.get("ort"))
    if oa and ob and oa != ob:
        if len(oa) >= 6 and len(ob) >= 6 and (oa in ob or ob in oa):
            return True, ""
        return False, "anderer_ort_name"
    d = meter_abstand(a, b)
    if d is not None and d > MAX_METER:
        return False, "anderer_ort_koordinaten"
    return True, ""


def gleiche_veranstaltung(a: dict, b: dict) -> tuple[bool, str]:
    """Identität zweier Datensätze → (gleich, Grund bei Ablehnung)."""
    if a.get("id") and a.get("id") == b.get("id"):
        return False, "gleicher_datensatz"
    if not _tag(a) or _tag(a) != _tag(b):
        return False, "anderer_tag"
    if titel_norm(a.get("titel")) != titel_norm(b.get("titel")):
        return False, "anderer_titel"
    za, zb = _zeit(a), _zeit(b)
    if za and zb and za != zb:
        return False, "andere_uhrzeit"
    return _ort_vertraeglich(a, b)


def gruppiere(events: list[dict]) -> list[dict]:
    """Kandidatengruppen (gleicher Tag + gleicher normalisierter Titel).

    Blocking, damit nicht jedes Paar geprüft wird: nur innerhalb einer Gruppe
    kann überhaupt eine Dublette entstehen.
    """
    gruppen: dict[tuple[str, str], list[dict]] = {}
    for ev in events:
        gruppen.setdefault((_tag(ev), titel_norm(ev.get("titel"))), []).append(ev)
    return [g for g in gruppen.values() if len(g) > 1]


def quelle_prio(quelle: str | None) -> int:
    return QUELLEN_PRIO.get((quelle or "").strip().lower(), PRIO_STANDARD)


def feld_reichtum(ev: dict) -> int:
    """Wie viele verwertbare Felder ein Datensatz hat (Kanon-Wahl bei Gleichstand)."""
    felder = ("beschreibung_kurz", "ende_local", "adresse", "bezirk", "lat",
              "altersband_min", "altersband_max")
    return sum(1 for f in felder if ev.get(f) not in (None, "", 0))


def waehle_kanon(gruppe: list[dict]) -> dict:
    """Der Datensatz, der bleibt: manuell gepflegt > Quellen-Priorität > Datenlage."""
    return sorted(gruppe, key=lambda e: (
        0 if e.get("manuell") else 1,          # Admin-Edits gewinnen immer
        quelle_prio(e.get("quelle")),
        -feld_reichtum(e),
        str(e.get("id") or ""),
    ))[0]


def finde_dubletten(events: list[dict]) -> dict:
    """Dubletten-Gruppen + Verdachtsfälle (gleicher Tag/Titel, andere Zeit/Ort).

    Gemergt wird nur, was die Identitätsregeln erfüllt. Alles, was im selben
    Block steckt, aber abweicht (z. B. ZLB-Stundenblöcke mit gleichem Titel),
    erscheint im Verdachts-Report — der Admin entscheidet, nichts passiert still.
    """
    merges: list[dict] = []
    verdacht: list[dict] = []
    for gruppe in gruppiere(events):
        rest = list(gruppe)
        while len(rest) > 1:
            kanon = waehle_kanon(rest)
            dubletten = [k for k in rest
                         if k["id"] != kanon["id"] and gleiche_veranstaltung(kanon, k)[0]]
            if not dubletten:
                for i, a in enumerate(rest):
                    for b in rest[i + 1:]:
                        gleich, grund = gleiche_veranstaltung(a, b)
                        if not gleich:
                            verdacht.append({"behalten": a, "kandidat": b, "grund": grund})
                break
            merges.append({"kanon": kanon, "dubletten": dubletten})
            entfallen = {d["id"] for d in dubletten}
            rest = [k for k in rest if k["id"] not in entfallen]
    return {"merges": merges, "verdacht": verdacht,
            "entfernbar": sum(len(m["dubletten"]) for m in merges)}


def provenienz_ergaenzen(quellen: list[dict], quelle: str, url: str | None,
                         source_event_id: str | None) -> bool:
    """Eine weitere gelistete Quelle vermerken — höchstens ein Eintrag je Quelle.

    Die erste Fund-URL einer Quelle ist der Beleg; weitere Zeilen derselben
    Quelle würden die Provenienz nur aufblähen (real: 4 Zeilen je Quelle über
    Wiederholungsläufe).
    """
    if any(q.get("quelle") == quelle for q in quellen):
        return False
    quellen.append({"quelle": quelle, "source_url": url,
                    "source_event_id": source_event_id})
    return True


def fehlende_felder(kanon: dict, dublette: dict) -> dict:
    """Felder, die der Kanon leer hat und die die Dublette füllen kann."""
    return {f: dublette[f] for f in FUELLBARE_FELDER
            if kanon.get(f) in (None, "") and dublette.get(f) not in (None, "")}
