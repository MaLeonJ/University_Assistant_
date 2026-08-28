"""Pipeline de investigación: busca y analiza todos los temas en paralelo.

Cada tema corre su secuencia búsqueda → análisis dentro de un thread
(vía asyncio.to_thread) y los temas avanzan simultáneamente con gather.
Ambas etapas consultan antes el cache SQLite: las búsquedas respetan un
TTL y los análisis se reutilizan mientras no cambien fuentes ni modelo
(los aciertos de cache no consumen cuota de IA).
"""

import asyncio
import logging

from . import cache
from .analyzer import analyze_topic, is_fallback
from .config import AI_MODEL, AI_PROVIDER
from .searcher import SearchResult, search_topic

logger = logging.getLogger(__name__)


async def research_topics(
    topics: list[str], max_results: int | None = None, materia: str | None = None
) -> tuple[list[str], dict[str, list[SearchResult]]]:
    """Investiga todos los temas en paralelo.

    Devuelve las secciones redactadas (mismo orden que `topics`) y los
    resultados de búsqueda por tema para la sección de fuentes.
    """
    total = len(topics)
    done = await asyncio.gather(
        *(_research_one(i, total, topic, max_results, materia) for i, topic in enumerate(topics, 1))
    )
    sections = [section for section, _ in done]
    results_by_topic = {topic: results for topic, (_, results) in zip(topics, done, strict=True)}
    return sections, results_by_topic


async def _research_one(
    index: int, total: int, topic: str, max_results: int | None, materia: str | None = None
) -> tuple[str, list[SearchResult]]:
    cached_topic = f"{topic} [{materia}]" if materia else topic
    results = await asyncio.to_thread(cache.get_search, cached_topic)
    origen = "cache"
    if results is None:
        if materia is not None:
            results = await asyncio.to_thread(search_topic, topic, max_results, materia)
        else:
            results = await asyncio.to_thread(search_topic, topic, max_results)
        if results:
            await asyncio.to_thread(cache.put_search, cached_topic, results)
        origen = "web"

    key = cache.analysis_key(cached_topic, results, AI_PROVIDER, AI_MODEL)
    section = await asyncio.to_thread(cache.get_analysis, key)
    if section is None:
        if materia is not None:
            section = await asyncio.to_thread(analyze_topic, topic, results, materia)
        else:
            section = await asyncio.to_thread(analyze_topic, topic, results)
        if results and not is_fallback(section):
            await asyncio.to_thread(cache.put_analysis, key, section)

    logger.info("[%d/%d] %s (%s)", index, total, topic, origen)
    return section, results
