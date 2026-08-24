"""Fixtures compartidas: aislan rutas de salida, estado y logging en temporales."""

import json
import logging
from logging.handlers import RotatingFileHandler

import pytest


@pytest.fixture(autouse=True)
def sin_log_a_archivo():
    """Evita que los tests escriban en el bot.log real del desarrollador."""
    root = logging.getLogger()
    archivo = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    for h in archivo:
        root.removeHandler(h)
    yield
    for h in archivo:
        root.addHandler(h)


@pytest.fixture
def output_dirs(tmp_path, monkeypatch):
    """Redirige documentos/ y el vault Obsidian a carpetas temporales."""
    out = tmp_path / "documentos"
    vault = tmp_path / "vault"
    import asistente.syncer as syncer
    import asistente.writer as writer

    monkeypatch.setattr(writer, "OUTPUT_DIR", out)
    monkeypatch.setattr(syncer, "OUTPUT_DIR", out)
    monkeypatch.setattr(syncer, "OBSIDIAN_DIR", vault)
    return {"out": out, "vault": vault}


@pytest.fixture(autouse=True)
def cache_db_tmp(tmp_path, monkeypatch):
    """Redirige el cache SQLite a un archivo temporal."""
    import asistente.cache as cache

    db = tmp_path / "data" / "cache.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cache, "CACHE_DB", str(db))
    return db


@pytest.fixture
def usage_file(tmp_path, monkeypatch):
    """Redirige el contador diario a un archivo temporal."""
    import asistente.usage as usage

    path = tmp_path / "data" / "usage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(usage, "USAGE_FILE", path)
    monkeypatch.setattr(usage, "AI_DAILY_LIMIT", 100)
    return path


@pytest.fixture
def write_usage(usage_file):
    def _write(date: str, count: int) -> None:
        usage_file.parent.mkdir(parents=True, exist_ok=True)
        usage_file.write_text(json.dumps({"date": date, "count": count}))

    return _write
