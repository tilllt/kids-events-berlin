"""Adapter-Registry. Laufzeit-Invariante: rein deterministisch, kein LLM.

Adapter werden aus der Quellen-Konfiguration (DB, Admin-GUI) gebaut:
- typ 'intern' → bestehender Python-Adapter (z. B. jup-berlin)
- typ 'regeln' → generischer SelectorAdapter (Regeln aus DB)
- typ 'feed'   → folgt mit der ersten Feed-Quelle (feedparser)
"""
from __future__ import annotations

from .jup_berlin import JupBerlinAdapter
from .selector_adapter import SelectorAdapter


def build_adapter(store, quelle: str):
    """Baut den Adapter für eine Quelle aus der DB-Konfiguration."""
    s = store.get_source(quelle)
    if not s:
        raise ValueError(f"Unbekannte Quelle: {quelle}")
    if not s["aktiv"]:
        raise ValueError(f"Quelle pausiert: {quelle}")
    if s["typ"] == "intern":
        return JupBerlinAdapter()
    if s["typ"] == "regeln":
        r = store.get_regeln(quelle)
        regel_yaml = (r or {}).get("regel_yaml")
        return SelectorAdapter(quelle, regel_yaml=regel_yaml,
                               base_url=s.get("url"))
    if s["typ"] == "feed":
        raise ValueError(f"Quelle '{quelle}' ist vom Typ feed: der Feed-Adapter "
                         "folgt, sobald die erste Feed-Quelle aufgenommen wird.")
    raise ValueError(f"Unbekannter Quellen-Typ: {s['typ']}")


def aktive_quellen(store) -> list[dict]:
    """Alle aktiven Quellen aus der DB (für --quelle=alle und Scheduler)."""
    return [s for s in store.list_sources() if s["aktiv"]]
