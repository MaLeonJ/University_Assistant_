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
from pathlib import Path
from typing import Annotated

import typer

from . import cache, drive, exporter, indexer, materias
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
    materia: Annotated[
        str | None, typer.Option("--materia", "-m", help="Asignatura o materia de estudio")
    ] = None,
    separar: Annotated[
        bool, typer.Option("--separar", "-s", help="Generar un documento por cada tema")
    ] = False,
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
    mat_efectiva = materia or materias.get_materia_activa()
    mat_info = f" [Materia: {mat_efectiva}]" if mat_efectiva else ""
    modo_info = " [Modo: Separados]" if separar and len(topics) > 1 else ""
    typer.echo(f"🔎 Investigando {len(topics)} tema(s) de «{title}»{mat_info}{modo_info}...")
    if mat_efectiva is not None:
        secciones, fuentes = asyncio.run(
            research_topics(topics, SEARCH_MAX_RESULTS, materia=mat_efectiva)
        )
    else:
        secciones, fuentes = asyncio.run(research_topics(topics, SEARCH_MAX_RESULTS))

    rutas: list[Path] = []
    if separar and len(topics) > 1:
        for t, sec in zip(topics, secciones, strict=False):
            doc_title = t.strip().capitalize() if t.strip() else t
            p = write_document(
                doc_title,
                [t],
                [sec],
                {t: fuentes.get(t, [])},
                materia=mat_efectiva,
            )
            rutas.append(p)
    else:
        p = write_document(title, topics, secciones, fuentes, materia=mat_efectiva)
        rutas.append(p)

    if drive.estado() is None:
        try:
            drive.sync_drive()
            typer.secho("☁️ Sincronizado a Google Drive", fg=typer.colors.CYAN)
        except drive.DriveError as e:
            typer.secho(f"⚠️ Auto-sync a Drive falló: {e}", fg=typer.colors.YELLOW)

    usadas, _ = get_usage()
    for r in rutas:
        typer.secho(f"✅ {r}", fg=typer.colors.GREEN)
    typer.echo(f"Llamadas IA hoy: {usadas}")


@app.command(name="materias")
def materias_cli(
    accion: Annotated[
        str | None, typer.Argument(help="listar | agregar | eliminar | activar")
    ] = None,
    nombre: Annotated[str | None, typer.Argument(help="Nombre de la asignatura")] = None,
) -> None:
    """Gestiona las materias del trimestre."""
    if not accion or accion.lower() == "listar":
        lista = materias.get_materias()
        activa = materias.get_materia_activa()
        if not lista:
            typer.echo("No tienes materias configuradas.")
            return
        typer.secho("📖 Materias configuradas:", fg=typer.colors.CYAN, bold=True)
        for m in lista:
            prefix = "⭐ [ACTIVA] " if m == activa else "  "
            typer.echo(f"{prefix}{m}")
        return

    subcmd = accion.lower()
    if not nombre:
        typer.secho("Debes especificar el nombre de la materia.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if subcmd == "agregar":
        if materias.agregar_materia(nombre):
            typer.secho(f"✅ Materia «{nombre}» agregada.", fg=typer.colors.GREEN)
        else:
            typer.secho(f"⚠️ La materia «{nombre}» ya existe o es inválida.", fg=typer.colors.YELLOW)
    elif subcmd == "eliminar":
        if materias.eliminar_materia(nombre):
            typer.secho(f"🗑️ Materia «{nombre}» eliminada.", fg=typer.colors.GREEN)
        else:
            typer.secho(f"⚠️ No existe la materia «{nombre}».", fg=typer.colors.YELLOW)
    elif subcmd == "activar":
        if materias.set_materia_activa(nombre):
            typer.secho(f"📌 Materia activa: «{nombre}».", fg=typer.colors.GREEN)
        else:
            typer.secho(f"⚠️ La materia «{nombre}» no está en tu lista.", fg=typer.colors.YELLOW)
    else:
        typer.secho(
            f"Acción inválida '{accion}'. Opciones: listar, agregar, eliminar, activar.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)


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
