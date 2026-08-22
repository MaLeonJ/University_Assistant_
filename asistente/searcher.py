import logging
import time

from ddgs import DDGS

from .config import SEARCH_MAX_RESULTS

logger = logging.getLogger(__name__)

RETRIES = 3


def search_topic(topic: str, max_results: int | None = None) -> list[dict]:
    max_results = max_results or SEARCH_MAX_RESULTS
    results = []
    last_error = None

    for attempt in range(1, RETRIES + 1):
        try:
            with DDGS() as ddgs:
                raw = ddgs.text(f"{topic} explicación", max_results=max_results)
                for r in raw:
                    results.append(
                        {
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", ""),
                        }
                    )
            if results:
                return results
        except Exception as e:
            last_error = e
            logger.warning("Intento %d/%d falló para '%s': %s", attempt, RETRIES, topic, e)
            time.sleep(2 * attempt)

    if last_error:
        logger.error("Búsqueda fallida para '%s' tras %d intentos", topic, RETRIES)
    return results
