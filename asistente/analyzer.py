import json
import logging

from .llm import generate
from .usage import register_call

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Eres un asistente universitario experto en investigación y didáctica. "
    "Redactas investigaciones académicas claras, extensas y bien organizadas en español, "
    "usando formato Markdown. Nunca inventas datos: te basas en las fuentes proporcionadas."
)

PROMPT = """Investiga y desarrolla el tema: **"{topic}"**

Fuentes obtenidas de la web:

{sources}

Redacta una investigación extensa, estructurada y didáctica sobre el tema, siguiendo este estilo:

1. Empieza con un subtítulo ### "Definición y contexto": qué es el tema, de dónde surge y por qué importa.
2. Continúa con una o varias secciones ### que expliquen los **conceptos clave** en profundidad (usa listas con *cursivas* para la terminología técnica y su término en inglés cuando aplique, ej. *Primary Key*).
3. Incluye una sección ### con **ejemplos concretos** (si el tema es de programación, usa bloques de código; si no, casos reales).
4. Cierra con una sección ### de **aplicaciones e importancia** práctica.
5. Si aporta valor, agrega una tabla Markdown al final resumiendo conceptos/terminología clave (columnas: Término | Descripción).

Requisitos:
- Entre 600 y 1000 palabras, en español.
- Usa **negritas** para términos importantes y tablas Markdown cuando ayuden a organizar información.
- NO incluyas enlaces ni referencias dentro del texto; las fuentes se listan aparte.
- No inventes datos: basa el contenido en las fuentes; si algo no está cubierto, indícalo.

Responde ÚNICAMENTE con el contenido en Markdown."""


def analyze_topic(topic: str, results: list[dict]) -> str:
    if not results:
        return (
            f"_No se encontraron resultados de búsqueda para este tema._"
        )

    sources = "\n".join(
        f"- **{r['title']}** — {r['snippet']} (URL: {r['url']})" for r in results
    )
    try:
        text = generate(
            PROMPT.format(topic=topic, sources=sources), system=SYSTEM_PROMPT
        )
        if not text:
            logger.warning("Respuesta vacía del proveedor de IA para '%s'", topic)
            return _fallback(topic, results)
        register_call()
        return text
    except Exception as e:
        logger.error("Error analizando '%s': %s", topic, e)
        return _fallback(topic, results)


def _fallback(topic: str, results: list[dict]) -> str:
    lines = [
        "_Contenido generado sin IA (cuota agotada o error). "
        "A continuación los resúmenes crudos de las fuentes:_",
        "",
    ]
    for r in results:
        snippet = r["snippet"]
        lines.append(f"- **{r['title']}**: {snippet}")
    return "\n".join(lines)


VISION_PROMPT = """Analiza esta imagen (puede ser un pizarrón, apuntes manuscritos,
diapositivas o un temario). Extrae su contenido académico e identifica:

- Un título breve que resuma el material (máx. 6 palabras).
- La lista de temas, conceptos o puntos que se desarrollan en la imagen.

Responde ÚNICAMENTE con JSON válido, sin markdown ni explicaciones:
{"title": "título breve", "topics": ["tema 1", "tema 2", "..."]}"""


def extract_topics_from_image(image_bytes: bytes, mime: str) -> tuple[str, list[str]] | None:
    try:
        text = generate(VISION_PROMPT, system=SYSTEM_PROMPT, images=[(image_bytes, mime)])
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```")
        data = json.loads(text.strip())
        title = str(data.get("title", "")).strip()
        topics = [str(t).strip() for t in data.get("topics", []) if str(t).strip()]
        if title and topics:
            register_call()
            return title, topics
        return None
    except Exception as e:
        logger.error("Error analizando imagen: %s", e)
        return None
