"""Regressionstest für die Admin-Oberfläche.

Anlass: Change 013 hat einen zweiten E-Mail-Bereich eingebaut, ohne die alten
SMTP-/Vorlagen-Felder zu entfernen. Folge waren DOPPELTE Element-IDs — der
Browser liefert bei ``querySelector("#id")`` das erste Vorkommen, also wurde das
falsche Feld gelesen und geschrieben. Zusätzlich war nicht erkennbar, welcher
Oberflächen-Stand im Browser geladen ist.
"""
import collections
import pathlib
import re

HTML = pathlib.Path("app/static/admin.html").read_text(encoding="utf-8")
JS = pathlib.Path("app/static/admin.js").read_text(encoding="utf-8")


def test_keine_doppelten_element_ids():
    ids = re.findall(r'id="([A-Za-z0-9_]+)"', HTML)
    doppelt = {k: v for k, v in collections.Counter(ids).items() if v > 1}
    assert not doppelt, f"Doppelte IDs in admin.html: {doppelt}"


def test_jede_im_js_genutzte_id_existiert():
    """Jede im JS angesprochene #id muss es geben — sonst stiller Ausfall.

    IDs dürfen auch aus JS-Vorlagen stammen (Dialoge werden per innerHTML
    gebaut), deshalb zählen statisches HTML und id="…" in admin.js zusammen.
    """
    definiert = set(re.findall(r'id="([A-Za-z0-9_]+)"', HTML))
    definiert |= set(re.findall(r'id="([A-Za-z0-9_]+)"', JS))
    definiert |= set(re.findall(r'\.id\s*=\s*"([A-Za-z0-9_]+)"', JS))   # per JS erzeugt
    genutzt = set(re.findall(r'\$\("#([A-Za-z0-9_]+)"\)', JS))
    fehlend = sorted(t for t in genutzt if t not in definiert)
    assert not fehlend, f"JS nutzt IDs, die nirgends definiert sind: {fehlend}"


def test_mail_bereich_hat_getrennte_zeilen_und_ist_offen():
    assert 'id="mailKlapp" open' in HTML, "E-Mail-Bereich ist nicht aufgeklappt"
    for feld in ("setMailReplyTo", "setMailBetreff", "setMailText"):
        assert f'id="{feld}"' in HTML, f"Feld fehlt: {feld}"
    assert '$("#setMailReplyTo")' in JS and '$("#setMailBetreff")' in JS


def test_alte_smtp_und_vorlagen_bloecke_sind_weg():
    assert 'id="smtpKlapp"' not in HTML and 'id="vorlageKlapp"' not in HTML
    assert 'id="smtpBtn"' not in JS and 'id="vorlageBtn"' not in JS
    assert '$("#setVorlage")' not in JS


def test_websuche_bereich_ist_offen():
    assert 'id="braveKlapp" open' in HTML
    assert '$("#braveTesten")' in JS


def test_baustand_marke_ist_in_der_kopfzeile():
    assert "<!--BAUSTAND-->" in HTML, "Kopfzeile zeigt den Oberflächen-Stand nicht"


def _formgrid_kinder(markup: str) -> list:
    """Alle direkten Kind-Elemente jedes .formgrid-Containers (DOM-Walk)."""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.kinder = []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            eltern = self.stack[-1] if self.stack else None
            if eltern is not None and "formgrid" in (eltern[1] or ""):
                self.kinder.append(tag)
            self.stack.append((tag, a.get("class")))

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    return

    p = P()
    p.feed(markup)
    return p.kinder


def test_formgrid_enthaelt_nur_labels():
    """Layout-Regel: .formgrid ist ein Grid aus Feldern — jedes Kind ist ein label.

    Anlass: die Mail-/Websuche-Bereiche hatten „<label>Text</label><div><input></div>"
    eingebaut. Das verdoppelt die Grid-Zellen und zerlegt das Desktop-Layout.
    """
    kinder = _formgrid_kinder(HTML)
    assert kinder, "keine formgrid-Bereiche gefunden"
    assert set(kinder) == {"label"}, f"formgrid enthält Nicht-Label-Elemente: {kinder}"


def test_dialog_im_js_nutzt_dieselbe_layout_regel():
    """Auch der Mail-Dialog (per innerHTML gebaut) muss Labels als Felder nutzen."""
    kinder = _formgrid_kinder(JS)
    assert kinder and set(kinder) == {"label"}, f"Dialog-formgrid: {kinder}"
