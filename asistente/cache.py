"""Cache SQLite de búsquedas y análisis (ahorra cuota de IA en re-consultas).

- Búsquedas: se cachean por tema con TTL (`CACHE_TTL_DAYS`).
- Análisis: se cachean por clave (tema + fuentes + proveedor + modelo), sin TTL:
  si cambian las fuentes o el modelo, la clave cambia y se regenera.

Las conexiones son de vida corta por operación, con `busy_timeout` para
tolerar escrituras concurrentes desde los threads del pipeline.
"""

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import asdict

from .config import CACHE_DB, CACHE_TTL_DAYS
from .searcher import SearchResult

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    query   TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    key     TEXT PRIMARY KEY,
    text    TEXT NOT NULL,
    created REAL NOT NULL
);
"""


def _connect(db_path=None) -> sqlite3.Connection:
    db_path = db_path or CACHE_DB
    conn = sqlite3.connect(db_path, timeout=5)
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(_SCHEMA)
    return conn


def get_search(topic: str, db_path=None) -> list[SearchResult] | None:
    try:
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT payload, created FROM searches WHERE query = ?", (topic,)
            ).fetchone()
    except sqlite3.Error as e:
        logger.warning("Cache de búsquedas no disponible: %s", e)
        return None
    if row is None:
        return None
    if time.time() - row[1] > CACHE_TTL_DAYS * 86400:
        return None
    return [SearchResult(**d) for d in json.loads(row[0])]


def put_search(topic: str, results: list[SearchResult], db_path=None) -> None:
    try:
        with _connect(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO searches (query, payload, created) VALUES (?, ?, ?)",
                (topic, json.dumps([asdict(r) for r in results]), time.time()),
            )
    except sqlite3.Error as e:
        logger.warning("No se pudo guardar la búsqueda en cache: %s", e)


def analysis_key(topic: str, results: list[SearchResult], provider: str, model: str) -> str:
    fuente = "|".join(sorted(r.url for r in results))
    base = f"{provider}|{model}|{topic}|{fuente}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def get_analysis(key: str, db_path=None) -> str | None:
    try:
        with _connect(db_path) as conn:
            row = conn.execute("SELECT text FROM analyses WHERE key = ?", (key,)).fetchone()
    except sqlite3.Error as e:
        logger.warning("Cache de análisis no disponible: %s", e)
        return None
    return row[0] if row else None


def put_analysis(key: str, text: str, db_path=None) -> None:
    try:
        with _connect(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO analyses (key, text, created) VALUES (?, ?, ?)",
                (key, text, time.time()),
            )
    except sqlite3.Error as e:
        logger.warning("No se pudo guardar el análisis en cache: %s", e)
