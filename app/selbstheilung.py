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
                     http_fehler: str = "", n_warn: int = 0) -> dict | None:
    """Liegt ein Fehler vor? (None = kein Fehler — auch bei weniger Terminen.)

    Change 028: `n_warn` sind die Fehler beim AUSLESEN der Listing-Blöcke
    („Item 12: start: kein Wert extrahiert"). Sie zählten bisher nicht mit — der
    Auslöser „Pflichtfeld bricht" konnte damit nie feuern (real: 45.568 solcher
    Zeilen bei umweltkalender-berlin, aber n_fehler = 0 in 34 Läufen).
    """
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
    gesamt = n_fehler + max(0, n_warn)
    bezug = n_zeilen + max(0, n_warn)
    if gesamt >= FEHLER_ABSOLUT or (bezug and gesamt / max(bezug, 1) >= FEHLERQUOTE):
        zusatz = (f" ({n_warn} davon beim Auslesen der Listing-Blöcke)"
                  if n_warn else "")
        return {"art": "fehlerquote", "status": None,
                "text": f"{gesamt} von {bezug} gelesenen Zeilen sind fehlerhaft{zusatz}",
                "zahlen": {"n_fehler": n_fehler, "n_warn": max(0, n_warn),
                           "n_zeilen": bezug}}
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
    # Auch eine unbrauchbare Antwort wird zurückgegeben: der Rohtext landet in
    # der Fallakte, sonst ist hinterher nicht nachvollziehbar, WARUM nichts kam.
    return {"yaml": neu, "begruendung": begruendung_aus_antwort(text or ""),
            "antwort": (text or "")[:4000], "prompt": prompt}


def llm_bereit(konfig: dict) -> bool:
    """Zählt dieser Endpunkt als eingerichtet?

    Ein Platzhalter wie `<LLM_BASE_URL>` ist nicht leer, aber keine Adresse.
    Ohne diese Prüfung würde die Automatik bei unkonfiguriertem Endpunkt einen
    Call versuchen und mit einer irreführenden Meldung scheitern (real: das
    Repo enthält als Voreinstellung einen Platzhalter).
    """
    return (konfig.get("llm_base_url") or "").strip().startswith(("http://", "https://"))


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
        if not llm_bereit(konf):
            print(f"[heilung] {quelle}: kein LLM-Endpunkt eingerichtet — "
                  f"Vorschlag entfällt (Basis-URL: {konf.get('llm_base_url')!r})",
                  flush=True)
            return None
        llm_ruf = lambda p: (chat(konf, p, max_tokens=2000) or {}).get("text", "")  # noqa: E731
    from .regeln import _LISTING_FELDER  # erlaubte Felder aus dem Regel-Schema
    v = vorschlag_erzeugen(quelle=quelle, regeln=regeln, befund=befund,
                           diagnose=diagnose, html=html,
                           erlaubte_felder=sorted(_LISTING_FELDER), llm_ruf=llm_ruf)
    archiv = store.seiten_archiv_holen(
        quelle, (((regeln_lesen(regeln).get("listing") or {}).get("url")) or ""))
    if not v or not v.get("yaml"):
        print(f"[heilung] {quelle}: Modell lieferte keine brauchbaren Regeln", flush=True)
        if heilung_id:
            store.heilung_setzen(
                heilung_id, begruendung="Modell-Antwort ohne gültiges YAML",
                beleg={"modell_antwort": (v or {}).get("antwort", "")[:2000],
                       "prompt_zeichen": len((v or {}).get("prompt") or "")},
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
            n_fehler: int = 0, http_fehler: str = "", n_warn: int = 0,
            notieren: bool = True, jetzt: str = "") -> dict | None:
    """Nach dem Listing-Abruf: gesunde Seite archivieren, Fehler feststellen.

    Rückgabe: der Befund (Fehler) oder None. Ein Rückgang ohne Fehler hinterlässt
    höchstens einen Eintrag mit Status 'beobachtet' — es wird nichts geändert.

    `notieren=False` stellt den Befund nur fest (kein Eintrag) — Change 028
    nutzt das, wenn für diese Quelle heute schon ein Fall vorliegt oder das
    Tageskontingent erschöpft ist.
    """
    archiv = store.seiten_archiv_holen(quelle, url) if url else None
    archiv_treffer = archiv["treffer"] if archiv else None

    b = befund_ermitteln(regeln=regeln, html=html, roh_zeilen=roh_zeilen,
                         n_zeilen=n_zeilen, n_fehler=n_fehler, n_warn=n_warn,
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
        if not notieren:
            return v          # Tageskontingent erschöpft: nur feststellen
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
    if not notieren:
        return b
    store.heilung_anlegen(quelle, b["art"], b, jetzt)
    print(f"[heilung] {quelle}: {b['art']} — {b['text']} "
          f"(Diagnose: {b['diagnose']['urteil']})", flush=True)
    return b


# ---------------------------------------------------------------------------
# Change 028: Automatik — reparieren, beobachten, zurücknehmen, melden
# ---------------------------------------------------------------------------
#
# Auftrag des Nutzers (2026-10-16): „Baue den Knopf ein, aber etabliere auch
# einen automatischen Modus, der versucht zu reparieren, oder wenn das nicht
# klappt, Bescheid sagt." Heilen darf nur, was BEWIESEN kaputt ist (Change 017);
# neu ist, dass der Befund auch zu einer Handlung führt: übernehmen, wenn das
# Gate grün ist, den nächsten Lauf beobachten, bei Einbruch zurücknehmen — und
# in jedem Fall melden.

AUTO_STANDARD = "1"
MAX_PRO_TAG_STANDARD = 3
BEOBACHTUNG_ANTEIL = 0.5      # unter der Hälfte des Probelaufs → Rücknahme
RUECKNAHME_SPERRE_TAGE = 7    # so lange kein automatischer zweiter Versuch
HEILBAR = ("selektoren_tot", "fehlerquote", "url_umgezogen", "pflichtfeld")
NUR_MELDUNG = ("verdacht", "gesperrt")


def einstellungen(store) -> dict:
    """Geltende Einstellungen der Automatik — ausschließlich aus der DB."""
    def s(key: str, standard: str = "") -> str:
        wert = store.get_setting(key)
        wert = "" if wert is None else str(wert).strip()
        return wert or standard

    def wahr(key: str, standard: str = "1") -> bool:
        return s(key, standard).lower() not in ("0", "false", "nein", "aus")

    try:
        grenze = int(s("heilung_max_pro_tag", str(MAX_PRO_TAG_STANDARD)))
    except ValueError:
        grenze = MAX_PRO_TAG_STANDARD
    return {"auto": wahr("heilung_auto", AUTO_STANDARD),
            "mail_aktiv": wahr("heilung_mail_aktiv", "1"),
            "mail_an": s("heilung_mail_an", s("smtp_from", s("smtp_reply_to", ""))),
            "max_pro_tag": max(0, grenze)}


def melden(store, *, betreff: str, text: str, mailer=None,
           konf: dict | None = None) -> dict:
    """Meldung rausschicken (E-Mail, wenn eingerichtet) — nie eine Ausnahme."""
    konf = konf if konf is not None else einstellungen(store)
    if not konf.get("mail_aktiv"):
        return {"mail": None, "fehler": "E-Mail-Meldungen sind abgeschaltet"}
    an = (konf.get("mail_an") or "").strip()
    if not an:
        return {"mail": None, "fehler": "Keine Melde-Adresse gesetzt (heilung_mail_an)"}
    try:
        if mailer is not None:
            mailer(an, betreff, text)
        else:
            from . import mail as _mail
            _mail.sende(store, an, betreff=betreff, text=text)
    except Exception as e:      # noqa: BLE001 — der Grund gehört in die Oberfläche
        return {"mail": None, "fehler": f"{type(e).__name__}: {str(e)[:200]}"}
    return {"mail": an, "fehler": None}


def _melden(store, *, heilung_id: int | None, quelle: str, text: str,
            mailer=None, konf: dict | None = None, zeit: str = "",
            betreff: str | None = None) -> dict:
    """Text in den Fall schreiben UND melden. Nichts fällt still aus."""
    erg = melden(store, betreff=betreff or f"Kinderkram: Selbstheilung {quelle}",
                 text=text, mailer=mailer, konf=konf)
    felder: dict = {"meldung": text, "zeit": zeit}
    if erg.get("mail"):
        felder["benachrichtigt_am"] = zeit
    if heilung_id:
        store.heilung_setzen(heilung_id, **felder)
    if erg.get("fehler"):
        store.log_error(quelle, f"Selbstheilung-Meldung nicht versandt: {erg['fehler']}")
    return erg


def holer(store, quelle: str):
    """Holt eine URL mit dem Projekt-UA — für umgezogene Listing-Seiten."""
    from .adapters.selector_adapter import UA as _UA
    import httpx

    def holen(url: str) -> str:
        with httpx.Client(headers={"User-Agent": _UA,
                                   "Accept-Language": "de-DE,de;q=0.9"},
                          follow_redirects=True, timeout=30) as c:
            r = c.get(url)
            r.raise_for_status()
            return r.text
    return holen


def uebernehmen(store, *, quelle: str, alt_yaml: str, neu_yaml: str, grund: str,
                verursacher: str, heilung_id: int | None,
                erwartete_treffer: int | None, zeit: str,
                beleg: dict | None = None) -> dict:
    """Regeln wirksam setzen — nur nach grünem Gate, immer mit Historie."""
    store.set_regeln(quelle, neu_yaml)
    hist_id = store.regel_historie_anlegen(
        quelle, alt_yaml=alt_yaml, neu_yaml=neu_yaml, grund=grund,
        verursacher=verursacher, heilung_id=heilung_id, zeit=zeit)
    if heilung_id:
        store.heilung_setzen(heilung_id, status="angenommen", zeit=zeit,
                             uebernommen_am=zeit, verursacher=verursacher,
                             erwartete_treffer=erwartete_treffer,
                             beleg=beleg)
    return {"historie_id": hist_id, "regeln_geaendert": True}


def beobachtung(store, *, quelle: str, roh_zeilen: int, jetzt: str,
                konf: dict | None = None, mailer=None) -> dict | None:
    """Wirkung der übernommenen Reparatur messen (im nächsten Lauf).

    Findet der Lauf weniger als die Hälfte der Probelauf-Zahl, ist die Reparatur
    gescheitert: alte Regeln zurück, Fall auf `zurueckgenommen`, Meldung raus.
    """
    h = store.heilung_zur_beobachtung(quelle)
    if not h:
        return None
    erwartet = int(h.get("erwartete_treffer") or 0)
    if erwartet and roh_zeilen < int(erwartet * BEOBACHTUNG_ANTEIL):
        grund = (f"Nach der Übernahme nur {roh_zeilen} Treffer statt {erwartet} "
                 f"im Probelauf")
        rueck = store.regel_ruecknahme(quelle, grund=grund, zeit=jetzt,
                                       heilung_id=h["id"])
        text = (f"Quelle {quelle}: die automatisch übernommene Reparatur trägt "
                f"nicht ({roh_zeilen} statt {erwartet} Termine). "
                + ("Die vorherigen Regeln sind wieder in Kraft."
                   if rueck else
                   "ACHTUNG: keine Vorgänger-Fassung in der Historie gefunden — "
                   "die Regeln müssen von Hand geprüft werden.")
                + f" Die Automatik pausiert für diese Quelle {RUECKNAHME_SPERRE_TAGE} Tage.")
        store.heilung_setzen(h["id"], status="zurueckgenommen",
                             pruefung_ergebnis="rollback", zeit=jetzt)
        _melden(store, heilung_id=h["id"], quelle=quelle, text=text,
                mailer=mailer, konf=konf, zeit=jetzt)
        print(f"[heilung] {quelle}: Rücknahme ({roh_zeilen} statt {erwartet})", flush=True)
        return {"heilung_id": h["id"], "rollback": bool(rueck), "text": text}
    store.heilung_setzen(h["id"], pruefung_ergebnis="ok", zeit=jetzt)
    return {"heilung_id": h["id"], "rollback": False,
            "text": (f"Reparatur trägt: {roh_zeilen} Treffer "
                     f"(erwartet mindestens {int(erwartet * BEOBACHTUNG_ANTEIL)})")}


def seiten_hinweis(diagnose: dict) -> str:
    """Warum ein Selektorwechsel hier nicht helfen kann (oder "" wenn doch).

    Live belegt am 16.10.2026 (familienportal): die Seite antwortet mit 200,
    enthält aber keinen einzigen Termin-Eintrag mit Datum — die Liste entsteht
    erst im Browser (Urteil `seite_ohne_terminangebot`). Ein neuer Selektor
    findet dort nichts. Das muss die Meldung sagen, statt einen Modell-Aufruf
    und das Tageskontingent zu verbrennen und danach über das Modell zu klagen.
    """
    if (diagnose or {}).get("urteil") == "seite_ohne_terminangebot":
        return ("Die Seite liefert keinen einzigen Termin-Eintrag mit Datum "
                "(die Liste entsteht vermutlich erst im Browser) — ein "
                "Selektorwechsel kann das nicht beheben, die Quelle braucht "
                "einen neuen Weg.")
    return ""


def versuchen(store, *, quelle: str, befund: dict, diagnose: dict, html: str,
              regeln: str, jetzt: str, auto: bool | None = None,
              heilung_id: int | None = None, holen=None, llm_ruf=None,
              mailer=None, konf: dict | None = None,
              verursacher: str = "auto") -> dict | None:
    """Einen bewiesenen Defekt reparieren — oder melden, warum nicht.

    `auto=True`: bei grünem Gate wird gleich übernommen (Stufe 2).
    `auto=False`: der Vorschlag wird nur geprüft und abgelegt (Admin bestätigt).
    """
    konf = konf if konf is not None else einstellungen(store)
    if auto is None:
        auto = konf["auto"]
    art = (befund or {}).get("art")
    if not art:
        return None

    if art in NUR_MELDUNG:
        if art == "verdacht":
            text = (f"Quelle {quelle}: {befund.get('text')} — kein Defekt bewiesen, "
                    f"es wird nichts geändert (Diagnose: "
                    f"{(diagnose or {}).get('urteil')}).")
        else:
            text = (f"Quelle {quelle}: Zugriff abgelehnt ({befund.get('status')}). "
                    f"Das ist nicht reparierbar — bitte die Quelle prüfen. Sie "
                    f"bleibt aktiv, damit nichts still verschwindet.")
        _melden(store, heilung_id=heilung_id, quelle=quelle, text=text,
                mailer=mailer, konf=konf, zeit=jetzt)
        return {"art": art, "aktion": "gemeldet", "meldung": text,
                "regeln_geaendert": False}

    if art not in HEILBAR:
        return None

    hinweis = seiten_hinweis(diagnose)
    if hinweis:
        text = (f"Quelle {quelle}: {befund.get('text')} — {hinweis} "
                f"Es wurde nichts geändert.")
        if heilung_id:
            store.heilung_setzen(heilung_id, status="unreparierbar", zeit=jetzt,
                                 meldung=text)
        else:
            heilung_id = store.heilung_anlegen(quelle, art, befund, jetzt,
                                               status="unreparierbar",
                                               verursacher=verursacher, meldung=text)
        _melden(store, heilung_id=heilung_id, quelle=quelle, text=text,
                mailer=mailer, konf=konf, zeit=jetzt)
        return {"art": art, "aktion": "unreparierbar", "meldung": text,
                "regeln_geaendert": False}

    if llm_ruf is None:
        from .recherche.llm import konfiguration
        if not llm_bereit(konfiguration(store)):
            text = (f"Quelle {quelle}: {befund.get('text')} — die Automatik kann "
                    f"nicht reparieren, weil kein LLM-Endpunkt eingerichtet ist "
                    f"(Einstellungen → Schul-Recherche → LLM-Endpunkt).")
            _melden(store, heilung_id=heilung_id, quelle=quelle, text=text,
                    mailer=mailer, konf=konf, zeit=jetzt)
            return {"art": art, "aktion": "kein-llm", "meldung": text,
                    "regeln_geaendert": False}

    alt_yaml = regeln or ""
    b = heilen(store, quelle=quelle, befund=befund, diagnose=diagnose, html=html,
               jetzt=jetzt, llm_ruf=llm_ruf, holen=holen, heilung_id=heilung_id)
    if b is None:
        text = (f"Quelle {quelle}: {befund.get('text')} — das Modell lieferte keine "
                f"brauchbaren Regeln. Es wurde nichts geändert.")
        _melden(store, heilung_id=heilung_id, quelle=quelle, text=text,
                mailer=mailer, konf=konf, zeit=jetzt)
        return {"art": art, "aktion": "vorschlag-unbrauchbar", "meldung": text,
                "regeln_geaendert": False}

    beleg = b.get("beleg") or {}
    fehler = beleg.get("fehler") or []
    zahl = beleg.get("treffer_heute")

    if not b.get("ok"):
        text = (f"Quelle {quelle}: {befund.get('text')} — Reparaturvorschlag "
                f"DURCHGEFALLEN ({'; '.join(fehler[:3]) or 'Gate rot'}). Die Regeln "
                f"sind unverändert.")
        _melden(store, heilung_id=b.get("id"), quelle=quelle, text=text,
                mailer=mailer, konf=konf, zeit=jetzt)
        return {"art": art, "aktion": "verworfen", "meldung": text,
                "regeln_geaendert": False, "beleg": beleg, "id": b.get("id")}

    if auto:
        uebernehmen(store, quelle=quelle, alt_yaml=alt_yaml, neu_yaml=b["yaml"],
                    grund=f"{art}: {befund.get('text')}",
                    verursacher=verursacher, heilung_id=b.get("id"),
                    erwartete_treffer=zahl, zeit=jetzt, beleg=beleg)
        text = (f"Quelle {quelle}: {befund.get('text')} — die Automatik hat die "
                f"Regeln repariert und übernommen ({zahl} Termine im Probelauf, "
                f"{beleg.get('treffer_alt')} auf der archivierten Seite). Der "
                f"nächste Lauf wird geprüft; trägt die Reparatur nicht, werden die "
                f"alten Regeln automatisch wiederhergestellt.")
        _melden(store, heilung_id=b.get("id"), quelle=quelle, text=text,
                mailer=mailer, konf=konf, zeit=jetzt)
        print(f"[heilung] {quelle}: automatisch repariert ({zahl} Treffer)", flush=True)
        return {"art": art, "aktion": "uebernommen", "meldung": text,
                "regeln_geaendert": True, "beleg": beleg, "id": b.get("id")}

    text = (f"Quelle {quelle}: {befund.get('text')} — Reparaturvorschlag geprüft "
            f"({zahl} Termine heute, {beleg.get('treffer_alt')} auf der archivierten "
            f"Seite). Die Automatik ist abgeschaltet — bitte in der Verwaltung "
            f"bestätigen (Quellen → Selbstheilung).")
    _melden(store, heilung_id=b.get("id"), quelle=quelle, text=text,
            mailer=mailer, konf=konf, zeit=jetzt)
    return {"art": art, "aktion": "vorgeschlagen", "meldung": text,
            "regeln_geaendert": False, "beleg": beleg, "id": b.get("id")}


def regel_diff(alt_yaml: str, neu_yaml: str, kontext: int = 1) -> str:
    """Zeilen-Diff zweier Regel-Fassungen (für die Oberfläche)."""
    import difflib
    d = difflib.unified_diff((alt_yaml or "").splitlines(),
                             (neu_yaml or "").splitlines(),
                             fromfile="bisher", tofile="Vorschlag",
                             lineterm="", n=kontext)
    return "\n".join(d)


def url_aus_regeln(regeln: str) -> str:
    return ((regeln_lesen(regeln).get("listing") or {}).get("url") or "").strip()


def lauf_auswerten(store, *, quelle: str, regeln: str, url: str = "",
                   html: str | None = None, roh_zeilen: int = 0, n_zeilen: int = 0,
                   n_fehler: int = 0, n_warn: int = 0, http_fehler: str = "",
                   jetzt: str = "", holen=None, llm_ruf=None, mailer=None,
                   konf: dict | None = None) -> dict:
    """Der eine Einstiegspunkt nach dem Listing-Abruf (Change 028).

    Reihenfolge ist Absicht: erst die Wirkung der letzten Übernahme messen (sie
    betrifft die aktuell geltenden Regeln), dann den Befund feststellen, dann —
    nur bei bewiesenem Defekt und freiem Kontingent — reparieren.
    """
    konf = konf if konf is not None else einstellungen(store)
    tag = (jetzt or "")[:10]
    aus: dict = {"befund": None, "beobachtung": None, "aktion": None, "protokoll": []}

    try:
        beob = beobachtung(store, quelle=quelle, roh_zeilen=roh_zeilen, jetzt=jetzt,
                           konf=konf, mailer=mailer)
    except Exception as e:      # darf den Lauf nie stören
        beob = None
        store.log_error(quelle, f"Selbstheilung-Beobachtung fehlgeschlagen: {e}")
    if beob:
        aus["beobachtung"] = beob
        aus["protokoll"].append(beob["text"])

    heute_schon = store.heilung_heute(quelle, tag) is not None
    b = pruefen(store, quelle=quelle, regeln=regeln, url=url, html=html,
                roh_zeilen=roh_zeilen, n_zeilen=n_zeilen, n_fehler=n_fehler,
                n_warn=n_warn, http_fehler=http_fehler, notieren=not heute_schon,
                jetzt=jetzt)
    aus["befund"] = b
    if b is None or heute_schon:
        return aus

    fall = store.heilung_heute(quelle, tag) or {}
    hid = fall.get("id")
    gruende = []
    if store.heilungen_zaehlen(tag) > konf["max_pro_tag"]:
        gruende.append(f"das Tageskontingent ist erschöpft "
                       f"({konf['max_pro_tag']} Versuche pro Tag)")
    if store.heilung_ruecknahme_kuerzlich(quelle, tage=RUECKNAHME_SPERRE_TAGE,
                                          tag=tag):
        gruende.append(f"nach einer Rücknahme pausiert die Automatik "
                       f"{RUECKNAHME_SPERRE_TAGE} Tage")
    if gruende:
        text = (f"Quelle {quelle}: {b.get('text')} — kein Reparaturversuch: "
                + " und ".join(gruende)
                + ". Der Fall steht in der Liste; der Knopf „Regeln reparieren "
                  "lassen“ umgeht das Kontingent.")
        store.heilung_setzen(hid, meldung=text, zeit=jetzt)
        aus["aktion"] = {"art": b.get("art"), "aktion": "uebersprungen",
                         "meldung": text, "regeln_geaendert": False}
        aus["protokoll"].append(text)
        return aus

    aktion = versuchen(store, quelle=quelle, befund=b,
                       diagnose=b.get("diagnose") or {}, html=html or "",
                       regeln=regeln, jetzt=jetzt, heilung_id=hid, holen=holen,
                       llm_ruf=llm_ruf, mailer=mailer, konf=konf,
                       verursacher="auto")
    aus["aktion"] = aktion
    if aktion and aktion.get("meldung"):
        aus["protokoll"].append(aktion["meldung"])
    return aus


def manuell_versuchen(store, *, quelle: str, jetzt: str, mailer=None,
                      konf: dict | None = None, llm_ruf=None) -> dict:
    """Knopf „Regeln reparieren lassen".

    Umgeht Tageskontingent und Automatik-Schalter (eine ausdrückliche Handlung),
    NICHT aber das Prüf-Gate: übernommen wird nur, was alle Prüfungen besteht.
    """
    konf = konf if konf is not None else einstellungen(store)
    regeln = (store.get_regeln(quelle) or {}).get("regel_yaml") or ""
    if not regeln.strip():
        return {"ok": False, "fehler": "Diese Quelle hat keine Regel-YAML — "
                                       "interne Quellen und Feeds werden nicht repariert."}
    from .adapters import build_adapter
    try:
        adapter = build_adapter(store, quelle)
    except ValueError as e:
        return {"ok": False, "fehler": str(e)}
    try:
        url = getattr(adapter, "_listing_url", "") or ""
        try:
            html = adapter.fetch_listing_page(0)
        except Exception as e:      # Seite nicht da → nicht raten
            text = (f"Quelle {quelle}: die Listing-Seite ist nicht abrufbar "
                    f"({type(e).__name__}: {str(e)[:120]}). Ohne Seite wäre jede "
                    f"Reparatur geraten — es wurde nichts geändert.")
            hid = store.heilung_anlegen(quelle, "manuell",
                                        {"art": "manuell", "text": text}, jetzt,
                                        status="fehlgeschlagen",
                                        verursacher="manuell", meldung=text)
            _melden(store, heilung_id=hid, quelle=quelle, text=text, mailer=mailer,
                    konf=konf, zeit=jetzt)
            return {"ok": False, "fehler": text, "id": hid}
        roh = len(adapter.parse_listing(html))
        warns = len(getattr(adapter, "drain_warnungen", lambda: [])())
    finally:
        adapter.close()

    archiv = store.seiten_archiv_holen(quelle, url) if url else None
    b = befund_ermitteln(regeln=regeln, html=html, roh_zeilen=roh, n_zeilen=roh,
                         n_fehler=0, n_warn=warns,
                         archiv_treffer=(archiv or {}).get("treffer"))
    if b is None:
        d = diagnose(regeln=regeln, html=html, url=url,
                     archiv_html=(archiv or {}).get("html"))
        text = (f"Quelle {quelle}: kein Defekt gefunden — {roh} Termin-Blöcke "
                f"gelesen, {warns} ohne vollständige Felder, Urteil: {d.get('urteil')}. "
                f"Es wurde nichts geändert.")
        hid = store.heilung_anlegen(quelle, "manuell",
                                    {"art": "manuell", "text": text,
                                     "zahlen": {"roh": roh, "warnungen": warns},
                                     "diagnose": d},
                                    jetzt, status="ohne-defekt",
                                    verursacher="manuell", meldung=text)
        store.heilung_setzen(hid, beleg=d, zeit=jetzt)
        _melden(store, heilung_id=hid, quelle=quelle, text=text, mailer=mailer,
                konf=konf, zeit=jetzt)
        return {"ok": True, "befund": None, "text": text, "id": hid}

    b["diagnose"] = diagnose(regeln=regeln, html=html, url=url,
                             archiv_html=(archiv or {}).get("html"))
    hid = store.heilung_anlegen(quelle, b["art"], b, jetzt,
                                verursacher="manuell", meldung=b.get("text"))
    aktion = versuchen(store, quelle=quelle, befund=b, diagnose=b["diagnose"],
                       html=html, regeln=regeln, jetzt=jetzt, auto=True,
                       heilung_id=hid, llm_ruf=llm_ruf, mailer=mailer, konf=konf,
                       verursacher="manuell")
    return {"ok": bool(aktion and aktion.get("regeln_geaendert")),
            "id": hid, "befund": b, **(aktion or {})}
