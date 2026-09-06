"""Scheduler: Berechnung des nächsten Tageszeitpunkts (Europe/Berlin)."""
from datetime import datetime, timedelta, timezone

from app.main import SCRAPE_AT_DEFAULT, _naechster_zeitpunkt

# UTC-Grenzfälle zu Europe/Berlin (Sommerzeit +02:00, Winterzeit +01:00)


def test_naechster_zeitpunkt_spaeter_am_tag():
    """06:00 UTC (08:00 Berlin) → nächster 05:30-Berlin-Termin ist morgen."""
    jetzt = datetime(2026, 9, 6, 6, 0, tzinfo=timezone.utc)  # Sommerzeit
    n = _naechster_zeitpunkt(jetzt, "05:30")
    # Morgen 03:30 UTC = 05:30 Berlin
    assert n == datetime(2026, 9, 7, 3, 30, tzinfo=timezone.utc)


def test_naechster_zeitpunkt_frueher_am_tag():
    """02:00 UTC (04:00 Berlin) → 05:30 Berlin ist heute, 03:30 UTC."""
    jetzt = datetime(2026, 9, 6, 2, 0, tzinfo=timezone.utc)
    n = _naechster_zeitpunkt(jetzt, "05:30")
    assert n == datetime(2026, 9, 6, 3, 30, tzinfo=timezone.utc)


def test_naechster_zeitpunkt_winterzeit():
    """Winterzeit (+01:00): 05:30 Berlin = 04:30 UTC; vor 04:30 UTC → heute."""
    jetzt = datetime(2026, 12, 6, 2, 0, tzinfo=timezone.utc)
    n = _naechster_zeitpunkt(jetzt, "05:30")
    assert n == datetime(2026, 12, 6, 4, 30, tzinfo=timezone.utc)


def test_naechster_zeitpunkt_genau_um_die_uhrzeit():
    """Genau 03:30 UTC (05:30 Berlin): Termin wäre <= jetzt → morgen."""
    jetzt = datetime(2026, 9, 6, 3, 30, tzinfo=timezone.utc)
    n = _naechster_zeitpunkt(jetzt, "05:30")
    assert n == datetime(2026, 9, 7, 3, 30, tzinfo=timezone.utc)


def test_ungueltige_uhrzeit_wirft():
    import pytest
    jetzt = datetime(2026, 9, 6, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        _naechster_zeitpunkt(jetzt, "25:99")
    with pytest.raises(ValueError):
        _naechster_zeitpunkt(jetzt, "fuenf")


def test_default_ist_morgens():
    """Standard-Uhrzeit existiert und liegt im erwarteten Format."""
    assert SCRAPE_AT_DEFAULT == "05:30"
    h, m = (int(x) for x in SCRAPE_AT_DEFAULT.split(":"))
    assert 0 <= h <= 23 and 0 <= m <= 59
