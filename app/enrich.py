"""Regelbasierte Anreicherung: Alter, Kostenlos, Kategorien — kein LLM.

Regeln sind konservativ: Wird kein eindeutiger Ausdruck gefunden, bleiben
Felder leer (None), statt zu raten. Filter „ohne Altersangabe" ist erlaubt.
"""
from __future__ import annotations

import re

_ALTER_PATTERNS: list[tuple[re.Pattern, str]] = [
    # (Regex, wirkung): min bzw. max setzen
    (re.compile(r"\bab\s*(\d+)\s*(?:jahren|jahren?|jahren?)?\b", re.I), "min"),
    (re.compile(r"für\s+kinder\s+ab\s+(\d+)\b", re.I), "min"),
    (re.compile(r"(\d+)\s*(?:bis|–|—|-|zu)\s*(\d+)\s*(?:jahren?|jahren?)\b", re.I), "range"),
    (re.compile(r"(\d+)\s*[-–—]\s*(\d+)\s*jahren?\b", re.I), "range"),
    (re.compile(r"\bU(\d{2})\b", re.I), "max"),  # U12, U16 …
    (re.compile(r"\b(?:kinder|kids)\s*(?:im alter)?\s*(\d+)\s*[-–—]\s*(\d+)\s*", re.I), "range"),
]

_FAMILIE_WORDS = re.compile(r"\bfamilien?|für\s+die\s+ganze\s+familie|mit\s+kindern?\b", re.I)


def classify_alter(titel: str, text: str) -> dict:
    """→ {altersband_min, altersband_max, alters_familie} (None = keine Angabe)."""
    hay = f"{titel or ''} {text or ''}"
    band_min: int | None = None
    band_max: int | None = None
    for rx, wirkung in _ALTER_PATTERNS:
        m = rx.search(hay)
        if not m:
            continue
        if wirkung == "min":
            # „ab 10 Uhr" ist KEIN Alter — nur übernehmen, wenn nicht Uhrzeit folgt.
            rest = hay[m.end():m.end() + 12]
            if re.search(r"\buhr\b|uhrzeit", rest, re.I):
                continue
            v = int(m.group(1))
            band_min = v if band_min is None else max(band_min, v)
        elif wirkung == "max":
            v = int(m.group(1))
            band_max = v if band_max is None else min(band_max, v)
        elif wirkung == "range":
            a, b = int(m.group(1)), int(m.group(2))
            if a <= b:
                band_min = a if band_min is None else max(band_min, a)
                band_max = b if band_max is None else min(band_max, b)
    return {
        "altersband_min": band_min,
        "altersband_max": band_max,
        "alters_familie": bool(_FAMILIE_WORDS.search(hay)),
    }


_FREI_WORTE = re.compile(
    r"\b(?:kostenlos|kostenfrei|umsonst|eintritt\s+frei|ohne\s+eintritt|gratis|freier\s+eintritt)\b", re.I
)
_PREIS_HINWEISE = re.compile(
    r"(?:€|\beur\b|\bpreis\b|\btickets?\b|\bzahlung\b|ermäßigt|kostenpflichtig)", re.I
)


def classify_kostenlos(frei_flag: bool | None, text: str) -> bool | None:
    """True/False bei Beleg, None = unbekannt."""
    if frei_flag is True:
        return True
    if _FREI_WORTE.search(text or ""):
        return True
    if _PREIS_HINWEISE.search(text or ""):
        return False
    return None


KATEGORIE_REGELN: list[tuple[str, list[re.Pattern]]] = [
    ("theater", [re.compile(r"\btheater|bühne|stück|aufführung|theaterstück|schauspiel", re.I)]),
    ("musik", [re.compile(r"\bkonzert|musik|chor|orchester|sing|lied|band\b", re.I)]),
    ("museum", [re.compile(r"\bmuseum|ausstellung|führung|galerie", re.I)]),
    ("bibliothek", [re.compile(r"\bbibliothek|vorlese|lesung|buch\b|leseförderung", re.I)]),
    ("workshop", [re.compile(r"\bworkshop|kurs|bastel|mal(en)?\b|werkstatt|mitmach|selbst\s+mach", re.I)]),
    ("sport", [re.compile(r"\bsport|fußball|turnen|schwimm|judo|tanz|bewegung|olympiade|meisterschaft", re.I)]),
    ("spiel", [re.compile(r"\bspiel|gaming|spiele|escape|rätsel|rallye|schnitzeljagd", re.I)]),
    ("fest", [re.compile(r"\bfest\b|markt|feier|kirmes|straßenfest", re.I)]),
    ("ferien", [re.compile(r"\bferien|camp\b|freizeit\b", re.I)]),
    ("natur", [re.compile(r"\bnatur|wald|garten|tier|bauernhof|park\b", re.I)]),
]


def classify_kategorien(text: str) -> list[str]:
    gefunden: list[str] = []
    for name, rxlist in KATEGORIE_REGELN:
        if any(rx.search(text or "") for rx in rxlist):
            gefunden.append(name)
    return gefunden
