"""Capa de acceso a proveedores de IA (texto y visión).

Unifica Gemini y APIs OpenAI-compatibles (OpenRouter) detrás de una
única función `generate`, seleccionable mediante AI_PROVIDER en .env.
"""

import base64
import logging

from .config import AI_API_KEY, AI_MODEL, AI_PROVIDER

logger = logging.getLogger(__name__)

OPENAI_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
}

_openai_client = None


def generate(
    prompt: str,
    *,
    system: str,
    images: list[tuple[bytes, str]] | None = None,
) -> str:
    if not AI_API_KEY:
        raise RuntimeError("AI_API_KEY no configurada")

    if AI_PROVIDER == "gemini":
        return _generate_gemini(prompt, system, images)
    if AI_PROVIDER in OPENAI_BASE_URLS:
        return _generate_openai_compatible(prompt, system, images)
    raise ValueError(f"Proveedor de IA no soportado: {AI_PROVIDER}")


def _generate_gemini(
    prompt: str, system: str, images: list[tuple[bytes, str]] | None
) -> str:
    from google import genai
    from google.genai import types

    logging.getLogger("google_genai").setLevel(logging.ERROR)
    client = genai.Client(api_key=AI_API_KEY)
    parts: list = [prompt]
    for data, mime in images or []:
        parts.append(types.Part.from_bytes(data=data, mime_type=mime))
    response = client.models.generate_content(
        model=AI_MODEL,
        contents=parts,
        config={"system_instruction": system},
    )
    return (response.text or "").strip()


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI

        _openai_client = OpenAI(
            api_key=AI_API_KEY, base_url=OPENAI_BASE_URLS[AI_PROVIDER]
        )
    return _openai_client


def _generate_openai_compatible(
    prompt: str, system: str, images: list[tuple[bytes, str]] | None
) -> str:
    if images:
        content: list[dict] = [{"type": "text", "text": prompt}]
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
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
    )
    return (response.choices[0].message.content or "").strip()
