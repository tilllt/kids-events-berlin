"""Change 010: LLM-Client (Endpunkt konfigurierbar, Fehler sichtbar)."""
import json

import httpx
import pytest

from app.recherche import llm
from app.store import Store


def _store(tmp_path, **settings):
    s = Store(tmp_path / "llm.db")
    for k, v in settings.items():
        s.set_setting(k, v)
    return s


def test_standard_endpunkt_ist_die_ki_box(tmp_path):
    s = _store(tmp_path)
    k = llm.konfiguration(s)
    assert k["llm_base_url"] == "http://192.168.178.140:8088/v1"
    assert k["llm_model"] == "llamacpp-gemma4-12B-unsloth"
    # Pflicht bei Gemma-4: Thinking aus, sonst leere Antwort
    assert json.loads(k["llm_extra_json"])["chat_template_kwargs"]["enable_thinking"] is False
    s.close()


def test_einstellungen_ueberschreiben_standard(tmp_path):
    s = _store(tmp_path, llm_base_url="https://litellm.n0ne.de/v1",
               llm_model="kibox/gemma-4-12b", llm_api_key="geheim")
    k = llm.konfiguration(s)
    assert k["llm_base_url"] == "https://litellm.n0ne.de/v1"
    assert k["llm_model"] == "kibox/gemma-4-12b" and k["llm_api_key"] == "geheim"
    s.close()


def test_leere_einstellung_faellt_auf_standard_zurueck(tmp_path):
    s = _store(tmp_path, llm_model="   ")
    assert llm.konfiguration(s)["llm_model"] == llm.STANDARD["llm_model"]
    s.close()


def test_zusatz_parameter_muessen_json_objekt_sein(tmp_path):
    s = _store(tmp_path, llm_extra_json="{kaputt")
    with pytest.raises(llm.LLMFehler, match="gültiges JSON"):
        llm.zusatz_parameter(llm.konfiguration(s))
    (tmp_path / "b").mkdir(exist_ok=True)
    s2 = _store(tmp_path / "b", llm_extra_json='["liste"]')
    with pytest.raises(llm.LLMFehler, match="JSON-Objekt"):
        llm.zusatz_parameter(llm.konfiguration(s2))
    s.close()
    s2.close()


def _client(antwort: dict, *status: int) -> httpx.Client:
    code = status[0] if status else 200

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content)
        # Die Zusatz-Parameter müssen beim Endpunkt ankommen (Thinking-Schalter).
        assert body["chat_template_kwargs"]["enable_thinking"] is False
        assert body["temperature"] == 0
        return httpx.Response(code, json=antwort)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _antwort(text: str, modell: str = "llamacpp-gemma4-12B-unsloth") -> dict:
    return {"model": modell, "choices": [{"finish_reason": "stop",
                                          "message": {"role": "assistant", "content": text}}],
            "usage": {"completion_tokens": 12}}


def test_chat_liefert_text_und_dauer(tmp_path):
    s = _store(tmp_path)
    c = _client(_antwort('{"termine": []}'))
    erg = llm.chat(llm.konfiguration(s), "Prompt", client=c)
    assert erg["text"] == '{"termine": []}' and erg["dauer_s"] >= 0
    assert erg["tokens"]["completion_tokens"] == 12
    s.close()


def test_leere_antwort_erklaert_den_thinking_schalter(tmp_path):
    s = _store(tmp_path, llm_extra_json="{}")
    antwort = {"model": "m", "choices": [{"finish_reason": "length",
                                         "message": {"content": "", "reasoning_content": "denkt"}}]}
    c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=antwort)))
    # reasoning_content wird toleriert (Fallback), Text ist trotzdem da
    assert llm.chat(llm.konfiguration(s), "x", client=c)["text"] == "denkt"

    leer = {"model": "m", "choices": [{"finish_reason": "length", "message": {"content": ""}}]}
    c2 = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=leer)))
    with pytest.raises(llm.LLMFehler, match="enable_thinking"):
        llm.chat(llm.konfiguration(s), "x", client=c2)
    s.close()


def test_http_fehler_und_netzfehler_sind_sichtbar(tmp_path):
    s = _store(tmp_path)
    c = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(503, text="Loading model")))
    with pytest.raises(llm.LLMFehler, match="HTTP 503"):
        llm.chat(llm.konfiguration(s), "x", client=c)

    def kaputt(request):
        raise httpx.ConnectError("kein Netz")

    c2 = httpx.Client(transport=httpx.MockTransport(kaputt))
    with pytest.raises(llm.LLMFehler, match="nicht erreichbar"):
        llm.chat(llm.konfiguration(s), "x", client=c2)
    s.close()


def test_ungueltige_basis_url_wird_abgewiesen(tmp_path):
    s = _store(tmp_path, llm_base_url="192.168.178.140:8088/v1")
    with pytest.raises(llm.LLMFehler, match="http://"):
        llm.chat(llm.konfiguration(s), "x", client=_client(_antwort("{}")))
    s.close()


def test_json_objekt_ist_tolerant():
    assert llm.json_objekt('```json\n{"termine": []}\n```') == {"termine": []}
    assert llm.json_objekt('Hier das Ergebnis: {"a": 1} — fertig') == {"a": 1}
    assert llm.json_objekt("kein json") is None
    assert llm.json_objekt("") is None


def test_test_verbindung_meldet_ok_und_fehler(tmp_path):
    s = _store(tmp_path)
    k = llm.konfiguration(s)
    ok = llm.test_verbindung(k, client=_client(_antwort('{"ok": true}')))
    assert ok["ok"] and ok["json_erkannt"] and ok["modell"] == "llamacpp-gemma4-12B-unsloth"

    c = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(500, text="boom")))
    schlecht = llm.test_verbindung(k, client=c)
    assert schlecht["ok"] is False and "HTTP 500" in schlecht["fehler"]
    assert schlecht["basis_url"] == k["llm_base_url"]
    s.close()
