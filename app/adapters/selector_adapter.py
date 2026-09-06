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
from datetime import datetime, timedelta, time as dtime
from typing import Any
from urllib.parse import urljoin

import httpx
import parsel

from ..model import BEZIRK_LABELS, TZ_BERLIN, make_event_id
from ..regeln import validate_regeln_yaml

UA = "kids-events-berlin/0.2 (+https://github.com/tilllt/kids-events-berlin)"

# Quell-Bezirksnamen (BEZIRK_LABELS-Werte) → kanonische Slugs. Wird genutzt,
# wenn eine Quelle den Bezirk direkt im Listing nennt (z. B. familienportal).
_LABEL_ZU_SLUG = {v.lower(): k for k, v in BEZIRK_LABELS.items()}

# Deutsche Monatsnamen für Datumstexte wie „6. September 2026“ (Detail-Termine).
_DE_MONATE = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5,
    "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}
_RE_DE_DATUM = re.compile(r"(\d{1,2})\.\s*([A-Za-zäöüß]+)\s*(\d{4})")


def _parse_de_datum(text: str) -> datetime | None:
    """„6. September 2026“ → datetime (Europe/Berlin, 00:00)."""
    m = _RE_DE_DATUM.search(text or "")
    if not m:
        return None
    mon = _DE_MONATE.get(m.group(2).lower())
    if not mon:
        return None
    try:
        return datetime(int(m.group(3)), mon, int(m.group(1)), tzinfo=TZ_BERLIN)
    except ValueError:
        return None


def _lade_regeln(regel_yaml: str | None, quelle: str) -> dict:
    fehler = validate_regeln_yaml(regel_yaml or "", quelle)
    if fehler:
        raise ValueError(f"Regeln für {quelle} ungültig: {'; '.join(fehler[:3])} …")
    import yaml
    return yaml.safe_load(regel_yaml or "")


def _feld_wert(el: parsel.Selector, regel: dict) -> str | None:
    """Extrahiert Text/Attribut aus einem Item-Element (parsel).

    Optionen: 'css' (+ 'attr'), oder 'xpath' (relativ zum Item, z. B.
    'ancestor::hylo-router-link[1]/@href' für Links, die das Item umschließen).
    """
    xp = regel.get("xpath")
    if xp:
        gefunden = el.xpath(xp)
        if not gefunden:
            return None
        for g in gefunden:
            v = g.get()
            if v:
                return v.strip()
        return None
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
        self._horizont_tage = int(listing.get("horizont_tage") or 0)
        self.horizont_tage = self._horizont_tage  # für die Pipeline (Fenster-Filter)
        # Detail-URLs mit diesem Substring überspringen (Quelle liefert tote
        # calendarize/cHash-Links, die auf die Startseite umleiten).
        self._detail_url_skip = str(listing.get("detail_url_skip") or "")
        self._detail_cfg = self._regeln.get("detail") or {}
        # Detailseiten nur laden, wenn die Regeln sie auswerten (JSON-LD/CSS).
        self.braucht_detail = bool(self._detail_cfg.get("jsonld")
                                   or self._detail_cfg.get("felder"))
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
    def _listing_url_mit_zeitraum(self, page: int) -> tuple[str, dict | None]:
        """URL mit Zeitraum-/Seiten-Platzhaltern auflösen.

        Platzhalter (nur wenn horizont_tage gesetzt bzw. in der URL):
          {start_ts}/{ende_ts}  Unix-Timestamps heute .. heute+horizont
          {start_de}/{ende_de}  als TT.MM.JJJJ (z. B. kesearch-Datepicker)
          {seite}               currentPage-artige Seitennummer (ab 1)
        Rückgabe: (url, pagination_params_oder_None)
        """
        url = self._listing_url
        if "{" in url:
            jetzt = datetime.now(TZ_BERLIN)
            von = jetzt.replace(hour=0, minute=0, second=0, microsecond=0)
            bis = (von + timedelta(days=self._horizont_tage)
                   ).replace(hour=23, minute=59, second=59)
            url = (url.replace("{start_ts}", str(int(von.timestamp())))
                      .replace("{ende_ts}", str(int(bis.timestamp())))
                      .replace("{start_de}", von.strftime("%d.%m.%Y"))
                      .replace("{ende_de}", bis.strftime("%d.%m.%Y")))
            if "{seite}" in url:
                return url.replace("{seite}", str(page + 1)), None
        if page and self._pag.get("param"):
            offset = int(self._pag.get("offset") or 0)
            return url, {self._pag["param"]: str(page + offset)}
        return url, None

    def fetch_listing_page(self, page: int = 0) -> str:
        url, params = self._listing_url_mit_zeitraum(page)
        r = self._client.get(url, params=params)
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
                            "beschreibung_kurz", "adresse", "bezirk"):
                f[feldname] = _feld_wert(item, regel)
        titel = f.get("titel")
        if not titel:
            raise ValueError("titel fehlt")
        url = f.get("url")
        if url and not url.startswith("http"):
            url = urljoin(self._listing_url, url)
        # Kein URL-Fallback hier: Slug (Hash aus Titel+Start) und source_url
        # (Listing-Seite als Beleg) werden getrennt behandelt — sonst kollabieren
        # alle Events einer linklosen Quelle auf denselben Slug.

        sregel = self._felder["start"]
        start_text = _regex_ziehen(f.get("start"), sregel.get("regex"))
        start = _parse_zeit(start_text, sregel.get("format"), "start")

        # Zeit-/Ende-Extraktion (Konvention):
        #   'zeit' = Start-Uhrzeit (ersetzt Uhrzeit von start), 'ende' = Ende
        #   (Zeit oder Datum+Zeit; reine Zeit = gleicher Tag wie start).
        # zeit und ende sind unabhängig — beide können existieren (z. B. ZLB).
        ende = None
        start_hat_zeit = "%H" in (sregel.get("format") or "")
        zeit_text = None
        zeit_regel = self._felder.get("zeit")
        ende_regel = self._felder.get("ende")

        def _nur_zeit(regel: dict) -> bool:
            fmt = regel.get("format") or ""
            return "%H" in fmt and "%d" not in fmt

        if zeit_regel:
            zt = _regex_ziehen(f.get("zeit"), zeit_regel.get("regex"))
            if zt:
                try:
                    zdt = _parse_zeit(zt, zeit_regel.get("format"), "zeit")
                    zeit_text = f"{zdt.hour:02d}:{zdt.minute:02d}"
                except ValueError:
                    zeit_text = None
        if ende_regel:
            et = _regex_ziehen(f.get("ende"), ende_regel.get("regex"))
            if et:
                try:
                    ende = _parse_zeit(et, ende_regel.get("format"), "ende")
                except ValueError:
                    ende = None
                if ende is not None and _nur_zeit(ende_regel):
                    ende = ende.replace(year=start.year, month=start.month, day=start.day)
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

        # Bezirk aus der Quelle (Label wie „Mitte“): regex-Nachbehandlung
        bezirk_regel = self._felder.get("bezirk")
        if bezirk_regel:
            f["bezirk"] = _regex_ziehen(f.get("bezirk"), bezirk_regel.get("regex"))

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
            "bezirk": f.get("bezirk"),
        }

    # --- Detail-Parsing (JSON-LD via extruct) -------------------------------
    def parse_detail(self, html: str) -> dict:
        if not html.strip():
            return {}  # kein Detail vorhanden (Listing ohne URL)
        out: dict[str, Any] = {}
        # CSS-Felder (Quellen ohne JSON-LD, z. B. familienportal): Selektoren
        # wie „#contact li.name“ (Venue) / „#contact li.address.loc“ (Adresse).
        css_felder = {k: v for k, v in (self._detail_cfg.get("felder") or {}).items()
                      if v.get("css")}
        if css_felder:
            sel_css = parsel.Selector(text=html)
            for feldname, regel in css_felder.items():
                txt = " ".join(sel_css.css(regel["css"]).css("::text").getall())
                txt = re.sub(r"\s+", " ", txt).strip()
                # Textknoten-Kommas („Straße 1 , 12435 Berlin“) normalisieren:
                # Leerzeichen vor Komma entfernen — für WFS-Geokodierung + Anzeige.
                txt = re.sub(r"\s*,\s*", ", ", txt)
                if txt:
                    out[feldname] = txt
        jsonld_felder = {k: v for k, v in (self._detail_cfg.get("felder") or {}).items()
                         if v.get("jsonld")}
        if jsonld_felder and not self._detail_cfg.get("jsonld"):
            return out  # Quelle ohne JSON-LD-Detail → nur CSS-Felder
        try:
            from extruct.jsonld import JsonLdExtractor
        except ImportError:  # pragma: no cover
            self._warnungen.append("extruct nicht installiert — Detail-JSON-LD übersprungen")
            return out
        try:
            daten = JsonLdExtractor().extract(html)
        except Exception as e:  # pragma: no cover
            self._warnungen.append(f"JSON-LD-Extraktion fehlgeschlagen: {e}")
            return out
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
                    if "streetAddress" in v or "postalCode" in v:
                        # Postadresse → „Straße Nr, PLZ Ort“ (für amtliche
                        # Geokodierung brauchen wir die PLZ)
                        teile = [v.get("streetAddress") or "", v.get("postalCode") or "",
                                 v.get("addressLocality") or ""]
                        v = ", ".join(t for t in teile if t)
                    else:
                        v = v.get("name") or v.get("streetAddress") or ""
                out[feldname] = v if isinstance(v, str) else str(v)

        # Serien-Terminliste der Detailseite (z. B. mp „Datum und Uhrzeit“):
        # li-Elemente mit zwei Spans (deutsches Datum + Uhrzeit). Ergänzt das
        # JSON-LD-Einzelevent um alle weiteren Termine → zu_events expandiert.
        tcss = self._detail_cfg.get("termine_css")
        if tcss:
            termine: list[tuple[datetime, datetime | None, bool]] = []
            sel = parsel.Selector(text=html)
            for li in sel.css(tcss):
                spans = li.css("span")
                if len(spans) < 1:
                    continue
                dt = _parse_de_datum(" ".join(spans[0].css("::text").getall()))
                if dt is None:
                    continue
                zeit_txt = ""
                if len(spans) > 1:
                    zeit_txt = " ".join(spans[1].css("::text").getall()).strip()
                mz = re.match(r"(\d{1,2}):(\d{2})", zeit_txt)
                if mz:
                    dt = dt.replace(hour=int(mz.group(1)), minute=int(mz.group(2)))
                    termine.append((dt, None, False))
                else:
                    # Nur Datum → ganztägig (00:00–23:59, wie Listing-Konvention)
                    termine.append((dt.replace(hour=0, minute=0),
                                    dt.replace(hour=23, minute=59), True))
            if termine:
                out["_termine"] = termine
        return out

    # --- Event-Bau ----------------------------------------------------------
    def zu_event(self, row: dict, detail: dict | None, jetzt: datetime) -> dict:
        """Erstes Event (Kompatibilität); Serien → zu_events."""
        return self.zu_events(row, detail, jetzt)[0]

    def _bau_event(self, row: dict, detail: dict, jetzt: datetime,
                   start: datetime, ende: datetime | None = None,
                   ganztags: bool | None = None) -> dict:
        """Ein Event aus row+detail mit konkretem Termin (start/ende/ganztags)."""
        start_local = start.astimezone(TZ_BERLIN)
        occ = start_local.strftime("%Y%m%dT%H%M")
        source_event_id = f"{row['slug']}#{occ}"
        url = row.get("url") or ""
        ort = (row.get("ort") or detail.get("ort")
               or (detail.get("adresse") and "Berlin")
               or "Ohne Angabe")
        # Quelle nennt den Bezirk direkt (Label wie „Pankow“, „Berlinweit“)
        # → kanonischer Slug; schützt die Pipeline vor Geo-Lookup von
        # reinen Bezirksnamen („Bezirk aus der Quelle“-Prinzip).
        bezirk = _LABEL_ZU_SLUG.get((row.get("bezirk") or "").strip().lower())
        if ende is None:
            ende = row.get("ende")
        if ganztags is None:
            ganztags = row.get("ganztags", False)
        return {
            "id": make_event_id(self.name, source_event_id),
            "titel": row["titel"],
            "beschreibung_kurz": row.get("beschreibung_kurz") or detail.get("beschreibung_kurz"),
            "start_iso": start.astimezone(TZ_BERLIN).isoformat(),
            "ende_iso": (ende.astimezone(TZ_BERLIN).isoformat()
                         if ende else None),
            "start_local": start_local.strftime("%Y-%m-%dT%H:%M:%S"),
            "ende_local": (ende.astimezone(TZ_BERLIN).strftime("%Y-%m-%dT%H:%M:%S")
                           if ende else None),
            "ganztags": ganztags,
            "ort": ort,
            "adresse": row.get("adresse") or detail.get("adresse"),
            "bezirk": bezirk,
            "lat": None,
            "lon": None,
            "kostenlos": None,
            "quelle": self.name,
            "source_event_id": source_event_id,
            "source_url": url or self._listing_url,
            "geholt_am": jetzt.isoformat(),
        }

    def zu_events(self, row: dict, detail: dict | None, jetzt: datetime) -> list[dict]:
        """→ Events für einen Listing-Treffer.

        Ohne Serien-Terminliste im Detail: ein Event (bisheriges Verhalten).
        Mit Terminliste (detail['_termine']): ein Event pro Termin; enthält
        die Liste den Listing-Start, ist sie autoritativ, sonst kommt das
        Row-Event zusätzlich (Sicherheitsnetz bei abweichenden Daten).
        """
        detail = detail or {}
        termine = detail.get("_termine") or []
        if not termine:
            return [self._bau_event(row, detail, jetzt, row["start"])]
        row_start = row["start"].astimezone(TZ_BERLIN).replace(second=0, microsecond=0)
        in_liste = any(t[0] == row_start for t in termine)
        evs = [self._bau_event(row, detail, jetzt, t[0], t[1], t[2]) for t in termine]
        if not in_liste:
            evs.insert(0, self._bau_event(row, detail, jetzt, row["start"]))
        return evs
