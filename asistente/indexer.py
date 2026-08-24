"""Índice full-text (SQLite FTS5) sobre la biblioteca de documentos generados.

- `sync_index()` sincroniza incrementalmente contra el disco comparando
  hashes: alta/actualización/baja de cada `.md` (ignora índices mensuales).
- `search()` busca por términos; el tokenizador elimina diacríticos, así
  que «ecuacion» encuentra «ecuación», y cada término se busca como
  prefijo citado («derivada» encuentra «derivadas»; OR/AND no rompen
  nada porque van dentro de la cita). La consulta del usuario nunca
  llega cruda a MATCH.
"""

import hashlib
import logging
import re
import sqlite3
from pathlib import Path

from .config import INDEX_DB, OUTPUT_DIR

logger = logging.getLogger(__name__)

FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
TITULO = re.compile(r"^# (.+)$", re.MULTILINE)
TERMINO = re.compile(r"[\wáéíóúüñ]+", re.UNICODE)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    hash TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
    path UNINDEXED,
    title,
    month,
    body,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def _connect(db_path=None) -> sqlite3.Connection:
    db_path = db_path or INDEX_DB
    conn = sqlite3.connect(db_path, timeout=5)
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(_SCHEMA)
    return conn


def _documentos(docs_dir: Path) -> list[tuple[Path, Path]]:
    pares = [
        (f.relative_to(docs_dir), f)
        for f in sorted(docs_dir.rglob("*.md"))
        if f.name != "00_Índice.md"
    ]
    return pares


def _extraer(texto: str, rel: Path) -> tuple[str, str]:
    cuerpo = FRONTMATTER.sub("", texto, count=1)
    m = TITULO.search(cuerpo)
    titulo = m.group(1).strip() if m else rel.stem
    mes = rel.parent.as_posix()
    return titulo, "" if mes == "." else mes


def sync_index(db_path=None, docs_dir=None) -> tuple[int, int, int]:
    """Sincroniza el índice con el disco. Devuelve (altas, actualizadas, bajas)."""
    docs_dir = Path(docs_dir or OUTPUT_DIR)
    altas = actualizadas = bajas = 0
    actuales: dict[str, str] = {}

    with _connect(db_path) as conn:
        for rel, abs_path in _documentos(docs_dir):
            actuales[rel.as_posix()] = hashlib.sha256(abs_path.read_bytes()).hexdigest()

        previos: dict[str, str] = dict(conn.execute("SELECT path, hash FROM files"))

        for ruta, digest in actuales.items():
            if previos.get(ruta) == digest:
                continue
            texto = (docs_dir / ruta).read_text(encoding="utf-8", errors="replace")
            titulo, mes = _extraer(texto, Path(ruta))
            conn.execute("DELETE FROM docs WHERE path = ?", (ruta,))
            conn.execute(
                "INSERT INTO docs (path, title, month, body) VALUES (?, ?, ?, ?)",
                (ruta, titulo, mes, texto),
            )
            conn.execute("INSERT OR REPLACE INTO files (path, hash) VALUES (?, ?)", (ruta, digest))
            if ruta in previos:
                actualizadas += 1
            else:
                altas += 1

        for ruta in sorted(set(previos) - set(actuales)):
            conn.execute("DELETE FROM docs WHERE path = ?", (ruta,))
            conn.execute("DELETE FROM files WHERE path = ?", (ruta,))
            bajas += 1

    return altas, actualizadas, bajas


def _consulta_segura(query: str, max_terminos: int = 8) -> str:
    """Términos citados con prefijo: «derivada» encuentra «derivadas», y
    palabras reservadas de FTS5 (OR, AND, NOT…) se buscan como texto."""
    terminos = TERMINO.findall(query)[:max_terminos]
    return " ".join(f'"{t}"*' for t in terminos)


def search(query: str, limit: int = 5, db_path=None) -> list[dict[str, str]]:
    """Busca en la biblioteca. Devuelve [{path, title, month, snippet}]."""
    consulta = _consulta_segura(query)
    if not consulta:
        return []
    with _connect(db_path) as conn:
        filas = conn.execute(
            """
            SELECT path, title, month,
                   snippet(docs, 3, '«', '»', ' … ', 18) AS frag
            FROM docs WHERE docs MATCH ?
            ORDER BY rank LIMIT ?
            """,
            (consulta, limit),
        ).fetchall()
    return [{"path": p, "title": t, "month": m, "snippet": s} for p, t, m, s in filas]
