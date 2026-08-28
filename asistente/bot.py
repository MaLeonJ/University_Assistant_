import asyncio
import html
import logging
import re
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from . import cache, drive, exporter, indexer, materias
from .analyzer import extract_topics_from_image
from .config import (
    AUTHORIZED_USER_ID,
    LOG_FILE,
    SEARCH_MAX_RESULTS,
    TELEGRAM_TOKEN,
    validate,
)
from .logsetup import setup_logging
from .parser import parse_message
from .pipeline import research_topics
from .syncer import sync_documents, sync_text
from .usage import format_usage, get_usage
from .usage import total as uso_total
from .writer import list_months, month_label, write_document

setup_logging()
logger = logging.getLogger(__name__)

MAX_DOCS_MOSTRADOS = 12
MAX_LOG_BLOCKS = 10
MAX_LOG_CHARS = 3500
MAX_TEMAS_FOTO = 12
LOG_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ ")

SELECCION = 0

HELP_TEXT = (
    "🤖 *Asistente Universitario*\n\n"
    "Envíame cualquier tema o temario y crearé un documento `.md` con la "
    "investigación.\n\n"
    "*Ejemplos:*\n"
    "• tipos de datos\n"
    "• tipado fuerte vs débil\n"
    "• temario corte 1: bases de datos, modelo E-R, normalización\n\n"
    "*Comandos:*\n"
    "/menu — abrir el menú de opciones\n"
    "/docs — ver documentos generados\n"
    "/materias — gestionar tus asignaturas del trimestre\n"
    "/buscar — buscar en tu biblioteca (full-text)\n"
    "/exportar — descargar un documento como PDF o DOCX\n"
    "/uso — cuántas llamadas a la IA te quedan hoy\n"
    "/stats — resumen de biblioteca y consumo\n"
    "/logs — ver los últimos errores registrados\n\n"
    "🔄 *Sincronización:* Los documentos se sincronizan automáticamente "
    "con Google Drive y tu Obsidian local (Syncthing).\n\n"
    "📷 También puedes enviar una *foto* del pizarrón o apuntes: la leeré, "
    "detectaré los temas y *elegirás con botones* cuáles investigar. "
    "Puedes abortar en cualquier momento con /cancel."
)

MENU_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("📚 Documentos", callback_data="docs"),
            InlineKeyboardButton("📖 Materias", callback_data="materias"),
        ],
        [
            InlineKeyboardButton("📊 Uso de IA", callback_data="uso"),
            InlineKeyboardButton("📈 Estadísticas", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("📋 Registros", callback_data="logs"),
            InlineKeyboardButton("❓ Ayuda", callback_data="ayuda"),
        ],
    ]
)

SYNC_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("💻 Local (Obsidian)", callback_data="sync:local"),
            InlineKeyboardButton("☁️ Google Drive", callback_data="sync:drive"),
        ],
        [InlineKeyboardButton("↩️ Menú", callback_data="menu")],
    ]
)

SYNC_MENU_TEXT = (
    "🔄 *Sincronizar documentos*\n\n"
    "💻 *Local* — copia a tu carpeta Obsidian (`OBSIDIAN_DIR`)\n"
    "☁️ *Drive* — sube a tu carpeta de Google Drive (`GDRIVE_FOLDER_ID`)"
)


def authorized(update: Update) -> bool:
    return update.effective_user is not None and (
        not AUTHORIZED_USER_ID or update.effective_user.id == AUTHORIZED_USER_ID
    )


async def show_menu(target, header: str = "") -> None:
    text = (header + "\n\n" if header else "") + "¿Qué quieres hacer?"
    await target.reply_text(text, reply_markup=MENU_KEYBOARD)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown", reply_markup=MENU_KEYBOARD)


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    await show_menu(update.message)


async def docs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    await update.message.reply_text(docs_text())


async def uso_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    await update.message.reply_text(format_usage(), parse_mode="Markdown")


async def sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    await update.message.reply_text(
        SYNC_MENU_TEXT, parse_mode="Markdown", reply_markup=SYNC_KEYBOARD
    )


async def _sync_local(query) -> None:
    await query.answer("Sincronizando...")
    try:
        resultado = await asyncio.to_thread(sync_documents)
    except OSError as e:
        logger.error("Sync local falló: %s", e)
        await query.edit_message_text(
            f"❌ *No pude sincronizar en local:*\n`{e}`\n\n"
            "Revisa `OBSIDIAN_DIR` en `.env` (¿existe y es escribible?).",
            parse_mode="Markdown",
            reply_markup=MENU_KEYBOARD,
        )
        return
    await query.edit_message_text(
        sync_text(resultado), reply_markup=MENU_KEYBOARD, parse_mode="Markdown"
    )


async def _sync_drive(query) -> None:
    motivo = drive.estado()
    if motivo:
        await query.answer()
        await query.edit_message_text(
            drive.texto_configuracion(motivo),
            parse_mode="Markdown",
            reply_markup=MENU_KEYBOARD,
        )
        return

    await query.answer("Subiendo a Drive...")
    try:
        resultado = await asyncio.to_thread(drive.sync_drive)
    except drive.DriveError as e:
        logger.error("Sync a Drive falló: %s", e)
        await query.edit_message_text(
            f"❌ *Drive falló:*\n`{e}`\n\nSi el token caducó, repite `asistente drive-auth`.",
            parse_mode="Markdown",
            reply_markup=MENU_KEYBOARD,
        )
        return
    await query.edit_message_text(
        drive.sync_text(resultado), reply_markup=MENU_KEYBOARD, parse_mode="Markdown"
    )


async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    await update.message.reply_text(logs_text(), parse_mode="Markdown")


async def buscar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    consulta = " ".join(context.args or []).strip()
    if not consulta:
        await update.message.reply_text(
            "🔎 *Buscar en tu biblioteca*\n\n"
            "Escribe por ejemplo: `/buscar ecuaciones diferenciales`",
            parse_mode="Markdown",
        )
        return

    await update.message.chat.send_action("typing")
    await asyncio.to_thread(indexer.sync_index)
    resultados = await asyncio.to_thread(indexer.search, consulta, 5)

    if not resultados:
        await update.message.reply_text(f"🔎 Sin resultados para «{consulta}».")
        return

    lineas = [f"🔎 <b>{len(resultados)} resultado(s)</b> para «{html.escape(consulta)}»\n"]
    for i, r in enumerate(resultados, 1):
        mes = f" <i>({html.escape(r['month'])})</i>" if r["month"] else ""
        lineas.append(f"{i}. <b>{html.escape(r['title'])}</b>{mes}")
        lineas.append(f"    {html.escape(r['snippet'])}\n")
    await update.message.reply_text("\n".join(lineas), parse_mode="HTML")


async def exportar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    args = [a.lower() for a in (context.args or [])]
    if not args or args[0] not in exporter.FORMATOS:
        formatos = " | ".join(exporter.FORMATOS)
        await update.message.reply_text(
            f"📤 *Exportar documento*\n\n"
            f"Uso: `/exportar {formatos}` (el más reciente)\n"
            f"o `/exportar {formatos} <términos>` (el mejor match)\n\n"
            f"Ejemplo: `/exportar pdf logica proposicional`",
            parse_mode="Markdown",
        )
        return

    formato, termino = args[0], " ".join(args[1:])
    await update.message.chat.send_action("upload_document")
    doc = await asyncio.to_thread(exporter.resolver_documento, termino)
    if doc is None:
        await update.message.reply_text(
            "📭 No encontré ningún documento para exportar."
            + (f" Sin resultados para «{termino}»." if termino else "")
        )
        return

    try:
        salida = await asyncio.to_thread(exporter.exportar, doc, formato)
    except RuntimeError as e:
        mensaje = str(e)
        if "no está instalado" in mensaje:
            mensaje += (
                "\nPara PDF también necesitarás un motor LaTeX:\n"
                "`sudo apt install texlive-latex-recommended texlive-xetex`"
            )
            await update.message.reply_text(f"⚠️ {mensaje}", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ {mensaje}")
        return

    with salida.open("rb") as fh:
        await update.message.reply_document(document=fh, filename=salida.name)


def stats_text() -> str:
    meses = list_months()
    docs = sum(len(d) for _, d in meses)
    kb = sum(p.stat().st_size for _, ds in meses for p in ds) / 1024
    usados_hoy, limite = get_usage()
    semana = uso_total(7)
    busquedas_cache, analisis_cache = cache.stats()

    lineas = ["📊 *Estadísticas*\n"]
    if docs:
        lineas.append(f"📚 *Biblioteca:* {docs} documento(s), {len(meses)} mes(es), {kb:.0f} KB")
    else:
        lineas.append("📚 *Biblioteca:* aún no hay documentos.")
    lineas.append(
        f"🧠 *IA:* hoy {usados_hoy}/{limite} · últimos 7 días {semana} (~{semana / 7:.1f}/día)"
    )
    lineas.append(f"💾 *Cache:* {busquedas_cache} búsqueda(s), {analisis_cache} análisis")
    return "\n".join(lineas)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    await update.message.reply_text(stats_text(), parse_mode="Markdown")


def logs_text() -> str:
    blocks = _recent_error_blocks()
    if not blocks:
        return "📋 *Registros*\n\n✅ Sin errores registrados en el archivo actual."

    lines = [f"📋 *Últimos {len(blocks)} errores* (`bot.log`):\n"]
    for block in reversed(blocks):
        text = "\n".join(block)
        if sum(len(line) + 1 for line in lines) + len(text) > MAX_LOG_CHARS:
            lines.append("_…errores más antiguos omitidos._")
            break
        lines.append(f"```{text}```\n")
    return "\n".join(lines)


def _recent_error_blocks() -> list[list[str]]:
    try:
        with LOG_FILE.open(encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        return []

    blocks: list[list[str]] = []
    for line in content.splitlines():
        if LOG_LINE.match(line):
            if line.split(" ")[2] == "ERROR":
                blocks.append([line])
            elif blocks:
                continue
        elif blocks and len(blocks[-1]) < 40:
            blocks[-1].append(line)

    return [b for b in blocks if b][-MAX_LOG_BLOCKS:]


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Excepción no manejada (update=%s)", update, exc_info=context.error)


def docs_text() -> str:
    months = list_months()
    if not months:
        return "📚 Aún no hay documentos generados."

    total = sum(len(docs) for _, docs in months)
    lines = [f"📚 *{total} documento(s)* por mes:\n"]
    shown = 0
    for mdir, docs in months:
        lines.append(f"📅 *{month_label(mdir)}*")
        for f in reversed(docs):
            if shown >= MAX_DOCS_MOSTRADOS:
                break
            size_kb = f.stat().st_size / 1024
            lines.append(f"• `{f.name}` ({size_kb:.1f} KB)")
            shown += 1
        lines.append("")
        if shown >= MAX_DOCS_MOSTRADOS:
            break

    restantes = total - shown
    if restantes > 0:
        lines.append(f"_…y {restantes} más. Consulta el `00_Índice.md` del mes._")
    return "\n".join(lines)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query is not None and query.data is not None
    await query.answer()

    if query.data == "docs":
        await query.edit_message_text(docs_text(), reply_markup=MENU_KEYBOARD)
    elif query.data == "uso":
        await query.edit_message_text(
            format_usage(), parse_mode="Markdown", reply_markup=MENU_KEYBOARD
        )
    elif query.data == "sync":
        await query.answer()
        await query.edit_message_text(
            SYNC_MENU_TEXT, reply_markup=SYNC_KEYBOARD, parse_mode="Markdown"
        )
    elif query.data == "sync:local":
        await _sync_local(query)
    elif query.data == "sync:drive":
        await _sync_drive(query)
    elif query.data == "menu":
        await query.edit_message_text("¿Qué quieres hacer?", reply_markup=MENU_KEYBOARD)
    elif query.data == "logs":
        await query.edit_message_text(
            logs_text(), reply_markup=MENU_KEYBOARD, parse_mode="Markdown"
        )
    elif query.data == "stats":
        await query.edit_message_text(
            stats_text(), reply_markup=MENU_KEYBOARD, parse_mode="Markdown"
        )
    elif query.data == "ayuda":
        await query.edit_message_text(HELP_TEXT, parse_mode="Markdown")
    elif query.data == "materias":
        text, kb = materias_text()
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    elif query.data == "mat_add":
        user_data = context.user_data
        if user_data is not None:
            user_data["esperando_materia"] = True
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Cancelar", callback_data="materias")]])
        await query.edit_message_text(
            "➕ *Agregar nueva materia*\n\n"
            "Escribe a continuación el nombre de la asignatura que deseas agregar:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
    elif query.data.startswith("mat_del:"):
        nombre = query.data.split(":", 1)[1]
        materias.eliminar_materia(nombre)
        text, kb = materias_text()
        await query.answer("Materia eliminada")
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    elif query.data.startswith("mat_set:"):
        nombre = query.data.split(":", 1)[1]
        materias.set_materia_activa(nombre)
        text, kb = materias_text()
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    elif query.data.startswith("modo:"):
        nuevo_modo = query.data.split(":", 1)[1]
        user_data = context.user_data
        if user_data and "pend_res" in user_data:
            user_data["pend_res"]["modo"] = nuevo_modo
            topics = user_data["pend_res"].get("topics", [])
            inc_modo = len(topics) > 1
            await query.edit_message_reply_markup(
                reply_markup=teclado_selector_materias(modo=nuevo_modo, incluir_modo=inc_modo)
            )
    elif query.data.startswith("mat_sel:"):
        op = query.data.split(":", 1)[1]
        mat: str | None = None
        if op == "activa":
            mat = materias.get_materia_activa()
        elif op != "ninguna":
            try:
                idx = int(op)
                lista = materias.get_materias()
                if 0 <= idx < len(lista):
                    mat = lista[idx]
            except ValueError:
                mat = None

        user_data = context.user_data
        pend = user_data.pop("pend_res", None) if user_data else None
        if pend:
            modo = pend.get("modo", "unificado")
            await query.edit_message_text("👍 Iniciando investigación...")
            assert query.message is not None
            await _investigar(query.message, pend["title"], pend["topics"], materia=mat, modo=modo)
        else:
            await query.edit_message_text("⚠️ La solicitud de investigación expiró.")


def materias_text() -> tuple[str, InlineKeyboardMarkup]:
    lista = materias.get_materias()
    activa = materias.get_materia_activa()
    lines = ["📖 *Materias del Trimestre*\n"]
    filas = []

    if not lista:
        lines.append(
            "Aún no tienes materias configuradas.\n\n"
            "Pulsa *➕ Agregar materia* o usa `/materias agregar <Nombre>`."
        )
    else:
        lines.append(f"📌 Materia activa por defecto: *{activa or 'Ninguna'}*\n")
        lines.append("Toca una materia para activarla por defecto, o 🗑️ para eliminarla:\n")
        for m in lista:
            prefix = "⭐ " if m == activa else "📖 "
            filas.append(
                [
                    InlineKeyboardButton(f"{prefix}{m}", callback_data=f"mat_set:{m}"),
                    InlineKeyboardButton("🗑️", callback_data=f"mat_del:{m}"),
                ]
            )

    filas.append([InlineKeyboardButton("➕ Agregar materia", callback_data="mat_add")])
    filas.append([InlineKeyboardButton("↩️ Menú", callback_data="menu")])
    return "\n".join(lines), InlineKeyboardMarkup(filas)


async def materias_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    args = context.args or []
    if args:
        subcmd = args[0].lower()
        nombre = " ".join(args[1:]).strip()
        if subcmd == "agregar" and nombre:
            if materias.agregar_materia(nombre):
                await update.message.reply_text(f"✅ Materia «{nombre}» agregada.")
            else:
                await update.message.reply_text(f"⚠️ La materia «{nombre}» ya existe o es inválida.")
            return
        elif subcmd == "eliminar" and nombre:
            if materias.eliminar_materia(nombre):
                await update.message.reply_text(f"🗑️ Materia «{nombre}» eliminada.")
            else:
                await update.message.reply_text(f"⚠️ No encontré la materia «{nombre}».")
            return
        elif subcmd == "activar" and nombre:
            if materias.set_materia_activa(nombre):
                await update.message.reply_text(f"📌 Materia activa fijada a: «{nombre}».")
            else:
                await update.message.reply_text(f"⚠️ La materia «{nombre}» no está en tu lista.")
            return

    text, keyboard = materias_text()
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


def teclado_selector_materias(
    modo: str = "unificado", incluir_modo: bool = True
) -> InlineKeyboardMarkup:
    lista = materias.get_materias()
    activa = materias.get_materia_activa()
    filas = []

    if incluir_modo:
        btn_uni = "✅ 📄 Todo en 1 doc" if modo == "unificado" else "📄 Todo en 1 doc"
        btn_sep = "✅ 📚 Docs separados" if modo == "separado" else "📚 Docs separados"
        filas.append(
            [
                InlineKeyboardButton(btn_uni, callback_data="modo:unificado"),
                InlineKeyboardButton(btn_sep, callback_data="modo:separado"),
            ]
        )

    if activa:
        filas.append(
            [InlineKeyboardButton(f"⭐ Usar activa ({activa})", callback_data="mat_sel:activa")]
        )
    for i, m in enumerate(lista):
        if m != activa:
            filas.append([InlineKeyboardButton(f"📖 {m}", callback_data=f"mat_sel:{i}")])
    filas.append([InlineKeyboardButton("🌐 General / Ninguna", callback_data="mat_sel:ninguna")])
    return InlineKeyboardMarkup(filas)


async def _investigar(
    destino,
    title: str,
    topics: list[str],
    materia: str | None = None,
    modo: str = "unificado",
) -> None:
    """Ejecuta la investigación y responde sobre `destino` (mensaje de Telegram)."""
    mat_text = f"\n📖 Asignatura: *{materia}*" if materia else ""
    modo_text = (
        "\n📚 Modo: *Un documento por tema*" if modo == "separado" and len(topics) > 1 else ""
    )
    await destino.reply_text(
        f"🔎 Investigando *{len(topics)} tema(s)* de «{title}»{mat_text}{modo_text}...\n"
        "_Esto puede tardar un poco._",
        parse_mode="Markdown",
    )
    await destino.chat.send_action("typing")

    if materia is not None:
        sections, results_by_topic = await research_topics(
            topics, SEARCH_MAX_RESULTS, materia=materia
        )
    else:
        sections, results_by_topic = await research_topics(topics, SEARCH_MAX_RESULTS)
    logger.info("Investigación completa: %s (Materia: %s, Modo: %s)", title, materia, modo)

    rutas: list[Path] = []
    if modo == "separado" and len(topics) > 1:
        for topic, section in zip(topics, sections, strict=False):
            doc_title = topic.strip().capitalize() if topic.strip() else topic
            p = write_document(
                doc_title,
                [topic],
                [section],
                {topic: results_by_topic.get(topic, [])},
                materia=materia,
            )
            rutas.append(p)
    else:
        p = write_document(title, topics, sections, results_by_topic, materia=materia)
        rutas.append(p)

    drive_status = ""
    if drive.estado() is None:
        try:
            await asyncio.to_thread(drive.sync_drive)
            drive_status = "\n☁️ *Sincronizado a Google Drive*"
        except drive.DriveError as e:
            logger.warning("Auto-sync a Drive falló: %s", e)

    used, limit = get_usage()
    if len(rutas) == 1:
        doc_info = f"✅ Documento listo:\n`{rutas[0].name}`"
    else:
        nombres = "\n".join([f"• `{r.name}`" for r in rutas])
        doc_info = f"✅ *{len(rutas)} documentos creados:*\n{nombres}"

    texto_resumen = f"{doc_info}{drive_status}\n\n📊 Llamadas a la IA hoy: {used}/{limit}"
    await destino.reply_text(texto_resumen, parse_mode="Markdown")
    await show_menu(destino)


async def research(
    update: Update,
    title: str,
    topics: list[str],
    materia: str | None = None,
    modo: str = "unificado",
) -> None:
    assert update.message is not None
    await _investigar(update.message, title, topics, materia=materia, modo=modo)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update) or update.message is None:
        return

    user_data = context.user_data if context is not None else None
    if user_data and user_data.get("esperando_materia"):
        user_data["esperando_materia"] = False
        nombre_materia = (update.message.text or "").strip()
        if nombre_materia:
            if materias.agregar_materia(nombre_materia):
                await update.message.reply_text(f"✅ Materia «{nombre_materia}» agregada.")
            else:
                await update.message.reply_text(
                    f"⚠️ La materia «{nombre_materia}» ya existe o es inválida."
                )
            text, kb = materias_text()
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
            return

    parsed = parse_message(update.message.text or "")
    if parsed is None:
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")
        return

    title, topics = parsed
    lista = materias.get_materias()
    incluir_modo = len(topics) > 1

    if user_data is not None:
        user_data["pend_res"] = {"title": title, "topics": topics, "modo": "unificado"}

    if not lista and not incluir_modo:
        await research(update, title, topics)
        return

    msg_extra = " (elige el modo de entrega y la materia):" if incluir_modo else ":"
    await update.message.reply_text(
        f"📖 *Configuración de Investigación*\n\n«*{title}*» ({len(topics)} tema(s)){msg_extra}",
        parse_mode="Markdown",
        reply_markup=teclado_selector_materias(modo="unificado", incluir_modo=incluir_modo),
    )


def teclado_temas(topics: list[str], sel: set[int]) -> InlineKeyboardMarkup:
    """Teclado multi-selección: un botón por tema + Generar/Cancelar."""
    filas = [
        [InlineKeyboardButton(("✅ " if i in sel else "") + t, callback_data=f"ft:{i}")]
        for i, t in enumerate(topics)
    ]
    filas.append(
        [
            InlineKeyboardButton("✔️ Generar", callback_data="ft:go"),
            InlineKeyboardButton("✖️ Cancelar", callback_data="ft:no"),
        ]
    )
    return InlineKeyboardMarkup(filas)


def texto_seleccion(title: str, topics: list[str], sel: set[int]) -> str:
    n = len(sel)
    total = len(topics)
    resumen = f"{n} de {total}" if n else "ninguno todavía"
    return (
        f"📋 Leí la imagen: «{title}»\n\n"
        f"Temas seleccionados: *{resumen}*.\n"
        f"Toca los temas que quieras incluir y luego pulsa *Generar*."
    )


async def foto_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not authorized(update) or update.message is None:
        return ConversationHandler.END

    caption = (update.message.caption or "").strip()
    if ":" in caption:
        parsed = parse_message(caption)
        if parsed:
            await _investigar(update.message, *parsed)
            return ConversationHandler.END

    await update.message.reply_text("📷 Analizando la imagen...")
    await update.message.chat.send_action("typing")

    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    data = bytes(await tg_file.download_as_bytearray())

    parsed = await asyncio.to_thread(extract_topics_from_image, data, "image/jpeg")
    if parsed is None:
        await update.message.reply_text(
            "❌ No pude leer la imagen. Verifica tu API key o intenta con "
            "una foto más clara del pizarrón/apuntes."
        )
        return ConversationHandler.END

    title, topics = parsed[:2]
    topics = topics[:MAX_TEMAS_FOTO]
    sel: set[int] = set()
    user_data = context.user_data
    assert user_data is not None
    user_data["foto"] = {"title": title, "topics": topics, "sel": sel}
    await update.message.reply_text(
        texto_seleccion(title, topics, sel), reply_markup=teclado_temas(topics, sel)
    )
    return SELECCION


async def foto_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    assert query is not None and query.data is not None
    user_data = context.user_data
    assert user_data is not None
    datos = user_data.get("foto")
    accion = query.data

    if accion == "ft:no":
        user_data.pop("foto", None)
        await query.answer()
        await query.edit_message_text("✖️ Selección cancelada.")
        return ConversationHandler.END

    if datos is None:
        await query.answer("Esta selección expiró; envía la foto otra vez.", show_alert=True)
        return ConversationHandler.END

    if accion == "ft:go":
        if not datos["sel"]:
            await query.answer("Marca al menos un tema primero.", show_alert=True)
            return SELECCION
        title = datos["title"]
        temas = [datos["topics"][i] for i in sorted(datos["sel"])]
        user_data.pop("foto", None)
        await query.answer()
        assert query.message is not None
        lista = materias.get_materias()
        incluir_modo = len(temas) > 1
        if not lista and not incluir_modo:
            await _investigar(query.message, title, temas)
            return ConversationHandler.END

        user_data["pend_res"] = {"title": title, "topics": temas, "modo": "unificado"}
        msg_extra = " (elige el modo de entrega y la materia):" if incluir_modo else ":"
        await query.edit_message_text(
            f"📖 *Configuración de Investigación*\n\n«*{title}*» ({len(temas)} tema(s)){msg_extra}",
            parse_mode="Markdown",
            reply_markup=teclado_selector_materias(modo="unificado", incluir_modo=incluir_modo),
        )
        return ConversationHandler.END

    idx = int(accion.split(":")[1])
    datos["sel"] ^= {idx}
    await query.answer()
    await query.edit_message_text(
        texto_seleccion(datos["title"], datos["topics"], datos["sel"]),
        reply_markup=teclado_temas(datos["topics"], datos["sel"]),
    )
    return SELECCION


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_data = context.user_data
    assert user_data is not None
    user_data.pop("foto", None)
    if update.message is not None:
        await update.message.reply_text("✖️ Cancelado.")
    return ConversationHandler.END


def main() -> None:
    errors = validate()
    if errors:
        raise SystemExit("Configuración incompleta:\n- " + "\n- ".join(errors))
    assert TELEGRAM_TOKEN is not None

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("docs", docs_command))
    app.add_handler(CommandHandler("sync", sync_command))
    app.add_handler(CommandHandler("uso", uso_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("buscar", buscar_command))
    app.add_handler(CommandHandler("exportar", exportar_command))
    app.add_handler(CommandHandler("logs", logs_command))
    app.add_handler(CommandHandler("materias", materias_command))
    app.add_handler(
        CallbackQueryHandler(
            button,
            pattern=r"^(docs|uso|logs|stats|ayuda|menu|sync(:local|:drive)?|materias|mat_add|mat_del:.*|mat_set:.*|mat_sel:.*|modo:.*)$",
        )
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(
        ConversationHandler(
            entry_points=[MessageHandler(filters.PHOTO & ~filters.COMMAND, foto_entry)],
            states={
                SELECCION: [
                    CallbackQueryHandler(foto_toggle, pattern=r"^ft:"),
                    MessageHandler(filters.PHOTO & ~filters.COMMAND, foto_entry),
                ]
            },
            fallbacks=[CommandHandler("cancel", cancelar)],
            allow_reentry=True,
        )
    )
    app.add_error_handler(on_error)

    logger.info("Bot iniciado")
    app.run_polling()


if __name__ == "__main__":
    main()
