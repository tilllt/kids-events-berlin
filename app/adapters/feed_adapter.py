"""Generischer RSS-Feed-Adapter (Stufe 1) für die Scrape-Pipeline.

Erfüllt das Pipeline-Interface (fetch_listing_page/parse_listing/zu_event/
close) — kein Quell-spezifischer Code. Der Berliner Landeskalender
(berlin.de) ist die erste Feed-Quelle des Projekts.

Zeit-Semantik: Viele Kalender-RSS (z. B. berlin.de) stempeln die
Event-Startzeit als +0000, obwohl die angezeigte (lokale) Zeit im Titel
steht — eine naive UTC→Berlin-Konvertierung verschiebt Events um 1–2 h.
Der Adapter parst deshalb zuerst eine Datums-/Zeit-Klammer am Titelende
(„(15.01.2027 15:30 - 18:00 Uhr)“, „(17.02.2027)“) als Berliner Ortszeit;
`published` dient nur als Fallback (ebenfalls als Berlin-Zeit
interpretiert, NICHT UTC-konvertiert — der Server stampft Lokalzeit).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import feedparser
import httpx

from ..model import TZ_BERLIN, make_event_id

UA = ("Mozilla/5.0 (compatible; KinderEventsBerlin/0.1; "
      "+https://kinderkram.cia-spandau.de)")
_TZ = ZoneInfo("Europe/Berlin")

# Datumsklammer am Titelende: „(15.01.2027 15:30 - 18:00 Uhr)“,
# „(17.02.2027)“, „(02.03.2027 14:00 Uhr)“. Gruppen: Datum, Zeit1, Zeit2.
_TITEL_TERMIN_RE = re.compile(
    r"\((\d{1,2})\.(\d{1,2})\.(\d{4})"
    r"(?:\s+(\d{1,2}):(\d{2}))?"
    r"(?:\s*-\s*(\d{1,2}):(\d{2}))?"
    r"\s*(?:Uhr)?\)\s*$"
)


def _titel_termin(titel: str) -> tuple[datetime | None, datetime | None, bool, str]:
    """Termin aus der Titel-Datumsklammer → (start, ende, ganztags, sauberer Titel).

    Klammer fehlt → (None, None, False, Titel unverändert).
    Nur Datum ohne Uhrzeit → ganztags (00:00), wie die Quellen-Konvention.
    """
    m = _TITEL_TERMIN_RE.search(titel)
    if not m:
        return None, None, False, titel
    tag, monat, jahr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    sauber = titel[: m.start()].strip().rstrip(" -–")
    if m.group(4):  # Uhrzeit vorhanden → start mit Zeit
        stunde, minute = int(m.group(4)), int(m.group(5))
        start = datetime(jahr, monat, tag, stunde, minute, tzinfo=_TZ)
        ende = None
        if m.group(6):
            ende = datetime(jahr, monat, tag, int(m.group(6)), int(m.group(7)),
                            tzinfo=_TZ)
        return start, ende, False, sauber
    # Nur Datum → ganztags
    start = datetime(jahr, monat, tag, 0, 0, tzinfo=_TZ)
    return start, None, True, sauber


class FeedAdapter:
    """RSS/Atom-Abo: eine Listing-URL, Items → Events.

    Konfiguration aus der Quellen-Zeile (DB): url = Feed-URL,
    horizont_tage = Fenster (0 = kein Fenster-Filter).
    """

    min_interval_s = 1.0
    robots_policy = "RSS-Abo; siehe docs/quellen.md"
    braucht_detail = False  # Feed trägt Titel/Beschreibung/Zeit selbst

    def __init__(self, quelle: str, *, url: str | None = None,
                 horizont_tage: int = 0, min_interval_s: float | None = None):
        self.name = quelle
        self._feed_url = (url or "").strip()
        self.horizont_tage = int(horizont_tage or 0)
        if min_interval_s:
            self.min_interval_s = float(min_interval_s)
        self._client = httpx.Client(
            headers={"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9"},
            follow_redirects=True, timeout=30,
        )
        self._warnungen: list[str] = []

    # --- Warnungen (von der Pipeline in die Fehler-Queue) -------------------
    def drain_warnungen(self) -> list[str]:
        out, self._warnungen = self._warnungen, []
        return out

    # --- Fetch --------------------------------------------------------------
    def fetch_listing_page(self, page: int = 0) -> str:
        if page > 0:
            return ""  # Feed hat eine Seite; Pipeline bricht über 0 Rows ab
        r = self._client.get(self._feed_url)
        r.raise_for_status()
        return r.text

    def fetch_detail(self, slug: str) -> str:
        return ""

    def parse_detail(self, html: str) -> dict:
        """Feed trägt alle Felder selbst — kein Detail-Enrichment."""
        return {}

    def close(self):
        self._client.close()

    # --- Listing-Parsing ----------------------------------------------------
    def parse_listing(self, xml: str) -> list[dict]:
        """→ [{slug, titel, start, ende, ganztags, url, beschreibung_kurz}]."""
        if not (xml or "").strip():
            return []  # leere Seite = Paginations-Ende, keine Strukturwarnung
        d = feedparser.parse(xml)
        if d.bozo and not d.entries:
            self._warnungen.append(f"Feed nicht parsebar: {getattr(d, 'bozo_exception', '?')}")
        out = []
        for e in d.entries:
            try:
                row = self._item_zu_row(e)
            except ValueError as ex:
                self._warnungen.append(f"Feed-Item: {ex}")
                continue
            if row:
                out.append(row)
        if not out and not d.entries:
            self._warnungen.append("Feed liefert 0 Items (Struktur geändert?)")
        return out

    def _item_zu_row(self, e) -> dict:
        titel = (e.get("title") or "").strip()
        if not titel:
            raise ValueError("Item ohne Titel übersprungen")
        start, ende, ganztags, sauber = _titel_termin(titel)
        # Fallback: published (Lokalzeit-Stempel des Servers, s. Modul-Doku)
        if start is None and e.get("published_parsed"):
            st = e["published_parsed"]
            start = datetime(*st[:6], tzinfo=_TZ)
            ganztags = (st[3] == 0 and st[4] == 0)
        if start is None:
            raise ValueError(f"Kein Termin für: {titel[:60]}")
        url = (e.get("link") or "").strip()
        guid = (e.get("guid") or url or titel).strip()
        slug = hashlib.sha1(guid.encode("utf-8")).hexdigest()[:16]
        beschreibung = (e.get("summary") or e.get("description") or "").strip()
        return {
            "slug": slug,
            "titel": sauber or titel,
            "start": start,
            "ende": ende,
            "ganztags": ganztags,
            "url": url,
            "beschreibung_kurz": beschreibung[:400] or None,
        }

    # --- Event-Bau ----------------------------------------------------------
    def zu_event(self, row: dict, detail: dict | None, jetzt: datetime) -> dict:
        start = row["start"]
        start_local = start.astimezone(TZ_BERLIN)
        occ = start_local.strftime("%Y%m%dT%H%M")
        source_event_id = f"{row['slug']}#{occ}"
        ende = row.get("ende")
        return {
            "id": make_event_id(self.name, source_event_id),
            "titel": row["titel"],
            "beschreibung_kurz": row.get("beschreibung_kurz")
                or (detail or {}).get("beschreibung_kurz"),
            "start_iso": start.astimezone(TZ_BERLIN).isoformat(),
            "ende_iso": (ende.astimezone(TZ_BERLIN).isoformat() if ende else None),
            "start_local": start_local.strftime("%Y-%m-%dT%H:%M:%S"),
            "ende_local": (ende.astimezone(TZ_BERLIN).strftime("%Y-%m-%dT%H:%M:%S")
                           if ende else None),
            "ganztags": row.get("ganztags", False),
            # Feed trägt keinen Veranstaltungsort → validate verlangt ort;
            # „Ohne Angabe“ ist der projektweite Fallback (keine Geokodierung).
            "ort": "Ohne Angabe",
            "adresse": None,
            "bezirk": None,
            "lat": None,
            "lon": None,
            "kostenlos": None,
            "quelle": self.name,
            "source_event_id": source_event_id,
            "source_url": row.get("url") or self._feed_url,
            "geholt_am": jetzt.isoformat(),
        }
