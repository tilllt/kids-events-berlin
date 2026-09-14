"""Regressionstest: Parameternamen zwischen Oberfläche und API festnageln.

Anlass (2026-09-13): Zwei Namensfehler derselben Art haben je einen Filter
lautlos verschluckt —
  * `km` im Frontend gegen `umkreis_km` in der API (Umkreissuche wirkte nie),
  * `zeitstufe` in der App-Adresse gegen `uhrzeit` in `/api/kalender.ics`
    (Zeitfilter kam im Kalender-Abo nicht an: 579 statt 222 Termine).
Beide Male gab es keine Fehlermeldung, nur unveränderte Ergebnisse.

Dieser Test liest die Namen aus den statischen Dateien und aus den echten
FastAPI-Signaturen (kein zweites Verzeichnis der Namen) und prüft:
  1. Was das Kalender-Abo in die Adresse schreibt, versteht der Endpunkt.
  2. Die Ausschlussliste des Abos enthält nur echte Schlüssel (kein Tippfehler,
     der einen Filter still verschluckt).
  3. Jeder im Frontend gesetzte Parameter existiert irgendwo — als eigener
     Adress-Schlüssel der App oder als Parameter einer API.
"""
import inspect
import pathlib
import re

from app.api import router

STATIC = pathlib.Path("app/static")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
NAEHE_JS = (STATIC / "naehe.js").read_text(encoding="utf-8")

_SET_RX = re.compile(r'\.set\(\s*"([^"]+)"')


def _api_parameter(pfad: str) -> set[str]:
    """Query-Parameter eines Endpunkts — aus der Signatur, nicht aus einer Liste."""
    for route in router.routes:
        if getattr(route, "path", None) == pfad:
            endpunkt = getattr(route, "endpoint", None)
            if endpunkt is None:
                continue
            sig = inspect.signature(endpunkt)
            return {name for name, p in sig.parameters.items()
                    if name != "request" and p.kind in (p.POSITIONAL_OR_KEYWORD,
                                                        p.KEYWORD_ONLY)}
    raise AssertionError(f"Endpunkt {pfad} nicht gefunden")


def _block(text: str, kopf: str) -> str:
    """Quelltextblock ab `kopf` bis zur schließenden Klammer in Spalte 0."""
    i = text.index(kopf)                       # ValueError = Umbau, Test anpassen
    return text[i:text.index("\n}", i)]


def _adress_schluessel_der_app() -> set[str]:
    """Schlüssel, die die App in ihre eigene Adresse schreibt (queryParams)."""
    return set(_SET_RX.findall(_block(APP_JS, "function queryParams() {")))


def _nicht_im_abo() -> set[str]:
    m = re.search(r"var NICHT_IM_ABO = \[(.*?)\];", NAEHE_JS, re.S)
    assert m, "NICHT_IM_ABO nicht gefunden"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def _umbenennen() -> dict[str, str]:
    m = re.search(r"var ABO_UMBENENNEN = \{(.*?)\};", NAEHE_JS, re.S)
    assert m, "ABO_UMBENENNEN nicht gefunden"
    return dict(re.findall(r'(\w+)\s*:\s*"([^"]+)"', m.group(1)))


def test_abo_adresse_versteht_der_kalender_endpunkt():
    """Fall 2 der Lehre: jeder durchgereichte Filter muss dort auch so heißen."""
    durchgereicht = _adress_schluessel_der_app() - _nicht_im_abo()
    umbenennen = _umbenennen()
    im_abo = {umbenennen.get(k, k) for k in durchgereicht}
    falsch = im_abo - _api_parameter("/api/kalender.ics")
    assert not falsch, (
        f"Diese Filter stehen im Abo-Link, aber /api/kalender.ics kennt sie "
        f"nicht: {sorted(falsch)} — Umbenennung in naehe.js prüfen.")


def test_abo_ausschlussliste_hat_keine_tippfehler():
    bekannt = (_adress_schluessel_der_app()
               | _api_parameter("/api/events")
               | _api_parameter("/api/kalender.ics"))
    unbekannt = _nicht_im_abo() - bekannt
    assert not unbekannt, (
        f"Unbekannte Schlüssel in NICHT_IM_ABO: {sorted(unbekannt)} — "
        f"ein Tippfehler hier verschluckt den Filter still.")


def test_frontend_parameter_existieren_ueberhaupt():
    """Fall 1 der Lehre: `km` statt `umkreis_km` — nirgends definiert."""
    bekannt = (_adress_schluessel_der_app()
               | _api_parameter("/api/events")
               | _api_parameter("/api/events.geojson")
               | _api_parameter("/api/kalender.ics")
               | _api_parameter("/api/orte"))
    gesetzt = {(name, key)
               for name, text in (("app.js", APP_JS), ("naehe.js", NAEHE_JS))
               for key in _SET_RX.findall(text)}
    unbekannt = sorted({(n, k) for n, k in gesetzt if k not in bekannt})
    assert not unbekannt, (
        f"Parameter, die keine API kennt und die nicht in der eigenen Adresse "
        f"stehen: {unbekannt}")


def test_zeitstufe_ist_im_abo_auf_uhrzeit_uebersetzt():
    """Der konkrete Fehler vom 2026-09-13 — Umbenennung darf nicht verschwinden."""
    assert _umbenennen().get("zeitstufe") == "uhrzeit"
    assert "zeitstufe" in _adress_schluessel_der_app()


def test_umkreis_heisst_in_api_und_frontend_gleich():
    assert "umkreis_km" in _api_parameter("/api/events")
    assert "umkreis_km" in _api_parameter("/api/kalender.ics")
    assert any("umkreis_km" in zeile for zeile in NAEHE_JS.splitlines())
    assert not re.search(r'\.set\(\s*"km"', NAEHE_JS), "km statt umkreis_km"
