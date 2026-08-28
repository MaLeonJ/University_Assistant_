import asyncio
import logging
import types
from pathlib import Path
from typing import Any

import pytest

import asistente.bot as bot
from asistente.searcher import SearchResult


def ctx_args(args):
    return types.SimpleNamespace(args=args)


class FakeChat:
    def __init__(self):
        self.actions = []

    async def send_action(self, action):
        self.actions.append(action)


class FakeMessage:
    def __init__(self, text="", caption=""):
        self.text = text
        self.caption = caption
        self.chat = FakeChat()
        self.reply_texts = []
        self.photo = []
        self.documents = []

    async def reply_text(self, text, **kwargs):
        self.reply_texts.append(text)

    async def reply_document(self, document=None, filename=None, **kwargs):
        self.documents.append((document, filename))


class FakeQuery:
    message: Any = None

    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []
        self.message = FakeMessage()

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(text)

    async def edit_message_reply_markup(self, reply_markup=None, **kwargs):
        self.edits.append("reply_markup_updated")


def fake_update(message=None, query=None, user_id=1) -> Any:
    return types.SimpleNamespace(
        message=message,
        callback_query=query,
        effective_user=types.SimpleNamespace(id=user_id),
    )


CTX: Any = None


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def pipeline_rapido(monkeypatch, output_dirs):
    """Desconecta la investigación real y neutraliza la restricción de usuario."""
    resultados = [SearchResult(title="Fuente", url="https://x.com", snippet="s")]

    async def fake_research(topics, max_results=None):
        return ["SECCIÓN" for _ in topics], dict.fromkeys(topics, resultados)

    monkeypatch.setattr(bot, "research_topics", fake_research)
    monkeypatch.setattr(bot, "AUTHORIZED_USER_ID", 0)


# ---------- autorización ----------


def test_usuario_autorizado_pasa(monkeypatch):
    monkeypatch.setattr(bot, "AUTHORIZED_USER_ID", 42)
    assert bot.authorized(fake_update(user_id=42))


def test_usuario_distinto_bloqueado(monkeypatch):
    monkeypatch.setattr(bot, "AUTHORIZED_USER_ID", 42)
    assert not bot.authorized(fake_update(user_id=7))


def test_sin_restriccion_acepta_a_cualquiera(monkeypatch):
    monkeypatch.setattr(bot, "AUTHORIZED_USER_ID", 0)
    assert bot.authorized(fake_update(user_id=999))


def test_sin_usuario_no_explota():
    update: Any = types.SimpleNamespace(effective_user=None)
    assert not bot.authorized(update)


# ---------- comandos simples ----------


def test_start_responde_ayuda():
    msg = FakeMessage()
    run(bot.start(fake_update(message=msg), CTX))
    assert "Asistente Universitario" in msg.reply_texts[0]


def test_menu_y_comandos_responden_algo():
    for coro_factory in (
        lambda m: bot.menu(fake_update(message=m), CTX),
        lambda m: bot.docs_command(fake_update(message=m), CTX),
        lambda m: bot.uso_command(fake_update(message=m), CTX),
        lambda m: bot.logs_command(fake_update(message=m), CTX),
    ):
        msg = FakeMessage()
        run(coro_factory(msg))
        assert msg.reply_texts


def test_sync_command_muestra_submenu(biblioteca_tmp):
    msg = FakeMessage()
    run(bot.sync_command(fake_update(message=msg), CTX))
    assert any("Sincronizar documentos" in t for t in msg.reply_texts)


# ---------- /buscar ----------


def test_buscar_sin_args_muestra_uso():
    msg = FakeMessage()
    run(bot.buscar_command(fake_update(message=msg), ctx_args([])))
    assert "Buscar" in msg.reply_texts[0]


def test_buscar_encuentra_en_la_biblioteca(biblioteca_tmp, output_dirs, tmp_path, monkeypatch):
    import asistente.indexer as indexer

    monkeypatch.setattr(indexer, "INDEX_DB", str(tmp_path / "s.db"))
    monkeypatch.setattr(indexer, "OUTPUT_DIR", output_dirs["out"])
    msg = FakeMessage()
    run(bot.buscar_command(fake_update(message=msg), ctx_args(["hola"])))
    assert "1 resultado(s)" in msg.reply_texts[0]
    assert "<b>x</b>" in msg.reply_texts[0]


def test_buscar_sin_resultados_avisa(biblioteca_tmp, output_dirs, tmp_path, monkeypatch):
    import asistente.indexer as indexer

    monkeypatch.setattr(indexer, "INDEX_DB", str(tmp_path / "s.db"))
    monkeypatch.setattr(indexer, "OUTPUT_DIR", output_dirs["out"])
    msg = FakeMessage()
    run(bot.buscar_command(fake_update(message=msg), ctx_args(["zzz-inexistente"])))
    assert "Sin resultados" in msg.reply_texts[0]


# ---------- /exportar ----------


def test_exportar_formato_invalido_muestra_uso():
    msg = FakeMessage()
    run(bot.exportar_command(fake_update(message=msg), ctx_args(["xlsx"])))
    assert "Exportar" in msg.reply_texts[0]


def test_exportar_sin_pandoc_avisa_como_instalar(biblioteca_tmp, output_dirs, monkeypatch):
    import asistente.exporter as exporter

    monkeypatch.setattr(exporter, "pandoc_disponible", lambda: False)
    msg = FakeMessage()
    run(bot.exportar_command(fake_update(message=msg), ctx_args(["docx"])))
    assert "pandoc" in msg.reply_texts[0]


def test_exportar_envia_el_archivo(biblioteca_tmp, output_dirs, monkeypatch):
    import asistente.exporter as exporter

    llamados = {}

    def fake_run(cmd, **kwargs):
        llamados["cmd"] = cmd
        salida = Path(cmd[cmd.index("-o") + 1])
        salida.write_bytes(b"%PDF-falso")
        return types.SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(exporter, "pandoc_disponible", lambda: True)
    monkeypatch.setattr(exporter.subprocess, "run", fake_run)
    msg = FakeMessage()
    run(bot.exportar_command(fake_update(message=msg), ctx_args(["pdf"])))

    assert llamados["cmd"][0] == "pandoc"
    assert msg.documents and msg.documents[0][1].endswith(".pdf")


def test_exportar_pandoc_falla_reporta_error(biblioteca_tmp, output_dirs, monkeypatch):
    import asistente.exporter as exporter

    def fake_run(cmd, **kwargs):
        return types.SimpleNamespace(returncode=1, stderr="linea1\nLaTeX error final")

    monkeypatch.setattr(exporter, "pandoc_disponible", lambda: True)
    monkeypatch.setattr(exporter.subprocess, "run", fake_run)
    msg = FakeMessage()
    run(bot.exportar_command(fake_update(message=msg), ctx_args(["pdf"])))
    assert "LaTeX error final" in msg.reply_texts[0]


# ---------- /stats ----------


def test_stats_text_y_comando(output_dirs, usage_file):
    texto = bot.stats_text()
    assert "Biblioteca" in texto
    assert "IA" in texto
    assert "Cache" in texto

    msg = FakeMessage()
    run(bot.stats_command(fake_update(message=msg), CTX))
    assert msg.reply_texts == [texto]


@pytest.fixture
def biblioteca_tmp(output_dirs):
    origen = output_dirs["out"] / "General" / "2026" / "08-agosto"
    origen.mkdir(parents=True)
    (origen / "x.md").write_text("hola")
    return origen


# ---------- menú de botones ----------


@pytest.mark.parametrize(
    "data,esperado",
    [
        ("docs", "documento"),
        ("uso", "Uso de la IA"),
        ("logs", "errores"),
        ("stats", "Estadísticas"),
        ("ayuda", "Asistente Universitario"),
    ],
)
def test_button_rutas_principales(data, esperado):
    query = FakeQuery(data)
    run(bot.button(fake_update(query=query), CTX))
    assert any(esperado in e for e in query.edits)


def test_button_sync_muestra_submenu(biblioteca_tmp):
    query = FakeQuery("sync")
    run(bot.button(fake_update(query=query), CTX))
    assert any("Sincronizar documentos" in e for e in query.edits)


def test_button_sync_local_sincroniza(biblioteca_tmp):
    query = FakeQuery("sync:local")
    run(bot.button(fake_update(query=query), CTX))
    assert any("Sincronización completada" in e for e in query.edits)


def test_button_sync_drive_sin_configurar_avisa_pasos(monkeypatch):
    import asistente.drive as drive

    monkeypatch.setattr(drive, "GDRIVE_FOLDER_ID", "")
    query = FakeQuery("sync:drive")
    run(bot.button(fake_update(query=query), CTX))
    assert any("no está configurado" in e for e in query.edits)
    assert any("GDRIVE_FOLDER_ID" in e for e in query.edits)


def test_button_sync_drive_configurado_sube(monkeypatch):
    import asistente.drive as drive

    monkeypatch.setattr(drive, "estado", lambda: None)
    monkeypatch.setattr(
        drive,
        "sync_drive",
        lambda: {"nuevos": 1, "actualizados": 0, "total": 1},
    )
    query = FakeQuery("sync:drive")
    run(bot.button(fake_update(query=query), CTX))
    assert any("Drive completada" in e for e in query.edits)


def test_button_sync_drive_fallo_api_no_crashea(monkeypatch):
    import asistente.drive as drive

    def explotar():
        raise drive.DriveError("API de Drive falló subiendo a.md: quota")

    monkeypatch.setattr(drive, "estado", lambda: None)
    monkeypatch.setattr(drive, "sync_drive", explotar)
    query = FakeQuery("sync:drive")
    run(bot.button(fake_update(query=query), CTX))
    assert any("Drive falló" in e for e in query.edits)


def test_button_menu_vuelve_al_menu():
    query = FakeQuery("menu")
    run(bot.button(fake_update(query=query), CTX))
    assert any("¿Qué quieres hacer?" in e for e in query.edits)


def test_button_mat_add_y_mat_del(tmp_path, monkeypatch):
    import asistente.materias as materias

    monkeypatch.setattr(materias, "MATERIAS_FILE", tmp_path / "materias.json")
    materias.agregar_materia("Física I")

    # mat_add
    ctx = ctx_foto()
    query = FakeQuery("mat_add")
    run(bot.button(fake_update(query=query), ctx))
    assert ctx.user_data.get("esperando_materia") is True
    assert any("Agregar nueva materia" in e for e in query.edits)

    # handle_message estando esperando_materia
    msg = FakeMessage(text="Química General")
    run(bot.handle_message(fake_update(message=msg), ctx))
    assert ctx.user_data.get("esperando_materia") is False
    assert "Química General" in materias.get_materias()

    # mat_del
    query_del = FakeQuery("mat_del:Química General")
    run(bot.button(fake_update(query=query_del), ctx))
    assert "Química General" not in materias.get_materias()


def test_button_modo_y_ejecucion_separada(usage_file):
    ctx = ctx_foto()
    ctx.user_data["pend_res"] = {
        "title": "Unidad 1",
        "topics": ["tema 1", "tema 2"],
        "modo": "unificado",
    }

    # Cambiar modo a separado
    query_modo = FakeQuery("modo:separado")
    run(bot.button(fake_update(query=query_modo), ctx))
    assert ctx.user_data["pend_res"]["modo"] == "separado"

    # Confirmar con mat_sel:ninguna
    query_sel = FakeQuery("mat_sel:ninguna")
    run(bot.button(fake_update(query=query_sel), ctx))
    assert any("2 documentos creados" in t for t in query_sel.message.reply_texts)


# ---------- mensajes de texto ----------


def test_mensaje_no_autorizado_se_ignora(monkeypatch):
    monkeypatch.setattr(bot, "AUTHORIZED_USER_ID", 42)
    msg = FakeMessage(text="temas varios")
    run(bot.handle_message(fake_update(message=msg, user_id=1), CTX))
    assert not msg.reply_texts


def test_mensaje_invalido_recibe_ayuda():
    msg = FakeMessage(text="")
    run(bot.handle_message(fake_update(message=msg), CTX))
    assert "Asistente Universitario" in msg.reply_texts[0]


def test_investigacion_completa(usage_file):
    msg = FakeMessage(text="tipos de datos")
    run(bot.handle_message(fake_update(message=msg), CTX))
    assert any("Investigando" in t for t in msg.reply_texts)
    assert any("Documento listo" in t for t in msg.reply_texts)
    creados = list(output_docs())
    assert len(creados) == 2


def test_investigacion_auto_sync_drive_exitoso(usage_file, monkeypatch):
    import asistente.drive as drive

    sincronizado = []

    def fake_sync():
        sincronizado.append(True)
        return {"nuevos": 1, "actualizados": 0, "total": 1}

    monkeypatch.setattr(drive, "estado", lambda: None)
    monkeypatch.setattr(drive, "sync_drive", fake_sync)

    msg = FakeMessage(text="tipos de datos")
    run(bot.handle_message(fake_update(message=msg), CTX))
    assert sincronizado == [True]
    assert any("Sincronizado a Google Drive" in t for t in msg.reply_texts)


def test_investigacion_auto_sync_drive_falla_no_rompe(usage_file, monkeypatch):
    import asistente.drive as drive

    def explotar():
        raise drive.DriveError("Fallo de red")

    monkeypatch.setattr(drive, "estado", lambda: None)
    monkeypatch.setattr(drive, "sync_drive", explotar)

    msg = FakeMessage(text="tipos de datos")
    run(bot.handle_message(fake_update(message=msg), CTX))
    assert any("Documento listo" in t for t in msg.reply_texts)


def output_docs():
    import asistente.writer as writer

    return list(writer.OUTPUT_DIR.rglob("*.md"))


def test_research_genera_un_documento_con_todos_los_temas(usage_file):
    msg = FakeMessage()
    run(bot.research(fake_update(message=msg), "Corte", ["tema a", "tema b"]))
    docs = [p for p in output_docs() if p.name != "00_Índice.md"]
    assert len(docs) == 1
    contenido = docs[0].read_text(encoding="utf-8")
    assert "## 1. tema a" in contenido
    assert "## 2. tema b" in contenido
    assert any("Documento listo" in t for t in msg.reply_texts)


# ---------- fotos: conversación de selección ----------


def mensaje_con_foto(caption="", bytes_imagen=b"img"):
    msg = FakeMessage(caption=caption)

    async def get_file():
        async def download():
            return bytearray(bytes_imagen)

        return types.SimpleNamespace(download_as_bytearray=download)

    msg.photo = [types.SimpleNamespace(get_file=get_file)]
    return msg


def ctx_foto():
    return types.SimpleNamespace(user_data={})


def fake_query_ft(data, texto="mensaje"):
    query = FakeQuery(data)
    query.message = FakeMessage(texto)
    return query


def test_teclado_y_texto_de_seleccion():
    teclado = bot.teclado_temas(["a", "b"], {1})
    etiquetas = [b.text for fila in teclado.inline_keyboard for b in fila]
    assert etiquetas == ["a", "✅ b", "✔️ Generar", "✖️ Cancelar"]
    assert "1 de 2" in bot.texto_seleccion("T", ["a", "b"], {1})
    assert "ninguno todavía" in bot.texto_seleccion("T", ["a", "b"], set())


def test_foto_con_caption_parseable_evita_vision(monkeypatch):
    llamado = []
    monkeypatch.setattr(
        bot,
        "extract_topics_from_image",
        lambda *a: llamado.append(a),
    )
    msg = mensaje_con_foto(caption="corte 3: sql, joins")
    estado = run(bot.foto_entry(fake_update(message=msg), ctx_foto()))
    assert estado == bot.ConversationHandler.END
    assert not llamado
    assert any("Documento listo" in t for t in msg.reply_texts)


def test_foto_sin_caption_muestra_seleccion(monkeypatch):
    monkeypatch.setattr(
        bot, "extract_topics_from_image", lambda *a: ("Pizarrón", ["tema 1", "tema 2"])
    )
    msg = mensaje_con_foto()
    ctx = ctx_foto()
    estado = run(bot.foto_entry(fake_update(message=msg), ctx))
    assert estado == bot.SELECCION
    assert ctx.user_data["foto"]["title"] == "Pizarrón"
    assert any("seleccionados" in t.lower() for t in msg.reply_texts)


def test_foto_ilegible_avisa_al_usuario(monkeypatch):
    monkeypatch.setattr(bot, "extract_topics_from_image", lambda *a: None)
    msg = mensaje_con_foto()
    estado = run(bot.foto_entry(fake_update(message=msg), ctx_foto()))
    assert estado == bot.ConversationHandler.END
    assert any("No pude leer" in t for t in msg.reply_texts)


def test_toggle_marca_y_desmarca():
    ctx = ctx_foto()
    ctx.user_data["foto"] = {"title": "T", "topics": ["a", "b"], "sel": set()}

    q = fake_query_ft("ft:0")
    estado = run(bot.foto_toggle(fake_update(query=q), ctx))
    assert estado == bot.SELECCION
    assert ctx.user_data["foto"]["sel"] == {0}
    assert "1 de 2" in q.edits[-1]

    run(bot.foto_toggle(fake_update(query=q), ctx))
    assert ctx.user_data["foto"]["sel"] == set()


def test_generar_sin_seleccion_avisa():
    ctx = ctx_foto()
    ctx.user_data["foto"] = {"title": "T", "topics": ["a"], "sel": set()}
    q = fake_query_ft("ft:go")

    estado = run(bot.foto_toggle(fake_update(query=q), ctx))

    assert estado == bot.SELECCION
    assert any("al menos un tema" in a for a in q.answers if a)


def test_generar_con_seleccion_investiga_solo_lo_elegido(monkeypatch):
    ctx = ctx_foto()
    ctx.user_data["foto"] = {
        "title": "T",
        "topics": ["a", "b", "c"],
        "sel": {0},
    }
    investigados = []

    async def fake_investigar(destino, title, topics):
        investigados.append((title, topics))

    monkeypatch.setattr(bot, "_investigar", fake_investigar)
    q = fake_query_ft("ft:go")

    estado = run(bot.foto_toggle(fake_update(query=q), ctx))

    assert estado == bot.ConversationHandler.END
    assert investigados == [("T", ["a"])]
    assert "foto" not in ctx.user_data


def test_generar_con_seleccion_multiples_temas_muestra_configuracion():
    ctx = ctx_foto()
    ctx.user_data["foto"] = {
        "title": "T",
        "topics": ["a", "b", "c"],
        "sel": {0, 2},
    }
    q = fake_query_ft("ft:go")

    estado = run(bot.foto_toggle(fake_update(query=q), ctx))

    assert estado == bot.ConversationHandler.END
    assert ctx.user_data["pend_res"]["topics"] == ["a", "c"]
    assert any("Configuración de Investigación" in e for e in q.edits)


def test_cancelar_por_boton():
    ctx = ctx_foto()
    ctx.user_data["foto"] = {"title": "T", "topics": ["a"], "sel": {0}}
    q = fake_query_ft("ft:no")

    estado = run(bot.foto_toggle(fake_update(query=q), ctx))

    assert estado == bot.ConversationHandler.END
    assert "cancelada" in q.edits[-1]
    assert "foto" not in ctx.user_data


def test_cancel_command_limpia_estado():
    ctx = ctx_foto()
    ctx.user_data["foto"] = {"title": "T", "topics": [], "sel": set()}
    msg = FakeMessage()

    estado = run(bot.cancelar(fake_update(message=msg), ctx))

    assert estado == bot.ConversationHandler.END
    assert "Cancelado" in msg.reply_texts[0]
    assert "foto" not in ctx.user_data


def test_boton_con_estado_expirado_avisa():
    q = fake_query_ft("ft:0")
    estado = run(bot.foto_toggle(fake_update(query=q), ctx_foto()))
    assert estado == bot.ConversationHandler.END
    assert any("expiró" in (a or "") for a in q.answers)


# ---------- registros ----------


def test_logs_sin_archivo(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "LOG_FILE", tmp_path / "no-existe.log")
    assert "Sin errores registrados" in bot.logs_text()


def test_logs_extrae_solo_errores(tmp_path, monkeypatch):
    log = tmp_path / "bot.log"
    log.write_text(
        "2026-08-23 10:00:00,000 INFO asistente.bot: Bot iniciado\n"
        "2026-08-23 10:01:00,000 ERROR asistente.bot: explotó\n"
        "Traceback (most recent call last):\n"
        "ValueError: boom\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "LOG_FILE", log)
    texto = bot.logs_text()
    assert "explotó" in texto
    assert "ValueError" in texto
    assert "INFO" not in texto.split("```")[1].splitlines()[0]


def test_on_error_registra_sin_notificar(caplog):
    ctx: Any = types.SimpleNamespace(error=ValueError("boom"))
    with caplog.at_level(logging.ERROR, logger="asistente.bot"):
        run(bot.on_error(None, ctx))
    assert any("boom" in str(r.exc_info[1]) for r in caplog.records if r.exc_info)


# ---------- arranque ----------


def test_main_sin_config_aborta(monkeypatch):
    monkeypatch.setattr(bot, "validate", lambda: ["Falta algo"])
    with pytest.raises(SystemExit):
        bot.main()


def test_main_registra_handlers_y_arranca(monkeypatch):
    registrados = []
    errores = []
    estado = {"polling": False}

    class FakeApp:
        def token(self, t):
            assert t
            return self

        def build(self):
            return self

        def add_handler(self, handler):
            registrados.append(handler)

        def add_error_handler(self, handler):
            errores.append(handler)

        def run_polling(self):
            estado["polling"] = True

    monkeypatch.setattr(bot, "validate", lambda: [])
    monkeypatch.setattr(bot, "TELEGRAM_TOKEN", "tok")
    monkeypatch.setattr(bot, "Application", types.SimpleNamespace(builder=FakeApp))

    bot.main()

    assert len(registrados) == 14
    assert len(errores) == 1
    assert estado["polling"]


def test_docs_text_lista_y_trunca_a_doce(biblioteca_tmp):
    mes = biblioteca_tmp
    for i in range(13):
        (mes / f"{i:02d}_10-00-tema-{i}.md").write_text(f"# Tema {i}\n", encoding="utf-8")

    texto = bot.docs_text()
    assert "14 documento(s)" in texto
    assert "Agosto" in texto
    assert "…y 2 más" in texto


def test_setup_logging_adjunta_handler_rotativo(tmp_path, monkeypatch):
    from logging.handlers import RotatingFileHandler

    from asistente import logsetup

    monkeypatch.setattr(logsetup, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(logsetup, "LOG_FILE", tmp_path / "logs" / "bot.log")
    antes = logging.getLogger().handlers[:]
    try:
        logsetup.setup_logging()
        rotativos = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, RotatingFileHandler) and h not in antes
        ]
        assert rotativos
    finally:
        for h in logging.getLogger().handlers[:]:
            if h not in antes:
                logging.getLogger().removeHandler(h)
