"""Validierung: Pflichtfelder, Zeitlogik, Horizont, URL — Fehler sichtbar.

Kein stilles Verwerfen: validate_event liefert Gründe; der Aufrufer protokolliert
sie in der Fehler-Queue und meldet n_fehler im Lauf (Alarm-Pfad).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .model import TZ_BERLIN, parse_iso

HORIZONT_PAST = timedelta(days=2)   # Events bis 2 Tage in der Vergangenheit tolerieren
HORIZONT_FUTURE = timedelta(days=400)

_URL_RE = re.compile(r"^https?://\S+$", re.I)


def validate_event(ev: dict, jetzt: datetime | None = None) -> list[str]:
    """Gibt Liste der Validierungsfehler zurück (leer = valide)."""
    fehler: list[str] = []
    jetzt = jetzt or datetime.now(TZ_BERLIN)

    if not (ev.get("titel") or "").strip():
        fehler.append("Pflichtfeld titel fehlt")
    if not (ev.get("quelle") or "").strip():
        fehler.append("Pflichtfeld quelle fehlt")
    if not (ev.get("source_url") or "").strip() or not _URL_RE.match(ev["source_url"]):
        fehler.append("source_url fehlt oder nicht wohlgeformt")
    if not (ev.get("ort") or "").strip():
        fehler.append("Pflichtfeld ort fehlt")

    try:
        start = parse_iso(ev["start_iso"])
    except (KeyError, ValueError):
        fehler.append("start_iso fehlt oder nicht parsebar")
        start = None

    ende = None
    if ev.get("ende_iso"):
        try:
            ende = parse_iso(ev["ende_iso"])
        except ValueError:
            fehler.append("ende_iso nicht parsebar")

    if start is not None:
        if start < jetzt - HORIZONT_PAST:
            fehler.append(f"start außerhalb Horizont (Vergangenheit): {ev['start_iso']}")
        if start > jetzt + HORIZONT_FUTURE:
            fehler.append(f"start außerhalb Horizont (zu weit in der Zukunft): {ev['start_iso']}")
        if ende is not None and ende < start:
            fehler.append("Zeitlogik: ende < start")

    return fehler
