"""Ausführbare Scrape-Pipeline: Listing-Seiten → Detail-Anreicherung →
Validierung → Store. Metriken + Fehler-Queue je Lauf.

LLM-frei: Enrichment ausschließlich Regelwerk (app/enrich.py) + gecachte
Nominatim-Reverse-Geokodierung (app/geo.py, deterministisch, kein LLM).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .adapters import aktive_quellen, build_adapter
from .enrich import classify_alter, classify_kategorien, classify_kostenlos
from .geo import bezirk_from_latlon
from .model import TZ_BERLIN
from .store import Store
from .validate import validate_event


def scrape(store: Store, quelle: str = "jup-berlin", *, online: bool = True,
           geo: bool = True, max_pages: int = 80, max_details: int | None = None,
           sleep_s: float | None = None, detail_html: dict[str, str] | None = None,
           listing_htmls: list[str] | None = None) -> dict:
    """Führt einen Lauf aus. offline: listing_htmls/detail_html statt Netz."""
    adapter = build_adapter(store, quelle)
    try:
        return _scrape_mit_adapter(store, adapter, quelle, online=online, geo=geo,
                                   max_pages=max_pages, max_details=max_details,
                                   sleep_s=sleep_s, detail_html=detail_html,
                                   listing_htmls=listing_htmls)
    finally:
        try:
            adapter.close()
        except Exception:  # pragma: no cover
            pass


def _scrape_mit_adapter(store, adapter, quelle, *, online, geo,
                        max_pages, max_details, sleep_s, detail_html, listing_htmls) -> dict:
    sleep_s = sleep_s if sleep_s is not None else getattr(adapter, "min_interval_s", 1.0)
    jetzt = datetime.now(TZ_BERLIN)
    run_id = store.start_run(quelle)

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
                break
            n_pages += 1
            rows = adapter.parse_listing(html)
            for w in getattr(adapter, "drain_warnungen", lambda: [])():
                store.log_error(quelle, w)
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
            if not rows:
                continue
            slugs = {r["slug"] for r in rows}
            if seen_slugs and slugs.issubset(seen_slugs):
                break
            seen_slugs |= slugs
            rows_all.extend(rows)
        n_pages = len(listing_htmls or [])

    # Detail-Anreicherung je eindeutigem Slug (gecacht pro Lauf)
    details: dict[str, dict] = {}
    slugs = [r["slug"] for r in rows_all]
    unique_slugs = list(dict.fromkeys(slugs))
    if max_details is not None:
        unique_slugs = unique_slugs[:max_details]
    for i, slug in enumerate(unique_slugs):
        if online:
            try:
                html = adapter.fetch_detail(slug)
                details[slug] = adapter.parse_detail(html)
            except Exception as e:
                store.log_error(quelle, f"Detail {slug}: {e}")
                details[slug] = {}
        else:
            details[slug] = adapter.parse_detail(detail_html.get(slug, ""))
        if sleep_s and online:
            import time as _t
            _t.sleep(sleep_s)

    n_neu = n_geaendert = n_fehler = 0
    for row in rows_all:
        slug = row["slug"]
        det = details.get(slug, {})
        ev = adapter.zu_event(row, det, jetzt)
        # Regel-Anreicherung
        text = f"{ev['titel']} {ev.get('beschreibung_kurz') or ''}"
        alter = classify_alter(ev["titel"], ev.get("beschreibung_kurz") or "")
        ev["altersband_min"] = alter["altersband_min"]
        ev["altersband_max"] = alter["altersband_max"]
        ev["alters_familie"] = alter["alters_familie"]
        ev["kategorien"] = classify_kategorien(text)
        ev["kostenlos"] = classify_kostenlos(det.get("kostenlos_flag"), text)
        # Bezirk: Koordinaten (aus Quelle) → Nominatim-Reverse (gecacht)
        if geo and online and ev.get("lat") and ev.get("lon"):
            bz = bezirk_from_latlon(store, ev["lat"], ev["lon"])
            if bz:
                ev["bezirk"] = bz
        fehler = validate_event(ev, jetzt)
        if fehler:
            n_fehler += 1
            store.log_error(quelle, "; ".join(fehler), {k: ev.get(k) for k in
                            ("titel", "start_iso", "source_url")})
            continue
        neu, geaendert = store.upsert_event(ev)
        n_neu += int(neu)
        n_geaendert += int(geaendert)

    # Stale-Bereinigung: Events der Quelle, deren Start > 3 Tage zurückliegt
    cutoff = (datetime.now(TZ_BERLIN) - timedelta(days=3)).astimezone(ZoneInfo("UTC")).isoformat()
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
