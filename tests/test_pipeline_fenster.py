"""Pipeline-Zeitfenster: harter 3-Wochen-Horizont (User-Vorgabe)."""
from datetime import datetime, timedelta

from app.model import TZ_BERLIN
from app.pipeline import _fenster_grenzen, _im_fenster


def test_fenster_grenzen_21_tage():
    jetzt = datetime(2026, 9, 6, 21, 0, tzinfo=TZ_BERLIN)
    von, bis = _fenster_grenzen(jetzt, 21)
    assert von == datetime(2026, 9, 6, 0, 0, tzinfo=TZ_BERLIN)
    # bis = heute + 22 Tage 23:59:59 (21 volle Tage ab heute 00:00)
    assert bis == datetime(2026, 9, 28, 23, 59, 59, tzinfo=TZ_BERLIN)


def test_im_fenster_inklusive_grenzen():
    von = datetime(2026, 9, 6, 0, 0, tzinfo=TZ_BERLIN)
    bis = datetime(2026, 9, 28, 23, 59, tzinfo=TZ_BERLIN)
    assert _im_fenster(von, von, bis)
    assert _im_fenster(bis, von, bis)
    assert _im_fenster(datetime(2026, 9, 7, 9, 0, tzinfo=TZ_BERLIN), von, bis)
    # außerhalb: gestern und jenseits des Horizonts
    assert not _im_fenster(von - timedelta(minutes=1), von, bis)
    assert not _im_fenster(datetime(2026, 9, 29, 0, 0, tzinfo=TZ_BERLIN), von, bis)
    # vergangene Streudaten (z. B. 01.08.2025) fallen raus
    assert not _im_fenster(datetime(2025, 8, 1, 10, 0, tzinfo=TZ_BERLIN), von, bis)


def test_fenster_nahtlos_ueber_tag():
    """Heute 23:59 liegt im Fenster, morgen 00:00 auch (21-Tage-Fenster)."""
    jetzt = datetime(2026, 9, 6, 23, 59, tzinfo=TZ_BERLIN)
    von, bis = _fenster_grenzen(jetzt, 21)
    assert _im_fenster(jetzt, von, bis)
    assert _im_fenster(datetime(2026, 9, 27, 23, 0, tzinfo=TZ_BERLIN), von, bis)
    assert not _im_fenster(datetime(2026, 9, 29, 0, 0, tzinfo=TZ_BERLIN), von, bis)
