from datetime import datetime, timedelta

from app.enrich import classify_alter, classify_kategorien, classify_kostenlos
from app.model import TZ_BERLIN, iso_utc, make_event_id
from app.validate import validate_event


def test_alter_regeln():
    assert classify_alter("Workshop", "Für Kinder ab 6 Jahren")["altersband_min"] == 6
    assert classify_alter("Fest", "Kinder von 6 bis 10 Jahre")["altersband_max"] == 10
    r = classify_alter("Turnen", "ab 10 Uhr auf dem Hof")  # Uhrzeit, kein Alter
    assert r["altersband_min"] is None
    r = classify_alter("Disco", "U16-Party")
    assert r["altersband_max"] == 16
    r = classify_alter("Picknick", "Ein Fest für die ganze Familie")
    assert r["alters_familie"] is True


def test_kostenlos_regeln():
    assert classify_kostenlos(True, "text") is True
    assert classify_kostenlos(None, "Der Eintritt ist kostenlos.") is True
    assert classify_kostenlos(None, "Tickets ab 12 € an der Kasse") is False
    assert classify_kostenlos(None, "Bunte Aktionen im Park.") is None


def test_kategorien_regeln():
    k = classify_kategorien("Theaterstück für Kinder mit Live-Musik")
    assert "theater" in k and "musik" in k
    assert classify_kategorien("") == []


def _min_ev(**kw):
    ev = {
        "titel": "T", "start_iso": iso_utc(datetime.now(TZ_BERLIN)),
        "ende_iso": None, "ort": "O", "quelle": "jup-berlin",
        "source_url": "https://jup.berlin/events/x",
    }
    ev.update(kw)
    return ev


def test_validate_ok():
    assert validate_event(_min_ev()) == []


def test_validate_pflichtfelder():
    assert validate_event(_min_ev(titel="  ")) != []
    assert validate_event(_min_ev(source_url="keine-url")) != []
    assert validate_event(_min_ev(ort=None)) != []


def test_validate_zeitlogik():
    jetzt = datetime.now(TZ_BERLIN)
    ev = _min_ev(start_iso=iso_utc(jetzt + timedelta(days=2)),
                 ende_iso=iso_utc(jetzt + timedelta(days=1)))
    fehler = validate_event(ev)
    assert any("ende < start" in f or "Zeitlogik" in f for f in fehler)


def test_validate_horizont():
    jetzt = datetime.now(TZ_BERLIN)
    assert validate_event(_min_ev(start_iso=iso_utc(jetzt - timedelta(days=30)))) != []
    assert validate_event(_min_ev(start_iso=iso_utc(jetzt + timedelta(days=500)))) != []
