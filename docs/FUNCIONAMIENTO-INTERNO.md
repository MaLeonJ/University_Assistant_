---
tags: [proyecto, documentacion, arquitectura]
fecha: 2026-08-23
---

# 🔬 Funcionamiento interno — Asistente Universitario

> Documentación técnica completa del programa: librerías, módulos, funciones,
> flujos de datos, persistencia y decisiones de diseño. Si vas a tocar código,
> lee esto primero. Complementa a `ARQUITECTURA.md` (que es la vista de alto nivel).

---

## 1. Visión general

El sistema es un bot personal de Telegram que convierte mensajes en
investigaciones académicas documentadas:

```
mensaje/foto ──▶ parser ──▶ searcher (web) ──▶ llm (IA) ──▶ writer (.md) ──▶ Telegram
                                    │                            │
                                    └── usage (cuota) ◀──────────┘
                                                                 └──▶ syncer ──▶ Obsidian
```

Proceso único, sin base de datos servidor: todo estado vive en archivos
(`documentos/`, `data/usage.json`, `logs/bot.log`). Un solo usuario autorizado;
todo lo demás se ignora silenciosamente.

---

## 2. Librerías externas (por qué cada una)

### python-telegram-bot `==22.8`
Framework async para bots. Conceptos que usa el proyecto:

| Concepto | Rol aquí |
|---|---|
| `Application` | Objeto central; se construye con `Application.builder().token(TOKEN).build()` |
| Polling (`run_polling`) | El bot pregunta a los servidores de Telegram si hay updates (long polling HTTP). No requiere IP pública ni webhook |
| `Update` | Envoltorio de todo evento entrante; expone `.message`, `.callback_query`, `.effective_user` |
| `CommandHandler` | Dispara con `/comando`; pasa `(update, context)` |
| `MessageHandler(filters)` | Captura texto (`filters.TEXT & ~filters.COMMAND`) o fotos (`filters.PHOTO`) |
| `CallbackQueryHandler` | Captura toques en botones inline (`callback_data` string) |
| `add_error_handler(fn)` | Red de seguridad: toda excepción no manejada en un handler cae en `on_error()` |
| `reply_text(parse_mode="Markdown")` | Respuestas con formato |

Detalle importante: PTB tipa `update.message` y `update.callback_query` como
opcionales (`Message | None`) aunque los filtros garanticen lo contrario; el
código documenta esa invariante con `assert`.

### ddgs `==9.15.0`
Cliente de búsqueda DuckDuckGo sin API key. Uso:
```python
with DDGS() as ddgs:  # context manager (sesión HTTP)
    ddgs.text(f"{tema} explicación", max_results=N)
```
Devuelve iterables de dicts con claves `title`, `href`, `body` — el proyecto los
normaliza a `{title, url, snippet}`.

### google-genai `==2.19.0`
SDK oficial de Google Gemini. Se importa *dentro* de la función (import perezoso):
```python
client = genai.Client(api_key=...)        # cliente REST síncrono
client.models.generate_content(
    model=AI_MODEL,
    contents=[prompt] o [prompt, types.Part.from_bytes(data, mime)],
    config={"system_instruction": ...},
)
```
`Part.from_bytes` es lo que habilita visión (leer fotos) sin OCR externo.

### openai `==3.3.1`
Cliente estándar OpenAI. La gracia: sirve para **cualquier API compatible**
cambiando `base_url`. Aquí apunta a OpenRouter:
```python
OpenAI(api_key=..., base_url="https://openrouter.ai/api/v1")
.chat.completions.create(model=..., messages=[{role, content}, ...])
```
Para visión, el `content` del mensaje usuario es una lista:
`[{"type": "text", ...}, {"type": "image_url", "image_url": {"url": "data:<mime>;base64,<b64>"}}]`.

### python-dotenv `==1.2.3`
`load_dotenv(BASE_DIR / ".env")` con ruta explícita — funciona sin importar el
directorio desde donde se lance `python main.py`.

### Stdlib protagonista
- `asyncio.to_thread` — corre funciones bloqueantes (IA, descarga de fotos) sin trabar el event loop de PTB.
- `logging.handlers.RotatingFileHandler` — log a archivo que rota por tamaño.
- `hashlib.md5` + `shutil.copy2` — comparación y copia incremental al vault.
- `pathlib.Path` — todas las rutas; `re` — parseo y extracción de errores del log.
- `json` — contador diario y respuesta estructurada de la visión.

---

## 3. Mapa de módulos y reglas de dependencia

```
main.py ──────────────▶ bot.py (orquestador Telegram)
                           │
      ┌────────┬──────────┼───────────┬────────────┐
      ▼        ▼          ▼           ▼            ▼
   parser   pipeline   writer      syncer      (comandos)
               │          │                        │
      ┌────────┴─────┐    │                        ▼
      ▼              ▼    │                     (config)
  searcher       analyzer │
      │              │    │
      └──▶ cache ◀───┘    │
             │            │
             ▼            ▼
          (config)      llm.py ──▶ gemini / openai-compat (+ fallback, breaker)
                               │
                               ▼
                            usage.py (registra consumo)
  indexer.py ◀── documentos/ (FTS5; lo consultan /buscar y exporter)
  exporter.py ◀── pandoc (binario externo opcional)
  logsetup.py ◀── bot.py (al importar configura logging global)
  config.py ◀── TODOS (única fuente de verdad de rutas/tokens/env)
```

Reglas: `config.py` no depende de nadie; `llm.py` no sabe de prompts ni de
Telegram; `analyzer.py` conoce prompts + llm + usage; `pipeline.py` orquesta
búsqueda+cache+análisis por tema; `bot.py` solo traduce Telegram ↔ pipeline.

---

## 4. Arranque: ciclo de vida

1. `python main.py` → importa `bot.main()` y lo ejecuta.
2. Al **importar** `asistente.bot` ocurren dos efectos: `setup_logging()`
   (crea `logs/bot.log`, adjunta handler rotativo + consola a la raíz, baja
   `httpx` a WARNING) y se cargan todas las constantes de `config`.
3. `main()`: `validate()` revisa TELEGRAM_TOKEN, AI_API_KEY, AUTHORIZED_USER_ID
   y coherencia AI_PROVIDER/AI_MODEL. Si falta algo → `SystemExit` con lista clara.
4. Construcción de la `Application` y registro de **10 handlers** en orden:
   7 comandos (`start help menu docs sync uso logs`), 1 `CallbackQueryHandler`,
   2 `MessageHandler` (texto-no-comando, foto) y 1 error handler.
5. `run_polling()` entra en bucle infinito: getUpdates → despachar → repetir.
   Terminar con Ctrl+C; PTB cierra limpio.

⚠️ Dos instancias simultáneas → Telegram responde **409 Conflict**. Por eso
existe el hábito `pkill -f "python main.py"` antes de relanzar.

---

## 5. Flujo completo: mensaje de texto

### 5.1 Recepción y autorización
`handle_message(update, ctx)`: primero `authorized(update)` — compara
`update.effective_user.id` con `AUTHORIZED_USER_ID` (si es `0`, acepta a
cualquiera: útil para tests). No autorizado → return silencioso.

### 5.2 Parseo — `parser.parse_message(text)`
- Vacío → `None` (el bot responde con la ayuda).
- Con `:` → `head:body`: título = `head.strip(" .")`, temas = partir `body` por
  la regex `SEPARATORS = [,;\n]+`, limpiando `" .-"` de cada tema.
  Título vacío o cero temas → `None`.
- Sin `:` → separar igual; un solo tema ⇒ título = primeras 6 palabras;
  varios ⇒ título genérico `"Investigación"`.

`slugify(text)`: minúsculas → tabla áéíóúñ→aeioun → `re.sub('[^a-z0-9]+' , '-')`
→ trim de guiones → máximo 60 chars → fallback `"documento"`.

### 5.3 Investigación — `bot.research(update, title, topics)` → `pipeline.research_topics`
Avisa al usuario y delega en el **pipeline async**: todos los temas corren
**en paralelo** (`asyncio.gather`); cada tema ejecuta su secuencia en un thread
de sistema (`asyncio.to_thread`) porque ddgs, SQLite y los SDK de IA son
bloqueantes. Por tema:

**a) Búsqueda con cache — `cache.get_search` / `searcher.search_topic`**
Si hay entrada vigente en `data/cache.db` (TTL `CACHE_TTL_DAYS`, default 7
días) se reutiliza sin tocar la red. Si no, consulta literal
`"{topic} explicación"` (el sufijo mejora resultados didácticos). Hasta
`RETRIES=3` intentos; entre fallo y fallo duerme `2*intento` s (backoff).
Un resultado exitoso se guarda en cache. Si todo falla → lista vacía (no lanza).

**b) Síntesis con cache — `cache.analysis_key` / `analyzer.analyze_topic`**
La clave del análisis es `sha256(proveedor|modelo|tema|URLs ordenadas)`: si
cambian las fuentes o el modelo, cambia la clave y se regenera. Sin acierto,
se llama a `analyze_topic`: sin resultados → nota informativa (no gasta IA);
con resultados arma la lista `- **título** — snippet (URL: url)` y la inyecta
en `PROMPT` (instrucciones: definición/contexto, conceptos clave con cursivas
y término en inglés, ejemplos concretos/código, aplicaciones, tabla final,
600–1000 palabras, español, sin enlaces en el cuerpo), bajo `SYSTEM_PROMPT`
(persona didáctica, no inventar). Solo si hay texto real registra consumo
(`register_call()`, protegido con lock por los threads). Excepción o texto
vacío → `_fallback()` con snippets crudos; los fallbacks **no se cachean**
(`is_fallback`).

### 5.4 Escritura — `writer.write_document(title, topics, sections, results_by_topic)`
Ruta: `documentos/<YYYY>/<MM-mes>/<DD_HH-MM>_<slug>.md`; si existe, sufijo
`-2`, `-3`… Contenido:
1. Frontmatter YAML (`tags: [universidad, investigacion]`, `fecha`, `hora`)
2. `# Título` + párrafo introductorio + línea de firma
3. `## Índice` numerado de temas
4. Por tema: `## N. tema` + sección generada + separador
5. `## Fuentes consultadas` — `_sources_section()` numera URLs **deduplicadas
   globalmente** (set `seen`, chequeado al insertar), agrupadas por tema;
   sin fuentes → sección omitida.

Después `update_index(dir_mes)` **regenera desde disco** `00_Índice.md`:
frontmatter propio, total de docs, bloque ```dataview``` (TABLE hora/fecha FROM
#investigacion WHERE file.folder = this.file.folder) y wikilinks
`[[stem|Título]]` ordenados descendente. Como se reconstruye leyendo la
carpeta (ignorando el propio índice), borrar un documento lo saca del índice
en la próxima escritura: auto-sanable.

Helpers de lectura: `_doc_title()` primera línea `# ` o stem; `_hora()` valor
de frontmatter `hora:` con `-`→`:`.

### 5.5 Respuesta
Reply con nombre del archivo + `used/limit` de hoy (`usage.get_usage`) y menú
inline (`show_menu`).

---

## 6. Flujo completo: foto 📷

`handle_photo`:
1. Guardia de autorización.
2. **Atajo barato**: si el caption contiene `:`, se intenta `parse_message`;
   si produce título+temas, va directo a `research` (cero cuota de visión).
3. Sin caption útil: avisa, toma la foto más grande (`photo[-1]` — Telegram
   entrega varias resoluciones), `await photo.get_file()` y
   `download_as_bytearray()` → `bytes`.
4. `asyncio.to_thread(extract_topics_from_image, data, "image/jpeg")`: la
   llamada HTTP de Gemini/OpenRouter es bloqueante; `to_thread` evita congelar
   el event loop mientras tanto.
5. `extract_topics_from_image` envía `VISION_PROMPT` pidiendo **JSON estricto**
   `{"title": ..., "topics": [...]}`, le quita fences ```json si vienen, hace
   `json.loads`, valida no-vacío, registra consumo y devuelve tupla; cualquier
   fallo → `None` → mensaje de error amable al usuario.
6. Éxito: confirma lo leído y entra a `research` normal.

---

## 7. Capa de IA — `llm.py`

Función única pública:
```python
generate(prompt: str, *, system: str, images: list[tuple[bytes, str]] | None = None) -> str
```

**Cadena de modelos con circuit breaker.** `generate()` arma la lista de
candidatos `[AI_MODEL, *AI_FALLBACK_MODELS]` (deduplicada, orden estable) y la
recorre: el primer modelo que responda gana. Cada modelo tiene su
`CircuitBreaker` (umbral `BREAKER_THRESHOLD=3`, enfriamiento
`BREAKER_COOLDOWN=300 s`, reloj `time.monotonic`): tras 3 fallos consecutivos
queda "abierto" y se omite sin gastar red hasta que pase el enfriamiento; un
éxito reinicia fallos y cierra el breaker. Si todos fallan o están abiertos →
se relanza el último error (o `RuntimeError("Ningún modelo disponible…")`).
`reset_breakers()` existe para tests.

Dispatch por `config.AI_PROVIDER` (validado **antes** de la cadena):
- `"gemini"` → `_generate_gemini` (SDK propio; imágenes vía
  `types.Part.from_bytes`; `system_instruction` en config; silencia el warning
  AFC del SDK bajando el logger `google_genai` a ERROR).
- `"openrouter"` → `_generate_openai_compatible` (cliente `openai` con
  `base_url` de `OPENAI_BASE_URLS`; imágenes como data-URI base64;
  envía `extra_body={"reasoning": {"enabled": False}}` para que los modelos de
  razonamiento no filtren su cadena de pensamiento en `content`).
- Otro → `ValueError`. Sin `AI_API_KEY` → `RuntimeError`.

Detalles finos:
- Cliente OpenAI es **singleton** (`_openai_client` global + fábrica perezosa):
  una sola conexión reutilizada por la vida del proceso.
- `content` tipado `str | list[dict[str, Any]]`: string plano cuando no hay
  imágenes (máxima compatibilidad), lista multimodal cuando las hay.
- La función **propaga excepciones**: quién decide qué hacer ante fallo es
  `analyzer` (política de fallback), no el transporte.

Cambiar de proveedor = editar 2-3 líneas de `.env`. Groq existió en esta capa
y se retiró (bloqueo regional desde Venezuela).

---

## 8. Interfaz de Telegram

### Menú inline
`MENU_KEYBOARD` — 5 botones con `callback_data`: `docs`, `uso`, `sync`,
`logs`, `ayuda`. `button(update, ctx)` hace `query.answer()` y enruta por ese
string; cada rama llama a la misma función pura que el comando equivalente
(`docs_text()`, `format_usage()`, …) y edita el mensaje original
(`edit_message_text`) manteniendo el teclado.

### Comandos
| Comando | Función | Fuente de datos |
|---|---|---|
| `/start`, `/help` | `start` | `HELP_TEXT` + menú |
| `/menu` | `menu` → `show_menu` | teclado |
| `/docs` | `docs_command` | `docs_text()` sobre disco real |
| `/buscar` | `buscar_command` | `indexer.sync_index()` + `indexer.search()` (FTS5) |
| `/exportar` | `exportar_command` | `exporter.resolver_documento()` + pandoc |
| `/stats` | `stats_command` | writer + usage + cache.stats() |
| `/sync` | `sync_command` | `sync_documents()` |
| `/uso` | `uso_command` | `format_usage()` |
| `/logs` | `logs_command` | `logs_text()` sobre `bot.log` |

### Búsqueda full-text — `indexer.py`
Índice SQLite FTS5 (`data/search.db`, tokenizador `unicode61
remove_diacritics 2`). `sync_index()` compara sha256 por archivo: alta,
actualización o baja incremental; ignora los índices mensuales. `search()`
convierte la consulta en términos citados con prefijo (`"derivada"*`): sin
acentos da igual y «derivada» encuentra «derivadas»; palabras reservadas de
FTS5 (OR/AND/NOT) van dentro de la cita, así que nunca rompen el parser.
Los snippets se resaltan con «…» y el bot escapa HTML antes de enviarlos.

### Exportación — `exporter.py`
`resolver_documento(termino)`: sin términos → documento más reciente; con
términos → primer resultado del índice full-text. `exportar(md, formato)`
ejecuta pandoc con timeout de 120 s. Para PDF usa XeLaTeX explícito y
convierte una **copia temporal sin emojis** (LaTeX no tiene esos glifos;
los símbolos matemáticos ≤ ≈ ∈ se conservan). Sin pandoc instalado lanza
`RuntimeError` con las instrucciones de instalación. Los archivos exportados
quedan junto al `.md` original en `documentos/`.

### Conversación de fotos — `bot.foto_entry` / `foto_toggle`
`ConversationHandler` con un solo estado intermedio (`SELECCION`):
- **Entrada** (`MessageHandler PHOTO`): si el caption trae `:` va directo al
  pipeline (atajo barato); si no, visión extrae título+temas y muestra un
  teclado multi-selección (un botón por tema, máx `MAX_TEMAS_FOTO=12`).
- **Toggles** (`CallbackQueryHandler pattern ^ft:`): `ft:N` alterna el tema
  (re-dibuja el teclado con ✅), `ft:go` genera solo lo marcado (exige ≥1) y
  `ft:no` cancela. Las selecciones viven en `context.user_data["foto"]`.
- En estado de selección, una foto nueva reinicia la selección (la entrada
  también está registrada dentro del estado).
- **Fallback**: `/cancel` limpia el estado en cualquier momento. Estado
  inexistente (bot reiniciado) → aviso de expiración.

### CLI — `cli.py` (typer)
Comando global `asistente` (entry point en pyproject: `asistente.cli:app`):
`investigar`, `buscar [-l N]`, `exportar FORMATO [TERMINO]`, `uso`, `stats`.
Reutiliza parser/pipeline/writer/indexer/exporter sin duplicar nada; `uso`
imprime el formato de Telegram desmarcado (`_plano`). Tests con
`typer.testing.CliRunner`.

`docs_text()`: `writer.list_months()` recorre años/meses descendente saltando
meses vacíos; muestra máx `MAX_DOCS_MOSTRADOS=12` con tamaño KB y nota
"…y N más". `month_label()` da formato "Agosto 2026".

### Observabilidad — `/logs`
`_recent_error_blocks()` lee `logs/bot.log` (OSError → []), detecta cabeceras
con regex `^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ `, filtra nivel `ERROR`
(campo 3 del split) y agrupa las líneas siguientes (tracebacks sin timestamp,
tope de 40 líneas) como parte del bloque. Devuelve los últimos 10 bloques.
`logs_text()` los renderiza más-recientes-primero dentro de fences ``` hasta
~3500 chars. Sin errores → mensaje verde. **Los errores nunca se envían solos
al chat**: se consultan bajo demanda (decisión de diseño explícita).

### Error handler global — `on_error`
Contrato PTB: recibe `(update, context)` donde `context.error` es la excepción.
Hace `logger.error(..., exc_info=context.error)` → traceback completo al
archivo rotativo. El bot sigue vivo; el usuario ni se entera salvo porque el
comando afectado no respondió.

---

## 9. Sincronización — `syncer.py`

`sync_documents()`:
1. Sin `documentos/` → ceros.
2. `mkdir` del destino (vault).
3. Para cada `*.md` recursivo ordenado: ruta relativa → destino espejo.
4. `_igual(src, dst)`: primero tamaño (`st_size`) — rechazo barato; luego
   **MD5** en chunks de 64 KB. ¿Por qué no fechas? El vault vive en un montaje
   **rclone/GDrive FUSE que no preserva mtimes**; comparar fechas daría falsos
   positivos/negativos. Hash es la única verdad.
5. Distinto → `shutil.copy2`. Contadores `nuevos` / `actualizados`.
6. **Nunca borra** del vault aunque el origen desaparezca (protección
   deliberada contra pérdida accidental).

`sync_text(resultado)` formatea el reporte con destino incluido.

---

## 10. Persistencia y estado

| Archivo | Quién escribe | Formato / política |
|---|---|---|
| `documentos/**.md` | writer | jerárquico año/mes, frontmatter, índice mensual |
| `data/usage.json` | usage | `{"date": "YYYY-MM-DD", "count": N}`; si la fecha difiere de hoy, `_load()` descarta → reset diario automático; escrituras protegidas con lock (threads del pipeline) |
| `data/cache.db` | cache | SQLite: tabla `searches` (TTL) y `analyses` (clave contenido); conexiones de vida corta con `busy_timeout=5000`; si la BD está corrupta degrada sin cache, sin romper |
| `logs/bot.log` (+`.1`…`.3`) | logsetup | texto plano, rota a 5 MB, conserva 3 respaldos |
| `.env` | humano | tokens; jamás commiteado |

El contador es **local y aproximado**: el límite real lo impone el proveedor.

---

## 11. Configuración — `config.py`

Resuelve `BASE_DIR` desde la ubicación del propio archivo (independiente del
cwd). Variables (todas con default sensato):

| Variable | Default | Efecto |
|---|---|---|
| `TELEGRAM_TOKEN` | — | requerido |
| `AUTHORIZED_USER_ID` | 0 (=todos) | ID Telegram autorizado |
| `AI_PROVIDER` | gemini | `gemini \| openrouter` (`VALID_PROVIDERS`) |
| `AI_API_KEY` | — | requerida |
| `AI_MODEL` | según proveedor | override puntual |
| `AI_FALLBACK_MODELS` | vacío | modelos de respaldo (coma); orden = prioridad |
| `CACHE_TTL_DAYS` | 7 | vigencia del cache de búsquedas |
| `AI_DAILY_LIMIT` | 100 | solo cosmético (/uso) |
| `SEARCH_MAX_RESULTS` | 5 | fuentes por tema |
| `OUTPUT_DIR` / `OBSIDIAN_DIR` / `DATA_DIR` / `LOG_DIR` | rutas del repo/vault | redirigibles (clave para tests) |

Defaults de modelo: `gemini-3.5-flash` · `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`.
Los catálogos gratuitos rotan; con `AI_FALLBACK_MODELS` la cadena salta sola a
un modelo de respaldo si el principal muere o se satura.

---

## 12. Calidad: cómo se prueba este código

Principio: **lógica pura directo; bordes con stubs**.

| Módulo testeado | Estrategia |
|---|---|
| parser, writer, syncer, usage | funciones puras sobre carpetas temporales (`tmp_path`) — nada de mocks |
| searcher | clase `FakeDDGS` con lista de efectos (excepción o datos); `time.sleep` parcheado |
| cache | SQLite en `tmp_path` (fixture autouse `cache_db_tmp`); roundtrips, TTL, claves, BD corrupta |
| indexer | biblioteca temporal; sync incremental (altas/actualizaciones/bajas), búsqueda con acentos/plurales, consultas maliciosas, límites |
| exporter | `subprocess.run` y `pandoc_disponible` parcheados; éxito/falla/timeout, resolución por recencia y por índice |
| pipeline | `search_topic`/`analyze_topic` fakes; orden, paralelismo medido por reloj, propagación de `max_results`, acierto de cache y no-cacheo de fallbacks |
| llm | stubs del SDK: `StubCompletions`/`ScriptedCompletions` con efectos ordenados; breaker probado con umbral/cooldown/parcheo de `time.monotonic`; `google.genai.Client` reemplazado por stub que captura model/contents/config |
| analyzer | `generate` y `register_call` monkeyparcheados; se prueban éxito, vacío, excepción y JSON de visión |
| config.validate | combinaciones de env incompleta/inválida |
| bot | fakes `FakeMessage/FakeQuery/FakeChat` (grabadoras de llamadas); handlers async ejecutados con `asyncio.run`; pipeline de investigación parcheado |

Fixtures (`tests/conftest.py`):
- `output_dirs` — redirige `OUTPUT_DIR`/`OBSIDIAN_DIR` de writer y syncer.
- `usage_file` / `write_usage` — contador temporal.
- `cache_db_tmp` (autouse) — cache SQLite en `tmp_path`; ningún test toca el
  `data/cache.db` real.
- autouse `sin_log_a_archivo` — desmonta el RotatingFileHandler durante los
  tests (no contaminan tu `bot.log` real).
- En test_bot, autouse además neutraliza `AUTHORIZED_USER_ID=0` (el `.env`
  real no debe filtrarse en las pruebas).

Estado: **154 tests, 97% cobertura con ramas**, ruff (lint+format) y mypy
estrictos en `asistente/` y `tests/`, hooks pre-commit (higiene + ruff).
La suite cazó dos bugs reales: dedup de fuentes solo entre temas (no
intra-tema) y la carrera de escritura de `usage.json` al paralelizar.

Comandos:
```bash
pytest --cov                 # suite + cobertura
ruff check . && ruff format .
mypy asistente/ tests/
pre-commit run --all-files
```

---

## 13. Decisiones técnicas y sus razones (resumen honesto)

- **Polling, no webhook** — uso personal local: cero infraestructura.
- **Paralelo con threads, no async nativo** — ddgs, sqlite3 y los SDK de IA son
  bloqueantes: `to_thread` los aprovecha desde el event loop de PTB sin
  reescribir nada; `gather` mantiene el orden de secciones.
- **Cache con clave de contenido, no solo tema** — un análisis se reutiliza
  mientras no cambien fuentes ni modelo; así nunca sirve contenido viejo.
- **MD5, no mtimes** — consecuencia directa del montaje rclone.
- **Fallback en cascada** — búsqueda vacía o IA caída nunca rompen: el
  documento sale con snippets crudos y queda marcado.
- **Capa multi-proveedor** — anti lock-in y portátil de CV; Groq retirado por
  geo-bloqueo, la abstracción hizo el cambio trivial.
- **Errores al archivo, consulta por demanda** — el bot no spamea tracebacks
  al chat; `/logs` es la ventana.
- **Índice regenerado desde disco** — fuente única de verdad = filesystem;
  imposible que el índice mienta.

## 14. Límites actuales (roadmap activo)

Fases 1-3 completadas. Fase 4 completa: ✅ `/buscar` FTS5, ✅ export
PDF/DOCX, ✅ `/stats`, ✅ conversación foto→botones, ✅ CLI typer.
Multi-usuario descartado por decisión de Leon (herramienta personal).
Fase 5: systemd/Docker, README final con GIF + badges CI, changelog.

## 15. Orden sugerido de lectura del código

1. `config.py` → 2. `parser.py` → 3. `searcher.py` → 4. `llm.py` →
5. `analyzer.py` → 6. `cache.py` → 7. `pipeline.py` → 8. `writer.py` →
9. `syncer.py` → 10. `usage.py` → 11. `logsetup.py` → 12. `bot.py`
(el más grande, deja el orquestador para el final).
