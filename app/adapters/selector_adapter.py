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
from urllib.parse import unquote_plus, urljoin

import httpx
import parsel

from ..model import BEZIRK_LABELS, TZ_BERLIN, make_event_id
from ..regeln import validate_regeln_yaml

UA = "kids-events-berlin/0.2 (+https://github.com/tilllt/kids-events-berlin)"

# Quell-Bezirksnamen (BEZIRK_LABELS-Werte) → kanonische Slugs. Wird genutzt,
# wenn eine Quelle den Bezirk direkt im Listing nennt (z. B. familienportal).
# Kanonische Slugs sind ebenfalls gültig: Quellen liefern denselben Bezirk mal
# als Label („Neukölln", „Treptow-Köpenick"), mal ASCII-slugig („neukoelln",
# „treptow-koepenick"). Ohne diese zweite Auflösung fielen genau die Bezirke
# mit Umlaut/ö-Transliteration stumm durch (bezirk=null).
_LABEL_ZU_SLUG = {
    **{k: k for k in BEZIRK_LABELS},
    **{v.lower(): k for k, v in BEZIRK_LABELS.items()},
}

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


# Termin-Textform OHNE Spans (z. B. Kinderkulturkalender):
#   „20.09.26, 11:00 - 20.09.26, 12:30“  (Start + Ende)
#   „11.10.2026, 10:00“                   (nur Start)
#   „20.09.26“                            (ganztägig)
_RE_TERMIN_DATUM = re.compile(r"(\d{1,2})[.](\d{1,2})[.]([0-9]{2,4})")
_RE_TERMIN_ZEIT = re.compile(r"(\d{1,2}):(\d{2})")


def _jahr_aus_kurz(v: str) -> int:
    j = int(v)
    return 2000 + j if j < 100 else j


def _parse_termin_text(text: str) -> tuple[datetime, datetime | None, bool] | None:
    """Termin-Text → (start, ende, ganztags) oder None (kein Datum → verwerfen)."""
    daten = _RE_TERMIN_DATUM.findall(text or "")
    if not daten:
        return None
    tag, monat, jahr = daten[0]
    try:
        start = datetime(_jahr_aus_kurz(jahr), int(monat), int(tag), tzinfo=TZ_BERLIN)
    except ValueError:
        return None
    zeiten = _RE_TERMIN_ZEIT.findall(text or "")
    if not zeiten:
        return (start.replace(hour=0, minute=0),
                start.replace(hour=23, minute=59), True)
    start = start.replace(hour=int(zeiten[0][0]), minute=int(zeiten[0][1]))
    if len(zeiten) < 2:
        return (start, None, False)
    tag_e, monat_e, jahr_e = daten[-1] if len(daten) > 1 else daten[0]
    try:
        ende = datetime(_jahr_aus_kurz(jahr_e), int(monat_e), int(tag_e),
                        int(zeiten[-1][0]), int(zeiten[-1][1]), tzinfo=TZ_BERLIN)
    except ValueError:
        return (start, None, False)
    if ende < start:
        ende = start
    # Explizit „00:00 - 23:59“ ist die Ganztags-Schreibweise der Quellen →
    # ganztags-Flag setzen (Konvention wie im jup-Adapter), sonst zeigt die
    # UI „00:00 – 23:59“ statt „ganztägig“.
    if (start.hour, start.minute, ende.hour, ende.minute) == (0, 0, 23, 59):
        return (start, ende, True)
    return (start, ende, False)


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
    if not text:
        # Kein Textknoten: Bild- oder Meta-Elemente tragen den Wert in einem
        # Attribut — auch als KIND des Treffers (typisch: <div><img alt="…">).
        # NIE das HTML-Markup zurückgeben: ein Selektor auf ein LEERES Element
        # lieferte früher dessen HTML und schrieb „<div class="location"></div>"
        # als Ortsnamen in die Datenbank (Nutzerfund 2026-09-13).
        for g in [*gefunden, *gefunden.css("*")]:
            for attr in ("alt", "title", "content", "value"):
                v = (g.attrib.get(attr) or "").strip()
                if v:
                    return v
        return None
    return text or None


def _regex_ziehen(text: str | None, rx: str | None) -> str | None:
    if not text or not rx:
        return text
    m = re.search(rx, text)
    return m.group(1) if m and m.groups() else (m.group(0) if m else None)


def _detail_feld_wert(sel_css: parsel.Selector, regel: dict) -> str:
    """Detail-Feld aus CSS(+attr/regex/urldecode) → Text ("" = kein Treffer).

    Reihenfolge: Selektor/Attribut → Whitespace/Komma normalisieren →
    urldecode (Prozent-/Plus-Kodierung, z. B. Adresse im Kalender-Link) →
    regex (ohne Treffer bleibt das Feld LEER, kein Rohtext in der DB).
    """
    if regel.get("attr"):
        txt = ""
        for el in sel_css.css(regel["css"]):
            v = el.attrib.get(regel["attr"])
            if v:
                txt = v
                break
    else:
        txt = " ".join(sel_css.css(regel["css"]).css("::text").getall())
    txt = re.sub(r"\s+", " ", txt).strip()
    # Textknoten-Kommas („Straße 1 , 12435 Berlin“) normalisieren.
    txt = re.sub(r"\s*,\s*", ", ", txt)
    if regel.get("urldecode") and txt:
        txt = unquote_plus(txt)
    if regel.get("regex"):
        txt = _regex_ziehen(txt, regel["regex"]) or ""
    return txt.strip()


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
        # Quellenweite Vorgaben: manche Kalender haben einen festen Ort
        # („Gärten der Welt IST der Ort"), sie brauchen also kein Ortsfeld.
        # Gilt nur, wenn die Quelle selbst nichts liefert — Quelle hat Vorrang.
        self._standard = {k: v.strip() for k, v in (self._regeln.get("standard") or {}).items()
                          if isinstance(v, str) and v.strip()}
        # Detailseiten nur laden, wenn die Regeln sie auswerten (JSON-LD/CSS/
        # Serien-Termine).
        self.braucht_detail = bool(self._detail_cfg.get("jsonld")
                                   or self._detail_cfg.get("felder")
                                   or self._detail_cfg.get("termine_css"))
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
                wert = _feld_wert(item, regel)
                # 'regex' gilt für JEDES Feld, nicht nur für die Termin-Felder.
                # Nötig z. B. beim Familienportal: dort trägt eine Karte sowohl
                # tote calendarize/cHash-Links (leiten auf die Liste um) als auch
                # sprechende /termin/<slug>-Links. Über ein Muster lässt sich der
                # brauchbare Link behalten und der tote verwerfen — sonst zeigt
                # die App einen Link, der ins Leere führt.
                # start/ende/zeit/bezirk behalten ihre eigene Auswertung darunter.
                if regel.get("regex") and feldname not in ("start", "ende", "zeit", "bezirk"):
                    wert = _regex_ziehen(wert, regel.get("regex"))
                f[feldname] = wert
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
        # Feld-Regeln dürfen eine Liste von Alternativen sein (erste mit
        # Treffer gewinnt): z. B. Adresse zuerst aus dem verknüpften Orts-
        # Knoten, sonst aus dem AddToCalendar-Link (Kinderkulturkalender hat
        # bei ~40 % der Angebote keinen Orts-Knoten, aber immer den Link).
        def _als_liste(v: Any) -> list[dict]:
            return [r for r in (v if isinstance(v, list) else [v])
                    if isinstance(r, dict)]

        detail_felder = self._detail_cfg.get("felder") or {}
        css_felder = {k: _als_liste(v) for k, v in detail_felder.items()
                      if any(r.get("css") for r in _als_liste(v))}
        if css_felder:
            sel_css = parsel.Selector(text=html)
            for feldname, regeln_liste in css_felder.items():
                for regel in regeln_liste:
                    if not regel.get("css"):
                        continue
                    txt = _detail_feld_wert(sel_css, regel)
                    if txt:
                        out[feldname] = txt
                        break

        # Serien-Terminliste der Detailseite: entweder li mit zwei Spans
        # (deutsches Datum + Uhrzeit, Museumsportal) oder Termin-Text ohne
        # Spans („20.09.26, 11:00 - 20.09.26, 12:30“, Kinderkulturkalender).
        # Läuft VOR dem JSON-LD-Block: die Terminliste ist unabhängig davon
        # und darf nicht an einem fehlenden @type:Event scheitern.
        tcss = self._detail_cfg.get("termine_css")
        if tcss:
            termine: list[tuple[datetime, datetime | None, bool]] = []
            sel = parsel.Selector(text=html)
            for li in sel.css(tcss):
                # Form A: li mit Spans (deutsches Datum + Uhrzeit).
                spans = li.css("span")
                dt = None
                if spans:
                    dt = _parse_de_datum(" ".join(spans[0].css("::text").getall()))
                if dt is not None:
                    zeit_txt = (" ".join(spans[1].css("::text").getall()).strip()
                                if len(spans) > 1 else "")
                    mz = re.match(r"(\d{1,2}):(\d{2})", zeit_txt)
                    if mz:
                        termine.append((dt.replace(hour=int(mz.group(1)),
                                                   minute=int(mz.group(2))), None, False))
                    else:
                        # Nur Datum → ganztägig (00:00–23:59, wie Listing-Konvention)
                        termine.append((dt.replace(hour=0, minute=0),
                                        dt.replace(hour=23, minute=59), True))
                    continue
                # Form B: Termin als Text — Datumslose Elemente (Buttons,
                # Kalender-Links) werden verworfen.
                geparst = _parse_termin_text(" ".join(li.css("::text").getall()))
                if geparst is None:
                    continue
                termine.append(geparst)
            if termine:
                out["_termine"] = termine

        jsonld_felder = {k: v for k, v in detail_felder.items()
                         if any(r.get("jsonld") for r in _als_liste(v))}
        if jsonld_felder and not self._detail_cfg.get("jsonld"):
            return out  # Quelle ohne JSON-LD-Detail → nur CSS-Felder
        if not self._detail_cfg.get("jsonld"):
            # Quelle ohne JSON-LD-Detail: Extraktion überspringen, sonst steht
            # pro Detailseite eine „kein JSON-LD @type:Event“-Warnung im Log,
            # die die Pipeline im Detail-Pfad nicht drainiert (stilles Rauschen).
            return out
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
        for feldname, regel_wert in detail_felder.items():
            pfad = next((r.get("jsonld") for r in _als_liste(regel_wert)
                         if r.get("jsonld")), None)
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
        # Ortsangabe: Quelle zuerst, dann die feste Vorgabe des Kalenders.
        # Nennt die Quelle keinen Ortsnamen, aber eine Adresse (BWB-Wasser-Mobil:
        # „Charlottenburger Chaussee 67, 13597 Berlin"), darf nicht „Ohne Angabe"
        # dastehen — dann gilt die grobe Ortsangabe „Berlin"; die genaue Adresse
        # steht weiterhin in der Adresszeile (und dient der Geokodierung).
        adresse = (row.get("adresse") or detail.get("adresse")
                   or self._standard.get("adresse"))

        def _ohne_bezirksname(wert: str | None) -> str | None:
            """Bezirks-/Stadtname ist kein Veranstaltungsort (Nutzerfund 2026-09-13).

            Gilt für JEDE Quelle der Ortsangabe — auch für das Detail-Feld:
            In der Quelle Umweltkalender steht bei manchen Angeboten nur
            „Friedrichshain-Kreuzberg, 10965 Berlin“ (keine Straße, kein Name).
            Ohne diese Prüfung landete der Bezirk im Ortsfilter (185 von 1350
            Terminen gemessen am 2026-09-14) und die Geokodierung suchte einen
            Ort, den es nicht gibt.
            """
            if wert and _LABEL_ZU_SLUG.get(str(wert).strip().lower()) not in (None, "unbekannt"):
                return None
            return wert

        ort = (_ohne_bezirksname(row.get("ort")) or _ohne_bezirksname(detail.get("ort"))
               or self._standard.get("ort")
               or (adresse and "Berlin")
               or "Ohne Angabe")
        # Termine geben den Ortsteil/Bezirk direkt an („Pankow“, „Berlinweit“)
        # → kanonischer Slug; schützt die Pipeline vor Geo-Lookup von
        # reinen Bezirksnamen („Bezirk aus der Quelle“-Prinzip). Feste
        # Kalender-Orte (standard) gelten nur, wenn die Quelle nichts liefert.
        bezirk = (_LABEL_ZU_SLUG.get((row.get("bezirk") or "").strip().lower())
                  or _LABEL_ZU_SLUG.get((self._standard.get("bezirk") or "").strip().lower()))
        # Steht in einem Ortsfeld nur ein Bezirks- oder Stadtname („Mitte":
        # 77 Termine, Nutzerfund 2026-09-13), ist das kein Veranstaltungsort:
        # der Wert wandert in den Bezirk — aus JEDEM Ortsfeld, auch dem der
        # Detailseite (dort steht bei manchen Angeboten der Umweltkalender-Quelle
        # nur „<Bezirk>, <PLZ> Berlin"; gemessen 2026-09-14: 185 von 1350
        # Terminen standen so mit einem Bezirk im Ortsfeld). Der Ort selbst wird
        # danach aus Detail / fester Vorgabe / Adresse bestimmt.
        for kandidat in (row.get("ort"), detail.get("ort")):
            slug = _LABEL_ZU_SLUG.get((kandidat or "").strip().lower())
            if slug and slug != "unbekannt":
                bezirk = bezirk or slug
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
            "adresse": adresse,
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

        detail.termine_autoritativ: true schaltet das Sicherheitsnetz ab —
        nötig, wenn das Listing nur ein Datum OHNE Uhrzeit trägt (Kinder-
        kulturkalender): das Row-Event wäre sonst ein zusätzlicher
        ganztägiger Phantom-Termin neben den echten Terminen.
        """
        detail = detail or {}
        termine = detail.get("_termine") or []
        if not termine:
            return [self._bau_event(row, detail, jetzt, row["start"])]
        evs = [self._bau_event(row, detail, jetzt, t[0], t[1], t[2]) for t in termine]
        if self._detail_cfg.get("termine_autoritativ"):
            return evs
        row_start = row["start"].astimezone(TZ_BERLIN).replace(second=0, microsecond=0)
        in_liste = any(t[0] == row_start for t in termine)
        if not in_liste:
            evs.insert(0, self._bau_event(row, detail, jetzt, row["start"]))
        return evs
