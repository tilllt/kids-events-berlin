"""Adapter jup.berlin/events — offizielles Berliner Jugendportal (Drupal 10).

Verifiziert 2026-09-06 (Fixtures in tests/fixtures/jup-berlin/):
- Listing: <article class="event teaser">, Titel in a.inner[title] bzw.
  .field--name-title, Datum in .field--name-field-event-date
  ("05.09.2026 | 10:00 - 14:00" bzw. mehrteilig), Ort in
  .field--name-field-location ("Berlinweit" möglich). Pagination: ?page=N.
- Detail (/events/<slug>): .field--name-body (Beschreibung),
  .field--name-field-address (Straße/PLZ/Ort), Koordinaten als
  "lat"/"lon"-JSON im Seiten-Skript, .field--name-field-forfree
  ("Teilnahme kostenlos") als Kostenlos-Flag.

robots.txt: erlaubt Crawling der Events-Pfade (2026-09-06 geprüft).
Nutzungspolitik: 1 Request/Sekunde, UA "kids-events-berlin/0.1 (+repo tilllt/kids-events-berlin)".
"""
from __future__ import annotations

import re
from datetime import datetime

import httpx
import parsel

from ..model import TZ_BERLIN, make_event_id, parse_local_dt

BASE = "https://jup.berlin"
LISTING = BASE + "/events"
QUELLE = "jup-berlin"

UA = "kids-events-berlin/0.1 (+https://github.com/tilllt/kids-events-berlin)"
MIN_INTERVAL_S = 1.0

_DATE_OR_TIME = re.compile(r"(\d{2}\.\d{2}\.\d{4})\s*\|\s*(\d{2}:\d{2})|(\d{2}:\d{2})")


def _parse_daterange(text: str) -> tuple[datetime, datetime | None, bool]:
    """Text → (start_local, ende_local, ganztags).

    Formen (beobachtet):
      "05.09.2026 | 00:00 - 05.09.2026 | 23:59"  (ganztägig/mehrtägig)
      "05.09.2026 | 10:00 - 14:00"
      "04.09.2026 | 10:00 - 08.09.2026 | 16:00"
    """
    tokens: list = []
    for m in _DATE_OR_TIME.finditer(text.replace("|", "|")):
        if m.group(1):
            tokens.append(("dt", m.group(1), m.group(2)))
        elif m.group(3):
            tokens.append(("t", m.group(3)))
    if not tokens:
        raise ValueError(f"kein Datum parsebar: {text!r}")
    start: datetime | None = None
    ende: datetime | None = None
    cur_date: str | None = None
    for tok in tokens:
        if tok[0] == "dt":
            cur_date = tok[1]
            dt = parse_local_dt(tok[1], tok[2])
        else:
            dt = parse_local_dt(cur_date or "", tok[1])  # type: ignore[arg-type]
            if cur_date is None:
                raise ValueError(f"Zeit ohne Datum: {text!r}")
        if start is None:
            start = dt
        else:
            ende = dt
    assert start is not None
    ganztags = start.hour == 0 and start.minute == 0 and (
        ende is None or (ende.hour == 23 and ende.minute == 59)
    )
    if ende is None:
        ende = start
    return start, ende, ganztags


class JupBerlinAdapter:
    name = QUELLE
    robots_policy = "erlaubt (robots.txt 2026-09-06 geprüft; Events-Pfade nicht disallowed)"
    min_interval_s = MIN_INTERVAL_S

    def __init__(self):
        self._client = httpx.Client(
            headers={"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9"},
            follow_redirects=True,
            timeout=30,
        )

    # --- Online-Fetch -----------------------------------------------------
    def fetch_listing_page(self, page: int) -> str:
        r = self._client.get(LISTING, params={"page": page} if page else None)
        r.raise_for_status()
        return r.text

    def fetch_detail(self, slug: str) -> str:
        r = self._client.get(f"{BASE}/events/{slug}")
        r.raise_for_status()
        return r.text

    def close(self):
        self._client.close()

    # --- Parsing (pur, offline testbar) -----------------------------------
    @staticmethod
    def parse_listing(html: str) -> list[dict]:
        """→ [{slug, titel, start, ende, ganztags, ort}] (datetime lokal, tz-aware)."""
        sel = parsel.Selector(text=html)
        out = []
        for art in sel.css("article.event.teaser"):
            a = art.css("a.inner")
            if not a:
                continue
            href = a.attrib.get("href", "")
            slug = href.rstrip("/").rsplit("/", 1)[-1] if href else ""
            titel = (a.attrib.get("title") or art.css(".field--name-title ::text").get("") or "").strip()
            if not titel:
                titel = " ".join(art.css(".field--name-title ::text").getall()).strip()
            datetext = " ".join(art.css(".field--name-field-event-date ::text").getall())
            ort = " ".join(art.css(".field--name-field-location ::text").getall()).strip()
            if not slug or not titel or not datetext:
                continue
            try:
                start, ende, ganztags = _parse_daterange(datetext)
            except ValueError:
                continue
            out.append({
                "slug": slug,
                "titel": titel,
                "start": start,
                "ende": ende,
                "ganztags": ganztags,
                "ort": ort or None,
            })
        return out

    @staticmethod
    def parse_detail(html: str) -> dict:
        """→ {beschreibung_kurz, adresse, lat, lon, kostenlos, venue_slug}."""
        sel = parsel.Selector(text=html)
        body = " ".join(sel.css(".field--name-body ::text").getall())
        body = re.sub(r"\s+", " ", body).strip()
        adresse = re.sub(r"\s+", " ", " ".join(
            sel.css(".field--name-field-address ::text").getall())).strip()
        lat = lon = None
        for lat_s, lon_s in re.findall(r'"lat":\s*"?(-?\d+\.\d+)"?[\s\S]{0,80}?"lon":\s*"?(-?\d+\.\d+)"?', html):
            la, lo = float(lat_s), float(lon_s)
            if abs(la) > 1 and abs(lo) > 1:
                lat, lon = la, lo
                break
        frei = bool(sel.css(".field--name-field-forfree"))
        venue = sel.css("a[href^='/orte/']::attr(href)").get()
        venue_slug = venue.rstrip("/").rsplit("/", 1)[-1] if venue else None
        return {
            "beschreibung_kurz": body[:400],
            "adresse": adresse or None,
            "lat": lat,
            "lon": lon,
            "kostenlos_flag": frei,
            "venue_slug": venue_slug,
        }

    # --- Event-Bau ----------------------------------------------------------
    def zu_event(self, row: dict, detail: dict | None, jetzt: datetime) -> dict:
        detail = detail or {}
        slug = row["slug"]
        start_local = row["start"].astimezone(TZ_BERLIN)
        occ = start_local.strftime("%Y%m%dT%H%M")
        source_event_id = f"{slug}#{occ}"
        ort = row.get("ort") or (detail.get("adresse") and "Berlin") or "Ohne Angabe"
        return {
            "id": make_event_id(self.name, source_event_id),
            "titel": row["titel"],
            "beschreibung_kurz": detail.get("beschreibung_kurz"),
            "start_iso": row["start"].astimezone(TZ_BERLIN).isoformat(),
            "ende_iso": (row["ende"].astimezone(TZ_BERLIN).isoformat()
                         if row.get("ende") else None),
            "start_local": start_local.strftime("%Y-%m-%dT%H:%M:%S"),
            "ende_local": (row["ende"].astimezone(TZ_BERLIN).strftime("%Y-%m-%dT%H:%M:%S")
                           if row.get("ende") else None),
            "ganztags": row.get("ganztags", False),
            "ort": ort,
            "adresse": detail.get("adresse"),
            "bezirk": None,
            "lat": detail.get("lat"),
            "lon": detail.get("lon"),
            "kostenlos": None,
            "quelle": self.name,
            "source_event_id": source_event_id,
            "source_url": f"{BASE}/events/{slug}",
            "geholt_am": jetzt.isoformat(),
        }
