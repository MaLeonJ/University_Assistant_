import pytest

import asistente.analyzer as analyzer


@pytest.fixture(autouse=True)
def registro(monkeypatch):
    llamadas = []
    monkeypatch.setattr(analyzer, "register_call", lambda: llamadas.append(1))
    return llamadas


RESULTADOS = [{"title": "Fuente", "url": "https://x.com", "snippet": "resumen"}]


def test_sin_resultados_no_consumen_ia(registro):
    texto = analyzer.analyze_topic("tema", [])
    assert "No se encontraron resultados" in texto
    assert not registro


def test_analisis_exitoso(monkeypatch, registro):
    monkeypatch.setattr(analyzer, "generate", lambda *a, **k: "TEXTO FINAL")
    assert analyzer.analyze_topic("tema", RESULTADOS) == "TEXTO FINAL"
    assert len(registro) == 1


def test_respuesta_vacia_cae_a_fallback(monkeypatch, registro):
    monkeypatch.setattr(analyzer, "generate", lambda *a, **k: "")
    texto = analyzer.analyze_topic("tema", RESULTADOS)
    assert "sin IA" in texto
    assert "Fuente" in texto
    assert not registro


def test_error_del_proveedor_cae_a_fallback(monkeypatch):
    def explota(*a, **k):
        raise RuntimeError("cuota agotada")

    monkeypatch.setattr(analyzer, "generate", explota)
    texto = analyzer.analyze_topic("tema", RESULTADOS)
    assert "resumen" in texto


def test_vision_extrae_json_con_fences(monkeypatch, registro):
    monkeypatch.setattr(
        analyzer,
        "generate",
        lambda *a, **k: '```json\n{"title": "Pizarrón BD", "topics": ["E-R"]}\n```',
    )
    resultado = analyzer.extract_topics_from_image(b"img", "image/png")
    assert resultado == ("Pizarrón BD", ["E-R"])
    assert len(registro) == 1


def test_vision_json_invalido_devuelve_none(monkeypatch):
    monkeypatch.setattr(analyzer, "generate", lambda *a, **k: "{no es json")
    assert analyzer.extract_topics_from_image(b"img", "image/png") is None


def test_vision_sin_temas_devuelve_none(monkeypatch):
    monkeypatch.setattr(analyzer, "generate", lambda *a, **k: '{"title": "T"}')
    assert analyzer.extract_topics_from_image(b"img", "image/png") is None


def test_vision_con_error_devuelve_none(monkeypatch):
    def explota(*a, **k):
        raise RuntimeError("sin visión")

    monkeypatch.setattr(analyzer, "generate", explota)
    assert analyzer.extract_topics_from_image(b"img", "image/png") is None
