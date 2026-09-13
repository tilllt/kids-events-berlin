"""Ausführbare Scrape-Pipeline: Listing-Seiten → Detail-Anreicherung →
Validierung → Store. Metriken + Fehler-Queue je Lauf.

LLM-frei: Enrichment ausschließlich Regelwerk (app/enrich.py) + gecachte
Nominatim-Reverse-Geokodierung (app/geo.py, deterministisch, kein LLM).
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .adapters import aktive_quellen, build_adapter
from .enrich import classify_alter, classify_kategorien, classify_kostenlos
from .geo import adresse_amtlich, bezirk_from_latlon, ort_aufloesen, ort_koordinaten
from .model import BEZIRK_BERLINWEIT, BEZIRK_LABELS, TZ_BERLIN
from .store import Store
from .validate import validate_event

# Ortsnamen, die nur Bezirksnamen sind (z. B. „Pankow“) → keine Geokodierung.
_BEZIRKS_LABEL_KEYS = {v.lower() for v in BEZIRK_LABELS.values()}

# Anzeigetexte sind Text, nie Markup — ein Selektor auf ein leeres Element hat
# früher dessen HTML als Wert geliefert („<div class="location"></div>" als
# Ortsname, Nutzerfund 2026-09-13).
_MARKUP_RX = re.compile(r"<[a-zA-Z/!][^>]*>")


def _markup_bereinigen(ev: dict, store: Store, quelle: str) -> None:
    """Tagger aus Textfeldern entfernen und den Vorfall protokollieren.

    Invariante für ALLE Adapter (Feed wie Regeln): kein Markup in der Datenbank.
    Bereinigt wird sichtbar — ein stiller Fix würde den Regel-Fehler verstecken.
    """
    for feld, wert in list(ev.items()):
        if not isinstance(wert, str) or not _MARKUP_RX.search(wert):
            continue
        sauber = re.sub(r"\s+", " ", _MARKUP_RX.sub(" ", wert)).strip()
        store.log_error(quelle, f"{feld} enthielt Markup, bereinigt: {wert[:70]!r}")
        ev[feld] = sauber


import threading

# Nur EIN Lauf zur Zeit: der Scheduler (main.py) und der Admin-Knopf
# (admin_api.py) können sonst gleichzeitig dieselbe Datenbank beschreiben. Genau
# das endete am 2026-09-13 in einem Segfault im SQLite/lxml-Zugriff (per
# Faulthandler-Protokoll gefunden: zwei Threads in pipeline._scrape_mit_adapter).
LAUF_SPERRE = threading.Lock()


def scrape(store, quelle="jup-berlin", *, online=True, geo=True, max_pages=80,
           max_details=None, sleep_s=None, detail_html=None, listing_htmls=None,
           jetzt=None) -> dict:
    """Serialisierter Einstieg: wartet auf einen laufenden Lauf.

    Wartezeit begrenzt (5 min); läuft dann noch einer, wird dieser Aufruf
    übersprungen statt parallel zu schreiben.
    """
    if not LAUF_SPERRE.acquire(timeout=300):
        return {"quelle": quelle, "uebersprungen": "ein Lauf laeuft bereits"}
    try:
        return _scrape_gesperrt(
            store, quelle, online=online, geo=geo, max_pages=max_pages,
            max_details=max_details, sleep_s=sleep_s, detail_html=detail_html,
            listing_htmls=listing_htmls, jetzt=jetzt)
    finally:
        LAUF_SPERRE.release()


def _scrape_gesperrt(store: Store, quelle: str = "jup-berlin", *, online: bool = True,
           geo: bool = True, max_pages: int = 80, max_details: int | None = None,
           sleep_s: float | None = None, detail_html: dict[str, str] | None = None,
           listing_htmls: list[str] | None = None,
           jetzt: datetime | None = None) -> dict:
    """Führt einen Lauf aus. offline: listing_htmls/detail_html statt Netz.

    jetzt: fester Referenzzeitpunkt (Europe/Berlin) für Fenster-/Horizont- und
    Stale-Berechnung — Tests injizieren ein festes Datum, damit Fixture-Offline-
    Tests nicht zeitabhängig werden (Fixture-Daten altern sonst aus dem Fenster).
    """
    jetzt = jetzt or datetime.now(TZ_BERLIN)
    adapter = build_adapter(store, quelle)
    try:
        return _scrape_mit_adapter(store, adapter, quelle, online=online, geo=geo,
                                   max_pages=max_pages, max_details=max_details,
                                   sleep_s=sleep_s, detail_html=detail_html,
                                   listing_htmls=listing_htmls, jetzt=jetzt)
    finally:
        try:
            adapter.close()
        except Exception:  # pragma: no cover
            pass


def _im_fenster(start, von, bis) -> bool:
    """Start liegt im Scrape-Fenster [von, bis] (tz-aware Vergleiche)."""
    return von <= start <= bis


def _fenster_grenzen(jetzt: datetime, horizont_tage: int) -> tuple[datetime, datetime]:
    """Fenster [heute 00:00, heute+horizont 23:59] Europe/Berlin."""
    von = jetzt.replace(hour=0, minute=0, second=0, microsecond=0)
    bis = (von + timedelta(days=horizont_tage + 1)
           ).replace(hour=23, minute=59, second=59)
    return von, bis


def _scrape_mit_adapter(store, adapter, quelle, *, online, geo,
                        max_pages, max_details, sleep_s, detail_html, listing_htmls,
                        jetzt: datetime) -> dict:
    sleep_s = sleep_s if sleep_s is not None else getattr(adapter, "min_interval_s", 1.0)
    run_id = store.start_run(quelle)

    # Quellen mit Zeitraum-Abfrage (z. B. familienportal, horizont_tage=21):
    # hartes Fenster [heute .. heute+horizont] — Streudaten und alles über den
    # Horizont hinaus wird verworfen; bricht ab, sobald eine Seite nur noch
    # außerhalb liegende Events listet.
    horizont = int(getattr(adapter, "horizont_tage", 0) or 0)
    von, bis = _fenster_grenzen(jetzt, horizont) if horizont else (None, None)

    def _filter_rows(rows: list[dict]) -> list[dict]:
        if not horizont:
            return rows
        return [r for r in rows if _im_fenster(r["start"], von, bis)]

    # Change 017: erste Listing-Seite + Rohtrefferzahl festhalten (Diagnose)
    erstes_html: str | None = None
    erste_roh = 0
    http_fehler = ""

    if online:
        detail_html = {}
        rows_all: list[dict] = []
        seen_slugs: set[str] = set()
        n_pages = 0
        for page in range(max_pages):
            try:
                html = adapter.fetch_listing_page(page)
            except Exception as e:
                store.log_error(quelle, f"Listing-Seite {page} fehlgeschlagen: {e}")
                http_fehler = f"{e}"
                break
            n_pages += 1
            rows = adapter.parse_listing(html)
            if page == 0:
                erstes_html = html
                erste_roh = len(rows)
            for w in getattr(adapter, "drain_warnungen", lambda: [])():
                store.log_error(quelle, w)
            rows = _filter_rows(rows)
            if not rows:
                break
            slugs = {r["slug"] for r in rows}
            if page > 0 and slugs.issubset(seen_slugs):
                break
            seen_slugs |= slugs
            rows_all.extend(rows)
            if sleep_s:
                import time as _t
                _t.sleep(sleep_s)
        # Warnung, wenn die allererste Seite leer war (Site-Umbau/Antibot?)
        if not rows_all:
            store.finish_run(run_id, n_events=0, n_neu=0, n_geaendert=0, n_fehler=0,
                             n_quellseiten=n_pages, status="anomalie-0-events")
            return {"run_id": run_id, "alerts": ["QUELLE_LEER: 0 Events auf Listing-Seiten"]}
    else:
        rows_all = []
        seen_slugs = set()
        for html in listing_htmls or []:
            rows = adapter.parse_listing(html)
            for w in getattr(adapter, "drain_warnungen", lambda: [])():
                store.log_error(quelle, w)
            rows = _filter_rows(rows)
            if not rows:
                continue
            slugs = {r["slug"] for r in rows}
            if seen_slugs and slugs.issubset(seen_slugs):
                break
            seen_slugs |= slugs
            rows_all.extend(rows)
        n_pages = len(listing_htmls or [])
        # Change 017: auch im Test-/CLI-Pfad die erste Seite für die Diagnose halten
        if listing_htmls:
            erstes_html = listing_htmls[0]
            try:
                erste_roh = len(adapter.parse_listing(listing_htmls[0]))
            except Exception:
                erste_roh = 0

    # Detail-Anreicherung je eindeutigem Slug (gecacht pro Lauf)
    details: dict[str, dict] = {}
    slugs = [r["slug"] for r in rows_all]
    unique_slugs = list(dict.fromkeys(slugs))
    # Detail-Fetch braucht die volle URL — der Slug ist nur der Pfadteil
    # („staudenmarkt-2026“), fetch_detail verwirft Nicht-http-Werte.
    slug_url = {r["slug"]: (r.get("url") or "") for r in rows_all}
    if max_details is not None:
        unique_slugs = unique_slugs[:max_details]
    for i, slug in enumerate(unique_slugs):
        if online and getattr(adapter, "braucht_detail", True):
            url = slug_url.get(slug) or slug
            if not (url or "").startswith("http"):
                details[slug] = {}
                continue
            # Tote Detail-Links überspringen (Quelle leitet auf die Startseite
            # um → kein Ort, und der Startseiten-Text würde die Beschreibung
            # verfälschen).
            skip_m = getattr(adapter, "_detail_url_skip", "") or ""
            if skip_m and skip_m in url:
                store.log_error(quelle, f"Detail übersprungen (defekter {skip_m}-Link): {slug}")
                details[slug] = {}
                continue
            # Detail-HTML-Cache: Termin-Detailseiten sind über das 21-Tage-
            # Fenster stabil — der Tageslauf fetcht nur noch neue Termine
            # (statt täglich ~780 Seiten: Laufzeit + Quellen-Last).
            html = store.detail_cache_get(quelle, url)
            if html is None:
                try:
                    html = adapter.fetch_detail(url)
                    store.detail_cache_put(quelle, url, html)
                except Exception as e:
                    store.log_error(quelle, f"Detail {slug}: {e}")
                    details[slug] = {}
                    if sleep_s:
                        import time as _t
                        _t.sleep(sleep_s)
                    continue
                if sleep_s:
                    import time as _t
                    _t.sleep(sleep_s)
            details[slug] = adapter.parse_detail(html)
        else:
            details[slug] = adapter.parse_detail(
                (detail_html or {}).get(slug, "") if not online
                else "")

    n_neu = n_geaendert = n_fehler = 0
    # Change 016: Kennungen aller Termine, die die Quelle in diesem Lauf noch
    # angeboten hat → Grundlage für das Entfernen verschwundener Angebote.
    gesehen: list[tuple[str, str]] = []
    # Ein HTTP-Client für alle Geokodierungs-Anfragen des Laufs (1 req/s).
    geo_client = None
    if geo and online:
        import httpx
        from .adapters.selector_adapter import UA as _UA
        geo_client = httpx.Client(headers={"User-Agent": _UA,
                                           "Accept-Language": "de-DE,de;q=0.9"},
                                  follow_redirects=True, timeout=30)
    try:
      for row in rows_all:
        slug = row["slug"]
        det = details.get(slug, {})
        # Serien: Detailseite mit mehreren Terminen → ein Event pro Termin.
        # Das 3-Wochen-Fenster gilt auch für expandierte Termine (kein
        # Scrapen über den Horizont hinaus). Interne Adapter (jup) liefern
        # nur zu_event → ein Event wie bisher.
        zu_events = getattr(adapter, "zu_events", None)
        evs_ = (zu_events(row, det, jetzt) if zu_events
                else [adapter.zu_event(row, det, jetzt)])
        for ev in evs_:
          # Invariante: kein Markup in Anzeigetexten (bereinigt + protokolliert).
          _markup_bereinigen(ev, store, quelle)
          if horizont:
            ev_start = datetime.fromisoformat(ev["start_iso"])
            if not _im_fenster(ev_start, von, bis):
              continue
          # Regel-Anreicherung
          text = f"{ev['titel']} {ev.get('beschreibung_kurz') or ''}"
          alter = classify_alter(ev["titel"], ev.get("beschreibung_kurz") or "")
          ev["altersband_min"] = alter["altersband_min"]
          ev["altersband_max"] = alter["altersband_max"]
          ev["alters_familie"] = alter["alters_familie"]
          ev["kategorien"] = classify_kategorien(text)
          ev["kostenlos"] = classify_kostenlos(det.get("kostenlos_flag"), text)
          # Berlinweit-Veranstaltungen (jup: „Berlinweit“ mit Platzhalter-
          # Koordinaten) bekommen den Sonder-Bezirk und KEINE Geokodierung.
          ort_roh = ev.get("ort") or ""
          if ort_roh.strip().lower() in ("berlinweit", "ganz berlin"):
              ev["bezirk"] = BEZIRK_BERLINWEIT
          # Orts-Alias auflösen („AGB | Wiese“ → Amerika-Gedenkbibliothek (Wiese)
          # + Adresse für die Geokodierung) — deterministisches Lexikon.
          ort_klar, ort_adresse = ort_aufloesen(ev.get("ort"))
          ev["ort"] = ort_klar
          if ort_adresse and not (ev.get("adresse") or "").strip():
              ev["adresse"] = ort_adresse
          # Bezirk: Koordinaten (aus Quelle) → Nominatim-Reverse (gecacht)
          if (geo_client and ev.get("lat") is not None and ev.get("lon") is not None
                  and not ev.get("bezirk")):
              bz = bezirk_from_latlon(store, ev["lat"], ev["lon"], geo_client)
              if bz:
                  ev["bezirk"] = bz
          # Ort ohne Koordinaten → erst amtliche Adress-Geokodierung (Straße +
          # Hausnummer + PLZ, WFS Adressen Berlin), dann Venue-Name über
          # Nominatim („Neue Nationalgalerie“). Läuft AUCH mit Bezirk aus der
          # Quelle — der Bezirk allein gibt keine Kartenposition. Nur Orte
          # ohne echten Venue (Bezirksname, „Ohne Angabe“, „Berlin“) werden
          # nicht geokodiert (Koordinaten wären wertlos).
          if geo_client and (ev.get("lat") is None or ev.get("lon") is None):
            ort_klar_ = (ev.get("ort") or "").strip()
            ort_low = ort_klar_.lower()
            ist_bezirksname = ort_low in _BEZIRKS_LABEL_KEYS
            treffer = None
            # Amtliche Adress-Geokodierung ZUERST und UNABHÄNGIG vom Ort:
            # eine echte Adresse (Straße+Hausnr+PLZ) ist die stärkere Aussage
            # als der Ortsname — Quellen ohne Veranstaltungsort im Text
            # (Kinderkulturkalender: ~40 % der Angebote) tragen den Ort nur
            # als „Ohne Angabe“/„Berlin“ und bekämen sonst NIE eine Position
            # (realer Befund 2026-09-12: 125 von 211 ohne Koordinaten, obwohl
            # die Adresse vorlag). Der Ortsname-Weg (Nominatim) bleibt auf
            # echte Venue-Namen beschränkt — Bezirksnamen, „Berlin“,
            # „Berlinweit“ und „Ohne Angabe“ ergeben dort keine Position.
            if (ev.get("adresse") or "").strip():
              treffer = adresse_amtlich(store, ev["adresse"], geo_client)
            if (not treffer and ort_klar_
                    and ort_low not in ("ohne angabe", "berlinweit",
                                        "ganz berlin", "berlin")
                    and not ist_bezirksname):
              treffer = ort_koordinaten(store, ev["ort"], geo_client)
            if treffer:
              ev["lat"] = treffer["lat"]
              ev["lon"] = treffer["lon"]
              if not ev.get("bezirk") and treffer.get("bezirk"):
                ev["bezirk"] = treffer["bezirk"]
              if not ev.get("adresse") and treffer.get("adresse"):
                ev["adresse"] = treffer["adresse"]
          fehler = validate_event(ev, jetzt)
          if fehler:
              n_fehler += 1
              store.log_error(quelle, "; ".join(fehler), {k: ev.get(k) for k in
                              ("titel", "start_iso", "source_url")})
              continue
          neu, geaendert = store.upsert_event(ev)
          gesehen.append((ev["id"], ev.get("source_event_id") or ""))
          n_neu += int(neu)
          n_geaendert += int(geaendert)
    finally:
        if geo_client is not None:
            geo_client.close()

    # Change 017: Selbstheilung — Befund feststellen, gesunde Seite archivieren.
    # Auslöser ist ein Fehler, nie eine kleinere Zahl. Fehler hier dürfen den
    # Lauf nicht stören (deshalb abgesichert).
    try:
        from . import selbstheilung as _sh
        _sh.pruefen(
            store, quelle=quelle,
            regeln=(store.get_regeln(quelle) or {}).get("regel_yaml") or "",
            url=getattr(adapter, "_listing_url", "") or "",
            html=erstes_html, roh_zeilen=erste_roh, n_zeilen=len(rows_all),
            n_fehler=n_fehler, http_fehler=http_fehler, jetzt=jetzt.isoformat())
    except Exception as e:
        store.log_error(quelle, f"Selbstheilung-Prüfung fehlgeschlagen: {e}")

    # Change 016: erst stempeln, was die Quelle noch anbietet, dann verschwundene
    # Angebote entfernen. Deterministisch (die Quelle ist das Signal) statt
    # fester Frist — der Altbestand behielt sonst Termine tageweise und mit
    # ihrem alten Zustand (Ort „Ohne Angabe", keine Position).
    store.markiere_gesehen(quelle, gesehen, jetzt.isoformat())
    weg = store.entferne_nicht_mehr_angeboten(quelle, jetzt.isoformat(),
                                              ok=(n_fehler == 0))
    if weg:
        print(f"[stale] {quelle}: {weg} nicht mehr angebotene Termine entfernt",
              flush=True)

    # Serien-Zwillinge: Quellen liefern mehrtägige Events teils als mehrere, je
    # um einen Tag verschobene Kopien (jup „Veranstaltungstermin/e“) → je Kette
    # nur der früheste Eintrag bleibt (Change 008). Räumt auch Altlasten mit weg.
    entfernt = store.entferne_ueberlappende_zwillinge(quelle)
    if entfernt:
        print(f"[dedup] {quelle}: {len(entfernt)} überlappende Serien-Zwillinge "
              f"entfernt", flush=True)

    # Quellen-übergreifende Dubletten (Change 011): dieselbe Veranstaltung bei
    # mehreren Quellen (real: ein Tag der offenen Tür 57×) wird zu einem
    # Datensatz mit Provenienz-Zeiger auf die übrigen Quellen.
    dub = store.merge_doppelte_events()
    if dub["entfernt"] or dub["verdacht"]:
        print(f"[dedup] quellenübergreifend: {dub['entfernt']} Dubletten entfernt, "
              f"{dub['verdacht']} Verdachtsfälle (nicht automatisch gemergt)",
              flush=True)

    # Stale-Bereinigung: Events der Quelle, deren Start > 3 Tage zurückliegt
    cutoff = (jetzt - timedelta(days=3)).astimezone(ZoneInfo("UTC")).isoformat()
    store.prune_stale(quelle, cutoff)

    n_events = store.count_events()
    store.finish_run(run_id, n_events=n_events, n_neu=n_neu, n_geaendert=n_geaendert,
                     n_fehler=n_fehler, n_quellseiten=n_pages)
    return {
        "run_id": run_id,
        "quelle": quelle,
        "rows": len(rows_all),
        "slugs": len(unique_slugs),
        "n_neu": n_neu,
        "n_geaendert": n_geaendert,
        "n_fehler": n_fehler,
        "n_zwillinge_entfernt": len(entfernt),
        "n_dubletten_entfernt": dub["entfernt"],
        "n_dubletten_verdacht": dub["verdacht"],
        "seiten": n_pages,
    }


def run_cli(quelle: str, db_path: str, online: bool, geo: bool, max_details: int | None):
    store = Store(db_path)
    try:
        if not online:
            from pathlib import Path
            fx = Path("tests/fixtures/jup-berlin")
            listings = [(fx / "listing_p0.html").read_text(encoding="utf-8"),
                        (fx / "listing_p1.html").read_text(encoding="utf-8")]
            details = {
                "familiensportfest": (fx / "detail_familiensportfest.html").read_text(encoding="utf-8"),
                "raetselabenteuer-berlin-prenzlauer-berg": (fx / "detail_raetsel.html").read_text(encoding="utf-8"),
            }
            summary = scrape(store, quelle, online=False, geo=False,
                             listing_htmls=listings, detail_html=details)
        else:
            summary = scrape(store, quelle, online=True, geo=geo, max_details=max_details)
        print(summary)
        if summary.get("alerts"):
            print("ALERTS:", summary["alerts"], file=sys.stderr)
            return 2
        return 0
    finally:
        store.close()
