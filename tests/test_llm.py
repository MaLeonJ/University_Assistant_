import base64
from typing import Any

import pytest

import asistente.llm as llm


@pytest.fixture(autouse=True)
def proveedor(monkeypatch):
    monkeypatch.setattr(llm, "AI_PROVIDER", "openrouter")
    monkeypatch.setattr(llm, "AI_API_KEY", "clave-test")
    monkeypatch.setattr(llm, "AI_MODEL", "modelo-test")
    monkeypatch.setattr(llm, "AI_FALLBACK_MODELS", ())
    llm._openai_client = None
    llm.reset_breakers()


class Respuesta:
    def __init__(self, texto):
        self.choices = [type("C", (), {"message": type("M", (), {"content": texto})()})]


class StubCompletions:
    def __init__(self, texto="OK"):
        self.texto = texto
        self.kwargs: Any = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return Respuesta(self.texto)


class ScriptedCompletions:
    """Devuelve o lanza efectos en orden; registra los modelos usados."""

    def __init__(self, efectos):
        self.efectos = list(efectos)
        self.llamadas: list[str] = []

    def create(self, **kwargs):
        self.llamadas.append(kwargs["model"])
        efecto = self.efectos.pop(0)
        if isinstance(efecto, Exception):
            raise efecto
        return Respuesta(efecto)


def _cliente_con(stub):
    cliente = type("Cliente", (), {})()
    cliente.chat = type("Chat", (), {})()
    cliente.chat.completions = stub
    return cliente


def test_sin_api_key_lanza_error(monkeypatch):
    monkeypatch.setattr(llm, "AI_API_KEY", None)
    with pytest.raises(RuntimeError):
        llm.generate("hola", system="s")


def test_proveedor_desconocido_lanza_error(monkeypatch):
    monkeypatch.setattr(llm, "AI_PROVIDER", "claude")
    with pytest.raises(ValueError):
        llm.generate("hola", system="s")


def test_ruta_openai_compatible_texto_plano(monkeypatch):
    stub = StubCompletions(texto="  respuesta  ")
    cliente = type("Cliente", (), {})()
    cliente.chat = type("Chat", (), {})()
    cliente.chat.completions = stub
    monkeypatch.setattr(llm, "_get_openai_client", lambda: cliente)

    resultado = llm.generate("pregunta", system="sistema")

    assert resultado == "respuesta"
    assert stub.kwargs["model"] == "modelo-test"
    assert stub.kwargs["messages"][0] == {"role": "system", "content": "sistema"}
    assert stub.kwargs["messages"][1]["content"] == "pregunta"


def test_ruta_vision_incluye_imagen_base64(monkeypatch):
    stub = StubCompletions()
    cliente = type("Cliente", (), {})()
    cliente.chat = type("Chat", (), {})()
    cliente.chat.completions = stub
    monkeypatch.setattr(llm, "_get_openai_client", lambda: cliente)

    datos = b"imagen-falsa"
    llm.generate("qué ves", system="s", images=[(datos, "image/png")])

    contenido = stub.kwargs["messages"][1]["content"]
    assert contenido[0] == {"type": "text", "text": "qué ves"}
    esperado = base64.b64encode(datos).decode("ascii")
    assert contenido[1]["image_url"]["url"] == f"data:image/png;base64,{esperado}"


def test_respuesta_nula_se_convierte_en_cadena_vacia(monkeypatch):
    stub = StubCompletions(texto=None)
    cliente = type("Cliente", (), {})()
    cliente.chat = type("Chat", (), {})()
    cliente.chat.completions = stub
    monkeypatch.setattr(llm, "_get_openai_client", lambda: cliente)

    assert llm.generate("x", system="s") == ""


def test_cliente_openai_se_instancia_una_sola_vez(monkeypatch):
    creados = []

    class StubOpenAI:
        def __init__(self, api_key, base_url):
            creados.append((api_key, base_url))
            self.chat = type("Chat", (), {})()
            self.chat.completions = StubCompletions()

    monkeypatch.setattr("openai.OpenAI", StubOpenAI)

    llm._generate_openai_compatible("modelo-test", "a", "s", None)
    llm._generate_openai_compatible("modelo-test", "b", "s", None)

    assert len(creados) == 1
    assert creados[0] == ("clave-test", "https://openrouter.ai/api/v1")


def test_base_url_de_openrouter_registrada():
    assert llm.OPENAI_BASE_URLS["openrouter"] == "https://openrouter.ai/api/v1"


def test_ruta_gemini_texto(monkeypatch):
    capturado: dict[str, Any] = {}

    class StubModels:
        def generate_content(self, model, contents, config):
            capturado.update(model=model, contents=contents, config=config)
            return type("Respuesta", (), {"text": " GEMINI_OK "})()

    class StubClient:
        def __init__(self, api_key):
            capturado["api_key"] = api_key
            self.models = StubModels()

    monkeypatch.setattr("google.genai.Client", StubClient)
    monkeypatch.setattr(llm, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(llm, "AI_MODEL", "gemini-test")

    assert llm.generate("pregunta", system="sistema") == "GEMINI_OK"
    assert capturado["model"] == "gemini-test"
    assert capturado["contents"] == ["pregunta"]
    assert capturado["config"] == {"system_instruction": "sistema"}


def test_ruta_gemini_vision(monkeypatch):
    class StubModels:
        def generate_content(self, model, contents, config):
            return type("Respuesta", (), {"text": "OK"})()

    class StubClient:
        def __init__(self, api_key):
            self.models = StubModels()

    monkeypatch.setattr("google.genai.Client", StubClient)
    monkeypatch.setattr(llm, "AI_PROVIDER", "gemini")

    resultado = llm.generate("qué ves", system="s", images=[(b"img", "image/png")])
    assert resultado == "OK"


def test_fallback_al_siguiente_modelo(monkeypatch):
    stub = ScriptedCompletions([RuntimeError("modelo muerto"), "OK-DE-B"])
    monkeypatch.setattr(llm, "_get_openai_client", lambda: _cliente_con(stub))
    monkeypatch.setattr(llm, "AI_FALLBACK_MODELS", ("modelo-b",))

    assert llm.generate("x", system="s") == "OK-DE-B"
    assert stub.llamadas == ["modelo-test", "modelo-b"]


def test_fallback_deduplica_el_modelo_principal(monkeypatch):
    stub = ScriptedCompletions(["OK"])
    monkeypatch.setattr(llm, "_get_openai_client", lambda: _cliente_con(stub))
    monkeypatch.setattr(llm, "AI_FALLBACK_MODELS", ("modelo-test", "otro"))

    llm.generate("x", system="s")

    assert stub.llamadas == ["modelo-test"]


def test_circuit_abre_tras_umbral_y_omite_llamadas(monkeypatch):
    stub = ScriptedCompletions([RuntimeError("x")] * 3)
    monkeypatch.setattr(llm, "_get_openai_client", lambda: _cliente_con(stub))

    for _ in range(3):
        with pytest.raises(RuntimeError):
            llm.generate("x", system="s")
    assert len(stub.llamadas) == 3

    with pytest.raises(RuntimeError, match="Ningún modelo"):
        llm.generate("x", system="s")

    assert len(stub.llamadas) == 3


def test_exito_reinicia_el_contador_de_fallos(monkeypatch):
    stub = ScriptedCompletions(
        [RuntimeError("a"), RuntimeError("b"), "OK", RuntimeError("c"), "OK2"]
    )
    monkeypatch.setattr(llm, "_get_openai_client", lambda: _cliente_con(stub))

    with pytest.raises(RuntimeError):
        llm.generate("x", system="s")
    with pytest.raises(RuntimeError):
        llm.generate("x", system="s")

    assert llm.generate("x", system="s") == "OK"

    with pytest.raises(RuntimeError):
        llm.generate("x", system="s")

    breaker = llm._breakers["modelo-test"]
    assert breaker.failures == 1
    assert breaker.opened_at is None
    assert llm.generate("x", system="s") == "OK2"


def test_cooldown_permite_reintento_de_sondeo(monkeypatch):
    breaker = llm.CircuitBreaker(threshold=1, cooldown=300)
    breaker.record_failure()
    assert not breaker.allow()

    real_monotonic = llm.time.monotonic
    monkeypatch.setattr(llm.time, "monotonic", lambda: real_monotonic() + 301)

    assert breaker.allow()
    breaker.record_success()
    assert breaker.allow()
    assert breaker.failures == 0
