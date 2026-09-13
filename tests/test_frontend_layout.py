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


def test_mobile_filter_schieben_die_liste_nach_unten():
    block = _block(r"@media \(max-width: 820px\)\s*\{.*?\n\}")
    assert "height: auto" in block, "Seite darf mobil nicht auf Bildschirmhöhe fixiert sein"
    assert "main { display: block; }" in block, "mobil normale Dokumentfolge nötig"
    assert re.search(r"#filters\s*\{[^}]*max-height:\s*none", block), \
        "Filter dürfen mobil nicht in einen Streifen gequetscht werden"
    liste = re.search(r"#eventlist\s*\{[^}]*\}", block)
    assert liste, "mobile Listen-Regel fehlt"
    assert "overflow-y: auto" in liste.group(0) and "max-height" in liste.group(0), \
        "Liste braucht mobil eine eigene Höhengrenze mit Scrollen, sonst ist die Karte unerreichbar"
    assert re.search(r"#mapwrap\s*\{[^}]*height:\s*30vh", block), \
        "Karte braucht mobil eine eigene, feste Höhe und muss ohne Scrollen sichtbar sein"
    liste = re.search(r"#eventlist\s*\{[^}]*\}", block).group(0)
    assert "36vh" in liste and "300px" in liste, \
        "mobile Liste auf ~5 Termine begrenzen, damit die Karte im Bild bleibt"
    assert re.search(r"main\s*\{[^}]*overflow-y:\s*auto", block), \
        "Hauptbereich muss mobil scrollen, wenn Filter aufklappen"
