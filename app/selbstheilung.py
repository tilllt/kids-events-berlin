"""Selbstheilung kaputter Scraper-Regeln (Change 017) — Erkennung und Diagnose.

Grundsatz: Geheilt wird nur, was **nachweislich kaputt** ist. Ein Rückgang der
Trefferzahl ist kein Defekt — ein Kalender darf saisonal oder nach dem Ende von
Terminen weniger anbieten. Eine kleinere Zahl löst deshalb nur die kostenlose
Diagnose aus; erst wenn die Diagnose zeigt, dass unsere Selektoren nicht mehr
passen (die Seite enthält weiterhin Termin-artige Einträge, `item_css` findet
aber nichts), gilt der Fehler als bewiesen und ein Reparaturvorschlag darf
entstehen.

Das LLM schreibt dabei **nie Code und nie neue Domains** — es ändert Regeln
(YAML), und zwar erst nach dem Prüf-Gate (Change 017, Phase 2).
"""
from __future__ import annotations

import re

import parsel
import yaml

FEHLERQUOTE = 0.30          # Anteil fehlerhafter Zeilen ab dem es ein Defekt ist
FEHLER_ABSOLUT = 10         # oder so viele Fehler in einem Lauf
STATUS_UMGEZOGEN = (404, 410)
STATUS_GESPERRT = (401, 402, 403, 429)

# Deutsches Datum in Textform — Signal, dass eine Seite noch Termine enthält.
# Ohne führende Wortgrenze: parsel klebt Textknoten ohne Leerzeichen zusammen
# („Fest 0" + „10.09.2026" → „Fest 010.09.2026"), das Datum muss trotzdem zählen.
DATUM_RX = re.compile(r"\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4}(?!\d)")

ARTEN = ("url_umgezogen", "gesperrt", "selektoren_tot", "fehlerquote", "pflichtfeld")


def status_aus_fehler(text: str = "") -> int | None:
    """HTTP-Status aus einer Fehlermeldung ziehen („… 404 …")."""
    m = re.search(r"\b([1-5]\d\d)\b", text or "")
    return int(m.group(1)) if m else None


def regeln_lesen(regeln: str) -> dict:
    try:
        d = yaml.safe_load(regeln or "") or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def item_css_aus(regeln: str) -> str | None:
    """Der Selektor, der die Termin-Blöcke auf der Listing-Seite auswählt."""
    listing = regeln_lesen(regeln).get("listing") or {}
    css = (listing.get("item_css") or "").strip()
    return css or None


def feld_selektoren_aus(regeln: str) -> dict[str, str]:
    """Feld → CSS-Selektor der Listing-Regeln (nur css, kein xpath/jsonld)."""
    felder = ((regeln_lesen(regeln).get("listing") or {}).get("felder") or {})
    out = {}
    for feld, regel in felder.items():
        if isinstance(regel, dict) and (regel.get("css") or "").strip():
            out[feld] = regel["css"].strip()
    return out


def _terminartige_links(sel: parsel.Selector) -> int:
    """Wie viele Links stehen in einem Umfeld mit Datum?

    Beweismittel: findet `item_css` nichts, die Seite hat aber weiterhin
    datierte Einträge, ist nicht die Quelle leer — unser Selektor passt nicht
    mehr. Das ist der Unterschied zwischen „weniger Termine" und „kaputt".
    """
    n = 0
    for a in sel.css("a"):
        eigen = (a.xpath("string(.)").get() or "")[:200]
        if DATUM_RX.search(eigen):
            n += 1
            continue
        vater = a.xpath("..")
        umfeld = (vater.xpath("string(.)").get() or "")[:400] if vater else ""
        if DATUM_RX.search(umfeld):
            n += 1
    return n


def diagnose(*, regeln: str, html: str, url: str = "",
             archiv_html: str | None = None) -> dict:
    """Fakten für Admin und Modell: welche Selektoren treffen noch?"""
    item_css = item_css_aus(regeln)
    d: dict = {
        "url": url,
        "seiten_groesse": len(html or ""),
        "item_css": item_css,
        "item_treffer": 0,
        "felder": {},
        "terminartige_links": 0,
        "archiv_item_treffer": None,
        "urteil": "unklar",
    }
    if not html:
        d["urteil"] = "seite_nicht_abrufbar"
        return d
    sel = parsel.Selector(text=html)
    items = sel.css(item_css) if item_css else []
    d["item_treffer"] = len(items)
    if items:
        for feld, css in feld_selektoren_aus(regeln).items():
            try:
                d["felder"][feld] = len(items[0].css(css))
            except Exception:
                d["felder"][feld] = 0
    d["terminartige_links"] = _terminartige_links(sel)
    if archiv_html and item_css:
        try:
            d["archiv_item_treffer"] = len(parsel.Selector(text=archiv_html).css(item_css))
        except Exception:
            d["archiv_item_treffer"] = None

    if d["item_treffer"] == 0 and d["terminartige_links"] >= 3:
        d["urteil"] = "selektoren_tot_aber_inhalt_da"
    elif d["item_treffer"] == 0:
        d["urteil"] = "seite_ohne_terminangebot"
    elif (d["archiv_item_treffer"] or 0) > d["item_treffer"]:
        d["urteil"] = "weniger_treffer_als_frueher"
    else:
        d["urteil"] = "selektoren_funktionieren"
    return d


def befund_ermitteln(*, regeln: str = "", html: str | None = None,
                     roh_zeilen: int = 0, n_zeilen: int = 0, n_fehler: int = 0,
                     archiv_treffer: int | None = None,
                     http_fehler: str = "") -> dict | None:
    """Liegt ein Fehler vor? (None = kein Fehler — auch bei weniger Terminen.)"""
    status = status_aus_fehler(http_fehler)
    if status in STATUS_UMGEZOGEN:
        return {"art": "url_umgezogen", "status": status,
                "text": f"Listing-Seite antwortet mit {status}", "zahlen": {}}
    if status in STATUS_GESPERRT:
        return {"art": "gesperrt", "status": status,
                "text": f"Zugriff abgelehnt ({status}) — nicht reparierbar",
                "zahlen": {}}
    if not http_fehler and roh_zeilen == 0 and (archiv_treffer or 0) > 0:
        return {"art": "selektoren_tot", "status": None,
                "text": "Seite erreichbar, aber kein Termin-Block passt noch",
                "zahlen": {"frueher": archiv_treffer}}
    if n_fehler >= FEHLER_ABSOLUT or (n_zeilen and n_fehler / max(n_zeilen, 1) >= FEHLERQUOTE):
        return {"art": "fehlerquote", "status": None,
                "text": f"{n_fehler} von {n_zeilen} gelesenen Zeilen sind fehlerhaft",
                "zahlen": {"n_fehler": n_fehler, "n_zeilen": n_zeilen}}
    return None


# ---------------------------------------------------------------------------
# Phase 2: LLM-Vorschlag + Prüf-Gate
# ---------------------------------------------------------------------------

MARKER_AUF = "===REGELN==="
MARKER_ZU = "===ENDE==="
HTML_AUSSCHNITT = 12000
REGRESSION_ANTEIL = 0.80      # muss auf der alten Seite mindestens so viel finden
MIN_TREFFER = 3               # und heute mindestens so viele Termine
MAX_TREFFER = 200             # darüber ist der Selektor absurd grob (Wildcard)

PROMPT_KOPF = """Du reparierst die Lese-Regeln (YAML) eines Termin-Scrapers. \
Die Quelle hat ihre HTML-Struktur geändert, die Regeln finden keine Termine mehr.

HARTE REGELN:
- Antworte NUR mit dem YAML zwischen {auf} und {zu}, danach ein Absatz "Begruendung:".
- Erlaubte Abschnitte: quelle, robots, listing, detail, standard.
- Erlaubte Listing-Felder: {felder}.
- Ändere Selektoren; die Quelle bleibt "{quelle}" und alle URLs bleiben auf
  der Domain {domain}. Keine Kommentare, keine Erklärungen im YAML."""


def html_ausschnitt(html: str, max_zeichen: int = HTML_AUSSCHNITT) -> str:
    """Relevanten Teil der Seite zeigen: Umgebung der ersten datierten Einträge.

    Das ganze HTML sprengt den Kontext und verwässert; der Bereich, in dem noch
    Termine stehen, ist das eigentliche Beweismittel.
    """
    if not html:
        return ""
    if len(html) <= max_zeichen:
        return html
    try:
        sel = parsel.Selector(text=html)
        for a in sel.css("a"):
            umfeld = a.xpath("string(ancestor::*[position()<=4])").get() or ""
            if DATUM_RX.search(umfeld or ""):
                knoten = a.xpath("ancestor::*[position()<=2]")
                roh = "".join(k.get() or "" for k in knoten[-1:]) or ""
                if len(roh) > 400:
                    return roh[:max_zeichen]
                break
    except Exception:
        pass
    hälfte = max_zeichen // 2
    return html[:hälfte] + "\n<!-- … gekürzt … -->\n" + html[-hälfte:]


def prompt_bauen(*, quelle: str, regeln: str, diagnose: dict, befund: dict,
                 html: str, erlaubte_felder: list[str]) -> str:
    domain = ""
    m = re.search(r"https?://([^/\s\"']+)", regeln or "")
    if m:
        domain = m.group(1)
    kopf = PROMPT_KOPF.format(auf=MARKER_AUF, zu=MARKER_ZU, quelle=quelle,
                              domain=domain or "(unverändert)",
                              felder=", ".join(erlaubte_felder))
    d = diagnose or {}
    felder = ", ".join(f"{k}: {v}×" for k, v in (d.get("felder") or {}).items()) or "—"
    teile = [
        kopf,
        "\nAKTUELLE REGELN:\n" + (regeln or "").strip(),
        "\nBEFUND (gemessen, nicht geschätzt):",
        f"- item_css {d.get('item_css')!r} trifft {d.get('item_treffer')} Blöcke"
        f" (früher {d.get('archiv_item_treffer')})",
        f"- Die Seite enthält weiterhin {d.get('terminartige_links')} Einträge mit Datum",
        f"- Seitengröße {d.get('seiten_groesse')} Zeichen",
        f"- Feld-Treffer im ersten Block: {felder}",
        f"- Befund: {befund.get('art')} — {befund.get('text')}",
        "\nHTML-AUSSCHNITT DER AKTUELLEN SEITE:\n" + html_ausschnitt(html),
        f"\nAntworte jetzt mit {MARKER_AUF}, dem vollständigen YAML, {MARKER_ZU} "
        f"und einem Absatz \"Begruendung:\".",
    ]
    return "\n".join(teile)


def yaml_aus_antwort(text: str) -> str | None:
    """Regeln aus der LLM-Antwort ziehen (Marker, sonst Codeblock)."""
    t = text or ""
    if MARKER_AUF in t and MARKER_ZU in t:
        roh = t.split(MARKER_AUF, 1)[1].split(MARKER_ZU, 1)[0]
    else:
        m = re.search(r"```(?:yaml)?\s*(.*?)```", t, re.S)
        roh = m.group(1) if m else ""
    roh = roh.strip()
    if not roh:
        return None
    try:
        doc = yaml.safe_load(roh)
    except Exception:
        return None
    return roh if isinstance(doc, dict) else None


def begruendung_aus_antwort(text: str) -> str:
    t = (text or "").split(MARKER_ZU, 1)[-1]
    m = re.search(r"Begr[üu]ndung\s*:?\s*(.+)", t, re.S | re.I)
    return (m.group(1).strip()[:1500] if m else "")


def zeilen_mit_regeln(regeln: str, html: str, quelle: str) -> list[dict]:
    """Listing mit vorgegebenen Regeln parsen (für Probelauf und Regression)."""
    from .adapters.selector_adapter import SelectorAdapter
    a = SelectorAdapter(quelle, regel_yaml=regeln)
    try:
        return a.parse_listing(html or "")
    finally:
        a.close()


def gate(*, neu_yaml: str, alt_yaml: str, quelle: str, html_heute: str,
         html_alt: str | None, treffer_alt: int | None,
         holen=None) -> dict:
    """Prüft einen Vorschlag ohne LLM. Ergebnis: {ok, beleg, fehler}."""
    beleg: dict = {"pruefungen": [], "treffer_heute": None, "treffer_alt": None,
                   "felder": {}}
    fehler: list[str] = []

    def pruefung(name: str, ok: bool, info: str = "") -> bool:
        beleg["pruefungen"].append({"pruefung": name, "ok": bool(ok), "info": info})
        if not ok:
            fehler.append(f"{name}: {info}" if info else name)
        return ok

    # 1) Regeln formal gültig
    from .regeln import validate_regeln_yaml
    vfehler = validate_regeln_yaml(neu_yaml or "")
    if not pruefung("Regeln gültig", not vfehler, "; ".join(vfehler[:3])):
        return {"ok": False, "beleg": beleg, "fehler": fehler}

    # 2) Quelle und Domain unverändert, kein Code
    doc = regeln_lesen(neu_yaml)
    alt_doc = regeln_lesen(alt_yaml)
    if not pruefung("Quellenname unverändert", doc.get("quelle") == alt_doc.get("quelle"),
                    f"{alt_doc.get('quelle')} → {doc.get('quelle')}"):
        return {"ok": False, "beleg": beleg, "fehler": fehler}
    alt_url = ((alt_doc.get("listing") or {}).get("url") or "")
    neu_url = ((doc.get("listing") or {}).get("url") or "")
    dom_alt = re.sub(r"^https?://([^/\s\"']+).*", r"\1", alt_url)
    dom_neu = re.sub(r"^https?://([^/\s\"']+).*", r"\1", neu_url)
    if not pruefung("Domain unverändert",
                    bool(dom_neu) and (dom_neu == dom_alt or neu_url == alt_url),
                    f"{dom_alt} → {dom_neu}"):
        return {"ok": False, "beleg": beleg, "fehler": fehler}

    # 3) Probelauf: die neuen Regeln müssen die Seiten finden
    html_fuer_probe = html_heute
    if holen is not None and neu_url and neu_url != alt_url:
        try:                                  # umgezogene Listing-Seite wirklich holen
            html_fuer_probe = holen(neu_url)
        except Exception as e:
            pruefung("Umgezogene Seite abrufbar", False, str(e)[:120])
            return {"ok": False, "beleg": beleg, "fehler": fehler}
    try:
        zeilen = zeilen_mit_regeln(neu_yaml, html_fuer_probe, quelle)
    except Exception as e:
        pruefung("Probelauf", False, f"Parsen schlug fehl: {str(e)[:120]}")
        return {"ok": False, "beleg": beleg, "fehler": fehler}
    n_min = max(MIN_TREFFER, int((treffer_alt or 0) * 0.5))
    beleg["treffer_heute"] = len(zeilen)
    if not pruefung("Probelauf heute", len(zeilen) >= n_min,
                    f"{len(zeilen)} Treffer, gefordert {n_min}"):
        return {"ok": False, "beleg": beleg, "fehler": fehler}

    # 4) Pflichtfelder gefüllt
    mit_titel = sum(1 for z in zeilen if (z.get("titel") or "").strip())
    mit_start = sum(1 for z in zeilen if z.get("start"))
    beleg["felder"] = {"titel": mit_titel, "start": mit_start, "zeilen": len(zeilen)}
    if not pruefung("Pflichtfelder", mit_titel >= n_min and mit_start >= n_min,
                    f"Titel {mit_titel}, Start {mit_start} von {n_min} gefordert"):
        return {"ok": False, "beleg": beleg, "fehler": fehler}

    # 5) Wildcard-Schutz: ein zu grober Selektor (LLM-Klassiker „div" oder „*")
    #    zöge Seiten-Gerüst als Termine herein. Absurd viele Treffer werden
    #    abgelehnt; verdächtig viele (deutlich mehr als die Quelle früher
    #    hergab) werden im Beleg ausgewiesen — bei Stufe 1 entscheidet der
    #    Admin, und eine harte Grenze würde echtes Wachstum einer Quelle
    #    fälschlich blockieren.
    #    BEWUSST nicht geprüft wird, ob der Vorschlag auf der ALTEN Seite noch
    #    Treffer hat: dort gilt die alte Struktur, eine richtige Reparatur
    #    findet dort nichts (Denkfehler der ersten Fassung).
    beleg.setdefault("warnungen", [])
    if not pruefung("Kein absurd grober Selektor", len(zeilen) <= MAX_TREFFER,
                    f"{len(zeilen)} Treffer heute (Grenze {MAX_TREFFER})"):
        return {"ok": False, "beleg": beleg, "fehler": fehler}
    if treffer_alt and len(zeilen) > max(20, int(treffer_alt * 3)):
        beleg["warnungen"].append(
            f"{len(zeilen)} Treffer heute statt früher {treffer_alt} — "
            f"Selektor möglicherweise zu grob, bitte Beleg prüfen")
    if html_alt and treffer_alt:
        try:
            alt_zeilen = zeilen_mit_regeln(neu_yaml, html_alt, quelle)
            beleg["treffer_alt"] = len(alt_zeilen)
            if len(alt_zeilen) > MAX_TREFFER:
                beleg["warnungen"].append(
                    f"{len(alt_zeilen)} Blöcke auf der archivierten Seite — "
                    f"Selektor möglicherweise zu grob")
        except Exception as e:
            beleg["treffer_alt"] = None
            beleg["pruefungen"].append({"pruefung": "Gegenprobe auf archivierter Seite",
                                        "ok": True,
                                        "info": f"nicht messbar: {str(e)[:80]}"})
    else:
        beleg["pruefungen"].append({"pruefung": "Gegenprobe auf archivierter Seite",
                                    "ok": True, "info": "kein Archiv vorhanden"})

    return {"ok": not fehler, "beleg": beleg, "fehler": fehler}


def vorschlag_erzeugen(*, quelle: str, regeln: str, befund: dict, diagnose: dict,
                       html: str, erlaubte_felder: list[str],
                       llm_ruf) -> dict | None:
    """LLM fragen und einen prüfbaren Vorschlag zurückgeben (oder None)."""
    prompt = prompt_bauen(quelle=quelle, regeln=regeln, diagnose=diagnose,
                          befund=befund, html=html, erlaubte_felder=erlaubte_felder)
    text = llm_ruf(prompt)
    neu = yaml_aus_antwort(text or "")
    if not neu:
        return None
    return {"yaml": neu, "begruendung": begruendung_aus_antwort(text or ""),
            "antwort": (text or "")[:4000], "prompt": prompt}


def heilen(store, *, quelle: str, befund: dict, diagnose: dict, html: str,
           jetzt: str, llm_ruf=None, holen=None,
           heilung_id: int | None = None) -> dict | None:
    """Vorschlag erzeugen, prüfen, ablegen — ohne die Regeln zu ändern.

    Übernommen wird erst durch den Admin (Stufe 1). Gesperrte Quellen werden
    nicht behandelt: eine Umgehung wäre falsch.
    """
    if befund.get("art") in ("gesperrt", "verdacht"):
        return None
    regeln = (store.get_regeln(quelle) or {}).get("regel_yaml") or ""
    if not regeln.strip():
        return None                       # interne Adapter haben keine YAML-Regeln
    if llm_ruf is None:
        from .recherche.llm import chat, konfiguration
        konf = konfiguration(store)
        if not (konf.get("llm_base_url") or "").strip():
            print(f"[heilung] {quelle}: kein LLM konfiguriert — Vorschlag entfällt",
                  flush=True)
            return None
        llm_ruf = lambda p: (chat(konf, p, max_tokens=2000) or {}).get("text", "")  # noqa: E731
    from .regeln import _LISTING_FELDER  # erlaubte Felder aus dem Regel-Schema
    v = vorschlag_erzeugen(quelle=quelle, regeln=regeln, befund=befund,
                           diagnose=diagnose, html=html,
                           erlaubte_felder=sorted(_LISTING_FELDER), llm_ruf=llm_ruf)
    archiv = store.seiten_archiv_holen(
        quelle, (((regeln_lesen(regeln).get("listing") or {}).get("url")) or ""))
    if v is None:
        print(f"[heilung] {quelle}: Modell lieferte keine brauchbaren Regeln", flush=True)
        if heilung_id:
            store.heilung_setzen(heilung_id, begruendung="Modell-Antwort ohne gültiges YAML",
                                 zeit=jetzt)
        return None
    pruef = gate(neu_yaml=v["yaml"], alt_yaml=regeln, quelle=quelle,
                 html_heute=html, html_alt=(archiv or {}).get("html"),
                 treffer_alt=(archiv or {}).get("treffer"), holen=holen)
    beleg = {**pruef["beleg"], "fehler": pruef["fehler"]}
    status = "vorgeschlagen" if pruef["ok"] else "verworfen"
    if heilung_id:
        store.heilung_setzen(heilung_id, status=status, vorschlag_yaml=v["yaml"],
                             begruendung=v["begruendung"], beleg=beleg, zeit=jetzt)
    else:
        heilung_id = store.heilung_anlegen(quelle, befund.get("art", "?"),
                                           {**befund, "diagnose": diagnose}, jetzt,
                                           status=status)
        store.heilung_setzen(heilung_id, vorschlag_yaml=v["yaml"],
                             begruendung=v["begruendung"], beleg=beleg, zeit=jetzt)
    kenn = "bestanden" if pruef["ok"] else "DURCHGEFALLEN"
    print(f"[heilung] {quelle}: Vorschlag {kenn} — "
          f"{beleg.get('treffer_heute')} Treffer heute, "
          f"{beleg.get('treffer_alt')} auf der archivierten Seite, "
          f"Fehler: {pruef['fehler'][:2]}", flush=True)
    return {"id": heilung_id, "ok": pruef["ok"], "beleg": beleg,
            "yaml": v["yaml"], "begruendung": v["begruendung"]}


def verdacht_ermitteln(*, roh_zeilen: int, n_zeilen: int = 0,
                       archiv_treffer: int | None = None) -> dict | None:
    """Rückgang ohne Fehler → nur Diagnose, kein Eingriff (kein Defektbeweis)."""
    if not archiv_treffer or archiv_treffer < 5:
        return None
    if roh_zeilen == 0:
        # Null Treffer bei vorhandenem Archiv ist bereits ein Fehler
        # (selektoren_tot), kein Verdachtsfall.
        return None
    if roh_zeilen * 2 >= archiv_treffer:      # weniger als die Hälfte früher?
        return None
    if n_zeilen == 0 and roh_zeilen > 0:      # alles weggefiltert = Fenster, kein Defekt
        return None
    return {"art": "verdacht", "status": None,
            "text": f"nur {roh_zeilen} Termine statt {archiv_treffer} — Ursache offen",
            "zahlen": {"jetzt": roh_zeilen, "frueher": archiv_treffer}}


def pruefen(store, *, quelle: str, regeln: str, url: str = "",
            html: str | None = None, roh_zeilen: int = 0, n_zeilen: int = 0,
            n_fehler: int = 0, http_fehler: str = "",
            jetzt: str = "") -> dict | None:
    """Nach dem Listing-Abruf: gesunde Seite archivieren, Fehler feststellen.

    Rückgabe: der Befund (Fehler) oder None. Ein Rückgang ohne Fehler hinterlässt
    höchstens einen Eintrag mit Status 'beobachtet' — es wird nichts geändert.
    """
    archiv = store.seiten_archiv_holen(quelle, url) if url else None
    archiv_treffer = archiv["treffer"] if archiv else None

    b = befund_ermitteln(regeln=regeln, html=html, roh_zeilen=roh_zeilen,
                         n_zeilen=n_zeilen, n_fehler=n_fehler,
                         archiv_treffer=archiv_treffer, http_fehler=http_fehler)

    # Gesunde Seiten ins Archiv: Grundlage der späteren Regressionsprobe.
    # Regel: das Archiv hält die STÄRKSTE bekannte gesunde Fassung. Sonst würde
    # ein schleichender Teilausfall (Selektor trifft nur noch 3 von 12) zum
    # neuen Maßstab und fiele nie wieder auf.
    if (html and roh_zeilen and b is None and url
            and roh_zeilen >= (archiv_treffer or 0)):
        store.seiten_archiv_setzen(quelle, url, html, roh_zeilen, jetzt)

    if b is None:
        v = verdacht_ermitteln(roh_zeilen=roh_zeilen, n_zeilen=n_zeilen,
                               archiv_treffer=archiv_treffer)
        if v is None:
            return None
        v["diagnose"] = diagnose(regeln=regeln, html=html or "", url=url,
                                 archiv_html=(archiv or {}).get("html"))
        if store.heilung_offen_fuer(quelle, (jetzt or "")[:10]):
            return v          # heute schon notiert — nicht täglich wiederholen
        # Beweis erbracht? (Seite hat datierte Einträge, unser Selektor nicht)
        if v["diagnose"]["urteil"] == "selektoren_tot_aber_inhalt_da":
            v["art"] = "selektoren_tot"
            v["text"] = "Rückgang, und der Selektor passt nicht mehr (Beweis erbracht)"
            store.heilung_anlegen(quelle, "selektoren_tot", v, jetzt)
            print(f"[heilung] {quelle}: selektoren_tot (aus Verdacht bewiesen)", flush=True)
        else:
            store.heilung_anlegen(quelle, "verdacht", v, jetzt, status="beobachtet")
            print(f"[heilung] {quelle}: Verdacht — {v['diagnose']['urteil']} "
                  f"({v['zahlen']['jetzt']} statt {v['zahlen']['frueher']}), kein Eingriff",
                  flush=True)
        return v

    if store.heilung_offen_fuer(quelle, (jetzt or "")[:10]):
        return b
    b["diagnose"] = diagnose(regeln=regeln, html=html or "", url=url,
                             archiv_html=(archiv or {}).get("html"))
    store.heilung_anlegen(quelle, b["art"], b, jetzt)
    print(f"[heilung] {quelle}: {b['art']} — {b['text']} "
          f"(Diagnose: {b['diagnose']['urteil']})", flush=True)
    return b
