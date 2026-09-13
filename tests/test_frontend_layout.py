"""Layout-Regeln der öffentlichen Seite (Karte + mobile Filter).

Anlass (Befund 2026-09-13): auf dem Desktop wirkte die Karte unten
abgeschnitten (feste Prozent-Höhe mit harter Obergrenze, danach nie neu
vermessen), und auf dem Handy verschwand die Ergebnisliste, sobald man die
Filter aufklappte (festgeklemmte Bildschirmhöhe mit eigenen Scroll-Bereichen).
Diese Regeln halten den Zustand fest.
"""
import pathlib
import re

CSS = pathlib.Path("app/static/style.css").read_text(encoding="utf-8")
JS = pathlib.Path("app/static/app.js").read_text(encoding="utf-8")


def _block(muster: str) -> str:
    m = re.search(muster, CSS, re.S)
    assert m, f"CSS-Block nicht gefunden: {muster}"
    return m.group(0)


def test_karte_hat_keine_harte_hohenkappung():
    block = _block(r"#mapwrap\s*\{[^}]*\}")
    assert "max-height" not in block, "feste Obergrenze schneidet die Karte ab"
    assert "height: 46%" not in CSS, "feste Prozent-Höhe ohne Mitschrumpfen"
    assert "min(" in block, "Höhe muss auf kleinen Fenstern mitschrumpfen können"
    assert re.search(r"#map\s*\{[^}]*min-height:\s*0", CSS), \
        "Karte braucht min-height:0, sonst sprengt sie den Container"


def test_karte_wird_nach_layoutaenderungen_neu_vermessen():
    assert "invalidateSize" in JS, "Leaflet-Größe wird nie aktualisiert"
    assert '"resize"' in JS and "orientationchange" in JS
    # Auch beim Auf-/Zuklappen der Filter
    assert re.search(r'filter-panel"\)\.forEach[^\n]*\n\s*karteNachziehen\(\);', JS), \
        "Filter-Umschalten zieht die Karte nicht nach"


def test_ortsfilter_im_frontend_vorhanden():
    """Der Ortsfilter muss als eigener Tab mit Panel in der Startseite stehen und
    im Request landen (Nutzer-Vorgabe: weiterer Filter „Ort", der sich den
    übrigen Filtern anpasst)."""
    html = pathlib.Path("app/static/index.html").read_text(encoding="utf-8")
    assert 'data-panel="ort"' in html and 'id="panel-ort"' in html
    assert 'id="ort-list"' in html and 'id="ort-suche"' in html
    # Auswahlliste kommt gefiltert vom Server …
    assert "/api/orte?" in JS
    # … und die Auswahl geht als 'ort' in die Abfrage (Trenner '|', damit
    # Ortsnamen mit Komma heil bleiben).
    assert 'p.set("ort", state.orte.join("|"))' in JS
    assert 'state.orte = (p.get("ort") || "").split("|")' in JS
    # Lange Ortslisten brauchen einen eigenen Scrollbereich.
    assert "#ort-list" in CSS and "max-height" in CSS


def test_mobile_filter_schieben_die_liste_nach_unten():
    """Mobil: Kopfzeile fest, main scrollt, Liste ~5 Einträge, Karte im Bild."""
    block = _block(r"@media \(max-width: 820px\)\s*\{.*?\n\}")
    assert "height: 100%" in block, "mobil muss die Bildschirmhöhe gelten, sonst scrollt die Karte weg"
    assert re.search(r"main\s*\{[^}]*overflow-y:\s*auto", block), \
        "Hauptbereich muss mobil scrollen, wenn Filter aufklappen"
    assert re.search(r"#filters\s*\{[^}]*max-height:\s*none", block), \
        "Filter dürfen mobil nicht in einen Streifen gequetscht werden"
    liste = re.search(r"#eventlist\s*\{[^}]*\}", block)
    assert liste, "mobile Listen-Regel fehlt"
    assert "overflow-y: auto" in liste.group(0) and "flex: 1 1 auto" in liste.group(0), \
        "Liste nimmt den Restplatz und scrollt in sich (~5 Einträge)"
    assert "min-height: 150px" in liste.group(0), "Liste darf nicht ganz verschwinden"
    assert re.search(r"#mapwrap\s*\{[^}]*height:\s*min\(24vh, 185px\)", block), \
        "Karte braucht mobil eine feste, kleine Höhe, damit sie ohne Scrollen sichtbar ist"
