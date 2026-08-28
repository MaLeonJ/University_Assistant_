import json
import logging
from typing import Any

from .config import MATERIAS_FILE

logger = logging.getLogger(__name__)


def _cargar() -> dict[str, Any]:
    if not MATERIAS_FILE.exists():
        return {"materias": [], "activa": None}
    try:
        with MATERIAS_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            if not isinstance(data, dict):
                return {"materias": [], "activa": None}
            return {
                "materias": [str(m).strip() for m in data.get("materias", []) if str(m).strip()],
                "activa": data.get("activa"),
            }
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Error leyendo materias.json: %s", e)
        return {"materias": [], "activa": None}


def _guardar(data: dict[str, Any]) -> None:
    MATERIAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with MATERIAS_FILE.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def get_materias() -> list[str]:
    return _cargar()["materias"]


def get_materia_activa() -> str | None:
    data = _cargar()
    activa = data.get("activa")
    if activa and activa in data["materias"]:
        return activa
    return None


def set_materia_activa(nombre: str | None) -> bool:
    data = _cargar()
    if nombre is not None:
        nombre = nombre.strip()
        if nombre not in data["materias"]:
            return False
    data["activa"] = nombre
    _guardar(data)
    return True


def agregar_materia(nombre: str) -> bool:
    nombre = nombre.strip()
    if not nombre:
        return False
    data = _cargar()
    if nombre in data["materias"]:
        return False
    data["materias"].append(nombre)
    if data["activa"] is None:
        data["activa"] = nombre
    _guardar(data)
    return True


def eliminar_materia(nombre: str) -> bool:
    nombre = nombre.strip()
    data = _cargar()
    if nombre not in data["materias"]:
        return False
    data["materias"].remove(nombre)
    if data["activa"] == nombre:
        data["activa"] = data["materias"][0] if data["materias"] else None
    _guardar(data)
    return True
