"""Contador diario de llamadas IA con historial reciente (para /stats).

Esquema v2 de usage.json: {"days": {"YYYY-MM-DD": N}} conservando los
últimos HISTORIAL_DIAS. Al leer, un archivo v1 ({date, count}) se migra
en memoria sin reescribirlo hasta la próxima llamada registrada.
"""

import json
import logging
import threading
from datetime import date, timedelta

from .config import AI_DAILY_LIMIT, USAGE_FILE

logger = logging.getLogger(__name__)

HISTORIAL_DIAS = 30
_lock = threading.Lock()


def _hoy() -> str:
    return str(date.today())


def _load() -> dict[str, int]:
    try:
        data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if isinstance(data.get("days"), dict):
        crudo = data["days"]
    elif isinstance(data, dict) and "date" in data:
        crudo = {data["date"]: data.get("count", 0)}
    else:
        return {}

    dias: dict[str, int] = {}
    for k, v in crudo.items():
        try:
            dias[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return dict(sorted(dias.items())[-HISTORIAL_DIAS:])


def _save(dias: dict[str, int]) -> None:
    USAGE_FILE.write_text(json.dumps({"days": dias}), encoding="utf-8")


def register_call() -> int:
    with _lock:
        dias = _load()
        hoy = _hoy()
        dias[hoy] = dias.get(hoy, 0) + 1
        _save(dias)
        return dias[hoy]


def get_usage() -> tuple[int, int]:
    return _load().get(_hoy(), 0), AI_DAILY_LIMIT


def historial(n: int = 7) -> list[tuple[str, int]]:
    """Últimos n días con actividad registrada, en orden cronológico."""
    dias = _load()
    return sorted(dias.items())[-n:]


def total(n_dias: int) -> int:
    """Llamadas acumuladas en los últimos n_dias naturales (incluye hoy)."""
    limite = date.today() - timedelta(days=n_dias - 1)
    return sum(c for f, c in _load().items() if date.fromisoformat(f) >= limite)


def format_usage() -> str:
    used, limit = get_usage()
    left = max(limit - used, 0)
    bar_len = 20
    filled = int(bar_len * used / limit) if limit else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    pct = int(used * 100 / limit) if limit else 0
    return (
        f"📊 *Uso de la IA (hoy)*\n\n"
        f"`{bar}` {pct}%\n"
        f"• Usadas hoy: *{used}*\n"
        f"• Restantes: *{left}*\n"
        f"• Límite diario configurado: {limit}\n\n"
        "_Contador local aproximado. El límite real lo define el proveedor "
        "de IA según el modelo y puede variar._"
    )
