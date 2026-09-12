"""Pipeline: amtliche Adress-Geokodierung greift AUCH ohne Venue-Namen.

Realer Befund 2026-09-12 (Kinderkulturkalender): 125 von 211 Events ohne
Koordinaten, obwohl die Adresse im Datensatz stand — die Geokodierung hing
am Ortsfeld, das die Quelle nur als „Ohne Angabe“/„Berlin“ liefert.
"""
from datetime import datetime

import app.pipeline as pl
from app.model import TZ_BERLIN, make_event_id
from app.store import Store

JETZT = datetime(2026, 9, 12, 12, 0, tzinfo=TZ_BERLIN)


class _FakeAdapter:
    """Liefert genau ein Event; kein Netz, kein Detail-Fetch."""
    name = "kinderkulturkalender"
    min_interval_s = 0.0
    horizont_tage = 21
    braucht_detail = False
    robots_policy = "test"

    def __init__(self, ort: str, adresse: str | None):
        self._ort = ort
        self._adresse = adresse

    def fetch_listing_page(self, page: int) -> str:
        return "<html></html>" if page == 0 else ""

    def parse_listing(self, html: str) -> list[dict]:
        if not html:
            return []
        return [{"slug": "test-event", "url": "https://example.org/angebot/test-event",
                 "titel": "Testangebot", "start": datetime(2026, 9, 20, 15, 0, tzinfo=TZ_BERLIN),
                 "ende": datetime(2026, 9, 20, 16, 0, tzinfo=TZ_BERLIN),
                 "ganztags": False, "ort": self._ort, "beschreibung_kurz": None,
                 "adresse": self._adresse, "bezirk": None}]

    def parse_detail(self, html: str) -> dict:
        return {}

    def drain_warnungen(self) -> list[str]:
        return []

    def zu_event(self, row: dict, detail: dict | None, jetzt: datetime) -> dict:
        seid = f"{row['slug']}#1"
        return {
            "id": make_event_id(self.name, seid), "titel": row["titel"],
            "beschreibung_kurz": None,
            "start_iso": row["start"].isoformat(), "ende_iso": row["ende"].isoformat(),
            "start_local": row["start"].strftime("%Y-%m-%dT%H:%M:%S"),
            "ende_local": row["ende"].strftime("%Y-%m-%dT%H:%M:%S"),
            "ganztags": False, "ort": row["ort"], "adresse": row.get("adresse"),
            "bezirk": None, "lat": None, "lon": None, "kostenlos": None,
            "quelle": self.name, "source_event_id": seid,
            "source_url": row["url"], "geholt_am": jetzt.isoformat(),
        }

    def close(self):
        pass


def _lauf(tmp_path, monkeypatch, ort, adresse):
    store = Store(tmp_path / "events.db")
    store.seed_default_sources()
    aufrufe: dict = {}

    def fake_adresse(store_, adresse_, client=None, **kw):
        aufrufe["adresse"] = adresse_
        return {"lat": 52.5, "lon": 13.4, "bezirk": "mitte", "adresse": adresse_}

    def fake_ort(store_, ort_, client=None, **kw):
        aufrufe["ort"] = ort_
        return {"lat": 52.5, "lon": 13.4, "bezirk": "mitte", "adresse": None}

    monkeypatch.setattr(pl, "build_adapter", lambda s, q: _FakeAdapter(ort, adresse))
    monkeypatch.setattr(pl, "adresse_amtlich", fake_adresse)
    monkeypatch.setattr(pl, "ort_koordinaten", fake_ort)
    summary = pl.scrape(store, "kinderkulturkalender", online=True, geo=True, jetzt=JETZT)
    ev = store.query_events({})
    store.close()
    return summary, ev, aufrufe


def test_adresse_wird_geokodiert_ohne_venue_namen(tmp_path, monkeypatch):
    summary, ev, aufrufe = _lauf(tmp_path, monkeypatch, "Ohne Angabe",
                                 "Columbiadamm 84 10965 Berlin")
    assert summary["n_fehler"] == 0
    assert aufrufe.get("adresse") == "Columbiadamm 84 10965 Berlin"
    assert "ort" not in aufrufe          # „Ohne Angabe" NICHT über Nominatim
    assert ev and ev[0]["lat"] == 52.5 and ev[0]["lon"] == 13.4
    assert ev[0]["bezirk"] == "mitte"


def test_ort_berlin_verhindert_die_adress_geokodierung_nicht(tmp_path, monkeypatch):
    _summary, ev, aufrufe = _lauf(tmp_path, monkeypatch, "Berlin",
                                  "Zossener Straße 24 10961 Berlin")
    assert aufrufe.get("adresse") == "Zossener Straße 24 10961 Berlin"
    assert "ort" not in aufrufe
    assert ev[0]["lat"] == 52.5


def test_ohne_adresse_bleibt_reiner_bezirksname_ohne_lookup(tmp_path, monkeypatch):
    _summary, ev, aufrufe = _lauf(tmp_path, monkeypatch, "Pankow", None)
    assert aufrufe == {}                 # kein Adress-, kein Orts-Lookup
    assert ev[0]["lat"] is None


def test_echter_venue_name_laeuft_ueber_nominatim(tmp_path, monkeypatch):
    _summary, ev, aufrufe = _lauf(tmp_path, monkeypatch, "Amerika-Gedenkbibliothek", None)
    assert aufrufe.get("ort") == "Amerika-Gedenkbibliothek"
    assert ev[0]["lat"] == 52.5
