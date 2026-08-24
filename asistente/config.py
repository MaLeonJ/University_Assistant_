import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
USAGE_FILE = DATA_DIR / "usage.json"
CACHE_DB = DATA_DIR / "cache.db"
CACHE_TTL_DAYS = int(os.getenv("CACHE_TTL_DAYS", "7"))

LOG_DIR = Path(os.getenv("LOG_DIR", BASE_DIR / "logs"))
LOG_FILE = LOG_DIR / "bot.log"

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "documentos"))
OBSIDIAN_DIR = Path(
    os.getenv(
        "OBSIDIAN_DIR",
        Path.home() / "GoogleDrive/Obsidian/Notebook/Universidad",
    )
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AUTHORIZED_USER_ID = int(os.getenv("AUTHORIZED_USER_ID", "0"))
SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "5"))

AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini")
AI_API_KEY = os.getenv("AI_API_KEY")
AI_DAILY_LIMIT = int(os.getenv("AI_DAILY_LIMIT", "100"))

DEFAULT_MODELS = {
    "gemini": "gemini-3.5-flash",
    "openrouter": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
}
AI_MODEL = os.getenv("AI_MODEL") or DEFAULT_MODELS.get(AI_PROVIDER, "")
AI_FALLBACK_MODELS = tuple(
    m.strip() for m in os.getenv("AI_FALLBACK_MODELS", "").split(",") if m.strip()
)

VALID_PROVIDERS = ("gemini", "openrouter")


def validate() -> list[str]:
    errors = []
    if not TELEGRAM_TOKEN:
        errors.append("Falta TELEGRAM_TOKEN en .env")
    if not AI_API_KEY:
        errors.append("Falta AI_API_KEY en .env (clave del proveedor de IA)")
    if not AUTHORIZED_USER_ID:
        errors.append("Falta AUTHORIZED_USER_ID en .env (tu ID de Telegram)")
    if AI_PROVIDER not in VALID_PROVIDERS:
        errors.append(
            f"AI_PROVIDER='{AI_PROVIDER}' no válido. Opciones: {', '.join(VALID_PROVIDERS)}"
        )
    elif not AI_MODEL:
        errors.append(f"Sin modelo por defecto para '{AI_PROVIDER}'; define AI_MODEL en .env")
    return errors
