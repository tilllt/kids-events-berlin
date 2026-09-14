"""Brave-Websuche als Stufe vor der Mail-Anfrage (Change 012).

Warum überhaupt Websuche: Die Recherche besucht bisher nur die Schul-Seite
selbst (Homepage + bis zu zwei Link-Kandidaten). Gemessen am 13.09.2026 an
Friedrichshain-Kreuzberger Grundschulen ohne Fund: in 5 von 8 Fällen liefert
eine Websuche den Termin — u. a. eine tiefe Unterseite der Schul-Website
(„…/tag-der-offenen-tuer-am-18-9-2026"), die die Heuristik nie besucht hätte.
Die Suche ist also primär ein Link-Finder, die Auswertung bleibt beim LLM mit
derselben Belegprüfung.

Kontingent (offizielle Preisseite von Brave, abgerufen 13.09.2026):
  Web Search kostet **5,00 $ je 1.000 Anfragen**; Brave schreibt monatlich
  **5,00 $ Guthaben** gut → **1.000 Anfragen gratis pro Monat**, Kapazität
  50 Anfragen/Sekunde. Überschreitungen laufen gegen das hinterlegte Guthaben
  bzw. die Zahlungsart — deshalb wird hier HART gestoppt statt weitergefragt.

Kontingent-Verwaltung: Grundlage ist eine Aufruf-Tabelle in der Datenbank
(`brave_aufrufe`), kein Zähler in den Einstellungen — der kann driften. Jeder
Aufruf wird VOR dem Absenden verbucht (Reservierung: ein Absturz mitten im
Request darf kein Guthaben „verlieren"), nach der Antwort um HTTP-Code,
Trefferzahl und Fehler ergänzt. Monats-/Tagesbudget sind in der Admin-GUI
änderbar; Erreichen des Budgets ist ein sichtbarer Fehler, kein stilles
Überspringen.

Rate Limit: mindestens `brave_anfragen_pro_s` Abstand zwischen zwei Aufrufen
(Standard 1/s, Brave erlaubt 50/s — wir bleiben höflich und berechenbar) und
bei HTTP 429 genau ein Wiederholungsversuch mit Wartezeit, danach klarer Fehler.
"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime

import httpx

from app.model import TZ_BERLIN

BASIS = "https://api.search.brave.com/res/v1/web/search"
PREIS_PRO_1000_USD = 5.0

KONFIG_STANDARD = {
    "brave_api_key": "",
    "brave_monat_limit": "900",     # 1.000 gratis/Monat → 100 Reserve
    "brave_tages_limit": "30",      # verteilt das Monatsbudget über den Monat
    "brave_anfragen_pro_s": "1",
    "brave_websuche_aktiv": "0",    # erst einschalten, wenn der Key geprüft ist
    "brave_wiederholung_tage": "30",  # dieselbe Schule höchstens 1× je 30 Tage fragen
}


class BraveFehler(RuntimeError):
    """Klartext-Fehler für die Oberfläche (kein stiller Abbruch)."""


def konfiguration(store) -> dict:
    k = dict(KONFIG_STANDARD)
    for schluessel in KONFIG_STANDARD:
        wert = store.get_setting(schluessel)
        if wert not in (None, ""):
            k[schluessel] = wert
    return k


def _int(wert, standard: int) -> int:
    try:
        return int(str(wert).strip())
    except (TypeError, ValueError):
        return standard


def heute_berlin() -> date:
    """Heute in Berlin — die eine Wahrheit für Tageszähler und Monatsbudget.

    `date.today()` nimmt die Systemzeitzone (im Container: UTC). Nachts weicht
    sie damit vom Berliner Datum ab, während `Store.brave_verbrauch` die
    Aufrufe im Berliner Datum stempelt — die Tageszählung fand dann 0 Aufrufe
    und das TAGESBUDGET griff nicht (gefunden 2026-09-14 durch
    tests/test_recherche_websuche.py::test_tagesbudget_stoppt_und_nennt_die_zahlen).
    """
    return datetime.now(TZ_BERLIN).date()


def monat(heute: date | None = None) -> str:
    return (heute or heute_berlin()).strftime("%Y-%m")


def status(store, konfig: dict | None = None, heute: date | None = None) -> dict:
    """Verbrauch gegen Budget — Grundlage für Drosselung und Anzeige."""
    k = konfig or konfiguration(store)
    v = store.brave_verbrauch(heute=heute)
    monats_limit = _int(k.get("brave_monat_limit"), 900)
    tages_limit = _int(k.get("brave_tages_limit"), 30)
    return {
        "monat": v["monat"], "verbraucht_monat": v["monat_anzahl"],
        "monats_limit": monats_limit, "rest_monat": max(0, monats_limit - v["monat_anzahl"]),
        "verbraucht_heute": v["tag_anzahl"], "tages_limit": tages_limit,
        "verbraucht_gesamt": v["gesamt"],
        "kosten_usd": round(v["gesamt"] * PREIS_PRO_1000_USD / 1000.0, 4),
        "aktiv": str(k.get("brave_websuche_aktiv", "0")).strip() in ("1", "true", "ja", "on"),
        "key_gesetzt": bool(str(k.get("brave_api_key") or "").strip()),
        "anfragen_pro_s": _int(k.get("brave_anfragen_pro_s"), 1),
        "wiederholung_tage": _int(k.get("brave_wiederholung_tage"), 30),
    }


def budget_fehler(st: dict) -> str | None:
    """Grund, warum gerade NICHT gesucht werden darf (None = frei)."""
    if not st["key_gesetzt"]:
        return "Kein Brave-API-Key hinterlegt (Einstellungen → Websuche)."
    if st["verbraucht_monat"] >= st["monats_limit"]:
        return (f"Monatsbudget aufgebraucht ({st['verbraucht_monat']}/{st['monats_limit']} "
                f"Anfragen) — Websuche pausiert bis zum Monatswechsel.")
    if st["tages_limit"] and st["verbraucht_heute"] >= st["tages_limit"]:
        return (f"Tagesbudget erreicht ({st['verbraucht_heute']}/{st['tages_limit']} Anfragen) "
                f"— die restlichen Schulen kommen morgen oder per Mail-Anfrage.")
    return None


def zuletzt_gesucht(store, bsn: str, konfig: dict | None = None,
                    heute: date | None = None) -> str | None:
    """Grund, warum dieselbe Schule gerade nicht noch einmal gesucht wird.

    Kontingent-Schutz: dieselbe Schule wird höchstens alle
    `brave_wiederholung_tage` Tage befragt (0 = immer). Verhindert, dass ein
    täglicher Lauf dieselbe Schule 30-mal im Monat bezahlt, ohne neuen Befund.
    """
    tage = _int((konfig or {}).get("brave_wiederholung_tage", KONFIG_STANDARD[
        "brave_wiederholung_tage"]), 30)
    if tage <= 0:
        return None
    zuletzt = store.brave_letzte_suche(bsn)
    if not zuletzt:
        return None
    try:
        # Zeitstempel wird in UTC gespeichert (Audit) — für das Alter zählt
        # aber das Berliner Datum, sonst „1 Tag" kurz nach Mitternacht.
        d = datetime.fromisoformat(zuletzt).astimezone(TZ_BERLIN).date()
    except ValueError:
        return None
    alter = ((heute or heute_berlin()) - d).days
    if alter < tage:
        return (f"Websuche für diese Schule erst vor {alter} Tagen gelaufen "
                f"(Wiederholung nach {tage} Tagen) — Kontingent geschont.")
    return None


def ergebnis_urls(daten: dict, domain: str | None = None, max_urls: int = 4) -> list[str]:
    """Treffer-URLs in Reihenfolge: Schul-Domain zuerst, dann Fremdquellen.

    Fremdquellen sind bewusst zugelassen (Blogs, Bezirksseiten), aber sie kommen
    nach den Seiten der Schule selbst und werden im Vorschlag als Quelle benannt.
    """
    roh = [e.get("url") for e in ((daten.get("web") or {}).get("results") or [])
           if e.get("url")]
    d = (domain or "").lower().removeprefix("www.")
    eigen = [u for u in roh if d and d in u.lower()]
    fremd = [u for u in roh if u not in eigen]
    gesehen, raus = set(), []
    for u in eigen + fremd:
        if u not in gesehen:
            gesehen.add(u)
            raus.append(u)
    return raus[:max_urls]


class BraveSuche:
    """Brave-Aufrufe mit Budget-Prüfung, Reservierung, Rate Limit und Audit."""

    def __init__(self, store, konfig: dict | None = None, client: httpx.Client | None = None,
                 heute_fn=heute_berlin, bsn: str | None = None):
        self.store = store
        self.bsn = bsn
        self.konfig = konfig or konfiguration(store)
        self.client = client or httpx.Client(timeout=20.0)
        self.heute_fn = heute_fn
        self._lock = threading.Lock()
        self._letzter_aufruf = 0.0

    def _warten(self) -> None:
        abstand = 1.0 / max(1, _int(self.konfig.get("brave_anfragen_pro_s"), 1))
        with self._lock:
            warte = self._letzter_aufruf + abstand - time.monotonic()
        if warte > 0:
            time.sleep(warte)

    def suche(self, query: str, count: int = 5, bsn: str | None = None) -> dict:
        """Eine Websuche. Wirft BraveFehler mit Klartext, wenn sie nicht geht."""
        st = status(self.store, self.konfig, heute=self.heute_fn())
        grund = budget_fehler(st)
        if grund:
            raise BraveFehler(grund)
        aufruf_id = self.store.starte_brave_aufruf(monat(self.heute_fn()), query,
                                                   bsn or self.bsn)
        treffer, fehler, code = 0, None, 0
        try:
            for versuch in (1, 2):
                self._warten()
                try:
                    r = self.client.get(BASIS, params={"q": query, "count": count,
                                                       "country": "DE", "search_lang": "de",
                                                       "safesearch": "strict"},
                                        headers={"Accept": "application/json",
                                                 "Accept-Encoding": "gzip",
                                                 "X-Subscription-Token":
                                                     str(self.konfig["brave_api_key"])})
                    code = r.status_code
                except httpx.HTTPError as e:
                    fehler = f"Brave nicht erreichbar: {e}"
                    break
                with self._lock:
                    self._letzter_aufruf = time.monotonic()
                if code == 200:
                    try:
                        daten = r.json()
                    except ValueError:
                        fehler = f"Antwort ist kein JSON: {r.text[:150]}"
                        break
                    treffer = len(((daten.get("web") or {}).get("results") or []))
                    return daten
                if code == 429 and versuch == 1:
                    time.sleep(2.0)  # genau ein Wiederholungsversuch
                    continue
                if code in (401, 403):
                    fehler = ("API-Key abgelehnt — Schlüssel in den Einstellungen prüfen "
                              "(Brave-Dashboard → API Keys).")
                elif code == 402:
                    fehler = ("Brave meldet fehlendes Guthaben (402) — Websuche gestoppt, "
                              "damit keine Kosten entstehen.")
                elif code == 429:
                    fehler = "Brave drosselt (429) auch nach Wiederholung — Lauf abgebrochen."
                elif code == 422:
                    fehler = f"Anfrage abgelehnt (422): {r.text[:150]}"
                else:
                    fehler = f"Brave antwortet HTTP {code}: {r.text[:150]}"
                break
            raise BraveFehler(fehler or f"Websuche fehlgeschlagen (HTTP {code})")
        finally:
            self.store.beende_brave_aufruf(aufruf_id, http_code=code, treffer=treffer,
                                            fehler=fehler)
