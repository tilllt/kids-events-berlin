"""Change 017: Selbstheilung — Erkennung, Diagnose, Archiv (Phase 1).

Der zentrale Test: Eine kleinere Zahl ist KEIN Fehler. Ein Kalender darf
saisonal weniger anbieten — geheilt wird nur, was nachweislich kaputt ist.
"""
from app import selbstheilung as sh
from app.store import Store

REGELN = """quelle: test-quelle
listing:
  url: https://example.invalid/termine
  item_css: "article.event"
  felder:
    titel: {css: "a"}
    start: {css: "span.datum"}
"""

# Gesunde Seite: Termin-Blöcke wie in den Regeln erwartet
HTML_GESUND = "<html><body>" + "".join(
    f'<article class="event"><a href="/e{i}">Fest {i}</a>'
    f'<span class="datum">1{i}.09.2026</span></article>' for i in range(5)
) + "</body></html>"

# Umbau der Quelle: gleiche Inhalte, andere Struktur (kein article.event mehr)
HTML_UMBAU = "<html><body>" + "".join(
    f'<div class="card"><a href="/e{i}">Fest {i}</a>'
    f'<span class="d">1{i}.09.2026</span></div>' for i in range(5)
) + "</body></html>"

JETZT = "2026-09-13T10:00:00+02:00"


def test_weniger_termine_ist_kein_fehler():
    """Nutzer-Einwand: Heilung darf nicht bei einer kleineren Zahl anspringen."""
    assert sh.befund_ermitteln(roh_zeilen=4, n_zeilen=4, n_fehler=0,
                               archiv_treffer=12) is None
    assert sh.befund_ermitteln(roh_zeilen=1, n_zeilen=1, n_fehler=0,
                               archiv_treffer=40) is None
    # Und ohne Archiv (erster Lauf) erst recht nicht
    assert sh.befund_ermitteln(roh_zeilen=0, n_zeilen=0, n_fehler=0,
                               archiv_treffer=None) is None


def test_verdacht_loest_nur_diagnose_aus():
    v = sh.verdacht_ermitteln(roh_zeilen=4, n_zeilen=4, archiv_treffer=12)
    assert v and v["art"] == "verdacht" and v["zahlen"]["frueher"] == 12
    # Alles durchs Zeitfenster gefiltert ist kein Defekt (Termine gelesen, aber
    # keiner im 3-Wochen-Fenster → ganz normal bei einem Kalender)
    assert sh.verdacht_ermitteln(roh_zeilen=4, n_zeilen=0, archiv_treffer=12) is None
    # Null Treffer bei vorhandenem Archiv ist ein Fehler, kein Verdacht
    assert sh.verdacht_ermitteln(roh_zeilen=0, n_zeilen=0, archiv_treffer=12) is None
    # Normale Schwankung
    assert sh.verdacht_ermitteln(roh_zeilen=9, n_zeilen=9, archiv_treffer=12) is None


def test_umgezogene_und_gesperrte_seite():
    b = sh.befund_ermitteln(http_fehler="Client error '404 Not Found' for url ...")
    assert b["art"] == "url_umgezogen" and b["status"] == 404
    b = sh.befund_ermitteln(http_fehler="429 Too Many Requests")
    assert b["art"] == "gesperrt" and b["status"] == 429


def test_tote_selektoren_nur_mit_frueheren_treffern():
    b = sh.befund_ermitteln(roh_zeilen=0, n_zeilen=0, n_fehler=0, archiv_treffer=9)
    assert b["art"] == "selektoren_tot"
    # Ohne Archiv ist „leer" kein Beweis
    assert sh.befund_ermitteln(roh_zeilen=0, n_zeilen=0, n_fehler=0,
                               archiv_treffer=0) is None


def test_fehlerquote_und_pflichtfeld():
    assert sh.befund_ermitteln(roh_zeilen=20, n_zeilen=20, n_fehler=12)["art"] == "fehlerquote"
    assert sh.befund_ermitteln(roh_zeilen=30, n_zeilen=30, n_fehler=10)["art"] == "fehlerquote"
    assert sh.befund_ermitteln(roh_zeilen=30, n_zeilen=30, n_fehler=8) is None   # < 30 % kein Defekt
    assert sh.befund_ermitteln(roh_zeilen=30, n_zeilen=30, n_fehler=10)["art"] == "fehlerquote"


def test_diagnose_erkennt_strukturellen_umbau():
    d = sh.diagnose(regeln=REGELN, html=HTML_UMBAU, url="https://example.invalid/termine")
    assert d["item_treffer"] == 0
    assert d["terminartige_links"] == 5
    assert d["urteil"] == "selektoren_tot_aber_inhalt_da"

    d2 = sh.diagnose(regeln=REGELN, html=HTML_GESUND)
    assert d2["item_treffer"] == 5 and d2["urteil"] == "selektoren_funktionieren"
    assert d2["felder"]["titel"] == 1 and d2["felder"]["start"] == 1

    # Selektoren tot UND keine datierten Einträge → Seite bietet nichts an
    d3 = sh.diagnose(regeln=REGELN, html="<html><body><p>Baustelle</p></body></html>")
    assert d3["urteil"] == "seite_ohne_terminangebot"


def test_yaml_wird_aus_der_antwort_gelesen():
    gut = f"Hier die Regeln:\n{MARKER}\nBegruendung: Selektor angepasst."
    assert sh.yaml_aus_antwort(gut) is not None
    # Codeblock als Ausweichweg
    assert sh.yaml_aus_antwort("```yaml\nquelle: q\n```") is not None
    assert sh.yaml_aus_antwort("Ich kann das nicht.") is None
    assert sh.yaml_aus_antwort(f"{sh.MARKER_AUF}\n[unclosed\n{sh.MARKER_ZU}") is None


MARKER = f"{sh.MARKER_AUF}\nquelle: test-quelle\nlisting:\n  url: https://example.invalid/termine\n  item_css: \"div.card\"\n  felder:\n    titel: {{css: \"a\"}}\n    start: {{css: \"span.d\", regex: \"([0-9]{{2}}[.][0-9]{{2}}[.][0-9]{{4}})\", format: \"%d.%m.%Y\"}}\n{sh.MARKER_ZU}"


def test_gate_nimmt_heilenden_vorschlag_an():
    """Der Selektor wird auf die neue Struktur angepasst — und passt weiterhin
    auf die archivierte Seite (echte Reparatur, kein Zufallstreffer)."""
    alt = REGELN.replace("{{css:", "").replace("}}", "")
    p = sh.gate(neu_yaml=MARKER.replace(sh.MARKER_AUF, "").replace(sh.MARKER_ZU, "").strip(),
                alt_yaml=REGELN, quelle="test-quelle", html_heute=HTML_UMBAU,
                html_alt=HTML_GESUND, treffer_alt=5)
    assert p["ok"], p["fehler"]
    assert p["beleg"]["treffer_heute"] == 5 and p["beleg"]["felder"]["start"] == 5


VORSCHLAG = sh.yaml_aus_antwort(MARKER)          # reines YAML ohne Marker


def test_gate_lehnt_fremde_domain_und_quelle_ab():
    fremd = VORSCHLAG.replace("https://example.invalid/termine", "https://boese.example/x")
    p = sh.gate(neu_yaml=fremd, alt_yaml=REGELN, quelle="test-quelle",
                html_heute=HTML_UMBAU, html_alt=HTML_GESUND, treffer_alt=5)
    assert not p["ok"] and any("Domain" in f for f in p["fehler"]), p["fehler"]

    andere = VORSCHLAG.replace("quelle: test-quelle", "quelle: andere-quelle")
    p = sh.gate(neu_yaml=andere, alt_yaml=REGELN, quelle="test-quelle",
                html_heute=HTML_UMBAU, html_alt=HTML_GESUND, treffer_alt=5)
    assert not p["ok"] and any("Quellenname" in f for f in p["fehler"]), p["fehler"]


def test_gate_lehnt_zu_wenige_treffer_ab():
    kaputt = VORSCHLAG.replace('item_css: "div.card"', 'item_css: "div.gibtsnicht"')
    p = sh.gate(neu_yaml=kaputt, alt_yaml=REGELN, quelle="test-quelle",
                html_heute=HTML_UMBAU, html_alt=HTML_GESUND, treffer_alt=5)
    assert not p["ok"] and any("Probelauf" in f for f in p["fehler"]), p["fehler"]


def test_gate_lehnt_absurd_groben_selektor_ab():
    """Ein Wildcard-Selektor („div") würde hunderte Gerüst-Blöcke als Termine
    einlesen → abgelehnt.

    Bewusst NICHT geprüft wird, ob der Vorschlag auf der ALTEN Seite noch
    Treffer hat: dort gilt die alte Struktur, eine richtige Reparatur findet
    dort nichts. Wichtige Prüfung bleibt „heute Treffer mit gefüllten Feldern".
    """
    grob = VORSCHLAG.replace('item_css: "div.card"', 'item_css: "div"')
    viele = "<html><body>" + "".join(
        f'<div class="k"><a href="/a{i}">Eintrag {i}</a>'
        f'<span class="d">{i % 28 + 1:02d}.09.2026</span></div>' for i in range(300)
    ) + "</body></html>"
    p = sh.gate(neu_yaml=grob, alt_yaml=REGELN, quelle="test-quelle",
                html_heute=viele, html_alt=HTML_GESUND, treffer_alt=5)
    assert not p["ok"] and any("grob" in f for f in p["fehler"]), p["fehler"]


def test_gate_warnt_bei_verdraechtig_vielen_treffern():
    """Verdächtig viele Treffer sind kein Ablehnungsgrund, aber sichtbar."""
    html = "<html><body>" + "".join(
        f'<div class="card"><a href="/e{i}">Fest {i}</a>'
        f'<span class="d">{i % 28 + 1:02d}.09.2026</span></div>' for i in range(40)
    ) + "</body></html>"
    p = sh.gate(neu_yaml=VORSCHLAG, alt_yaml=REGELN, quelle="test-quelle",
                html_heute=html, html_alt=HTML_GESUND, treffer_alt=5)
    assert p["ok"], p["fehler"]
    assert p["beleg"]["warnungen"], "verdächtige Trefferzahl muss im Beleg stehen"


def test_heilen_legt_vorschlag_ab_ohne_regeln_zu_aendern(tmp_path):
    s = Store(tmp_path / "h.db")
    s.add_source("test-quelle", "Test", "regeln", "https://example.invalid/termine")
    s.set_regeln("test-quelle", REGELN)
    vorschlag = MARKER.replace(sh.MARKER_AUF, "").replace(sh.MARKER_ZU, "").strip()
    b = sh.heilen(s, quelle="test-quelle",
                  befund={"art": "selektoren_tot", "text": "kein Treffer"},
                  diagnose=sh.diagnose(regeln=REGELN, html=HTML_UMBAU),
                  html=HTML_UMBAU, jetzt=JETZT,
                  llm_ruf=lambda p: f"{sh.MARKER_AUF}\n{vorschlag}\n{sh.MARKER_ZU}\n"
                                    "Begruendung: Karten tragen jetzt die Klasse card.")
    assert b and b["ok"], b
    liste = s.heilungen_liste("test-quelle")
    assert liste[0]["status"] == "vorgeschlagen"
    assert liste[0]["vorschlag_yaml"] and "div.card" in liste[0]["vorschlag_yaml"]
    assert "Befund" not in (liste[0]["vorschlag_yaml"] or "")
    # Entscheidend: die gültigen Regeln sind UNVERÄNDERT (Übernahme nur per Admin)
    assert s.get_regeln("test-quelle")["regel_yaml"] == REGELN


def test_heilen_behandelt_gesperrte_quelle_nicht(tmp_path):
    s = Store(tmp_path / "h2.db")
    s.add_source("test-quelle", "Test", "regeln", "https://example.invalid/termine")
    s.set_regeln("test-quelle", REGELN)
    gerufen = {"n": 0}

    def fake(p):
        gerufen["n"] += 1
        return ""

    b = sh.heilen(s, quelle="test-quelle",
                  befund={"art": "gesperrt", "text": "429"}, diagnose={},
                  html=HTML_UMBAU, jetzt=JETZT, llm_ruf=fake)
    assert b is None and gerufen["n"] == 0   # kein LLM-Aufruf bei Sperren


def test_pruefen_archiviert_und_meldet(tmp_path):
    s = Store(tmp_path / "sh.db")
    url = "https://example.invalid/termine"

    # Gesunder Lauf → Seite wandert ins Archiv, kein Befund
    b = sh.pruefen(s, quelle="test-quelle", regeln=REGELN, url=url, html=HTML_GESUND,
                   roh_zeilen=5, n_zeilen=5, n_fehler=0, jetzt=JETZT)
    assert b is None
    assert s.seiten_archiv_holen("test-quelle", url)["treffer"] == 5
    assert s.heilungen_liste() == []

    # Quelle baut um: 0 Treffer, Seite erreichbar → Befund + Archiv ist Grundlage
    b = sh.pruefen(s, quelle="test-quelle", regeln=REGELN, url=url, html=HTML_UMBAU,
                   roh_zeilen=0, n_zeilen=0, n_fehler=0, jetzt=JETZT)
    assert b and b["art"] == "selektoren_tot"
    liste = s.heilungen_liste("test-quelle")
    assert len(liste) == 1 and liste[0]["status"] == "offen"
    assert "selektoren_tot_aber_inhalt_da" in (liste[0]["diagnose_json"] or "")
    # Das Archiv bleibt die gesunde Fassung (wird nicht von der kaputten ersetzt)
    assert s.seiten_archiv_holen("test-quelle", url)["treffer"] == 5

    # Zweiter Lauf am selben Tag: kein zweiter Eintrag (ein Versuch je Quelle/Tag)
    sh.pruefen(s, quelle="test-quelle", regeln=REGELN, url=url, html=HTML_UMBAU,
               roh_zeilen=0, n_zeilen=0, n_fehler=0, jetzt=JETZT)
    assert len(s.heilungen_liste("test-quelle")) == 1


def test_verdacht_wird_beobachtet_nicht_behandelt(tmp_path):
    s = Store(tmp_path / "sh2.db")
    url = "https://example.invalid/termine"
    sh.pruefen(s, quelle="q2", regeln=REGELN, url=url, html=HTML_GESUND,
               roh_zeilen=12, n_zeilen=12, n_fehler=0, jetzt=JETZT)
    # Nur noch 3 statt 12, aber alles intakt → beobachtet, kein Eingriff
    b = sh.pruefen(s, quelle="q2", regeln=REGELN, url=url, html=HTML_GESUND,
                   roh_zeilen=3, n_zeilen=3, n_fehler=0, jetzt=JETZT)
    assert b and b["art"] == "verdacht"
    liste = s.heilungen_liste("q2")
    assert liste[0]["status"] == "beobachtet"
    assert s.heilung_offen_fuer("q2", "2026-09-13") is None   # keine offene Störung
