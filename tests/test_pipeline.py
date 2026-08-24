import asyncio
import time

import asistente.pipeline as pipeline
from asistente.searcher import SearchResult


def _conectar_fakes(monkeypatch, retardo=0.0):
    def fake_search(topic, n=None):
        time.sleep(retardo)
        return [SearchResult(title=topic, url="https://x.com", snippet="s")]

    def fake_analyze(topic, results):
        return f"SECCIÓN-{topic}"

    monkeypatch.setattr(pipeline, "search_topic", fake_search)
    monkeypatch.setattr(pipeline, "analyze_topic", fake_analyze)


def test_orden_y_resultados_por_tema(monkeypatch):
    _conectar_fakes(monkeypatch)

    secciones, por_tema = asyncio.run(pipeline.research_topics(["a", "b", "c"]))

    assert secciones == ["SECCIÓN-a", "SECCIÓN-b", "SECCIÓN-c"]
    assert set(por_tema) == {"a", "b", "c"}
    assert por_tema["b"][0].title == "b"


def test_temas_corren_en_paralelo(monkeypatch):
    _conectar_fakes(monkeypatch, retardo=0.2)

    inicio = time.monotonic()
    secciones, _ = asyncio.run(pipeline.research_topics(["a", "b", "c"]))
    duracion = time.monotonic() - inicio

    assert secciones == ["SECCIÓN-a", "SECCIÓN-b", "SECCIÓN-c"]
    assert duracion < 0.55


def test_max_results_se_propaga(monkeypatch):
    recibido = {}

    def fake_search(topic, n=None):
        recibido["n"] = n
        return []

    monkeypatch.setattr(pipeline, "search_topic", fake_search)
    monkeypatch.setattr(pipeline, "analyze_topic", lambda t, r: "s")

    asyncio.run(pipeline.research_topics(["a"], max_results=3))

    assert recibido["n"] == 3


def test_segunda_vuelta_usa_cache(monkeypatch):
    llamadas = {"search": 0, "analyze": 0}

    def fake_search(topic, n=None):
        llamadas["search"] += 1
        return [SearchResult(title=topic, url=f"https://{topic}.com", snippet="s")]

    def fake_analyze(topic, results):
        llamadas["analyze"] += 1
        return f"SECCIÓN-{topic}"

    monkeypatch.setattr(pipeline, "search_topic", fake_search)
    monkeypatch.setattr(pipeline, "analyze_topic", fake_analyze)

    asyncio.run(pipeline.research_topics(["a", "b"]))
    asyncio.run(pipeline.research_topics(["a", "b"]))

    assert llamadas == {"search": 2, "analyze": 2}


def test_fallback_no_se_cachea(monkeypatch):
    llamadas = {"analyze": 0}

    def fake_search(topic, n=None):
        return [SearchResult(title=topic, url="https://x.com", snippet="s")]

    def fake_analyze(topic, results):
        llamadas["analyze"] += 1
        return "_Contenido generado sin IA (cuota agotada o error)._"

    monkeypatch.setattr(pipeline, "search_topic", fake_search)
    monkeypatch.setattr(pipeline, "analyze_topic", fake_analyze)

    asyncio.run(pipeline.research_topics(["a"]))
    asyncio.run(pipeline.research_topics(["a"]))

    assert llamadas["analyze"] == 2
