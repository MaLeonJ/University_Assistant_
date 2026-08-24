import base64
from typing import Any

import pytest

import asistente.llm as llm


@pytest.fixture(autouse=True)
def proveedor(monkeypatch):
    monkeypatch.setattr(llm, "AI_PROVIDER", "openrouter")
    monkeypatch.setattr(llm, "AI_API_KEY", "clave-test")
    monkeypatch.setattr(llm, "AI_MODEL", "modelo-test")
    llm._openai_client = None


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

    llm._generate_openai_compatible("a", "s", None)
    llm._generate_openai_compatible("b", "s", None)

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
