"""LLM-Anbindung der Schul-Recherche (Change 010).

Der Endpunkt ist vollständig im Admin konfigurierbar und OpenAI-kompatibel
(`/v1/chat/completions`): Basis-URL, Modell, optionaler API-Key, Timeout und
zusätzliche Parameter als JSON. Voreinstellung ist der lokale llama.cpp auf
der KI-Box — die liegt im selben Netz wie die App, also kein Cloud-Kontingent
und kein Datenschutzproblem bei Schul-Antwortmails.

PITFALL (gemessen 2026-09-13, KI-Box): Gemma-4 liefert ohne
`chat_template_kwargs={"enable_thinking": false}` ein leeres `content`
(`finish_reason=length`, Denktext in `reasoning_content`) — für die Extraktion
unbrauchbar. Der Zusatz-Parameter ist deshalb als Standard vorbelegt und darf
im Admin überschrieben werden (andere Endpunkte brauchen ihn nicht).
"""
from __future__ import annotations

import json
import re
import time

import httpx

# Voreinstellung: lokaler Endpunkt der KI-Box im LAN des Containerhosts.
STANDARD = {
    "llm_base_url": "http://192.168.178.140:8088/v1",
    "llm_model": "llamacpp-gemma4-12B-unsloth",
    "llm_api_key": "",
    "llm_timeout_s": "120",
    "llm_extra_json": '{"chat_template_kwargs": {"enable_thinking": false}}',
}

# Diese Einstellungen liest die Recherche; alles andere in `settings` ist egal.
SCHLUESSEL = tuple(STANDARD)


class LLMFehler(RuntimeError):
    """Endpunkt nicht erreichbar oder Antwort unbrauchbar — sichtbar, nie still."""


def konfiguration(store) -> dict:
    """Gespeicherte Einstellungen über die Voreinstellung legen (leer = Standard)."""
    k = dict(STANDARD)
    for key in SCHLUESSEL:
        wert = store.get_setting(key)
        if wert is not None and str(wert).strip() != "":
            k[key] = str(wert).strip()
    return k


def zusatz_parameter(konfig: dict) -> dict:
    """`llm_extra_json` → dict. Ungültiges JSON ist ein sichtbarer Fehler."""
    roh = (konfig.get("llm_extra_json") or "").strip()
    if not roh:
        return {}
    try:
        d = json.loads(roh)
    except json.JSONDecodeError as e:
        raise LLMFehler(f"Zusatz-Parameter sind kein gültiges JSON: {e}") from e
    if not isinstance(d, dict):
        raise LLMFehler("Zusatz-Parameter müssen ein JSON-Objekt sein (z. B. {\"temperature\": 0}).")
    return d


def _url(konfig: dict) -> str:
    basis = (konfig.get("llm_base_url") or "").rstrip("/")
    if not basis.startswith(("http://", "https://")):
        raise LLMFehler("LLM-Basis-URL muss mit http:// oder https:// beginnen.")
    return f"{basis}/chat/completions"


def _timeout(konfig: dict) -> float:
    try:
        t = float(konfig.get("llm_timeout_s") or 120)
    except (TypeError, ValueError):
        return 120.0
    return min(max(t, 5.0), 600.0)


def _kopfzeilen(konfig: dict) -> dict:
    key = (konfig.get("llm_api_key") or "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def chat(konfig: dict, prompt: str, *, max_tokens: int = 800,
         client: httpx.Client | None = None) -> dict:
    """Ein Chat-Aufruf gegen den konfigurierten Endpunkt.

    Rückgabe: {"text", "dauer_s", "modell", "tokens"}. Fehler werden als
    LLMFehler geworfen (kein stiller Teil-Lauf).
    """
    payload = {"model": konfig.get("llm_model") or "",
               "messages": [{"role": "user", "content": prompt}],
               "max_tokens": int(max_tokens),
               "temperature": 0}
    payload.update(zusatz_parameter(konfig))
    eigene = client is None
    c = client or httpx.Client(timeout=_timeout(konfig))
    t0 = time.time()
    try:
        r = c.post(_url(konfig), json=payload, headers=_kopfzeilen(konfig))
        if r.status_code >= 400:
            raise LLMFehler(f"Endpunkt antwortet HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
    except httpx.HTTPError as e:
        raise LLMFehler(f"Endpunkt nicht erreichbar ({_url(konfig)}): {e}") from e
    finally:
        if eigene:
            c.close()
    try:
        wahl = d["choices"][0]
        msg = wahl.get("message") or {}
    except (KeyError, IndexError, TypeError) as e:
        raise LLMFehler(f"Unerwartete Antwortstruktur: {str(d)[:200]}") from e
    text = msg.get("content") or msg.get("reasoning_content") or ""
    if not text.strip():
        raise LLMFehler(
            "Leere Antwort — bei Gemma-4 fehlt meist "
            "{\"chat_template_kwargs\": {\"enable_thinking\": false}} in den Zusatz-Parametern "
            f"(finish_reason={wahl.get('finish_reason')}).")
    return {"text": text, "dauer_s": round(time.time() - t0, 2),
            "modell": d.get("model") or payload["model"],
            "tokens": d.get("usage", {})}


def json_objekt(text: str) -> dict | None:
    """Erstes JSON-Objekt aus einer Modellantwort — ```-Zäune und Vorrede tolerant."""
    if not text:
        return None
    roh = text.strip()
    if roh.startswith("```"):
        roh = re.sub(r"^```[a-zA-Z]*\s*", "", roh)
        roh = re.sub(r"\s*```$", "", roh)
    versuche = [roh]
    start, ende = roh.find("{"), roh.rfind("}")
    if start >= 0 and ende > start:
        versuche.append(roh[start:ende + 1])
    for v in versuche:
        try:
            d = json.loads(v)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict):
            return d
    return None


def test_verbindung(konfig: dict, client: httpx.Client | None = None) -> dict:
    """Kleiner Testaufruf für den Admin-Knopf — Ergebnis immer sichtbar.

    Rückgabe: {"ok": bool, "dauer_s", "modell", "antwort"|"fehler"}.
    """
    prompt = ('Antworte ausschließlich mit JSON, ohne Erklärtext: {"ok": true}')
    try:
        erg = chat(konfig, prompt, max_tokens=48, client=client)
    except LLMFehler as e:
        return {"ok": False, "fehler": str(e), "basis_url": konfig.get("llm_base_url"),
                "modell": konfig.get("llm_model")}
    return {"ok": True, "dauer_s": erg["dauer_s"], "modell": erg["modell"],
            "basis_url": konfig.get("llm_base_url"),
            "antwort": erg["text"][:200],
            "json_erkannt": json_objekt(erg["text"]) is not None}
