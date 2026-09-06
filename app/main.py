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
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .admin_api import router as admin_router
from .api import router as api_router
from .store import Store

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
DB_PATH = DATA_DIR / "events.db"
STATIC_DIR = Path(__file__).parent / "static"


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

    def worker():
        from .pipeline import scrape
        if boot and store.count_events() == 0:
            try:
                print("[scheduler] Erstlauf (DB leer)…", flush=True)
                scrape(store, "jup-berlin", online=True, geo=geocode)
                print("[scheduler] Erstlauf fertig.", flush=True)
            except Exception as e:  # pragma: no cover
                print(f"[scheduler] Erstlauf fehlgeschlagen: {e}", flush=True)
        while not stop.wait(interval_h * 3600):
            try:
                summary = scrape(store, "jup-berlin", online=True, geo=geocode)
                print(f"[scheduler] Lauf ok: {summary}", flush=True)
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
app.include_router(api_router)
app.include_router(admin_router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/admin", include_in_schema=False)
def admin():
    """Admin-Sektion: Quellen/Regeln/Einstellungen. Offen — Schutz folgt
    (vor öffentlichem Betrieb absichern, siehe docs/admin.md)."""
    return FileResponse(str(STATIC_DIR / "admin.html"))
