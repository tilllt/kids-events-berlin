"""Seiten holen und für das LLM aufbereiten (Change 010).

Bewusst deterministisch und LLM-frei: Hier entsteht nur Text plus die
Fundstellen-Fenster. Das LLM hilft beim *Verstehen*, nicht beim Zugang —
Bot-Schutz, harte 403 und Turnstile bleiben Sache der Mail-Anfrage.
"""
from __future__ import annotations

import html as htmllib
import re
from urllib.parse import urljoin, urlparse

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Kandidaten-Priorität: offene Tür zuerst, dann Termine, dann Aktuelles.
LINK_KEYWORDS = (
    ("offen", r"offene[nr]?[-_\s]?t[uü]r|tag[-_\s]der[-_\s]offenen"),
    ("termin", r"termine?|terminplan|schultermine|jahresplan|kalender"),
    ("anmeld", r"anmeldung|schulanfang|schulanf[aä]nger|einschulung"),
    ("aktuell", r"aktuelles|neuigkeiten|news|mitteilungen"),
)

# Zielklassen der Recherche (Titelvokabular s. schul_import.KEYWORD_TITEL)
TERMIN_RE = re.compile(
    r"offene[nr]?\s+t[uü]r|tag der offenen|infoabend|informationsabend|"
    r"informationsveranstaltung|infoveranstaltung|schnuppertag|schnupperunterricht",
    re.I)
DATUM_RE = re.compile(r"\b\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4}\b")
MONAT_RE = re.compile(
    r"\b(januar|februar|m[aä]rz|april|mai|juni|juli|august|september|"
    r"oktober|november|dezember)\b", re.I)


def url_saeubern(url: str | None) -> str:
    """Website-Angabe aus dem Stamm in eine abrufbare URL bringen.

    Der Schul-WFS-Stamm enthält Werte mit Steuerzeichen und ohne Schema
    (real: „\rhttps://…", „www.schule.de") — httpx bricht bei so etwas mit
    `InvalidURL` ab und riss im ersten Feldlauf den ganzen Lauf mit.
    """
    u = re.sub(r"[\x00-\x1f\x7f]", "", (url or "")).strip()
    if u and not u.startswith(("http://", "https://")):
        u = "http://" + u
    return u


def hole(url: str, client: httpx.Client) -> tuple[str | None, str]:
    """(html, status) — Fehler werden als Text zurückgegeben, nicht geworfen."""
    url = url_saeubern(url)
    if not url:
        return None, "keine URL"
    try:
        r = client.get(url, headers={"User-Agent": UA,
                                     "Accept-Language": "de-DE,de;q=0.9"},
                       follow_redirects=True)
    except Exception as e:  # auch InvalidURL/UnicodeError: sichtbar, nicht still
        return None, f"{type(e).__name__}: {e}"
    if r.status_code >= 400:
        return None, f"HTTP {r.status_code}"
    ctype = (r.headers.get("content-type") or "").lower()
    if "pdf" in ctype or r.content[:4] == b"%PDF":
        return None, "PDF (kein HTML)"
    return r.text, f"OK {r.status_code}"


def text_von(html: str) -> str:
    """HTML → Fließtext (Scripts/Styles raus, Entitäten auf, Whitespace normal)."""
    x = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    x = re.sub(r"(?s)<[^>]+>", " ", x)
    return re.sub(r"\s+", " ", htmllib.unescape(x)).strip()


def kandidaten(html: str, basis: str, *, max_seiten: int = 3) -> list[str]:
    """Terminrelevante Links derselben Domain, nach Priorität sortiert."""
    host = urlparse(basis).netloc.replace("www.", "")
    treffer: dict[str, int] = {}
    for m in re.finditer(r'(?is)<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', html):
        ziel = urljoin(basis, m.group(1))
        if urlparse(ziel).netloc.replace("www.", "") != host:
            continue
        if ziel.rstrip("/") == basis.rstrip("/"):
            continue
        label = text_von(m.group(2))[:80]
        for prio, (_, rx) in enumerate(LINK_KEYWORDS):
            if re.search(rx, m.group(1), re.I) or re.search(rx, label, re.I):
                treffer[ziel] = min(treffer.get(ziel, 99), prio)
                break
    return [u for _, u in sorted((p, u) for u, p in treffer.items())][:max_seiten]


def hat_terminindiz(text: str) -> bool:
    """Vorfilter: Datumsindiz UND Ziel-Keyword — sonst kein LLM-Aufruf."""
    return bool(TERMIN_RE.search(text)) and bool(DATUM_RE.search(text) or MONAT_RE.search(text))


def text_fenster(text: str, *, umfeld_vor: int = 400, umfeld_nach: int = 500,
                 max_zeichen: int = 9000) -> str:
    """Nur die Umgebung der Termin-Stellen senden (überlappungsfrei).

    Ein blindes `text[:9000]` verschwendet Aufmerksamkeit und Kontext: die
    Terminstelle kann weit hinten stehen (realer Befund bei Schul-Seiten mit
    Navigation oben). Ohne Fundstelle mit Datum gibt es kein Fenster — dann
    wird die Seite gar nicht erst geschickt.
    """
    stellen: list[list[int]] = []
    for m in TERMIN_RE.finditer(text):
        umfeld = text[max(0, m.start() - umfeld_vor):m.end() + umfeld_nach]
        if DATUM_RE.search(umfeld) or re.search(
                r"\b\d{1,2}\.\s?(januar|februar|m[aä]rz|april|mai|juni|juli|august|"
                r"september|oktober|november|dezember)", umfeld, re.I):
            stellen.append([max(0, m.start() - umfeld_vor),
                            min(len(text), m.end() + umfeld_nach)])
    if not stellen:
        return ""
    stellen.sort()
    verschmolzen = [stellen[0]]
    for a, b in stellen[1:]:
        if a <= verschmolzen[-1][1]:
            verschmolzen[-1][1] = max(verschmolzen[-1][1], b)
        else:
            verschmolzen.append([a, b])
    return "\n\n[…]\n\n".join(text[a:b] for a, b in verschmolzen)[:max_zeichen]
