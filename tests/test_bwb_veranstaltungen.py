r"""Quelle Berliner Wasserbetriebe (bwb.de/de/veranstaltungen.php).

Anlass (2026-09-24, beim Abschluss-Check über alle 17 Quellen): Die Quelle
meldete seit Wochen `anomalie-0-events`. Zwei getrennte Befunde:

1. **Die Quelle ist derzeit wirklich leer.** Alle 23 Einträge der Seite liegen
   in der Vergangenheit (neuester 13.09.2026) — die Berliner Wasser-Mobil-Tour
   läuft Mai..September. `anomalie-0-events` ist hier also RICHTIG und kein
   Defekt (im Unterschied zu industriekultur, wo dieselbe Meldung ein
   301-Umzug war).

2. **Die Regel hatte einen latenten Fehler.** `info-begin` trägt Datum UND
   Uhrzeit („2026-06-06 17:00:00"). Die alte Regel zog per regex nur
   `([0-9]{4}-[0-9]{2}-[0-9]{2})` und formatierte mit '%Y-%m-%d' — die Uhrzeit
   fiel weg, JEDER Termin wäre ganztags geworden, obwohl die Quelle sie nennt.
   Aufgefallen wäre das erst beim Saisonstart 2027. Jetzt: Datum aus `start`,
   Uhrzeit aus `zeit` (dieselbe Zelle), Ende aus `info-end`.

   Bewusst NICHT als Datum+Zeit in EINEM Feld (`format: '%Y-%m-%d %H:%M:%S'`):
   einzelne Einträge der Seite haben GAR KEINE Uhrzeit („2024-04-28"). Ein
   Format, das die Uhrzeit verlangt, würde solche Zeilen komplett verwerfen —
   getrennte Felder lassen sie ganztags, statt sie zu verlieren.
"""
from datetime import datetime
from pathlib import Path

from app.adapters.selector_adapter import SelectorAdapter
from app.model import TZ_BERLIN
from app.quellen_defaults import BWB_REGELN
from app.regeln import validate_regeln_yaml

QUELLE = "bwb-veranstaltungen"
FIXTURE = Path(__file__).parent / "fixtures" / "bwb" / "listing.html"


def _adapter() -> SelectorAdapter:
    return SelectorAdapter(QUELLE, regel_yaml=BWB_REGELN)


def test_regeln_sind_pruefbar():
    assert validate_regeln_yaml(BWB_REGELN, QUELLE) == []


def test_uhrzeit_und_ende_werden_gelesen():
    """12:00 statt 00:00 — sonst gälte der Termin als ganztägig."""
    rows = {r["titel"]: r for r in _adapter().parse_listing(
        FIXTURE.read_text(encoding="utf-8"))}
    r = rows["Berliner Wasser Mobil Tour 2026"]
    assert r["start"] == datetime(2026, 5, 9, 12, 0, tzinfo=TZ_BERLIN), r["start"]
    assert r["ende"] == datetime(2026, 5, 9, 19, 0, tzinfo=TZ_BERLIN), r["ende"]
    assert not r["ganztags"], r


def test_eintrag_ohne_uhrzeit_bleibt_ganztags_statt_zu_fehlen():
    """Das Fixture enthält einen echten Eintrag ohne Uhrzeit — er darf nicht
    verschwinden, nur weil die Zeit fehlt (deshalb getrennte Felder statt
    eines Formats '%Y-%m-%d %H:%M:%S' für beide)."""
    rows = _adapter().parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert len(rows) == 2, rows
    ohne = [r for r in rows if r["titel"] == "Berliner Wassermobil on Tour"]
    assert len(ohne) == 1, rows
    assert ohne[0]["start"].hour == 0 and ohne[0]["start"].minute == 0, ohne[0]
    assert ohne[0]["ganztags"], ohne[0]
    # Ganztägig bekommt ein Tagesende 23:59 — nicht None (so filtert die App
    # den Tag korrekt) und nicht der Endzeitpunkt 00:00.
    assert ohne[0]["ende"] == datetime(2024, 4, 28, 23, 59, tzinfo=TZ_BERLIN), ohne[0]


def test_alte_regel_haette_die_zeit_verloren():
    """Der Beweis, dass die Änderung wirkt: mit dem alten Feldaufbau
    (`format: '%Y-%m-%d'` direkt auf der Zelle, ohne `zeit`) kommt 00:00."""
    alt = BWB_REGELN.replace(
        "    zeit: {css: '.info-begin', regex: '([0-9]{2}:[0-9]{2})', format: '%H:%M'}\n", "")
    rows = {r["titel"]: r for r in SelectorAdapter(QUELLE, regel_yaml=alt)
            .parse_listing(FIXTURE.read_text(encoding="utf-8"))}
    assert rows["Berliner Wasser Mobil Tour 2026"]["start"].hour == 0
