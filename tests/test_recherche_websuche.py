"""Change 012: Brave-Websuche — Kontingent, Rate Limit, Fehler, Fallback im Lauf.

Brave-Tarif (offizielle Preisseite, abgerufen 13.09.2026): 5 $ je 1.000 Anfragen,
5 $ Gratis-Guthaben je Monat → 1.000 Anfragen. Überschreitung läuft gegen
hinterlegtes Guthaben, deshalb muss HIER hart gestoppt werden.
"""
import json
from datetime import date, datetime
import inspect

import httpx
import pytest

from app.model import TZ_BERLIN
from app.recherche import kern, websearch
from app.store import Store

TREFFER = {"web": {"results": [
    {"url": "https://www.fremdblog.de/offener-tag"},
    {"url": "https://www.schul.example.org/tag-der-offenen-tuer-am-18-9-2026"},
    {"url": "https://www.schul.example.org/"},
    {"url": "https://www.schul.example.org/", "titel": "doppelt"},
    {"url": "https://www.bezirk.example.org/termine"},
]}}


def _store(tmp_path, **settings):
    s = Store(tmp_path / "brave.db")
    s.set_setting("brave_api_key", "test-key")
    for k, v in settings.items():
        s.set_setting(k, str(v))
    return s


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=TREFFER)


# --- Kontingent ------------------------------------------------------------
def test_kontingent_wird_gezaehlt_und_stoppt_hart(tmp_path):
    s = _store(tmp_path, brave_monat_limit=2, brave_tages_limit=0)
    suche = websearch.BraveSuche(s, websearch.konfiguration(s), client=_client(_ok))
    assert suche.suche("a") and suche.suche("b")
    st = websearch.status(s)
    assert st["verbraucht_monat"] == 2 and st["rest_monat"] == 0
    assert st["kosten_usd"] == 0.01  # 2 × 5 $/1000
    with pytest.raises(websearch.BraveFehler) as e:
        suche.suche("c")
    assert "Monatsbudget aufgebraucht (2/2" in str(e.value)
    assert websearch.status(s)["verbraucht_monat"] == 2  # kein Aufruf draufgegangen
    s.close()


def test_tagesbudget_stoppt_und_nennt_die_zahlen(tmp_path):
    s = _store(tmp_path, brave_monat_limit=100, brave_tages_limit=1)
    suche = websearch.BraveSuche(s, websearch.konfiguration(s), client=_client(_ok))
    suche.suche("a")
    with pytest.raises(websearch.BraveFehler) as e:
        suche.suche("b")
    assert "Tagesbudget erreicht (1/1" in str(e.value)
    assert websearch.status(s)["verbraucht_monat"] == 1
    s.close()


def test_tageszaehler_und_verbrauch_rechnen_in_berliner_zeit(tmp_path):
    """Ursache 2026-09-14: `date.today()` (Systemzeit = UTC) gegen das Berliner
    Datum im Verbrauch — nachts zählte der Tageszähler 0 und das TAGESBUDGET
    griff nicht (echtes Guthaben war ungeschützt). Beide Seiten müssen
    dasselbe Datum benutzen; dieser Vergleich gilt zu jeder Uhrzeit.
    """
    s = _store(tmp_path, brave_monat_limit=100, brave_tages_limit=30)
    assert websearch.heute_berlin() == datetime.now(TZ_BERLIN).date()
    assert s.brave_verbrauch()["tag"] == websearch.heute_berlin().strftime("%Y-%m-%d")
    assert websearch.monat() == datetime.now(TZ_BERLIN).strftime("%Y-%m")
    # Der Vorgabewert der Suche muss die Berliner Uhr sein, nicht die Systemuhr.
    vorgabe = inspect.signature(websearch.BraveSuche.__init__).parameters["heute_fn"]
    assert vorgabe.default is websearch.heute_berlin
    s.close()


def test_monatswechsel_setzt_das_kontingent_zurueck(tmp_path):
    s = _store(tmp_path, brave_monat_limit=2, brave_tages_limit=0)
    s.starte_brave_aufruf("2026-08", "alte Anfrage")      # Vormonat
    assert websearch.status(s, heute=date(2026, 9, 13))["verbraucht_monat"] == 0
    assert websearch.status(s, heute=date(2026, 9, 13))["verbraucht_gesamt"] == 1
    suche = websearch.BraveSuche(s, websearch.konfiguration(s), client=_client(_ok),
                                 heute_fn=lambda: date(2026, 9, 13))
    suche.suche("neu")
    assert websearch.status(s, heute=date(2026, 9, 13))["verbraucht_monat"] == 1
    s.close()


def test_ohne_key_wird_nicht_gesucht(tmp_path):
    s = Store(tmp_path / "kein.db")
    assert "Kein Brave-API-Key" in websearch.budget_fehler(websearch.status(s))
    with pytest.raises(websearch.BraveFehler):
        websearch.BraveSuche(s, websearch.konfiguration(s), client=_client(_ok)).suche("a")
    s.close()


def test_fehlgeschlagener_aufruf_zaehlt_als_reservierung(tmp_path):
    """Absturz mitten im Request darf das Kontingent nicht 'vergessen'."""
    def kaputt(request):
        raise httpx.ConnectError("kein Netz")

    s = _store(tmp_path)
    with pytest.raises(websearch.BraveFehler) as e:
        websearch.BraveSuche(s, websearch.konfiguration(s),
                             client=_client(kaputt)).suche("a")
    assert "nicht erreichbar" in str(e.value)
    v = s.brave_verbrauch()
    assert v["monat_anzahl"] == 1 and v["fehler_monat"] == 1
    assert "kein Netz" in s.brave_letzte(1)[0]["fehler"]
    s.close()


# --- Rate Limit und Fehlerbehandlung ---------------------------------------
def test_rate_limit_haelt_den_abstand_ein(tmp_path, monkeypatch):
    """Abstand wird eingehalten — mit einer Uhr NUR im Modul websearch.

    (Früher wurde das globale time-Modul gepatcht; das leckte in andere Tests.)
    """
    import types
    geschlafen: list[float] = []
    uhr = {"t": 100.0}
    monkeypatch.setattr(websearch, "time", types.SimpleNamespace(
        monotonic=lambda: uhr["t"], sleep=lambda s: geschlafen.append(s)))
    s = _store(tmp_path, brave_anfragen_pro_s=2)  # 0,5 s Abstand
    suche = websearch.BraveSuche(s, websearch.konfiguration(s), client=_client(_ok))
    suche.suche("a")
    suche.suche("b")
    assert geschlafen, "zweiter Aufruf wurde nicht gedrosselt"
    assert all(0 < w <= 0.5 for w in geschlafen)
    s.close()


def test_429_wird_einmal_wiederholt_und_nur_einmal_gezaehlt(tmp_path):
    versuche = {"n": 0}

    def handler(request):
        versuche["n"] += 1
        if versuche["n"] == 1:
            return httpx.Response(429, text="too many requests")
        return httpx.Response(200, json=TREFFER)

    s = _store(tmp_path, brave_anfragen_pro_s=50)
    daten = websearch.BraveSuche(s, websearch.konfiguration(s),
                                 client=_client(handler)).suche("a")
    assert versuche["n"] == 2 and daten == TREFFER
    assert s.brave_verbrauch()["monat_anzahl"] == 1, "Wiederholung darf kein Budget kosten"
    s.close()


def test_dauerhafte_429_meldet_klartext(tmp_path):
    s = _store(tmp_path, brave_anfragen_pro_s=50)
    with pytest.raises(websearch.BraveFehler) as e:
        websearch.BraveSuche(s, websearch.konfiguration(s),
                             client=_client(lambda r: httpx.Response(429))).suche("a")
    assert "drosselt (429)" in str(e.value)
    s.close()


def test_falscher_key_und_fehlendes_guthaben_melden_klartext(tmp_path):
    for code, erwartet in ((401, "abgelehnt"), (403, "abgelehnt"), (402, "Guthaben")):
        (tmp_path / str(code)).mkdir(exist_ok=True)
        s = _store(tmp_path / str(code), brave_anfragen_pro_s=50)
        with pytest.raises(websearch.BraveFehler) as e:
            websearch.BraveSuche(s, websearch.konfiguration(s),
                                 client=_client(lambda r, c=code: httpx.Response(c, text="x"))
                                 ).suche("a")
        assert erwartet in str(e.value)
        assert s.brave_letzte(1)[0]["fehler"]
        s.close()


def test_treffer_sortierung_eigene_domain_zuerst(tmp_path):
    urls = websearch.ergebnis_urls(TREFFER, domain="schul.example.org")
    assert urls[0].endswith("/tag-der-offenen-tuer-am-18-9-2026")
    assert urls[1] == "https://www.schul.example.org/"      # Dublette entfernt
    assert "fremdblog" in urls[2] and len(urls) == 4
    s = _store(tmp_path)
    assert websearch.ergebnis_urls(TREFFER, domain=None)[0].startswith("https://www.fremdblog")
    s.close()


# --- Fallback im Recherche-Lauf -------------------------------------------
SEITE_OHNE_TERMIN = """<html><body><h1>Grundschule</h1>
<p>Willkommen auf unserer Seite. Kontakt und Impressum.</p></body></html>"""
SEITE_MIT_TERMIN = """<html><body><h1>Tag der offenen Tür am 18.9.2026</h1>
<p>Wir laden herzlich ein: Tag der offenen Tür am 18.09.2026 von 16:00 bis 18:00 Uhr
in der Aula.</p></body></html>"""


class FakeSuche:
    """Wie BraveSuche, aber ohne Netz.

    Mit `store` verbucht sie Aufrufe wie das Original (Reservierung + Abschluss),
    damit Tests die echte Kontingent-Zählung prüfen — ohne Brave anzurufen.
    """

    def __init__(self, ergebnis, store=None):
        self.ergebnis = ergebnis
        self.store = store
        self.aufrufe: list[str] = []

    def suche(self, query, count=5, bsn=None):
        self.aufrufe.append(query)
        aufruf_id = None
        if self.store is not None:
            aufruf_id = self.store.starte_brave_aufruf(
                websearch.monat(date.today()), query, bsn)
        if isinstance(self.ergebnis, Exception):
            if self.store is not None:
                self.store.beende_brave_aufruf(aufruf_id, http_code=0, treffer=0,
                                               fehler=str(self.ergebnis))
            raise self.ergebnis
        if self.store is not None:
            self.store.beende_brave_aufruf(aufruf_id, http_code=200,
                                           treffer=len(websearch.ergebnis_urls(self.ergebnis)),
                                           fehler=None)
        return self.ergebnis


def _schule(store, bsn="02G90", name="Test-Schule", website="https://schul.example.org"):
    store.upsert_schule({"bsn": bsn, "name": name, "schulform": "Grundschule",
                         "bezirk": "friedrichshain-kreuzberg", "website": website})


def _lauf_client(seiten: dict, antwort_termine):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"model": "m", "choices": [{"finish_reason": "stop",
                "message": {"content": json.dumps({"termine": antwort_termine},
                                                  ensure_ascii=False)}}]})
        url = str(request.url)
        for muster, html in sorted(seiten.items(), key=lambda kv: -len(kv[0])):
            if muster in url:
                return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        return httpx.Response(404, text="weg")
    return _client(handler)


def test_websuche_findet_tiefe_unterseite_wenn_eigene_seite_leer(tmp_path):
    """Der gemessene Realfall: die Terminseite liegt unter einer tiefen URL."""
    s = _store(tmp_path)
    _schule(s)
    suche = FakeSuche(TREFFER)
    zusammen = kern.lauf(s, limit=1, dry_run=False, suche=suche,
                         client=_lauf_client({"schul.example.org": SEITE_OHNE_TERMIN,
                                              "tag-der-offenen-tuer-am-18-9-2026": SEITE_MIT_TERMIN},
                                             [{"titel": "Tag der offenen Tür",
                                               "datum": "18.09.2026", "zeit": "16:00",
                                               "beleg":
                                                   "Tag der offenen Tür am 18.09.2026 von 16:00 bis 18:00 Uhr"}]))
    assert suche.aufrufe, "Websuche wurde nicht als Fallback benutzt"
    assert zusammen["websuche_anfragen"] >= 1
    assert zusammen["status"] == {"gefunden": 1}, zusammen["status"]
    vorschlaege = s.list_termine_manuell(status="ungeprueft")
    assert len(vorschlaege) == 1 and vorschlaege[0]["start_datum"] == "18.09.2026"
    assert "tag-der-offenen-tuer" in vorschlaege[0]["quelle_hinweis"]
    s.close()


def test_keine_websuche_wenn_die_eigene_seite_schon_liefert(tmp_path):
    """Kontingent schonen: Suche nur, wenn die eigenen Seiten leer bleiben."""
    s = _store(tmp_path)
    _schule(s, bsn="02G91")
    suche = FakeSuche(TREFFER)
    zusammen = kern.lauf(s, limit=1, dry_run=False, suche=suche,
                         client=_lauf_client({"schul.example.org": SEITE_MIT_TERMIN},
                                             [{"titel": "Tag der offenen Tür",
                                               "datum": "18.09.2026",
                                               "beleg":
                                                   "Tag der offenen Tür am 18.09.2026 von 16:00 bis 18:00 Uhr"}]))
    assert suche.aufrufe == [], "Websuche lief, obwohl die Schul-Seite den Termin hatte"
    assert zusammen["websuche_anfragen"] == 0 and zusammen["status"] == {"gefunden": 1}
    s.close()


def test_aufgebrauchtes_budget_ist_an_der_schule_sichtbar(tmp_path):
    """Kein stiller Ausfall: der Grund steht an der Schule."""
    s = _store(tmp_path)
    _schule(s, bsn="02G92")
    suche = FakeSuche(websearch.BraveFehler("Monatsbudget aufgebraucht (900/900 Anfragen) "
                                            "— Websuche pausiert bis zum Monatswechsel."))
    zusammen = kern.lauf(s, limit=1, dry_run=True, suche=suche,
                         client=_lauf_client({"schul.example.org": SEITE_OHNE_TERMIN}, []))
    assert zusammen["websuche_fehler"] == 1
    assert "Monatsbudget aufgebraucht" in zusammen["schulen"][0]["grund"]
    assert zusammen["schulen"][0]["websuche"]["fehler"].startswith("Monatsbudget")
    s.close()


def test_wiederholung_schuetzt_das_kontingent(tmp_path):
    """Dieselbe Schule wird nicht täglich erneut gesucht (Kontingent-Schutz)."""
    s = _store(tmp_path, brave_wiederholung_tage=30)
    _schule(s, bsn="02G94")
    suche = FakeSuche(TREFFER, store=s)
    client = _lauf_client({"schul.example.org": SEITE_OHNE_TERMIN}, [])
    kern.lauf(s, limit=1, dry_run=True, suche=suche, client=client)
    # Treffer auf der Schul-Domain im ersten Ergebnis → zweite Frage entfällt
    assert len(suche.aufrufe) == 1, "erster Lauf soll fragen"
    assert s.brave_verbrauch()["monat_anzahl"] == 1

    # zweiter Lauf: gleiche Schule, gleicher Tag → kein einziger Aufruf
    zusammen = kern.lauf(s, limit=1, dry_run=True, suche=suche, client=client)
    assert len(suche.aufrufe) == 1, "zweiter Lauf hat erneut Kontingent verbraucht"
    assert "vor 0 Tagen" in zusammen["schulen"][0]["grund"]
    assert s.brave_verbrauch()["monat_anzahl"] == 1

    # 0 Tage = bewusst jedes Mal suchen
    s.set_setting("brave_wiederholung_tage", "0")
    kern.lauf(s, limit=1, dry_run=True, suche=suche, client=client)
    assert len(suche.aufrufe) == 2
    s.close()


def test_wiederholungsgrenze_laeuft_ab(tmp_path):
    from datetime import date, timedelta
    s = _store(tmp_path, brave_wiederholung_tage=30)
    k = websearch.konfiguration(s)
    assert websearch.zuletzt_gesucht(s, "02G95", k) is None          # nie gesucht
    s.starte_brave_aufruf("2026-01", "q", bsn="02G95")
    assert websearch.zuletzt_gesucht(s, "02G95", k, heute=date.today()) is not None
    k0 = dict(k, brave_wiederholung_tage="0")
    assert websearch.zuletzt_gesucht(s, "02G95", k0) is None
    s.close()


def test_lauf_nutzt_websuche_nur_wenn_aktiviert(tmp_path, monkeypatch):
    """Schalter aus = kein einziger Brave-Aufruf (Kontingent-Schutz)."""
    s = _store(tmp_path, brave_websuche_aktiv=0)
    _schule(s, bsn="02G93")
    gerufen = {"n": 0}
    monkeypatch.setattr(websearch, "BraveSuche",
                        lambda *a, **k: gerufen.__setitem__("n", gerufen["n"] + 1))
    kern.lauf(s, limit=1, dry_run=True,
              client=_lauf_client({"schul.example.org": SEITE_OHNE_TERMIN}, []))
    assert gerufen["n"] == 0
    s.set_setting("brave_websuche_aktiv", "1")
    kern.lauf(s, limit=1, dry_run=True,
              client=_lauf_client({"schul.example.org": SEITE_OHNE_TERMIN}, []))
    assert gerufen["n"] == 1
    s.close()
