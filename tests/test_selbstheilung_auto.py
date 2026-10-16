"""Change 028: Selbstheilung mit Automatik, Knopf und Meldung.

Nutzerauftrag (2026-10-16): „Baue den Knopf ein, aber etabliere auch einen
automatischen Modus, der versucht zu reparieren, oder wenn das nicht klappt,
Bescheid sagt."

Diese Datei prüft genau das — und dass dabei NICHTS ohne grünes Gate übernommen
wird, dass eine wirkungslose Reparatur zurückgenommen wird und dass eine
Meldung nie still ausfällt.
"""
import json

from fastapi.testclient import TestClient

from app import selbstheilung as sh
from app.store import Store

Q = "test-quelle"
URL = "https://example.invalid/termine"
JETZT = "2026-09-13T10:00:00+02:00"
FOLGETAG = "2026-09-14T10:00:00+02:00"
CHEF = "chef@example.invalid"

REGELN = f"""quelle: {Q}
listing:
  url: {URL}
  item_css: "article.event"
  felder:
    titel: {{css: "a"}}
    start: {{css: "span.datum", format: "%d.%m.%Y"}}
"""

# Der Umbau der Quelle: gleiche Inhalte, andere Klassen.
HTML_GESUND = "<html><body>" + "".join(
    f'<article class="event"><a href="/e{i}">Fest {i}</a>'
    f'<span class="datum">{i + 1:02d}.09.2026</span></article>' for i in range(5)
) + "</body></html>"

HTML_UMBAU = "<html><body>" + "".join(
    f'<div class="card"><a href="/e{i}">Fest {i}</a>'
    f'<span class="d">{i + 1:02d}.09.2026</span></div>' for i in range(5)
) + "</body></html>"

# Ein Vorschlag, der den Umbau wirklich repariert (5 Treffer, Titel + Start).
NEU = f"""quelle: {Q}
listing:
  url: {URL}
  item_css: "div.card"
  felder:
    titel: {{css: "a"}}
    start: {{css: "span.d", regex: "([0-9]{{2}}[.][0-9]{{2}}[.][0-9]{{4}})", format: "%d.%m.%Y"}}
"""

KONF_AUTO = {"auto": True, "mail_aktiv": True, "mail_an": CHEF, "max_pro_tag": 3}
KONF_VON_HAND = {"auto": False, "mail_aktiv": True, "mail_an": CHEF, "max_pro_tag": 3}


def _store(tmp_path, name="auto.db") -> Store:
    s = Store(tmp_path / name)
    s.add_source(Q, "Test", "regeln", URL)
    s.set_regeln(Q, REGELN)
    return s


def _archiv(s: Store, treffer: int = 5) -> None:
    """Gesunde Seite ins Archiv (Vorbedingung der Regressionsprobe)."""
    sh.pruefen(s, quelle=Q, regeln=REGELN, url=URL, html=HTML_GESUND,
               roh_zeilen=treffer, n_zeilen=treffer, n_fehler=0, jetzt=JETZT)


def _ruf(text: str):
    """LLM-Attrappe; zählt die Aufrufe mit."""
    zaehler = {"n": 0}

    def ruf(prompt: str) -> str:
        zaehler["n"] += 1
        return text

    return ruf, zaehler


def antwort(yaml_text: str, begruendung: str = "Karten tragen jetzt die Klasse card.") -> str:
    return f"{sh.MARKER_AUF}\n{yaml_text}\n{sh.MARKER_ZU}\nBegruendung: {begruendung}"


def _mails():
    sammel: list[dict] = []
    mailer = lambda an, betreff, text: sammel.append(  # noqa: E731
        {"an": an, "betreff": betreff, "text": text})
    return sammel, mailer


def _lauf(s, *, html=HTML_UMBAU, roh=0, n=0, n_warn=0, jetzt=JETZT, konf=None,
          ruft=None, mailer=None, http_fehler=""):
    ruf, _ = ruft or _ruf(antwort(NEU))
    return sh.lauf_auswerten(s, quelle=Q, regeln=REGELN, url=URL, html=html,
                             roh_zeilen=roh, n_zeilen=n, n_warn=n_warn,
                             http_fehler=http_fehler, jetzt=jetzt, llm_ruf=ruf,
                             mailer=mailer, konf=konf or KONF_AUTO)


# --- Automatik -------------------------------------------------------------

def test_automatik_repariert_und_uebernimmt(tmp_path):
    s = _store(tmp_path)
    _archiv(s)
    mails, mailer = _mails()
    aus = _lauf(s, roh=0, n=0, konf=KONF_AUTO, mailer=mailer)

    assert aus["befund"]["art"] == "selektoren_tot"
    assert aus["aktion"]["aktion"] == "uebernommen", aus["aktion"]
    assert aus["aktion"]["regeln_geaendert"] is True
    # Die neuen Regeln sind wirksam ...
    gespeichert = s.get_regeln(Q)["regel_yaml"]
    assert "div.card" in gespeichert and "article.event" not in gespeichert
    # ... und der Fall ist vollständig dokumentiert
    h = s.heilungen_liste(Q)[0]
    assert h["status"] == "angenommen" and h["verursacher"] == "auto"
    assert h["erwartete_treffer"] == 5 and h["uebernommen_am"]
    assert h["benachrichtigt_am"], "Meldung muss raus sein"
    assert h["beleg_json"] and "pruefungen" in h["beleg_json"]
    # Historie trägt die Vorgänger-Fassung (Rücknahme-Grundlage)
    hist = s.regel_historie_liste(Q)
    assert len(hist) == 1 and hist[0]["aktiv"] == 1
    assert "article.event" in hist[0]["alt_yaml"]
    # Meldung gegangen: an die eingestellte Adresse, mit Quelle im Betreff
    assert mails and mails[0]["an"] == CHEF and Q in mails[0]["betreff"]
    assert "repariert" in mails[0]["text"]


def test_rotes_gate_laesst_die_regeln_unveraendert(tmp_path):
    s = _store(tmp_path)
    _archiv(s)
    mails, mailer = _mails()
    kaputt = NEU.replace('item_css: "div.card"', 'item_css: "div.gibtsnicht"')
    ruf, zaehler = _ruf(antwort(kaputt))
    aus = _lauf(s, roh=0, n=0, konf=KONF_AUTO, mailer=mailer, ruft=(ruf, zaehler))

    assert zaehler["n"] == 1, "das Modell wird genau einmal gefragt"
    assert aus["aktion"]["aktion"] == "verworfen"
    assert aus["aktion"]["regeln_geaendert"] is False
    assert s.get_regeln(Q)["regel_yaml"] == REGELN, "Regeln dürfen sich nicht ändern"
    assert s.regel_historie_liste(Q) == [], "ohne Übernahme keine Historie"
    h = s.heilungen_liste(Q)[0]
    assert h["status"] == "verworfen" and "DURCHGEFALLEN" in h["meldung"]
    assert mails and "DURCHGEFALLEN" in mails[0]["text"]


def test_automatik_aus_legt_nur_einen_vorschlag_ab(tmp_path):
    s = _store(tmp_path)
    _archiv(s)
    mails, mailer = _mails()
    aus = _lauf(s, roh=0, n=0, konf=KONF_VON_HAND, mailer=mailer)

    assert aus["aktion"]["aktion"] == "vorgeschlagen"
    assert aus["aktion"]["regeln_geaendert"] is False
    assert s.get_regeln(Q)["regel_yaml"] == REGELN
    h = s.heilungen_liste(Q)[0]
    assert h["status"] == "vorgeschlagen" and h["vorschlag_yaml"]
    assert "bestätigen" in h["meldung"] and mails, "auch ohne Automatik wird gemeldet"


def test_gesperrte_quelle_wird_gemeldet_nicht_repariert(tmp_path):
    s = _store(tmp_path)
    _archiv(s)
    mails, mailer = _mails()
    ruf, zaehler = _ruf(antwort(NEU))
    aus = _lauf(s, roh=0, n=0, konf=KONF_AUTO, mailer=mailer, ruft=(ruf, zaehler),
                html=None, http_fehler="Client error '429 Too Many Requests'")

    assert aus["befund"]["art"] == "gesperrt"
    assert zaehler["n"] == 0, "bei Sperren darf das Modell gar nicht erst gefragt werden"
    assert aus["aktion"]["regeln_geaendert"] is False
    assert s.get_regeln(Q)["regel_yaml"] == REGELN
    assert mails and "nicht reparierbar" in mails[0]["text"]
    # Die Quelle bleibt aktiv — eine stille Abschaltung wäre schlimmer
    assert bool(s.get_source(Q)["aktiv"]) is True


# --- Beobachtung und Rücknahme ---------------------------------------------

def test_wirkungslose_reparatur_wird_zurueckgenommen(tmp_path):
    s = _store(tmp_path)
    _archiv(s)
    _lauf(s, roh=0, n=0, konf=KONF_AUTO, mailer=_mails()[1])
    assert "div.card" in s.get_regeln(Q)["regel_yaml"]

    # Nächster Lauf: die reparierten Regeln finden fast nichts mehr
    mails, mailer = _mails()
    aus = _lauf(s, roh=1, n=1, konf=KONF_AUTO, mailer=mailer)

    assert aus["beobachtung"] and aus["beobachtung"]["rollback"] is True
    assert s.get_regeln(Q)["regel_yaml"] == REGELN, "alte Fassung muss wieder gelten"
    h = s.heilungen_liste(Q)[0]
    assert h["status"] == "zurueckgenommen" and h["pruefung_ergebnis"] == "rollback"
    assert mails and "trägt nicht" in mails[0]["text"]
    # Historie kennt beides: Übernahme und Rücknahme
    assert [z["verursacher"] for z in s.regel_historie_liste(Q)] == ["rollback", "auto"]


def test_nach_der_ruecknahme_pausiert_die_automatik(tmp_path):
    s = _store(tmp_path)
    _archiv(s)
    _lauf(s, roh=0, n=0, konf=KONF_AUTO, mailer=_mails()[1])
    _lauf(s, roh=1, n=1, konf=KONF_AUTO, mailer=_mails()[1])

    # Am Folgetag: kein zweiter automatischer Versuch, aber eine Meldung
    mails, mailer = _mails()
    ruf, zaehler = _ruf(antwort(NEU))
    aus = _lauf(s, roh=0, n=0, jetzt=FOLGETAG, konf=KONF_AUTO, mailer=mailer,
                ruft=(ruf, zaehler))

    assert zaehler["n"] == 0, "nach einer Rücknahme kein neuer Modell-Aufruf"
    assert aus["aktion"]["aktion"] == "uebersprungen"
    assert "pausiert" in aus["aktion"]["meldung"]


def test_tageskontingent_und_ein_versuch_je_quelle(tmp_path):
    s = _store(tmp_path)
    _archiv(s)
    s.add_source("zweite", "Zweite", "regeln", URL)
    s.set_regeln("zweite", REGELN.replace(f"quelle: {Q}", "quelle: zweite"))
    # Ein anderer Fall ist heute schon gelaufen → Kontingent ist erschöpft
    s.heilung_anlegen("zweite", "selektoren_tot", {"art": "selektoren_tot"}, JETZT)
    s.heilung_anlegen("zweite", "selektoren_tot", {"art": "selektoren_tot"}, JETZT)

    ruf, zaehler = _ruf(antwort(NEU))
    aus = _lauf(s, roh=0, n=0, konf={"auto": True, "mail_aktiv": True, "mail_an": CHEF,
                                     "max_pro_tag": 1}, ruft=(ruf, zaehler))

    assert zaehler["n"] == 0 and aus["aktion"]["aktion"] == "uebersprungen"
    assert "Kontingent" in aus["aktion"]["meldung"]
    assert s.get_regeln(Q)["regel_yaml"] == REGELN


def test_zweiter_lauf_am_selben_tag_notiert_nichts_neues(tmp_path):
    s = _store(tmp_path)
    _archiv(s)
    _lauf(s, roh=0, n=0, konf=KONF_VON_HAND, mailer=_mails()[1])
    anzahl = len(s.heilungen_liste(Q))
    _lauf(s, roh=0, n=0, konf=KONF_VON_HAND, mailer=_mails()[1])
    assert len(s.heilungen_liste(Q)) == anzahl


# --- Meldung ---------------------------------------------------------------

def test_mailfehler_ist_sichtbar_und_wird_protokolliert(tmp_path):
    s = _store(tmp_path)
    _archiv(s)

    def kaputter_mailer(an, betreff, text):
        raise RuntimeError("SMTP down")

    aus = _lauf(s, roh=0, n=0, konf=KONF_AUTO, mailer=kaputter_mailer)
    h = s.heilungen_liste(Q)[0]
    assert aus["aktion"]["regeln_geaendert"] is True   # Reparatur gilt trotzdem
    assert h["benachrichtigt_am"] is None              # aber ehrlich: nicht gemeldet
    fehler = s.recent_errors(Q, limit=10)
    assert any("nicht versandt" in f["grund"] for f in fehler), fehler


def test_mail_abgeschaltet_wird_nicht_versucht(tmp_path):
    s = _store(tmp_path)
    _archiv(s)
    mails, mailer = _mails()
    konf = dict(KONF_AUTO, mail_aktiv=False)
    _lauf(s, roh=0, n=0, konf=konf, mailer=mailer)
    assert mails == []
    assert s.heilungen_liste(Q)[0]["benachrichtigt_am"] is None


def test_platzhalter_als_endpunkt_gilt_nicht_als_eingerichtet():
    """Im Repo steht als Voreinstellung ein Platzhalter — der ist keine Adresse."""
    assert sh.llm_bereit({"llm_base_url": "<LLM_BASE_URL>"}) is False
    assert sh.llm_bereit({"llm_base_url": ""}) is False
    assert sh.llm_bereit({}) is False
    assert sh.llm_bereit({"llm_base_url": "http://192.168.178.140:8088/v1"}) is True


def test_ohne_endpunkt_wird_gemeldet_statt_repariert(tmp_path):
    s = _store(tmp_path)
    _archiv(s)
    mails, mailer = _mails()
    # Ohne llm_ruf (also der echte Weg) und ohne Endpunkt in der Datenbank
    aus = sh.lauf_auswerten(s, quelle=Q, regeln=REGELN, url=URL, html=HTML_UMBAU,
                            roh_zeilen=0, n_zeilen=0, jetzt=JETZT, mailer=mailer,
                            konf=KONF_AUTO)

    assert aus["aktion"]["aktion"] == "kein-llm", aus["aktion"]
    assert "kein LLM-Endpunkt" in aus["aktion"]["meldung"]
    assert aus["aktion"]["regeln_geaendert"] is False
    assert s.get_regeln(Q)["regel_yaml"] == REGELN
    assert mails, "auch dieser Fall muss gemeldet werden"


def test_api_meldet_fehlenden_endpunkt(tmp_path):
    s = _store(tmp_path)
    _archiv(s)
    c = _client(tmp_path, s)
    liste = c.get("/api/admin/heilungen").json()
    assert liste["llm_bereit"] is False, "Platzhalter darf nicht als eingerichtet gelten"


# --- Erkennung: Listing-Fehler zählen mit (Change 028) ---------------------
def test_listing_fehler_loesen_jetzt_einen_befund_aus():
    """45.568 solcher Zeilen bei umweltkalender-berlin, aber n_fehler = 0."""
    assert sh.befund_ermitteln(roh_zeilen=100, n_zeilen=100, n_fehler=0,
                               n_warn=1) is None
    b = sh.befund_ermitteln(roh_zeilen=100, n_zeilen=100, n_fehler=0, n_warn=12)
    assert b and b["art"] == "fehlerquote"
    assert b["zahlen"]["n_warn"] == 12 and "Listing-Blöcke" in b["text"]
    # Quote ehrlich gerechnet (Bezug = gelesene Zeilen + Warnungen)
    assert sh.befund_ermitteln(roh_zeilen=100, n_zeilen=100, n_fehler=0,
                               n_warn=8) is None
    assert sh.befund_ermitteln(roh_zeilen=100, n_zeilen=100, n_fehler=9,
                               n_warn=1)["art"] == "fehlerquote"


# --- Handbetrieb: der Knopf ------------------------------------------------

class _FakeAdapter:
    """Ersetzt den echten Adapter: liefert die umgebaute Seite."""

    def __init__(self, rows=5):
        self._listing_url = URL
        self.rows = rows
        self.warnungen: list[str] = []

    def fetch_listing_page(self, page=0):
        return HTML_UMBAU

    def parse_listing(self, html):
        return [{"slug": f"e{i}"} for i in range(self.rows)]

    def drain_warnungen(self):
        raus, self.warnungen = self.warnungen, []
        return raus

    def close(self):
        pass


def test_knopf_reparieren_holt_die_seite_und_uebernimmt(tmp_path, monkeypatch):
    s = _store(tmp_path)
    _archiv(s)
    # Die Quelle liefert seit dem Umbau keine Blöcke mehr → bewiesener Defekt
    adapter = _FakeAdapter(rows=0)
    monkeypatch.setattr("app.adapters.build_adapter", lambda store, quelle: adapter)
    mails, mailer = _mails()

    ergebnis = sh.manuell_versuchen(s, quelle=Q, jetzt=JETZT, mailer=mailer,
                                    konf=KONF_VON_HAND, llm_ruf=_ruf(antwort(NEU))[0])

    assert ergebnis["ok"] is True and ergebnis["aktion"] == "uebernommen", ergebnis
    assert "div.card" in s.get_regeln(Q)["regel_yaml"]
    h = s.heilungen_liste(Q)[0]
    assert h["verursacher"] == "manuell" and h["status"] == "angenommen"


def test_knopf_meldet_wenn_nichts_kaputt_ist(tmp_path, monkeypatch):
    s = _store(tmp_path)
    _archiv(s)
    adapter = _FakeAdapter(rows=5)      # Selektor liest die Blöcke weiter
    monkeypatch.setattr("app.adapters.build_adapter", lambda store, quelle: adapter)
    mails, mailer = _mails()

    ergebnis = sh.manuell_versuchen(s, quelle=Q, jetzt=JETZT, mailer=mailer,
                                    konf=KONF_VON_HAND, llm_ruf=_ruf(antwort(NEU))[0])

    assert ergebnis["ok"] is True and ergebnis["befund"] is None
    assert s.get_regeln(Q)["regel_yaml"] == REGELN
    h = s.heilungen_liste(Q)[0]
    assert h["status"] == "ohne-defekt" and "kein Defekt" in h["meldung"]


def test_knopf_verweigert_interne_quellen(tmp_path, monkeypatch):
    s = _store(tmp_path)
    s.add_source("jup", "jup", "intern", URL)
    ergebnis = sh.manuell_versuchen(s, quelle="jup", jetzt=JETZT)
    assert ergebnis["ok"] is False and "keine Regel-YAML" in ergebnis["fehler"]


# --- Admin-API -------------------------------------------------------------

def _client(tmp_path, s: Store):
    from app.main import app
    app.state.store = s
    return TestClient(app)


def test_api_liste_detail_und_uebernehmen(tmp_path, monkeypatch):
    s = _store(tmp_path)
    _archiv(s)
    _lauf(s, roh=0, n=0, konf=KONF_VON_HAND, mailer=_mails()[1])
    fall = s.heilungen_liste(Q)[0]
    c = _client(tmp_path, s)

    liste = c.get("/api/admin/heilungen").json()
    assert liste["faelle"] and liste["einstellungen"]["auto"] in (True, False)
    assert liste["llm_bereit"] in (True, False)

    detail = c.get(f"/api/admin/heilungen/{fall['id']}").json()
    assert detail["vorschlag_yaml"] and "div.card" in detail["diff"]
    assert detail["befund"]["art"] == "selektoren_tot"

    # Übernahme prüft erneut an der JETZIGEN Seite (Netz durch Attrappe ersetzt)
    monkeypatch.setattr(sh, "holer", lambda store, quelle: (lambda url: HTML_UMBAU))
    r = c.post(f"/api/admin/heilungen/{fall['id']}/uebernehmen")
    assert r.status_code == 200, r.text
    assert r.json()["beleg"]["treffer_heute"] == 5
    assert "div.card" in s.get_regeln(Q)["regel_yaml"]
    assert s.heilungen_liste(Q)[0]["status"] == "angenommen"

    # Rücknahme durch den Admin stellt die Vorgänger-Fassung her
    r = c.post(f"/api/admin/heilungen/{fall['id']}/zuruecknehmen")
    assert r.status_code == 200, r.text
    assert s.get_regeln(Q)["regel_yaml"] == REGELN


def test_api_uebernehmen_lehnt_veralteten_vorschlag_ab(tmp_path, monkeypatch):
    s = _store(tmp_path)
    _archiv(s)
    fall = s.heilung_anlegen(Q, "selektoren_tot", {"art": "selektoren_tot"}, JETZT)
    s.heilung_setzen(fall, vorschlag_yaml=NEU.replace("div.card", "div.gibtsnicht"), zeit=JETZT)
    c = _client(tmp_path, s)
    monkeypatch.setattr(sh, "holer", lambda store, quelle: (lambda url: HTML_UMBAU))

    r = c.post(f"/api/admin/heilungen/{fall}/uebernehmen")
    assert r.status_code == 422
    assert "Probelauf" in " ".join(r.json()["detail"]["fehler"])
    assert s.get_regeln(Q)["regel_yaml"] == REGELN


def test_api_ablehnen_und_verlauf(tmp_path):
    s = _store(tmp_path)
    _archiv(s)
    _lauf(s, roh=0, n=0, konf=KONF_AUTO, mailer=_mails()[1])
    c = _client(tmp_path, s)
    verlauf = c.get("/api/admin/heilungen/verlauf").json()
    assert verlauf and verlauf[0]["quelle"] == Q and verlauf[0]["aktiv"] == 1

    fall = s.heilung_anlegen(Q, "selektoren_tot", {"art": "selektoren_tot"}, JETZT)
    r = c.post(f"/api/admin/heilungen/{fall}/ablehnen", json={"grund": "Seite wird gerade umgebaut"})
    assert r.status_code == 200
    assert s.heilung_holen(fall)["status"] == "abgelehnt"
    assert "umgebaut" in s.heilung_holen(fall)["meldung"]


def test_api_reparieren_knopf_startet_und_prueft_vorab(tmp_path, monkeypatch):
    s = _store(tmp_path)
    _archiv(s)
    c = _client(tmp_path, s)
    gerufen: list[str] = []
    monkeypatch.setattr(sh, "manuell_versuchen",
                        lambda store, quelle, jetzt, **k: gerufen.append(quelle) or {"ok": True})

    r = c.post(f"/api/admin/sources/{Q}/reparieren")
    assert r.status_code == 202, r.text
    from app.admin_api import LAUF_THREADS
    for t in list(LAUF_THREADS):
        t.join(timeout=5)
    assert gerufen == [Q]

    # Nicht-Regel-Quellen und pausierte Quellen werden abgewiesen
    s.add_source("feed-quelle", "Feed", "feed", URL)
    assert c.post("/api/admin/sources/feed-quelle/reparieren").status_code == 409
    s.update_source(Q, aktiv=False)
    assert c.post(f"/api/admin/sources/{Q}/reparieren").status_code == 409
    assert c.post("/api/admin/sources/gibtsnicht/reparieren").status_code == 404


# --- Ehrlichkeit: nicht reparierbare Seiten und unbrauchbare Antworten ------

HTML_LEER = ("<html><body><h1>Veranstaltungen</h1>"
             "<p>Keine Treffer für Ihre Auswahl.</p></body></html>")


def test_seite_ohne_inhalt_wird_als_nicht_reparierbar_gemeldet(tmp_path):
    """Live belegt (familienportal, 16.10.2026): die Seite antwortet 200, hat
    aber keinen Eintrag mit Datum — die Liste entsteht im Browser. Ein
    Selektorwechsel hilft nicht, das muss die Meldung sagen."""
    s = _store(tmp_path)
    _archiv(s)
    mails, mailer = _mails()
    ruf, zaehler = _ruf(antwort(NEU))
    aus = _lauf(s, html=HTML_LEER, roh=0, n=0, konf=KONF_AUTO, mailer=mailer,
                ruft=(ruf, zaehler))

    assert aus["befund"]["art"] == "selektoren_tot"
    assert aus["aktion"]["aktion"] == "unreparierbar", aus["aktion"]
    assert zaehler["n"] == 0, "kein Modell-Aufruf für eine Seite ohne Inhalt"
    assert "kein Selektor" in aus["aktion"]["meldung"] or \
           "Selektorwechsel kann das nicht beheben" in aus["aktion"]["meldung"]
    assert s.get_regeln(Q)["regel_yaml"] == REGELN
    h = s.heilungen_liste(Q)[0]
    assert h["status"] == "unreparierbar" and h["benachrichtigt_am"], "gemeldet wird trotzdem"
    assert mails


def test_unbrauchbare_modellantwort_wird_in_der_akte_festgehalten(tmp_path):
    """Sonst ist hinterher nicht nachvollziehbar, WARUM nichts kam."""
    s = _store(tmp_path)
    _archiv(s)
    ruf, _ = _ruf("Ich kann diese Seite leider nicht reparieren.")
    aus = _lauf(s, roh=0, n=0, konf=KONF_AUTO, mailer=_mails()[1], ruft=(ruf, 0))
    h = s.heilungen_liste(Q)[0]
    assert h["status"] == "offen"
    assert h["begruendung"] == "Modell-Antwort ohne gültiges YAML"
    beleg = json.loads(h["beleg_json"] or "{}")
    assert "Ich kann diese Seite" in beleg.get("modell_antwort", "")
    assert s.get_regeln(Q)["regel_yaml"] == REGELN
    assert aus["aktion"]["regeln_geaendert"] is False


# --- Oberfläche ------------------------------------------------------------

def test_oberflaeche_hat_knopf_liste_und_einstellungen():
    import pathlib
    html = pathlib.Path("app/static/admin.html").read_text(encoding="utf-8")
    js = pathlib.Path("app/static/admin.js").read_text(encoding="utf-8")
    for feld in ("heilungKlapp", "heilungListe", "heilungStatus", "heilungPanel",
                 "heilungVerlauf", "heilungSetKlapp", "setHeilungAuto",
                 "setHeilungMailAktiv", "setHeilungMailAn", "setHeilungMax",
                 "heilungSpeichern"):
        assert f'id="{feld}"' in html, f"Feld fehlt: {feld}"
    assert 'id="heilungKlapp" open' in html, "Bereich muss offen ausgeliefert werden"
    assert 'data-act="heilung"' in js, "Knopf „Reparieren“ fehlt in der Quellenliste"
    assert "/reparieren" in js and "/heilungen" in js
