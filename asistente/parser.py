import re

SEPARATORS = re.compile(r"[,;\n]+")


def parse_message(text: str) -> tuple[str, list[str]] | None:
    text = text.strip()
    if not text:
        return None

    if ":" in text:
        head, body = text.split(":", 1)
        title = head.strip(" .")
        topics = [t.strip(" .-") for t in SEPARATORS.split(body) if t.strip(" .-")]
        if title and topics:
            return title, topics
        return None

    topics = [t.strip(" .-") for t in SEPARATORS.split(text) if t.strip(" .-")]
    if len(topics) == 1:
        return _title_from_topic(topics[0]), topics
    return "Investigación", topics


def _title_from_topic(topic: str) -> str:
    words = topic.split()
    return " ".join(words[:6])


def slugify(text: str) -> str:
    text = text.lower().strip()
    replacements = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return slug[:60] or "documento"
