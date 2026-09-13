"""FastAPI-App: API + statische UI + Hintergrund-Scheduler.

Umgebung:
  DATA_DIR          Datenverzeichnis (Default: data) — Volume im Container
  SCRAPE_INTERVAL_H Scrape-Intervall (Default: 24)
  SCRAPE_ON_BOOT    "1" = einmal beim Start scrapen, wenn DB leer (Default: 1)
  GEOCODE           "0" schaltet Nominatim-Reverse aus (Default: an)
"""
from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from .admin_api import router as admin_router
from .api import router as api_router
from .model import TZ_BERLIN
from .store import Store

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
DB_PATH = DATA_DIR / "events.db"
STATIC_DIR = Path(__file__).parent / "static"

# Standard: täglich 05:30 Europe/Berlin — morgens stehen die neu gelisteten
# Termine der Quellen bereit. Intervall-Modus nur, wenn bewusst gesetzt
# (DB-Einstellung scrape_interval_h bei leerer scrape_at).
SCRAPE_AT_DEFAULT = "05:30"


def _naechster_zeitpunkt(jetzt_utc: datetime, uhrzeit: str) -> datetime:
    """Nächster Tageszeitpunkt (HH:MM) in Europe/Berlin nach jetzt_utc (UTC)."""
    h, m = (int(x) for x in uhrzeit.split(":"))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Ungültige Uhrzeit: {uhrzeit}")
    local = jetzt_utc.astimezone(TZ_BERLIN)
    termin = local.replace(hour=h, minute=m, second=0, microsecond=0)
    if termin <= local:
        termin += timedelta(days=1)
    return termin.astimezone(timezone.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    store = Store(DB_PATH)
    store.seed_default_sources()
    app.state.store = store
    interval_h = float(os.environ.get("SCRAPE_INTERVAL_H", "24"))
    geocode = os.environ.get("GEOCODE", "1") != "0"
    boot = os.environ.get("SCRAPE_ON_BOOT", "1") == "1"

    stop = threading.Event()

    def _scrape_aktive():
        """Alle aktiven Quellen aus der DB; Fehler je Quelle in die Queue."""
        from .adapters import aktive_quellen
        from .pipeline import scrape
        quellen = aktive_quellen(store)
        for s in quellen:
            try:
                summary = scrape(store, s["quelle"], online=True, geo=geocode)
                print(f"[scheduler] {s['quelle']} ok: {summary}", flush=True)
            except Exception as e:  # pragma: no cover
                print(f"[scheduler] {s['quelle']} fehlgeschlagen: {e}", flush=True)
                store.log_error(s["quelle"], f"Scheduler-Lauf fehlgeschlagen: {e}")

    def _warte_bis_naechster_lauf() -> float:
        """Sekunden bis zum nächsten Scrape: feste Uhrzeit (scrape_at,
        HH:MM Europe/Berlin), sonst Intervall (scrape_interval_h), sonst
        Standard-Uhrzeit SCRAPE_AT_DEFAULT (05:30)."""
        at = ((store.get_setting("scrape_at") or "").strip()
              or os.environ.get("SCRAPE_AT", "").strip())
        if at:
            try:
                n = _naechster_zeitpunkt(datetime.now(timezone.utc), at)
                return max(0.0, (n - datetime.now(timezone.utc)).total_seconds())
            except ValueError:
                print(f"[scheduler] Ungültige scrape_at '{at}' — "
                      "Standard 05:30.", flush=True)
        db_iv = store.get_setting("scrape_interval_h")
        if db_iv or os.environ.get("SCRAPE_INTERVAL_H"):
            h = float(db_iv) if db_iv else float(
                os.environ["SCRAPE_INTERVAL_H"])
            return h * 3600
        n = _naechster_zeitpunkt(datetime.now(timezone.utc), SCRAPE_AT_DEFAULT)
        return max(0.0, (n - datetime.now(timezone.utc)).total_seconds())

    def worker():
        from .pipeline import scrape
        if boot and store.count_events() == 0:
            try:
                print("[scheduler] Erstlauf (DB leer)…", flush=True)
                _scrape_aktive()
                print("[scheduler] Erstlauf fertig.", flush=True)
            except Exception as e:  # pragma: no cover
                print(f"[scheduler] Erstlauf fehlgeschlagen: {e}", flush=True)
        while True:
            if stop.wait(_warte_bis_naechster_lauf()):
                break
            try:
                _scrape_aktive()
                print("[scheduler] Läufe ok.", flush=True)
            except Exception as e:  # pragma: no cover
                print(f"[scheduler] Lauf fehlgeschlagen: {e}", flush=True)

    t = threading.Thread(target=worker, name="scrape-scheduler", daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        store.close()


app = FastAPI(title="kids-events-berlin", lifespan=lifespan)
class NoCacheStaticFiles(StaticFiles):
    """Statische Assets immer per ETag revalidieren — nach einem Deploy darf
    kein alter JS/CSS-Stand im Browser kleben (führte zu „filtert nach heute“,
    weil ein offener Tab den alten Default behielt)."""
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers.setdefault("Cache-Control", "no-cache")
        return resp


app.include_router(api_router)
app.include_router(admin_router)
app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/admin", include_in_schema=False)
def admin():
    """Admin-Sektion: Quellen/Regeln/Einstellungen. Offen — Schutz folgt
    (vor öffentlichem Betrieb absichern, siehe docs/admin.md).

    Die Seite wird beim Ausliefern mit dem Änderungsstand von admin.js/style.css
    versioniert (``?v=<mtime>``) und trägt den Stand sichtbar in der Kopfzeile.
    Grund: ein offener oder zwischengespeicherter Tab zeigte sonst eine alte
    Oberfläche, ohne dass man das erkennen konnte („die GUI ist nicht
    aktualisiert"). ``no-store`` gilt für die Seite selbst, die Assets bleiben
    per ETag revalidierbar.
    """
    html = (STATIC_DIR / "admin.html").read_text(encoding="utf-8")
    stand = max((STATIC_DIR / "admin.js").stat().st_mtime,
                (STATIC_DIR / "style.css").stat().st_mtime,
                (STATIC_DIR / "admin.html").stat().st_mtime)
    marke = datetime.fromtimestamp(stand, TZ_BERLIN).strftime("%d.%m.%Y %H:%M")
    version = str(int(stand))
    html = html.replace('"/static/style.css"', f'"/static/style.css?v={version}"')
    html = html.replace('"/static/admin.js"', f'"/static/admin.js?v={version}"')
    html = html.replace("<!--BAUSTAND-->",
                        f"<span class=\"badge\" title=\"Stand der Oberfläche\">"
                        f"Stand {marke}</span>")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
