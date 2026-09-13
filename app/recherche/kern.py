"""Ablauf der Schul-Recherche (Change 010).

Kette je Schule: Homepage + max. 2 Terminseiten holen → Vorfilter (Datumsindiz
UND Ziel-Keyword) → Fundstellen-Fenster → ein LLM-Aufruf → **deterministische
Belegprüfung** → Vorschlag als `termine_manuell` (Status `ungeprueft`).

Die Prüfung ist die eigentliche Absicherung, nicht das Modell:
  1. Das Zitat muss whitespace-normalisiert im Quelltext stehen (≥ 15 Zeichen).
  2. Das Datum muss IM Zitat stehen (TT.MM.JJJJ oder „17. September 2026").
     Gemessen: ohne diese Regel hat das Modell Zahlen aus einem
     Kalender-Widget als Termin ausgegeben (25.09.2026 aus „21. 25. 29.").
  3. Datum im Sicht-Horizont, Uhrzeit plausibel, Titel im Vokabular.
  4. Keine Dublette (Schule + Datum + Titelnormalform).
Alles Verworfene wird mit Grund protokolliert — nie still.
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

import httpx

from ..model import TZ_BERLIN
from . import fetch
from .llm import LLMFehler, chat, json_objekt

# Zielklassen-Vokabular (bewusst dasselbe wie im Crawl-Import, Change 005)
TITEL_VOKABULAR = (
    ("tag der offenen", "Tag der offenen Tür"),
    ("offene tür", "Tag der offenen Tür"),
    ("infoabend", "Infoabend"),
    ("informationsabend", "Infoabend"),
    ("informationsveranstaltung", "Informationsveranstaltung"),
    ("infoveranstaltung", "Infoveranstaltung"),
    ("schnuppertag", "Schnuppertag"),
    ("schnupperunterricht", "Schnupperunterricht"),
)
MONATE = ("januar", "februar", "märz", "april", "mai", "juni", "juli",
          "august", "september", "oktober", "november", "dezember")
# Schreibvarianten je Monatsindex (März auch ohne Umlaut — Schul-Seiten mischen)
MONAT_VARIANTEN = {3: ("märz", "maerz")}

PROMPT = """Du bekommst Auszüge einer Schul-Webseite ({schule}, Jahr {jahr}).

Aufgabe: Finde ausschließlich Termine für Tag der offenen Tür, Infoabend /
Informationsveranstaltung oder Schnuppertag.

Antworte NUR mit JSON: {{"termine": [{{"titel": "...", "datum": "TT.MM.JJJJ",
"zeit": "HH:MM" oder null, "beleg": "wörtliches Zitat, höchstens 200 Zeichen"}}]}}

HARTE REGELN:
- Das Datum MUSS im Zitat stehen (z. B. "am 17.09.2026" oder "17. September 2026").
  Steht kein Datum im Zitat, gehört der Termin NICHT in die Antwort.
- Kein Jahr im Text → Jahr {jahr}. Kein Datum im Text → Termin weglassen.
- Nichts erfinden. Kein solcher Termin vorhanden → {{"termine": []}}

AUSZÜGE:
---
{fenster}
---"""

STATUS_KEIN_INDIZ = "keinIndiz"
STATUS_KEIN_FUND = "keinFund"
STATUS_GEFUNDEN = "gefunden"
STATUS_ABRUF = "abrufFehler"
STATUS_FEHLER = "fehler"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def titel_aus_vokabular(roh: str) -> str | None:
    """Freier Modell-Titel → Katalogtitel, oder None (nicht Zielklasse)."""
    low = norm(roh)
    for muster, titel in TITEL_VOKABULAR:
        if muster in low:
            return titel
    return None


def datum_im_zitat(datum: str, zitat: str) -> bool:
    """Steht das Datum im Zitat? Nur so ist der Termin belegt."""
    if not datum or not zitat:
        return False
    try:
        t, m, j = (int(x) for x in datum.split("."))
    except ValueError:
        return False
    z = norm(zitat)
    if m < 1 or m > 12:
        return False
    monate = MONAT_VARIANTEN.get(m, (MONATE[m - 1],))
    varianten = [f"{t:02d}.{m:02d}.{j:04d}", f"{t}.{m}.{j}", f"{t:02d}.{m:02d}.",
                 f"{t}.{m}.", f"{t:02d}.{m:02d}", f"{t}.{m}"]
    for monat in monate:
        varianten += [f"{t}. {monat}", f"{t}.{monat}", f"{t} {monat}"]
    return any(v in z for v in varianten)


def _zeit_ok(zeit: str | None) -> bool:
    if not zeit:
        return True
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(zeit).strip())
    if not m:
        return False
    h, mi = int(m.group(1)), int(m.group(2))
    return 5 <= h <= 22 and 0 <= mi <= 59


def _datum_parsen(datum: str) -> date | None:
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(str(datum).strip(), fmt).date()
        except ValueError:
            continue
    return None


def pruefe_fund(fund: dict, quelltext: str, heute: date) -> tuple[dict | None, str]:
    """Ein Modell-Fund → (normalisierter Vorschlag, "") oder (None, Grund)."""
    zitat = str(fund.get("beleg") or "").strip()
    if len(norm(zitat)) < 15:
        return None, "zitat_zu_kurz"
    if norm(zitat) not in norm(quelltext):
        return None, "zitat_nicht_belegt"
    titel = titel_aus_vokabular(fund.get("titel") or zitat)
    if not titel:
        return None, "titel_unbekannt"
    datum = _datum_parsen(fund.get("datum") or "")
    if not datum:
        return None, "datum_unlesbar"
    if not datum_im_zitat(fund["datum"], zitat):
        return None, "datum_nicht_im_zitat"
    if datum < heute:
        return None, "datum_vergangen"
    if datum > heute + timedelta(days=400):
        return None, "datum_ausserhalb_horizont"
    if not _zeit_ok(fund.get("zeit")):
        return None, "zeit_unplausibel"
    return ({"titel": titel, "start_datum": datum.strftime("%d.%m.%Y"),
             "start_zeit": (str(fund["zeit"]).strip() if fund.get("zeit") else None),
             "beleg": zitat}, "")


def _prompt(schulname: str, jahr: int, fenster: str) -> str:
    return PROMPT.replace("{schule}", schulname).replace("{jahr}", str(jahr)) \
                 .replace("{fenster}", fenster)


def schul_kandidaten(store, *, limit: int | None = None,
                     nur_bsn: str | None = None, bezirk: str | None = None,
                     schulform: str | None = None) -> list[dict]:
    """Schulen mit Website, die am längsten nicht geprüft wurden (nie zuerst)."""
    return store.schulen_fuer_recherche(limit=limit, nur_bsn=nur_bsn,
                                        bezirk=bezirk, schulform=schulform)


def verarbeite_schule(store, schule: dict, konfig: dict, client: httpx.Client,
                      heute: date, *, dry_run: bool = False,
                      schlaf_s: float = 1.1) -> dict:
    """Eine Schule prüfen. Rückgabe = Zähler + evtl. Gründe (nie Ausnahmen)."""
    bsn = schule["bsn"]
    website = (schule.get("website") or "").strip()
    ergebnis = {"bsn": bsn, "schule": schule.get("name") or bsn,
                "status": STATUS_FEHLER, "llm_calls": 0, "n_roh": 0,
                "n_belegt": 0, "verworfen": {}, "url": None, "grund": "",
                "vorschlaege": []}
    if not website:
        ergebnis.update(status="uebersprungen", grund="keine Website im Stamm")
        return ergebnis
    html, status = fetch.hole(website, client)
    if html is None:
        ergebnis.update(status=STATUS_ABRUF, grund=status)
        return ergebnis

    seiten = [(website, html)]
    for url in fetch.kandidaten(html, website):
        if schlaf_s:
            time.sleep(schlaf_s)
        h2, st2 = fetch.hole(url, client)
        if h2 is not None:
            seiten.append((url, h2))

    fenster, fenster_url, text_gesamt = "", None, ""
    for url, h in seiten:
        t = fetch.text_von(h)
        if not fetch.hat_terminindiz(t):
            continue
        f = fetch.text_fenster(t)
        if f:
            fenster, fenster_url, text_gesamt = f, url, t
            break
    if not fenster:
        ergebnis.update(status=STATUS_KEIN_INDIZ, url=website,
                        grund=f"{len(seiten)} Seiten ohne Terminstelle mit Datum")
        return ergebnis

    try:
        antwort = chat(konfig, _prompt(schule.get("name") or bsn, heute.year, fenster),
                       max_tokens=900, client=client)
        ergebnis["llm_calls"] = 1
    except LLMFehler as e:
        ergebnis.update(status=STATUS_FEHLER, url=fenster_url, grund=str(e))
        return ergebnis

    obj = json_objekt(antwort["text"]) or {}
    funde_roh = obj.get("termine")
    funde = [f for f in funde_roh if isinstance(f, dict)] if isinstance(funde_roh, list) else []
    if isinstance(funde_roh, list) and len(funde) != len(funde_roh):
        ergebnis["verworfen"]["kein_objekt"] = len(funde_roh) - len(funde)
    ergebnis["n_roh"] = len(funde)
    ergebnis["url"] = fenster_url
    ergebnis["modell"] = antwort.get("modell")
    for fund in funde:
        vorschlag, grund = pruefe_fund(fund, text_gesamt, heute)
        if not vorschlag:
            ergebnis["verworfen"][grund] = ergebnis["verworfen"].get(grund, 0) + 1
            continue
        if store.termin_manuell_vorhanden(bsn, vorschlag["start_datum"], vorschlag["titel"]):
            ergebnis["verworfen"]["dublette"] = ergebnis["verworfen"].get("dublette", 0) + 1
            continue
        if not dry_run:
            tid = store.upsert_termin_manuell({
                "schule_bsn": bsn, "titel": vorschlag["titel"],
                "start_datum": vorschlag["start_datum"], "start_zeit": vorschlag["start_zeit"],
                "beschreibung": None, "url": fenster_url,
                "status": "ungeprueft",
                "quelle_hinweis": (f"LLM-Recherche {datetime.now(TZ_BERLIN):%d.%m.%Y} · "
                                   f"{fenster_url} · Modell {antwort.get('modell')} · "
                                   f"Zitat: „{vorschlag['beleg'][:180]}\""),
            })
            ergebnis["vorschlaege"].append(tid)
        ergebnis["n_belegt"] += 1
    ergebnis["status"] = STATUS_GEFUNDEN if ergebnis["n_belegt"] else STATUS_KEIN_FUND
    if not ergebnis["n_belegt"] and ergebnis["n_roh"]:
        ergebnis["grund"] = ", ".join(f"{k}×{v}" for k, v in ergebnis["verworfen"].items())
    return ergebnis


def lauf(store, *, limit: int = 20, nur_bsn: str | None = None, dry_run: bool = False,
         bezirk: str | None = None, schulform: str | None = None,
         konfig: dict | None = None, client: httpx.Client | None = None) -> dict:
    """Recherche-Lauf über die am längsten ungeprüften Schulen."""
    from .llm import konfiguration
    konfig = konfig or konfiguration(store)
    eigene = client is None
    c = client or httpx.Client(timeout=30.0, follow_redirects=True)
    heute = datetime.now(TZ_BERLIN).date()
    t0 = time.time()
    kandidaten = schul_kandidaten(store, limit=limit, nur_bsn=nur_bsn,
                                  bezirk=bezirk, schulform=schulform)
    zusammen = {"geprueft": 0, "schulen": [], "llm_calls": 0, "belegt": 0,
                "verworfen": {}, "fehler": 0, "status": {},
                "start": datetime.now(TZ_BERLIN).isoformat(timespec="seconds"),
                "dauer_s": 0.0, "limit": limit, "dry_run": dry_run,
                "bezirk": bezirk, "schulform": schulform}
    try:
        for schule in kandidaten:
            erg = verarbeite_schule(store, schule, konfig, c, heute, dry_run=dry_run)
            zusammen["geprueft"] += 1
            zusammen["llm_calls"] += erg["llm_calls"]
            zusammen["belegt"] += erg["n_belegt"]
            if erg["status"] in (STATUS_FEHLER, STATUS_ABRUF):
                zusammen["fehler"] += 1
            zusammen["status"][erg["status"]] = zusammen["status"].get(erg["status"], 0) + 1
            for k, v in erg["verworfen"].items():
                zusammen["verworfen"][k] = zusammen["verworfen"].get(k, 0) + v
            zusammen["schulen"].append(erg)
            if not dry_run:
                store.set_schule_recherche(
                    erg["bsn"], erg["status"],
                    f"{erg['n_belegt']} belegt / {erg['n_roh']} roh"
                    + (f" · {erg['grund']}" if erg["grund"] else ""))
                store.log_recherche_lauf({
                    "bsn": erg["bsn"], "url": erg.get("url"), "seiten_hash": None,
                    "modell": erg.get("modell"), "n_roh": erg["n_roh"],
                    "n_belegt": erg["n_belegt"],
                    "verworfen_grund": (", ".join(f"{k}×{v}" for k, v in erg["verworfen"].items())
                                        or None),
                    "dauer_s": None, "erstellt_am": datetime.now(TZ_BERLIN).isoformat(timespec="seconds"),
                })
            print(f"[recherche] {erg['bsn']} {erg['status']}: "
                  f"{erg['n_belegt']}/{erg['n_roh']} belegt"
                  + (f" · {erg['grund']}" if erg["grund"] else ""), flush=True)
    finally:
        if eigene:
            c.close()
    zusammen["dauer_s"] = round(time.time() - t0, 1)
    return zusammen
