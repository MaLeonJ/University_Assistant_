"""Exportación de documentos a PDF/DOCX mediante pandoc.

- `resolver_documento()` elige el objetivo: sin términos devuelve el más
  reciente; con términos usa el índice full-text (`indexer.search`).
- `exportar()` convierte con pandoc; si no está instalado o falla, lanza
  `RuntimeError` con un mensaje accionable (el bot lo muestra tal cual).
"""

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import indexer
from .config import OUTPUT_DIR
from .writer import list_months

logger = logging.getLogger(__name__)

FORMATOS = ("pdf", "docx")

# Emojis y símbolos pictográficos que LaTeX no tiene en sus fuentes por
# defecto. Se conservan símbolos matemáticos (≤ ≈ ∈ viven fuera de estos
# rangos) para no dañar contenido académico.
EMOJIS = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\ufe0f\u200d]")


def pandoc_disponible() -> bool:
    return shutil.which("pandoc") is not None


def _sin_emojis(md_path: Path) -> Path:
    """Copia temporal del documento sin emojis (solo para el motor PDF)."""
    texto = EMOJIS.sub("", md_path.read_text(encoding="utf-8"))
    fd, nombre = tempfile.mkstemp(suffix=".md", dir=md_path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(texto)
    return Path(nombre)


def resolver_documento(termino: str = "") -> Path | None:
    """Elige el documento a exportar: el más reciente o el mejor match."""
    if termino.strip():
        indexer.sync_index()
        hits = indexer.search(termino, limit=1)
        if not hits:
            return None
        return OUTPUT_DIR / hits[0]["path"]

    meses = list_months()
    if not meses:
        return None
    return meses[0][1][-1]


def exportar(md_path: Path, formato: str) -> Path:
    """Convierte md_path al formato pedido; devuelve la ruta generada."""
    if formato not in FORMATOS:
        raise ValueError(f"Formato no soportado: {formato}. Opciones: {', '.join(FORMATOS)}")
    if not pandoc_disponible():
        raise RuntimeError("pandoc no está instalado. En Pop!_OS/Ubuntu: sudo apt install pandoc")

    salida = md_path.with_suffix("." + formato)
    fuente = md_path
    cmd = ["pandoc"]
    if formato == "pdf":
        cmd += ["--pdf-engine=xelatex"]
        fuente = _sin_emojis(md_path)

    try:
        cmd += [str(fuente), "-o", str(salida)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("pandoc tardó demasiado y se canceló") from e
    finally:
        if fuente != md_path:
            fuente.unlink(missing_ok=True)

    if proc.returncode != 0:
        detalle = (proc.stderr or "").strip().splitlines()
        raise RuntimeError(f"pandoc falló: {detalle[-1] if detalle else 'sin detalle'}")

    logger.info("Exportado %s → %s", md_path.name, salida.name)
    return salida
