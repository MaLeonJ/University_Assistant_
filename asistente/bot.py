import asyncio
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .analyzer import analyze_topic, extract_topics_from_image
from .config import (
    AUTHORIZED_USER_ID,
    LOG_FILE,
    SEARCH_MAX_RESULTS,
    TELEGRAM_TOKEN,
    validate,
)
from .logsetup import setup_logging
from .parser import parse_message
from .searcher import search_topic
from .syncer import sync_documents, sync_text
from .usage import format_usage, get_usage
from .writer import list_months, month_label, write_document

setup_logging()
logger = logging.getLogger(__name__)

MAX_DOCS_MOSTRADOS = 12
MAX_LOG_BLOCKS = 10
MAX_LOG_CHARS = 3500
LOG_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ ")

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
    "/sync — copiar los documentos a tu Obsidian\n"
    "/uso — cuántas llamadas a la IA te quedan hoy\n"
    "/logs — ver los últimos errores registrados\n\n"
    "📷 También puedes enviar una *foto* del pizarrón o apuntes: la leeré, "
    "detectaré los temas y generaré el documento igual."
)

MENU_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("📚 Documentos", callback_data="docs"),
            InlineKeyboardButton("📊 Uso de IA", callback_data="uso"),
        ],
        [
            InlineKeyboardButton("🔄 Sincronizar", callback_data="sync"),
            InlineKeyboardButton("📋 Registros", callback_data="logs"),
        ],
        [
            InlineKeyboardButton("❓ Ayuda", callback_data="ayuda"),
        ],
    ]
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
    await update.message.chat.send_action("typing")
    await update.message.reply_text(sync_text(sync_documents()), parse_mode="Markdown")


async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    await update.message.reply_text(logs_text(), parse_mode="Markdown")


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
        await query.answer("Sincronizando...")
        await query.edit_message_text(
            sync_text(sync_documents()), reply_markup=MENU_KEYBOARD, parse_mode="Markdown"
        )
    elif query.data == "logs":
        await query.edit_message_text(
            logs_text(), reply_markup=MENU_KEYBOARD, parse_mode="Markdown"
        )
    elif query.data == "ayuda":
        await query.edit_message_text(HELP_TEXT, parse_mode="Markdown")


async def research(update: Update, title: str, topics: list[str]) -> None:
    assert update.message is not None
    await update.message.reply_text(
        f"🔎 Investigando *{len(topics)} tema(s)* de «{title}»...\n_Esto puede tardar un poco._",
        parse_mode="Markdown",
    )

    sections = []
    results_by_topic: dict[str, list[dict]] = {}
    for i, topic in enumerate(topics, 1):
        await update.message.chat.send_action("typing")
        results = search_topic(topic, SEARCH_MAX_RESULTS)
        results_by_topic[topic] = results
        sections.append(analyze_topic(topic, results))
        logger.info("[%d/%d] %s", i, len(topics), topic)

    path = write_document(title, topics, sections, results_by_topic)

    used, limit = get_usage()
    await update.message.reply_text(
        f"✅ Documento listo:\n`{path.name}`\n\n📊 Llamadas a la IA hoy: {used}/{limit}",
        parse_mode="Markdown",
    )
    await show_menu(update.message)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update) or update.message is None:
        return

    parsed = parse_message(update.message.text or "")
    if parsed is None:
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")
        return

    title, topics = parsed
    await research(update, title, topics)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update) or update.message is None:
        return

    caption = (update.message.caption or "").strip()
    if ":" in caption:
        parsed = parse_message(caption)
        if parsed:
            await research(update, *parsed)
            return

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
        return

    title, topics = parsed
    await update.message.reply_text(
        f"📋 Leí la imagen: «{title}»\nTemas detectados: {', '.join(topics)}"
    )
    await research(update, title, topics)


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
    app.add_handler(CommandHandler("logs", logs_command))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_error_handler(on_error)

    logger.info("Bot iniciado")
    app.run_polling()


if __name__ == "__main__":
    main()
