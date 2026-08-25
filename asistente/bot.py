import asyncio
import html
import logging
import re

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

from . import cache, drive, exporter, indexer
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
    "/buscar — buscar en tu biblioteca (full-text)\n"
    "/exportar — descargar un documento como PDF o DOCX\n"
    "/sync — sincronizar a Obsidian local o Google Drive\n"
    "/uso — cuántas llamadas a la IA te quedan hoy\n"
    "/stats — resumen de biblioteca y consumo\n"
    "/logs — ver los últimos errores registrados\n\n"
    "📷 También puedes enviar una *foto* del pizarrón o apuntes: la leeré, "
    "detectaré los temas y *elegirás con botones* cuáles investigar. "
    "Puedes abortar en cualquier momento con /cancel."
)

MENU_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("📚 Documentos", callback_data="docs"),
            InlineKeyboardButton("📊 Uso de IA", callback_data="uso"),
        ],
        [
            InlineKeyboardButton("🔄 Sincronizar", callback_data="sync"),
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


async def _investigar(destino, title: str, topics: list[str]) -> None:
    """Ejecuta la investigación y responde sobre `destino` (mensaje de Telegram)."""
    await destino.reply_text(
        f"🔎 Investigando *{len(topics)} tema(s)* de «{title}»...\n_Esto puede tardar un poco._",
        parse_mode="Markdown",
    )
    await destino.chat.send_action("typing")

    sections, results_by_topic = await research_topics(topics, SEARCH_MAX_RESULTS)
    logger.info("Investigación completa: %s", title)

    path = write_document(title, topics, sections, results_by_topic)

    used, limit = get_usage()
    await destino.reply_text(
        f"✅ Documento listo:\n`{path.name}`\n\n📊 Llamadas a la IA hoy: {used}/{limit}",
        parse_mode="Markdown",
    )
    await show_menu(destino)


async def research(update: Update, title: str, topics: list[str]) -> None:
    assert update.message is not None
    await _investigar(update.message, title, topics)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update) or update.message is None:
        return

    parsed = parse_message(update.message.text or "")
    if parsed is None:
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")
        return

    title, topics = parsed
    await research(update, title, topics)


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
        await _investigar(query.message, title, temas)
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
    app.add_handler(
        CallbackQueryHandler(
            button, pattern=r"^(docs|uso|logs|stats|ayuda|menu|sync(:local|:drive)?)$"
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
