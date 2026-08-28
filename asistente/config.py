import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def resolver_ruta(nombre_env: str, default: Path) -> Path:
    """Resuelve una ruta del .env: absoluta tal cual, relativa contra BASE_DIR."""
    valor = os.getenv(nombre_env)
    if not valor:
        return default
    ruta = Path(valor).expanduser()
    return ruta if ruta.is_absolute() else (BASE_DIR / ruta).resolve()


DATA_DIR = resolver_ruta("DATA_DIR", BASE_DIR / "data")
USAGE_FILE = DATA_DIR / "usage.json"
MATERIAS_FILE = DATA_DIR / "materias.json"
CACHE_DB = DATA_DIR / "cache.db"
CACHE_TTL_DAYS = int(os.getenv("CACHE_TTL_DAYS", "7"))
INDEX_DB = DATA_DIR / "search.db"

LOG_DIR = resolver_ruta("LOG_DIR", BASE_DIR / "logs")
LOG_FILE = LOG_DIR / "bot.log"

OUTPUT_DIR = resolver_ruta("OUTPUT_DIR", BASE_DIR / "documentos")
OBSIDIAN_DIR = resolver_ruta(
    "OBSIDIAN_DIR",
    Path.home() / "GoogleDrive/Obsidian/Notebook/Universidad",
)

GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "")
GDRIVE_CREDENTIALS_FILE = resolver_ruta("GDRIVE_CREDENTIALS_FILE", BASE_DIR / "credentials.json")
GDRIVE_TOKEN_FILE = resolver_ruta("GDRIVE_TOKEN_FILE", DATA_DIR / "token.json")

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
