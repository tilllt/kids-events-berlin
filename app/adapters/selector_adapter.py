"""Generischer Regel-Adapter (Stufe 2): YAML-Regeln aus der DB → Events.

Erfüllt das Pipeline-Interface (fetch_listing_page/parse_listing/fetch_detail/
parse_detail/zu_event) — kein Quell-spezifischer Code. Extraktion:
- Listing: parsel (CSS, Feld-Optionen css/attr/regex/format/join)
- Detail: extruct JSON-LD (@type: Event) mit JSONPath-Feld-Mapping (jsonpath-ng)

Deterministisch; kein LLM. Warnungen beim Parsen (nicht extrahierbare Items)
werden gesammelt und von der Pipeline in die Fehler-Queue geschrieben.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, time as dtime
from typing import Any
from urllib.parse import urljoin

import httpx
import parsel

from ..model import TZ_BERLIN, make_event_id
from ..regeln import validate_regeln_yaml

UA = "kids-events-berlin/0.2 (+https://github.com/tilllt/kids-events-berlin)"


def _lade_regeln(regel_yaml: str | None, quelle: str) -> dict:
    fehler = validate_regeln_yaml(regel_yaml or "", quelle)
    if fehler:
        raise ValueError(f"Regeln für {quelle} ungültig: {'; '.join(fehler[:3])} …")
    import yaml
    return yaml.safe_load(regel_yaml or "")


def _feld_wert(el: parsel.Selector, regel: dict) -> str | None:
    """Extrahiert Text/Attribut aus einem Item-Element (parsel)."""
    css = regel.get("css")
    if not css:
        return None
    gefunden = el.css(css)
    if not gefunden:
        return None
    if regel.get("attr"):
        for g in gefunden:
            v = g.attrib.get(regel["attr"])
            if v:
                return v.strip()
        return None
    texte = []
    for g in gefunden:
        texte.extend(g.css("::text").getall())
    roh = regel.get("join") if regel.get("join") else " "
    text = roh.join(t.strip() for t in texte if t and t.strip()).strip()
    if not text and len(gefunden) == 1:
        text = (gefunden[0].get() or "").strip()
    return text or None


def _regex_ziehen(text: str | None, rx: str | None) -> str | None:
    if not text or not rx:
        return text
    m = re.search(rx, text)
    return m.group(1) if m and m.groups() else (m.group(0) if m else None)


def _parse_zeit(text: str | None, fmt: str | None, feld: str) -> datetime:
    """Text → tz-aware datetime Europe/Berlin. Wirft ValueError mit Kontext."""
    if not text:
        raise ValueError(f"{feld}: kein Wert extrahiert")
    if fmt:
        try:
            dt = datetime.strptime(text.strip(), fmt)
        except ValueError:
            raise ValueError(f"{feld}: '{text[:40]}' passt nicht zu Format '{fmt}'") from None
    else:
        try:
            dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"{feld}: '{text[:40]}' ist kein ISO-Datum") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_BERLIN)
    else:
        dt = dt.astimezone(TZ_BERLIN)
    return dt


class SelectorAdapter:
    name = ""  # wird aus der Quelle gesetzt
    robots_policy = ""
    min_interval_s = 1.0

    def __init__(self, quelle: str, regel_yaml: str | None = None,
                 regeln: dict | None = None, *, base_url: str | None = None):
        self.name = quelle
        self._regeln = regeln or _lade_regeln(regel_yaml, quelle)
        listing = self._regeln.get("listing") or {}
        self._listing_url = listing.get("url") or base_url or ""
        self._item_css = listing.get("item_css", "")
        self._felder: dict = listing.get("felder") or {}
        self._pag = listing.get("pagination") or {}
        self._detail_cfg = self._regeln.get("detail") or {}
        q = self._regeln.get("quelle") or quelle
        robots = (self._regeln.get("robots") or "")[:200]
        self.robots_policy = robots or "siehe docs/quellen.md"
        self._warnungen: list[str] = []
        self._client = httpx.Client(
            headers={"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9"},
            follow_redirects=True, timeout=30,
        )

    # --- Warnungen (von der Pipeline in die Fehler-Queue) -------------------
    def drain_warnungen(self) -> list[str]:
        out, self._warnungen = self._warnungen, []
        return out

    # --- Fetch --------------------------------------------------------------
    def fetch_listing_page(self, page: int = 0) -> str:
        params = None
        if page and self._pag.get("param"):
            params = {self._pag["param"]: str(page)}
        r = self._client.get(self._listing_url, params=params)
        r.raise_for_status()
        return r.text

    def fetch_detail(self, slug: str) -> str:
        if not slug.startswith("http"):
            return ""  # Listing ohne Detail-URL (z. B. Museumsportal) → kein Fetch
        r = self._client.get(slug)
        r.raise_for_status()
        return r.text

    def close(self):
        self._client.close()

    # --- Listing-Parsing ----------------------------------------------------
    @staticmethod
    def _url_to_slug(url: str) -> str:
        u = url.rstrip("/")
        letzter = u.rsplit("/", 1)[-1]
        if letzter and len(letzter) > 3 and "." not in letzter:
            return letzter[:120]
        return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]

    def parse_listing(self, html: str) -> list[dict]:
        """→ [{slug, titel, start, ende, ganztags, ort, url}] (datetime tz-aware)."""
        sel = parsel.Selector(text=html)
        items = sel.css(self._item_css)
        if not items:
            self._warnungen.append(f"item_css '{self._item_css}' liefert 0 Elemente "
                                   "(Struktur geändert?)")
        out = []
        for i, item in enumerate(items):
            try:
                row = self._item_zu_row(item)
            except ValueError as e:
                self._warnungen.append(f"Item {i}: {e}")
                continue
            if row:
                out.append(row)
        return out

    def _item_zu_row(self, item: parsel.Selector) -> dict:
        f = {}
        for feldname, regel in self._felder.items():
            if feldname in ("titel", "start", "ende", "zeit", "ort", "url",
                            "beschreibung_kurz", "adresse"):
                f[feldname] = _feld_wert(item, regel)
        titel = f.get("titel")
        if not titel:
            raise ValueError("titel fehlt")
        url = f.get("url")
        if url and not url.startswith("http"):
            url = urljoin(self._listing_url, url)

        sregel = self._felder["start"]
        start_text = _regex_ziehen(f.get("start"), sregel.get("regex"))
        start = _parse_zeit(start_text, sregel.get("format"), "start")

        # Zeit-/Ende-Extraktion (Konvention):
        #   'zeit' = Start-Uhrzeit (ersetzt Uhrzeit von start), 'ende' = Ende
        #   (Zeit oder Datum+Zeit; reine Zeit = gleicher Tag wie start).
        ende = None
        start_hat_zeit = "%H" in (sregel.get("format") or "")
        zeit_text = None
        ende_regel = self._felder.get("ende")
        zeit_regel = self._felder.get("zeit")
        if ende_regel:
            eregel = ende_regel
            et = _regex_ziehen(f.get("ende"), eregel.get("regex"))
        elif zeit_regel:
            eregel = zeit_regel
            et = _regex_ziehen(f.get("zeit"), zeit_regel.get("regex"))
        else:
            eregel = None
            et = None
        if et and eregel:
            try:
                extra = _parse_zeit(et, eregel.get("format"), "ende/zeit")
            except ValueError:
                extra = None
            if extra is not None:
                nur_zeit = "%H" in (eregel.get("format") or "") \
                    and "%d" not in (eregel.get("format") or "")
                if nur_zeit:
                    extra = extra.replace(year=start.year, month=start.month, day=start.day)
                if eregel is ende_regel and ende_regel is not None:
                    ende = extra
                    zeit_text = f"{extra.hour:02d}:{extra.minute:02d}"
                else:
                    zeit_text = f"{extra.hour:02d}:{extra.minute:02d}"
        if zeit_text and not start_hat_zeit:
            h, m = zeit_text.split(":")
            start = start.replace(hour=int(h), minute=int(m), second=0)
            start_hat_zeit = True

        ganztags = False
        if not start_hat_zeit:
            # Nur ein Datum ohne Uhrzeit → ganztägig (00:00–23:59, wie jup-Konvention)
            start = start.replace(hour=0, minute=0, second=0)
            ende = start.replace(hour=23, minute=59)
            ganztags = True

        ort = f.get("ort")
        return {
            "slug": self._url_to_slug(url) if url else hashlib.sha1(
                f"{titel}|{start.isoformat()}".encode()).hexdigest()[:16],
            "url": url,
            "titel": titel,
            "start": start,
            "ende": ende,
            "ganztags": ganztags,
            "ort": ort or None,
            "beschreibung_kurz": f.get("beschreibung_kurz"),
            "adresse": f.get("adresse"),
        }

    # --- Detail-Parsing (JSON-LD via extruct) -------------------------------
    def parse_detail(self, html: str) -> dict:
        if not html.strip():
            return {}  # kein Detail vorhanden (Listing ohne URL)
        if not self._detail_cfg.get("jsonld"):
            return {}
        try:
            from extruct.jsonld import JsonLdExtractor
        except ImportError:  # pragma: no cover
            self._warnungen.append("extruct nicht installiert — Detail-JSON-LD übersprungen")
            return {}
        out: dict[str, Any] = {}
        try:
            daten = JsonLdExtractor().extract(html)
        except Exception as e:  # pragma: no cover
            self._warnungen.append(f"JSON-LD-Extraktion fehlgeschlagen: {e}")
            return {}
        event = None
        for d in daten:
            if isinstance(d, dict) and d.get("@type") == "Event":
                event = d
                break
            if isinstance(d, dict):
                for g in d.get("@graph", []) if isinstance(d.get("@graph"), list) else []:
                    if isinstance(g, dict) and g.get("@type") == "Event":
                        event = g
                        break
            if event:
                break
        if event is None:
            self._warnungen.append("kein JSON-LD @type:Event auf der Detailseite")
            return out
        from jsonpath_ng.ext import parse as jp_parse
        for feldname, regel in (self._detail_cfg.get("felder") or {}).items():
            pfad = regel.get("jsonld")
            if not pfad:
                continue
            try:
                treffer = [m.value for m in jp_parse(pfad).find(event)]
            except Exception:
                treffer = []
            if treffer:
                v = treffer[0]
                if isinstance(v, dict):
                    v = v.get("name") or v.get("streetAddress") or ""
                out[feldname] = v if isinstance(v, str) else str(v)
        return out

    # --- Event-Bau ----------------------------------------------------------
    def zu_event(self, row: dict, detail: dict | None, jetzt: datetime) -> dict:
        detail = detail or {}
        start_local = row["start"].astimezone(TZ_BERLIN)
        occ = start_local.strftime("%Y%m%dT%H%M")
        source_event_id = f"{row['slug']}#{occ}"
        url = row.get("url") or ""
        ort = row.get("ort") or detail.get("ort") or (detail.get("adresse") and "Berlin") or None
        return {
            "id": make_event_id(self.name, source_event_id),
            "titel": row["titel"],
            "beschreibung_kurz": row.get("beschreibung_kurz") or detail.get("beschreibung_kurz"),
            "start_iso": row["start"].astimezone(TZ_BERLIN).isoformat(),
            "ende_iso": (row["ende"].astimezone(TZ_BERLIN).isoformat()
                         if row.get("ende") else None),
            "start_local": start_local.strftime("%Y-%m-%dT%H:%M:%S"),
            "ende_local": (row["ende"].astimezone(TZ_BERLIN).strftime("%Y-%m-%dT%H:%M:%S")
                           if row.get("ende") else None),
            "ganztags": row.get("ganztags", False),
            "ort": ort,
            "adresse": row.get("adresse") or detail.get("adresse"),
            "bezirk": None,
            "lat": None,
            "lon": None,
            "kostenlos": None,
            "quelle": self.name,
            "source_event_id": source_event_id,
            "source_url": url or self._listing_url,
            "geholt_am": jetzt.isoformat(),
        }
