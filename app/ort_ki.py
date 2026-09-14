"""LLM-Ortsprüfung (Change 022) — Vorschläge für Termine ohne Ortsnamen.

Eigene Stufe **nach** der deterministischen Pipeline. Die Adapter bleiben
LLM-frei (Invariante in `app/adapters/__init__.py`); hier wird nur
**vorgeschlagen**. Die Ergebnisse landen in `ort_vorschlaege` und werden erst
nach menschlicher Prüfung in die Ortsfelder übernommen (Nutzerentscheid
14.09.2026: „eigener Wert mit Kennzeichnung plus manueller Check").

Ablauf je Termin:

1. Kandidat bestimmen: kein Ortsname (Straße, generisch, leer) oder keine Position.
2. Text besorgen: Seitenquelle (`typ: regeln`) → Detailseite über die Regeln,
   Text der Felder + Abschnitt; Feed-/Intern-Quelle → gespeicherte Beschreibung.
3. Modell fragen (Prompt v2, Endpunkt im Admin konfigurierbar): ort/adresse/
   treffpunkt/beleg.
4. Prüfen: Steht der **Name** wörtlich im Seitentext (das Zitat ist nur der
   Zeiger — der reine Zitat-Test verwirft korrekte Vorschläge, gemessen
   14.09.: 7 von 7)? Ist der Wert ein Bezirksname, generisch, kein Gewinn?
   Abstand zwischen Vorschlag und Adresse (Nominatim, gecacht) als Band.
5. Vorschlag speichern — nie übernehmen.

Fehler werden gezählt und benannt (kein stiller Teil-Lauf). Gemessen
14.09.2026: 839 Termine ≈ 56 min, 0 Modellfehler, 828 brauchbare Vorschläge.
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime
from difflib import SequenceMatcher

import httpx
from parsel import Selector

from .adapters import build_adapter
from .adapters.selector_adapter import _LABEL_ZU_SLUG
from .geo import adresse_amtlich, ort_koordinaten
from .model import TZ_BERLIN
from .orte import ist_generisch
from .recherche import llm as llm_mod

# Wortlaut wie im gemessenen Schattenlauf (Prompt v2). Änderungen hier ändern
# das Verhalten der Stufe — bitte mit Messung, nicht im Vorbeigehen.
PROMPT = """Du liest die Detailseite einer Berliner Veranstaltung für Familien.
Nenne den ORT: die Einrichtung oder das Gelände, wo die Veranstaltung stattfindet.

Wichtig zum Feld "Ort/Treffpunkt": Es enthält häufig eine Adresse und danach einen
Teilbereich (z. B. "Besuchszentrum", "Eingang", "Kasse", "Werkstatt", "Pavillon")
oder einen Treffpunkt. Ein Teilbereich ist NICHT der Ort — nenne die Einrichtung,
zu der er gehört. Steht die Einrichtung nicht in diesem Feld, nimm sie aus dem
Feld "Anbieter" oder aus dem Beschreibungstext (Beispiel: der Text sagt
"... ist der Botanische Garten Berlin ..." → Ort = "Botanischer Garten").
Haltestellen oder Parkplätze ("S Rummelsburg", "Parkplatz am Hüttenweg") sind
Treffpunkte, nicht der Ort, wenn eine Einrichtung erkennbar ist.

Antworte AUSSCHLIESSLICH mit JSON, ohne Erklärung:
{{"ort": "<Einrichtung/Gelände>" oder null,
 "adresse": "<Straße und Hausnummer>" oder null,
 "treffpunkt": "<Teilbereich/Treffpunkt aus dem Feld>" oder null,
 "beleg": "<wörtliches Zitat aus dem Text, das den Ort belegt>" oder null}}

Nur was wirklich im Text steht. Keine Vermutung, keine Ableitung aus dem Bezirk.
Ist keine Einrichtung erkennbar, ist "ort" null.

Text:
{text}"""

# Zusätzlich zu app.orte._GENERISCH: Werte, die im Ortsfeld wie ein Ort aussehen,
# aber keiner sind (gemessen im Bestand).
GENERISCH_ZUSATZ = {"berlinweit", "vielerorts", "in ganz berlin", "berlinweit verteilt"}

VERBOTEN = re.compile(r"^(unser|unsere|unserem|unseren|der|die|das|dem|den|ein|eine|"
                      r"hier|dort|vor|beim|am|im|zum|zur)\b", re.I)
LAGEWORT = re.compile(r"\s+(?:direkt\s+)?(?:vor|am|an|beim|bei|im|in|auf|gegenüber|neben|"
                      r"hinter|zwischen|Ecke|Nähe|nähe|hinterm|vorm)\s+", re.I)
ZIFFER = re.compile(r"\d")
ZITAT_MINDESTAEHNLICHKEIT = 0.80


def ist_kandidat(ev: dict) -> bool:
    """Termin ohne brauchbaren Ortsnamen oder ohne Position?"""
    ort = (ev.get("ort") or "").strip()
    ohne_pos = not (ev.get("lat") and ev.get("lon"))
    ohne_name = (not ort or ist_generisch_oder_zusatz(ort) or bool(ZIFFER.search(ort)))
    return ohne_pos or ohne_name


def ist_generisch_oder_zusatz(wert: str) -> bool:
    w = (wert or "").strip().lower()
    return ist_generisch(wert) or w in GENERISCH_ZUSATZ


def ist_bezirksname(wert: str) -> bool:
    """Bezirks-/Stadtname oder Liste davon — kein Veranstaltungsort (Change 019)."""
    teile = [t.strip() for t in re.split(r"[,/]|\bund\b", wert or "") if t.strip()]
    if not teile:
        return False
    treffer = sum(1 for t in teile
                  if (_LABEL_ZU_SLUG.get(t.lower()) or "unbekannt") != "unbekannt")
    return treffer == len(teile) or (treffer >= 2 and len(teile) <= 5)


def seiten_text(detail: dict, html: str, max_zeichen: int = 6000) -> str:
    """Text für das Modell: Felder der Regel + Abschnittstext der Seite."""
    teile = [f"{k}: {v}" for k, v in detail.items()
             if isinstance(v, str) and v.strip()]
    sel = Selector(html)
    for css in ("section.veranstaltungsdetail ::text", ".veranstaltung ::text",
                "main ::text", "#content ::text"):
        roh = re.sub(r"\s+", " ", " ".join(sel.css(css).getall())).strip()
        if len(roh) > 200:
            teile.append(roh[:4000])
            break
    return "\n".join(teile)[:max_zeichen]


def abstand_band(meter: float | None) -> str:
    """Abstandsbänder statt binärer Schwelle (Parks/Campus sind groß)."""
    if meter is None:
        return "n/v"
    if meter <= 300:
        return "an derselben Adresse"
    if meter <= 1000:
        return "gleiche Anlage"
    return "nicht ortsgleich"


def _distanz(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def antwort_lesen(text: str) -> dict:
    """JSON aus der Modellantwort ziehen (wirft nichts, meldet Fehler als Wert)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {"fehler": f"kein JSON in der Antwort: {(text or '')[:80]!r}"}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return {"fehler": f"JSON unlesbar: {e}"}
    return d if isinstance(d, dict) else {"fehler": "Antwort ist kein Objekt"}


def name_belegt(name: str, text: str) -> bool:
    """Steht der vorgeschlagene Name wörtlich im Text? (stärker als der Zitat-Test)"""
    n = re.sub(r"\s+", " ", (name or "")).strip().lower()
    return bool(n) and n in re.sub(r"\s+", " ", text or "").lower()


def zitat_aehnlich(zitat: str, text: str) -> float:
    """Ähnlichkeit des Zitats zum Text (0..1) — für die Anzeige, nicht als K.o.-Kriterium."""
    z = re.sub(r"\s+", " ", (zitat or "")).strip().lower()
    t = re.sub(r"\s+", " ", text or "").lower()
    if not z or not t:
        return 0.0
    kern = z[:120]
    i = t.find(kern.split()[0]) if kern.split() else -1
    if i < 0:
        return 0.0
    return SequenceMatcher(None, kern, t[i:i + len(kern) + 20]).ratio()


def belegherkunft(beleg: str) -> str:
    b = beleg or ""
    if re.search(r"\bAnbieter\s*:", b):
        return "Anbieter-Feld"
    if re.search(r"Ort/Treffpunkt|Veranstaltungsort|Treffpunkt", b):
        return "Ort-Feld"
    return "Fließtext"


def plausibel(ort: str, belegt: bool, ort_jetzt: str) -> tuple[bool, str]:
    """Automatischer Filter VOR der Prüfliste (Regeln aus dem gemessenen Lauf)."""
    ort = (ort or "").strip()
    if not ort:
        return False, "kein Ortsname"
    if not belegt:
        return False, "kein Beleg (Name steht nicht auf der Seite)"
    if ist_generisch_oder_zusatz(ort):
        return False, "generische Angabe"
    if ist_bezirksname(ort.split(" (")[0]):
        return False, "Bezirksname statt Ort"
    if not ort[0].isupper():
        return False, "beginnt klein"
    if VERBOTEN.match(ort):
        return False, "Satzfragment/Pronomen"
    if not (3 <= len(ort) <= 90):
        return False, "Länge unplausibel"
    if ort.split(" (")[0].strip().lower() == (ort_jetzt or "").strip().lower():
        return False, "kein Gewinn (wie bisher)"
    return True, "ok"


def vorschlag_bauen(store, ev: dict, detail: dict, text: str, roh: dict,
                    modell: str, herkunft: str, client: httpx.Client | None) -> dict | None:
    """Prüft eine Modellantwort und baut den Vorschlagsdatensatz (None = verworfen)."""
    ort = (roh.get("ort") or "").strip()
    adresse = (roh.get("adresse") or "").strip()
    treffpunkt = (roh.get("treffpunkt") or "").strip()
    beleg = (roh.get("beleg") or "").strip()
    belegt = name_belegt(ort, text) if ort else False
    # Lagebeschreibung auf den Namen kürzen ("Gendarmenmarkt direkt vor …")
    m = LAGEWORT.search(ort)
    if m and len(ort[:m.start()].strip()) >= 3:
        rest = ort[m.start():].strip()
        treffpunkt = f"{rest}{' · ' + treffpunkt if treffpunkt else ''}"
        ort = ort[:m.start()].strip()
    ok, grund = plausibel(ort, belegt, ev.get("ort") or "")
    if not ok:
        return None
    # Abstand: Name gegen die bekannte Adresse (Vorschlag zuerst, sonst Bestand)
    meter = None
    adr_vergleich = (ev.get("adresse") or "").strip() or adresse
    if ort and adr_vergleich:
        ko_ort = ort_koordinaten(store, ort, client=client)
        teile = adresse_teile_holen(store, adr_vergleich, client)
        if ko_ort and teile:
            meter = _distanz((ko_ort["lat"], ko_ort["lon"]), teile)
    return {
        "event_id": ev["id"], "quelle": ev["quelle"], "ort_vorschlag": ort,
        "adresse_vorschlag": adresse, "treffpunkt": treffpunkt, "beleg": beleg,
        "belegherkunft": belegherkunft(beleg), "abstand_m": round(meter) if meter else None,
        "ortsband": abstand_band(meter), "name_im_text": belegt, "modell": modell,
        "herkunft": herkunft,
    }


def adresse_teile_holen(store, adresse: str, client: httpx.Client | None):
    """Koordinaten der Adresse (amtlicher WFS, gecacht) als Tupel."""
    try:
        d = adresse_amtlich(store, adresse, client=client)
    except Exception:
        return None
    if not d or not d.get("lat"):
        return None
    return (d["lat"], d["lon"])


def lauf(store, *, quelle: str | None = None, limit: int | None = None,
         fortschritt=None, llm_chat=None) -> dict:
    """Vorschläge für alle Kandidaten erzeugen. Rückgabe: Zähler + Fehlerliste.

    `llm_chat` erlaubt Tests, den Modellaufruf zu ersetzen (Muster:
    `chat(konfig, prompt)` → {"text": …}).
    """
    konfig = llm_mod.konfiguration(store)
    modell = konfig.get("llm_model") or "?"
    chat = llm_chat or (lambda p: llm_mod.chat(konfig, p, max_tokens=700))
    zaehler: dict = {"kandidaten": 0, "geprueft": 0, "vorschlaege": 0, "leer": 0,
                     "zu_kurz": 0, "abruf_fehler": 0, "llm_fehler": 0, "verworfen": 0}
    fehler: list[dict] = []
    quellen = [quelle] if quelle else [s["quelle"] for s in store.list_sources()
                                       if s.get("aktiv")]
    zeilen: list[dict] = []
    with httpx.Client(timeout=60, follow_redirects=True,
                      headers={"User-Agent": "kinderkram-aggregator/1.0 "
                                             "(+https://kinderkram.cia-spandau.de)"}) as c:
        for q in quellen:
            try:
                src = store.get_source(q) or {}
                adapter = build_adapter(store, q) if src.get("typ") == "regeln" else None
            except ValueError as e:
                fehler.append({"quelle": q, "fehler": f"Adapter nicht baubar: {e}"})
                continue
            evs = [e for e in store.list_events_admin(quelle=q, limit=5000)
                   if ist_kandidat(e)]
            if limit:
                evs = evs[:int(limit)]
            zaehler["kandidaten"] += len(evs)
            for i, ev in enumerate(evs, 1):
                detail, text = {}, (ev.get("beschreibung_kurz") or "").strip()
                if adapter is not None:
                    try:
                        html = c.get(ev["source_url"]).text
                        detail = adapter.parse_detail(html)
                        text = seiten_text(detail, html)
                        time.sleep(1.2)          # Quelle schonen
                    except Exception as ex:
                        zaehler["abruf_fehler"] += 1
                        fehler.append({"quelle": q, "titel": ev.get("titel"),
                                       "fehler": f"Abruf: {type(ex).__name__}"})
                        continue
                if len(text) < 200:
                    zaehler["zu_kurz"] += 1
                    continue
                try:
                    antwort = chat(PROMPT.format(text=text))
                except Exception as ex:
                    zaehler["llm_fehler"] += 1
                    fehler.append({"quelle": q, "titel": ev.get("titel"),
                                   "fehler": f"Modell: {type(ex).__name__}: {ex}"})
                    time.sleep(2)
                    continue
                roh = antwort_lesen(antwort.get("text", "") if isinstance(antwort, dict) else "")
                if roh.get("fehler"):
                    zaehler["llm_fehler"] += 1
                    fehler.append({"quelle": q, "titel": ev.get("titel"),
                                   "fehler": roh["fehler"]})
                    continue
                zaehler["geprueft"] += 1
                if not (roh.get("ort") or roh.get("adresse")):
                    zaehler["leer"] += 1
                    continue
                v = vorschlag_bauen(store, ev, detail, text, roh, modell,
                                    "Lauf im Admin", c)
                if v is None:
                    zaehler["verworfen"] += 1
                    continue
                zeilen.append(v)
                zaehler["vorschlaege"] += 1
                if fortschritt and i % 10 == 0:
                    fortschritt(q, i, len(evs), zaehler.copy())
    zaehler["neu_gespeichert"] = store.ort_vorschlaege_speichern(zeilen)
    zaehler["modell"] = modell
    zaehler["beendet_am"] = datetime.now(TZ_BERLIN).isoformat(timespec="seconds")
    zaehler["fehler_liste"] = fehler[:50]
    store.set_setting("ort_ki_letzter_lauf", json.dumps(zaehler, ensure_ascii=False))
    return zaehler


def letzter_lauf(store) -> dict:
    """Ergebnis des letzten Laufs (aus den Einstellungen)."""
    roh = store.get_setting("ort_ki_letzter_lauf")
    if not roh:
        return {}
    try:
        return json.loads(roh)
    except json.JSONDecodeError:
        return {}
