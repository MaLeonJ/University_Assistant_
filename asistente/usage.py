import json
import logging
from datetime import date

from .config import AI_DAILY_LIMIT, USAGE_FILE

logger = logging.getLogger(__name__)


def _load() -> dict:
    try:
        data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if data.get("date") != str(date.today()):
        return {}
    return {"date": data["date"], "count": int(data.get("count", 0))}


def _save(data: dict) -> None:
    USAGE_FILE.write_text(json.dumps(data), encoding="utf-8")


def register_call() -> int:
    data = _load()
    data["date"] = str(date.today())
    data["count"] = data.get("count", 0) + 1
    _save(data)
    return data["count"]


def get_usage() -> tuple[int, int]:
    return _load().get("count", 0), AI_DAILY_LIMIT


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
