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

from . import dedupe
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
    manuell INTEGER NOT NULL DEFAULT 0,
    -- Change 016: wann hat die Quelle diesen Termin zuletzt angeboten?
    zuletzt_gesehen TEXT,
    -- Change 011: weitere Quellen, die dieselbe Veranstaltung gelistet haben
    quellen_json TEXT
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
-- Change 017: Seiten-Archiv der letzten GESUNDEN Listing-Seite je Quelle.
-- Grundlage für die Regressionsprobe eines Reparaturvorschlags: ein Selektor,
-- der nur zufällig auf die heutige Seite passt, findet dort nichts.
CREATE TABLE IF NOT EXISTS seiten_archiv (
    quelle TEXT NOT NULL,
    url TEXT NOT NULL,
    html TEXT NOT NULL,
    treffer INTEGER NOT NULL DEFAULT 0,
    geholt_am TEXT NOT NULL,
    PRIMARY KEY (quelle, url)
);
-- Change 017: festgestellte Störungen und (Phase 2) Reparaturvorschläge.
-- status: offen | beobachtet | vorgeschlagen | angenommen | abgelehnt
CREATE TABLE IF NOT EXISTS heilungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quelle TEXT NOT NULL,
    art TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'offen',
    befund_json TEXT NOT NULL,
    diagnose_json TEXT,
    vorschlag_yaml TEXT,
    begruendung TEXT,
    beleg_json TEXT,
    erstellt_am TEXT NOT NULL,
    geaendert_am TEXT
);
CREATE INDEX IF NOT EXISTS idx_heilungen_quelle ON heilungen(quelle, erstellt_am);
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
    schulzweig_id TEXT,
    angefragt_am TEXT,
    recherche_am TEXT,
    recherche_status TEXT,
    recherche_notiz TEXT,
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
-- Change 012: jeder Brave-Aufruf wird VOR dem Absenden verbucht (Reservierung),
-- nach der Antwort um HTTP-Code/Treffer/Fehler ergaenzt. Das Monats- und
-- Tagesbudget wird daraus gezaehlt — kein Zaehler in den Einstellungen, der
-- driften koennte.
-- Change 013: Versand-Protokoll der Schul-Anfragen (Tagesbremse + Nachweis).
CREATE TABLE IF NOT EXISTS mail_versand (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT,
    stunde TEXT,
    an TEXT NOT NULL,
    betreff TEXT,
    schule_bsn TEXT,
    zeitpunkt TEXT NOT NULL,
    ok INTEGER,
    fehler TEXT
);
CREATE INDEX IF NOT EXISTS idx_mail_versand_tag ON mail_versand(tag);

CREATE TABLE IF NOT EXISTS brave_aufrufe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monat TEXT NOT NULL,
    tag TEXT,
    bsn TEXT,
    query TEXT NOT NULL,
    zeitpunkt TEXT NOT NULL,
    http_code INTEGER,
    treffer INTEGER,
    fehler TEXT
);
CREATE INDEX IF NOT EXISTS idx_brave_aufrufe_monat ON brave_aufrufe(monat);
CREATE TABLE IF NOT EXISTS schul_recherche_lauf (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bsn TEXT NOT NULL,
    url TEXT,
    seiten_hash TEXT,
    modell TEXT,
    n_roh INTEGER NOT NULL DEFAULT 0,
    n_belegt INTEGER NOT NULL DEFAULT 0,
    verworfen_grund TEXT,
    dauer_s REAL,
    erstellt_am TEXT
);
CREATE INDEX IF NOT EXISTS idx_recherche_lauf_bsn ON schul_recherche_lauf(bsn);
"""

# Uhrzeit-Bänder (Ortszeit), für time()-Vergleich in SQL.
UHRZEIT_SQL = {
    "vormittag": ("00:00", "12:00"),
    "nachmittag": ("12:00", "17:00"),
    "abend": ("17:00", "24:00"),
}

# Ein Termin ist ganztägig, wenn er so markiert ist ODER um 00:00 beginnt.
# Quellen, die nur ein Datum ohne Uhrzeit liefern (z. B. Umweltkalender,
# Festivals), landen auf 00:00 — solche Termine müssen in jedem Zeitband
# auftauchen, sonst verschwindet ein Tagesfest beim Filter „nachmittags“.
# Achtung: SQLites time() liefert „HH:MM:SS“ — der Vergleich gegen das
# frühere „'00:00'“ war deshalb immer falsch (Gleichheit griff nie).
GANZTAGS_SQL = "(ganztags = 1 OR time(start_local) < '00:01')"


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
            # Change 011: Provenienz zusammengeführter Dubletten (weitere Quellen,
            # die dieselbe Veranstaltung gelistet haben).
            if "quellen_json" not in ev_cols:
                self._conn.execute("ALTER TABLE events ADD COLUMN quellen_json TEXT")
            # Change 016: Grundlage für das Entfernen nicht mehr angebotener
            # Termine (deterministisch: die Quelle selbst ist das Signal).
            if "zuletzt_gesehen" not in ev_cols:
                self._conn.execute("ALTER TABLE events ADD COLUMN zuletzt_gesehen TEXT")
            # Altbestand: alles, was schon da ist, gilt als zuletzt beim Holen
            # gesehen — sonst würde der erste Lauf nach dem Update den ganzen
            # Bestand als „nicht mehr angeboten" einstufen.
            self._conn.execute(
                "UPDATE events SET zuletzt_gesehen = geholt_am "
                "WHERE zuletzt_gesehen IS NULL")
            # Change 012: Schulenbezug je Brave-Aufruf (Wiederholungs-Schutz)
            br_cols = {r["name"] for r in self._conn.execute(
                "PRAGMA table_info(brave_aufrufe)").fetchall()}
            if br_cols and "bsn" not in br_cols:
                self._conn.execute("ALTER TABLE brave_aufrufe ADD COLUMN bsn TEXT")
            # schulen.schulzweig_id (Link auf das offizielle Schulportrait)
            sc_cols = {r["name"] for r in self._conn.execute(
                "PRAGMA table_info(schulen)").fetchall()}
            if sc_cols and "schulzweig_id" not in sc_cols:
                self._conn.execute(
                    "ALTER TABLE schulen ADD COLUMN schulzweig_id TEXT")
            # Change 010: Recherche-Stand je Schule (Alt-DBs ohne diese Spalten)
            for spalte in ("recherche_am TEXT", "recherche_status TEXT",
                           "recherche_notiz TEXT"):
                if sc_cols and spalte.split()[0] not in sc_cols:
                    self._conn.execute(f"ALTER TABLE schulen ADD COLUMN {spalte}")
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
                           quelle, source_event_id, source_url, geholt_am, status, manuell,
                           quellen_json)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        self._ev_tuple(ev),
                    )
                    self._conn.commit()
                    return False, True
                # Change 011: dieselbe Veranstaltung — auch aus einer anderen
                # Quelle und auch bei abweichender Orts-Schreibweise — wird
                # zusammengeführt statt ein zweites Mal eingefügt.
                if not ev.get("manuell"):
                    self._conn.commit()  # Zwilling-Suche sieht den aktuellen Stand
                    zwilling = self._zwilling_identisch(ev)
                    if zwilling is not None:
                        neuer_ist_besser = dedupe.quelle_prio(ev["quelle"]) < dedupe.quelle_prio(
                            zwilling["quelle"])
                        if neuer_ist_besser:
                            # Amtliche Quelle kommt später dazu: alten Satz als
                            # Provenienz übernehmen und durch den neuen ersetzen.
                            quellen = self._quellen_liste(zwilling.get("quellen_json"))
                            dedupe.provenienz_ergaenzen(quellen, zwilling["quelle"],
                                                        zwilling.get("source_url"),
                                                        zwilling.get("source_event_id"))
                            ev["quellen_json"] = json.dumps(quellen, ensure_ascii=False)
                            for feld, wert in dedupe.fehlende_felder(ev, zwilling).items():
                                ev.setdefault(feld, wert)
                            self._conn.execute("DELETE FROM events WHERE id=?",
                                               (zwilling["id"],))
                        else:
                            # Bestehender Satz bleibt kanonisch: fehlende Felder
                            # ergänzen, fremde Quelle als Provenienz vermerken.
                            quellen = self._quellen_liste(zwilling.get("quellen_json"))
                            if ev["quelle"] != zwilling["quelle"]:
                                dedupe.provenienz_ergaenzen(quellen, ev["quelle"],
                                                            ev.get("source_url"),
                                                            ev.get("source_event_id"))
                            fuellung = dedupe.fehlende_felder(zwilling, ev)
                            sets = "".join(f", {k}=?" for k in fuellung)
                            self._conn.execute(
                                f"UPDATE events SET quellen_json=?{sets} WHERE id=?",
                                (json.dumps(quellen, ensure_ascii=False),
                                 *fuellung.values(), zwilling["id"]))
                            self._conn.commit()
                            return False, True
                self._conn.execute(
                    """INSERT INTO events (id, titel, beschreibung_kurz, start_iso, ende_iso,
                       start_local, ende_local, ganztags, ort, adresse, bezirk, lat, lon,
                       altersband_min, altersband_max, alters_familie, kategorien, kostenlos,
                       quelle, source_event_id, source_url, geholt_am, status, manuell, quellen_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
            int(ev.get("manuell", 0)), ev.get("quellen_json"),
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


    def list_orte(self, filters: dict, limit: int = 400) -> list[dict]:
        """Veranstaltungsorte mit Anzahl im aktuellen Filterkontext.

        Für den Ortsfilter der Startseite: die Auswahlliste muss sich den
        übrigen Filtern anpassen — ist ein Bezirk gewählt, dürfen nur Orte in
        diesem Bezirk erscheinen. Der Ortsfilter selbst zählt dabei NICHT mit
        (sonst würde eine Auswahl ihre eigene Optionsliste auf einen Eintrag
        zusammenstreichen und man käme nicht mehr heraus).
        """
        f = {k: v for k, v in (filters or {}).items() if k != "orte"}
        f["limit"] = 20000
        zaehler: dict[tuple, int] = {}
        for e in self.query_events(f):
            ort = (e.get("ort") or "").strip()
            if not ort or ort == "Ohne Angabe":
                continue
            schluessel = (ort, e.get("bezirk"))
            zaehler[schluessel] = zaehler.get(schluessel, 0) + 1
        out = [{"ort": ort, "bezirk": bez, "n": n} for (ort, bez), n in zaehler.items()]
        out.sort(key=lambda o: (-o["n"], o["ort"].lower()))
        return out[:limit]

    def query_events(self, filters: dict) -> list[dict]:
        """Filter: bezirk(list), orte(list), altersband(list of (lo,hi,family)),
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

        if filters.get("orte"):
            orte = list(filters["orte"])
            where.append(f"ort IN ({','.join('?' * len(orte))})")
            args.extend(orte)

        if filters.get("uhrzeit"):
            band_or: list[str] = []
            band_args: list = []
            for band in filters["uhrzeit"]:
                # Ganztägige Termine gehören in JEDES Zeitband — ein Tagesfest
                # ist nachmittags genauso relevant wie vormittags. Ein Termin
                # gilt als ganztägig, wenn er so markiert ist ODER um 00:00
                # beginnt (viele Quellen liefern "nur Datum" ohne Uhrzeit).
                # Ohne den zweiten Teil fielen genau diese Termine stumm aus
                # jedem Band außer "ganztags".
                if band == "ganztags":
                    band_or.append(GANZTAGS_SQL)
                else:
                    lo, hi = UHRZEIT_SQL[band]
                    band_or.append(GANZTAGS_SQL)
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
        """Löscht Events der Quelle, die VOR cutoff ENDEN (ISO UTC).

        Ende statt Start: mehrtägige Events (Ferienworkshop 09.–13.09.) sind
        an ihrem vierten Tag noch nicht „alt“ — eine Start-Bedingung warf sie
        mitten im Lauf weg (realer Befund 2026-09-12: ein laufender Workshop
        verschwand aus Liste und Karte). Fehlendes ende_local = eintägig →
        dann zählt der Starttag.
        """
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM events WHERE quelle=? AND "
                "COALESCE(ende_iso, start_iso) < ?",
                (quelle, cutoff_iso_utc),
            )
            self._conn.commit()
            return int(cur.rowcount)

    def markiere_gesehen(self, quelle: str, refs: list[tuple[str, str]],
                         zeit: str) -> int:
        """Change 016: stempelt alle Termine, die die Quelle noch anbietet.

        refs = (id, source_event_id) der gelesenen Termine. Der normale
        Schreibpfad ändert nur echte Unterschiede — ohne diesen Stempel hätte
        ein unveränderter Termin nach Tagen ein altes „zuletzt gesehen" und
        gälte fälschlich als nicht mehr angeboten. Beide Kennungen werden
        geprüft: nach einer Zusammenführung kann der Satz unter anderer id stehen.
        """
        if not refs:
            return 0
        ids = [r[0] for r in refs if r[0]]
        sids = [r[1] for r in refs if len(r) > 1 and r[1]]
        n = 0
        with self._lock:
            for spalte, werte in (("id", ids), ("source_event_id", sids)):
                for i in range(0, len(werte), 400):   # SQL-Variablen begrenzen
                    block = werte[i:i + 400]
                    ph = ",".join("?" * len(block))
                    cur = self._conn.execute(
                        f"UPDATE events SET zuletzt_gesehen=? WHERE quelle=? "
                        f"AND {spalte} IN ({ph})",
                        [zeit, quelle, *block])
                    n += int(cur.rowcount)
            self._conn.commit()
        return n

    def entferne_nicht_mehr_angeboten(self, quelle: str, lauf_start: str,
                                      ok: bool = True) -> int:
        """Change 016: Termine löschen, die die Quelle nicht mehr anbietet.

        Bedingung: „zuletzt gesehen" fehlt oder liegt VOR dem Laufbeginn UND der
        letzte Tag (Ende, sonst Start) liegt in der Vergangenheit. Ein
        Mehrtagestermin, den die Quelle weiterhin anbietet, ist gestempelt und
        bleibt. Bei ok=False (Lauf mit Fehlern) passiert nichts — ein halb
        gelesenes Listing darf keinen Termin kosten.
        """
        if not ok:
            return 0
        heute = lauf_start[:10]
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM events WHERE quelle=? "
                "AND (zuletzt_gesehen IS NULL OR zuletzt_gesehen < ?) "
                "AND substr(COALESCE(ende_local, start_local), 1, 10) < ?",
                (quelle, lauf_start, heute),
            )
            self._conn.commit()
            return int(cur.rowcount)

    # ---- Change 017: Selbstheilung ---------------------------------------

    def seiten_archiv_setzen(self, quelle: str, url: str, html: str,
                             treffer: int, zeit: str) -> None:
        """Letzte GESUNDE Listing-Seite merken (Grundlage der Regressionsprobe)."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO seiten_archiv (quelle, url, html, treffer, geholt_am) "
                "VALUES (?,?,?,?,?) ON CONFLICT(quelle, url) DO UPDATE SET "
                "html=excluded.html, treffer=excluded.treffer, "
                "geholt_am=excluded.geholt_am",
                (quelle, url, html, int(treffer), zeit))
            self._conn.commit()

    def seiten_archiv_holen(self, quelle: str, url: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM seiten_archiv WHERE quelle=? AND url=?",
            (quelle, url)).fetchone()
        return dict(row) if row else None

    def heilung_anlegen(self, quelle: str, art: str, befund: dict, zeit: str,
                        status: str = "offen") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO heilungen (quelle, art, status, befund_json, "
                "diagnose_json, erstellt_am) VALUES (?,?,?,?,?,?)",
                (quelle, art, status,
                 json.dumps(befund, ensure_ascii=False),
                 json.dumps(befund.get("diagnose") or {}, ensure_ascii=False), zeit))
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def heilung_offen_fuer(self, quelle: str, tag: str = "") -> dict | None:
        """Schon eine offene Meldung? (Höchstens ein Heilungsversuch je Quelle/Tag)"""
        where = ("quelle=? AND status IN ('offen','vorschlagen','vorgeschlagen')")
        args: list = [quelle]
        if tag:
            where += " AND substr(erstellt_am,1,10)=?"
            args.append(tag)
        row = self._conn.execute(
            f"SELECT * FROM heilungen WHERE {where} ORDER BY id DESC LIMIT 1",
            args).fetchone()
        return dict(row) if row else None

    def heilungen_liste(self, quelle: str | None = None,
                        limit: int = 50) -> list[dict]:
        if quelle:
            rows = self._conn.execute(
                "SELECT * FROM heilungen WHERE quelle=? ORDER BY id DESC LIMIT ?",
                (quelle, limit)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM heilungen ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def heilung_setzen(self, heilung_id: int, *, status: str | None = None,
                       vorschlag_yaml: str | None = None,
                       begruendung: str | None = None,
                       beleg: dict | None = None, zeit: str = "") -> None:
        sets, args = [], []
        for spalte, wert in (("status", status), ("vorschlag_yaml", vorschlag_yaml),
                             ("begruendung", begruendung)):
            if wert is not None:
                sets.append(f"{spalte}=?")
                args.append(wert)
        if beleg is not None:
            sets.append("beleg_json=?")
            args.append(json.dumps(beleg, ensure_ascii=False))
        if zeit:
            sets.append("geaendert_am=?")
            args.append(zeit)
        if not sets:
            return
        args.append(heilung_id)
        with self._lock:
            self._conn.execute(f"UPDATE heilungen SET {', '.join(sets)} WHERE id=?", args)
            self._conn.commit()

    def entferne_ueberlappende_zwillinge(self, quelle: str) -> list[dict]:
        """Überlappende Serien-Zwillinge EINER Quelle zusammenfassen.

        Quellen führen mehrtägige Events teils als mehrere, je um einen Tag
        verschobene Einträge mit derselben Spanne (jup.berlin: „Veranstaltungs-
        termin/e“) — jeder Eintrag ist einzeln korrekt, in Summe entsteht ein
        Stapel überlappender Kopien in Liste und Karte (realer User-Befund
        2026-09-12: ein Ferienworkshop 13× im Bestand).

        Regel: Gruppen aus gleicher Quelle + normalisiertem Titel + Ort werden
        zu Ketten mit ECHTER Überlappung zusammengefasst (start < ende des
        Vorgängers; fehlendes ende zählt als Starttag). Je Kette bleibt der
        Eintrag mit dem FRÜHESTEN Start — das ist der ursprüngliche Termin,
        die verschobenen Kopien sind die späteren.

        Berührende Slots (ende == start, z. B. ZLB-Stundenblöcke 09–10/10–11
        Uhr) sind KEINE Dubletten und bleiben unangetastet, ebenso gleiche
        Titel an verschiedenen Orten und manuell gepflegte Events (manuell=1).

        Rückgabe: die gelöschten Datensätze (für Metrik/Log).
        """
        with self._lock:
            rows = [dict(r) for r in self._conn.execute(
                "SELECT id, titel, ort, start_local, ende_local FROM events "
                "WHERE quelle=? AND COALESCE(manuell, 0) = 0 "
                "ORDER BY start_local, id", (quelle,)).fetchall()]

        def _key(r: dict) -> tuple[str, str]:
            return ((r.get("titel") or "").strip().lower(),
                    (r.get("ort") or "").strip().lower())

        def _dt(v):
            try:
                return datetime.fromisoformat(v) if v else None
            except ValueError:
                return None

        gruppen: dict[tuple[str, str], list[dict]] = {}
        for r in rows:
            gruppen.setdefault(_key(r), []).append(r)

        zu_loeschen: list[dict] = []
        for items in gruppen.values():
            if len(items) < 2:
                continue
            kette = [items[0]]
            for r in items[1:]:
                ende_vor = _dt(kette[-1].get("ende_local")) or _dt(kette[-1]["start_local"])
                start = _dt(r["start_local"])
                if ende_vor and start and start < ende_vor:
                    kette.append(r)
                else:
                    zu_loeschen.extend(kette[1:])
                    kette = [r]
            zu_loeschen.extend(kette[1:])
        if not zu_loeschen:
            return []
        with self._lock:
            self._conn.executemany("DELETE FROM events WHERE id = ?",
                                   [(r["id"],) for r in zu_loeschen])
            self._conn.commit()
        return zu_loeschen

    # --- Change 013: Mail-Versand (Protokoll + Tagesbremse) ------------------
    def starte_mail_versand(self, an: str, betreff: str, schule_bsn: str | None = None) -> int:
        jetzt = datetime.now(TZ_BERLIN)
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO mail_versand(tag, stunde, an, betreff, schule_bsn, zeitpunkt, ok)
                   VALUES (?,?,?,?,?,?,0)""",
                (jetzt.strftime("%Y-%m-%d"), jetzt.strftime("%Y-%m-%dT%H"), an[:200],
                 betreff[:300], schule_bsn, iso_utc(jetzt)))
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def beende_mail_versand(self, eintrag_id: int, *, ok: bool, fehler: str | None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE mail_versand SET ok=?, fehler=? WHERE id=?",
                (1 if ok else 0, fehler, eintrag_id))
            self._conn.commit()

    def mail_versand_zaehler(self) -> dict:
        jetzt = datetime.now(TZ_BERLIN)
        tag, stunde = jetzt.strftime("%Y-%m-%d"), jetzt.strftime("%Y-%m-%dT%H")
        with self._lock:
            heute = self._conn.execute(
                "SELECT COUNT(*) c FROM mail_versand WHERE tag=?", (tag,)).fetchone()["c"]
            diese_stunde = self._conn.execute(
                "SELECT COUNT(*) c FROM mail_versand WHERE stunde=?", (stunde,)).fetchone()["c"]
            gesamt = self._conn.execute(
                "SELECT COUNT(*) c FROM mail_versand").fetchone()["c"]
            fehler = self._conn.execute(
                "SELECT COUNT(*) c FROM mail_versand WHERE ok=0").fetchone()["c"]
        return {"tag": tag, "heute": heute, "diese_stunde": diese_stunde,
                "gesamt": gesamt, "fehler_gesamt": fehler}

    def mail_versand_bremse_grund(self) -> str | None:
        """Warum gerade NICHT gesendet werden darf (None = frei).

        Schützt davor, dass ein Fehllauf 700 Schulen anschreibt: Grenzen sind
        `mail_max_pro_tag` (Standard 40) und `mail_absender_pro_stunde` (20).
        """
        def zahl(key, standard):
            try:
                return int(str(self.get_setting(key) or standard).strip())
            except (TypeError, ValueError):
                return standard
        z = self.mail_versand_zaehler()
        max_tag = zahl("mail_max_pro_tag", 40)
        max_stunde = zahl("mail_absender_pro_stunde", 20)
        if max_tag and z["heute"] >= max_tag:
            return (f"Tagesgrenze für den Mail-Versand erreicht ({z['heute']}/{max_tag}) "
                    f"— morgen geht es weiter.")
        if max_stunde and z["diese_stunde"] >= max_stunde:
            return (f"Stundengrenze für den Mail-Versand erreicht "
                    f"({z['diese_stunde']}/{max_stunde}) — bitte kurz warten.")
        return None

    def mail_versand_erlaubt(self) -> bool:
        return self.mail_versand_bremse_grund() is None

    def mail_letzte(self, limit: int = 25) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, tag, an, betreff, schule_bsn, zeitpunkt, ok, fehler
                   FROM mail_versand ORDER BY id DESC LIMIT ?""", (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    # --- Change 013: Mail-Versand (Protokoll + Tagesbremse) ENDE -------------

    # --- Change 012: Brave-Websuche (Kontingent-Verwaltung) ------------------
    def starte_brave_aufruf(self, monat: str, query: str, bsn: str | None = None) -> int:
        """Aufruf reservieren (zählt gegen das Budget, auch wenn er scheitert)."""
        jetzt = datetime.now(TZ_BERLIN)
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO brave_aufrufe(monat, tag, bsn, query, zeitpunkt, http_code, treffer)
                   VALUES (?,?,?,?,?,0,0)""",
                (monat, jetzt.strftime("%Y-%m-%d"), bsn, query[:300], iso_utc(jetzt)))
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def brave_letzte_suche(self, bsn: str) -> str | None:
        """Zeitpunkt der letzten Websuche zu dieser Schule (Wiederholungs-Schutz)."""
        with self._lock:
            r = self._conn.execute(
                """SELECT zeitpunkt FROM brave_aufrufe WHERE bsn=?
                   ORDER BY id DESC LIMIT 1""", (bsn,)).fetchone()
        return r["zeitpunkt"] if r else None

    def beende_brave_aufruf(self, aufruf_id: int, *, http_code: int | None,
                            treffer: int, fehler: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE brave_aufrufe SET http_code=?, treffer=?, fehler=? WHERE id=?",
                (http_code, treffer, fehler, aufruf_id))
            self._conn.commit()

    def brave_verbrauch(self, heute=None) -> dict:
        """Verbrauch aus den Aufrufen selbst (kein separater Zähler)."""
        tag = (heute or datetime.now(TZ_BERLIN).date()).strftime("%Y-%m-%d")
        mo = tag[:7]
        with self._lock:
            monat_anzahl = self._conn.execute(
                "SELECT COUNT(*) c FROM brave_aufrufe WHERE monat=?", (mo,)).fetchone()["c"]
            tag_anzahl = self._conn.execute(
                "SELECT COUNT(*) c FROM brave_aufrufe WHERE tag=?", (tag,)).fetchone()["c"]
            gesamt = self._conn.execute(
                "SELECT COUNT(*) c FROM brave_aufrufe").fetchone()["c"]
            fehler = self._conn.execute(
                "SELECT COUNT(*) c FROM brave_aufrufe WHERE monat=? AND fehler IS NOT NULL",
                (mo,)).fetchone()["c"]
        return {"monat": mo, "monat_anzahl": monat_anzahl, "tag": tag,
                "tag_anzahl": tag_anzahl, "gesamt": gesamt, "fehler_monat": fehler}

    def brave_letzte(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, monat, tag, query, zeitpunkt, http_code, treffer, fehler
                   FROM brave_aufrufe ORDER BY id DESC LIMIT ?""", (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    # --- Change 011: Dubletten über Quellen hinweg ---------------------------
    def _quellen_liste(self, roh: str | None) -> list[dict]:
        if not roh:
            return []
        try:
            d = json.loads(roh)
        except json.JSONDecodeError:
            return []
        return d if isinstance(d, list) else []

    def merge_doppelte_events(self, *, dry_run: bool = False,
                              nur_quelle: str | None = None) -> dict:
        """Dieselbe Veranstaltung aus mehreren Quellen zu einem Datensatz.

        Kanon = manuell gepflegt > amtliche Quelle > Einrichtung > Aggregator,
        bei Gleichstand der datenreichere Satz. Leere Felder des Kanons werden
        aus der Dublette gefüllt (real: Endzeit stand nur in einer Quelle), die
        weiteren Quellen wandern als Provenienz in `quellen_json`. Manuell
        gepflegte Datensätze werden nie entfernt.

        Rückgabe: Zähler + Listen für Bericht/Status (kein stiller Eingriff).
        """
        with self._lock:
            rows = [dict(r) for r in self._conn.execute("SELECT * FROM events").fetchall()]
        if nur_quelle:
            rows = [r for r in rows if r["quelle"] == nur_quelle]
        bericht = dedupe.finde_dubletten(rows)
        ergebnis = {"geprueft": len(rows), "gruppen": len(bericht["merges"]),
                    "entfernbar": bericht["entfernbar"], "entfernt": 0,
                    "felder_ergaenzt": 0, "verdacht": len(bericht["verdacht"]),
                    "dry_run": dry_run,
                    "beispiele": [{"behalten": m["kanon"]["titel"],
                                   "behalten_quelle": m["kanon"]["quelle"],
                                   "entfernt": [{"quelle": d["quelle"], "titel": d["titel"]}
                                                for d in m["dubletten"]][:5]}
                                  for m in bericht["merges"][:10]],
                    "verdachtsfaelle": [{"titel": v["kandidat"]["titel"],
                                         "datum": (v["kandidat"].get("start_local") or "")[:16],
                                         "grund": v["grund"]} for v in bericht["verdacht"][:10]]}
        if dry_run or not bericht["merges"]:
            return ergebnis
        for m in bericht["merges"]:
            kanon = m["kanon"]
            entfernbar = [d for d in m["dubletten"] if not d.get("manuell")]
            if not entfernbar:
                continue
            quellen = self._quellen_liste(kanon.get("quellen_json"))
            fuellung: dict = {}
            for d in entfernbar:
                dedupe.provenienz_ergaenzen(quellen, d["quelle"], d.get("source_url"),
                                            d.get("source_event_id"))
                for feld, wert in dedupe.fehlende_felder(kanon, d).items():
                    if feld in fuellung:
                        continue
                    fuellung[feld] = wert
                    kanon[feld] = wert  # damit weitere Dubletten denselben Stand sehen
            with self._lock:
                if fuellung:
                    sets = ", ".join(f"{k}=?" for k in fuellung)
                    self._conn.execute(
                        f"UPDATE events SET {sets}, quellen_json=? WHERE id=?",
                        (*fuellung.values(), json.dumps(quellen, ensure_ascii=False),
                         kanon["id"]))
                else:
                    self._conn.execute(
                        "UPDATE events SET quellen_json=? WHERE id=?",
                        (json.dumps(quellen, ensure_ascii=False), kanon["id"]))
                self._conn.executemany("DELETE FROM events WHERE id=?",
                                       [(d["id"],) for d in entfernbar])
                self._conn.commit()
            ergebnis["entfernt"] += len(entfernbar)
            ergebnis["felder_ergaenzt"] += len(fuellung)
        return ergebnis

    def _zwilling_identisch(self, ev: dict) -> dict | None:
        """Bestehender Datensatz (jede Quelle), der DIESELBE Termin ist.

        Schützt strukturell davor, dass dieselbe Veranstaltung mehrfach in die
        Datenbank kommt (real: ein Tag der offenen Tür 57× im Bestand). Die
        Identitätsregeln stehen in `app.dedupe` — u. a. gleicher Titel, gleicher
        Tag, gleiche Uhrzeit und ein verträglicher Ort (damit unterschiedliche
        Veranstaltungen am selben Ort zur selben Zeit getrennt bleiben).

        ACHTUNG: wird nur aus `upsert_event` aufgerufen und läuft dort bereits
        unter `self._lock` — deshalb hier KEIN erneutes Lock (sonst Deadlock,
        weil `threading.Lock` nicht wiedereintrittsfähig ist).
        """
        rows = [dict(r) for r in self._conn.execute(
            """SELECT * FROM events WHERE start_iso=? AND lower(trim(titel))=?
               AND id != ?""",
            (ev["start_iso"], (ev.get("titel") or "").strip().lower(),
             ev["id"])).fetchall()]
        for r in rows:
            if r.get("manuell") and not ev.get("manuell"):
                continue  # manuell gepflegte Sätze werden nicht als Zwilling benutzt
            gleich, _ = dedupe.gleiche_veranstaltung(r, ev)
            if gleich:
                return r
        return None

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
                     q: str | None = None, ohne_termin: bool = False,
                     nur_mit_email: bool = False,
                     nur_ohne_fund: bool = False) -> list[dict]:
        """Schulen für die Verwaltung — mit denselben Filtern wie im Frontend.

        `ohne_termin` blendet Schulen aus, die schon einen Termin haben (Vorschlag
        oder freigegeben, Datum heute oder später). `naechster_termin` steht in
        jeder Zeile, damit die Oberfläche den Grund zeigen kann.
        """
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
        if nur_mit_email:
            where.append("TRIM(COALESCE(email, '')) <> ''")
        if nur_ohne_fund:
            where.append("COALESCE(recherche_status, '') <> 'gefunden'")
        heute = datetime.now(TZ_BERLIN).strftime("%Y-%m-%d")
        sql = ("SELECT s.*, "
               "(SELECT COUNT(*) FROM termine_manuell t WHERE t.schule_bsn = s.bsn) AS n_termine, "
               "(SELECT MIN(t.start_datum) FROM termine_manuell t WHERE t.schule_bsn = s.bsn "
               "   AND t.start_datum >= ?) AS naechster_termin "
               "FROM schulen s" +
               (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY name")
        with self._lock:
            rows = self._conn.execute(sql, [heute] + args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["hat_termin"] = bool(d.get("naechster_termin"))
            if ohne_termin and d["hat_termin"]:
                continue
            out.append(d)
        return out

    def bezirke_liste(self) -> list[str]:
        """Vorkommende Bezirke im Schulbestand (Filterliste der Oberfläche)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT bezirk FROM schulen WHERE TRIM(COALESCE(bezirk, '')) <> '' "
                "ORDER BY bezirk").fetchall()
        return [r["bezirk"] for r in rows]

    def schulformen_liste(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT schulform FROM schulen "
                "WHERE TRIM(COALESCE(schulform, '')) <> '' ORDER BY schulform").fetchall()
        return [r["schulform"] for r in rows]

    def get_schule(self, bsn: str) -> dict | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM schulen WHERE bsn=?", (bsn,)).fetchone()
        return dict(r) if r else None

    def upsert_schule(self, sch: dict) -> None:
        """Anlegen oder aktualisieren (bsn = Schlüssel)."""
        f = {k: sch.get(k) for k in ("bsn", "name", "schulform", "bezirk", "ortsteil",
                                     "plz", "strasse", "email", "website",
                                     "schulzweig_id", "notiz")}
        if not f.get("bsn") or not f.get("name"):
            raise ValueError("bsn und name sind Pflichtfelder für eine Schule.")
        f["zuletzt_geaendert"] = self._jetzt()
        f["bsn"] = str(f["bsn"]).strip()
        f["name"] = str(f["name"]).strip()
        for k in ("email", "website", "schulzweig_id", "notiz"):
            f[k] = (str(f[k]).strip() if f.get(k) not in (None, "") else None)
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO schulen(bsn, name, schulform, bezirk, ortsteil, plz,
                       strasse, email, website, schulzweig_id, notiz, zuletzt_geaendert)
                       VALUES (:bsn,:name,:schulform,:bezirk,:ortsteil,:plz,:strasse,
                               :email,:website,:schulzweig_id,:notiz,:zuletzt_geaendert)""", f)
            except sqlite3.IntegrityError:
                sets = ", ".join(f"{k}=:{k}" for k in
                                 ("name", "schulform", "bezirk", "ortsteil", "plz",
                                  "strasse", "email", "website", "schulzweig_id",
                                  "notiz", "zuletzt_geaendert"))
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

    # --- Change 010: Schul-Recherche (LLM, out-of-band) ---------------------
    def set_schule_recherche(self, bsn: str, status: str, notiz: str | None = None) -> None:
        """Recherche-Stand je Schule (sichtbar im Admin, nie still)."""
        with self._lock:
            self._conn.execute(
                """UPDATE schulen SET recherche_am=?, recherche_status=?,
                   recherche_notiz=?, zuletzt_geaendert=? WHERE bsn=?""",
                (self._jetzt(), status, notiz, self._jetzt(), bsn))
            self._conn.commit()

    def schulen_fuer_recherche(self, limit: int | None = None,
                              nur_bsn: str | None = None,
                              bezirk: str | None = None,
                              schulform: str | None = None,
                              bsn_liste: list[str] | None = None) -> list[dict]:
        """Schulen mit Website; nie geprüfte zuerst, dann die ältesten Prüfungen."""
        where, args = ["website IS NOT NULL", "TRIM(website) <> ''"], []
        if nur_bsn:
            where.append("bsn = ?")
            args.append(nur_bsn)
        if bsn_liste:
            platzhalter = ",".join("?" * len(bsn_liste))
            where.append(f"bsn IN ({platzhalter})")
            args.extend(list(bsn_liste))
        if bezirk:
            where.append("bezirk = ?")
            args.append(str(bezirk).strip().lower())
        if schulform:
            where.append("schulform = ?")
            args.append(schulform)
        sql = ("SELECT * FROM schulen WHERE " + " AND ".join(where) +
               " ORDER BY (recherche_am IS NOT NULL), recherche_am, name")
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def log_recherche_lauf(self, eintrag: dict) -> int:
        """Eine Zeile je geprüfter Seite — auch für verworfene Funde (Provenienz)."""
        felder = {k: eintrag.get(k) for k in (
            "bsn", "url", "seiten_hash", "modell", "n_roh", "n_belegt",
            "verworfen_grund", "dauer_s", "erstellt_am")}
        felder["erstellt_am"] = felder["erstellt_am"] or self._jetzt()
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO schul_recherche_lauf(bsn, url, seiten_hash, modell,
                   n_roh, n_belegt, verworfen_grund, dauer_s, erstellt_am)
                   VALUES (:bsn,:url,:seiten_hash,:modell,:n_roh,:n_belegt,
                           :verworfen_grund,:dauer_s,:erstellt_am)""", felder)
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def list_recherche_lauf(self, bsn: str | None = None, limit: int = 50) -> list[dict]:
        args: list = []
        sql = "SELECT * FROM schul_recherche_lauf"
        if bsn:
            sql += " WHERE bsn=?"
            args.append(bsn)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def termin_manuell_vorhanden(self, bsn: str, start_datum: str, titel: str) -> bool:
        """Dubletten-Schutz: gleiche Schule + Datum + Titelnormalform."""
        with self._lock:
            r = self._conn.execute(
                """SELECT id FROM termine_manuell
                   WHERE schule_bsn=? AND start_datum=? AND LOWER(TRIM(titel))=?""",
                (bsn, start_datum, titel.strip().lower())).fetchone()
        return r is not None

    def recherche_uebersicht(self, *, nur_ohne_fund: bool = False,
                             limit: int = 500, bezirk: str | None = None,
                             schulform: str | None = None) -> dict:
        """Recherche-Stand aller Schulen + letzter Lauf je Schule (Admin-Ansicht)."""
        where = ["s.website IS NOT NULL", "TRIM(s.website) <> ''"]
        args: list = []
        if nur_ohne_fund:
            where.append("(s.recherche_status IS NULL OR s.recherche_status <> 'gefunden')")
        if bezirk:
            where.append("s.bezirk = ?")
            args.append(str(bezirk).strip().lower())
        if schulform:
            where.append("s.schulform = ?")
            args.append(schulform)
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT s.bsn, s.name, s.schulform, s.bezirk, s.website,
                           s.recherche_am, s.recherche_status, s.recherche_notiz,
                           (SELECT COUNT(*) FROM termine_manuell t
                             WHERE t.schule_bsn = s.bsn AND t.status='ungeprueft') AS n_offen,
                           (SELECT l.url FROM schul_recherche_lauf l
                             WHERE l.bsn = s.bsn ORDER BY l.id DESC LIMIT 1) AS letzte_url,
                           (SELECT l.verworfen_grund FROM schul_recherche_lauf l
                             WHERE l.bsn = s.bsn ORDER BY l.id DESC LIMIT 1) AS letzter_grund
                    FROM schulen s
                    WHERE {' AND '.join(where)}
                    ORDER BY (s.recherche_am IS NOT NULL), s.recherche_am, s.name
                    LIMIT ?""", (*args, int(limit))).fetchall()
            laeufe = self._conn.execute(
                "SELECT * FROM schul_recherche_lauf ORDER BY id DESC LIMIT 1").fetchone()
        return {"schulen": [dict(r) for r in rows],
                "letzter_lauf": dict(laeufe) if laeufe else None}

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
