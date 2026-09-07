import sqlite3
import json
con = sqlite3.connect('/data/events.db')
con.row_factory = sqlite3.Row
# Alle SenBJF-Events + ihre geholt_am-Verläufe ansehen
rows = con.execute("SELECT id, titel, start_iso, geholt_am, lat, lon, bezirk, "
                   "altersband_min, altersband_max, kostenlos, kategorien, ort "
                   "FROM events WHERE quelle='berlin-senbjf-kalender'").fetchall()
for r in rows:
    print(dict(r))
print("---runs:")
for r in con.execute("SELECT id, started_at, n_neu, n_geaendert, n_fehler FROM runs WHERE quelle='berlin-senbjf-kalender' ORDER BY id").fetchall():
    print(dict(r))
