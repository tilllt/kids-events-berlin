"""Ortsnamen zusammenführen: Normalform, kanonischer Ort, Prüfliste.

Warum: Derselbe Ort kommt in verschiedenen Schreibweisen aus den Quellen
(„B.L.O. Ateliers" / „B.L.O.-Ateliers", „Neue Kammern am Schloss Sanssouci" /
„Neue Kammern von Sanssouci"). Ohne Zusammenführung listet der Ortsfilter
denselben Ort mehrfach — und die Karte setzt mehrere Marker für einen Ort.

Nutzerentscheidung (2026-09-13):
- Automatisch zusammengeführt wird NUR bei identischer Normalform.
- Ähnliche, aber nicht gleiche Namen landen als Verdachtsfall in der Prüfliste
  und werden erst nach Bestätigung zu Aliasen.
- Generische Angaben („Aula", „online", „Kein Ort") sind keine Orte: keine
  Geokodierung, sie zählen nicht als Veranstaltungsort.
- Die Quellschreibweise bleibt erhalten (Provenienz).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

# „am"/„von" unterscheiden keinen Ort — ebenso wenig das Wort „Schloss"
# („Neue Kammern am Schloss Sanssouci" = „Neue Kammern von Sanssouci").
_FUELLWORT_RX = re.compile(
    r"\b(am|an|auf|beim|der|die|das|dem|den|des|im|in|von|vom|zum|zur|zu|"
    r"schloss|schloß|z\.?\s?h\.?|e\.?\s?v\.?)\b")
# Straßen-/Platzkürzel am Wortende vereinheitlichen, damit
# „Immanuelkirchstr." und „Immanuelkirchstraße" gleich behandelt werden.
_STR_ENDE_RX = re.compile(r"(\w*)str\.?(?=[^a-zäöü0-9]|$)")
_PL_ENDE_RX = re.compile(r"(\w*)pl\.?(?=[^a-zäöü0-9]|$)")

# Generische Angaben: sagen keinen Ort, sondern nur „irgendwo".
_GENERISCH = {
    "aula", "turnhalle", "sporthalle", "halle", "foyer", "mehrzweckhalle",
    "stadion", "sportplatz", "gymnasium", "schule", "bibliothek",
    "online", "digital", "webinar", "zoom",
    "ohne angabe", "kein ort", "keine angabe", "ohne ort", "unbekannt",
    "diverse", "verschiedene", "verschiedene orte", "mehrere orte",
    "berlin", "berlinweit", "ganz berlin", "stadtweit",
    "nach absprache", "wird bekannt gegeben", "folgt", "siehe beschreibung",
    "siehe anbieter", "treffpunkt wird bekannt gegeben", "vor ort",
    "bezirk", "ausserhalb berlins", "außerhalb berlins",
}

# Ab dieser Ähnlichkeit lohnt die Nachfrage (Prüfliste). Bewusst großzügig:
# ein überflüssiger Vorschlag kostet einen Klick, ein übersehener doppelter Ort
# bleibt dauerhaft doppelt. Verschmolzen wird trotzdem nichts automatisch.
AEHNLICH_AB = 0.80


def normalform(name: str) -> str:
    """Vergleichsform eines Ortsnamens.

    „B.L.O.-Ateliers" → „b l o ateliers"; „Neue Kammern am Schloss Sanssouci"
    → „neue kammern sanssouci". Umlaute bleiben erhalten (keine
    Akzent-Entfernung) — „Bülow" und „Bulow" sind nicht sicher dasselbe.
    """
    t = (name or "").strip().lower().replace("ß", "ss")
    t = _STR_ENDE_RX.sub(r"\1strasse", t)
    t = _PL_ENDE_RX.sub(r"\1platz", t)
    t = _FUELLWORT_RX.sub(" ", t)
    t = re.sub(r"[^a-zäöü0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def ist_generisch(name: str) -> bool:
    """Sagt der Name überhaupt einen Ort? („Aula" ≠ Veranstaltungsort.)"""
    n = normalform(name)
    return not n or n in _GENERISCH


def aehnlich(a: str, b: str) -> float:
    """Ähnlichkeit zweier Ortsnamen (0..1) auf Basis der Normalform."""
    na, nb = normalform(a), normalform(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def kanonisch_waehlen(varianten: list[tuple[str, int]]) -> str:
    """Anzeigename einer Gruppe: häufigste Schreibweise, bei Gleichstand die
    ausführlichste (meist die mit Zusatz wie „… Ateliers")."""
    return sorted(varianten, key=lambda v: (-v[1], -len(v[0])))[0][0]


def gruppiere(orte: list[tuple[str, int]]) -> dict[str, list[tuple[str, int]]]:
    """[(Ort, Anzahl)] → {Normalform: [(Ort, Anzahl)]}, generische fallen raus."""
    gruppen: dict[str, list[tuple[str, int]]] = {}
    for name, anzahl in orte:
        if ist_generisch(name):
            continue
        gruppen.setdefault(normalform(name), []).append((name, anzahl))
    return gruppen


def automatische_zuordnung(orte: list[tuple[str, int]]) -> dict[str, str]:
    """Schreibweise → kanonischer Name, NUR für identische Normalform.

    Das ist die sichere Zusammenführung: „B.L.O. Ateliers" und „B.L.O.-Ateliers"
    landen in derselben Gruppe, „Neue Kammern am Schloss Sanssouci" und
    „Neue Kammern von Sanssouci" ebenfalls.
    """
    zuordnung: dict[str, str] = {}
    for varianten in gruppiere(orte).values():
        if len(varianten) < 2:
            continue
        kanonisch = kanonisch_waehlen(varianten)
        for name, _ in varianten:
            if name != kanonisch:
                zuordnung[name] = kanonisch
    return zuordnung


def _teilmenge(a: str, b: str) -> bool:
    """Steckt ein Name ganz im anderen? („Immanuelkirche" ⊂ „Kapelle …")"""
    ta, tb = set(normalform(a).split()), set(normalform(b).split())
    return bool(ta) and bool(tb) and (ta <= tb or tb <= ta)


def verdachtsfaelle(orte: list[tuple[str, int]], *, max_paare: int = 200) -> list[dict]:
    """Ähnliche Namen mit UNTERSCHIEDLICHER Normalform → Prüfliste.

    Zwei Kriterien: ähnliche Schreibweise (Ähnlichkeitsmaß) oder ein Name
    steckt vollständig im anderen. Bewusst keine automatische Zusammenführung:
    „Grundschule am Park" kann es in zwei Bezirken geben. Bestätigt der Nutzer,
    wird daraus ein Alias.
    """
    eintraege = [(name, anzahl) for name, anzahl in orte if not ist_generisch(name)]
    paare: list[dict] = []
    for i, (name_a, zahl_a) in enumerate(eintraege):
        for name_b, zahl_b in eintraege[i + 1:]:
            if normalform(name_a) == normalform(name_b):
                continue  # wird automatisch zusammengeführt
            wert = aehnlich(name_a, name_b)
            if wert >= AEHNLICH_AB or _teilmenge(name_a, name_b):
                paare.append({"a": name_a, "b": name_b, "anzahl_a": zahl_a,
                              "anzahl_b": zahl_b, "aehnlichkeit": round(wert, 3),
                              "grund": "teilmenge" if _teilmenge(name_a, name_b) else "aehnlich"})
    paare.sort(key=lambda p: -p["aehnlichkeit"])
    return paare[:max_paare]


def generische(orte: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Generische Angaben mit Häufigkeit (für den Abschnitt „ohne festen Ort")."""
    return sorted([(n, a) for n, a in orte if ist_generisch(n)], key=lambda v: -v[1])
