from datetime import datetime
from pathlib import Path

from .config import OUTPUT_DIR
from .parser import slugify
from .searcher import SearchResult

MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

INDEX_NAME = "00_Índice.md"


def month_dir(dt: datetime, materia: str | None = None) -> Path:
    mat_folder = materia.strip() if (materia and materia.strip()) else "General"
    return OUTPUT_DIR / mat_folder / f"{dt:%Y}" / f"{dt.month:02d}-{MESES[dt.month - 1]}"


def month_label(month_path: Path) -> str:
    nombre = month_path.name.split("-", 1)[1].capitalize()
    year = month_path.parent.name
    materia = month_path.parent.parent.name
    return f"{materia} — {nombre} {year}"


def write_document(
    title: str,
    topics: list[str],
    sections: list[str],
    results_by_topic: dict[str, list[SearchResult]],
    materia: str | None = None,
) -> Path:
    now = datetime.now()
    doc_dir = month_dir(now, materia)
    doc_dir.mkdir(parents=True, exist_ok=True)

    path = doc_dir / f"{now:%d_%H-%M}_{slugify(title)}.md"
    n = 2
    while path.exists():
        path = doc_dir / f"{now:%d_%H-%M}_{slugify(title)}-{n}.md"
        n += 1

    tags = ["universidad", "investigacion"]
    materia_header = ""
    materia_line = ""
    if materia:
        tag_m = slugify(materia)
        if tag_m and tag_m not in tags:
            tags.append(tag_m)
        materia_line = f'materia: "{materia}"\n'
        materia_header = f" — 📖 *{materia}*"

    lines = [
        "---",
        f"tags: [{', '.join(tags)}]",
    ]
    if materia_line:
        lines.append(materia_line.strip())
    lines += [
        f"fecha: {now:%Y-%m-%d}",
        f"hora: {now:%H-%M}",
        "---",
        "",
        f"# {title}",
        "",
        f"Este documento reúne la investigación de **{len(topics)} "
        + ("tema" if len(topics) == 1 else "temas")
        + "**, generada automáticamente a partir de fuentes web.",
        "",
        f"> 📚 *Asistente Universitario*{materia_header} — 🗓️ {now:%d/%m/%Y} · {now:%H:%M}",
        "",
        "## Índice",
        "",
    ]
    lines += [f"{i}. {t}" for i, t in enumerate(topics, 1)]
    lines += ["", "---", ""]

    for i, (topic, section) in enumerate(zip(topics, sections, strict=True), 1):
        lines += [f"## {i}. {topic}", "", section.strip(), "", "---", ""]

    lines += _sources_section(results_by_topic)

    path.write_text("\n".join(lines), encoding="utf-8")
    update_index(doc_dir)
    return path


def update_index(doc_dir: Path) -> Path:
    docs = _docs_in(doc_dir)
    year = doc_dir.parent.name
    materia_nombre = doc_dir.parent.parent.name
    mes_nombre = doc_dir.name.split("-", 1)[1].capitalize()

    entries = [
        f"- {int(p.name[:2]):02d} · {_hora(p)} — [[{p.stem}|{_doc_title(p)}]]"
        for p in reversed(docs)
    ]

    lines = [
        "---",
        "tags: [indice]",
        f"fecha: {datetime.now():%Y-%m-%d}",
        "---",
        "",
        f"# 📚 Índice — {materia_nombre} · {mes_nombre} {year}",
        "",
        f"**Total:** {len(docs)} documento(s)",
        "",
        "```dataview",
        'TABLE hora AS "Hora", fecha AS "Fecha"',
        "FROM #investigacion",
        "WHERE file.folder = this.file.folder",
        "SORT file.name DESC",
        "```",
        "",
    ]
    if entries:
        lines += ["## Documentos", ""]
        lines += entries
    else:
        lines.append("_Aún no hay documentos este mes._")

    index_path = doc_dir / INDEX_NAME
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path


def list_months() -> list[tuple[Path, list[Path]]]:
    months: list[tuple[Path, list[Path]]] = []
    if not OUTPUT_DIR.exists():
        return months
    materia_dirs = sorted(d for d in OUTPUT_DIR.iterdir() if d.is_dir())
    for mat_dir in materia_dirs:
        years = sorted((d for d in mat_dir.iterdir() if d.is_dir()), reverse=True)
        for year_dir in years:
            meses = sorted((d for d in year_dir.iterdir() if d.is_dir()), reverse=True)
            for m in meses:
                docs = _docs_in(m)
                if docs:
                    months.append((m, docs))
    months.sort(key=lambda item: (item[0].parent.name, item[0].name), reverse=True)
    return months


def _docs_in(doc_dir: Path) -> list[Path]:
    if not doc_dir.exists():
        return []
    return sorted(p for p in doc_dir.glob("*.md") if p.name != INDEX_NAME)


def _doc_title(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("# "):
                    return line[2:].strip() or path.stem
    except OSError:
        pass
    return path.stem


def _hora(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("hora:"):
                    h = line.split(":", 1)[1].strip().replace("-", ":")
                    return h
    except OSError:
        pass
    return ""


def _sources_section(results_by_topic: dict[str, list[SearchResult]]) -> list[str]:
    lines = ["## Fuentes consultadas", ""]
    seen: set[str] = set()
    count = 0

    for topic, results in results_by_topic.items():
        topic_sources: list[SearchResult] = []
        for r in results:
            if r.url and r.url not in seen:
                seen.add(r.url)
                topic_sources.append(r)
        if not topic_sources:
            continue
        lines.append(f"**{topic}**")
        lines.append("")
        for r in topic_sources:
            count += 1
            title = r.title.strip() or r.url
            lines.append(f"{count}. [{title}]({r.url})")
        lines.append("")

    if count == 0:
        return []
    return lines
