from typing import ClassVar

import pytest

import asistente.searcher as searcher
from asistente.searcher import SearchResult


class FakeDDGS:
    """Sustituye a ddgs.DDGS: lanza o devuelve según los efectos configurados."""

    efectos: ClassVar[list] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def text(self, query, max_results):
        efecto = FakeDDGS.efectos.pop(0)
        if isinstance(efecto, Exception):
            raise efecto
        return efecto


@pytest.fixture
def fake_ddgs(monkeypatch):
    FakeDDGS.efectos = []
    monkeypatch.setattr(searcher, "DDGS", FakeDDGS)
    monkeypatch.setattr(searcher.time, "sleep", lambda s: None)
    return FakeDDGS


def test_busqueda_exitosa_al_primer_intento(fake_ddgs):
    fake_ddgs.efectos = [[{"title": "T", "href": "https://x.com", "body": "resumen"}]]
    resultados = searcher.search_topic("tema")
    assert resultados == [SearchResult(title="T", url="https://x.com", snippet="resumen")]


def test_reintenta_tras_fallos_y_recupera(fake_ddgs):
    fake_ddgs.efectos = [RuntimeError("fallo 1"), RuntimeError("fallo 2")]
    fake_ddgs.efectos.append([{"title": "T", "href": "u", "body": "b"}])
    assert len(searcher.search_topic("tema")) == 1


def test_agota_intentos_y_devuelve_vacio(fake_ddgs):
    fake_ddgs.efectos = [RuntimeError("x")] * searcher.RETRIES
    assert searcher.search_topic("tema") == []


def test_resultados_vacios_siguen_reintentando(fake_ddgs):
    fake_ddgs.efectos = [[], [{"title": "T", "href": "u", "body": "b"}]]
    assert len(searcher.search_topic("tema")) == 1


def test_max_results_por_defecto(fake_ddgs, monkeypatch):
    recibido = {}
    original = FakeDDGS.text

    def text(self, query, max_results):
        recibido["max"] = max_results
        return original(self, query, max_results)

    monkeypatch.setattr(FakeDDGS, "text", text)
    fake_ddgs.efectos = [[]]
    searcher.search_topic("tema")
    assert recibido["max"] == searcher.SEARCH_MAX_RESULTS
