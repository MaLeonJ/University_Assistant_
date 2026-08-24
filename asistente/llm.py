"""Capa de acceso a proveedores de IA (texto y visión).

Unifica Gemini y APIs OpenAI-compatibles (OpenRouter) detrás de una
única función `generate`, seleccionable mediante AI_PROVIDER en .env.

Incluye cadena de fallback por modelos (AI_FALLBACK_MODELS) con circuit
breaker por modelo: tras N fallos consecutivos el modelo se abre y se
omite sin gastar red ni tiempo hasta que pase el enfriamiento.
"""

import base64
import logging
import time
from typing import Any

from .config import AI_API_KEY, AI_FALLBACK_MODELS, AI_MODEL, AI_PROVIDER

logger = logging.getLogger(__name__)

OPENAI_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
}

BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN = 300

_openai_client = None
_breakers: dict[str, "CircuitBreaker"] = {}


class CircuitBreaker:
    """Omite un modelo tras fallos consecutivos; reintenta tras enfriarse."""

    def __init__(self, threshold: int = BREAKER_THRESHOLD, cooldown: float = BREAKER_COOLDOWN):
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.opened_at: float | None = None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        return time.monotonic() - self.opened_at >= self.cooldown

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            if self.opened_at is None:
                logger.warning("Circuit breaker abierto tras %d fallos", self.failures)
            self.opened_at = time.monotonic()


def _breaker_for(model: str) -> CircuitBreaker:
    if model not in _breakers:
        _breakers[model] = CircuitBreaker()
    return _breakers[model]


def reset_breakers() -> None:
    _breakers.clear()


def generate(
    prompt: str,
    *,
    system: str,
    images: list[tuple[bytes, str]] | None = None,
) -> str:
    if not AI_API_KEY:
        raise RuntimeError("AI_API_KEY no configurada")
    if AI_PROVIDER != "gemini" and AI_PROVIDER not in OPENAI_BASE_URLS:
        raise ValueError(f"Proveedor de IA no soportado: {AI_PROVIDER}")

    candidatos = list(dict.fromkeys([AI_MODEL, *AI_FALLBACK_MODELS]))
    last_error: Exception | None = None

    for model in candidatos:
        breaker = _breaker_for(model)
        if not breaker.allow():
            logger.warning("Circuit abierto para '%s'; modelo omitido", model)
            continue
        try:
            texto = _generate_with_model(model, prompt, system, images)
        except Exception as e:
            breaker.record_failure()
            logger.error(
                "Modelo '%s' falló (%d/%d): %s", model, breaker.failures, breaker.threshold, e
            )
            last_error = e
            continue
        breaker.record_success()
        return texto

    raise last_error or RuntimeError("Ningún modelo disponible en la cadena")


def _generate_with_model(
    model: str, prompt: str, system: str, images: list[tuple[bytes, str]] | None
) -> str:
    if AI_PROVIDER == "gemini":
        return _generate_gemini(model, prompt, system, images)
    return _generate_openai_compatible(model, prompt, system, images)


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI

        _openai_client = OpenAI(api_key=AI_API_KEY, base_url=OPENAI_BASE_URLS[AI_PROVIDER])
    return _openai_client


def _generate_gemini(
    model: str, prompt: str, system: str, images: list[tuple[bytes, str]] | None
) -> str:
    from google import genai
    from google.genai import types

    logging.getLogger("google_genai").setLevel(logging.ERROR)
    client = genai.Client(api_key=AI_API_KEY)
    parts: list = [prompt]
    for data, mime in images or []:
        parts.append(types.Part.from_bytes(data=data, mime_type=mime))
    response = client.models.generate_content(
        model=model,
        contents=parts,
        config={"system_instruction": system},
    )
    return (response.text or "").strip()


def _generate_openai_compatible(
    model: str, prompt: str, system: str, images: list[tuple[bytes, str]] | None
) -> str:
    content: str | list[dict[str, Any]]
    if images:
        content = [{"type": "text", "text": prompt}]
        for data, mime in images:
            b64 = base64.b64encode(data).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                }
            )
    else:
        content = prompt

    response = _get_openai_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        extra_body={"reasoning": {"enabled": False}},
    )
    return (response.choices[0].message.content or "").strip()
