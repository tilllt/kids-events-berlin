"""Adapter-Registry. Laufzeit-Invariante: rein deterministisch, kein LLM."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .jup_berlin import JupBerlinAdapter

if TYPE_CHECKING:
    from .jup_berlin import JupBerlinAdapter as _Adapter

ADAPTERS: dict[str, "_Adapter"] = {"jup-berlin": JupBerlinAdapter()}


def get_adapter(name: str) -> "_Adapter":
    try:
        return ADAPTERS[name]
    except KeyError:
        raise ValueError(f"Unbekannte Quelle: {name} (bekannt: {', '.join(ADAPTERS)})") from None
