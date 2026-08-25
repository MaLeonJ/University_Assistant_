"""CLI del Asistente Universitario: el mismo pipeline, sin Telegram.

Comandos:
- investigar: genera un documento a partir de un temario o tema
- buscar: búsqueda full-text sobre la biblioteca generada
- exportar: convierte un documento a PDF o DOCX con pandoc
- uso / stats: consumo de IA y resumen general

Instalación del comando global (tras editar pyproject):
    pip install -e .
"""

import asyncio
from typing import Annotated

import typer

from . import cache, exporter, indexer
from .config import SEARCH_MAX_RESULTS, validate
from .parser import parse_message
from .pipeline import research_topics
from .usage import format_usage, get_usage
from .usage import total as uso_total
from .writer import list_months, write_document

app = typer.Typer(
    help="Asistente Universitario: investiga temarios y gestiona tu biblioteca de apuntes.",
    no_args_is_help=True,
    add_completion=False,
)


def _plano(texto: str) -> str:
    """Quita el marcado Markdown que solo tiene sentido en Telegram."""
    for token in ("**", "*", "`"):
        texto = texto.replace(token, "")
    return texto


@app.command()
def investigar(
    temario: Annotated[str, typer.Argument(help="Tema o 'título: tema1, tema2'")],
) -> None:
    """Investiga en la web y genera un documento Markdown."""
    errores = validate()
    if errores:
        typer.secho("Configuración incompleta:", fg=typer.colors.RED)
        for e in errores:
            typer.echo(f"- {e}")
        raise typer.Exit(code=1)

    parsed = parse_message(temario)
    if parsed is None:
        typer.secho(f"No pude interpretar «{temario}».", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    title, topics = parsed
    typer.echo(f"🔎 Investigando {len(topics)} tema(s) de «{title}»...")
    secciones, fuentes = asyncio.run(research_topics(topics, SEARCH_MAX_RESULTS))
    path = write_document(title, topics, secciones, fuentes)

    usadas, _ = get_usage()
    typer.secho(f"✅ {path}", fg=typer.colors.GREEN)
    typer.echo(f"Llamadas IA hoy: {usadas}")


@app.command()
def buscar(
    consulta: Annotated[list[str], typer.Argument(help="Términos de búsqueda")],
    limite: Annotated[int, typer.Option("--limite", "-l", min=1, max=50)] = 10,
) -> None:
    """Busca full-text en los documentos generados."""
    indexer.sync_index()
    resultados = indexer.search(" ".join(consulta), limite)
    if not resultados:
        typer.echo("Sin resultados.")
        raise typer.Exit(code=1)
    for r in resultados:
        mes = f" ({r['month']})" if r["month"] else ""
        typer.secho(r["title"] + mes, fg=typer.colors.CYAN, bold=True)
        typer.echo(f"  {r['path']}")
        snippet = r["snippet"].replace("\n", " ").strip()
        typer.echo(f"  {snippet}\n")


@app.command()
def exportar(
    formato: Annotated[str, typer.Argument(help="pdf | docx")],
    termino: Annotated[str | None, typer.Argument()] = None,
) -> None:
    """Exporta el documento más reciente (o el mejor match) a PDF/DOCX."""
    if formato.lower() not in exporter.FORMATOS:
        typer.secho(
            f"Formato inválido. Opciones: {', '.join(exporter.FORMATOS)}", fg=typer.colors.RED
        )
        raise typer.Exit(code=1)
    doc = exporter.resolver_documento(termino or "")
    if doc is None:
        typer.echo("No hay ningún documento que coincida.")
        raise typer.Exit(code=1)
    try:
        salida = exporter.exportar(doc, formato.lower())
    except RuntimeError as e:
        typer.secho(str(e), fg=typer.colors.RED)
        raise typer.Exit(code=1) from e
    typer.secho(f"✅ {salida}", fg=typer.colors.GREEN)


@app.command()
def uso() -> None:
    """Muestra la cuota diaria de llamadas a la IA."""
    typer.echo(_plano(format_usage()))


@app.command()
def stats() -> None:
    """Resumen de biblioteca, consumo y cache."""
    meses = list_months()
    docs = sum(len(d) for _, d in meses)
    usadas, limite = get_usage()
    busquedas, analisis = cache.stats()
    typer.echo(f"Biblioteca: {docs} documento(s) en {len(meses)} mes(es)")
    typer.echo(f"IA hoy: {usadas}/{limite} · últimos 7 días: {uso_total(7)}")
    typer.echo(f"Cache: {busquedas} búsqueda(s), {analisis} análisis")


@app.command(name="drive-auth")
def drive_auth() -> None:
    """Autoriza Google Drive en tu navegador y genera data/token.json."""
    from . import drive

    try:
        ruta = drive.login_interactivo()
    except drive.DriveError as e:
        typer.secho(str(e), fg=typer.colors.RED)
        raise typer.Exit(code=1) from e
    typer.secho(f"✅ Token guardado en {ruta}", fg=typer.colors.GREEN)
    typer.echo(
        "Copia ese archivo al servidor (junto a credentials.json) "
        "y define GDRIVE_FOLDER_ID en .env."
    )


if __name__ == "__main__":
    app()
