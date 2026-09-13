"""Change 010: Extraktionskern mit Belegprüfung (deterministisch vor dem LLM)."""
import json
from datetime import date

import httpx
import pytest

from app.recherche import fetch, kern
from app.store import Store

SEITE_ELIASHOF = """
<html><head><title>Termine</title><script>var x=1;</script></head>
<body><nav>Startseite | Kontakt</nav>
<h1>Termine im Schuljahr 2026/27</h1>
<p>Tag der offenen Tür am 17.09.2026 von 09:30 bis 11:30 Uhr</p>
<p>Herbstferien vom 19.10.2026 bis 30.10.2026</p>
</body></html>
"""
SEITE_OHNE_TERMIN = "<html><body><h1>Willkommen</h1><p>Unsere Schule stellt sich vor.</p></body></html>"


def _schule(store, bsn="02G32", name="Grundschule im Eliashof",
            website="https://www.grundschule-im-eliashof.de"):
    store.upsert_schule({"bsn": bsn, "name": name, "schulform": "Grundschule",
                         "bezirk": "friedrichshain-kreuzberg", "website": website})
    return store.get_schule(bsn)


def _client(html_seiten: dict[str, str], llm_text: str) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["temperature"] == 0
            if "chat_template_kwargs" in body:
                assert body["chat_template_kwargs"]["enable_thinking"] is False
            return httpx.Response(200, json={"model": "test-modell", "choices": [
                {"finish_reason": "stop", "message": {"content": llm_text}}]})
        url = str(request.url)
        for url_muster, html in html_seiten.items():
            if url.startswith(url_muster):
                return httpx.Response(200, text=html,
                                      headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- Belegprüfung ----------------------------------------------------------
def test_zitat_muss_im_quelltext_stehen():
    heute = date(2026, 9, 13)
    text = fetch.text_von(SEITE_ELIASHOF)
    gut, grund = kern.pruefe_fund(
        {"titel": "Tag der offenen Tür", "datum": "17.09.2026", "zeit": "09:30",
         "beleg": "Tag der offenen Tür am 17.09.2026 von 09:30 bis 11:30 Uhr"}, text, heute)
    assert grund == "" and gut["titel"] == "Tag der offenen Tür"
    assert gut["start_datum"] == "17.09.2026" and gut["start_zeit"] == "09:30"

    erfunden, grund2 = kern.pruefe_fund(
        {"titel": "Tag der offenen Tür", "datum": "17.09.2026",
         "beleg": "Wir laden herzlich ein zum Schnuppernachmittag"}, text, heute)
    assert erfunden is None and grund2 == "zitat_nicht_belegt"


def test_datum_muss_im_zitat_stehen():
    heute = date(2026, 9, 13)
    text = fetch.text_von(SEITE_ELIASHOF)
    # Klassischer Fehler (real beobachtet): Datum irgendwo von der Seite,
    # Zitat ohne Datum — z. B. Zahlen aus einem Kalender-Widget.
    schlecht, grund = kern.pruefe_fund(
        {"titel": "Tag der offenen Tür", "datum": "25.09.2026",
         "beleg": "Tag der offenen Tür am 17.09.2026 von 09:30 bis 11:30 Uhr"}, text, heute)
    assert schlecht is None and grund == "datum_nicht_im_zitat"

    # Zitat steht im Text, enthält aber kein Datum
    text2 = ("Anmeldung und Tag der offenen Tür finden im Herbst statt. "
             "Tag der offenen Tür am 17.09.2026 ab 09:30 Uhr.")
    ohne, grund2 = kern.pruefe_fund(
        {"titel": "Tag der offenen Tür", "datum": "17.09.2026",
         "beleg": "Anmeldung und Tag der offenen Tür finden im Herbst statt"}, text2, heute)
    assert ohne is None and grund2 == "datum_nicht_im_zitat"


def test_weiter_gueltungen():
    heute = date(2026, 9, 13)
    text = "Tag der offenen Tür am 17.09.2026 von 09:30 bis 11:30 Uhr"
    assert kern.pruefe_fund({"titel": "Elterncafé", "datum": "17.09.2026",
                             "beleg": text}, text, heute)[1] == "titel_unbekannt"
    assert kern.pruefe_fund({"titel": "Tag der offenen Tür", "datum": "17.09.2026",
                             "beleg": "kurz"}, text, heute)[1] == "zitat_zu_kurz"
    assert kern.pruefe_fund({"titel": "Tag der offenen Tür", "datum": "17.09.2026",
                             "zeit": "23:30", "beleg": text}, text, heute)[1] == "zeit_unplausibel"

    alt = "Tag der offenen Tür am 12.09.2026 von 09:30 bis 11:30 Uhr"
    assert kern.pruefe_fund({"titel": "Tag der offenen Tür", "datum": "12.09.2026",
                             "beleg": alt}, alt, heute)[1] == "datum_vergangen"

    # Horizont ist 400 Tage: der nächste Jahrgang (17.09.2027) ist noch erlaubt,
    # ein Datum weit darüber nicht.
    fern = "Tag der offenen Tür am 17.09.2028 von 09:30 bis 11:30 Uhr"
    assert kern.pruefe_fund({"titel": "Tag der offenen Tür", "datum": "17.09.2028",
                             "beleg": fern}, fern, heute)[1] == "datum_ausserhalb_horizont"
    # Unlesbares Datum
    assert kern.pruefe_fund({"titel": "Tag der offenen Tür", "datum": "im Herbst",
                             "beleg": text}, text, heute)[1] == "datum_unlesbar"


def test_datum_im_zitat_monatsschreibweise():
    assert kern.datum_im_zitat("17.09.2026", "Tag der offenen Tür am 17. September 2026")
    assert kern.datum_im_zitat("17.09.2026", "am 17.9. um 9:30 Uhr")
    assert not kern.datum_im_zitat("17.09.2026", "Termine im September 2026")
    assert not kern.datum_im_zitat("", "irgendwas")


def test_titel_vokabular():
    assert kern.titel_aus_vokabular("Tag der offenen Tür für Schulanfänger") == "Tag der offenen Tür"
    assert kern.titel_aus_vokabular("Informationsabend für Eltern") == "Infoabend"
    assert kern.titel_aus_vokabular("Sommerfest") is None


# --- Vorfilter und Fenster -------------------------------------------------
def test_vorfilter_und_fenster():
    text = fetch.text_von(SEITE_ELIASHOF)
    assert fetch.hat_terminindiz(text)
    assert not fetch.hat_terminindiz(fetch.text_von(SEITE_OHNE_TERMIN))
    # Realistische Seite: viel Navigation/Text vor der Terminstelle
    lang = ("Startseite Kontakt Impressum Datenschutz Über uns " * 40) + text
    fenster = fetch.text_fenster(lang)
    assert "17.09.2026" in fenster
    assert len(fenster) < len(lang) / 2
    assert fenster.startswith("Startseite") is False or "17.09.2026" in fenster
    # Ohne Terminstelle mit Datum gibt es kein Fenster → kein LLM-Aufruf
    assert fetch.text_fenster("Tag der offenen Tür — Termin folgt") == ""


def test_kandidatenfiltern_nach_prioritaet():
    html = """<a href="/termine">Termine</a><a href="/tag-der-offenen-tuer">TdOT</a>
              <a href="https://fremde-domain.de/termine">extern</a>
              <a href="/kontakt">Kontakt</a>"""
    links = fetch.kandidaten(html, "https://schule.de/")
    assert links[0] == "https://schule.de/tag-der-offenen-tuer"
    assert "https://fremde-domain.de/termine" not in links
    assert "https://schule.de/kontakt" not in links


# --- Gesamtlauf (Mock: Seite + Modell) ------------------------------------
def test_lauf_schreibt_belegten_vorschlag_in_die_queue(tmp_path):
    store = Store(tmp_path / "kern.db")
    _schule(store)
    llm_text = json.dumps({"termine": [
        {"titel": "Tag der offenen Tür", "datum": "17.09.2026", "zeit": "09:30",
         "beleg": "Tag der offenen Tür am 17.09.2026 von 09:30 bis 11:30 Uhr"},
        {"titel": "Tag der offenen Tür", "datum": "25.09.2026", "zeit": None,
         "beleg": "Herbstferien vom 19.10.2026 bis 30.10.2026"}]})
    client = _client({"https://www.grundschule-im-eliashof.de": SEITE_ELIASHOF}, llm_text)
    zusammen = kern.lauf(store, limit=5, client=client, konfig={"llm_base_url": "http://test/v1",
                                                              "llm_model": "test-modell",
                                                              "llm_extra_json": '{"chat_template_kwargs": {"enable_thinking": false}}'})
    assert zusammen["geprueft"] == 1 and zusammen["belegt"] == 1 and zusammen["llm_calls"] == 1
    assert zusammen["verworfen"] == {"datum_nicht_im_zitat": 1}
    termine = store.list_termine_manuell()
    assert len(termine) == 1
    t = termine[0]
    assert t["status"] == "ungeprueft" and t["start_datum"] == "17.09.2026"
    assert "LLM-Recherche" in t["quelle_hinweis"] and "Zitat" in t["quelle_hinweis"]
    # Nichts davon ist öffentlich (kein bestätigter Termin)
    assert store.count_events() == 0
    # Stand + Protokollzeile sind sichtbar
    sch = store.get_schule("02G32")
    assert sch["recherche_status"] == "gefunden" and sch["recherche_am"]
    assert store.list_recherche_lauf("02G32")[0]["n_belegt"] == 1
    store.close()


def test_zweiter_lauf_legt_keine_dublette_an(tmp_path):
    store = Store(tmp_path / "dub.db")
    _schule(store)
    llm_text = json.dumps({"termine": [
        {"titel": "Tag der offenen Tür", "datum": "17.09.2026", "zeit": "09:30",
         "beleg": "Tag der offenen Tür am 17.09.2026 von 09:30 bis 11:30 Uhr"}]})
    konfig = {"llm_base_url": "http://test/v1", "llm_model": "m", "llm_extra_json": "{}"}
    for _ in range(2):
        kern.lauf(store, limit=5, client=_client(
            {"https://www.grundschule-im-eliashof.de": SEITE_ELIASHOF}, llm_text), konfig=konfig)
    assert len(store.list_termine_manuell()) == 1
    store.close()


def test_schule_ohne_indiz_bekommt_keinen_llm_aufruf(tmp_path):
    store = Store(tmp_path / "leer.db")
    _schule(store, bsn="02G99", name="Schule ohne Termine",
            website="https://leer.example.org")
    aufrufe = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            aufrufe["n"] += 1
            return httpx.Response(500, text="darf nicht passieren")
        return httpx.Response(200, text=SEITE_OHNE_TERMIN,
                              headers={"content-type": "text/html"})

    zusammen = kern.lauf(store, limit=5,
                         client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert aufrufe["n"] == 0 and zusammen["llm_calls"] == 0
    assert zusammen["status"] == {"keinIndiz": 1}
    assert store.get_schule("02G99")["recherche_status"] == "keinIndiz"
    store.close()


def test_abruf_fehler_und_fehlender_website_eintrag(tmp_path):
    store = Store(tmp_path / "fehler.db")
    _schule(store, bsn="02G98", name="Blockierte Schule", website="https://blockiert.example.org")
    store.upsert_schule({"bsn": "02G97", "name": "Ohne Website", "schulform": "Grundschule"})

    def handler(request):
        return httpx.Response(503, text="bot protection")

    zusammen = kern.lauf(store, limit=10,
                         client=httpx.Client(transport=httpx.MockTransport(handler)))
    status = {s["bsn"]: s for s in zusammen["schulen"]}
    # Nur Schulen MIT Website werden geprüft — ohne Website ist keine Recherche möglich
    assert "02G98" in status and status["02G98"]["status"] == kern.STATUS_ABRUF
    assert "HTTP 503" in status["02G98"]["grund"]
    assert zusammen["fehler"] == 1
    assert store.get_schule("02G98")["recherche_status"] == "abrufFehler"
    store.close()


def test_llm_liefert_html_statt_json(tmp_path):
    """Ein Proxy-Fehlerseite statt JSON muss ein klarer LLM-Fehler sein."""
    store = Store(tmp_path / "html.db")
    _schule(store, bsn="02G54", name="Schule", website="https://html.example.org")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, text="<html>Bad Gateway</html>",
                                  headers={"content-type": "text/html"})
        return httpx.Response(200, text=SEITE_ELIASHOF, headers={"content-type": "text/html"})

    zusammen = kern.lauf(store, limit=1, konfig={
        "llm_base_url": "http://test/v1", "llm_model": "m", "llm_extra_json": "{}"},
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert zusammen["status"] == {"fehler": 1}
    assert "kein JSON" in zusammen["schulen"][0]["grund"]
    store.close()


def test_llm_fehler_wird_zur_schule_notiz(tmp_path):
    store = Store(tmp_path / "llmfail.db")
    _schule(store, bsn="02G96", name="Langsame Schule", website="https://llm.example.org")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(503, json={"error": {"message": "Loading model"}})
        return httpx.Response(200, text=SEITE_ELIASHOF, headers={"content-type": "text/html"})

    zusammen = kern.lauf(store, limit=5, konfig={
        "llm_base_url": "http://test/v1", "llm_model": "m", "llm_extra_json": "{}"},
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert zusammen["status"] == {"fehler": 1}
    assert "HTTP 503" in zusammen["schulen"][0]["grund"]
    assert store.get_schule("02G96")["recherche_status"] == "fehler"
    store.close()


def test_dry_run_schreibt_nichts(tmp_path):
    store = Store(tmp_path / "dry.db")
    _schule(store)
    llm_text = json.dumps({"termine": [
        {"titel": "Tag der offenen Tür", "datum": "17.09.2026", "zeit": "09:30",
         "beleg": "Tag der offenen Tür am 17.09.2026 von 09:30 bis 11:30 Uhr"}]})
    zusammen = kern.lauf(store, limit=5, dry_run=True, konfig={
        "llm_base_url": "http://test/v1", "llm_model": "m", "llm_extra_json": "{}"},
        client=_client({"https://www.grundschule-im-eliashof.de": SEITE_ELIASHOF}, llm_text))
    assert zusammen["belegt"] == 1 and store.list_termine_manuell() == []
    assert store.get_schule("02G32")["recherche_status"] is None
    store.close()


def test_schulen_ohne_website_werden_uebersprungen(tmp_path):
    store = Store(tmp_path / "nur_website.db")
    store.upsert_schule({"bsn": "02G95", "name": "Ohne Website", "schulform": "Grundschule"})
    assert store.schulen_fuer_recherche() == []
    store.close()


def test_dreckige_website_wird_gesaeubert(tmp_path):
    """WFS-Stamm liefert Websites mit Steuerzeichen — real brach das den Lauf ab."""
    assert fetch.url_saeubern("\rhttps://schule.example.org") == "https://schule.example.org"
    assert fetch.url_saeubern("  www.schule.de \n") == "http://www.schule.de"
    assert fetch.url_saeubern("\x00") == ""

    store = Store(tmp_path / "dreck.db")
    store.upsert_schule({"bsn": "02G50", "name": "Schule mit Dreck-URL",
                         "schulform": "Grundschule",
                         "website": "\rhttps://www.grundschule-im-eliashof.de"})
    gesehen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":  # LLM-Aufruf
            return httpx.Response(200, json={"model": "m", "choices": [
                {"finish_reason": "stop", "message": {"content": '{"termine": []}'}}]})
        gesehen.append(str(request.url))
        return httpx.Response(200, text=SEITE_ELIASHOF, headers={"content-type": "text/html"})

    zusammen = kern.lauf(store, limit=1, dry_run=True,
                         client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert gesehen and gesehen[0].startswith("https://www.grundschule-im-eliashof.de")
    assert zusammen["status"] == {"keinFund": 1}, zusammen["status"]
    store.close()


def test_eine_kaputte_schule_stoppt_den_lauf_nicht(tmp_path, monkeypatch):
    """Eine unerwartete Ausnahme darf nicht 34 Schulen abwürgen (real passiert)."""
    store = Store(tmp_path / "weiter.db")
    _schule(store, bsn="02G51", name="Kaputt", website="https://kaputt.example.org")
    _schule(store, bsn="02G52", name="Gut", website="https://gut.example.org")
    echt = kern.verarbeite_schule
    aufrufe = {"n": 0}

    def mit_ausnahme(store_, schule, *a, **k):
        aufrufe["n"] += 1
        if aufrufe["n"] == 1:
            raise UnicodeError("kaputte Zeile")
        return echt(store_, schule, *a, **k)

    monkeypatch.setattr(kern, "verarbeite_schule", mit_ausnahme)
    zusammen = kern.lauf(store, limit=2, dry_run=True,
                         client=httpx.Client(transport=httpx.MockTransport(
                             lambda r: httpx.Response(200, text=SEITE_OHNE_TERMIN,
                                                      headers={"content-type": "text/html"}))))
    assert zusammen["geprueft"] == 2, "Lauf wurde durch eine kaputte Schule beendet"
    assert zusammen["fehler"] == 1 and zusammen["status"].get("keinIndiz") == 1
    assert "kaputte Zeile" in zusammen["schulen"][0]["grund"]
    store.close()
