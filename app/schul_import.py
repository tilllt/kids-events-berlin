"""Schul-Import (Change 005): WFS-Schulstamm + Crawl-Termine in die Admin-DB.

- `import_schulen(store, geo_json_pfad)`: alle allgemeinbildenden Schulen aus
  dem WFS-Dump (dl-de-zero-2.0) als `schulen`-Zeilen (upsert, idempotent).
- `import_crawl_termine(store, crawl_json_pfad)`: bereinigte, zukünftige
  Termin-Funde aus dem Strato-Crawl als `termine_manuell` (status
  `ungeprueft`, quelle_hinweis = Fund-URL), damit der Admin sie prüft.

Konservativer Crawl-Filter (User-Vorgabe „kein LLM, Rauschen raus"):
nur Termin-Keywords + parsebares Zukunftsdatum; `time`-Funde (News-/
Artikel-Zeitstempel) nur, wenn der Text ein Termin-Keyword trägt.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

# Schularten, die Kinder/Jugendliche allgemeinbildend aufnehmen
SCHULARTEN_ALLGEMEINBILDEND = {
    "Grundschule",
    "Integrierte Sekundarschule",
    "Gymnasium",
    "Gemeinschaftsschule",
}

# Termin-Keywords: Tage der offenen Tür / Infoabende / Schnuppern
TERMIN_KEYWORDS = (
    "tag der offenen tür", "tag der offenen tuer", "tag der offenen",
    "infoabend", "informationsabend", "infoveranstaltung",
    "schnuppertag", "schnupperunterricht",
)

# Keyword → kanonischer Kurztitel (Kategorie), damit der Import saubere,
# deduplizierbare Titel liefert statt roher Textfetzen.
KEYWORD_TITEL = (
    ("tag der offenen", "Tag der offenen Tür"),
    ("infoabend", "Infoabend"),
    ("informationsabend", "Infoabend"),
    ("infoveranstaltung", "Infoveranstaltung"),
    ("schnuppertag", "Schnuppertag"),
    ("schnupperunterricht", "Schnupperunterricht"),
)


def _hat_termin_keyword(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in TERMIN_KEYWORDS)


def _zeile_zu_termin(zeile: str, url: str | None, heute: date) -> dict | None:
    """Eine Crawl-Fundzeile → bereinigter Termin-Vorschlag oder None."""
    zeile = (zeile or "").strip()
    if len(zeile) < 6 or len(zeile) > 600:
        return None
    low = zeile.lower()
    kw = next((k for k, _ in KEYWORD_TITEL if k in low), None)
    if not kw:
        return None
    datum = _parse_datum(zeile)
    if not datum:
        return None
    if datum < heute:
        return None
    if datum > heute + timedelta(days=400):
        return None
    # Uhrzeit: "von 09:00 bis 12:00" / "von 10 – 13 Uhr" / "8.30 Uhr"
    # Fallback NUR mit explizitem "Uhr" — sonst matcht das Datum "12.09.2026"
    # als 12:09 (realer Fund). Datum-Separator ist "." oder "-", nie ":".
    zeit = None
    m = re.search(r"(?:von|ab)\s+(\d{1,2})[:.](\d{2})", zeile)
    if not m:
        m = re.search(r"(\d{1,2})[:.](\d{2})\s*uhr", zeile)
    if m:
        zeit = f"{int(m.group(1)):02d}:{m.group(2)}"
    titel = dict(KEYWORD_TITEL).get(kw, kw.capitalize())
    return {"titel": titel, "start_datum": datum.strftime("%d.%m.%Y"),
            "start_zeit": zeit, "url": url, "beleg": zeile[:400]}


def _norm_bezirk(name: str) -> str:
    """'Charlottenburg-Wilmersdorf' → 'charlottenburg-wilmersdorf' (Slug)."""
    return (name or "").strip().lower()


def _norm_schulart(wfs_schulart: str) -> str:
    """WFS-schulart → schulform-Spalte (unverändert übernehmen)."""
    return (wfs_schulart or "").strip()


def import_schulen(store, geo_json_pfad: str) -> dict:
    """WFS-Dump (GeoJSON) → schulen. Nur allgemeinbildende. Idempotent."""
    with open(geo_json_pfad, encoding="utf-8") as f:
        dump = json.load(f)
    feats = dump.get("features", [])
    n_neu = n_ges = n_uebersprungen = 0
    for feat in feats:
        p = feat.get("properties", {})
        schulart = _norm_schulart(p.get("schulart"))
        if schulart not in SCHULARTEN_ALLGEMEINBILDEND:
            n_uebersprungen += 1
            continue
        n_ges += 1
        strasse = (p.get("strasse") or "").strip()
        hausnr = (p.get("hausnr") or "").strip()
        if strasse and hausnr:
            strasse = f"{strasse} {hausnr}"
        sch = {
            "bsn": str(p.get("bsn") or "").strip(),
            "name": (p.get("schulname") or "").strip(),
            "schulform": schulart,
            "bezirk": _norm_bezirk(p.get("bezirk")),
            "ortsteil": (p.get("ortsteil") or "").strip(),
            "plz": (p.get("plz") or "").strip(),
            "strasse": strasse,
            "email": (p.get("email") or "").strip() or None,
            "website": (p.get("internet") or "").strip() or None,
            "notiz": f"Quelle: Schul-WFS Berlin (dl-de-zero-2.0), Stand {p.get('schuljahr') or 'unbekannt'}",
        }
        if not sch["bsn"] or not sch["name"]:
            continue
        try:
            store.upsert_schule(sch)
            n_neu += 1
        except ValueError:
            continue
    return {"gesamt_wfs": len(feats), "importiert": n_neu,
            "allgemeinbildend_im_dump": n_ges, "uebersprungen": n_uebersprungen}


def import_schulzweig_ids(store, mapping_json_pfad: str) -> dict:
    """Mapping {bsn: id_schulzweig} → schulen.schulzweig_id (Schulportrait-Link).

    Das Mapping stammt aus app/bsn_schulzweig_map.py (Redirect-Abgriff des
    Berliner Schulverzeichnisses). Nur BSNs aktualisieren, die in der DB
    existieren; idempotent."""
    with open(mapping_json_pfad, encoding="utf-8") as f:
        mapping = json.load(f)
    n_ges = n_ok = n_unbekannt = 0
    for bsn, szid in mapping.items():
        n_ges += 1
        sch = store.get_schule(str(bsn))
        if not sch:
            n_unbekannt += 1
            continue
        if str(sch.get("schulzweig_id") or "") == str(szid):
            continue
        sch["schulzweig_id"] = str(szid)
        store.upsert_schule(sch)
        n_ok += 1
    return {"mapping_eintraege": n_ges, "aktualisiert": n_ok,
            "bsn_unbekannt": n_unbekannt}


# --- Crawl-Termine -----------------------------------------------------------

_DATUM_RE = re.compile(
    r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})|(\d{4})-(\d{1,2})-(\d{1,2})"
)


def _parse_datum(text: str) -> date | None:
    """Erstes parsebares Datum im Text (TT.MM.JJ[JJ] oder JJJJ-MM-TT)."""
    m = _DATUM_RE.search(text)
    if not m:
        return None
    if m.group(1):
        tag, mon, jahr = int(m.group(1)), int(m.group(2)), m.group(3)
        jahr = 2000 + int(jahr) if len(jahr) == 2 else int(jahr)
    else:
        jahr, mon, tag = int(m.group(4)), int(m.group(5)), int(m.group(6))
    try:
        return date(jahr, mon, tag)
    except ValueError:
        return None


def import_crawl_termine(store, crawl_json_pfad: str) -> dict:
    """Crawl-Rohdaten → termine_manuell (ungeprueft, dedupliziert)."""
    with open(crawl_json_pfad, encoding="utf-8") as f:
        eintraege = json.load(f)
    heute = datetime.now().astimezone().date()
    n_schulen_gefunden = n_roh = n_importiert = n_duplikat = n_alt = 0
    gesehen: set[tuple] = set()
    fehler_schulen: list[str] = []
    for e in eintraege:
        bsn = str(e.get("bsn") or "").strip()
        if not bsn or not store.get_schule(bsn):
            fehler_schulen.append(bsn)
            continue
        n_schulen_gefunden += 1
        for t in (e.get("termine") or []):
            n_roh += 1
            zeile = t.get("zeile") or t.get("text") or ""
            url = t.get("url")
            if t.get("quelle") == "time" and not _hat_termin_keyword(zeile):
                n_alt += 1  # News-Zeitstempel ohne Termin-Kontext
                continue
            term = _zeile_zu_termin(zeile, url, heute)
            if not term:
                n_alt += 1
                continue
            schl = (bsn, term["start_datum"], term["titel"].lower()[:80])
            if schl in gesehen:
                n_duplikat += 1
                continue
            # Idempotenz: existiert der Termin (Schule+Datum+Titel) schon in der
            # DB (vorheriger Lauf)? Sonst verdoppelt jeder Re-Import den Bestand.
            vorhanden = any(
                (bestehend.get("schule_bsn") == bsn
                 and bestehend.get("start_datum") == term["start_datum"]
                 and (bestehend.get("titel") or "").lower()[:80] == schl[2])
                for bestehend in store.list_termine_manuell(schule_bsn=bsn))
            if vorhanden:
                n_duplikat += 1
                continue
            gesehen.add(schl)
            try:
                store.upsert_termin_manuell({
                    "schule_bsn": bsn,
                    "titel": term["titel"],
                    "start_datum": term["start_datum"],
                    "start_zeit": term["start_zeit"],
                    "url": url,
                    "status": "ungeprueft",
                    "quelle_hinweis": f"automatisch erkannt: {url or '?'}",
                    "beschreibung": f"Crawl-Fund: {term['beleg']}",
                })
                n_importiert += 1
            except ValueError:
                continue
    return {"schulen_mit_funden": n_schulen_gefunden, "roh_funde": n_roh,
            "importiert": n_importiert, "duplikate": n_duplikat,
            "verworfen_alt_oder_rauschen": n_alt,
            "schulen_ohne_stamm": len(set(fehler_schulen))}
