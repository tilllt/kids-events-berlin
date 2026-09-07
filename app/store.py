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
from datetime import datetime, timedelta
from pathlib import Path

from .model import (BEZIRK_BERLINWEIT, BEZIRK_UNBEKANNT, TZ_BERLIN, iso_utc,
                    make_event_id)

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
    status TEXT NOT NULL DEFAULT 'auto',
    manuell INTEGER NOT NULL DEFAULT 0
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
CREATE TABLE IF NOT EXISTS detail_cache (
    quelle TEXT NOT NULL,
    url TEXT NOT NULL,
    html TEXT NOT NULL,
    geholt_am TEXT NOT NULL,
    PRIMARY KEY (quelle, url)
);
CREATE TABLE IF NOT EXISTS schulen (
    bsn TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    schulform TEXT,
    bezirk TEXT,
    ortsteil TEXT,
    plz TEXT,
    strasse TEXT,
    email TEXT,
    website TEXT,
    angefragt_am TEXT,
    notiz TEXT,
    zuletzt_geaendert TEXT
);
CREATE TABLE IF NOT EXISTS tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    farbe TEXT,
    sort INTEGER NOT NULL DEFAULT 0,
    template INTEGER NOT NULL DEFAULT 0,
    zuletzt_geaendert TEXT
);
CREATE TABLE IF NOT EXISTS termine_manuell (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schule_bsn TEXT NOT NULL REFERENCES schulen(bsn) ON DELETE CASCADE,
    kategorie_id TEXT REFERENCES tags(id) ON DELETE SET NULL,
    titel TEXT NOT NULL,
    start_datum TEXT NOT NULL,
    start_zeit TEXT,
    ende_datum TEXT,
    ende_zeit TEXT,
    ganztags INTEGER NOT NULL DEFAULT 0,
    ort TEXT,
    adresse TEXT,
    beschreibung TEXT,
    url TEXT,
    status TEXT NOT NULL DEFAULT 'ungeprueft',
    quelle_hinweis TEXT,
    erstellt_am TEXT,
    zuletzt_geaendert TEXT
);
CREATE INDEX IF NOT EXISTS idx_termine_manuell_schule ON termine_manuell(schule_bsn);
CREATE INDEX IF NOT EXISTS idx_termine_manuell_status ON termine_manuell(status);
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
        # Migration VOR executescript: legt der Schema-String zuerst eine leere
        # tags-Tabelle an, greift der termin_kategorien→tags-Rename nie (Bedingung
        # 'tags not in tabs' wäre False). Frische DBs: nichts zu migrieren.
        self._migriere_alt_db()
        self._conn.executescript(SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()

    def _migriere_alt_db(self):
        """Alt-DB (vor Change-005-Redesign): events.manuell + termin_kategorien → tags.

        Bestehende DBs wurden mit dem alten Schema erzeugt (kein `manuell`-Flag,
        Tabelle `termin_kategorien`). Idempotent — jeder Aufruf prüft, was fehlt.
        """
        try:
            ev_cols = {r["name"] for r in self._conn.execute(
                "PRAGMA table_info(events)").fetchall()}
            if "manuell" not in ev_cols:
                self._conn.execute(
                    "ALTER TABLE events ADD COLUMN manuell INTEGER NOT NULL DEFAULT 0")
            # termin_kategorien (Alt) existiert → Daten nach tags übernehmen
            tabs = {r["name"] for r in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "termin_kategorien" in tabs and "tags" not in tabs:
                self._conn.execute(
                    "ALTER TABLE termin_kategorien RENAME TO tags")
                self._conn.execute(
                    "ALTER TABLE tags ADD COLUMN template INTEGER NOT NULL DEFAULT 0")
            # termine_manuell.kategorie_id zeigt ggf. noch auf termin_kategorien
            # (FK-Name ist nur Doku in SQLite — kein Umbau nötig, id bleibt id)
            self._conn.commit()
        except sqlite3.OperationalError:
            self._conn.rollback()  # z. B. ALTER doppelt in Rennbedingungen

    # --- Events -----------------------------------------------------------
    def upsert_event(self, ev: dict, *, manuell_schutz: bool = True) -> tuple[bool, bool]:
        """(neu, geaendert) — idempotent, nur echte Änderungen schreiben.

        manuell_schutz: Ein in der DB vorhandenes Event mit manuell=1 (vom Admin
        bearbeitet) wird von einem Scrape-Update NICHT überschrieben — die
        Admin-Bearbeitung gewinnt (User-Entscheidung 2026-09-07). Wer das Event
        bewusst aktualisieren will (Admin-Edit, Spiegel-Sync), ruft mit
        manuell_schutz=False bzw. setzt ev['manuell']=1.
        """
        # Kanonische Vergleichs-/Schreibform: kategorien immer als JSON-String.
        ev = dict(ev)
        ev["kategorien"] = json.dumps(ev.get("kategorien") or [], ensure_ascii=False)
        ev["manuell"] = int(bool(ev.get("manuell")))
        with self._lock:
            cur = self._conn.execute("SELECT * FROM events WHERE id = ?", (ev["id"],))
            old = cur.fetchone()
            if old is None:
                # ID-Schema-Wechsel (z. B. Quelle bekommt später Event-URLs):
                # gleicher Inhalt (Quelle+Titel+Start+Ort) unter anderer ID wäre
                # ein Duplikat → alten Zwilling übernehmen (löschen + neu schreiben).
                # Manuell gepflegte Events (manuell=1) nie als Zwilling löschen.
                zwi = self._conn.execute(
                    """SELECT id FROM events
                       WHERE quelle=? AND titel=? AND start_iso=?
                         AND COALESCE(ort,'')=COALESCE(?,'') AND id != ?
                         AND manuell = 0
                       ORDER BY id LIMIT 1""",
                    (ev["quelle"], ev["titel"], ev["start_iso"], ev.get("ort"), ev["id"]),
                ).fetchone()
                if zwi is not None:
                    self._conn.execute("DELETE FROM events WHERE id=?", (zwi["id"],))
                    self._conn.execute(
                        """INSERT INTO events (id, titel, beschreibung_kurz, start_iso, ende_iso,
                           start_local, ende_local, ganztags, ort, adresse, bezirk, lat, lon,
                           altersband_min, altersband_max, alters_familie, kategorien, kostenlos,
                           quelle, source_event_id, source_url, geholt_am, status, manuell)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        self._ev_tuple(ev),
                    )
                    self._conn.commit()
                    return False, True
                self._conn.execute(
                    """INSERT INTO events (id, titel, beschreibung_kurz, start_iso, ende_iso,
                       start_local, ende_local, ganztags, ort, adresse, bezirk, lat, lon,
                       altersband_min, altersband_max, alters_familie, kategorien, kostenlos,
                       quelle, source_event_id, source_url, geholt_am, status, manuell)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    self._ev_tuple(ev),
                )
                self._conn.commit()
                return True, False
            old_row = dict(old)
            # Manuell gepflegtes Event: Scrape-Update (ev ohne manuell=1) darf
            # es nicht überschreiben. Admin-Edits/Spiegel-Sync setzen manuell=1.
            if manuell_schutz and old_row.get("manuell") and not ev.get("manuell"):
                return False, False
            # Altlast-Bereinigung auch im Update-Pfad: Wenn dieselbe Quelle
            # dasselbe Event (Titel+Start+Ort) unter einer ANDEREN id führt
            # (ID-Schema-Wechsel, z. B. Quelle bekam später Event-URLs), ist
            # die andere id eine verwaiste Duplikat-Version → entfernen.
            zwi = self._conn.execute(
                """SELECT id FROM events
                   WHERE quelle=? AND titel=? AND start_iso=?
                     AND COALESCE(ort,'')=COALESCE(?,'') AND id != ? AND id != ?
                     AND manuell = 0
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
            int(ev.get("manuell", 0)),
        )

    def list_events_admin(self, quelle: str | None = None,
                          status: str | None = None,
                          q: str | None = None,
                          limit: int = 1000) -> list[dict]:
        """Alle Events (auch gescrapte) für die Admin-Terminliste —
        mit manuell-Flag, sortiert nach Start (neueste zuerst)."""
        where, args = [], []
        if quelle:
            where.append("quelle = ?")
            args.append(quelle)
        if status:
            where.append("status = ?")
            args.append(status)
        if q:
            where.append("(titel LIKE ? OR ort LIKE ? OR adresse LIKE ?)")
            like = f"%{q}%"
            args.extend([like, like, like])
        sql = ("SELECT * FROM events"
               + (f" WHERE {' AND '.join(where)}" if where else "")
               + " ORDER BY start_iso DESC LIMIT ?")
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["kategorien"] = json.loads(d.get("kategorien") or "[]")
            out.append(d)
        return out

    def get_event(self, ev_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM events WHERE id=?", (ev_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["kategorien"] = json.loads(d.get("kategorien") or "[]")
        return d

    def update_event_admin(self, ev_id: str, felder: dict) -> bool:
        """Admin-Edit eines Events (auch gescraptes) → manuell=1.

        Erlaubte Felder: titel, beschreibung_kurz, ort, adresse, bezirk,
        kategorien, kostenlos, ganztags. Nur gesendete Felder ändern
        (Partial-Update), nie Scrape-Felder wie quelle/source_*.
        Rückgabe: True wenn geändert."""
        erlaubt = {"titel", "beschreibung_kurz", "ort", "adresse", "bezirk",
                   "kategorien", "kostenlos", "ganztags", "start_local",
                   "ende_local"}
        sets, vals = [], []
        for k in erlaubt:
            if k in felder and felder[k] is not None:
                if k == "kategorien":
                    sets.append("kategorien = ?")
                    vals.append(json.dumps(felder[k] or [], ensure_ascii=False))
                elif k in ("kostenlos", "ganztags"):
                    sets.append(f"{k} = ?")
                    vals.append(int(bool(felder[k])))
                else:
                    sets.append(f"{k} = ?")
                    vals.append(felder[k])
        # start_local mitgeführt → start_iso (UTC) neu berechnen, damit
        # Sortierung/Filters der öffentlichen API stimmen.
        if "start_local" in felder and felder["start_local"]:
            try:
                lokal = datetime.fromisoformat(felder["start_local"])
            except ValueError:
                lokal = None
            if lokal is not None:
                sets.append("start_iso = ?")
                vals.append(iso_utc(lokal))
        if not sets:
            return False
        sets.append("manuell = 1")  # Admin-Edit → Scrape überschreibt nicht mehr
        sets.append("geholt_am = ?")
        vals.append(iso_utc(datetime.now(TZ_BERLIN)))
        vals.append(ev_id)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE events SET {', '.join(sets)} WHERE id = ?", vals)
            self._conn.commit()
        return cur.rowcount > 0


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

    def detail_cache_get(self, quelle: str, url: str, ttl_tage: int = 14) -> str | None:
        """Gecachtes Detail-HTML, wenn jünger als ttl_tage (ISO-String-Vergleich)."""
        cutoff = (datetime.now(TZ_BERLIN) - timedelta(days=ttl_tage)).isoformat()
        with self._lock:
            row = self._conn.execute(
                "SELECT html FROM detail_cache WHERE quelle=? AND url=? AND geholt_am>=?",
                (quelle, url, cutoff),
            ).fetchone()
        return row["html"] if row else None

    def detail_cache_put(self, quelle: str, url: str, html: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO detail_cache(quelle, url, html, geholt_am) VALUES (?,?,?,?) "
                "ON CONFLICT(quelle, url) DO UPDATE SET html=excluded.html, "
                "geholt_am=excluded.geholt_am",
                (quelle, url, html, datetime.now(TZ_BERLIN).isoformat()),
            )
            self._conn.commit()

    def detail_cache_prune(self, alter_tage: int = 14) -> int:
        """Entfernt Einträge, deren Quelle sie nicht mehr braucht (Seiten, die
        aus dem Zeitfenster gefallen sind)."""
        cutoff = (datetime.now(TZ_BERLIN) - timedelta(days=alter_tage)).isoformat()
        with self._lock:
            cur = self._conn.execute("DELETE FROM detail_cache WHERE geholt_am<?", (cutoff,))
            self._conn.commit()
        return cur.rowcount

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
                    "INSERT OR IGNORE INTO settings(key, wert, geaendert) VALUES ('scrape_at','05:30',?)",
                    (self._jetzt(),),
                )
                self._conn.commit()
        # Template-Tags bei jedem Start sicherstellen (idempotent) — außerhalb
        # des Locks, upsert_tag nimmt ihn selbst (Lock ist nicht reentrant).
        self.seed_template_tags()

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

    # --- Admin: Schulen / Kategorien / manuelle Termine ----------------------
    def list_schulen(self, bezirk: str | None = None, schulform: str | None = None,
                     q: str | None = None) -> list[dict]:
        where, args = [], []
        if bezirk:
            where.append("bezirk = ?")
            args.append(bezirk)
        if schulform:
            where.append("schulform = ?")
            args.append(schulform)
        if q:
            where.append("(name LIKE ? OR bsn LIKE ?)")
            args.extend([f"%{q}%", f"%{q}%"])
        sql = "SELECT * FROM schulen" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY name"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["n_termine"] = int(self._conn.execute(
                "SELECT COUNT(*) c FROM termine_manuell WHERE schule_bsn=?", (d["bsn"],)
            ).fetchone()["c"])
            out.append(d)
        return out

    def get_schule(self, bsn: str) -> dict | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM schulen WHERE bsn=?", (bsn,)).fetchone()
        return dict(r) if r else None

    def upsert_schule(self, sch: dict) -> None:
        """Anlegen oder aktualisieren (bsn = Schlüssel)."""
        f = {k: sch.get(k) for k in ("bsn", "name", "schulform", "bezirk", "ortsteil",
                                     "plz", "strasse", "email", "website", "notiz")}
        if not f.get("bsn") or not f.get("name"):
            raise ValueError("bsn und name sind Pflichtfelder für eine Schule.")
        f["zuletzt_geaendert"] = self._jetzt()
        f["bsn"] = str(f["bsn"]).strip()
        f["name"] = str(f["name"]).strip()
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO schulen(bsn, name, schulform, bezirk, ortsteil, plz,
                       strasse, email, website, notiz, zuletzt_geaendert)
                       VALUES (:bsn,:name,:schulform,:bezirk,:ortsteil,:plz,:strasse,
                               :email,:website,:notiz,:zuletzt_geaendert)""", f)
            except sqlite3.IntegrityError:
                sets = ", ".join(f"{k}=:{k}" for k in
                                 ("name", "schulform", "bezirk", "ortsteil", "plz",
                                  "strasse", "email", "website", "notiz", "zuletzt_geaendert"))
                self._conn.execute(
                    f"UPDATE schulen SET {sets} WHERE bsn=:bsn", f)
            self._conn.commit()

    def delete_schule(self, bsn: str) -> None:
        """Löscht Schule + deren manuelle Termine (FK CASCADE) + Events-Spiegel."""
        with self._lock:
            ids = [r["id"] for r in self._conn.execute(
                "SELECT id FROM termine_manuell WHERE schule_bsn=?", (bsn,)).fetchall()]
            cur = self._conn.execute("DELETE FROM schulen WHERE bsn=?", (bsn,))
            self._conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"Unbekannte Schule: {bsn}")
        for tid in ids:
            self._unsync_manuelles_event(tid)

    def set_schule_angefragt(self, bsn: str, wert: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE schulen SET angefragt_am=?, zuletzt_geaendert=? WHERE bsn=?",
                (wert, self._jetzt(), bsn))
            self._conn.commit()

    # --- Tags (für ALLE Termine; Template + eigene) -------------------------
    def list_tags(self, nur_template: bool = False) -> list[dict]:
        sql = "SELECT * FROM tags" + (" WHERE template = 1" if nur_template else "")
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY template DESC, sort, name").fetchall()
        return [dict(r) for r in rows]

    def get_tag(self, tid: str) -> dict | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM tags WHERE id=?", (tid,)).fetchone()
        return dict(r) if r else None

    def upsert_tag(self, tag: dict) -> None:
        kid = str(tag.get("id") or "").strip()
        name = str(tag.get("name") or "").strip()
        if not kid or not name:
            raise ValueError("id und name sind Pflichtfelder für einen Tag.")
        farbe = (tag.get("farbe") or "").strip() or None
        try:
            sort = int(tag.get("sort", 0) or 0)
        except (TypeError, ValueError):
            sort = 0
        template = int(bool(tag.get("template")))
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO tags(id, name, farbe, sort, template, zuletzt_geaendert) "
                    "VALUES (?,?,?,?,?,?)", (kid, name, farbe, sort, template, self._jetzt()))
            except sqlite3.IntegrityError:
                self._conn.execute(
                    "UPDATE tags SET name=?, farbe=?, sort=?, zuletzt_geaendert=? WHERE id=?",
                    (name, farbe, sort, self._jetzt(), kid))
            self._conn.commit()

    def delete_tag(self, kid: str) -> None:
        with self._lock:
            cur = self._conn.execute("DELETE FROM tags WHERE id=?", (kid,))
            self._conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"Unbekannter Tag: {kid}")

    def tag_namen(self) -> dict[str, str]:
        """id → Name für die Tag-Auflösung an Events."""
        with self._lock:
            rows = self._conn.execute("SELECT id, name FROM tags").fetchall()
        return {r["id"]: r["name"] for r in rows}

    def seed_template_tags(self) -> None:
        """Template-Tags anlegen (nur wenn id noch fehlt — nie überschreiben,
        sonst verlöre der User Anpassungen an Template-Tags bei jedem Start)."""
        template = [
            # Schul-Termine (User-Vorgabe)
            ("tdot", "Tag der offenen Tür", "#2ea043", 10),
            ("infoabend", "Infoabend", "#58a6ff", 20),
            ("schnuppertag", "Schnuppertag", "#d29922", 30),
            ("anmeldung", "Anmeldezeitraum", "#f85149", 40),
            # Übliche Veranstaltungsarten (aus Quellen-Kategorien aggregiert)
            ("workshop", "Workshop", "#8b5cf6", 100),
            ("museum", "Museum & Ausstellung", "#0d9488", 110),
            ("spiel", "Spiel & Spaß", "#ec4899", 120),
            ("natur", "Natur & Draußen", "#22c55e", 130),
            ("theater", "Theater", "#a855f7", 140),
            ("musik", "Musik & Konzert", "#f59e0b", 150),
            ("sport", "Sport", "#ef4444", 160),
            ("bibliothek", "Bibliothek & Lesen", "#3b82f6", 170),
            ("fest", "Fest & Feier", "#f97316", 180),
            ("ferien", "Ferienangebot", "#06b6d4", 190),
            ("lesung", "Lesung", "#6366f1", 200),
            ("film", "Film & Kino", "#e11d48", 210),
            ("fuehrung", "Führung", "#14b8a6", 220),
            ("markt", "Markt & Börse", "#84cc16", 230),
            ("familie", "Familienangebot", "#f472b6", 240),
        ]
        for kid, name, farbe, sort in template:
            if self.get_tag(kid) is not None:
                continue  # existiert bereits — User-Anpassung nicht überschreiben
            try:
                self.upsert_tag({"id": kid, "name": name, "farbe": farbe,
                                 "sort": sort, "template": 1})
            except ValueError:
                pass

    # --- Manuelle Termine ---------------------------------------------------
    def titel_vorschlaege(self, limit: int = 25) -> list[str]:
        """Häufigste bisherige Termin-Titel (für Auto-Complete im Formular):
        manuell gepflegte Termine + gespiegelte Schul-Events (quelle=manuell)."""
        sql = """
            SELECT titel, COUNT(*) n FROM (
                SELECT titel FROM termine_manuell
                UNION ALL
                SELECT titel FROM events WHERE quelle = 'manuell'
            ) GROUP BY titel ORDER BY n DESC, titel LIMIT ?
        """
        with self._lock:
            rows = self._conn.execute(sql, (int(limit),)).fetchall()
        return [r["titel"] for r in rows]

    def list_termine_manuell(self, schule_bsn: str | None = None,
                             status: str | None = None) -> list[dict]:
        where, args = [], []
        if schule_bsn:
            where.append("t.schule_bsn = ?")
            args.append(schule_bsn)
        if status:
            where.append("t.status = ?")
            args.append(status)
        sql = ("SELECT t.*, s.name AS schulname, s.bezirk AS schulbezirk, "
               "k.name AS kategorie_name, k.farbe AS kategorie_farbe "
               "FROM termine_manuell t "
               "LEFT JOIN schulen s ON s.bsn = t.schule_bsn "
               "LEFT JOIN tags k ON k.id = t.kategorie_id"
               + (f" WHERE {' AND '.join(where)}" if where else "")
               + " ORDER BY t.start_datum, t.start_zeit")
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def get_termin_manuell(self, tid: int) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                """SELECT t.*, s.name AS schulname, s.bezirk AS schulbezirk,
                   k.name AS kategorie_name
                   FROM termine_manuell t
                   LEFT JOIN schulen s ON s.bsn = t.schule_bsn
                   LEFT JOIN tags k ON k.id = t.kategorie_id
                   WHERE t.id=?""", (tid,)).fetchone()
        return dict(r) if r else None

    def upsert_termin_manuell(self, t: dict) -> int:
        """Anlegen (id None) oder aktualisieren. Pflicht: schule_bsn, titel,
        start_datum. Bei status='bestaetigt' wird das Event nach events
        gespiegelt (öffentliche Sichtbarkeit), sonst entfernt."""
        if not t.get("schule_bsn") or not str(t.get("titel") or "").strip() \
                or not str(t.get("start_datum") or "").strip():
            raise ValueError("schule_bsn, titel und start_datum sind Pflichtfelder.")
        tid = t.get("id")
        if tid is not None:
            tid = int(tid)
        now = self._jetzt()
        felder = dict(t)
        felder["schule_bsn"] = str(felder["schule_bsn"]).strip()
        felder["titel"] = str(felder["titel"]).strip()
        felder["start_datum"] = str(felder["start_datum"]).strip()
        for k in ("start_zeit", "ende_datum", "ende_zeit", "ort", "adresse",
                  "beschreibung", "url", "quelle_hinweis"):
            felder[k] = (str(felder[k]).strip() if felder.get(k) not in (None, "") else None)
        felder["kategorie_id"] = (str(felder["kategorie_id"]).strip()
                                  if felder.get("kategorie_id") else None)
        felder["ganztags"] = int(bool(felder.get("ganztags")))
        status = str(felder.get("status") or "ungeprueft").strip()
        if status not in ("ungeprueft", "bestaetigt"):
            raise ValueError(f"Unbekannter Status: {status}")
        felder["status"] = status
        if tid is None:
            felder["erstellt_am"] = now
            felder["zuletzt_geaendert"] = now
            with self._lock:
                cur = self._conn.execute(
                    """INSERT INTO termine_manuell(schule_bsn, kategorie_id, titel,
                       start_datum, start_zeit, ende_datum, ende_zeit, ganztags, ort,
                       adresse, beschreibung, url, status, quelle_hinweis,
                       erstellt_am, zuletzt_geaendert)
                       VALUES (:schule_bsn,:kategorie_id,:titel,:start_datum,:start_zeit,
                               :ende_datum,:ende_zeit,:ganztags,:ort,:adresse,:beschreibung,
                               :url,:status,:quelle_hinweis,:erstellt_am,:zuletzt_geaendert)""",
                    felder)
                self._conn.commit()
                tid = int(cur.lastrowid)
        else:
            felder["zuletzt_geaendert"] = now
            sets = ", ".join(f"{k}=:{k}" for k in (
                "schule_bsn", "kategorie_id", "titel", "start_datum", "start_zeit",
                "ende_datum", "ende_zeit", "ganztags", "ort", "adresse", "beschreibung",
                "url", "status", "quelle_hinweis", "zuletzt_geaendert"))
            with self._lock:
                cur = self._conn.execute(
                    f"UPDATE termine_manuell SET {sets} WHERE id=:id",
                    {**felder, "id": tid})
                self._conn.commit()
            if cur.rowcount == 0:
                raise ValueError(f"Unbekannter Termin: {tid}")
        if status == "bestaetigt":
            self._sync_manuelles_event(tid)
        else:
            self._unsync_manuelles_event(tid)
        return tid

    def delete_termin_manuell(self, tid: int) -> None:
        with self._lock:
            cur = self._conn.execute("DELETE FROM termine_manuell WHERE id=?", (tid,))
            self._conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"Unbekannter Termin: {tid}")
        self._unsync_manuelles_event(tid)

    def _termin_zu_event_dict(self, t: dict) -> dict | None:
        """Baut aus einem manuellen Termin das öffentliche Event (quelle='manuell')."""
        if t.get("status") != "bestaetigt":
            return None
        try:
            start_dt = datetime.strptime(t["start_datum"], "%d.%m.%Y").replace(tzinfo=TZ_BERLIN)
        except (ValueError, TypeError):
            return None
        zeit = (t.get("start_zeit") or "").strip()
        ganztags = bool(t.get("ganztags"))
        if zeit and not ganztags:
            try:
                hh, mm = zeit.split(":")
                start_dt = start_dt.replace(hour=int(hh), minute=int(mm))
            except (ValueError, AttributeError):
                zeit = ""
        if not zeit or ganztags:
            start_dt = start_dt.replace(hour=0, minute=0)
            ganztags = True
        ende_dt = None
        if t.get("ende_datum"):
            try:
                ende_dt = datetime.strptime(t["ende_datum"], "%d.%m.%Y").replace(tzinfo=TZ_BERLIN)
                ezeit = (t.get("ende_zeit") or "").strip()
                if ezeit and not ganztags:
                    hh, mm = ezeit.split(":")
                    ende_dt = ende_dt.replace(hour=int(hh), minute=int(mm))
                else:
                    ende_dt = ende_dt.replace(hour=23, minute=59)
            except (ValueError, AttributeError):
                ende_dt = None
        elif not ganztags and zeit:
            # Ende = Startzeit + 0 (eintägig, Zeit bekannt, kein separates Ende)
            ende_dt = None  # eintägig: Ende bleibt None (Store-Semantik)
        kategorien = [t["kategorie_name"]] if t.get("kategorie_name") else []
        tid = int(t["id"])
        ev = {
            "id": make_event_id("manuell", str(tid)),
            "titel": t["titel"],
            "beschreibung_kurz": t.get("beschreibung") or None,
            "start_iso": iso_utc(start_dt),
            "ende_iso": iso_utc(ende_dt) if ende_dt else None,
            "start_local": start_dt.astimezone(TZ_BERLIN).strftime("%Y-%m-%dT%H:%M:%S"),
            "ende_local": (ende_dt.astimezone(TZ_BERLIN).strftime("%Y-%m-%dT%H:%M:%S")
                           if ende_dt else None),
            "ganztags": int(ganztags),
            "ort": t.get("ort") or t.get("schulname"),
            "adresse": t.get("adresse"),
            "bezirk": t.get("schulbezirk"),
            "lat": None, "lon": None,
            "altersband_min": None, "altersband_max": None, "alters_familie": 0,
            "kategorien": kategorien,
            "kostenlos": 1,  # Schultermine (tdot/Infoabend) sind kostenlos
            "quelle": "manuell",
            "source_event_id": str(tid),
            "source_url": t.get("url") or "",
            "geholt_am": iso_utc(datetime.now(TZ_BERLIN)),
            "status": "manuell",
            "manuell": 1,  # Admin-gepflegt — Scrape überschreibt nie
        }
        return ev

    def _sync_manuelles_event(self, tid: int) -> None:
        t = self.get_termin_manuell(tid)
        if not t:
            return
        ev = self._termin_zu_event_dict(t)
        if not ev:
            self._unsync_manuelles_event(tid)
            return
        self.upsert_event(ev)

    def _unsync_manuelles_event(self, tid: int) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM events WHERE quelle='manuell' AND source_event_id=?",
                (str(tid),))
            self._conn.commit()
