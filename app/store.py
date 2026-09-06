"""SQLite-Store (WAL): events, runs, errors, venues_cache, meta.

Single-Writer (Scheduler-Prozess); API liest. Kein ORM — bewusst schlank.

Zeit-Konvention: start_iso/ende_iso = UTC-ISO (kanonisch, für Vergleiche);
start_local/ende_local = naive Ortszeit Europe/Berlin (für Datums-/Uhrzeit-Filter
und Anzeige). Filter auf Tageszeit/Datum laufen IMMER gegen die *_local-Spalten,
damit die Uhrzeit-Bänder unabhängig von der Container-Zeitzone korrekt sind.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from .model import BEZIRK_BERLINWEIT, BEZIRK_UNBEKANNT, TZ_BERLIN, iso_utc

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    titel TEXT NOT NULL,
    beschreibung_kurz TEXT,
    start_iso TEXT NOT NULL,
    ende_iso TEXT,
    start_local TEXT NOT NULL,
    ende_local TEXT,
    ganztags INTEGER NOT NULL DEFAULT 0,
    ort TEXT,
    adresse TEXT,
    bezirk TEXT,
    lat REAL,
    lon REAL,
    altersband_min INTEGER,
    altersband_max INTEGER,
    alters_familie INTEGER NOT NULL DEFAULT 0,
    kategorien TEXT,
    kostenlos INTEGER,
    quelle TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    geholt_am TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'auto'
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_iso);
CREATE INDEX IF NOT EXISTS idx_events_start_local ON events(start_local);
CREATE INDEX IF NOT EXISTS idx_events_bezirk ON events(bezirk);
CREATE INDEX IF NOT EXISTS idx_events_quelle ON events(quelle);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quelle TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    n_events INTEGER NOT NULL DEFAULT 0,
    n_neu INTEGER NOT NULL DEFAULT 0,
    n_geaendert INTEGER NOT NULL DEFAULT 0,
    n_fehler INTEGER NOT NULL DEFAULT 0,
    n_quellseiten INTEGER NOT NULL DEFAULT 0,
    dauer_s REAL,
    status TEXT NOT NULL DEFAULT 'running'
);
CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quelle TEXT NOT NULL,
    zeitpunkt TEXT NOT NULL,
    grund TEXT NOT NULL,
    roh TEXT
);
CREATE TABLE IF NOT EXISTS venues_cache (
    venue_key TEXT PRIMARY KEY,
    lat REAL, lon REAL, bezirk TEXT, adresse TEXT, geholt_am TEXT
);
CREATE TABLE IF NOT EXISTS ort_geo (
    ort_key TEXT PRIMARY KEY,
    ort TEXT NOT NULL,
    lat REAL, lon REAL, bezirk TEXT, adresse TEXT,
    gefunden INTEGER NOT NULL DEFAULT 1,
    aktualisiert_am TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    quelle TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    typ TEXT NOT NULL DEFAULT 'regeln',
    url TEXT,
    aktiv INTEGER NOT NULL DEFAULT 1,
    rate_limit_s REAL NOT NULL DEFAULT 1.0,
    menge_min INTEGER,
    menge_max INTEGER,
    horizont_tage INTEGER NOT NULL DEFAULT 60,
    robots TEXT,
    notiz TEXT,
    zuletzt_geaendert TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS regeln (
    quelle TEXT PRIMARY KEY REFERENCES sources(quelle) ON DELETE CASCADE,
    regel_yaml TEXT NOT NULL,
    geaendert TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    wert TEXT NOT NULL,
    geaendert TEXT NOT NULL
);
"""

# Uhrzeit-Bänder (Ortszeit), für time()-Vergleich in SQL.
UHRZEIT_SQL = {
    "vormittag": ("00:00", "12:00"),
    "nachmittag": ("12:00", "17:00"),
    "abend": ("17:00", "24:00"),
}


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.Lock()
        self._run_ts: dict[int, float] = {}
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()

    # --- Events -----------------------------------------------------------
    def upsert_event(self, ev: dict) -> tuple[bool, bool]:
        """(neu, geaendert) — idempotent, nur echte Änderungen schreiben."""
        # Kanonische Vergleichs-/Schreibform: kategorien immer als JSON-String.
        ev = dict(ev)
        ev["kategorien"] = json.dumps(ev.get("kategorien") or [], ensure_ascii=False)
        with self._lock:
            cur = self._conn.execute("SELECT * FROM events WHERE id = ?", (ev["id"],))
            old = cur.fetchone()
            if old is None:
                # ID-Schema-Wechsel (z. B. Quelle bekommt später Event-URLs):
                # gleicher Inhalt (Quelle+Titel+Start+Ort) unter anderer ID wäre
                # ein Duplikat → alten Zwilling übernehmen (löschen + neu schreiben).
                zwi = self._conn.execute(
                    """SELECT id FROM events
                       WHERE quelle=? AND titel=? AND start_iso=?
                         AND COALESCE(ort,'')=COALESCE(?,'') AND id != ?
                       ORDER BY id LIMIT 1""",
                    (ev["quelle"], ev["titel"], ev["start_iso"], ev.get("ort"), ev["id"]),
                ).fetchone()
                if zwi is not None:
                    self._conn.execute("DELETE FROM events WHERE id=?", (zwi["id"],))
                    self._conn.execute(
                        """INSERT INTO events (id, titel, beschreibung_kurz, start_iso, ende_iso,
                           start_local, ende_local, ganztags, ort, adresse, bezirk, lat, lon,
                           altersband_min, altersband_max, alters_familie, kategorien, kostenlos,
                           quelle, source_event_id, source_url, geholt_am, status)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        self._ev_tuple(ev),
                    )
                    self._conn.commit()
                    return False, True
                self._conn.execute(
                    """INSERT INTO events (id, titel, beschreibung_kurz, start_iso, ende_iso,
                       start_local, ende_local, ganztags, ort, adresse, bezirk, lat, lon,
                       altersband_min, altersband_max, alters_familie, kategorien, kostenlos,
                       quelle, source_event_id, source_url, geholt_am, status)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    self._ev_tuple(ev),
                )
                self._conn.commit()
                return True, False
            old_row = dict(old)
            # Altlast-Bereinigung auch im Update-Pfad: Wenn dieselbe Quelle
            # dasselbe Event (Titel+Start+Ort) unter einer ANDEREN id führt
            # (ID-Schema-Wechsel, z. B. Quelle bekam später Event-URLs), ist
            # die andere id eine verwaiste Duplikat-Version → entfernen.
            zwi = self._conn.execute(
                """SELECT id FROM events
                   WHERE quelle=? AND titel=? AND start_iso=?
                     AND COALESCE(ort,'')=COALESCE(?,'') AND id != ? AND id != ?
                   ORDER BY id LIMIT 1""",
                (ev["quelle"], ev["titel"], ev["start_iso"], ev.get("ort"),
                 old_row["id"], ev["id"]),
            ).fetchone()
            if zwi is not None:
                self._conn.execute("DELETE FROM events WHERE id=?", (zwi["id"],))
                self._conn.commit()
            comparable = {
                k: old_row[k] for k in ("titel", "beschreibung_kurz", "start_iso", "ende_iso",
                                        "ganztags", "ort", "adresse", "bezirk", "lat", "lon",
                                        "altersband_min", "altersband_max", "alters_familie",
                                        "kategorien", "kostenlos", "source_url")
            }
            new_comp = {k: ev[k] for k in comparable}
            changed = comparable != new_comp
            if changed:
                sets = ", ".join(f"{k} = ?" for k in new_comp)
                vals = list(new_comp.values()) + [ev["geholt_am"], ev["id"]]
                self._conn.execute(f"UPDATE events SET {sets}, geholt_am = ? WHERE id = ?", vals)
                self._conn.commit()
            return False, changed

    @staticmethod
    def _ev_tuple(ev: dict) -> tuple:
        return (
            ev["id"], ev["titel"], ev.get("beschreibung_kurz"), ev["start_iso"],
            ev.get("ende_iso"), ev["start_local"], ev.get("ende_local"),
            int(ev.get("ganztags", False)), ev.get("ort"), ev.get("adresse"),
            ev.get("bezirk"), ev.get("lat"), ev.get("lon"),
            ev.get("altersband_min"), ev.get("altersband_max"),
            int(ev.get("alters_familie", False)), ev["kategorien"],
            ev.get("kostenlos"), ev["quelle"], ev["source_event_id"],
            ev["source_url"], ev["geholt_am"], ev.get("status", "auto"),
        )

    def query_events(self, filters: dict) -> list[dict]:
        """Filter: bezirk(list), altersband(list of (lo,hi,family)),
        uhrzeit(list of band keys), von/bis (Datum lokal, YYYY-MM-DD),
        kostenlos(bool), quelle(list), q."""
        where: list[str] = []
        args: list = []

        bez = filters.get("bezirk") or []
        if bez:
            if BEZIRK_UNBEKANNT in bez:
                # „Ohne Angabe" schließt Events mit unbekanntem Bezirk ein; Sonderwert
                # wird nicht als IN-Wert verwendet, weil bezirk dort nie exakt steht.
                bez = [b for b in bez if b != BEZIRK_UNBEKANNT]
                where.append("bezirk IS NULL")
                if not bez:
                    bez = None
            if bez:
                if BEZIRK_BERLINWEIT in bez:
                    where.append(f"(bezirk IN ({','.join('?' * len(bez))}) OR bezirk = ?)")
                    args.extend(bez)
                    args.append(BEZIRK_BERLINWEIT)
                else:
                    where.append(f"bezirk IN ({','.join('?' * len(bez))})")
                    args.extend(bez)

        if filters.get("altersband"):
            # Events OHNE Altersangabe passen nur, wenn kein Altersfilter aktiv ist.
            where.append("(altersband_min IS NOT NULL OR altersband_max IS NOT NULL OR alters_familie = 1)")
            alt_or: list[str] = []
            alt_args: list = []
            for lo, hi, fam in filters["altersband"]:
                if fam:
                    alt_or.append("alters_familie = 1")
                    continue
                lo = lo if lo is not None else 0
                hi = hi if hi is not None else 99
                alt_or.append("(COALESCE(altersband_min, 0) <= ? AND COALESCE(altersband_max, 99) >= ?)")
                alt_args.extend([hi, lo])
            if alt_or:
                where.append("(" + " OR ".join(alt_or) + ")")
                args.extend(alt_args)

        if filters.get("uhrzeit"):
            band_or: list[str] = []
            band_args: list = []
            for band in filters["uhrzeit"]:
                # Ganztägige Events (ganztags=1, Start 00:00) passen zu jedem Band.
                if band == "ganztags":
                    band_or.append("(ganztags = 1 OR time(start_local) = '00:00')")
                else:
                    lo, hi = UHRZEIT_SQL[band]
                    band_or.append("ganztags = 1")
                    band_or.append("(time(start_local) >= ? AND time(start_local) < ?)")
                    band_args.extend([lo, hi])
            where.append("(" + " OR ".join(band_or) + ")")
            args.extend(band_args)

        if filters.get("von") or filters.get("bis"):
            # Fenster-Überlappung statt Starttag: Ein Event liegt im Zeitraum,
            # wenn es nicht erst nach dessen Ende beginnt und nicht schon vor
            # dessen Anfang vorbei ist. Ohne Ende-Feld gilt der Starttag als
            # Ende (eintägig) — sonst blieben eintägige Events nach ihrem Tag
            # fälschlich „laufend“. Mehrtägige Events (Start 05.09., Ende
            # 09.09.) bleiben so bei „diese Woche“ (06.–12.09.) sichtbar.
            if filters.get("bis"):
                where.append("date(start_local) <= date(?)")
                args.append(filters["bis"])
            if filters.get("von"):
                where.append(
                    "COALESCE(date(ende_local), date(start_local)) >= date(?)"
                )
                args.append(filters["von"])

        if filters.get("kostenlos") is True:
            where.append("kostenlos = 1")
        elif filters.get("kostenlos") is False:
            where.append("kostenlos = 0")

        quelle = filters.get("quelle") or []
        if quelle:
            where.append(f"quelle IN ({','.join('?' * len(quelle))})")
            args.extend(quelle)

        q = (filters.get("q") or "").strip()
        if q:
            where.append("(titel LIKE ? OR COALESCE(beschreibung_kurz, '') LIKE ? OR COALESCE(ort, '') LIKE ?)")
            args.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

        limit = min(int(filters.get("limit", 500)), 2000)
        sql = "SELECT * FROM events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY start_iso LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["kategorien"] = json.loads(d["kategorien"] or "[]")
            except json.JSONDecodeError:
                d["kategorien"] = []
            out.append(d)
        return out
    def count_events(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"])

    # --- Runs / Errors ------------------------------------------------------
    def start_run(self, quelle: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO runs(quelle, started_at) VALUES (?,?)",
                (quelle, iso_utc(datetime.now(TZ_BERLIN))),
            )
            self._conn.commit()
            run_id = int(cur.lastrowid)  # type: ignore[arg-type]
            self._run_ts[run_id] = time.time()
            return run_id

    def finish_run(self, run_id: int, *, n_events: int, n_neu: int, n_geaendert: int,
                   n_fehler: int, n_quellseiten: int, status: str = "ok"):
        with self._lock:
            self._conn.execute(
                """UPDATE runs SET finished_at=?, n_events=?, n_neu=?, n_geaendert=?,
                   n_fehler=?, n_quellseiten=?, dauer_s=?, status=?
                   WHERE id=?""",
                (iso_utc(datetime.now(TZ_BERLIN)), n_events, n_neu, n_geaendert,
                 n_fehler, n_quellseiten,
                 time.time() - self._run_ts[run_id], status, run_id),
            )
            self._conn.commit()

    def log_error(self, quelle: str, grund: str, roh: dict | None = None):
        with self._lock:
            self._conn.execute(
                "INSERT INTO errors(quelle, zeitpunkt, grund, roh) VALUES (?,?,?,?)",
                (quelle, iso_utc(datetime.now(TZ_BERLIN)), grund,
                 json.dumps(roh, ensure_ascii=False) if roh else None),
            )
            self._conn.commit()

    def recent_runs(self, quelle: str, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runs WHERE quelle=? ORDER BY id DESC LIMIT ?",
                (quelle, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_runs_all(self, quelle: str | None = None, limit: int = 50) -> list[dict]:
        if quelle:
            return self.recent_runs(quelle, limit)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def recent_errors(self, quelle: str | None, limit: int = 50) -> list[dict]:
        if quelle:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT * FROM errors WHERE quelle=? ORDER BY id DESC LIMIT ?",
                    (quelle, limit)).fetchall()
        else:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT * FROM errors ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d.get("roh"):
                try:
                    d["roh"] = json.loads(d["roh"])
                except json.JSONDecodeError:
                    pass
            out.append(d)
        return out

    def recent_errors_all(self, limit: int = 50) -> list[dict]:
        return self.recent_errors(None, limit)

    def prune_stale(self, quelle: str, cutoff_iso_utc: str) -> int:
        """Löscht Events der Quelle, deren Start vor cutoff liegt (ISO UTC)."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM events WHERE quelle=? AND start_iso < ?",
                (quelle, cutoff_iso_utc),
            )
            self._conn.commit()
            return int(cur.rowcount)

    def get_venue_cache(self, key: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM venues_cache WHERE venue_key=?", (key,)
            ).fetchone()
        return dict(r) if r else None

    def set_venue_cache(self, key: str, lat, lon, bezirk, adresse):
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO venues_cache(venue_key, lat, lon, bezirk, adresse, geholt_am)
                   VALUES (?,?,?,?,?,?)""",
                (key, lat, lon, bezirk, adresse, iso_utc(datetime.now(TZ_BERLIN))),
            )
            self._conn.commit()

    def get_ort_geo(self, ort_key: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM ort_geo WHERE ort_key=?", (ort_key,)
            ).fetchone()
        return dict(r) if r else None

    def set_ort_geo(self, ort_key: str, ort: str, lat, lon, bezirk, adresse,
                    gefunden: bool):
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO ort_geo
                   (ort_key, ort, lat, lon, bezirk, adresse, gefunden, aktualisiert_am)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (ort_key, ort, lat, lon, bezirk, adresse, int(gefunden),
                 iso_utc(datetime.now(TZ_BERLIN))),
            )
            self._conn.commit()

    # --- Admin: Quellen / Regeln / Einstellungen ----------------------------
    def _jetzt(self) -> str:
        return iso_utc(datetime.now(TZ_BERLIN))

    def seed_default_sources(self):
        """Erster Start: MVP-Quelle eintragen (idempotent, nur wenn leer)."""
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) c FROM sources").fetchone()["c"]
            if n == 0:
                self._conn.execute(
                    """INSERT INTO sources(quelle, name, typ, url, aktiv, rate_limit_s,
                       menge_min, menge_max, horizont_tage, robots, notiz, zuletzt_geaendert)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    ("jup-berlin", "jup! Berlin (offizielles Jugendportal)",
                     "intern", "https://jup.berlin/events", 1, 1.0,
                     5, 300, 60,
                     "erlaubt (robots.txt 2026-09-06)",
                     "Bestehender Python-Adapter (Change 001), typ intern",
                     self._jetzt()),
                )
                self._conn.execute(
                    "INSERT OR IGNORE INTO settings(key, wert, geaendert) VALUES ('scrape_interval_h','24',?)",
                    (self._jetzt(),),
                )
                self._conn.commit()

    def list_sources(self, aktiv_nur: bool = False) -> list[dict]:
        with self._lock:
            sql = "SELECT * FROM sources" + (" WHERE aktiv=1" if aktiv_nur else "") + " ORDER BY quelle"
            rows = self._conn.execute(sql).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["events"] = int(self._conn.execute(
                "SELECT COUNT(*) c FROM events WHERE quelle=?", (d["quelle"],)).fetchone()["c"])
            out.append(d)
        return out

    def get_source(self, quelle: str) -> dict | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM sources WHERE quelle=?", (quelle,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["events"] = int(self._conn.execute(
            "SELECT COUNT(*) c FROM events WHERE quelle=?", (quelle,)).fetchone()["c"])
        return d

    def add_source(self, quelle: str, name: str, typ: str, url: str | None = None, *,
                   aktiv: bool = True, rate_limit_s: float = 1.0,
                   menge_min: int | None = None, menge_max: int | None = None,
                   horizont_tage: int = 60, robots: str | None = None,
                   notiz: str | None = None) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO sources(quelle, name, typ, url, aktiv, rate_limit_s,
                       menge_min, menge_max, horizont_tage, robots, notiz, zuletzt_geaendert)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (quelle, name, typ, url, int(bool(aktiv)), float(rate_limit_s),
                     menge_min, menge_max, int(horizont_tage), robots, notiz, self._jetzt()),
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"Quelle existiert bereits: {quelle}") from None
            self._conn.commit()

    def update_source(self, quelle: str, **felder) -> None:
        erlaubt = {"name", "typ", "url", "aktiv", "rate_limit_s", "menge_min",
                   "menge_max", "horizont_tage", "robots", "notiz"}
        vals = {k: v for k, v in felder.items() if k in erlaubt and v is not None}
        if not vals:
            return
        vals["zuletzt_geaendert"] = self._jetzt()
        sets = ", ".join(f"{k}=?" for k in vals)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE sources SET {sets} WHERE quelle=?", (*vals.values(), quelle))
            self._conn.commit()
            if cur.rowcount == 0:
                raise ValueError(f"Unbekannte Quelle: {quelle}")

    def delete_source(self, quelle: str) -> None:
        with self._lock:
            cur = self._conn.execute("DELETE FROM sources WHERE quelle=?", (quelle,))
            self._conn.commit()
            if cur.rowcount == 0:
                raise ValueError(f"Unbekannte Quelle: {quelle}")

    def get_regeln(self, quelle: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT regel_yaml, geaendert FROM regeln WHERE quelle=?", (quelle,)).fetchone()
        return dict(r) if r else None

    def set_regeln(self, quelle: str, regel_yaml: str) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO regeln(quelle, regel_yaml, geaendert) VALUES (?,?,?)
                   ON CONFLICT(quelle) DO UPDATE SET regel_yaml=excluded.regel_yaml,
                   geaendert=excluded.geaendert""",
                (quelle, regel_yaml, self._jetzt()),
            )
            self._conn.commit()

    def all_settings(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT key, wert FROM settings").fetchall()
        return {r["key"]: r["wert"] for r in rows}

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            r = self._conn.execute("SELECT wert FROM settings WHERE key=?", (key,)).fetchone()
        return r["wert"] if r else default

    def set_setting(self, key: str, wert: str) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO settings(key, wert, geaendert) VALUES (?,?,?)
                   ON CONFLICT(key) DO UPDATE SET wert=excluded.wert, geaendert=excluded.geaendert""",
                (key, wert, self._jetzt()),
            )
            self._conn.commit()
